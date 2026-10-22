#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""市场赔率数据：澳客（okooo.cn）的两个公开页面，只用 Python 3.9+ 标准库。

  · 竞彩赛程页  https://www.okooo.cn/jingcai/
        每场竞足的「赛事编号（周五003）+ 开赛时间 + 竞彩 SP（胜平负、让球胜平负）+ 两队联赛排名」。
        编号和 500 网竞足表里的一模一样，所以按「编号 + 开赛时间」就能精确配上，不用猜队名。
  · 凯利方差页  https://www.okooo.cn/jingcai/shuju/peilv/
        每场约 25 家公司的初始/最新胜平负赔率。每家公司的赔率先去掉抽水（换成加起来是 100% 的概率），
        再取各家的中位数，就是「市场共识」——比单看近况硬得多的一份独立参考。

用在哪里（gen_tips.py 调用）
  1. 竞足有场次没配上北单（队名叫法差太多）时，用竞足自己的 SP 当参考赔率，不再因为配不上就放弃这一场；
  2. 每场足球单关的「两队数据对比」里加一句市场共识；推荐的那一方市场只给很低的赢球概率时，
     「数据支持」降成「部分支持」（不进串关），低到 30% 以下直接算「数据不支持」。

守规矩：先读 robots.txt，只读它允许的页面，也只在它写的 Visit-time（UTC 01:30–18:30）里读；每次共读 2 个页面，页面之间隔几秒；
被拒绝（403/429）或读不到就算了，不绕。读不到不影响出推单（只是少了这一层参考）。
命令行测试：python market_data.py   （读这两个页面，打印认出了几场、前几场的赔率和市场共识）
"""
from __future__ import annotations

import argparse
import json
import re
import statistics
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as L

BJT = timezone(timedelta(hours=8))
__version__ = "1.0"

HOST = "https://www.okooo.cn"
JC_PATH = "/jingcai/"
ODDS_PATH = "/jingcai/shuju/peilv/"
GAP = 4.0                               # 两个页面之间隔几秒
MIN_COMPANIES = 6                       # 至少几家公司的赔率才算「市场共识」
MKT_WEAK = 0.40                         # 推荐方被市场给的赢球概率低于这个 → 「数据支持」降成「部分支持」
MKT_AGAINST = 0.30                      # 低于这个 → 「数据不支持」
SNAP_FILE = "market_latest.json"        # 最近一次读到的内容（只用来排查问题；不会拿旧数据当今天的用）


# ═══════════════════════ 1. 小工具 ═══════════════════════
def _f(s: Any) -> Optional[float]:
    try:
        v = float(str(s).strip())
        return v if v > 0 else None
    except (TypeError, ValueError):
        return None


def probs(odds: Optional[List[Optional[float]]]) -> Optional[List[float]]:
    """三个赔率 → 去掉抽水后的概率（加起来 100%）。有一个缺就返回 None。"""
    if not odds or len(odds) != 3 or any(o is None or o <= 1.0 for o in odds):
        return None
    inv = [1.0 / o for o in odds]                   # type: ignore[operator]
    t = sum(inv)
    return [x / t for x in inv]


def _txt(h: str) -> str:
    h = re.sub(r"(?is)<span[^>]*font-size\s*:\s*0[^>]*>.*?</span>", "", h)       # 澳客在公司名里夹的看不见的字符
    return re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", "", h).replace("&nbsp;", " ")).strip()


def _rank(s: Optional[str]) -> Optional[int]:
    m = re.search(r"\[\s*(\d{1,2})\s*\]", s or "")
    return int(m.group(1)) if m else None


# ═══════════════════════ 2. 解析：竞彩赛程页 ═══════════════════════
def parse_jc(html: str) -> List[Dict[str, Any]]:
    """每场一个字典：{code 周五003, mid, lg, home, away, kick 'YYYY-MM-DD HH:MM', rq 让球数(主队，-1=主让一球), sp [主胜,平,客胜]|None,
    rqsp [让球胜,让球平,让球负]|None, hr, ar 两队联赛排名|None, ended 是否已停售}。认不出的块跳过。"""
    out: List[Dict[str, Any]] = []
    for blk in re.split(r'(?=<div class="touzhu_1")', html)[1:]:
        head = blk[:1200]
        code = re.search(r'data-ordercn="([^"]+)"', head)
        mid = re.search(r'data-mid="(\d+)"', head)
        kick = re.search(r'title="比赛时间:\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})', blk)
        if not (code and kick):
            continue
        rq = re.search(r'data-rq="\s*([+-]?\d+)\s*"', head)
        lg = re.search(r'class="saiming[^"]*"[^>]*title="([^"]*)"', blk)
        names = re.findall(r'class="zhum[^"]*"\s+title="([^"]*)"', blk)
        i1 = blk.find('class="rangqiuspf')
        sec1, sec2 = (blk[:i1], blk[i1:]) if i1 > 0 else (blk, "")
        i2 = sec2.find("<!--更多-->")
        if i2 > 0:
            sec2 = sec2[:i2]

        def three(sec: str) -> Optional[List[float]]:
            v = [_f(x) for x in re.findall(r'<div[^>]*class="peilv[^"]*"[^>]*>\s*([^<\s]*)\s*</div>', sec)]
            return v[:3] if len(v) >= 3 and all(x is not None and x > 1.0 for x in v[:3]) else None   # type: ignore[return-value]
        ranks = re.findall(r'<div class="paim[^"]*">\s*<p class="p2">([^<]*)</p>', sec1)
        out.append({
            "code": code.group(1), "mid": mid.group(1) if mid else "", "lg": lg.group(1) if lg else "",
            "home": names[0] if names else "", "away": names[1] if len(names) > 1 else "",
            "kick": kick.group(1), "rq": int(rq.group(1)) if rq else 0,
            "sp": three(sec1), "rqsp": three(sec2),
            "hr": _rank(ranks[0]) if ranks else None, "ar": _rank(ranks[1]) if len(ranks) > 1 else None,
            "ended": 'data-end="1"' in head,
        })
    return out


# ═══════════════════════ 3. 解析：凯利方差页（各公司赔率） ═══════════════════════
def parse_odds(html: str, now: Optional[datetime] = None) -> List[Dict[str, Any]]:
    """每场一个字典：{code, lg, kick 'YYYY-MM-DD HH:MM', home, away, rq, mid, companies [{name, init [3], last [3]}]}。"""
    now = (now or datetime.now(BJT)).astimezone(BJT).replace(tzinfo=None) if (now is None or now.tzinfo) else now
    out: List[Dict[str, Any]] = []
    for blk in re.split(r'(?=<div class="clearfix container_wrapper pankoudata">)', html)[1:]:
        t = re.sub(r"\s+", " ", blk)
        hd = re.search(r'<p class="float_l">(.*?)</p>', t)
        bs = re.findall(r"<b>([^<]*)</b>", hd.group(1)) if hd else []
        tm = re.search(r"<span>([^<]*)</span><em[^>]*>\(\s*([+-]?\d+)\s*\)</em><strong>VS</strong><b>([^<]*)</b>", t)
        if len(bs) < 3 or not tm:
            continue
        md = re.match(r"(\d{1,2})-(\d{1,2}) (\d{1,2}):(\d{2})", bs[2])
        if not md:
            continue
        try:
            dt = datetime(now.year, int(md.group(1)), int(md.group(2)), int(md.group(3)), int(md.group(4)))
        except ValueError:
            continue
        if dt < now - timedelta(days=120):               # 年底读到明年一月的比赛
            dt = dt.replace(year=dt.year + 1)
        elif dt > now + timedelta(days=240):
            dt = dt.replace(year=dt.year - 1)
        mid = re.search(r"/soccer/match/(\d+)/", t)
        comps: List[Dict[str, Any]] = []
        for row in re.findall(r"<tr[^>]*>.*?</tr>", t):
            if "csspDataObj" not in row:
                continue
            first = re.search(r"<td[^>]*>(.*?)</td>", row)
            init = [_f(x) for x in re.findall(r'<span class="csspDataObj">\s*([\d.]+)\s*</span>', row)]
            last = [_f(x) for x in re.findall(r'<span class="spDataObj">\s*([\d.]+)\s*</span>', row)]
            if len(init) >= 3 and len(last) >= 3:
                comps.append({"name": _txt(first.group(1)) if first else "", "init": init[:3], "last": last[:3]})
        out.append({"code": bs[0], "lg": bs[1], "kick": dt.strftime("%Y-%m-%d %H:%M"), "home": tm.group(1), "away": tm.group(3),
                    "rq": int(tm.group(2)), "mid": mid.group(1) if mid else "", "companies": comps})
    return out


def consensus(companies: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """各家公司「最新」赔率去水后的概率取中位数 → 市场共识；同样算一份「初始」的，看这段时间市场往哪边走。"""
    def med(key: str) -> Optional[List[float]]:
        ps = [p for p in (probs(c.get(key)) for c in companies) if p]
        if len(ps) < MIN_COMPANIES:
            return None
        m = [statistics.median(p[k] for p in ps) for k in range(3)]
        s = sum(m)
        return [x / s for x in m]
    last = med("last")
    if last is None:
        return None
    init = med("init")
    n = sum(1 for c in companies if probs(c.get("last")))
    return {"n": n, "p": last, "p0": init}


# ═══════════════════════ 4. 配对：500 网表里的一场 ↔ 澳客的一场 ═══════════════════════
class Market:
    """一次读到的全部内容。lookup(赛事编号, 开赛时间) → 这一场的 {sp, rqsp, rq, cons, hr, ar, mid, home, away}，找不到返回 None。"""

    def __init__(self, jc: Optional[List[Dict[str, Any]]] = None, odds: Optional[List[Dict[str, Any]]] = None):
        self.jc = jc or []
        self.odds = odds or []
        self.errors: List[str] = []
        self.asof = ""
        self._ix: Dict[Tuple[str, str], Dict[str, Any]] = {}
        for r in self.jc:
            self._ix[(r["code"], r["kick"])] = {"code": r["code"], "kick": r["kick"], "home": r["home"], "away": r["away"], "lg": r["lg"],
                                              "mid": r["mid"], "sp": r["sp"], "rqsp": r["rqsp"], "rq": r["rq"], "hr": r["hr"], "ar": r["ar"],
                                              "ended": r["ended"], "cons": None}
        for o in self.odds:
            rec = self._ix.get((o["code"], o["kick"]))
            if rec is None:
                rec = self._ix[(o["code"], o["kick"])] = {"code": o["code"], "kick": o["kick"], "home": o["home"], "away": o["away"], "lg": o["lg"],
                                                        "mid": o["mid"], "sp": None, "rqsp": None, "rq": o["rq"], "hr": None, "ar": None,
                                                        "ended": False, "cons": None}
            rec["cons"] = consensus(o["companies"])

    def __bool__(self) -> bool:
        return bool(self._ix)

    def lookup(self, code: str, kick: str) -> Optional[Dict[str, Any]]:
        return self._ix.get(((code or "").strip(), (kick or "").strip()[:16]))

    def summary(self) -> str:
        n_sp = sum(1 for r in self._ix.values() if r["sp"])
        n_c = sum(1 for r in self._ix.values() if r["cons"])
        return f"澳客：{len(self.jc)} 场竞足有 SP、{len(self.odds)} 场有各公司赔率（其中 {n_c} 场够 {MIN_COMPANIES} 家，能算市场共识）"


# ═══════════════════════ 5. 读网页（守 robots.txt 和访问时间段） ═══════════════════════
def _visit_ok(win: Tuple[str, str], now: Optional[time.struct_time] = None) -> bool:
    """Visit-time（UTC，HHMM-HHMM）：现在在不在允许的时间段里（跨午夜也支持）。"""
    now = now or time.gmtime()
    cur = now.tm_hour * 100 + now.tm_min
    a, b = int(win[0]), int(win[1])
    return (a <= cur <= b) if a <= b else (cur >= a or cur <= b)


def _fetcher_cls():
    import sina_data as SD

    class MarketFetcher(SD.WanchangFetcher):
        """用和完场页同一套读法（robots.txt、间隔、失败就停），再多守一条 robots 里的 Visit-time。"""
        retry_codes = (429, 503)                       # 被拒绝（403）就停，不反复试

        def __init__(self, *a: Any, **k: Any):
            super().__init__(*a, **k)
            self.visit: Optional[Tuple[str, str]] = None

        def check_robots(self) -> str:
            if self.rules_ready:
                return self._visit_msg()
            code, text, err = self._get(self.host + "/robots.txt")
            if code == 200:
                self.rules = SD._robots_rules(text)
                m = re.search(r"(?im)^\s*visit-time\s*:\s*(\d{4})\s*-\s*(\d{4})", text)
                if m:
                    self.visit = (m.group(1), m.group(2))
            elif code in (404, 410):
                self.rules = None
            else:
                return f"读不到网站的 robots.txt（{err or code}），为守规矩就不继续了"
            self.rules_ready = True
            return self._visit_msg()

        def _visit_msg(self) -> str:
            if self.visit and not _visit_ok(self.visit):
                return f"robots.txt 只让在 UTC {self.visit[0]}-{self.visit[1]} 访问，现在不在这个时间段，先不读"
            return ""

        def path_for(self, label: Optional[str]) -> str:       # type: ignore[override]
            return label or "/"
    return MarketFetcher


def fetch(folder: Optional[Path] = None, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
          proxy: str = "", host: Optional[str] = None, gap: Optional[float] = None, sleep: Callable[[float], None] = time.sleep,
          now: Optional[datetime] = None) -> Market:
    """读两个页面并解析。任何问题都不抛异常：读不到就返回空的 Market（errors 里写原因）。"""
    say = log or (lambda m: None)
    mk = Market()
    now = now or datetime.now(BJT)
    try:
        F = _fetcher_cls()(host=host or HOST, gap=GAP if gap is None else gap, proxy=proxy, sleep=sleep, cancel=cancel)
    except Exception as exc:  # noqa: BLE001
        mk.errors.append(f"没法读澳客（{type(exc).__name__}: {exc}）")
        return mk
    jc: List[Dict[str, Any]] = []
    odds: List[Dict[str, Any]] = []
    for path, name in ((JC_PATH, "竞彩赛程页"), (ODDS_PATH, "凯利方差页")):
        html, err = F.page(path)
        if err == "已停止":
            mk.errors.append("已停止")
            break
        if err:
            mk.errors.append(f"澳客{name}没读成：{err}")
            say(f"  ⚠ 澳客{name}没读成：{err}")
            if "robots" in err or "403" in err or "Visit-time" in err or "访问" in err or F.fail >= 2:
                break
            continue
        try:
            rows = parse_jc(html) if path == JC_PATH else parse_odds(html, now)
        except Exception as exc:  # noqa: BLE001
            mk.errors.append(f"澳客{name}读到了但解析出错：{exc}")
            say(f"  ⚠ 澳客{name}解析出错：{exc}")
            continue
        if not rows:
            mk.errors.append(f"澳客{name}读到了，但里面一场比赛都没认出来（网站可能改版了）")
            say(f"  ⚠ 澳客{name}里一场比赛都没认出来（网站可能改版了）")
            continue
        if path == JC_PATH:
            jc = rows
        else:
            odds = rows
    mk2 = Market(jc, odds)
    mk2.errors = mk.errors
    mk2.asof = now.astimezone(BJT).strftime("%H:%M")
    if folder is not None and mk2:
        try:                                              # 留一份最近读到的（排查用）
            snap = {"asof": now.astimezone(BJT).strftime("%Y-%m-%d %H:%M"), "jc": mk2.jc, "odds": mk2.odds}
            L.p(folder, SNAP_FILE).write_text(json.dumps(snap, ensure_ascii=False), encoding="utf-8")
        except OSError:
            pass
    return mk2


# ═══════════════════════ 6. 给「两队数据对比」补一句市场共识 ═══════════════════════
def _pc(x: float) -> str:
    return f"{x:.0%}"


def market_text(rec: Dict[str, Any], home: str, away: str) -> str:
    bits: List[str] = []
    c = rec.get("cons")
    if c:
        p = c["p"]
        bits.append(f"市场共识（澳客 {c['n']} 家公司最新赔率去水后取中位数）：{home}胜{_pc(p[0])}/平{_pc(p[1])}/{away}胜{_pc(p[2])}")
        if c.get("p0"):
            d = p[0] - c["p0"][0]
            if abs(d) >= 0.04:
                bits.append(f"{home}胜的概率比初盘{'升' if d > 0 else '降'}了{abs(d) * 100:.0f}个百分点")
    sp = probs(rec.get("sp"))
    if sp:
        bits.append(f"竞彩 SP 去水后：{home}胜{_pc(sp[0])}/平{_pc(sp[1])}/{away}胜{_pc(sp[2])}")
    hr, ar = rec.get("hr"), rec.get("ar")
    if hr or ar:
        bits.append(f"联赛排名：{home}{('第%d' % hr) if hr else '—'}、{away}{('第%d' % ar) if ar else '—'}")
    return "；".join(bits)


def annotate(notes: List[Dict[str, Any]], matches: List[Dict[str, Any]], log: Optional[Callable[[str], None]] = None) -> int:
    """matches 里带 mkt（Market.lookup 的结果）的场次，给对应的 note 补一句市场共识；
    推荐方向是「某队赢」（need==1）时，市场给这一方的赢球概率太低 → 降级（支持→部分支持；<30% → 不支持）。返回改了几条结论。"""
    say = log or (lambda m: None)
    import team_data as T
    byk = {(m["home"], m["away"]): m for m in matches}
    changed = 0
    for n in notes:
        mk = tuple(n.get("mk") or ())
        m = byk.get(mk)  # type: ignore[arg-type]
        rec = (m or {}).get("mkt")
        if not m or not rec:
            continue
        txt = market_text(rec, m["home"], m["away"])
        if not txt:
            continue
        base, sep, _tail = n["note"].rpartition("。")
        base = base if sep else n["note"]
        verdict, why = n["verdict"], (n.get("why", "").split("：", 1) + [""])[1] if "：" in n.get("why", "") else n.get("why", "")
        side, need = m.get("side"), m.get("need", 1)
        c = rec.get("cons")
        if c and side in ("home", "away") and need == 1:
            ps = c["p"][0] if side == "home" else c["p"][2]
            who = m["home"] if side == "home" else m["away"]
            if ps < MKT_AGAINST and verdict != "against":
                verdict, why = "against", f"市场共识只给{who}赢球{_pc(ps)}，和推荐方向对不上"
            elif ps < MKT_WEAK and verdict == "support":
                verdict, why = "mixed", f"市场共识只给{who}赢球{_pc(ps)}，不算稳"
        new = T.finish_note(m, base + "；" + txt, verdict, n.get("lean"), n.get("score"), why)
        if new["verdict"] != n["verdict"]:
            changed += 1
            say(f"    市场共识改了结论：{m['home']}vs{m['away']}：{n['verdict']} → {new['verdict']}（{why}）")
        n["note"], n["verdict"], n["why"] = new["note"], new["verdict"], new["why"]
        n["mkt"] = True
    return changed


# ═══════════════════════ 7. 命令行 ═══════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="读澳客的竞彩 SP 和各公司赔率，看能认出多少场")
    ap.add_argument("--proxy", default="")
    a = ap.parse_args(argv)
    here = L.app_root(__file__)
    mk = fetch(here, log=print, proxy=a.proxy)
    for e in mk.errors:
        print("·", e)
    if not mk:
        print("一场都没读到。")
        return 1
    print(mk.summary())
    for r in mk.jc[:6]:
        rec = mk.lookup(r["code"], r["kick"]) or {}
        c = rec.get("cons")
        print(f"  {r['code']} {r['lg']} {r['kick']} {r['home']}({r['rq']:+d}){'' if r['rq'] else ''}vs{r['away']}  SP {r['sp']}  让球SP {r['rqsp']}"
              + (f"  共识 {[round(x, 2) for x in c['p']]}（{c['n']}家）" if c else ""))
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    raise SystemExit(main())
