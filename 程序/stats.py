# -*- coding: utf-8 -*-
"""战绩统计中心：从 tips_history.json 里算各种命中率，纯标准库、不联网。

  compute(hist, today)        → 一大包统计数字（分玩法、近7日/近30日/累计、连红连黑、数据支持与否、防平、模型把握档、
                                 赔率档、联赛、★档、比分参考命中、未中归因、逐日）
  report_text(S)              → 「战绩统计.txt」的正文
  export_csv(hist, path)      → 每条已出结果的推单一行，Excel 能直接打开
  miss_reason(p)              → 一条没中的单场推荐，没中在哪（平局/爆冷/走盘/分差档位）
  miss_summary(items)         → 「未中归因：平局 2｜爆冷 1」这样一句（复盘帖里用）
  period_post(...)            → 周报/月报帖子（只写真实数字）

所有数字都来自历史里的真实结果，样本少时会直接标「样本少」，不下结论。"""
import csv
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Tuple

__version__ = "1.2"

SINGLE = ("竞足", "北单", "竞篮")
TRAD = ("胜负彩", "任九", "4场进球", "6场半全场")
COMBO = ("竞足串关", "北单串关", "竞篮串关")
PLAY_ORDER = ["竞足", "北单", "竞篮", "竞足串关", "北单串关", "竞篮串关", "胜负彩", "任九", "4场进球", "6场半全场"]
MIN_N = 8            # 一档样本少于这么多条，只列数字，不说「明显更好/更差」
BANDS_P = [(0.0, 0.45, "45%以下"), (0.45, 0.55, "45–55%"), (0.55, 0.65, "55–65%"), (0.65, 0.75, "65–75%"), (0.75, 1.01, "75%以上")]
BANDS_SP = [(0, 1.3, "SP 1.30以下"), (1.3, 1.5, "SP 1.30–1.50"), (1.5, 1.8, "SP 1.50–1.80"), (1.8, 2.2, "SP 1.80–2.20"), (2.2, 99, "SP 2.20以上")]


def _settled(p: Dict[str, Any]) -> bool:
    return p.get("status") in ("hit", "miss")


def pct(h: int, n: int) -> str:
    return f"{h / n:.0%}" if n else "—"


def frac(h: int, n: int) -> str:
    return f"{h}/{n}（{pct(h, n)}）" if n else "0/0"


def score_of(p: Dict[str, Any]) -> Optional[Tuple[int, int]]:
    """这条推单对应比赛的最终比分 (主, 客)。结果里没有比分（胜负彩只记了「胜」）就返回 None。竞篮的结果写的是「客:主」。"""
    m = re.match(r"\s*(\d+):(\d+)", str(p.get("result") or ""))
    if not m:
        return None
    a, b = int(m.group(1)), int(m.group(2))
    return (b, a) if p.get("play") == "竞篮" else (a, b)


def _line(p: Dict[str, Any]) -> float:
    try:
        return float(str(p.get("line") or "0").replace("＋", "+").replace("－", "-"))
    except ValueError:
        return 0.0


def miss_reason(p: Dict[str, Any]) -> Optional[str]:
    """没中的单场推荐：没中在哪。只给能从比分确定的原因，说不准的返回 None（不乱编）。
    平局｜爆冷（对方赢了）｜走盘（让球后刚好平）｜分差档位（竞篮方向对了、分差档没中）｜进球数（只对进球类）。"""
    if p.get("status") != "miss" or "legs" in p:
        return None
    sc = score_of(p)
    if sc is None:
        return None
    h, a = sc
    play, mk = p.get("play"), p.get("market")
    pk = list(p.get("pick") or [])
    if play == "竞篮":
        home_won = h > a
        if mk == "胜负":
            return "爆冷"
        want_home = any(str(x).startswith("主胜") for x in pk)
        return "分差档位" if home_won == want_home else "爆冷"
    if play in ("竞足", "北单"):
        if mk == "胜平负" and play == "竞足":
            if "胜" in pk:
                return "平局" if h == a else "爆冷" if h < a else None
            if "负" in pk:
                return "平局" if h == a else "爆冷" if h > a else None
            return None
        if mk in ("让球胜平负",) or play == "北单":
            L = _line(p)
            d = h + L - a
            if d == 0:
                return "走盘"
            if "胜" in pk and d < 0:
                return "爆冷"
            if "负" in pk and d > 0:
                return "爆冷"
    return None


