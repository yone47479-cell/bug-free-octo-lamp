# -*- coding: utf-8 -*-
"""发帖前把关：把「已经生成的帖子」在发出去之前再检查一遍，免得出低级错误。纯标准库，不联网。

  preflight(...)        发帖前自检：已开赛的场次、夸大用词、数据太旧、重复、空帖、帖子里混进程序变量、长度
  deadlines(...)        每条帖子的「建议发帖时间」（该帖里最早一场开赛前 N 分钟），已经过了就标出来
  odds_snapshot(...)    把这次推单的赔率/让球线存个快照；下次更新时 odds_drift(...) 对比，看市场往哪边动了
  diagnostics(...)      一键诊断包：把排查问题要用的信息（版本、设置、日志尾巴、文件清单、历史概况……）写成 诊断报告.txt
                        （密钥一律打码，不含推单内容之外的隐私）

检查结果是一个个 {"level": "error|warn|info", "post": 帖子名, "code": 类型, "text": 一句话}，操作台用颜色区分。
"""
import json
import os
import platform
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as LY

__version__ = "1.1"

# 帖子名 → 它对应的推单玩法（用来找这条帖子里有哪些比赛、最早几点开赛）
POST_PLAYS: Dict[str, Tuple[str, ...]] = {
    "电竞预测": ("电竞",),
    "竞足": ("竞足", "竞足串关"), "北单": ("北单", "北单串关"), "竞篮": ("竞篮", "竞篮串关"),
    "重点关注": ("竞足",), "胜负彩任九": ("胜负彩", "任九"), "进球半全场": ("4场进球", "6场半全场"),
}
NO_DEADLINE = ("昨日复盘", "周报", "月报")

# 夸大/保证类用词（帖子里不能有）。「保证」前面有 不/无法/不是 这些否定就不算（比如「数据是参考，不是保证」）
FORBIDDEN = ["稳赚", "必中", "包赢", "包中", "必赢", "必红", "稳赢", "稳胆", "稳单", "保证", "百分百", "内幕", "包回血", "带你上岸", "无风险", "零风险", "稳了"]
NEGATIONS = ("不是", "不", "无法", "没有", "并非", "非", "不能", "别信", "没法", "不会")


