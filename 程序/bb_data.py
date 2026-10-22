# -*- coding: utf-8 -*-
"""
bb_data.py —— 篮球版的「自己攒比分 + 数据模型」，给 竞篮 推单做两队数据对比（只用 Python 3.9+ 标准库）。

比分从哪来：500 网篮球「完场比分」页（live.500.com/lq.php?c=wc&e=日期）。这一页把当天每场比赛的球队、各节得分
直接写在网页自己的源码里（matchList），所以只需要读这一个网页，不碰任何被 robots.txt 禁止的脚本或接口。
规矩和足球完场页一样：先读 robots.txt，不让读的不读；每页隔 2.5 秒；读不到就停；读过的日子不重复读。
页面里的球队顺序是「客队在前、主队在后」（和竞彩篮球一样；已用你的赛果表核对过：拜仁 101:93 艾菲斯 = 客:主）。
页面里那一列赔率（oddsList）的含义没核实，不用。

模型（刻意简单、可检查，不是黑盒）：
  1. 每队一个「强弱值」= 最近 100 天比赛的净胜分，扣掉对手强弱和主场优势，越近的比赛权重越大（半衰期 35 天）；
     比赛少的队往联赛平均靠拢（相当于先给每队加 5 场“平均水平”的比赛），所以样本少时不会算出夸张的数字。
  2. 同样的办法再算每队的「得分高低」（两队总分），用来估计这场的总分。
  3. 预计净胜分 = 主队强弱 − 客队强弱 + 联赛主场优势；误差按正态分布（宽度用回测里真实的预测误差），
     得出赢球、让分过盘、大分的概率。
它不知道伤停、轮休、首发，只是“近况 + 对手强弱”的数学推算，和盘口、新闻一起做交叉印证，不是单独的结论。

自动回测：每次更新都用最近 45 天的比赛做「只用赛前数据」的滚动回测，和“只看联赛平均主场优势”的基准比；
没比基准好、或者场次太少时，模型只显示、不参与判断（bb_model_check.json 里记着）。

单独用：  python bb_data.py            看篮球赛果库和回测
          python bb_data.py --fill 30   补最近 30 天的篮球比分（每页隔 2.5 秒）
"""
from __future__ import annotations

import argparse
import bisect
import json
import math
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as L
import team_data as T

BJT = timezone(timedelta(hours=8))
BB_DB_FILE = "bb_results_db.json"
BB_CHECK_FILE = "bb_model_check.json"
BB_PATH = "/lq.php?c=wc"
BB_KEEP_DAYS = 160       # 赛果库保留多少天
BB_FIRST_DAYS = 30       # 库里还很空时，第一次自动补多少天
BB_DAILY_DAYS = 2        # 平时每次更新检查最近几个比赛日
BB_BACK_DAYS = 90        # 往前补到多少天
BB_BACK_PER_RUN = 12     # 每次更新最多往前补几天
BB_MIN_DONE = 8          # 完整读过的比赛日少于这个数，就当作「第一次」
BB_DONE_HOUR = 18        # 比赛日 D 的页面（D-1 中午～D 中午的比赛）到 D 当天这个钟点之后才算踢完

FIT_DAYS = 100           # 模型看多少天以内的比赛
HALF_LIFE = 35.0         # 权重半衰期（天）
LAM_M = 5.0              # 强弱值往平均靠拢的力度（相当于先加几场“平均水平”的比赛）
LAM_T = 8.0              # 得分高低的同上
SWEEPS = 14
MIN_G = 3                # 每队赛前至少要有几场才预测
K_H = 25.0               # 联赛主场优势往全体平均靠拢的“虚拟场数”
K_MU = 12.0              # 联赛平均总分同上
H_CLAMP = (0.0, 6.0)
SIGMA_M_DEFAULT, SIGMA_T_DEFAULT = 12.5, 17.0
SIGMA_M_RANGE, SIGMA_T_RANGE = (8.0, 18.0), (10.0, 28.0)
SD_INFLATE = 1.12        # 没有回测数据时，拿样本内误差放大一点当预测误差

BT_DAYS = 45
BT_STEP = 3              # 回测里每隔几天重新拟合一次（保守：比实际每天重拟合略差）
BT_MIN_N = 80            # 回测场次少于这个，不能证明模型靠谱
BT_MIN_GAIN_LL = 0.005   # 对数损失要比基准至少低这么多，而且差距要超过误差（标准误）的 2 倍

TOTAL_SANE = 25.0                       # 模型预计总分和竞彩总分盘差超过这么多分，就不写大分概率（多半是数据对不上）
SUPPORT_P = 0.80         # 模型认为推荐方赢球概率 ≥ 这个 → 数据支持
AGAINST_P = 0.62         # < 这个 → 数据不支持（中间是部分支持）


# ═══════════════════════ 1. 解析页面 ═══════════════════════
_LQ_SEL = re.compile(r'id="expect_sel"[^>]*>\s*<option[^>]*value="(\d{4}-\d{2}-\d{2})"', re.I)


def _json_after(html: str, var: str) -> Any:
    """取出页面里 `var 名字=[...]` 这个数组（用 JSON 解析，嵌套的括号不会错）。找不到返回 None。"""
    m = re.search(r"var\s+" + re.escape(var) + r"\s*=\s*\[", html)
    if not m:
        return None
    try:
        obj, _ = json.JSONDecoder().raw_decode(html[m.end() - 1:])
    except ValueError:
        return None
    return obj


def _periods(s: Any) -> Optional[Tuple[int, int, bool]]:
    """'31-20-24-27' → (4, 102, False)；'14-20-20-14/7' → (4, 75, True)：加时的分也算进总分。"""
    txt = str(s or "").strip()
    if not txt:
        return None
    main, _, ot = txt.partition("/")
    qs = re.findall(r"\d+", main)
    if len(qs) < 2 or len(qs) > 8:
        return None
    extra = re.findall(r"\d+", ot)
    return len(qs), sum(int(x) for x in qs) + sum(int(x) for x in extra), bool(extra)