def miss_counts(items: Iterable[Dict[str, Any]]) -> Counter:
    c: Counter = Counter()
    for p in items:
        r = miss_reason(p)
        if r:
            c[r] += 1
    return c


def miss_summary(items: Iterable[Dict[str, Any]]) -> str:
    """复盘帖里的一句：📉未中归因：平局 2｜爆冷 1（没有可归因的返回空串）。"""
    c = miss_counts(items)
    if not c:
        return ""
    order = ["平局", "爆冷", "走盘", "分差档位"]
    return "📉未中归因：" + "｜".join(f"{k} {c[k]}" for k in order if c.get(k))


def _pick_side_prob(p: Dict[str, Any]) -> Optional[float]:
    """推荐方向在「数据模型」里的概率（只对竞足胜平负的胜/负）。没有就 None。"""
    m = p.get("mdl")
    if not (isinstance(m, dict) and m.get("ok")):
        return None
    pk = list(p.get("pick") or [])
    if p.get("play") == "竞足" and p.get("market") == "胜平负":
        if pk == ["胜"] and "ph" in m:
            return float(m["ph"])
        if pk == ["负"] and "pa" in m:
            return float(m["pa"])
    return None


def _order_key(p: Dict[str, Any]) -> Tuple[str, str, str]:
    return (str(p.get("date") or ""), str(p.get("kick") or ""), str(p.get("id") or ""))


def _streaks(ps: List[Dict[str, Any]]) -> Dict[str, Any]:
    ps = sorted([p for p in ps if _settled(p)], key=_order_key)
    cur_s, cur_n, best_h, best_m, run_s, run_n = None, 0, 0, 0, None, 0
    for p in ps:
        s = p["status"]
        if s == run_s:
            run_n += 1
        else:
            run_s, run_n = s, 1
        if s == "hit":
            best_h = max(best_h, run_n)
        else:
            best_m = max(best_m, run_n)
    cur_s, cur_n = run_s, run_n
    return {"n": len(ps), "cur": (cur_s, cur_n) if cur_s else None, "max_hit": best_h, "max_miss": best_m}


def _hn(ps: Iterable[Dict[str, Any]]) -> List[int]:
    h = n = 0
    for p in ps:
        if _settled(p):
            n += 1
            h += p["status"] == "hit"
    return [h, n]


def _shift(day: str, delta: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=delta)).strftime("%Y-%m-%d")


