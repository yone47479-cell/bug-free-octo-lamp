# -*- coding: utf-8 -*-
"""
snapshot.py —— 给每条推单帖子做「图片快照」（PNG），发 X 时可以直接配图。只用 Python 自带的库，不用装任何东西。

做法：把每条帖子排成一张固定风格的卡片（一个 HTML 页面），再让你电脑里自带的 Edge / Chrome 在后台悄悄截图（不会弹窗口）。
图片里的字就是帖子里的字（战绩、场次、推荐、比分参考……全部来自帖子本身），不加任何新的数据、也不写夸大的话。
找不到 Edge / Chrome 时，不会报错退出：照样生成一个「快照.html」，用浏览器打开就能看到所有卡片（可以自己截图）。

用法：
  python snapshot.py                       # 用 tips_history.json 里最近一次生成的推单，出图到 推单图片_日期 文件夹
  python snapshot.py --day 2026-10-16      # 指定哪一天
  python snapshot.py --theme 深色          # 深色底
"""
from __future__ import annotations

import argparse
import html
import json
import os
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as L

__version__ = "1.4"
CARD_W = 800            # 卡片宽度（CSS 像素）；图片实际宽度 = (CARD_W + 2*PAD) × SCALE
PAD = 28                # 卡片四周的底色留白
SCALE = 2               # 清晰度倍数（2 = 图片宽 1712 像素，文字很清楚；文件一般几百 KB，X 允许最大 5MB）
IMG_DIR_FMT = "推单图片_{day}"
HTML_NAME = "快照.html"
SHOT_TIMEOUT = 90       # 浏览器一次截图最长等多久（秒）
SHOT_EXTRA = 200        # 截图窗口比卡片多开的高度（截完会裁掉）
MAX_CARD_H = 1900       # 一张图最高多少（CSS 像素，×清晰度 = 3800 像素，X 也能完整显示）；更高的帖子自动拆成几张

BRAND_FALLBACK: Dict[str, Any] = {"栏目名": "今日热推", "署名": "", "图片配色": "浅色", "图片风格": "按玩法", "图片水印": "", "榜单勋章": ["🥇", "🥈", "🥉"]}

SEP_RE = re.compile(r"^[━─—=\-]{6,}$")
HEAD_RE = re.compile(r"^(?P<ic>[^\s【]{0,4})\s*【(?P<inner>[^】]+)】(?P<rest>.*)$")
THREAD_RE = re.compile(r"🧵\s*(\d+)\s*/\s*(\d+)")
ROW_RE = re.compile(r"^(\d{1,2})\s+(.+?)\s+▶\s+(.+)$")          # 胜负彩/进球/半全场的一行：序号 对阵 ▶ 选项
TILE_RE = re.compile(r"^([\u4e00-\u9fffA-Za-z0-9]+?)\s+(\d+)/(\d+)$")                  # 战绩格子：竞足 4/8
ITEM_RE = re.compile(r"[✅❌⏳]\S+")
PARLAY_RE = re.compile(r"^🎯(?P<lab>\d+串\d+|任九\S*?|串关\S*?)：(?P<val>.*)$")
SCORE_RE = re.compile(r"^🎯比分参考 \d+:\d+")


def esc(s: Any) -> str:
    return html.escape(str(s), quote=False)