def parse_lq(html: str) -> Tuple[Optional[str], List[Dict[str, Any]], Dict[str, Any]]:
    """500 网篮球完场页 → (页面上的比赛日, 已完场比赛 [{k,id,lg,h,a,hf,af,hid,aid,hs,as,ot}], 统计 {found,rows,done,bad})。
    k = 开赛时间（北京时间）；h/a = 主队/客队的竞彩叫法（短名）；hf/af = 全名；hid/aid = 球队编号；页面是客队在前。"""
    m = _LQ_SEL.search(html)
    label = m.group(1) if m else None
    arr = _json_after(html, "matchList")
    stat: Dict[str, Any] = {"found": isinstance(arr, list), "rows": 0, "done": 0, "bad": 0}
    out: List[Dict[str, Any]] = []
    if not isinstance(arr, list):
        return label, out, stat
    for r in arr:
        if not isinstance(r, list) or len(r) < 24:
            stat["bad"] += 1
            continue
        stat["rows"] += 1
        if str(r[0]) != "11":                               # 11 = 完场；其他（改期、中断、没打完）不收
            continue
        try:
            k = f"{str(r[3]).strip()} {str(r[4]).strip()}"
            datetime.strptime(k, "%Y-%m-%d %H:%M")
            ap, hp = _periods(r[22]), _periods(r[23])
            if not ap or not hp or ap[0] != hp[0]:
                raise ValueError("节数对不上")
            full_a, full_h = str(r[13]).strip(), str(r[18]).strip()
            short_a = (str(r[28]).strip() if len(r) > 28 else "") or full_a
            short_h = (str(r[29]).strip() if len(r) > 29 else "") or full_h
            if not short_a or not short_h or not str(r[12]) or not str(r[17]):
                raise ValueError("缺队名/编号")
            if not (20 <= ap[1] <= 250 and 20 <= hp[1] <= 250):
                raise ValueError("比分不合常理")
        except (ValueError, TypeError, IndexError):
            stat["bad"] += 1
            continue
        stat["done"] += 1
        out.append({"k": k, "id": str(r[1]), "lg": str(r[6]).strip(), "h": short_h, "a": short_a, "hf": full_h, "af": full_a,
                    "hid": str(r[17]), "aid": str(r[12]), "hs": hp[1], "as": ap[1], "ot": bool(ap[2] or hp[2])})
    return label, out, stat


# ═══════════════════════ 2. 自己攒的篮球赛果库 ═══════════════════════
def _clean(s: str) -> str:
    return re.sub(r"[\s　​·・\-—_.()（）]+", "", str(s or "")).lower()


def _sim(a: str, b: str) -> float:
    try:
        import sina_data as SD
        return SD.name_sim(a, b) if SD.marks_ok(a, b) else 0.0
    except Exception:  # noqa: BLE001
        return 1.0 if _clean(a) == _clean(b) else 0.0


class BbDB:
    """bb_results_db.json：{rows:[…], days:{比赛日: 读到几场}}。球队用页面里的球队编号认（同名不同队不会混）。"""

    def __init__(self, folder: Path):
        self.path = L.p(folder, BB_DB_FILE)
        self.rows: List[Dict[str, Any]] = []
        self.days: Dict[str, int] = {}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.rows = [r for r in d.get("rows", []) if isinstance(r, dict) and r.get("k") and r.get("hid") and r.get("aid")]
            wd = d.get("days")
            if isinstance(wd, dict):
                self.days = {str(k): int(v) for k, v in wd.items() if isinstance(v, (int, float))}
        except (OSError, ValueError, AttributeError):
            pass
        self._have = self._keys(self.rows)
        self._ix: Optional[Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, set]]] = None

    @staticmethod
    def _key(r: Dict[str, Any]) -> List[str]:
        """一场比赛的“身份”：页面里的比赛编号，和 开球时间+两队编号 两种（任何一种对上就是同一场）。"""
        ks = [f"{r['k']}|{r['hid']}|{r['aid']}"]
        if r.get("id"):
            ks.append("id:" + str(r["id"]))
        return ks

    @classmethod
    def _keys(cls, rows: List[Dict[str, Any]]) -> set:
        out: set = set()
        for r in rows:
            out.update(cls._key(r))
        return out

    def add(self, rows: List[Dict[str, Any]]) -> int:
        n = 0
        for r in rows:
            try:
                keys = self._key(r)
                if any(x in self._have for x in keys):
                    continue
                self.rows.append({"k": r["k"], "id": str(r.get("id", "")), "lg": r.get("lg", ""), "h": r["h"], "a": r["a"],
                                  "hf": r.get("hf", r["h"]), "af": r.get("af", r["a"]), "hid": str(r["hid"]), "aid": str(r["aid"]),
                                  "hs": int(r["hs"]), "as": int(r["as"]), "ot": bool(r.get("ot"))})
                self._have.update(keys)
                n += 1
            except (KeyError, TypeError, ValueError):
                continue
        if n:
            self._ix = None
        return n

    def save(self) -> None:
        cut = (datetime.now(BJT) - timedelta(days=BB_KEEP_DAYS)).strftime("%Y-%m-%d")
        self.rows = [r for r in self.rows if r["k"][:10] >= cut]
        self.rows.sort(key=lambda r: r["k"])
        self.days = {k: v for k, v in self.days.items() if k >= cut}
        self._have = self._keys(self.rows)
        self._ix = None
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"v": 1, "rows": self.rows, "days": self.days}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    # —— 认球队 ——
    def _index(self) -> Tuple[Dict[str, Dict[str, int]], Dict[str, Dict[str, int]], Dict[str, set]]:
        if self._ix is None:
            nm: Dict[str, Dict[str, int]] = {}      # 清洗后的队名 → {球队编号: 出现次数}
            tl: Dict[str, Dict[str, int]] = {}      # 球队编号 → {联赛: 场数}
            tn: Dict[str, set] = {}                 # 球队编号 → 它的各种写法
            for r in self.rows:
                for tid, short, full in ((r["hid"], r["h"], r.get("hf") or r["h"]), (r["aid"], r["a"], r.get("af") or r["a"])):
                    for name in (short, full):
                        c = nm.setdefault(_clean(name), {})
                        c[tid] = c.get(tid, 0) + 1
                        tn.setdefault(tid, set()).add(name)
                    lg = tl.setdefault(tid, {})
                    lg[r.get("lg", "")] = lg.get(r.get("lg", ""), 0) + 1
            self._ix = (nm, tl, tn)
        return self._ix

    def resolve(self, name: str, lg: str = "") -> Tuple[Optional[str], str]:
        """竞彩上的队名 → (球队编号, 说明)。找不到、或有两支同名的球队分不开，编号是 None，说明里写原因。"""
        nm, tl, tn = self._index()
        cands = dict(nm.get(_clean(name), {}))
        how = ""
        if not cands:                                       # 写法不同：只在同联赛的球队里找最像的，要明显比第二名像
            pool = [t for t, ls in tl.items() if (not lg or lg in ls)]
            scored = sorted(((max((_sim(name, x) for x in tn[t]), default=0.0), t) for t in pool), reverse=True)
            if scored and scored[0][0] >= 0.6 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.2):
                return scored[0][1], f"{name}按相似的写法对上了 {sorted(tn[scored[0][1]])[0]}"
            return None, f"{name}在篮球赛果库里找不到（叫法不同，或最近没打过比赛）"
        if len(cands) > 1:
            here = {t: c for t, c in cands.items() if lg and lg in tl.get(t, {})}
            if here:
                cands = here
            if len(cands) > 1:
                best = sorted(cands, key=lambda t: -tl.get(t, {}).get(lg, 0))
                if tl.get(best[0], {}).get(lg, 0) > tl.get(best[1], {}).get(lg, 0):
                    cands = {best[0]: 1}
        if len(cands) != 1:
            return None, f"库里有 {len(cands)} 支叫「{name}」的球队，分不清是哪支"
        return next(iter(cands)), how

    def team_games(self, tid: str) -> int:
        return sum(self._index()[1].get(tid, {}).values())

    def league_games(self, tid: str, lg: str) -> int:
        return self._index()[1].get(tid, {}).get(lg, 0)

    def main_league(self, tid: str) -> str:
        ls = self._index()[1].get(tid, {})
        return max(ls, key=lambda k: ls[k]) if ls else ""

    def form(self, tid: str, before: str, n: int = 6) -> Optional[Dict[str, Any]]:
        """某队开赛前最近 n 场：{n,w,l,pf,pa,avg,last}。last = 最近一场的开赛时间。"""
        rows = [r for r in self.rows if r["k"] < before and tid in (r["hid"], r["aid"])]
        rows.sort(key=lambda r: r["k"], reverse=True)
        rows = rows[:n]
        if not rows:
            return None
        w = pf = pa = 0
        for r in rows:
            mine, theirs = (r["hs"], r["as"]) if r["hid"] == tid else (r["as"], r["hs"])
            pf, pa = pf + mine, pa + theirs
            w += mine > theirs
        c = len(rows)
        return {"n": c, "w": w, "l": c - w, "pf": pf / c, "pa": pa / c, "avg": (pf - pa) / c, "last": rows[0]["k"]}