def compute(hist: Dict[str, Any], today: str, draw_guard: float = 0.29) -> Dict[str, Any]:
    """today：今天的销售日（YYYY-MM-DD）。统计只用今天之前的推单（今天发的还没出结果）。"""
    picks = [p for p in (hist.get("picks") or {}).values() if p.get("date") and p["date"] < today]
    singles = [p for p in picks if p.get("play") in SINGLE and "legs" not in p]
    periods = {"近7日": (_shift(today, -7), today), "近30日": (_shift(today, -30), today), "累计": ("0000-00-00", today)}
    S: Dict[str, Any] = {"today": today, "draw_guard_thr": draw_guard, "n_picks": len(picks), "n_settled": sum(_settled(p) for p in picks)}
    dates = sorted({p["date"] for p in picks})
    S["first_date"], S["last_date"] = (dates[0], dates[-1]) if dates else ("", "")

    by_play: Dict[str, Dict[str, List[int]]] = {}
    for name, (lo, hi) in periods.items():
        d: Dict[str, List[int]] = {}
        for pl in PLAY_ORDER:
            ps = [p for p in picks if p.get("play") == pl and lo <= p["date"] < hi]
            h, n = _hn(ps)
            pend = sum(1 for p in ps if p.get("status") == "pending")
            if n or pend:
                d[pl] = [h, n, pend]
        by_play[name] = d
    S["by_play"] = by_play
    S["periods"] = {k: v for k, v in periods.items()}
    S["singles"] = {name: _hn([p for p in singles if lo <= p["date"] < hi]) for name, (lo, hi) in periods.items()}

    S["streaks"] = {pl: _streaks([p for p in singles if p["play"] == pl]) for pl in SINGLE}
    S["streaks"]["全部单场"] = _streaks(singles)

    # 按「两队数据」是否支持（数据把关的效果）
    by_cmp: Dict[str, List[int]] = {"support": [0, 0], "mixed": [0, 0], "none": [0, 0], "against": [0, 0], "nodata": [0, 0]}
    for p in singles:
        if not _settled(p):
            continue
        k = p.get("cmp_v") if p.get("cmp_v") in ("support", "mixed") else "none"
        by_cmp[k][1] += 1
        by_cmp[k][0] += p["status"] == "hit"
    for p in (hist.get("shadow") or {}).values():
        if p.get("status") in ("hit", "miss") and p.get("why") in ("against", "nodata") and p.get("date", "9") < today:
            by_cmp[p["why"]][1] += 1
            by_cmp[p["why"]][0] += p["status"] == "hit"
    S["by_cmp"] = by_cmp

    # 防平：竞足胜平负、模型算平局概率高 / 低 的两组，实际打平了多少
    dg: Dict[str, Any] = {}
    for p in singles:
        if p.get("play") != "竞足" or p.get("market") != "胜平负" or not _settled(p):
            continue
        m = p.get("mdl")
        sc = score_of(p)
        if not (isinstance(m, dict) and m.get("ok") and "pd" in m and sc):
            continue
        g = "high" if m["pd"] >= draw_guard else "low"
        e = dg.setdefault(g, {"n": 0, "hit": 0, "draw": 0})
        e["n"] += 1
        e["hit"] += p["status"] == "hit"
        e["draw"] += sc[0] == sc[1]
    S["draw_guard"] = dg

    # 模型把握档：推荐方向的模型概率 vs 实际命中（看模型有没有过度自信）
    cal: List[Dict[str, Any]] = []
    for lo, hi, lab in BANDS_P:
        rows = [(p, _pick_side_prob(p)) for p in singles if _settled(p)]
        rows = [(p, q) for p, q in rows if q is not None and lo <= q < hi]
        if rows:
            cal.append({"label": lab, "n": len(rows), "hit": sum(p["status"] == "hit" for p, _ in rows), "avg": sum(q for _, q in rows) / len(rows)})
    S["calib"] = cal
    # 北单：赔率隐含概率 vs 实际命中
    cal_bd: List[Dict[str, Any]] = []
    for lo, hi, lab in BANDS_P:
        rows = [p for p in singles if p.get("play") == "北单" and _settled(p) and isinstance(p.get("prob"), (int, float)) and lo <= p["prob"] < hi]
        if rows:
            cal_bd.append({"label": lab, "n": len(rows), "hit": sum(p["status"] == "hit" for p in rows), "avg": sum(p["prob"] for p in rows) / len(rows)})
    S["calib_bd"] = cal_bd

    # 北单赔率档
    sp_rows: List[Dict[str, Any]] = []
    for lo, hi, lab in BANDS_SP:
        rows = [p for p in singles if p.get("play") == "北单" and _settled(p) and isinstance(p.get("sp"), (int, float)) and lo <= p["sp"] < hi]
        if rows:
            sp_rows.append({"label": lab, "n": len(rows), "hit": sum(p["status"] == "hit" for p in rows)})
    S["sp_bands"] = sp_rows

    # 联赛
    lg: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for p in singles:
        if _settled(p) and p.get("lg"):
            lg[p["lg"]][1] += 1
            lg[p["lg"]][0] += p["status"] == "hit"
    S["leagues"] = sorted(((k, v[0], v[1]) for k, v in lg.items() if v[1] >= 5), key=lambda x: (-x[2], x[0]))

    # ★档（如果推单带了 star 字段）
    st: Dict[int, List[int]] = defaultdict(lambda: [0, 0])
    for p in singles:
        if _settled(p) and isinstance(p.get("star"), int):
            st[p["star"]][1] += 1
            st[p["star"]][0] += p["status"] == "hit"
    S["stars"] = {k: tuple(v) for k, v in sorted(st.items(), reverse=True)}
    S["star_trust"] = star_trust(hist)
    try:                                                         # 综合概率（赔率+模型+两队数据）分档：说的和实际差多少
        import composite as CP
        S["cp_bins"] = [b for b in CP.bucket_stats(hist) if b["n"]]
        S["cp_trust"] = CP.cp_trust(hist)
    except Exception:  # noqa: BLE001 —— composite.py 缺了或出错，只是少这一节
        S["cp_bins"], S["cp_trust"] = [], (True, "")

    # 比分参考 / 进球数参考（同一场只算一次）
    seen: set = set()
    n_s = h_s = n_g = h_g = 0
    for p in singles:
        m = p.get("mdl")
        sc = score_of(p)
        if p.get("play") == "竞篮" or not (isinstance(m, dict) and m.get("ok") and sc) or (p.get("date"), p.get("home"), p.get("away")) in seen:
            continue
        seen.add((p.get("date"), p.get("home"), p.get("away")))
        n_s += 1
        h_s += f"{sc[0]}:{sc[1]}" in (m.get("top") or [])
        if m.get("goals"):
            n_g += 1
            h_g += (sc[0] + sc[1]) in m["goals"]
    S["score_ref"], S["goals_ref"] = (h_s, n_s), (h_g, n_g)

    # 未中归因
    S["miss"] = {name: dict(miss_counts([p for p in singles if lo <= p["date"] < hi])) for name, (lo, hi) in periods.items()}
    S["miss_n"] = {name: sum(1 for p in singles if lo <= p["date"] < hi and p.get("status") == "miss") for name, (lo, hi) in periods.items()}

    # 逐日（最近 14 个有推单的日子）
    daily: List[Tuple[str, Dict[str, List[int]]]] = []
    for d in reversed(dates[-14:]):
        row: Dict[str, List[int]] = {}
        for pl in SINGLE:
            h, n = _hn([p for p in singles if p["date"] == d and p["play"] == pl])
            pend = sum(1 for p in singles if p["date"] == d and p["play"] == pl and p.get("status") == "pending")
            if n or pend:
                row[pl] = [h, n, pend]
        daily.append((d, row))
    S["daily"] = daily
    return S