def _dt(s: Any) -> Optional[datetime]:
    m = re.match(r"\s*(\d{4})-(\d{2})-(\d{2})[ T](\d{2}):(\d{2})", str(s or ""))
    if not m:
        return None
    try:
        return datetime(int(m.group(1)), int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    except ValueError:
        return None


def when_text(t: datetime, now: datetime) -> str:
    """开赛/截止时间读起来顺口：今晚20:00、明天凌晨00:45、10月17日 02:00。"""
    d = (t.date() - now.date()).days
    hm = f"{t:%H:%M}"
    part = "凌晨" if t.hour < 6 else "上午" if t.hour < 12 else "下午" if t.hour < 18 else "晚上"
    if d == 0:
        return ("今晚" if part == "晚上" else "今天" + part) + hm
    if d == 1:
        return "明天" + part + hm
    return f"{t.month}月{t.day}日 {hm}"


def find_forbidden(text: str) -> List[str]:
    """帖子里的夸大用词（带否定的不算）。返回命中的词（去重）。"""
    hit: List[str] = []
    for w in FORBIDDEN:
        for m in re.finditer(re.escape(w), text):
            pre = text[max(0, m.start() - 4):m.start()]
            if any(n in pre for n in NEGATIONS):
                continue
            if w not in hit:
                hit.append(w)
            break
    return hit


def _body_lines(text: str) -> List[str]:
    out = []
    for i, l in enumerate(text.split("\n")):
        s = l.strip()
        if i == 0 or not s:
            continue
        if re.fullmatch(r"[━\-─=—_~·\s]+", s) or s.startswith(("⚠️", "⚠", "#")) or s.startswith("🧵"):
            continue
        out.append(s)
    return out


def _singles(picks: List[Dict[str, Any]], plays: Tuple[str, ...]) -> List[Dict[str, Any]]:
    return [p for p in picks if p.get("play") in plays and "legs" not in p]


def preflight(posts: List[Tuple[str, str]], picks: List[Dict[str, Any]], now: datetime, *, fetched: str = "", limit: int = 25000,
              prev_posts: Optional[List[Dict[str, str]]] = None, weight: Optional[Callable[[str], int]] = None,
              splitter: Optional[Callable[[str, int], List[str]]] = None, stale_hours: float = 6.0) -> List[Dict[str, str]]:
    """发帖前自检。posts：[(名字, 正文)]；picks：今天这批推单；now：北京时间（不带时区）。"""
    issues: List[Dict[str, str]] = []

    def add(level: str, post: str, code: str, text: str) -> None:
        issues.append({"level": level, "post": post, "code": code, "text": text})

    # 1) 已开赛的场次
    for name, _txt in posts:
        plays = POST_PLAYS.get(name)
        if not plays and name == "总览":
            plays = tuple(sum(POST_PLAYS.values(), ()))
        if not plays:
            continue
        ps = [p for p in _singles(picks, plays) if _dt(p.get("kick"))]
        started = [p for p in ps if _dt(p["kick"]) <= now]
        if started:
            seen, names = set(), []
            for p in started:
                k = (p.get("home"), p.get("away"))
                if k not in seen:
                    seen.add(k)
                    names.append(f"{p.get('home')}vs{p.get('away')}")
            allk = {(p.get("home"), p.get("away")) for p in ps}
            all_started = len(seen) == len(allk)
            add("error" if all_started else "warn", name, "started",
                (f"这条里的比赛已经全部开赛了（{'、'.join(names[:4])}），别再发" if all_started
                 else f"有 {len(seen)} 场已经开赛（{'、'.join(names[:4])}{'等' if len(names) > 4 else ''}），发之前把这几场删掉"))
    # 2) 夸大用词
    for name, txt in posts:
        bad = find_forbidden(txt)
        if bad:
            add("error", name, "forbidden", "里面有不该出现的词：" + "、".join(bad) + "（改掉再发）")
    # 3) 程序变量混进帖子
    for name, txt in posts:
        if re.search(r"\bNone\b|\bnan\b|\{[^}\n]{0,30}\}|\bNaN\b|undefined", txt):
            add("error", name, "placeholder", "帖子里混进了程序的变量（None/nan/大括号），别发，把运行日志发给我看")
    # 4) 数据太旧
    ft = _dt(fetched)
    if ft:
        age = (now - ft).total_seconds() / 3600
        if age >= 24:
            add("error", "", "stale", f"表格数据是 {age / 24:.0f} 天前抓的，赔率和让球早变了——先点「一键更新」重新抓")
        elif age >= stale_hours:
            add("warn", "", "stale", f"表格数据是 {age:.0f} 小时前抓的（{fetched}），赔率可能已经变化——发之前最好再点一次「一键更新」")
    # 5) 重复
    for name, plays in POST_PLAYS.items():
        if name == "重点关注":
            continue
        seen_k: Dict[Tuple[Any, ...], int] = {}
        for p in _singles(picks, plays):
            k = (p.get("play"), p.get("market"), p.get("key"))
            seen_k[k] = seen_k.get(k, 0) + 1
        dup = [k for k, v in seen_k.items() if v > 1]
        if dup:
            add("error", name, "duplicate", f"同一场推荐了两次（{dup[0][2]}），不对劲，先别发")
    names_seen: Dict[str, int] = {}
    texts_seen: Dict[str, str] = {}
    for name, txt in posts:
        names_seen[name] = names_seen.get(name, 0) + 1
        body = "\n".join(txt.split("\n")[1:])
        if body in texts_seen and texts_seen[body] != name:
            add("warn", name, "dup_text", f"和「{texts_seen[body]}」那条内容一样，是不是重复了")
        texts_seen.setdefault(body, name)
    for name, c in names_seen.items():
        if c > 1:
            add("warn", name, "dup_name", f"有 {c} 条同名帖子")
    if prev_posts:
        old = {x.get("name"): x.get("text") for x in prev_posts if isinstance(x, dict)}
        same = [n for n, t in posts if old.get(n) == t]
        if same and len(same) == len(posts):
            add("info", "", "same_as_prev", "和上一次生成的内容完全一样（赔率、场次都没变）——如果已经发过了，这次不用再发")
    # 6) 空帖
    for name, txt in posts:
        if len(_body_lines(txt)) < 2:
            add("warn", name, "empty", "内容几乎是空的，发之前看一眼")
    # 7) 长度
    if weight:
        for name, txt in posts:
            w = weight(txt)
            if w > 25000:
                add("error", name, "too_long", f"太长了（约 {w}），超过 X 长帖的上限 25000，发不出去")
            elif limit and limit < 25000 and w > limit:
                k = len(splitter(txt, limit)) if splitter else 0
                add("info", name, "long", f"比每条上限 {limit} 长，会按「串」发" + (f"（拆成 {k} 条）" if k else ""))
    order = {"error": 0, "warn": 1, "info": 2}
    issues.sort(key=lambda i: order[i["level"]])
    return issues


def issue_lines(issues: List[Dict[str, str]]) -> List[str]:
    icon = {"error": "⛔", "warn": "⚠", "info": "ℹ"}
    return [f"{icon[i['level']]} " + (f"【{i['post']}】" if i["post"] else "") + i["text"] for i in issues]


# ════════════════════════════════════════════════════════════════════════════
# 建议发帖时间
# ════════════════════════════════════════════════════════════════════════════
def _deadline_row(name: str, kicks: List[datetime], label: str, now: datetime, lead_min: int, note: str = "") -> Dict[str, Any]:
    """一条帖子的建议发帖时间（kicks：这条帖子里各场的开赛时间 / 售彩截止时间）。"""
    row: Dict[str, Any] = {"post": name, "earliest": None, "suggest": None, "status": "na", "text": note, "kicks": sorted(kicks), "label": label}
    if not kicks:
        return row
    kicks = sorted(kicks)
    e = kicks[0]
    row["earliest"] = e
    future = [k for k in kicks if k > now]
    if not future:
        row.update(status="done", text=f"{label} {when_text(kicks[-1], now)} 已经过了，这条别再发")
        return row
    if e <= now:
        row.update(status="started", text=f"最早一场已开赛，只发还没开赛的（下一场 {when_text(future[0], now)}）")
        return row
    sug = e - timedelta(minutes=lead_min)
    row["suggest"] = sug
    if sug > now:
        row.update(status="ok", text=f"建议 {when_text(sug, now)} 前发（{label} {when_text(e, now)}）")
    else:
        row.update(status="late", text=f"已过建议时间 {when_text(sug, now)}，{label} {when_text(e, now)}——尽快发")
    return row


def _fix_overview(rows: List[Dict[str, Any]], now: datetime) -> None:
    """总览跟着最早的那条帖子一起发。"""
    sug_all = [r["suggest"] for r in rows if r["suggest"] and r["post"] != "总览"]
    for r in rows:
        if r["post"] == "总览" and sug_all:
            m = min(sug_all)
            r["suggest"] = m
            r["status"] = "ok" if m > now else "late"
            r["text"] = f"和第一条一起发，建议 {when_text(m, now)} 前" if m > now else f"和第一条一起发，建议时间 {when_text(m, now)} 已过——尽快"


def deadlines(posts: List[Tuple[str, str]], picks: List[Dict[str, Any]], meta: Dict[str, Any], now: datetime, lead_min: int = 30) -> List[Dict[str, Any]]:
    """每条帖子的建议发帖时间（该帖里最早一场开赛前 lead_min 分钟）。
    status：ok 还有时间｜late 已过建议时间但最早一场还没开｜started 最早一场已开赛｜done 全部已开赛｜na 没有时间限制。"""
    rows: List[Dict[str, Any]] = []
    for name, _t in posts:
        if name in NO_DEADLINE:
            rows.append(_deadline_row(name, [], "", now, lead_min, "没有时间限制，早上先发也行"))
        elif name == "总览":
            rows.append(_deadline_row(name, [], "", now, lead_min, "和第一条一起发（建议放在最前）"))
        elif name in ("胜负彩任九", "进球半全场"):
            dl = _dt(meta.get("sfc_deadline"))
            rows.append(_deadline_row(name, [dl] if dl else [], "售彩截止", now, lead_min, "" if dl else "没查到售彩截止时间，没法给建议"))
        else:
            kicks = sorted({k for k in (_dt(p.get("kick")) for p in _singles(picks, POST_PLAYS.get(name, ()))) if k})
            rows.append(_deadline_row(name, kicks, "最早一场", now, lead_min, "" if kicks else "没查到开赛时间，没法给建议"))
    _fix_overview(rows, now)
    return rows


def deadlines_json(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """能存进 JSON 的样子（时间变成 'YYYY-MM-DD HH:MM' 文字）。"""
    f = lambda t: f"{t:%Y-%m-%d %H:%M}" if t else ""
    return [dict(r, earliest=f(r.get("earliest")), suggest=f(r.get("suggest")), kicks=[f(k) for k in r.get("kicks", [])]) for r in rows]


def refresh_deadlines(rows: List[Dict[str, Any]], now: datetime, lead_min: int = 30) -> List[Dict[str, Any]]:
    """用存下来的开赛时间，按「现在」重新算一遍每条的状态（界面隔一会儿刷新一次，红色标出已经过了的）。输入输出都是 JSON 样子。"""
    out: List[Dict[str, Any]] = []
    for r in rows:
        ks = [k for k in (_dt(x) for x in r.get("kicks", [])) if k]
        note = r.get("text", "") if not ks else ""
        out.append(_deadline_row(r.get("post", ""), ks, r.get("label", "") or "最早一场", now, lead_min, note))
    _fix_overview(out, now)
    return deadlines_json(out)


# ════════════════════════════════════════════════════════════════════════════
# 临场变动：赔率/让球快照对比
# ════════════════════════════════════════════════════════════════════════════
def odds_snapshot(picks: List[Dict[str, Any]], now: datetime) -> Dict[str, Any]:
    """这批推单当时的赔率(SP)、让球线、总分线、方向。串关不记。"""
    items: Dict[str, Any] = {}
    for p in picks:
        if "legs" in p:
            continue
        items[p["id"]] = {"name": f"{p.get('home', '')}vs{p.get('away', '')}", "play": p.get("play"), "label": str(p.get("label", "")),
                          "sp": p.get("sp"), "line": p.get("line"), "total": p.get("total"), "kick": p.get("kick", "")}
    return {"at": f"{now:%H:%M}", "items": items}


def _f(x: Any) -> Optional[float]:
    try:
        return float(str(x).replace("＋", "+").replace("－", "-"))
    except (TypeError, ValueError):
        return None


def odds_drift(old: Optional[Dict[str, Any]], picks: List[Dict[str, Any]], now: datetime, min_pct: float = 0.08) -> List[Dict[str, str]]:
    """和上一次生成时的快照比：参考赔率(北单SP)变了多少、让球线/总分线动没动、推荐方向翻没翻、有没有推荐消失/新增。
    SP 变大 = 市场对推荐方向降温；变小 = 升温。只比还没开赛的。"""
    if not old or not isinstance(old.get("items"), dict):
        return []
    at = old.get("at", "")
    pre = f"和 {at} 那次相比：" if at else "和上次相比："
    out: List[Dict[str, str]] = []
    new = {p["id"]: p for p in picks if "legs" not in p}
    for pid, o in old["items"].items():
        k = _dt(o.get("kick"))
        if k and k <= now:
            continue
        p = new.get(pid)
        nm = o.get("name", pid)
        if p is None:
            out.append({"level": "warn", "kind": "gone", "text": f"{pre}{nm} 这次不推了（赔率/让球变化后不符合条件，或数据不支持了）——如果已经发过，记得补一句更正"})
            continue
        if str(p.get("label", "")) != o.get("label"):
            out.append({"level": "error", "kind": "flip", "text": f"{pre}{nm} 推荐方向变了：{o.get('label')} → {p.get('label')}——已经发过的要更正"})
        a, b = _f(o.get("line")), _f(p.get("line"))
        if a is not None and b is not None and a != b:
            out.append({"level": "warn", "kind": "line", "text": f"{pre}{nm} 的{'让分' if o.get('play') == '竞篮' else '让球'}线 {o.get('line')} → {p.get('line')}，盘口变了，重新核对再发"})
        ta, tb = _f(o.get("total")), _f(p.get("total"))
        if ta is not None and tb is not None and ta != tb:
            out.append({"level": "info", "kind": "total", "text": f"{pre}{nm} 预设总分 {o.get('total')} → {p.get('total')}"})
        sa, sb = _f(o.get("sp")), _f(p.get("sp"))
        if sa and sb and sa > 0 and abs(sb - sa) / sa >= min_pct:
            r = (sb - sa) / sa
            out.append({"level": "warn" if r > 0 else "info", "kind": "cool" if r > 0 else "heat",
                        "text": f"{pre}{nm} 参考赔率 {sa:g} → {sb:g}（{r:+.0%}），" + ("市场对这个方向降温了，再看一眼" if r > 0 else "市场更看好这个方向了")})
    for pid, p in new.items():
        if pid not in old["items"]:
            k = _dt(p.get("kick"))
            if not k or k > now:
                out.append({"level": "info", "kind": "new", "text": f"{pre}新增推荐 {p.get('home', '')}vs{p.get('away', '')}（{p.get('label', '')}）"})
    order = {"error": 0, "warn": 1, "info": 2}
    out.sort(key=lambda i: order[i["level"]])
    return out


# ════════════════════════════════════════════════════════════════════════════
# 一键诊断包
# ════════════════════════════════════════════════════════════════════════════
SECRET_KEYS = re.compile(r"key|token|secret|密钥|口令|密码|password|cookie|authorization", re.I)


def redact(obj: Any) -> Any:
    """把设置里的密钥一类的值打码。"""
    if isinstance(obj, dict):
        return {k: ("***已隐藏***" if (SECRET_KEYS.search(str(k)) and v) else redact(v)) for k, v in obj.items()}
    if isinstance(obj, list):
        return [redact(x) for x in obj]
    if isinstance(obj, str) and re.search(r"[A-Za-z0-9]{28,}", obj):
        return re.sub(r"[A-Za-z0-9_\-]{28,}", "***", obj)
    return obj


def _read_json(path: Path) -> Tuple[Any, str]:
    try:
        return json.loads(path.read_text(encoding="utf-8-sig")), ""
    except OSError as e:
        return None, f"读不了（{e.__class__.__name__}）"
    except ValueError as e:
        return None, f"JSON 格式坏了（{e}）"


def diagnostics(folder: Path, *, versions: Optional[Dict[str, str]] = None, log_tail: Optional[List[str]] = None,
                browser: Optional[Callable[[], Any]] = None, now: Optional[datetime] = None, extra: Optional[List[str]] = None) -> str:
    """生成诊断报告文字（不写文件；调用方写到 诊断报告.txt）。排查问题要的信息都在里面，密钥已打码。"""
    folder = LY.find_root(Path(folder))
    now = now or datetime.now()
    L: List[str] = []
    A = L.append
    A(f"诊断报告  生成于 {now:%Y-%m-%d %H:%M:%S}（电脑本地时间）")
    A("=" * 52)
    A("把这个文件发给我就行；里面的密钥已经打码，没有你的账号信息。")
    A("")
    A("【环境】")
    A(f"  系统：{platform.platform()}")
    A(f"  Python：{sys.version.split()[0]}（{platform.machine()}）")
    A(f"  脚本文件夹：{folder}")
    if versions:
        A("  版本：" + "｜".join(f"{k} {v}" for k, v in versions.items()))
    if browser:
        try:
            b = browser()
            A(f"  截图用的浏览器：{b if b else '没找到 Edge/Chrome（图片快照会退成网页版）'}")
        except Exception as e:  # noqa: BLE001
            A(f"  截图用的浏览器：检查时出错（{e}）")
    A("")
    A("【文件】（只列名字、大小、修改时间，不看内容）")
    org = LY.is_organized(folder)
    scan = [("", folder)] + ([(sub + "\\", folder / sub) for sub in LY.SUBDIRS] if org else [])
    for prefix, dd in scan:
        try:
            fs = sorted([f for f in dd.iterdir() if f.is_file()], key=lambda f: f.name) if dd.exists() else []
        except OSError as e:
            fs = []
            A(f"  读不了文件夹 {dd}：{e}")
        for f in fs:
            try:
                st = f.stat()
                A(f"  {prefix + f.name:<38} {st.st_size / 1024:>9.1f} KB  {datetime.fromtimestamp(st.st_mtime):%m-%d %H:%M}")
            except OSError:
                A(f"  {prefix + f.name}")
        try:
            subs = sorted([x for x in dd.iterdir() if x.is_dir() and not (org and prefix == "" and x.name in LY.SUBDIRS)], key=lambda x: x.name) if dd.exists() else []
        except OSError:
            subs = []
        for x in subs:
            try:
                n = sum(1 for _ in x.iterdir())
            except OSError:
                n = -1
            A(f"  [文件夹] {prefix + x.name}（{n} 项）")
    A("")
    A("【设置】")
    for nm in ("console_settings.json", "brand.json", "rules.json", "manual.json"):
        p = LY.p(folder, nm)
        if not p.exists():
            A(f"  {nm}：没有" + ("（用默认）" if nm in ("brand.json", "rules.json") else ""))
            continue
        data, err = _read_json(p)
        if err:
            A(f"  {nm}：{err}   ← 这个文件有问题")
            continue
        if nm == "brand.json":
            A(f"  {nm}：正常（{len(data)} 项；栏目名「{data.get('栏目名', '')}」，朴素版={data.get('朴素版')}，显示星级={data.get('显示星级', '—')}）")
        elif nm == "rules.json":
            diff = [f"{k}={v}" for k, v in data.items() if k not in ("说明", "各项说明")]
            A(f"  {nm}：正常（{'；'.join(diff)}）")
        elif nm == "manual.json":
            A(f"  {nm}：正常（{len(data) if hasattr(data, '__len__') else '?'} 项）")
        else:
            A(f"  {nm}：" + json.dumps(redact(data), ensure_ascii=False)[:1500])
    A("")
    A("【历史推单】")
    h, err = _read_json(LY.p(folder, "tips_history.json"))
    if not LY.p(folder, "tips_history.json").exists():
        A("  tips_history.json：还没有（第一次点「一键更新」后才会有）")
    elif err:
        A(f"  tips_history.json：{err}   ← 这个文件有问题（会自动用「历史备份」恢复）")
    elif isinstance(h, dict):
        picks = h.get("picks") or {}
        st: Dict[str, int] = {}
        for p in picks.values():
            st[p.get("status", "?")] = st.get(p.get("status", "?"), 0) + 1
        days = sorted(h.get("runs") or {})
        A(f"  推单 {len(picks)} 条（{'｜'.join(f'{k} {v}' for k, v in sorted(st.items()))}）；生成过的日子 {len(days)} 天"
          + (f"，最近一次 {days[-1]}" if days else ""))
    bd = LY.p(folder, "历史备份")
    if bd.exists():
        bs = sorted(bd.glob("*.json"))
        A(f"  历史备份：{len(bs)} 份" + (f"（最新 {bs[-1].name}）" if bs else ""))
    else:
        A("  历史备份：还没有（第二次更新后会有）")
    A("")
    A("【赛果库和模型】")
    r, err = _read_json(LY.p(folder, "results_db.json"))
    if err and LY.p(folder, "results_db.json").exists():
        A(f"  results_db.json：{err}")
    elif isinstance(r, (dict, list)):
        rows = r.get("rows") if isinstance(r, dict) else r
        A(f"  赛果库：{len(rows) if isinstance(rows, list) else '?'} 场")
    else:
        A("  赛果库：还没有")
    m, err = _read_json(LY.p(folder, "model_check.json"))
    if isinstance(m, dict):
        t = m.get("tune") or {}
        A(f"  数据模型回测（{m.get('date', '?')}）：样本 {m.get('n', '?')} 场，过关={m.get('ok')}" + (f"；原因：{m.get('reason')}" if m.get("reason") else "")
          + f"；校准={'启用' if m.get('calib') else '未启用'}；参数择优={t.get('date', '没做过')}{'（已换参数）' if t.get('changed') else ''}")
    else:
        A("  数据模型回测：还没有")
    A("")
    A("【上一次运行】")
    lr, err = _read_json(LY.p(folder, "console_last_run.json"))
    if isinstance(lr, dict):
        A(f"  销售日 {lr.get('day', '?')}｜推单 {lr.get('picks', '?')} 条｜结算 {lr.get('settled', '?')} 条｜表格 {lr.get('xlsx', '?')}")
        for k in ("warnings", "notes", "collect_issues", "rules_warns", "preflight", "drift"):
            v = lr.get(k)
            if v:
                A(f"  {k}（前 8 条）：")
                for x in list(v)[:8]:
                    A("    - " + (x if isinstance(x, str) else json.dumps(x, ensure_ascii=False))[:300])
    elif LY.p(folder, "console_last_run.json").exists():
        A(f"  console_last_run.json：{err}")
    else:
        A("  还没有运行记录")
    A("")
    A("【界面错误日志 console_error.log（最后 25 行）】")
    p = LY.p(folder, "console_error.log")
    if p.exists():
        try:
            A("\n".join("  " + x for x in p.read_text(encoding="utf-8", errors="replace").splitlines()[-25:]))
        except OSError as e:
            A(f"  读不了：{e}")
    else:
        A("  没有错误日志（好事）")
    A("")
    A("【运行日志（界面里最后 60 行）】")
    if log_tail:
        A("\n".join("  " + str(redact(x)) for x in log_tail[-60:]))
    else:
        A("  （没有拿到界面里的日志；命令行运行时看命令行输出）")
    if extra:
        A("")
        A("【其他】")
        L.extend("  " + x for x in extra)
    return "\n".join(L) + "\n"