# ═══════════════════════ 3. 读页面（补比分） ═══════════════════════
def _day_done(label: str, now: datetime) -> bool:
    """比赛日 label 的页面（前一天中午到当天中午的比赛）到 label 当天 BB_DONE_HOUR 点之后才算踢完。"""
    try:
        end = datetime.strptime(label, "%Y-%m-%d") + timedelta(hours=BB_DONE_HOUR)
    except ValueError:
        return False
    return now.replace(tzinfo=None) >= end


def recent_labels(days: int, now: Optional[datetime] = None) -> List[str]:
    """从今天往前 days 天的比赛日标签（YYYY-MM-DD，北京时间）。"""
    now_ = now or datetime.now(BJT)
    today = now_.astimezone(BJT).replace(tzinfo=None) if now_.tzinfo else now_
    return [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, max(1, int(days)) + 1)]


def lq_fill(folder: Path, labels: List[str], *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
            proxy: str = "", sleep: Callable[[float], None] = time.sleep, host: Optional[str] = None, gap: Optional[float] = None,
            now: Optional[datetime] = None, force: bool = False) -> Dict[str, Any]:
    """读这些比赛日的篮球完场页，把完场比分存进篮球赛果库。已经完整读过的日子跳过（force=True 重读）。不抛异常。"""
    import sina_data as SD
    say = log or (lambda m: None)
    cancel = cancel or (lambda: False)
    now = now or datetime.now(BJT)
    today = now.astimezone(BJT).replace(tzinfo=None) if now.tzinfo else now
    res: Dict[str, Any] = {"pages": 0, "ok": 0, "rows": 0, "added": 0, "total": 0, "skipped": 0, "errors": [], "stopped": False,
                           "blocked": False, "span": ""}
    try:
        db = BbDB(Path(folder))
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"篮球赛果库打不开：{exc}")
        return res
    fetcher = SD.WanchangFetcher(host=host, gap=gap, proxy=proxy, sleep=sleep, cancel=cancel)
    fetcher.path_for = lambda label: BB_PATH + (f"&e={label}" if label else "")        # type: ignore[assignment]
    try:
        for label in labels:
            if cancel():
                res["stopped"] = True
                break
            if not force and label in db.days and _day_done(label, today):
                res["skipped"] += 1
                continue
            html, err = fetcher.page(label)
            if err == "已停止":
                res["stopped"] = True
                break
            res["pages"] += 1
            if err:
                res["errors"].append(f"{label}：{err}")
                say(f"  ⚠ 篮球 {label}：没读到（{err}）")
                if "robots" in err:
                    res["blocked"] = True
                    break
                if fetcher.fail >= 3:
                    say("  篮球：连续 3 次没读到，先停下（网络或网站的问题，过一会再试）")
                    break
                continue
            page_label, rows, stat = parse_lq(html)
            if not stat["found"]:
                res["errors"].append(f"{label}：页面里没找到比赛数据（网站改版？）")
                say(f"  ⚠ 篮球 {label}：页面里没找到比赛数据（网站可能改版了）")
                continue
            if page_label != label:
                res["errors"].append(f"{label}：页面显示的是 {page_label or '（认不出日期）'}，跳过")
                say(f"  ⚠ 篮球 {label}：页面显示的日期是 {page_label or '认不出'}，这天跳过")
                continue
            res["ok"] += 1
            res["rows"] += len(rows)
            added = db.add(rows)
            res["added"] += added
            if _day_done(label, today):
                db.days[label] = len(rows)
            bad = f"，{stat['bad']} 行没认出" if stat["bad"] else ""
            say(f"  篮球 {label}：读到 {len(rows)} 场已完场，新存 {added} 场{bad}")
            if res["ok"] % 5 == 0:
                db.save()
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"出错：{exc}")
        say(f"  ⚠ 读篮球完场页出错：{exc}")
    finally:
        try:
            db.save()
        except Exception:  # noqa: BLE001
            pass
    res["total"] = len(db.rows)
    days = sorted({r["k"][:10] for r in db.rows})
    res["span"] = f"{days[0]} ～ {days[-1]}" if days else ""
    return res