def star_trust(hist: Dict[str, Any]) -> Tuple[bool, str]:
    """★档位值不值得显示在帖子里：样本够了才下判断。最高档的命中率比最低档还低 3 个百分点以上（星级没有区分度）→ 不显示；
    样本还不够 → 先显示（页面上写「验证中」）。返回 (是否显示, 一句说明)。"""
    t: Dict[int, List[int]] = defaultdict(lambda: [0, 0])
    for p in (hist.get("picks") or {}).values():
        if _settled(p) and isinstance(p.get("star"), int) and "legs" not in p:
            t[p["star"]][1] += 1
            t[p["star"]][0] += p["status"] == "hit"
    big = {k: v for k, v in t.items() if v[1] >= 10}
    total = sum(v[1] for v in t.values())
    if total < 40 or len(big) < 2:
        return True, f"星级还在验证中（已出结果 {total} 条，每档要 ≥10 条、合计 ≥40 条才下判断）"
    hi_k, lo_k = max(big), min(big)
    hi_r, lo_r = big[hi_k][0] / big[hi_k][1], big[lo_k][0] / big[lo_k][1]
    if hi_r < lo_r - 0.03:
        return False, f"{'★' * hi_k}命中率（{hi_r:.0%}）反而比{'★' * lo_k}（{lo_r:.0%}）低，星级暂时没有区分度，已不在帖子里显示"
    return True, f"星级有区分度：{'★' * hi_k} {hi_r:.0%} vs {'★' * lo_k} {lo_r:.0%}"


def _band_line(lab: str, n: int, h: int, extra: str = "") -> str:
    return f"  {lab}：{frac(h, n)}{extra}" + ("  （样本少）" if n < MIN_N else "")