# ════════════════════════════════════════════════════════════════════════════
# 1. 把一条帖子的文字拆成「头 / 身 / 尾」
# ════════════════════════════════════════════════════════════════════════════
def split_post(text: str) -> Dict[str, Any]:
    lines = [l.rstrip() for l in str(text).replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    out: Dict[str, Any] = {"brand": "", "play": "", "sub": [], "thread": None, "icon": "", "body": [], "tips": [], "tags": [], "sign": []}
    if not lines:
        return out
    m = HEAD_RE.match(lines[0].strip())
    if m:
        inner = m.group("inner")
        out["brand"], _, out["play"] = inner.partition("·")
        out["icon"] = m.group("ic").strip()
        rest = m.group("rest")
        tm = THREAD_RE.search(rest)
        if tm:
            out["thread"] = (int(tm.group(1)), int(tm.group(2)))
            rest = THREAD_RE.sub("", rest)
        out["sub"] = [x.strip() for x in rest.split("｜") if x.strip()]
        rest_lines = lines[1:]
    else:
        out["play"] = lines[0].strip()
        rest_lines = lines[1:]
    # 尾巴：最后一条分隔线之后（提示语、署名、话题标签）
    seps = [i for i, l in enumerate(rest_lines) if SEP_RE.match(l.strip())]
    body, foot = rest_lines, []
    if seps:
        last = seps[-1]
        foot = rest_lines[last + 1:]
        body = rest_lines[:last]
        if seps[0] == 0 and body:
            body = body[1:] if SEP_RE.match(body[0].strip()) else body
    else:
        # 没有分隔线（朴素版）：最后一行如果是话题标签就当尾巴
        while rest_lines and rest_lines[-1].strip().startswith("#"):
            foot.insert(0, rest_lines.pop())
        body = rest_lines
    for l in foot:
        t = l.strip()
        if not t:
            continue
        if t.startswith("#"):
            out["tags"].append(t)
        elif "仅供参考" in t or "理性购彩" in t:
            out["tips"].append(t)
        else:
            out["sign"].append(t)
    # 去掉身体开头结尾的空行
    while body and not body[0].strip():
        body.pop(0)
    while body and not body[-1].strip():
        body.pop()
    out["body"] = body
    return out


def _raw_parts(text: str) -> Tuple[str, str, List[str], List[str]]:
    """帖子文字 → (标题行, 分隔线, 身体各行, 尾巴各行)。和 split_post 用同一套规矩，但保留原文，拆图时要原样拼回去。"""
    lines = [l.rstrip() for l in str(text).replace("\r\n", "\n").split("\n")]
    while lines and not lines[0].strip():
        lines.pop(0)
    if not lines:
        return "", "", [], []
    head, rest = lines[0], lines[1:]
    seps = [i for i, l in enumerate(rest) if SEP_RE.match(l.strip())]
    sep = rest[seps[0]].strip() if seps else "━━━━━━━━━━━━"
    if len(seps) >= 2 or (seps and seps[0] > 0):
        last = seps[-1]
        body, foot = rest[:last], rest[last + 1:]
        if body and SEP_RE.match(body[0].strip()):
            body = body[1:]
    else:
        body, foot = (rest[1:] if seps else list(rest)), []
        while body and body[-1].strip().startswith("#"):
            foot.insert(0, body.pop())
    return head, sep, body, foot


BLOCK_STARTS = ("📋",)                       # 没有空行隔开的长帖（复盘）在这些行前面断开
DEFAULT_MEDALS = ("🥇", "🥈", "🥉", "🔹")


def _blocks(body: List[str], medals: Tuple[str, ...] = DEFAULT_MEDALS) -> List[List[str]]:
    """身体各行 → 一块一块：空行隔开；榜单上每一场（勋章开头）自己一块；复盘里每个「📋」小节自己一块。"""
    blocks: List[List[str]] = []
    cur: List[str] = []
    for l in body:
        t = l.strip()
        if not t:
            if cur:
                blocks.append(cur)
                cur = []
            continue
        first = t.split(None, 1)[0] if t else ""
        if cur and (t.startswith(BLOCK_STARTS) or (first in medals and len(t.split()) > 1)):
            blocks.append(cur)
            cur = []
        cur.append(l)
    if cur:
        blocks.append(cur)
    return blocks


def split_into_parts(text: str, k: int, medals: Optional[List[str]] = None) -> List[str]:
    """太长的帖子拆成 k 份（按「一场一块」的边界断开，不会把一场切成两半）；每份都带原来的标题、提示语和话题标签。
    拆不开（只有一块）就原样返回。"""
    head, sep, body, foot = _raw_parts(text)
    blocks = _blocks(body, tuple(medals or ()) + DEFAULT_MEDALS)
    k = min(int(k), len(blocks))
    if k <= 1:
        return [text]
    w = [len(b) + 1 for b in blocks]
    total = float(sum(w))
    groups: List[List[List[str]]] = [[]]
    acc = 0.0
    for i, b in enumerate(blocks):
        g = len(groups)
        if groups[-1] and g < k and acc + w[i] / 2.0 > total * g / k and len(blocks) - i >= k - g:
            groups.append([])
        groups[-1].append(b)
        acc += w[i]
    out = []
    for grp in groups:
        lines = [head, sep]
        for j, b in enumerate(grp):
            if j:
                lines.append("")
            lines += b
        lines += ["", sep] + foot
        out.append("\n".join(lines))
    return out


# ════════════════════════════════════════════════════════════════════════════
# 2. 身体各种行 → HTML 片段
# ════════════════════════════════════════════════════════════════════════════
def _flags(s: str) -> Tuple[str, bool, bool]:
    up, dr = "📈" in s, "防平" in s
    s = s.replace("📈", "").replace("防平", "")
    return re.sub(r"\s+", " ", s).strip(), up, dr


def _badge(up: bool = False, dr: bool = False) -> str:
    return ('<em class="dr">防平</em>' if dr else "") + ('<em class="up">📈数据支持</em>' if up else "")


def _teams(s: str, cls: str = "tm") -> str:
    s = s.strip()
    for sep in (" vs ", "vs", " VS "):
        if sep in s:
            a, b = s.split(sep, 1)
            return f'<div class="{cls}"><span>{esc(a.strip())}</span><i>vs</i><span>{esc(b.strip())}</span></div>'
    return f'<div class="{cls}"><span>{esc(s)}</span></div>'


def _pick_row(line: str) -> str:
    """🧭胜平负：桑德兰胜 防平 📈｜让球(+1)负  →  一排小标签"""
    s = line.strip()[1:].strip() if line.strip().startswith(("🧭", "👉")) else line.strip()
    chips, up_any = [], False
    for seg in [x.strip() for x in s.split("｜") if x.strip()]:
        txt, up, dr = _flags(seg)
        up_any = up_any or up
        lab, val = "", txt
        if "：" in txt:
            lab, val = txt.split("：", 1)
        elif txt.startswith("胜分差 "):
            lab, val = "胜分差", txt[4:]
        chips.append(f'<span class="pc">{"<b>" + esc(lab) + "</b>" if lab else ""}{esc(val)}</span>' + _badge(dr=dr))
    return '<div class="pk"><span class="cp">🧭</span>' + "".join(chips) + _badge(up=up_any) + "</div>"


def _score_row(line: str) -> str:
    """🎯比分参考 1:0｜1:1｜2:0　⚽进球 2、3、4球   /   ⚽进球数 2、3、4球"""
    parts = [p.strip() for p in re.split(r"[\s　]*(?=⚽)", line.strip()) if p.strip()]
    out = []
    for p in parts:
        if p.startswith("🎯比分参考"):
            bits = p.split(None, 1)
            sc = [x for x in (bits[1] if len(bits) > 1 else "").split("｜") if x.strip()]
            out.append('<span class="sl">🎯比分参考</span>' + "".join(f'<span class="sp">{esc(x.strip())}</span>' for x in sc))
        elif p.startswith("⚽"):
            out.append(f'<span class="gl">{esc(p)}</span>')
        else:
            out.append(f'<span class="gl">{esc(p)}</span>')
    return '<div class="sc">' + "".join(out) + "</div>"


def _chips(vals: List[str], cls: str = "chip") -> str:
    out = []
    for v in vals:
        up = "📈" in v
        txt = re.sub(r"\s+", " ", v.replace("📈", "")).strip()
        if txt:
            out.append(f'<span class="{cls}">{esc(txt)}</span>' + _badge(up=up))
    return "".join(out)


def _entry(rank: str, lines: List[str]) -> str:
    """热度榜上的一场（勋章 + 内容）。有 🧭 那一行的是竞足/竞篮卡片；没有的是北单一行式。"""
    first = lines[0]
    rest = [l.strip() for l in lines[1:] if l.strip()]
    if any(l.startswith("👉") for l in rest) and not any(l.startswith("🧭") for l in rest):
        # 综合推单：竞足011｜伯恩茅斯 vs 格拉茨风暴 ⏰03:00(次日) / 👉伯恩茅斯胜｜综合76% ★★★ ⚠️分歧 / 赔率85%｜模型44%｜📈数据支持
        tag, _, tail = first.partition("｜")
        km = re.search(r"\s*(⏰\S+)\s*$", tail)
        kick = km.group(1) if km else ""
        teams = tail[:km.start()] if km else tail
        inner = [f'<div class="meta">{esc(tag)}{(" " + esc(kick)) if kick else ""}</div>', _teams(teams)]
        for l in rest:
            if l.startswith("👉"):
                inner.append(_pick_row(l))
            elif l.startswith(("🎯", "⚽")):
                inner.append(_score_row(l))
            else:
                inner.append(f'<div class="bs">{esc(l)}</div>')
        return f'<div class="m"><div class="rk">{esc(rank)}</div><div class="mb">{"".join(inner)}</div></div>'
    if any(l.startswith("🧭") for l in rest):
        meta = first
        teams = next((l for l in rest if not l.startswith(("🧭", "🎯", "⚽", "📊"))), "")
        inner = [f'<div class="meta">{esc(meta)}</div>']
        if teams:
            inner.append(_teams(teams))
        for l in rest:
            if l.startswith("🧭"):
                inner.append(_pick_row(l))
            elif l.startswith(("🎯", "⚽")):
                inner.append(_score_row(l))
            elif l.startswith("📊"):
                inner.append(f'<div class="bs">{esc(l)}</div>')
        return f'<div class="m"><div class="rk">{esc(rank)}</div><div class="mb">{"".join(inner)}</div></div>'
    # 北单：93 费伦茨瓦罗斯vs比尔森｜让球(0)胜｜SP 1.53 📈
    segs = [x.strip() for x in first.split("｜") if x.strip()]
    num, teams = "", segs[0] if segs else first
    mm = re.match(r"^(\S+)\s+(.+)$", teams)
    if mm:
        num, teams = mm.group(1), mm.group(2)
    up_any, chips = False, []
    for k, seg in enumerate(segs[1:]):
        txt, up, dr = _flags(seg)
        up_any = up_any or up
        cls = "pc" if k == 0 else "pc soft"
        chips.append(f'<span class="{cls}">{esc(txt)}</span>{_badge(dr=dr)}')
    inner = [f'<div class="meta">{esc(num)}</div>' if num else "", _teams(teams, "tm sm"),
             '<div class="pk"><span class="cp">🧭</span>' + "".join(chips) + _badge(up=up_any) + "</div>"]
    inner += [_score_row(l) for l in rest if l.startswith(("🎯", "⚽"))]
    inner += [f'<div class="bs">{esc(l)}</div>' for l in rest if l.startswith("📊")]
    return f'<div class="m"><div class="rk">{esc(rank)}</div><div class="mb">{"".join(inner)}</div></div>'


def _row(m: "re.Match[str]") -> str:
    """01 波兹南莱赫-勒沃库森 ▶ 0 🎯"""
    no, teams, val = m.group(1), m.group(2).strip(), m.group(3).strip()
    if "vs" in teams:
        a, b = teams.split("vs", 1)
    elif "-" in teams:
        a, b = teams.split("-", 1)
    else:
        a, b = teams, ""
    up = "📈" in val
    val = val.replace("📈", "")
    tier = next((t for t in ("🎯", "🔸", "⚪") if t in val), "")
    val = val.replace(tier, "").strip() if tier else val
    opts: List[str] = []
    for part in [x.strip() for x in val.split("｜") if x.strip()]:
        if "｜" not in val and "/" in part:
            opts += [x for x in part.split("/") if x]
        else:
            opts.append(part)
    ch = "".join(f'<span class="o">{esc(x)}</span>' for x in opts)
    vs = f'<span>{esc(a.strip())}</span>' + (f'<i>vs</i><span>{esc(b.strip())}</span>' if b else "")
    tier_html = '<span class="tr">' + esc(tier) + '</span>' if tier else ""
    return (f'<div class="row"><b>{esc(no)}</b><div class="t">{vs}</div><div class="os">{ch}{tier_html}'
            f'{_badge(up=up)}</div></div>')


def _tiles(segs: List["re.Match[str]"]) -> str:
    out = []
    for m in segs:
        n, a, b = m.group(1), int(m.group(2)), int(m.group(3))
        pct = (a / b) if b else 0
        out.append(f'<div class="tile"><div class="tl">{esc(n)}</div><div class="tv">{a}<small>/{b}</small></div>'
                   f'<div class="bar"><div style="width:{pct * 100:.0f}%"></div></div><div class="tp">{pct:.0%}</div></div>')
    return '<div class="tiles">' + "".join(out) + "</div>"


def _icon_split(line: str) -> Tuple[str, str]:
    """行首的表情符号 + 后面的文字。"""
    i = 0
    while i < len(line) and i < 4 and not (line[i].isalnum() or line[i].isspace() or line[i] in "（【([#•"):
        i += 1
    return line[:i], line[i:].strip()


KV_CLASS = {"🎯": "core", "⚠️": "warn", "⚠": "warn", "🧊": "warn", "💡": "tip", "🧠": "method", "💬": "quote", "📣": "slogan", "👇": "guide",
            "🙅": "warn"}


def _kv(line: str) -> str:
    icon, rest = _icon_split(line)
    cls = KV_CLASS.get(icon, "kv")
    if icon == "🎯" and "核心" not in rest:
        cls = "kv"
    if "：" in rest:
        lab, val = rest.split("：", 1)
        vals = [x.strip() for x in val.split("｜") if x.strip()] if cls not in ("quote",) else [val.strip()]
    elif "｜" in rest:
        parts = [x.strip() for x in rest.split("｜") if x.strip()]
        lab, vals = parts[0], parts[1:]
    else:
        lab, vals = "", [rest]
    if cls in ("quote", "slogan", "guide", "tip") or (not lab and len(vals) == 1 and len(vals[0]) > 18):
        txt = (lab + "：" if lab else "") + " ".join(vals)
        return f'<div class="ln {cls}"><span class="ic">{esc(icon)}</span><span>{esc(txt)}</span></div>'
    return (f'<div class="ln {cls}"><span class="ic">{esc(icon)}</span>' + (f'<span class="lb">{esc(lab)}</span>' if lab else "")
            + f'<div class="vs">{_chips(vals)}</div></div>')


def body_html(lines: List[str], medals: List[str]) -> str:
    out: List[str] = []
    medal_set = set(medals) | {"🔹"}
    i, n = 0, len(lines)
    while i < n:
        raw = lines[i]
        line = raw.strip().replace("　", " ").strip()
        if not line:
            i += 1
            continue
        # —— 榜单上的一场：勋章开头，直到空行 / 下一枚勋章 / 串关行
        mm = re.match(r"^(\S+?)\s+(.*)$", line)
        if mm and mm.group(1) in medal_set:
            ent = [mm.group(2)]
            i += 1
            while i < n:
                nxt = lines[i].strip().replace("　", " ").strip()
                if not nxt or PARLAY_RE.match(nxt):
                    break
                m2 = re.match(r"^(\S+?)\s+(.*)$", nxt)
                if m2 and m2.group(1) in medal_set:
                    break
                ent.append(nxt)
                i += 1
            out.append(_entry(mm.group(1), ent))
            continue
        i += 1
        if SEP_RE.match(line):
            out.append('<div class="hr"></div>')
            continue
        mr = ROW_RE.match(line)
        if mr:
            out.append(_row(mr))
            continue
        if SCORE_RE.match(line) or line.startswith("⚽进球"):
            out.append(_score_row(line))
            continue
        if line.startswith("🧭") and "：" in line and not out[-1:] == []:
            out.append(_kv(line).replace('class="ln kv"', 'class="ln kv mini"'))
            continue
        mp = PARLAY_RE.match(line)
        if mp:
            val = mp.group("val").strip()
            sp = ""
            ms = re.search(r"（(SP[^）]*)）\s*$", val)
            if ms:
                sp, val = ms.group(1), val[:ms.start()].strip()
            if val.startswith("再加"):
                body = f'<span class="plus">再加</span>' + "".join(f'<span class="chip">{esc(x)}</span>' for x in re.split(r"[+\s]+", val[2:]) if x)
            else:
                parts = [x for x in (val.split("+") if "+" in val else val.split()) if x.strip()]
                body = '<span class="plus">＋</span>'.join(f'<span class="chip">{esc(x.strip())}</span>' for x in parts)
            out.append(f'<div class="ln parlay"><span class="pl">{esc(mp.group("lab"))}</span><div class="vs">{body}'
                       + (f'<span class="chip soft">{esc(sp)}</span>' if sp else "") + "</div></div>")
            continue
        if line.startswith("🎯") and re.search(r"[✅❌⏳]", line):          # 🎯串关 ❌2串1(1/2) ❌3串1(2/3)   /  🎯❌任九(7/9)
            lab = "串关" if line.startswith("🎯串关") else ""
            items = ITEM_RE.findall(line)
            out.append('<div class="ln parlay">' + (f'<span class="pl">{lab}</span>' if lab else "") + f'<div class="vs">{_items(items)}</div></div>')
            continue
        if line[0] in "✅❌⏳" and ITEM_RE.match(line):
            out.append(f'<div class="vs items">{_items(ITEM_RE.findall(line))}</div>')
            continue
        # 战绩格子：竞足 4/8｜北单 5/8｜竞篮 3/4
        segs = [TILE_RE.match(x.strip()) for x in line.split("｜")]
        if segs and all(segs):
            out.append(_tiles([s for s in segs if s]))
            continue
        if line.startswith("【") and "】" in line:                              # 【4场进球】主队球数｜客队球数
            t, _, r = line[1:].partition("】")
            out.append(f'<div class="sec2"><b>{esc(t)}</b><span>{esc(r.strip())}</span></div>')
            continue
        if line.startswith("•"):
            out.append(f'<div class="bl">{esc(line[1:].strip())}</div>')
            continue
        if re.match(r"^(SP)?(热度榜|大热门榜)", line) or re.match(r"^.*榜\s*TOP\d+", line):
            out.append(f'<div class="pill">{esc(line)}</div>')
            continue
        if line.startswith("🎯单选"):
            out.append(f'<div class="legend">{esc(line)}</div>')
            continue
        icon, rest = _icon_split(line)
        if icon:
            if icon in ("📋", "📌", "✅", "⚔️", "⚔", "📊", "📈") and "：" not in rest:
                m3 = re.match(r"^(.*?)\s+(\d+/\d+（\d+%）)$", rest)
                if m3:
                    out.append(f'<div class="sub"><span class="ic">{esc(icon)}</span><span>{esc(m3.group(1))}</span><b>{esc(m3.group(2))}</b></div>')
                else:
                    out.append(f'<div class="sub"><span class="ic">{esc(icon)}</span><span>{esc(rest)}</span></div>')
                continue
            out.append(_kv(line))
            continue
        out.append(f'<p>{esc(line)}</p>')
    return "\n".join(out)


def _items(items: List[str]) -> str:
    out = []
    for it in items:
        cls = {"✅": "ok", "❌": "ng", "⏳": "pd"}.get(it[0], "")
        out.append(f'<span class="it {cls}">{esc(it)}</span>')
    return "".join(out)


# ════════════════════════════════════════════════════════════════════════════
# 3. 卡片 + 整页
# ════════════════════════════════════════════════════════════════════════════
CSS = """
:root{--page:#e6ecf5;--card:#ffffff;--ink:#0f172a;--soft:#475569;--mute:#64748b;--line:#e2e8f0;--tint:#f6f8fc;
--hd1:#0b1b3f;--hd2:#1e40af;--gold:#f5c451;--accent:#1d4ed8;--accentbg:#e8efff;--ok:#15803d;--okbg:#e7f6ec;--ng:#b91c1c;--ngbg:#fdecec;
--warn:#b45309;--warnbg:#fff4e0;--vio:#5b21b6;--viobg:#f3efff;--shadow:0 10px 30px rgba(15,23,42,.14)}
:root.dark{--page:#0b1020;--card:#131a2e;--ink:#eef2ff;--soft:#c4cce0;--mute:#94a3b8;--line:#25304d;--tint:#18213a;
--hd1:#070d1e;--hd2:#1c3a8a;--accent:#7aa2ff;--accentbg:#1b2a52;--ok:#4ade80;--okbg:#12301f;--ng:#fb7185;--ngbg:#3a1520;
--warn:#fbbf24;--warnbg:#38290c;--vio:#c4b5fd;--viobg:#271f4d;--shadow:0 10px 30px rgba(0,0,0,.5)}
*{box-sizing:border-box;margin:0;padding:0}
html,body{background:var(--page)}
body{font-family:"Microsoft YaHei UI","Microsoft YaHei","PingFang SC","Noto Sans CJK SC","Source Han Sans SC","Segoe UI","Segoe UI Emoji","Apple Color Emoji","Noto Color Emoji",sans-serif;
color:var(--ink);-webkit-font-smoothing:antialiased;line-height:1.45}
.page{width:%(W)dpx;padding:%(PAD)dpx;margin:0 auto}
.card{width:%(CW)dpx;background:var(--card);border-radius:var(--rad,26px);overflow:hidden;box-shadow:var(--shadow)}
body.one .card,body.one .gap{display:none}body.one .card.on{display:block}
body:not(.one) .page{padding-bottom:0}
.hd{background:linear-gradient(135deg,var(--hd1),var(--hd2));color:#fff;padding:30px 36px 26px;position:relative}
.hd:after{content:"";position:absolute;left:0;right:0;bottom:0;height:6px;background:var(--stripe,linear-gradient(90deg,var(--gold),#ffdf8a 60%%,transparent))}
.hd:before{content:"";position:absolute;left:0;right:0;top:0;bottom:0;z-index:0;pointer-events:none;background:var(--orn,none);-webkit-mask-image:var(--ornmask,none);mask-image:var(--ornmask,none)}
.hd>*{position:relative;z-index:1}
.hd .top{display:flex;justify-content:space-between;align-items:center;font-size:21px;letter-spacing:.5px;color:#cfe0ff}
.hd .top .brand{font-weight:700;color:var(--gold)}
.hd .ths{display:flex;gap:8px}
.hd .th{background:rgba(255,255,255,.14);border-radius:999px;padding:3px 14px;font-size:20px;color:#fff}
.hd h1{font-size:46px;line-height:1.2;margin-top:12px;font-weight:800;letter-spacing:1px}
.hd h1 .hi{margin-right:10px}
.hd .hsub{margin-top:12px;display:flex;flex-wrap:wrap;gap:10px}
.hd .hsub span{background:rgba(255,255,255,.16);border-radius:999px;padding:4px 16px;font-size:22px;color:#fff}
.bd{padding:26px 32px 8px}
.bd>*{margin-bottom:16px}
p{font-size:24px;color:var(--soft);line-height:1.6;white-space:pre-wrap}
.bd>p:first-child{font-size:28px;font-weight:700;color:var(--ink)}
.hr{height:1px;background:var(--line);margin:4px 0 !important}
.pill{display:inline-block;background:var(--accentbg);color:var(--accent);font-size:22px;font-weight:700;padding:6px 18px;border-radius:999px}
.legend{font-size:21px;color:var(--mute)}
.m{display:flex;gap:16px;background:var(--tint);border:1px solid var(--line);border-radius:20px;padding:18px 20px}
.rk{font-size:40px;line-height:1;flex:0 0 auto;width:52px;text-align:center;padding-top:4px}
.mb{flex:1;min-width:0}
.meta{font-size:21px;color:var(--mute);font-weight:600}
.tm{font-size:31px;font-weight:800;line-height:1.3;margin:4px 0 8px;display:flex;flex-wrap:wrap;align-items:baseline;gap:4px 12px}
.tm.sm{font-size:27px}
.tm i{font-style:normal;font-size:20px;color:var(--mute);font-weight:600}
.pk{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin-top:2px}
.cp{font-size:24px}
.pc{background:var(--accent);color:#fff;font-weight:800;font-size:25px;padding:5px 18px;border-radius:999px;display:inline-block}
.pc b{font-weight:600;font-size:19px;opacity:.82;margin-right:8px}
:root.dark .pc{color:#0b1020}
.pc.soft{background:var(--accentbg);color:var(--accent);font-weight:700;font-size:22px}
:root.dark .pc.soft{color:var(--accent)}
em{font-style:normal;font-size:20px;font-weight:700;border-radius:999px;padding:3px 12px;display:inline-block}
em.up{background:var(--okbg);color:var(--ok)}
em.dr{background:var(--warnbg);color:var(--warn)}
.sc{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px;margin-top:10px;background:var(--viobg);color:var(--vio);border-radius:14px;padding:8px 14px;font-size:22px}
.sc .sl{font-weight:700}
.sc .sp{font-weight:800;font-size:24px;background:var(--card);border-radius:10px;padding:1px 12px;letter-spacing:.5px}
.sc .gl{margin-left:auto;font-weight:600}
.bs{margin-top:10px;font-size:21px;color:var(--mute);line-height:1.5}
.row{display:flex;align-items:center;gap:14px;background:var(--tint);border:1px solid var(--line);border-radius:16px;padding:10px 16px}
.row b{flex:0 0 46px;font-size:24px;color:var(--accent);font-variant-numeric:tabular-nums}
.row .t{flex:1;min-width:0;font-size:25px;font-weight:700;display:flex;flex-wrap:wrap;gap:0 10px;align-items:baseline}
.row .t i{font-style:normal;font-size:18px;color:var(--mute);font-weight:600}
.row .os{display:flex;align-items:center;gap:6px;flex:0 0 auto}
.row .o{background:var(--accent);color:#fff;font-weight:800;font-size:22px;border-radius:10px;padding:2px 12px;min-width:36px;text-align:center}
:root.dark .row .o{color:#0b1020}
.row em{font-size:17px;padding:2px 9px}
.row .tr{font-size:26px;line-height:1;margin-left:4px}
.ln{display:flex;flex-wrap:wrap;align-items:center;gap:8px 12px;font-size:24px}
.ln .ic{font-size:26px}
.ln .lb{font-weight:800;color:var(--ink)}
.vs{display:flex;flex-wrap:wrap;align-items:center;gap:8px 10px}
.chip{background:var(--tint);border:1px solid var(--line);border-radius:999px;padding:4px 16px;font-size:23px;font-weight:700;color:var(--ink)}
.chip.soft{color:var(--mute);font-weight:600}
.ln.core{background:linear-gradient(90deg,#fff7df,#fffbf0);border:1px solid #f4dc9a;border-radius:18px;padding:14px 18px}
.ln.core .lb{color:#92400e}.ln.core .chip{background:#fff;border-color:#f1d48a;color:#7c2d12}
:root.dark .ln.core{background:#33290f;border-color:#6b5420}:root.dark .ln.core .lb{color:var(--gold)}:root.dark .ln.core .chip{background:#241c08;color:#fde68a;border-color:#6b5420}
.ln.warn{background:var(--warnbg);color:var(--warn);border-radius:16px;padding:12px 18px;font-weight:600}
.ln.warn .lb{color:var(--warn)}.ln.warn .chip{background:transparent;border-color:transparent;color:var(--warn);padding:0;font-weight:600}
.ln.method{background:var(--accentbg);color:var(--accent);border-radius:16px;padding:12px 18px}
.ln.method .lb{color:var(--accent);font-size:26px}.ln.method .chip{background:var(--card);border-color:transparent;color:var(--accent)}
.ln.quote,.ln.slogan,.ln.tip{color:var(--soft);font-size:23px;flex-wrap:nowrap;align-items:flex-start}
.ln.quote span:last-child{font-style:italic}
.ln.slogan{font-weight:700;color:var(--ink)}
.ln.guide{color:var(--mute);font-size:21px;flex-wrap:nowrap;align-items:flex-start}
.ln.mini{font-size:22px;background:var(--tint);border-radius:14px;padding:8px 14px}
.sub{display:flex;align-items:center;gap:10px;font-size:25px;font-weight:800;border-left:6px solid var(--gold);padding-left:14px;margin-top:6px}
.sub b{margin-left:auto;background:var(--accentbg);color:var(--accent);border-radius:999px;padding:2px 14px;font-size:22px}
.sec2{display:flex;align-items:baseline;gap:12px;font-size:26px;font-weight:800;margin-top:6px}
.sec2 span{font-size:21px;font-weight:500;color:var(--mute)}
.bl{font-size:23px;color:var(--soft);padding-left:26px;position:relative;line-height:1.55}
.bl:before{content:"";position:absolute;left:8px;top:.62em;width:9px;height:9px;border-radius:50%%;background:var(--gold)}
.tiles{display:flex;flex-wrap:wrap;gap:12px}
.tile{flex:1 1 150px;min-width:150px;background:var(--tint);border:1px solid var(--line);border-radius:18px;padding:12px 16px}
.tl{font-size:20px;color:var(--mute);font-weight:600}
.tv{font-size:40px;font-weight:800;line-height:1.1;color:var(--ink)}
.tv small{font-size:22px;color:var(--mute);font-weight:600}
.bar{height:8px;background:var(--line);border-radius:6px;overflow:hidden;margin:8px 0 4px}
.bar div{height:100%%;background:linear-gradient(90deg,var(--accent),var(--gold));border-radius:6px}
.tp{font-size:19px;color:var(--mute);font-weight:700}
.parlay{background:var(--tint);border:1px dashed var(--line);border-radius:18px;padding:12px 16px}
.pl{background:var(--gold);color:#3b2a00;font-weight:800;font-size:22px;border-radius:12px;padding:3px 14px}
.plus{color:var(--mute);font-weight:700;font-size:22px}
.items{gap:8px 8px}
.it{border-radius:12px;padding:3px 12px;font-size:21px;font-weight:700;border:1px solid var(--line);background:var(--tint)}
.it.ok{background:var(--okbg);color:var(--ok);border-color:transparent}
.it.ng{background:var(--ngbg);color:var(--ng);border-color:transparent}
.it.pd{background:var(--warnbg);color:var(--warn);border-color:transparent}
.ft{padding:6px 36px 28px}
.ft .rule{height:1px;background:var(--line);margin:8px 0 14px}
.ft .tip{font-size:20px;color:var(--mute);line-height:1.5}
.ft .cta{font-size:23px;color:var(--ink);font-weight:700;line-height:1.55;margin-top:2px}
.ft .tags{margin-top:8px;font-size:21px;color:var(--accent);font-weight:600;line-height:1.6}
.ft .wm{margin-top:12px;display:flex;justify-content:space-between;align-items:center;font-size:20px;color:var(--mute)}
.ft .wm b{color:var(--ink);letter-spacing:1px}
"""


# ════════════════════════════════════════════════════════════════════════════
# 3b. 按玩法换风格：每种玩法一套配色＋头部图案＋细节（图片里不加任何新文字，只是换外观）
# ════════════════════════════════════════════════════════════════════════════
STYLE_SAME = ("统一", "单一", "same", "uniform")        # brand.json「图片风格」写这些 = 所有图片都用同一套深蓝（老样子）
THEME_KEYS: List[Tuple[Tuple[str, ...], str]] = [        # 帖子名/玩法名里含这些字 → 用哪套风格（先匹配到的算）
    (("复盘", "赛果", "战绩"), "fp"),
    (("综合",), "zh"),
    (("重点",), "zd"),
    (("北单", "北京单场"), "bd"),
    (("竞篮", "篮球"), "lq"),
    (("胜负彩", "任九", "任选"), "sf"),
    (("进球", "半全场"), "jq"),
    (("竞足", "竞彩足球", "足球"), "jz"),
]


def _svg(body: str, color: str = "#ffffff", op: float = 0.24, w: int = 3, vb: str = "0 0 560 300") -> str:
    """一段 SVG 线条图案 → CSS 里能直接用的 url(...)（不依赖任何外部文件）。"""
    s = (f"<svg xmlns='http://www.w3.org/2000/svg' viewBox='{vb}' fill='none' stroke='{color}' stroke-opacity='{op}' "
         f"stroke-width='{w}' stroke-linecap='round' stroke-linejoin='round'>{body}</svg>")
    return 'url("data:image/svg+xml,' + s.replace("<", "%3C").replace(">", "%3E").replace("#", "%23") + '")'


def _barcode(x0: int, y0: int, y1: int, n: int = 16) -> str:
    out, x = [], x0
    for i in range(n):
        wd = (2, 5, 3, 7, 2, 4)[i % 6]
        out.append(f"<path d='M{x} {y0}V{y1}' stroke-width='{wd}'/>")
        x += wd + 5
    return "".join(out)


_FADE = "linear-gradient(90deg,transparent 22%,#000 62%)"
_ORN_FIT = "right -8px center/auto 120% no-repeat"
_PITCH = ("<rect x='24' y='24' width='500' height='252'/><path d='M274 24V276'/><circle cx='274' cy='150' r='52'/>"
          "<circle cx='274' cy='150' r='4' fill='#fff' fill-opacity='.3'/><rect x='24' y='84' width='88' height='132'/><rect x='24' y='120' width='34' height='60'/>"
          "<rect x='436' y='84' width='88' height='132'/><rect x='490' y='120' width='34' height='60'/>"
          "<path d='M112 126A44 44 0 0 1 112 174'/><path d='M436 126A44 44 0 0 0 436 174'/>")
_COURT = ("<rect x='30' y='26' width='500' height='248'/><rect x='392' y='96' width='138' height='108'/><circle cx='392' cy='150' r='46'/>"
          "<path d='M530 54H452A118 118 0 0 0 452 246H530'/><path d='M530 132V168'/><circle cx='514' cy='150' r='9'/>"
          "<path d='M30 26V274' stroke-opacity='.0'/><path d='M200 26V274'/><circle cx='200' cy='150' r='44'/>")
_TICKET = ("<path d='M36 40H524V122A26 26 0 0 0 524 174V260H36V174A26 26 0 0 0 36 122Z'/><path d='M372 40V260' stroke-dasharray='6 9'/>"
           + _barcode(396, 80, 220, 12) + "<path d='M70 100H320M70 150H260M70 200H300' stroke-opacity='.5'/>")
_NET = ("<path d='M60 280V50H520V280'/>" + "".join(f"<path d='M{x} 50V250'/>" for x in range(100, 520, 40))
        + "".join(f"<path d='M60 {y}H520'/>" for y in range(90, 260, 40)) + "<circle cx='450' cy='222' r='30' fill='#fff' fill-opacity='.10'/>"
        "<path d='M450 202L468 215L461 237H439L432 215Z'/>")
_RADAR = ("<path d='M280 38L375 93V203L280 258L185 203V93Z'/><path d='M280 73L345 111V189L280 227L215 189V111Z'/><path d='M280 108L315 129V171L280 192L245 171V129Z'/>"
          "<path d='M280 150L280 38M280 150L375 93M280 150L375 203M280 150L280 258M280 150L185 203M280 150L185 93'/>"
          "<path d='M280 70L352 104L362 198L280 236L206 196L200 106Z' fill='#f5c451' fill-opacity='.18' stroke-opacity='.5'/>")
_SCOPE = ("<circle cx='300' cy='150' r='104'/><circle cx='300' cy='150' r='66'/><circle cx='300' cy='150' r='26'/>"
          "<path d='M300 22V76M300 224V278M172 150H226M374 150H428'/><path d='M200 70H228M200 70V98M400 70H372M400 70V98M200 230H228M200 230V202M400 230H372M400 230V202'/>"
          "<path d='M376 226L430 280' stroke-width='9'/>")
_LEDGER = ("<path d='M60 64H520M60 118H520M60 172H520M60 226H520' stroke-opacity='.18'/>"
           "<path d='M84 86l14 15l28 -32'/><path d='M84 140l14 15l28 -32'/><path d='M86 184l34 34M120 184l-34 34'/><path d='M84 248l14 15l28 -32' stroke-opacity='0'/>"
           "<path d='M172 92H330M172 146H300M172 200H350'/><path d='M400 214V150M432 214V108M464 214V170M496 214V84' stroke-width='14' stroke-opacity='.2'/>")
_LATTICE = ("<defs><pattern id='p' width='60' height='60' patternUnits='userSpaceOnUse'><path d='M30 2L58 30L30 58L2 30Z' stroke-width='2'/>"
            "<circle cx='30' cy='30' r='7' stroke-width='2'/></pattern></defs><rect width='560' height='300' fill='url(%23p)' stroke='none'/>")

_DASH = ("<rect x='214' y='46' width='104' height='80' rx='16'/><rect x='334' y='46' width='104' height='80' rx='16' fill='#fff' fill-opacity='.08'/>"
         "<rect x='454' y='46' width='104' height='80' rx='16'/><rect x='214' y='148' width='104' height='80' rx='16' fill='#fff' fill-opacity='.08'/>"
         "<rect x='334' y='148' width='104' height='80' rx='16'/><rect x='454' y='148' width='104' height='80' rx='16' fill='#fff' fill-opacity='.08'/>"
         "<path d='M232 72H292M232 92H270M352 72H412M352 92H390M472 72H532M472 92H510M232 174H292M232 194H270M352 174H412M352 194H390M472 174H532M472 194H510' stroke-opacity='.4'/>"
         "<path d='M214 258H558' stroke-opacity='.3'/>")

THEMES: Dict[str, Dict[str, Any]] = {
    "gen": dict(   # 总览／认不出的帖子：深蓝＋看板格子（配色用页面默认的）
        L={}, D={}, orn=_svg(_DASH, op=0.26), mask=_FADE, pos="right 20px bottom -6px/auto 112% no-repeat", rad="26px", stripe="", css=""),
    "jz": dict(   # 竞足：球场绿
        L=dict(hd1="#052e16", hd2="#15803d", gold="#bef264", accent="#166534", accentbg="#e4f4e8", tint="#f2f9f4", line="#d6e8db", page="#dff0e4"),
        D=dict(hd1="#021b0d", hd2="#166534", accent="#4ade80", accentbg="#12301f", page="#06130c", card="#0d1f14", tint="#12281b", line="#1d3a2a"),
        orn=_svg(_PITCH, op=0.22), mask=_FADE, pos=_ORN_FIT, rad="26px",
        stripe="repeating-linear-gradient(90deg,var(--gold) 0 54px,transparent 54px 108px)",
        css=".card.th-jz .m{border-left:7px solid var(--accent)}.card.th-jz .sub{border-left-color:var(--accent)}"),
    "bd": dict(   # 北单：中国红＋金
        L=dict(hd1="#4a0404", hd2="#b91c1c", gold="#fbbf24", accent="#92400e", accentbg="#fff1d6", tint="#fff8f1", line="#f0dcc8", page="#f7e6dc"),
        D=dict(hd1="#2e0505", hd2="#991b1b", accent="#fbbf24", accentbg="#3a2a0c", page="#170909", card="#241313", tint="#2d1919", line="#4a2c2c"),
        orn=_svg(_LATTICE, color="#fde68a", op=0.30, w=2), mask=_FADE, pos="0 0/auto 100% no-repeat", rad="22px",
        stripe="repeating-linear-gradient(90deg,var(--gold) 0 14px,transparent 14px 22px)",
        css=".card.th-bd .m{border:1px solid #efcf96;box-shadow:inset 0 0 0 3px var(--card),inset 0 0 0 4px #f3d9a0}.card.th-bd .sub{border-left-color:#b91c1c}"
            ":root.dark .card.th-bd .m{border-color:#6b5420;box-shadow:inset 0 0 0 3px var(--card),inset 0 0 0 4px #6b5420}"),
    "lq": dict(   # 竞篮：篮球橙＋球场线
        L=dict(hd1="#1c1008", hd2="#ea580c", gold="#fdba74", accent="#c2410c", accentbg="#ffedd5", tint="#fff7f0", line="#f1dccb", page="#fbe9da"),
        D=dict(hd1="#100a05", hd2="#9a3412", accent="#fb923c", accentbg="#3a2210", page="#140c06", card="#211409", tint="#2a1a0d", line="#44301c"),
        orn=_svg(_COURT, op=0.26), mask=_FADE, pos=_ORN_FIT, rad="30px",
        stripe="linear-gradient(90deg,var(--gold),#fb923c 55%,transparent)",
        css=".card.th-lq .m{border-radius:30px}.card.th-lq .pc{border-radius:14px}.card.th-lq .sub{border-left-color:var(--accent)}"),
    "sf": dict(   # 胜负彩／任九：票面紫
        L=dict(hd1="#2e1065", hd2="#7c3aed", gold="#fcd34d", accent="#6d28d9", accentbg="#f0eaff", tint="#f8f5ff", line="#e3daf6", page="#ebe5f9"),
        D=dict(hd1="#1e0a4a", hd2="#5b21b6", accent="#c4b5fd", accentbg="#2b2058", page="#0f0a1e", card="#1a1233", tint="#221945", line="#3a2d68"),
        orn=_svg(_TICKET, op=0.26), mask=_FADE, pos=_ORN_FIT, rad="14px",
        stripe="repeating-linear-gradient(90deg,var(--gold) 0 10px,transparent 10px 20px)",
        css=".card.th-sf .m,.card.th-sf .row,.card.th-sf .tile,.card.th-sf .parlay{border-style:dashed;border-width:2px}.card.th-sf .sub{border-left-color:var(--accent)}"),
    "jq": dict(   # 4场进球／6场半全场：球网青
        L=dict(hd1="#042f2e", hd2="#0f766e", gold="#5eead4", accent="#0f766e", accentbg="#dcf5f1", tint="#eff9f7", line="#d0e9e5", page="#dbf1ee"),
        D=dict(hd1="#021a1f", hd2="#0e7490", accent="#5eead4", accentbg="#0f3a40", page="#041519", card="#0a1d22", tint="#0f2a30", line="#1c424a"),
        orn=_svg(_NET, op=0.22, w=2), mask=_FADE, pos=_ORN_FIT, rad="20px",
        stripe="linear-gradient(90deg,var(--gold),#99f6e4 55%,transparent)",
        css=".card.th-jq .row{border-left:6px solid var(--accent)}.card.th-jq .sub{border-left-color:var(--accent)}"),
    "zh": dict(   # 综合推单：黑金
        L=dict(hd1="#0d0d0d", hd2="#4a3a16", gold="#f5c451", accent="#854d0e", accentbg="#fbf1d6", tint="#faf7ee", line="#e6dfc9", page="#e9e4d6"),
        D=dict(hd1="#050505", hd2="#3b2f12", accent="#f5c451", accentbg="#3a2e0e", page="#0b0a07", card="#16140e", tint="#1e1b12", line="#3a3320"),
        orn=_svg(_RADAR, color="#f5c451", op=0.5, w=2), mask=_FADE, pos=_ORN_FIT, rad="10px",
        stripe="linear-gradient(90deg,#f5c451,#fff1b8 45%,#f5c451 70%,transparent)",
        css=".card.th-zh{border:2px solid #e3c77a}.card.th-zh .m{background:linear-gradient(135deg,var(--tint),var(--card));border-color:#e3c77a}"
            ".card.th-zh .sub{border-left-color:#854d0e}:root.dark .card.th-zh{border-color:#6b5420}:root.dark .card.th-zh .m{border-color:#4a3f1c}"),
    "zd": dict(   # 重点关注：聚光灯玫红
        L=dict(hd1="#3b0443", hd2="#be185d", gold="#f9a8d4", accent="#be185d", accentbg="#fde7f1", tint="#fdf4f8", line="#f0d6e2", page="#f6e2ec"),
        D=dict(hd1="#2a0230", hd2="#9d174d", accent="#f9a8d4", accentbg="#4a1640", page="#160716", card="#230c24", tint="#2d1230", line="#4d2552"),
        orn=_svg(_SCOPE, op=0.28), mask=_FADE, pos=_ORN_FIT, rad="32px",
        stripe="linear-gradient(90deg,var(--gold),#fbcfe8 55%,transparent)",
        css=".card.th-zd .m{box-shadow:0 0 0 4px var(--accentbg)}.card.th-zd .sub{border-left-color:var(--accent)}"),
    "fp": dict(   # 昨日复盘：账本灰
        L=dict(hd1="#1f2937", hd2="#475569", gold="#cbd5e1", accent="#334155", accentbg="#e6ebf2", tint="#f4f6f9", line="#dce1e9", page="#e5e8ed"),
        D=dict(hd1="#0b0f17", hd2="#334155", accent="#cbd5e1", accentbg="#2a3142", page="#0d1016", card="#161a23", tint="#1c212e", line="#2f3648"),
        orn=_svg(_LEDGER, op=0.34, w=3), mask=_FADE, pos=_ORN_FIT, rad="12px",
        stripe="repeating-linear-gradient(90deg,var(--gold) 0 6px,transparent 6px 12px)",
        css=".card.th-fp .m,.card.th-fp .row,.card.th-fp .tile,.card.th-fp .parlay{border-radius:10px}.card.th-fp .sub{border-left-color:#64748b}"),
}


def theme_of(post_name: str, play: str = "") -> str:
    """这条帖子用哪套风格：先看帖子名，再看标题里的玩法名；认不出来就是默认的深蓝（gen）。"""
    for text in (str(post_name or ""), str(play or "")):
        for kws, th in THEME_KEYS:
            if any(k in text for k in kws):
                return th
    return "gen"


def themes_css() -> str:
    out: List[str] = []
    for k, t in THEMES.items():
        L_, D_ = t["L"], t["D"]
        decs = [f"--{kk}:{vv}" for kk, vv in L_.items() if kk != "page"]
        decs += [f"--orn:{t['orn']} {t['pos']}", f"--ornmask:{t['mask']}", f"--rad:{t['rad']}"]
        if t.get("stripe"):
            decs.append(f"--stripe:{t['stripe']}")
        out.append(f".card.th-{k}{{{';'.join(decs)}}}")
        if D_:
            out.append(f":root.dark .card.th-{k}{{" + ";".join(f"--{kk}:{vv}" for kk, vv in D_.items() if kk != "page") + "}")
        if L_:
            out.append(f":root.t-{k}{{--page:{L_['page']}}}:root.dark.t-{k}{{--page:{D_['page']}}}")
        if t.get("css"):
            out.append(t["css"])
    return "\n".join(out)


def card_html(post_name: str, text: str, idx: int, total: int, B: Dict[str, Any], part: Optional[Tuple[int, int]] = None,
              pos: Optional[int] = None) -> str:
    P = split_post(text)
    brand = B.get("栏目名") or P["brand"] or "今日热推"
    medals = [x for x in (B.get("榜单勋章") or []) if isinstance(x, str)]
    title = P["play"] or brand
    kicker = brand if P["play"] else "今日推单"
    icon = P["icon"]
    thread = P["thread"] or ((idx, total) if total > 1 else None)
    sub = "".join(f"<span>{esc(x)}</span>" for x in P["sub"])
    head = (f'<div class="hd"><div class="top"><span class="brand">{esc(kicker)}</span>'
            + '<span class="ths">' + (f'<span class="th">🧵 {thread[0]}/{thread[1]}</span>' if thread else "")
            + (f'<span class="th">图 {part[0]}/{part[1]}</span>' if part else "") + "</span></div>"
            f'<h1>{("<span class=hi>" + esc(icon) + "</span>") if icon else ""}{esc(title)}</h1>'
            + (f'<div class="hsub">{sub}</div>' if sub else "") + "</div>")
    wm = B.get("图片水印") or B.get("署名") or brand
    foot = '<div class="ft"><div class="rule"></div>'
    if P["tips"]:
        foot += '<div class="tip">' + "<br>".join(esc(x) for x in P["tips"]) + "</div>"
    own = set(x for x in (B.get("互动语") or []) if isinstance(x, str)) | ({B["提示语"]} if isinstance(B.get("提示语"), str) and B.get("提示语") else set())
    cta = [x for x in P["sign"] if x in own]                     # 结尾互动语（点赞/转发/关注）和自己填的提示语也画在图上
    if cta:
        foot += '<div class="cta">' + "<br>".join(esc(x) for x in cta) + "</div>"
    if P["tags"]:
        foot += '<div class="tags">' + " ".join(esc(x) for x in P["tags"]) + "</div>"
    foot += f'<div class="wm"><span>{esc(post_name)}</span><b>{esc(wm)}</b></div></div>'
    th = "none" if str(B.get("图片风格") or "") in STYLE_SAME else theme_of(post_name, P["play"])
    return f'<div class="card th-{th}" id="c{idx - 1 if pos is None else pos}" data-name="{esc(post_name)}" data-t="{th}">{head}<div class="bd">{body_html(P["body"], medals)}</div>{foot}</div>'


def _norm_items(posts: List[Any]) -> List[Tuple[str, str, Optional[Tuple[int, int]], int, int]]:
    """(名字, 文字) 或 (名字, 文字, 第几份/共几份, 原来第几条, 原来共几条) → 统一成 5 个一组。"""
    n = len(posts)
    out = []
    for i, it in enumerate(posts, 1):
        if len(it) >= 5:
            out.append((it[0], it[1], it[2], it[3], it[4]))
        else:
            out.append((it[0], it[1], None, i, n))
    return out


def build_page(posts: List[Any], B: Optional[Dict[str, Any]] = None, theme: Optional[str] = None) -> str:
    B = dict(BRAND_FALLBACK, **(B or {}))
    dark = (theme or B.get("图片配色")) in ("深色", "dark", "深")
    gap = f'<div class="gap" style="height:{PAD}px"></div>'
    cards = gap.join(card_html(nm, tx, oi, on, B, part, pos) for pos, (nm, tx, part, oi, on) in enumerate(_norm_items(posts)))
    css = CSS % {"W": CARD_W + 2 * PAD, "PAD": PAD, "CW": CARD_W} + "\n" + themes_css()
    js = (
        "(function(){var q=location.search||'',cs=document.querySelectorAll('.card');"
        "var m=/[?&]c=(\\d+)/.exec(q);"
        "if(m){document.body.className='one';var c=document.getElementById('c'+m[1]);if(c){c.className+=' on';document.documentElement.className+=' t-'+(c.getAttribute('data-t')||'none');}}"
        "if(/[?&]m=1/.test(q)){var h=[];for(var i=0;i<cs.length;i++)h.push(cs[i].offsetHeight);document.title='H:'+h.join(',');}"
        "})();"
    )
    cls = ' class="dark"' if dark else ""
    return (f'<!doctype html><html lang="zh-CN"{cls}><head><meta charset="utf-8">'
            f'<meta name="viewport" content="width={CARD_W + 2 * PAD}"><title>推单图片快照</title><style>{css}</style></head>'
            f'<body><div class="page">{cards}</div><script>{js}</script></body></html>')


# ════════════════════════════════════════════════════════════════════════════
# 4. 找浏览器 + 截图
# ════════════════════════════════════════════════════════════════════════════
def _registry_browser_candidates() -> List[str]:
    """读取系统和当前用户的浏览器注册路径；不启动或修改浏览器。"""
    try:
        import winreg
    except ImportError:
        return []
    out = []
    for root in (winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE):
        for view in (0, winreg.KEY_WOW64_64KEY, winreg.KEY_WOW64_32KEY):
            for exe in ("msedge.exe", "chrome.exe", "chromium.exe", "brave.exe"):
                key = "SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\App Paths\\" + exe
                try:
                    with winreg.OpenKey(root, key, 0, winreg.KEY_READ | view) as handle:
                        value, _ = winreg.QueryValueEx(handle, None)
                        if isinstance(value, str):
                            out.append(value)
                except OSError:
                    continue
    return out


def find_browser(custom: str = "") -> Optional[str]:
    """按手选路径、环境变量、注册表、常用目录、PATH和现有Playwright缓存查找。"""
    cands: List[str] = [custom, os.environ.get("TIPS_BROWSER", "")]
    cands += _registry_browser_candidates()
    bases = [os.environ.get(key, "") for key in ("ProgramFiles", "ProgramFiles(x86)", "ProgramW6432", "LOCALAPPDATA")]
    bases += [str(Path.home() / "AppData" / "Local"), "C:/Program Files", "C:/Program Files (x86)"]
    for base in bases:
        if not base:
            continue
        cands += [str(Path(base) / relative) for relative in (
            "Microsoft/Edge/Application/msedge.exe", "Google/Chrome/Application/chrome.exe",
            "Chromium/Application/chrome.exe", "BraveSoftware/Brave-Browser/Application/brave.exe")]
    cands += ["/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
              "/Applications/Microsoft Edge.app/Contents/MacOS/Microsoft Edge",
              "/Applications/Chromium.app/Contents/MacOS/Chromium"]
    for name in ("msedge", "microsoft-edge", "google-chrome", "google-chrome-stable", "chrome", "chromium", "chromium-browser"):
        found = shutil.which(name)
        if found:
            cands.append(found)
    caches = [Path.home() / ".cache/ms-playwright"]
    if os.environ.get("LOCALAPPDATA"):
        caches.append(Path(os.environ["LOCALAPPDATA"]) / "ms-playwright")
    if os.environ.get("PLAYWRIGHT_BROWSERS_PATH") not in (None, "", "0"):
        caches.insert(0, Path(os.environ["PLAYWRIGHT_BROWSERS_PATH"]))
    for cache in caches:
        if not cache.is_dir():
            continue
        for pattern in ("chromium-*/chrome-win/chrome.exe", "chromium-*/chrome-win64/chrome.exe",
                        "chromium-*/chrome-linux/chrome", "chromium-*/chrome-linux64/chrome"):
            cands += [str(path) for path in sorted(cache.glob(pattern), reverse=True)]
    seen = set()
    for raw in cands:
        if not raw:
            continue
        cleaned = os.path.expandvars(os.path.expanduser(str(raw).strip().strip('"').strip("'")))
        if cleaned in seen:
            continue
        seen.add(cleaned)
        path = Path(cleaned)
        if path.is_file():
            return str(path)
        if path.is_dir():
            for relative in ("chrome.exe", "msedge.exe", "Application/chrome.exe", "Application/msedge.exe",
                             "App/Chrome-bin/chrome.exe", "App/Chrome64/chrome.exe"):
                candidate = path / relative
                if candidate.is_file():
                    return str(candidate)
    return None


def png_size(path: Path) -> Optional[Tuple[int, int]]:
    try:
        with open(path, "rb") as f:
            head = f.read(24)
        if head[:8] != b"\x89PNG\r\n\x1a\n":
            return None
        return struct.unpack(">II", head[16:24])
    except OSError:
        return None


def crop_png_rows(path: Path, rows: int) -> bool:
    """把 PNG 只留上面 rows 行（去掉底部多出来的底色）。只裁底部，所以不用解开滤波，纯标准库。成功返回 True。"""
    import zlib
    try:
        data = Path(path).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            return False
        pos, chunks, idat = 8, [], b""
        while pos + 8 <= len(data):
            ln, typ = struct.unpack(">I4s", data[pos:pos + 8])
            body = data[pos + 8:pos + 8 + ln]
            pos += 12 + ln
            if typ == b"IDAT":
                idat += body
            elif typ != b"IEND":
                chunks.append((typ, body))
        ihdr = next(b for t, b in chunks if t == b"IHDR")
        w, h, depth, ctype, _, _, interlace = struct.unpack(">IIBBBBB", ihdr)
        bpp = {2: 3, 6: 4, 0: 1, 4: 2}.get(ctype)
        if depth != 8 or interlace or not bpp or rows >= h or rows <= 0:
            return rows >= h and bool(bpp)
        raw = zlib.decompress(idat)
        rl = 1 + w * bpp
        if len(raw) != rl * h:
            return False
        newihdr = struct.pack(">IIBBBBB", w, rows, depth, ctype, 0, 0, 0)

        def chunk(t: bytes, b: bytes) -> bytes:
            return struct.pack(">I", len(b)) + t + b + struct.pack(">I", zlib.crc32(t + b) & 0xFFFFFFFF)
        out = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", newihdr)
        out += b"".join(chunk(t, b) for t, b in chunks if t != b"IHDR")
        out += chunk(b"IDAT", zlib.compress(raw[:rl * rows], 6)) + chunk(b"IEND", b"")
        Path(path).write_bytes(out)
        return True
    except (OSError, ValueError, StopIteration, struct.error, zlib.error):
        return False


def _kill_tree(proc: "subprocess.Popen[Any]") -> None:
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        else:
            proc.kill()
    except Exception:  # noqa: BLE001
        pass


def _run(cmd: List[str], timeout: float) -> Tuple[int, bytes]:
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, stdin=subprocess.DEVNULL, creationflags=flags)
    try:
        out, _ = proc.communicate(timeout=timeout)
        return proc.returncode, out or b""
    except subprocess.TimeoutExpired:
        _kill_tree(proc)
        try:
            out, _ = proc.communicate(timeout=10)
        except Exception:  # noqa: BLE001
            out = b""
        return -9, out or b""