def lq_daily(folder: Path, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None, proxy: str = "",
             sleep: Callable[[float], None] = time.sleep, host: Optional[str] = None, gap: Optional[float] = None,
             now: Optional[datetime] = None) -> Dict[str, Any]:
    """每次更新时调用：存最近几个比赛日的篮球比分，并把更早的日子逐步补到 BB_BACK_DAYS 天（库里还很空时，第一次补最近 30 天）。"""
    say = log or (lambda m: None)
    now_ = now or datetime.now(BJT)
    today = now_.astimezone(BJT).replace(tzinfo=None) if now_.tzinfo else now_
    try:
        done_days = set(BbDB(Path(folder)).days)
    except Exception:  # noqa: BLE001
        done_days = set()
    first = len(done_days) < BB_MIN_DONE
    recent = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, BB_DAILY_DAYS + 1)]
    older = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(BB_DAILY_DAYS + 1, (BB_FIRST_DAYS if first else BB_BACK_DAYS) + 1)]
    older = [d for d in older if d not in done_days][: (BB_FIRST_DAYS if first else BB_BACK_PER_RUN)]
    labels = recent + older
    verbose = first or bool(older)
    say("读 500 网篮球完场页，攒篮球两队近况用的比分" + (f"（{'第一次攒篮球比分，先补最近 %d 天' % BB_FIRST_DAYS if first else '再往前补 %d 天' % len(older)}，约 {max(1, round(len(labels) * 3.5 / 60))} 分钟）……" if verbose else "……"))
    r = lq_fill(folder, labels, log=(say if verbose else None), cancel=cancel, proxy=proxy, sleep=sleep, host=host, gap=gap, now=now)
    if r["errors"] and not r["ok"]:
        say(f"⚠ 篮球完场页没读成：{r['errors'][0]}（不影响足球推单，只是篮球赛果库没增加）")
    elif not r["ok"] and r["skipped"]:
        say(f"篮球赛果库：最近几天的比分之前都存过了，共 {r['total']} 场" + (f"（{r['span']}）" if r["span"] else ""))
    else:
        say(f"篮球赛果库：读了 {r['ok']} 页，新存 {r['added']} 场，共 {r['total']} 场" + (f"（{r['span']}）" if r["span"] else ""))
    return r


# ═══════════════════════ 4. 数据模型 ═══════════════════════
def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _ts(k: str) -> Optional[float]:
    try:
        return datetime.strptime(k[:16], "%Y-%m-%d %H:%M").replace(tzinfo=timezone.utc).timestamp() / 86400.0
    except (ValueError, TypeError):
        return None


class Games:
    """把赛果行整理成按时间排好的元组，方便按时间切片：(ts, k, hid, aid, 主得分, 客得分, 联赛)。"""

    def __init__(self, rows: List[Dict[str, Any]]):
        g = []
        for r in rows:
            t = _ts(r.get("k", ""))
            if t is None:
                continue
            try:
                g.append((t, r["k"], str(r["hid"]), str(r["aid"]), int(r["hs"]), int(r["as"]), r.get("lg", "") or ""))
            except (KeyError, TypeError, ValueError):
                continue
        g.sort(key=lambda x: x[0])
        self.g = g
        self.ts = [x[0] for x in g]

    def between(self, lo: float, hi: float) -> List[Tuple[float, str, str, str, int, int, str]]:
        return self.g[bisect.bisect_left(self.ts, lo): bisect.bisect_left(self.ts, hi)]


class Fit:
    """拟合好的强弱值。r = 净胜分强弱，o = 得分高低（都是相对联赛平均）。"""

    def __init__(self) -> None:
        self.r: Dict[str, float] = {}
        self.o: Dict[str, float] = {}
        self.ng: Dict[str, int] = {}
        self.last: Dict[str, str] = {}
        self.H: Dict[str, float] = {}
        self.MU: Dict[str, float] = {}
        self.ratio: Dict[str, float] = {}
        self.comp: Dict[str, str] = {}                      # 球队 → 所在“圈子”（互相有过交手链的球队同一圈；不同圈的强弱值没法互相比）
        self.H0, self.MU0 = 3.0, 160.0
        self.sd_m, self.sd_t = SIGMA_M_DEFAULT, SIGMA_T_DEFAULT
        self.n = 0