def report_text(S: Dict[str, Any], rules_note: str = "") -> str:
    L: List[str] = []
    A = L.append
    A(f"战绩统计（截至 {S['today']} 之前已出结果的推单）")
    A("=" * 46)
    if not S["n_settled"]:
        A("还没有已出结果的推单，攒几天再来看。每天点「一键更新」，昨天的推单会自动结算进来。")
        return "\n".join(L) + "\n"
    A(f"记录范围：{S['first_date']} ～ {S['last_date']}｜已出结果 {S['n_settled']} 条（历史里保留的记录，太老的会自动清理）")
    A("")
    A("一、各玩法命中率（单场推荐 = 竞足/北单/竞篮；串关、传统足彩另列）")
    for name in ("近7日", "近30日", "累计"):
        d = S["by_play"][name]
        parts = [f"{pl} {frac(v[0], v[1])}" + (f"+待{v[2]}" if v[2] else "") for pl, v in d.items() if v[1] or v[2]]
        sh, sn = S["singles"][name]
        A(f"■ {name}：单场合计 {frac(sh, sn)}" if sn else f"■ {name}：还没有已出结果的单场推荐")
        for i in range(0, len(parts), 3):
            A("    " + "｜".join(parts[i:i + 3]))
    A("")
    A("二、连红连黑（单场推荐，按开赛先后排）")
    for k, v in S["streaks"].items():
        if not v["n"]:
            continue
        cur = v["cur"]
        cs = (f"现在连{'红' if cur[0] == 'hit' else '黑'} {cur[1]} 场" if cur else "—")
        A(f"  {k}：{cs}｜历史最长 连红 {v['max_hit']} / 连黑 {v['max_miss']}（共 {v['n']} 场）")
    A("")
    A("三、「两队数据」把关效果（单场推荐 + 影子记账）")
    names = {"support": "📈数据支持的（推了）", "mixed": "部分支持的（推了）", "none": "没有数据标记的（推了）",
             "against": "被数据撤掉的（假如没撤）", "nodata": "没取到数据的（假如推了）"}
    any_c = False
    for k in ("support", "mixed", "none", "against", "nodata"):
        h, n = S["by_cmp"][k]
        if n:
            any_c = True
            A(_band_line(names[k], n, h))
    if any_c:
        sup, non = S["by_cmp"]["support"], S["by_cmp"]["none"]
        ag = S["by_cmp"]["against"]
        if sup[1] >= MIN_N and ag[1] >= MIN_N:
            A("  → " + ("被撤掉的命中率确实更低，把关有用。" if ag[0] / ag[1] < sup[0] / sup[1] - 0.05 else
                       "被撤掉的和推出去的命中率差不多，把关暂时看不出作用。"))
        else:
            A("  → 样本还不够下结论；撤掉的那组命中率明显更低，才说明把关有用。")
    else:
        A("  还没有样本。")
    A("")
    A(f"四、防平：模型算平局概率高（≥{S.get('draw_guard_thr', 0.29):.0%}）vs 低，竞足胜平负实际打平了多少")
    dg = S["draw_guard"]
    if dg:
        for k, lab in (("high", "标了「防平」的"), ("low", "没标防平的")):
            e = dg.get(k)
            if e:
                A(_band_line(lab, e["n"], e["hit"], f"｜打平 {e['draw']} 场（{pct(e['draw'], e['n'])}）"))
        hi_, lo_ = dg.get("high"), dg.get("low")
        if hi_ and lo_ and hi_["n"] >= MIN_N and lo_["n"] >= MIN_N:
            A("  → " + ("标防平的，打平比例确实更高，这个提醒有用。" if hi_["draw"] / hi_["n"] > lo_["draw"] / lo_["n"] + 0.03 else "标防平的并没有更容易打平，这个提醒暂时没看出用处。"))
    else:
        A("  还没有样本（需要带数据模型的竞足推荐出了结果）。")
    A("")
    A("五、模型把握 vs 实际命中（竞足胜平负：模型给推荐方向的概率，和实际命中率对照，看有没有「吹过头」）")
    if S["calib"]:
        for c in S["calib"]:
            gap = c["hit"] / c["n"] - c["avg"]
            A(_band_line(f"模型 {c['label']}", c["n"], c["hit"], f"｜模型平均说 {c['avg']:.0%}，实际 {pct(c['hit'], c['n'])}（差 {gap:+.0%}）"))
    else:
        A("  还没有样本。")
    if S["calib_bd"]:
        A("  北单（赔率隐含的概率 vs 实际）：")
        for c in S["calib_bd"]:
            A(_band_line("  " + c["label"], c["n"], c["hit"], f"｜赔率说 {c['avg']:.0%}，实际 {pct(c['hit'], c['n'])}"))
    A("")
    if S["stars"]:
        A("六、信心星级（★越多应该越准；如果不是，说明星级没用，我会在页面上提醒）")
        for k, (h, n) in S["stars"].items():
            A(_band_line("★" * k, n, h))
        if S.get("star_trust"):
            A("  → " + S["star_trust"][1] + "。")
        A("")
    if S.get("cp_bins"):
        A("六b、综合概率（赔率+数据模型+两队数据）分档核对：「说的」和「实际」差多少（单场，已出结果，只算真的掺了模型的）")
        for b in S["cp_bins"]:
            A(_band_line(b["name"], b["n"], b["hit"], f"｜综合平均说 {b['sum'] / b['n']:.0%}，实际 {pct(b['hit'], b['n'])}（差 {b['hit'] / b['n'] - b['sum'] / b['n']:+.0%}）"))
        ok_, why_ = S.get("cp_trust") or (True, "")
        A("  → " + (why_ if not ok_ else "综合概率越高，实际命中越高才说明它有用；样本少的档只看看，别当结论。"))
        A("")
    A("七、北单赔率档")
    if S["sp_bands"]:
        for r in S["sp_bands"]:
            A(_band_line(r["label"], r["n"], r["hit"]))
    else:
        A("  还没有样本。")
    A("")
    A("八、联赛（样本 ≥5 场才列）")
    if S["leagues"]:
        for lg, h, n in S["leagues"][:15]:
            A(_band_line(lg, n, h))
    else:
        A("  还没有联赛够 5 场。")
    A("")
    A("九、比分参考 / 进球数参考（数据模型推算的，命中率本来就不高，如实记在这里）")
    h, n = S["score_ref"]
    A(f"  比分参考（3 个比分里有实际比分）：{frac(h, n)}" if n else "  比分参考：还没有样本")
    h, n = S["goals_ref"]
    A(f"  进球数参考（3 个进球数里有实际总进球）：{frac(h, n)}" if n else "  进球数参考：还没有样本")
    A("")
    A("十、未中归因（单场推荐没中的，原因能从比分看出来的）")
    for name in ("近7日", "近30日", "累计"):
        c, tot = S["miss"][name], S["miss_n"][name]
        if tot:
            A(f"  {name}：未中 {tot} 场｜" + ("｜".join(f"{k} {c[k]}" for k in ("平局", "爆冷", "走盘", "分差档位") if c.get(k)) or "原因说不准"))
    A("")
    A("十一、逐日（最近 14 个有推单的日子）")
    for d, row in S["daily"]:
        seg = "｜".join(f"{pl} {v[0]}/{v[1]}" + (f"+待{v[2]}" if v[2] else "") for pl, v in row.items())
        A(f"  {d[5:]}  {seg}")
    A("")
    A("说明：命中率是把推过的单一条条对赛果算出来的，样本越少越不稳；只是如实记录，不代表以后，也不建议按这些数字加码。")
    if rules_note:
        A(rules_note)
    return "\n".join(L) + "\n"


