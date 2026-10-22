# -*- coding: utf-8 -*-
"""composite.py —— 综合推单：把「赔率（盘口）」「数据模型」「两队数据」三样东西合成一个综合概率。

为什么要合：
  · 赔率/盘口里装着伤停、首发、资金这些我们看不到的信息，单看准头通常最好；
  · 数据模型只看两队的比分走势，信息少，但和赔率是两路独立的证据，掺一部分进去能纠偏；
  · 两队数据（近况、伤停）只做很小的加减，因为模型分已经用过其中一部分，不重复算。

怎么合（足球）：
  1. 赔率这边：北单（或竞足）的让球 SP 去掉庄家抽水，得到「让球胜/平/负」三个概率（线 L）；
  2. 模型这边：同一条让球线 L 上的「胜/平/负」概率（match_model 存的「让球分布表」）；
  3. 对数加权平均（几何平均）再归一：综合 ∝ 赔率^(1-w) × 模型^w，w = 模型占比（默认 0.30，rules.json 里「模型占比」可改）；
  4. 两队数据：支持 +1.5 个百分点、部分支持不动、不支持 −3 个百分点（不支持的单场本来就会被撤，所以基本看不到）；
  5. 竞足「胜平负」要的是「直接赢球」概率：让球线 0 就是综合里的胜；让 1 球 = 综合的「让球胜 + 让球平」；
     让 2 球及以上：把净胜球数当正态分布，用「让球胜」「让球胜+平」反推，再算净胜 ≥1 球的概率。
  模型回测没过关、或这场没有模型数据 → 只用赔率（+两队数据），帖子里不写「综合」。

篮球：竞彩让分盘就是「预计净胜分」，模型算的净胜分按同样的占比合并，再用正态分布换算成赢球概率。

综合概率只是更好的概率估计，不是命中保证；战绩统计页会按「综合概率分档」逐档核对到底中了多少，没区分度就自动不再显示百分比。
占比 w 也会随历史战绩慢慢校正（样本够多、且前后两半都更好才动，并且往默认值靠拢），记在 composite_weights.json。
纯标准库。
"""
from __future__ import annotations

import json
import math
from datetime import datetime
from pathlib import Path
from statistics import NormalDist
from typing import Any, Dict, List, Optional, Tuple

import layout as L

__version__ = "1.1"

W_MDL = 0.30                    # 模型占比的默认值
W_MIN, W_MAX = 0.0, 0.60        # 自动校正时占比的范围
DATA_TILT = {"support": 0.015, "mixed": 0.0, "against": -0.03}     # 两队数据对综合概率的加减（概率点）
DIV_GAP = 0.15                  # 赔率和模型对「推荐方」的概率差 ≥ 这个，标「分歧」
SIGMA_BB = 11.5                 # 篮球净胜分的默认标准差（模型没给时）
WEIGHT_FILE = "composite_weights.json"
FIT_MIN_N = 80                  # 校正占比：已出结果且赔率、模型概率都记着的推单至少这么多
FIT_MIN_GAIN = 0.002            # 对数损失要比默认占比至少好这么多
FIT_PRIOR_N = 120               # 往默认值靠拢的「虚拟样本数」：样本越多，越相信自己拟合出来的


# ───────────────────────────── 基础数学 ─────────────────────────────
def pool3(a: Tuple[float, float, float], b: Tuple[float, float, float], w: float) -> Tuple[float, float, float]:
    """对数加权平均：a^(1-w) × b^w，归一。w=0 就是 a，w=1 就是 b。"""
    w = max(0.0, min(1.0, float(w)))
    q = [max(1e-9, a[i]) ** (1.0 - w) * max(1e-9, b[i]) ** w for i in range(3)]
    t = sum(q)
    return (q[0] / t, q[1] / t, q[2] / t)


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _clip(x: float, lo: float = 0.02, hi: float = 0.97) -> float:
    return max(lo, min(hi, x))


def _logit(p: float) -> float:
    p = max(1e-6, min(1 - 1e-6, p))
    return math.log(p / (1 - p))