def _base_cmd(browser: str, mode: str, udir: str) -> List[str]:
    cmd = [browser, f"--headless={mode}" if mode else "--headless", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--mute-audio", "--allow-file-access-from-files",
           f"--user-data-dir={udir}"]
    if os.name != "nt" and hasattr(os, "geteuid") and os.geteuid() == 0:        # 在 Linux 以 root 跑（测试环境）时需要
        cmd.append("--no-sandbox")
    return cmd


def measure(browser: str, mode: str, udir: str, url: str, n: int, timeout: float = SHOT_TIMEOUT) -> Optional[List[int]]:
    rc, out = _run(_base_cmd(browser, mode, udir) + [f"--window-size={CARD_W + 2 * PAD},1200", "--dump-dom", url + "?m=1"], timeout)
    m = re.search(rb"<title>H:([0-9,]+)</title>", out)
    if not m:
        return None
    hs = [int(x) for x in m.group(1).decode().split(",") if x]
    return hs if len(hs) == n and all(h > 0 for h in hs) else None


def shoot(browser: str, mode: str, udir: str, url: str, dest: Path, height: int, timeout: float = SHOT_TIMEOUT) -> bool:
    if dest.exists():
        try:
            dest.unlink()
        except OSError:
            pass
    cmd = _base_cmd(browser, mode, udir) + [f"--window-size={CARD_W + 2 * PAD},{height}", f"--force-device-scale-factor={SCALE}",
                                            f"--screenshot={dest}", url]
    rc, _ = _run(cmd, timeout)
    return dest.exists() and dest.stat().st_size > 1000