def export_csv(hist: Dict[str, Any], path: Any) -> int:
    """已出结果的推单（含串关）一行一条，utf-8-sig 编码 Excel 双击直接能开。返回写了多少行。"""
    rows = sorted([p for p in (hist.get("picks") or {}).values() if _settled(p)], key=_order_key)
    head = ["日期", "玩法", "项目", "联赛", "主队", "客队", "推荐", "让球线", "参考赔率SP", "概率", "两队数据", "结果", "是否命中", "未中原因"]
    cv = {"support": "数据支持", "mixed": "部分支持", "against": "数据反对"}
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        w = csv.writer(f)
        w.writerow(head)
        for p in rows:
            w.writerow([p.get("date"), p.get("play"), p.get("market"), p.get("lg", ""), p.get("home", ""), p.get("away", ""), p.get("label", ""),
                        p.get("line", ""), p.get("sp", "") if p.get("sp") is not None else "", p.get("prob", ""),
                        cv.get(p.get("cmp_v") or "", ""), p.get("result", ""), "中" if p["status"] == "hit" else "未中", miss_reason(p) or ""])
    return len(rows)


# ════════════════════════════════════════════════════════════════════════════
# 周报 / 月报 帖子
# ════════════════════════════════════════════════════════════════════════════
def md(day: str) -> str:
    return f"{int(day[5:7])}/{int(day[8:10])}"