def _sig(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


# ───────────────────────────── 足球 ─────────────────────────────
def model_line(mdl: Optional[Dict[str, Any]], line: float) -> Optional[Tuple[float, float, float]]:
    """模型在让球线 line 上的 (让球胜, 平, 负) 概率。mdl 没过回测、没这条线 → None。
    优先用 match_model 存的「让球分布表」ln；老记录没有 ln 时：0 线用卡片上的胜平负，其余线用预计进球 lh/la 现算（独立泊松，没校准）。"""
    if not (isinstance(mdl, dict) and mdl.get("ok")):
        return None
    try:
        li = int(round(float(line)))
    except (TypeError, ValueError):
        return None
    if abs(float(line) - li) > 1e-9:
        return None
    ln = mdl.get("ln")
    if isinstance(ln, dict) and str(li) in ln:
        v = ln[str(li)]
        if isinstance(v, (list, tuple)) and len(v) == 3:
            return (float(v[0]), float(v[1]), float(v[2]))
    if li == 0:                                    # 老记录没有分布表：0 线就是卡片上（校准后）的胜平负
        try:
            t = (float(mdl["ph"]), float(mdl["pd"]), float(mdl["pa"]))
            if all(x >= 0 for x in t) and 0.98 <= sum(t) <= 1.02:
                return (t[0] / sum(t), t[1] / sum(t), t[2] / sum(t))
        except (KeyError, TypeError, ValueError):
            pass
    try:
        import match_model as MM
        g = MM.poisson_grid(float(mdl["lh"]), float(mdl["la"]))
        v = MM.line_table(g, (li,))[str(li)]
        return (v[0], v[1], v[2])
    except Exception:  # noqa: BLE001
        return None


def plain_win(vec: Tuple[float, float, float], line: float, fav_home: bool) -> float:
    """热门方「直接赢球」（胜平负里的胜）的概率，从它在让球线 line 上的 (让球胜, 平, 负) 三个概率换算：
    线 0：就是热门的胜；让 1 球：让球胜 + 让球平（赢 1 球正好走水）；让 2 球及以上：把净胜球数当正态分布，
    用「让球胜」「让球胜+平」两个数反推出均值和离散度，再算净胜 ≥1 球的概率（算不出合理的值就退回「让球胜+平」这个保守下限）。"""
    lw, ld = (vec[0], vec[1]) if fav_home else (vec[2], vec[1])
    k = abs(int(round(line)))
    if k == 0:
        return lw
    if k == 1:
        return lw + ld
    a, b = lw, lw + ld
    try:
        if not (0.001 <= a < b <= 0.999):
            raise ValueError("概率不在合理范围")
        nd = NormalDist()
        z1, z2 = nd.inv_cdf(1 - a), nd.inv_cdf(1 - b)
        sigma = 1.0 / (z1 - z2)
        if not (0.8 <= sigma <= 3.2):
            raise ValueError("离散度不合理")
        mu = k + 0.5 - z1 * sigma
        return max(b, min(0.995, 1.0 - nd.cdf((0.5 - mu) / sigma)))
    except (ValueError, ZeroDivisionError):
        return b


def football(info: Dict[str, Any], mdl: Optional[Dict[str, Any]], cmp_v: Optional[str], kind: str, w: float = W_MDL,
             line_bonus: float = 0.0) -> Optional[Dict[str, Any]]:
    """一场足球推荐的综合概率。
    info：gen_tips.analyse() 的结果（p=赔率三个概率、L=让球线、fav='3'/'0'）；
    kind："line" = 让球胜/负（推荐方赢盘）；"plain" = 胜平负的胜/负（推荐方直接赢球）。
    返回 {cp 这条推荐的综合概率, pm 赔率概率, pq 模型概率(或 None), src 用了哪几路("赔模数"), div 分歧, flip 综合倾向反了,
          exact 赔率概率是不是精确值（让球线 |L|≤1 或让球推荐），adj 排序分（这一场热门直接赢球的综合概率，同一场的各个玩法用同一个）}。"""
    p, fav = info.get("p"), info.get("fav")
    if not p or fav not in ("3", "0"):
        return None
    line = float(info.get("L") or 0.0)
    fav_home = fav == "3"
    si, oi = (0, 2) if fav_home else (2, 0)
    p3 = (float(p[0]), float(p[1]), float(p[2]))
    q = model_line(mdl, line)
    src = "赔"
    if q is not None:
        pc = pool3(p3, q, w)
        src += "模"
    else:
        pc = p3
    lb_c = pc[si]
    q_side = q[si] if q is not None else None
    flip = pc[oi] > pc[si] + 0.02
    win_m, win_c = plain_win(p3, line, fav_home), plain_win(pc, line, fav_home)
    pq_plain = None
    if q is not None and isinstance(mdl, dict):
        try:
            pq_plain = float(mdl["ph"] if fav_home else mdl["pa"])
        except (KeyError, TypeError, ValueError):
            pq_plain = None
    if kind == "line":
        base, pm, pq, exact = lb_c, p3[si], q_side, True
    else:
        base, pm, pq, exact = win_c, win_m, pq_plain, abs(line) <= 1.0 + 1e-9
    tilt = DATA_TILT.get(cmp_v or "", None)
    if tilt is not None:
        src += "数"
    cp = _clip(base + (tilt or 0.0))
    div = bool(q is not None and (abs(q_side - p3[si]) >= DIV_GAP or flip))
    return {"cp": cp, "pm": _clip(pm), "pq": None if pq is None else _clip(pq), "src": src, "div": div, "flip": bool(flip), "exact": exact,
            "lb_c": lb_c, "win_c": win_c, "adj": _clip(win_c + (tilt or 0.0))}


# ───────────────────────────── 篮球 ─────────────────────────────
def basketball(line: Optional[float], home_side: bool, bbm: Optional[Dict[str, Any]], cmp_v: Optional[str], w: float = W_MDL) -> Optional[Dict[str, Any]]:
    """竞篮胜负（主胜/客胜）的综合概率。line = 竞彩让分（加在主队身上，-12.5 = 主队让 12.5 分，也就是盘口预计主队净胜 12.5 分）；
    bbm = 篮球模型：{ok, M 预计主队净胜, sm 净胜分标准差}。"""
    if line is None:
        return None
    sig = SIGMA_BB
    ok = isinstance(bbm, dict) and bbm.get("ok") and isinstance(bbm.get("M"), (int, float))
    if isinstance(bbm, dict) and isinstance(bbm.get("sm"), (int, float)) and bbm["sm"] > 3:
        sig = float(bbm["sm"])
    m_mkt = -float(line)
    ph_m = _phi((m_mkt - 0.5) / sig)
    src = "赔"
    if ok:
        m_c = (1 - w) * m_mkt + w * float(bbm["M"])
        ph_q = _phi((float(bbm["M"]) - 0.5) / sig)
        ph_c = _phi((m_c - 0.5) / sig)
        src += "模"
    else:
        ph_q, ph_c = None, ph_m
    side = (lambda x: x) if home_side else (lambda x: 1.0 - x)
    tilt = DATA_TILT.get(cmp_v or "", None)
    if tilt is not None:
        src += "数"
    cp = _clip(side(ph_c) + (tilt or 0.0), 0.02, 0.985)
    pm, pq = side(ph_m), (None if ph_q is None else side(ph_q))
    div = bool(pq is not None and abs(pq - pm) >= DIV_GAP)
    return {"cp": cp, "pm": _clip(pm, 0.02, 0.985), "pq": None if pq is None else _clip(pq, 0.02, 0.985), "src": src, "div": div,
            "flip": bool(pq is not None and (pq < 0.5) != (pm < 0.5)), "exact": True, "adj": cp}


def attach(p: Dict[str, Any], c: Optional[Dict[str, Any]]) -> None:
    """把综合概率写进推单（cp 综合概率；cp_m 赔率概率；cp_q 模型概率；cp_src 用了哪几路；cp_div 分歧；cp_x 赔率概率是不是精确值）。"""
    if not c:
        return
    p["cp"] = round(c["cp"], 3)
    p["cp_m"] = round(c["pm"], 3)
    if c.get("pq") is not None:
        p["cp_q"] = round(c["pq"], 3)
    p["cp_src"] = c["src"]
    if c.get("div"):
        p["cp_div"] = True
    if c.get("exact"):
        p["cp_x"] = True


def has_model(p: Dict[str, Any]) -> bool:
    """这条推单的综合概率里真的掺了模型（帖子里才写「综合」）。"""
    return "模" in str(p.get("cp_src") or "") and isinstance(p.get("cp"), (int, float))


# ───────────────────────────── 占比的自动校正 ─────────────────────────────
def _ll(rows: List[Tuple[float, float, int]], w: float) -> float:
    tot = 0.0
    for pm, pq, y in rows:
        pr = _sig((1 - w) * _logit(pm) + w * _logit(pq))
        pr = max(1e-6, min(1 - 1e-6, pr))
        tot += -math.log(pr if y else 1 - pr)
    return tot / max(1, len(rows))


from reliability import date_split, beijing_now


def fit_weight(hist: Dict[str, Any], prior: float = W_MDL) -> Dict[str, Any]:
    """用已经出结果的推单（记着赔率概率 cp_m 和模型概率 cp_q 的）校正「模型占比」。
    在 0～0.6 里找让对数损失最低的占比；要比默认占比至少好 FIT_MIN_GAIN、前一半和后一半时间里都更好，才改；
    改的时候也只往拟合值走一部分（样本越多走得越多）。返回 {w, n, changed, reason, ...}。"""
    rows: List[Tuple[str, float, float, int]] = []
    for p in (hist.get("picks") or {}).values():
        if "legs" in p or p.get("status") not in ("hit", "miss"):
            continue
        if not p.get("cp_x") or not isinstance(p.get("cp_m"), (int, float)) or not isinstance(p.get("cp_q"), (int, float)):
            continue
        rows.append((str(p.get("date") or ""), float(p["cp_m"]), float(p["cp_q"]), 1 if p["status"] == "hit" else 0))
    rows.sort(key=lambda r: r[0])
    out: Dict[str, Any] = {"w": prior, "n": len(rows), "changed": False, "date": beijing_now().strftime("%Y-%m-%d"), "validation_scheme": "chronological_date_60_20_20"}
    if len(rows) < FIT_MIN_N:
        out["reason"] = f"已出结果且带模型概率的推单只有 {len(rows)} 条（要 ≥{FIT_MIN_N}），模型占比先用默认 {prior:.0%}"
        return out
    train, val, test = date_split(rows, lambda r: r[0])
    out["split"] = {"train": len(train), "validation": len(val), "test": len(test)}
    if min(len(train), len(val), len(test)) < 20:
        out["reason"] = "按日期分段后的独立样本不足，保留默认权重"
        return out
    convert = lambda rs: [(r[1], r[2], r[3]) for r in rs]
    tr, va, te = map(convert, (train, val, test))
    grid = [i / 20 for i in range(0, int(W_MAX * 20) + 1)]
    best = min(grid, key=lambda w: _ll(tr, w))
    n = len(train)
    w = round(max(W_MIN, min(W_MAX, (n * best + FIT_PRIOR_N * prior) / (n + FIT_PRIOR_N))), 3)
    train_gain = _ll(tr, prior) - _ll(tr, w)
    val_gain = _ll(va, prior) - _ll(va, w)
    out.update(best=best, candidate=w, base_ll=round(_ll(tr, prior), 4),
               best_ll=round(_ll(tr, w), 4), validation_gain=round(val_gain, 4),
               validation_scheme="chronological_date_60_20_20")
    if train_gain < FIT_MIN_GAIN or val_gain < FIT_MIN_GAIN:
        out["reason"] = "候选权重未通过训练/验证段，保留默认权重"
        return out
    test_gain = _ll(te, prior) - _ll(te, w)
    out["test_gain"] = round(test_gain, 4)
    if test_gain >= FIT_MIN_GAIN:
        out.update(w=w, changed=True, reason=f"按日期独立验证与最终验收均通过，采用模型占比 {w:.0%}")
    else:
        out["reason"] = "候选权重未通过独立测试段，保留默认权重"
    return out


def load_weight(folder: Any, prior: float = W_MDL) -> Tuple[float, str]:
    """composite_weights.json 里校正好的占比（没有就是默认）。返回 (占比, 一句说明)。"""
    try:
        d = json.loads(L.p(Path(folder), WEIGHT_FILE).read_text(encoding="utf-8"))
        if d.get("validation_scheme") == "chronological_date_60_20_20" and d.get("changed") and isinstance(d.get("w"), (int, float)) and W_MIN <= d["w"] <= W_MAX:
            return float(d["w"]), f"模型占比 {d['w']:.0%}（按历史战绩校正过，{d.get('date', '')}）"
    except (OSError, ValueError, AttributeError):
        pass
    return prior, f"模型占比 {prior:.0%}（默认）"


def refit_and_save(folder: Any, hist: Dict[str, Any], prior: float = W_MDL, every_days: int = 7) -> Dict[str, Any]:
    """每周最多重拟合一次，结果存进 composite_weights.json。不抛异常。"""
    path = L.p(Path(folder), WEIGHT_FILE)
    today = beijing_now().strftime("%Y-%m-%d")
    try:
        old = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(old, dict) and old.get("date") and old.get("validation_scheme") == "chronological_date_60_20_20":
            gap = (datetime.strptime(today, "%Y-%m-%d") - datetime.strptime(str(old["date"]), "%Y-%m-%d")).days
            if 0 <= gap < every_days:
                return old
    except (OSError, ValueError, TypeError):
        pass
    res = fit_weight(hist, prior)
    try:
        path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
    except OSError:
        pass
    return res


# ───────────────────────────── 战绩核对 ─────────────────────────────
CP_BINS = ((0.0, 0.55, "55%以下"), (0.55, 0.65, "55–65%"), (0.65, 0.75, "65–75%"), (0.75, 1.01, "75%以上"))
CP_TRUST_MIN = 40               # 带综合概率、已出结果的单场至少这么多，才判断综合概率有没有区分度
CP_TRUST_BIN_MIN = 10           # 对比的「高档」和「低档」每档至少这么多条


def bucket_stats(hist: Dict[str, Any]) -> List[Dict[str, Any]]:
    """按综合概率分档：每档的条数、实际命中率、综合概率的平均值（看说的和实际差多少）。只算单场、已出结果、真的掺了模型的。"""
    out = [{"name": nm, "lo": lo, "hi": hi, "n": 0, "hit": 0, "sum": 0.0} for lo, hi, nm in CP_BINS]
    for p in (hist.get("picks") or {}).values():
        if "legs" in p or p.get("status") not in ("hit", "miss") or not has_model(p):
            continue
        if p.get("play") not in ("竞足", "北单", "竞篮") or p.get("market") not in ("胜平负", "让球胜平负", "胜负"):
            continue
        cp = float(p["cp"])
        for b in out:
            if b["lo"] <= cp < b["hi"]:
                b["n"] += 1
                b["hit"] += p["status"] == "hit"
                b["sum"] += cp
                break
    return out


def cp_trust(hist: Dict[str, Any]) -> Tuple[bool, str]:
    """综合概率在战绩里有没有区分度：样本够多时，最高那档的命中率不能比最低那档还低 3 个百分点以上，否则帖子里不再写百分比。样本不够 → 先显示。"""
    bs = [b for b in bucket_stats(hist) if b["n"] > 0]
    tot = sum(b["n"] for b in bs)
    if tot < CP_TRUST_MIN or len(bs) < 2:
        return True, ""
    hi, lo = bs[-1], bs[0]
    if hi["n"] < CP_TRUST_BIN_MIN or lo["n"] < CP_TRUST_BIN_MIN:
        return True, ""
    if hi["hit"] / hi["n"] < lo["hit"] / lo["n"] - 0.03:
        return False, (f"综合概率在战绩里暂时没有区分度（{hi['name']}的实际命中 {hi['hit'] / hi['n']:.0%}，反而比{lo['name']}的 {lo['hit'] / lo['n']:.0%} 低），"
                       "帖子里先不写综合百分比，数据多了会自动恢复。")
    return True, ""


def bucket_text(hist: Dict[str, Any]) -> str:
    bs = [b for b in bucket_stats(hist) if b["n"] > 0]
    if not bs:
        return ""
    parts = [f"{b['name']}：说 {b['sum'] / b['n']:.0%}→实际 {b['hit'] / b['n']:.0%}（{b['hit']}/{b['n']}）" for b in bs]
    return "综合概率分档核对（单场，已出结果）：" + "｜".join(parts)