def _est_h(text: str) -> int:
    """量不出高度时的估算（偏高一点，宁可底下多一点底色，也别把字截掉）。"""
    return max(700, 260 + 68 * len([l for l in str(text).split("\n") if l.strip()]))


def _safe_name(s: str) -> str:
    return re.sub(r'[\\/:*?"<>|\s]+', "", s) or "帖子"


def make_images(posts: List[Tuple[str, str]], out_dir: Path, *, B: Optional[Dict[str, Any]] = None, theme: Optional[str] = None,
                browser: str = "", log: Callable[[str], None] = print, cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """把每条帖子做成一张 PNG，存进 out_dir（默认叫 推单图片_日期）。返回 {"files": [...], "html": 路径, "error": 说明}。
    不会抛异常：任何问题都写进 error，并且至少保留「快照.html」。"""
    res: Dict[str, Any] = {"files": [], "html": None, "dir": str(out_dir), "error": "", "browser": "", "total": 0}
    posts = [(n, t) for n, t in posts if str(t).strip()]
    if not posts:
        res["error"] = "没有可做图的帖子（先点「一键更新」生成今日推单）。"
        return res
    res["total"] = len(posts)
    out_dir = Path(out_dir)
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
        for old in out_dir.glob("*.png"):                              # 上一次的图删掉，免得多出来旧图
            if re.match(r"^\d\d_", old.name):
                old.unlink()
        page = build_page(posts, B, theme)
        hp = out_dir / HTML_NAME
        hp.write_text(page, encoding="utf-8")
        res["html"] = str(hp)
    except OSError as exc:
        res["error"] = f"写不了图片文件夹：{exc}"
        return res
    exe = find_browser(browser)
    if not exe:
        res["error"] = (f"没找到 Edge / Chrome 浏览器，没法自动截图。已生成「{HTML_NAME}」：用浏览器打开它，每张卡片可以右键截图（或按 Win+Shift+S）。"
                        "在操作台点「选择浏览器」，选 chrome.exe 或 msedge.exe；命令行可用 --browser 指定完整路径。")
        return res
    res["browser"] = exe
    tmp = Path(tempfile.mkdtemp(prefix="tipsnap_"))                      # 临时文件放纯英文路径，浏览器最稳
    try:
        tp = tmp / "cards.html"
        tp.write_text(page, encoding="utf-8")
        url = tp.as_uri()
        n = len(posts)
        items: List[Any] = [(nm, tx, None, i, n) for i, (nm, tx) in enumerate(posts, 1)]
        mode, heights = "new", None
        for md in ("new", ""):                                           # 新版无界面模式不行就换旧版
            udir = str(tmp / ("ud_" + (md or "old")))
            heights = measure(exe, md, udir, url, n)
            if heights:
                mode = md
                break
        measured = bool(heights)
        if not heights:
            log("  （没能量出卡片高度，改用估算高度；图片下方可能多一点底色）")
            heights = [_est_h(t) for _, t in posts]
            mode = "new"
        medals = [x for x in ((B or {}).get("榜单勋章") or []) if isinstance(x, str)]
        # 太高的帖子（竞足 7 场、复盘……）拆成几张，每张不超过 MAX_CARD_H：X 上看得全，也不会被压缩
        if any(h > MAX_CARD_H for h in heights):
            new_items: List[Any] = []
            for it, h in zip(items, heights):
                parts = split_into_parts(it[1], -(-h // MAX_CARD_H), medals) if h > MAX_CARD_H else [it[1]]
                if len(parts) > 1:
                    new_items += [(it[0], pt, (pi, len(parts)), it[3], it[4]) for pi, pt in enumerate(parts, 1)]
                else:
                    new_items.append(it)
            if len(new_items) != len(items):
                items = new_items
                res["total"] = len(items)
                page = build_page(items, B, theme)
                (out_dir / HTML_NAME).write_text(page, encoding="utf-8")
                tp = tmp / "cards2.html"
                tp.write_text(page, encoding="utf-8")
                url = tp.as_uri()
                heights = (measure(exe, mode, str(tmp / "ud_m2"), url, len(items)) if measured else None) or [_est_h(it[1]) for it in items]
                log(f"  （有 {len(items) - n} 张图是长帖拆出来的，每张不超过 {MAX_CARD_H} 像素高）")
        udir = str(tmp / "ud_shot")
        for i, (it, h) in enumerate(zip(items, heights), 1):
            if cancel and cancel():
                res["error"] = "已停止。"
                break
            name, part, oi = it[0], it[2], it[3]
            dest = out_dir / (f"{oi:02d}_{_safe_name(name)}" + (f"_图{part[0]}" if part else "") + ".png")
            tmpdest = tmp / f"s{i}.png"
            want_h = h + 2 * PAD
            ok = False
            # 无界面浏览器的窗口会被「吃掉」一截高度（约 90 像素，没有画面），所以窗口开高一点，截完再把底部多出来的底色裁掉
            if shoot(exe, mode, udir, f"{url}?c={i - 1}", tmpdest, want_h + SHOT_EXTRA):
                sz = png_size(tmpdest)
                if sz and sz[1] >= want_h * SCALE - 2:
                    ok = True
                    crop_png_rows(tmpdest, want_h * SCALE)
            if ok:
                shutil.move(str(tmpdest), str(dest))
                res["files"].append(str(dest))
                log(f"  ✔ {dest.name}")
            else:
                log(f"  ✘ 「{name}」这张没截出来")
        if len(res["files"]) < len(items) and not res["error"]:
            res["error"] = (f"{len(items) - len(res['files'])} 张没截出来（浏览器没响应）。可以再点一次；"
                            f"或者用浏览器打开「{HTML_NAME}」自己截图。")
    except Exception as exc:  # noqa: BLE001
        res["error"] = f"做图时出错：{exc}"
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return res


# ════════════════════════════════════════════════════════════════════════════
# 5. 命令行：python snapshot.py [--day 日期] [--theme 深色]
# ════════════════════════════════════════════════════════════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="给推单帖子做图片快照")
    ap.add_argument("--day", help="哪一天的推单（默认最近一次）")
    ap.add_argument("--history", default="", help="历史推单文件（默认：脚本文件夹里的 tips_history.json）")
    ap.add_argument("--theme", choices=["浅色", "深色"], help="底色（默认读 brand.json 的「图片配色」）")
    ap.add_argument("--browser", default="", help="浏览器路径（默认自动找 Edge/Chrome）")
    ap.add_argument("--out", help="图片文件夹（默认 推单图片_日期）")
    args = ap.parse_args(argv)
    base = L.app_root(__file__)
    hist_path = Path(args.history) if args.history else L.p(base, "tips_history.json")
    if args.history:
        base = L.find_root(hist_path.resolve().parent)
    try:
        hist = json.loads(hist_path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        print(f"读不了 {hist_path}：{exc}")
        return 2
    runs = hist.get("runs") or {}
    day = args.day or (sorted(runs)[-1] if runs else "")
    posts = [(p["name"], p["text"]) for p in (runs.get(day) or {}).get("posts", [])]
    if not posts:
        print("历史里没有这一天的推文原文。先运行 gen_tips.py / 点「一键更新」。")
        return 2
    B: Dict[str, Any] = {}
    try:
        B = json.loads(L.p(base, "brand.json").read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        pass
    out = Path(args.out) if args.out else L.p(base, IMG_DIR_FMT.format(day=day))
    r = make_images(posts, out, B=B, theme=args.theme, browser=args.browser)
    print(f"图片 {len(r['files'])}/{len(posts)} 张 → {out}")
    if r["error"]:
        print("⚠ " + r["error"])
    return 0 if r["files"] else 1


if __name__ == "__main__":
    sys.exit(main())