def period_summary(hist: Dict[str, Any], start: str, end: str) -> Dict[str, Any]:
    """start～end（含）这段时间的推单战绩。"""
    ps = [p for p in (hist.get("picks") or {}).values() if start <= p.get("date", "") <= end]
    out: Dict[str, Any] = {"start": start, "end": end, "plays": {}, "n": 0}
    for pl in PLAY_ORDER:
        h, n = _hn([p for p in ps if p.get("play") == pl])
        if n:
            out["plays"][pl] = (h, n)
    singles = [p for p in ps if p.get("play") in SINGLE and "legs" not in p]
    out["singles"] = tuple(_hn(singles))
    out["n"] = out["singles"][1]
    out["pending"] = sum(1 for p in ps if p.get("status") == "pending")
    out["streak"] = _streaks(singles)
    out["cmp"] = {k: tuple(_hn([p for p in singles if (p.get("cmp_v") if p.get("cmp_v") in ("support", "mixed") else "none") == k])) for k in ("support", "mixed", "none")}
    out["miss"] = miss_counts(singles)
    out["days"] = len({p["date"] for p in ps})
    byday: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    for p in singles:
        if _settled(p):
            byday[p["date"]][1] += 1
            byday[p["date"]][0] += p["status"] == "hit"
    out["best_day"] = max(byday.items(), key=lambda kv: (kv[1][0] / kv[1][1], kv[1][1]), default=None) if byday else None
    out["worst_day"] = min(byday.items(), key=lambda kv: (kv[1][0] / kv[1][1], -kv[1][1]), default=None) if byday else None
    return out


def period_post(hist: Dict[str, Any], start: str, end: str, kind: str, name: str, sep: str, slogan: str, disclaimer: str, tags: str,
                min_n: int = 5) -> Optional[str]:
    """周报/月报。kind：「周报」或「月报」。已出结果的单场推荐少于 min_n 条返回 None（样本太少不发）。全部是真实结果。"""
    S = period_summary(hist, start, end)
    if S["n"] < min_n:
        return None
    sh, sn = S["singles"]
    L = [f"📅【{name}·{kind}】{md(start)}–{md(end)}", sep, "", f"📌这{S['days']}天单场推荐合计：{sh}/{sn}（{pct(sh, sn)}）"]
    seg = [f"{pl} {h}/{n}" for pl, (h, n) in S["plays"].items() if pl in SINGLE]
    if seg:
        L.append("🧭" + "｜".join(seg))
    comb = [(pl, S["plays"][pl]) for pl in COMBO if pl in S["plays"]]
    if comb:
        L.append("🎯串关 " + f"{sum(h for _, (h, _n) in comb)}/{sum(n for _, (_h, n) in comb)}")
    trad = [f"{pl} {S['plays'][pl][0]}/{S['plays'][pl][1]}" for pl in TRAD if pl in S["plays"]]
    if trad:
        L.append("🎲传统足彩 " + "｜".join(trad))
    st = S["streak"]
    if st["n"]:
        L.append(f"🔁最长连红 {st['max_hit']} 场｜最长连黑 {st['max_miss']} 场")
    bd, wd = S["best_day"], S["worst_day"]
    if bd and wd and bd[0] != wd[0]:
        L.append(f"📆最好一天 {md(bd[0])}（{bd[1][0]}/{bd[1][1]}）｜最差一天 {md(wd[0])}（{wd[1][0]}/{wd[1][1]}）")
    sup, non = S["cmp"]["support"], S["cmp"]["none"]
    if sup[1] >= 3 and non[1] >= 3:
        L.append(f"📈有两队数据支持的 {sup[0]}/{sup[1]}（{pct(*sup)}）｜没有数据标记的 {non[0]}/{non[1]}（{pct(*non)}）")
    elif sup[1] >= 3:
        L.append(f"📈有两队数据支持的 {sup[0]}/{sup[1]}（{pct(*sup)}）")
    if S["miss"]:
        order = ["平局", "爆冷", "走盘", "分差档位"]
        L.append("📉未中的原因：" + "｜".join(f"{k} {S['miss'][k]}" for k in order if S["miss"].get(k)))
    if S["pending"]:
        L.append(f"⏳还有 {S['pending']} 条没出结果，没算进去")
    L += ["", "💬" + (slogan or "命中不吹，未中不删"), "样本不大，只是如实记录，不代表以后。"]
    L += [x for x in (disclaimer, tags) if x]                       # 结尾的互动语/提示语和话题标签，空的就不写
    return "\n".join(L)