def fit(games: Games, as_ts: float, *, fit_days: float = FIT_DAYS, half_life: float = HALF_LIFE, lam_m: float = LAM_M,
        lam_t: float = LAM_T, sweeps: int = SWEEPS) -> Fit:
    """用 as_ts（天）之前 fit_days 天内的比赛，拟合每队强弱。"""
    f = Fit()
    sel = games.between(as_ts - fit_days, as_ts)
    f.n = len(sel)
    if not sel:
        return f
    lgs: Dict[str, List[float]] = {}                        # 联赛 → [权重和, 净胜分加权和, 总分加权和, 场数]
    allw = allm = allt = 0.0
    wl: List[float] = []
    for t, k, h, a, hs, as_, lg in sel:
        w = 0.5 ** ((as_ts - t) / half_life)
        wl.append(w)
        s = lgs.setdefault(lg, [0.0, 0.0, 0.0, 0])
        s[0] += w; s[1] += w * (hs - as_); s[2] += w * (hs + as_); s[3] += 1
        allw += w; allm += w * (hs - as_); allt += w * (hs + as_)
        f.ng[h] = f.ng.get(h, 0) + 1
        f.ng[a] = f.ng.get(a, 0) + 1
        f.last[h] = k if k > f.last.get(h, "") else f.last[h]
        f.last[a] = k if k > f.last.get(a, "") else f.last[a]
    f.H0 = max(H_CLAMP[0], min(H_CLAMP[1], allm / allw))
    f.MU0 = allt / allw
    for lg, s in lgs.items():
        f.H[lg] = max(H_CLAMP[0], min(H_CLAMP[1], (s[1] + K_H * f.H0) / (s[0] + K_H)))
        f.MU[lg] = (s[2] + K_MU * f.MU0) / (s[0] + K_MU)
    adj: Dict[str, List[Tuple[str, float, float, float]]] = {}
    for (t, k, h, a, hs, as_, lg), w in zip(sel, wl):
        m_adj = (hs - as_) - f.H[lg]
        t_adj = (hs + as_) - f.MU[lg]
        adj.setdefault(h, []).append((a, m_adj, t_adj, w))
        adj.setdefault(a, []).append((h, -m_adj, t_adj, w))
    sw = {tid: sum(x[3] for x in lst) for tid, lst in adj.items()}
    r = {tid: 0.0 for tid in adj}
    o = {tid: 0.0 for tid in adj}
    for _ in range(sweeps):
        for tid, lst in adj.items():
            sm = st = 0.0
            for opp, cm, ct, w in lst:
                sm += w * (r[opp] + cm)
                st += w * (ct - o[opp])
            r[tid] = sm / (sw[tid] + lam_m)
            o[tid] = st / (sw[tid] + lam_t)
    f.r, f.o = r, o
    par: Dict[str, str] = {tid: tid for tid in adj}

    def _root(x: str) -> str:
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x
    for t, k, h, a, hs, as_, lg in sel:
        rh, ra = _root(h), _root(a)
        if rh != ra:
            par[rh] = ra
    f.comp = {tid: _root(tid) for tid in adj}
    # 样本内误差：给没有回测数据时当“预测误差”用（放大一点），并看各联赛的比赛是不是比别的联赛更“散”
    ssm = sst = 0.0
    per: Dict[str, List[float]] = {}
    for (t, k, h, a, hs, as_, lg), w in zip(sel, wl):
        em = (hs - as_) - (r[h] - r[a] + f.H[lg])
        et = (hs + as_) - (f.MU[lg] + o[h] + o[a])
        ssm += w * em * em
        sst += w * et * et
        p = per.setdefault(lg, [0.0, 0.0, 0])
        p[0] += w * em * em; p[1] += w; p[2] += 1
    f.sd_m = max(SIGMA_M_RANGE[0], min(SIGMA_M_RANGE[1], math.sqrt(ssm / allw) * SD_INFLATE))
    f.sd_t = max(SIGMA_T_RANGE[0], min(SIGMA_T_RANGE[1], math.sqrt(sst / allw) * SD_INFLATE))
    g_sd = math.sqrt(ssm / allw) or 1.0
    for lg, (ss, ww, n) in per.items():
        ratio = math.sqrt(ss / ww) / g_sd if ww > 0 else 1.0
        f.ratio[lg] = 1.0 + (max(0.8, min(1.25, ratio)) - 1.0) * n / (n + 30.0)
    return f


def predict(f: Fit, hid: str, aid: str, lg: str, *, sig_m: Optional[float] = None, sig_t: Optional[float] = None) -> Optional[Dict[str, Any]]:
    """两队各至少 MIN_G 场赛前比赛才预测。返回 {M 预计主队净胜, T 预计总分, sm, st, n, has_lg, ...}。"""
    nh, na = f.ng.get(hid, 0), f.ng.get(aid, 0)
    if nh < MIN_G or na < MIN_G:
        return None
    has_lg = lg in f.H
    H = f.H.get(lg, f.H0)
    MU = f.MU.get(lg, f.MU0)
    ratio = f.ratio.get(lg, 1.0)
    sm = (sig_m or f.sd_m) * ratio
    st = (sig_t or f.sd_t) * ratio
    return {"M": f.r.get(hid, 0.0) - f.r.get(aid, 0.0) + H, "T": MU + f.o.get(hid, 0.0) + f.o.get(aid, 0.0), "sm": sm, "st": st,
            "n": (nh, na), "lg": lg, "has_lg": has_lg, "H": H, "last": (f.last.get(hid, ""), f.last.get(aid, ""))}


def p_home_win(p: Dict[str, Any]) -> float:
    return 1.0 - _phi((0.5 - p["M"]) / p["sm"])                  # 净胜分 ≥ 1


def p_cover(p: Dict[str, Any], line: float) -> float:
    """主队过盘概率：竞彩让分 line 是加在主队身上的（-12.5 = 主队让 12.5 分），主队净胜分 + line > 0 才算过盘。"""
    return 1.0 - _phi((-line - p["M"]) / p["sm"])


def p_over(p: Dict[str, Any], total: float) -> float:
    return 1.0 - _phi((total - p["T"]) / p["st"])


# ═══════════════════════ 5. 回测 ═══════════════════════
def backtest(rows: List[Dict[str, Any]], days: int = BT_DAYS, step: int = BT_STEP, min_n: int = BT_MIN_N) -> Dict[str, Any]:
    """滚动回测：每 step 天重新拟合一次（只用这段时间之前的比赛），预测接下来 step 天里的比赛。
    基准 = 只看该联赛（赛前）平均主场优势：预计净胜分 = 主场优势，赢球概率 = 联赛赛前主队胜率（往全体平均靠拢）。"""
    G = Games(rows)
    res: Dict[str, Any] = {"n": 0, "ok": False, "days": days, "reason": ""}
    if len(G.g) < 60:
        res["reason"] = "篮球赛果库里比分还太少，没法回测"
        return res
    last = G.ts[-1]
    cut = math.floor(last - days)
    recs: List[Tuple[float, int, float, int, str, float]] = []      # (M, 实际净胜, T, 实际总分, 联赛, 基准赢球概率)
    b0 = float(cut)
    while b0 <= last:
        test = G.between(b0, b0 + step)
        if test:
            f = fit(G, b0)
            prior: Dict[str, List[int]] = {}
            tot = [0, 0]
            for t, k, h, a, hs, as_, lg in G.between(b0 - FIT_DAYS, b0):
                s = prior.setdefault(lg, [0, 0])
                s[0] += 1; s[1] += hs > as_
                tot[0] += 1; tot[1] += hs > as_
            g_rate = (tot[1] / tot[0]) if tot[0] >= 20 else 0.6
            for t, k, h, a, hs, as_, lg in test:
                p = predict(f, h, a, lg)
                if not p:
                    continue
                n_, w_ = prior.get(lg, [0, 0])
                base = (w_ + 20 * g_rate) / (n_ + 20)
                recs.append((p["M"], hs - as_, p["T"], hs + as_, lg, max(0.05, min(0.95, base))))
        b0 += step
    n = len(recs)
    res["n"] = n
    if n < min_n:
        res["reason"] = f"最近{days}天能回测的比赛只有 {n} 场（要 ≥{min_n}），先不让模型参与判断"
        return res
    sm = math.sqrt(sum((m - y) ** 2 for m, y, _, _, _, _ in recs) / n)
    stt = math.sqrt(sum((t - z) ** 2 for _, _, t, z, _, _ in recs) / n)
    sm = max(SIGMA_M_RANGE[0], min(SIGMA_M_RANGE[1], sm))
    stt = max(SIGMA_T_RANGE[0], min(SIGMA_T_RANGE[1], stt))
    hit = 0
    bins: Dict[str, List[int]] = {"50-65%": [0, 0], "65-80%": [0, 0], "80%+": [0, 0]}
    h_by_lg: Dict[str, List[float]] = {}
    for M, y, T_, z, lg, base in recs:
        s_ = h_by_lg.setdefault(lg, [0.0, 0])
        s_[0] += y; s_[1] += 1
    allmean = sum(y for _, y, _, _, _, _ in recs) / n
    allmean_t = sum(z for _, _, _, z, _, _ in recs) / n
    d_ll: List[float] = []                         # 每场：基准的对数损失 − 模型的对数损失（>0 = 模型好）
    d_ae: List[float] = []                         # 每场：基准的净胜分误差 − 模型的（>0 = 模型好）
    ll = ll0 = mae = mae0 = tmae = tmae0 = 0.0
    for M, y, T_, z, lg, base in recs:
        ph = max(1e-6, min(1 - 1e-6, 1.0 - _phi((0.5 - M) / sm)))
        win = 1 if y > 0 else 0
        l1 = -math.log(ph if win else 1 - ph)
        l0 = -math.log(base if win else 1 - base)
        s_ = h_by_lg[lg]
        # 基准的预计净胜分 = 该联赛平均主场优势（用回测窗口内的联赛平均，对基准是宽松的）
        e1, e0 = abs(y - M), abs(y - ((s_[0] + 20 * allmean) / (s_[1] + 20)))
        ll += l1; ll0 += l0; mae += e1; mae0 += e0
        d_ll.append(l0 - l1); d_ae.append(e0 - e1)
        pf = max(ph, 1 - ph)
        right = (win == 1) == (ph >= 0.5)
        hit += right
        key = "50-65%" if pf < 0.65 else "65-80%" if pf < 0.8 else "80%+"
        bins[key][0] += 1; bins[key][1] += right
        tmae += abs(z - T_); tmae0 += abs(z - allmean_t)

    def gain(d: List[float]) -> Tuple[float, float]:
        m_ = sum(d) / len(d)
        var = sum((x - m_) ** 2 for x in d) / max(1, len(d) - 1)
        return m_, math.sqrt(var / len(d))
    g_ll, se_ll = gain(d_ll)
    g_ae, se_ae = gain(d_ae)
    res.update(acc=hit / n, logloss=ll / n, base_logloss=ll0 / n, mae=mae / n, base_mae=mae0 / n, t_mae=tmae / n, t_base_mae=tmae0 / n,
               sigma_m=sm, sigma_t=stt, ll_gain=g_ll, ll_se=se_ll, mae_gain=g_ae, mae_se=se_ae,
               bins={k: (v[0], (v[1] / v[0]) if v[0] else None) for k, v in bins.items()})
    better = g_ll > BT_MIN_GAIN_LL and g_ll > 2 * se_ll and g_ae > 0
    b80, b65 = bins["80%+"], bins["65-80%"]
    calib = (b80[0] < 12 or b80[1] / b80[0] >= 0.72) and (b65[0] < 20 or b65[1] / b65[0] >= 0.55)
    res["ok"] = bool(better and calib)
    if not better:
        res["reason"] = "模型的预测没有明显比“只看联赛平均主场优势”更准（差距没超过误差的 2 倍），只显示、不参与判断"
    elif not calib:
        res["reason"] = "模型说把握很大的比赛实际赢得没那么多（过于自信），只显示、不参与判断"
    return res


def check_text(r: Dict[str, Any]) -> str:
    if not r.get("n") or "acc" not in r:
        return "篮球模型回测：" + (r.get("reason") or "没数据")
    sure = [f"{k}→实际{v[1]:.0%}（{v[0]}场）" for k, v in r["bins"].items() if v[0] >= 8 and v[1] is not None]
    return (f"篮球模型回测（最近{r['days']}天 {r['n']} 场，每场只用赛前数据）：预计净胜分平均差 {r['mae']:.1f} 分（基准 {r['base_mae']:.1f}）；"
            f"赢球方向对 {r['acc']:.0%}；对数损失 {r['logloss']:.3f}（基准 {r['base_logloss']:.3f}，越小越好）"
            + (f"；把握分段：{'，'.join(sure)}" if sure else "") + "。"
            + ("过关，模型参与判断。" if r["ok"] else (r.get("reason") or "不过关") + "。"))


def run_check(folder: Path, db: Optional[BbDB] = None, write: bool = True) -> Dict[str, Any]:
    """读篮球赛果库、回测、结果存进 bb_model_check.json（同一天、同一份库不重复算）。不抛异常。"""
    folder = Path(folder)
    try:
        db = db or BbDB(folder)
        sig = f"{len(db.rows)}|{db.rows[-1]['k'] if db.rows else ''}|{FIT_DAYS}|{HALF_LIFE}|{LAM_M}|{LAM_T}"
        path = L.p(folder, BB_CHECK_FILE)
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if old.get("sig") == sig and old.get("date") == datetime.now().strftime("%Y-%m-%d"):
                return old
        except (OSError, ValueError):
            pass
        res = backtest(db.rows)
        res["sig"], res["date"] = sig, datetime.now().strftime("%Y-%m-%d")
        if write:
            try:
                path.write_text(json.dumps(res, ensure_ascii=False, indent=1), encoding="utf-8")
            except OSError:
                pass
        return res
    except Exception as exc:  # noqa: BLE001
        return {"n": 0, "ok": False, "reason": f"回测没跑成（{exc}）"}


# ═══════════════════════ 6. 给竞篮推单出「两队数据对比」 ═══════════════════════
def _hours_between(a: str, b: str) -> Optional[float]:
    ta, tb = _ts(a), _ts(b)
    return None if ta is None or tb is None else abs(tb - ta) * 24.0


def _rest_text(home: str, away: str, kick: str, last: Tuple[str, str]) -> str:
    bits = []
    for name, lk in ((home, last[0]), (away, last[1])):
        h = _hours_between(lk, kick) if lk else None
        if h is None:
            continue
        if h <= 30:
            bits.append(f"{name}背靠背（上场离开赛只有{h:.0f}小时）")
        elif h >= 24 * 7:
            bits.append(f"{name}已歇{h / 24:.0f}天")
    return "，".join(bits)


def _line_of(s: Any) -> Optional[float]:
    try:
        return float(str(s).replace("＋", "+").replace("－", "-").strip())
    except (TypeError, ValueError):
        return None


def judge(side: Optional[str], p: Optional[Dict[str, Any]], trusted: bool, hs: Optional[Dict[str, Any]], as_: Optional[Dict[str, Any]],
          line: float) -> Tuple[str, Optional[str], Optional[float], str]:
    """(结论, 数据倾向, 分数, 一句原因)。模型回测过关 → 听模型的赢球概率；不过关 → 退回“近况胜负+场均净胜”的老办法（team_data 同一套）。"""
    if side not in ("home", "away"):
        return "mixed", None, None, "这场的推荐不是单一方向，只列数据、不下结论"
    if p is not None and trusted:
        ph = p_home_win(p)
        pw = ph if side == "home" else 1.0 - ph
        score = round((pw - 0.5) * 4.0, 2)
        lean = side if pw >= 0.55 else ("away" if side == "home" else "home") if pw <= 0.45 else None
        if pw >= SUPPORT_P:
            return "support", lean, score, f"模型算推荐方赢球概率{pw:.0%}"
        if pw >= AGAINST_P:
            return "mixed", lean, score, f"模型算推荐方赢球概率只有{pw:.0%}，不算稳"
        return "against", lean, score, f"模型算推荐方赢球概率只有{pw:.0%}"
    if hs and as_ and hs["n"] >= 3 and as_["n"] >= 3:
        return T.Provider._bjudge(side, {"n": hs["n"], "w": hs["w"], "l": hs["l"], "avg": hs["avg"]},
                                  {"n": as_["n"], "w": as_["w"], "l": as_["l"], "avg": as_["avg"]}, None, None, abs(line))
    return "mixed", None, None, "近况场次太少，没法下结论"


def notes_for(folder: Path, matches: List[Dict[str, Any]], log: Optional[Callable[[str], None]] = None) -> Tuple[List[Dict[str, Any]], List[str]]:
    """竞篮（篮球）比赛 → (两队数据对比 notes, 说明)。和 SinaProvider.notes_for 同一个接口。每场必须两队都在篮球赛果库里认得出、
    都有够用的赛前比赛，才出 note；否则不出（没有数据就不推），原因写进说明。"""
    say = log or (lambda m: None)
    problems: List[str] = []
    notes: List[Dict[str, Any]] = []
    if not matches:
        return notes, problems
    db = BbDB(Path(folder))
    if len(db.rows) < 40:
        problems.append(f"篮球赛果库里比分还太少（{len(db.rows)} 场），{len(matches)} 场篮球没有数据对比；每次更新会自动攒，过几天就够了。")
        return notes, problems
    check = run_check(Path(folder), db)
    say("  " + check_text(check))
    trusted = bool(check.get("ok"))
    G = Games(db.rows)
    first_kick = min(m["kick"].astimezone(BJT).strftime("%Y-%m-%d %H:%M") for m in matches)
    as_ts = _ts(first_kick) or (G.ts[-1] + 0.5 if G.ts else 0.0)
    f = fit(G, as_ts)
    sig_m = check.get("sigma_m") if trusted else None
    sig_t = check.get("sigma_t") if trusted else None
    short: Dict[str, List[str]] = {"noname": [], "few": [], "cross": []}
    for m in matches:
        vs = f"{m['home']}vs{m['away']}"
        lg = m.get("lg") or ""
        kick = m["kick"].astimezone(BJT).strftime("%Y-%m-%d %H:%M")
        hid, why_h = db.resolve(m["home"], lg)
        aid, why_a = db.resolve(m["away"], lg)
        if not hid or not aid:
            short["noname"].append(vs)
            say(f"    {vs}：{why_h if not hid else why_a}")
            continue
        for w in (why_h, why_a):
            if w:
                say(f"    {vs}：{w}")
        hs_, as_ = db.form(hid, kick), db.form(aid, kick)
        if not hs_ or not as_ or hs_["n"] < MIN_G or as_["n"] < MIN_G:
            short["few"].append(f"{vs}（{m['home']}{hs_['n'] if hs_ else 0}场/{m['away']}{as_['n'] if as_ else 0}场）")
            continue
        # 两队是不是“可比较”：在这场比赛的联赛里各自有比赛，或者平时就在同一个联赛打
        ch, ca = f.comp.get(hid), f.comp.get(aid)
        if ch is not None and ca is not None:
            comparable = ch == ca                                       # 同一个圈子里才能比强弱
        else:                                                           # 有一队最近没比赛 → 只看近况，要求平时在同一个联赛
            comparable = bool(lg and db.league_games(hid, lg) >= 2 and db.league_games(aid, lg) >= 2) or db.main_league(hid) == db.main_league(aid)
        if not comparable:
            short["cross"].append(vs)
            continue
        p = predict(f, hid, aid, lg, sig_m=sig_m, sig_t=sig_t)
        side = m.get("side")
        line = _line_of(m.get("line"))
        total = _line_of(m.get("total"))
        verdict, lean, score, why = judge(side, p, trusted, hs_, as_, line if line is not None else 0.0)

        def part(zh: str, st: Dict[str, Any]) -> str:
            return f"{zh}近{st['n']}场{st['w']}胜{st['l']}负（场均得{st['pf']:.0f}失{st['pa']:.0f}，净胜{st['avg']:+.1f}）"
        txt = part(m["home"], hs_) + "；" + part(m["away"], as_)
        if p is not None:
            bits = [f"数据模型（两队近{p['n'][0]}/{p['n'][1]}场，扣掉对手强弱和主场优势）：预计{m['home']}净胜{p['M']:+.1f}分"]
            if p["has_lg"]:
                bits.append(f"全场总分约{p['T']:.0f}")
            if side in ("home", "away"):
                ph = p_home_win(p)
                bits.append(f"{m['home'] if side == 'home' else m['away']}赢球概率{(ph if side == 'home' else 1 - ph):.0%}")
            if line is not None and abs(line) > 0:
                bits.append(f"{m['home']}{line:+g}分盘过盘{min(0.99, max(0.01, p_cover(p, line))):.0%}")
            if total and p["has_lg"] and abs(p["T"] - total) <= TOTAL_SANE:        # 模型总分和盘口差太远多半是对错了联赛/数据不够，不写
                bits.append(f"总分{total:g}的大分概率{min(0.99, max(0.01, p_over(p, total))):.0%}")
            seg = "，".join(bits)
            rest = _rest_text(m["home"], m["away"], kick, p["last"])
            txt += "；" + seg + (f"；{rest}" if rest else "") + ("" if trusted else "（回测未过关，只参考）")
        elif not trusted:
            txt += "；数据模型（样本不够，没算）"
        note = T.finish_note(m, txt, verdict, lean, score, why)
        note["model"] = bool(p is not None)
        if p is not None:                                              # 篮球模型的净胜分估计：综合推单把它和竞彩让分盘合并（回测没过关的只存着，不参与）
            note["bbm"] = {"ok": bool(trusted), "M": round(p["M"], 2), "sm": round(p["sm"], 2), "T": round(p["T"], 1)}
        note["src"] = "bb"
        notes.append(note)
    parts = []
    if short["noname"]:
        parts.append(f"{len(short['noname'])} 场队名在篮球赛果库里认不出：{'、'.join(short['noname'])}")
    if short["few"]:
        parts.append(f"{len(short['few'])} 场有一队赛前比赛不到 {MIN_G} 场：{'、'.join(short['few'])}")
    if short["cross"]:
        parts.append(f"{len(short['cross'])} 场两队不在同一个联赛、又缺共同联赛的比赛，强弱没法比：{'、'.join(short['cross'])}")
    if parts:
        problems.append("篮球没取到数据对比的原因：" + "；".join(parts) + "。")
    say(f"  篮球：{len(matches)} 场竞篮，{len(notes)} 场取到两队数据对比（篮球赛果库 {len(db.rows)} 场）")
    return notes, problems


# ═══════════════════════ 7. 命令行 ═══════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="篮球赛果库和数据模型：补比分、看回测")
    ap.add_argument("--fill", type=int, default=0, metavar="N", help="先读 500 网篮球完场页，补最近 N 天（1～60）的比分")
    ap.add_argument("--days", type=int, default=BT_DAYS, help="回测看最近多少天")
    a = ap.parse_args(argv)
    here = L.app_root(__file__)
    if a.fill:
        n = max(1, min(60, a.fill))
        today = datetime.now(BJT).replace(tzinfo=None)
        labels = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, n + 1)]
        r = lq_fill(here, labels, log=print)
        print(f"读了 {r['ok']} 页，新存 {r['added']} 场，共 {r['total']} 场" + (f"（{r['span']}）" if r["span"] else ""))
    db = BbDB(here)
    if not db.rows:
        print("篮球赛果库是空的（先点一次“一键更新”，或运行 python bb_data.py --fill 30）")
        return 1
    days = sorted({r["k"][:10] for r in db.rows})
    print(f"篮球赛果库 {len(db.rows)} 场（{days[0]} ～ {days[-1]}），{len({r['hid'] for r in db.rows} | {r['aid'] for r in db.rows})} 支球队。")
    r = backtest(db.rows, days=a.days)
    print(check_text(r))
    if r.get("bins"):
        for k, v in r["bins"].items():
            print(f"  模型最大把握 {k}：{v[0]} 场，实际猜对 {('%.0f%%' % (v[1] * 100)) if v[1] is not None else '-'}")
        print(f"  预计总分平均差 {r['t_mae']:.1f} 分（基准 {r['t_base_mae']:.1f}）；预测误差 净胜分 ±{r['sigma_m']:.1f}，总分 ±{r['sigma_t']:.1f}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    raise SystemExit(main())
