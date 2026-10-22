#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""推单文案自动生成：读取 export_500_all.py 导出的 xlsx，只用 Python 3.9+ 标准库。

每天两步
  python export_500_all.py --keep-older-draws          # 1) 采集 → 500网数据_2026-10-15.xlsx
  python gen_tips.py 500网数据_2026-10-15.xlsx          # 2) 结算昨日推单 → 生成今日推单 → 推单文案_2026-10-15.txt

想用窗口操作（不用敲命令）：双击 启动操作台.bat（即 tips_console.pyw），它调用的就是本文件里的 run()。

前后衔接靠 tips_history.json（整理后的结构放在「数据库」文件夹；旧结构就在当前文件夹）
  * 每次生成的推单都存进去，状态为 pending；
  * 第二天的 xlsx 里「昨日已开奖」有了赛果，脚本按 销售日+赛事编号 找到对应推单并判定 命中/未中；
  * 每种玩法一篇文章：先「📊昨日复盘」（昨日赛果概况＋我们昨天推的单逐条对账，命中未中都列），再「🔥今日推单」；
    另有一条很短的总览（昨日战绩、近 7 日累计）。
  * 漏了某天没跑：下次运行会自动补结算那天的推单（用本地旧表，或 --backfill 调用 export_500_all.py 补抓）。
  * 某天没跑也不会乱：结果没出的推单一直 pending，超过 4 天仍无结果就标为作废，不计入命中率。
  * 赛果库 results_db.json：每次运行存下昨日已开奖的比分（竞足、北单；还有 500 网「完场」页里全部赛事的比分，一天 200 多场），
    用来算两队近况。刚开始用时可以先补一次历史：python gen_tips.py --history-days 30（操作台上是「补历史赛果」按钮，约 1～2 分钟）。
    操作台每天更新时会自动读完场页，赛果库还很空时第一次会自动补 30 天；命令行每天更新想要同样效果，加 --wanchang。

推单规则（全部可在下面「可调参数」里改；脚本只用表里有的数据）
  北单   把「让球胜/平/负」SP 换算成概率，取最热方向，概率 ≥ 55% 的前 8 场；2/3/4 串 1 的参考 SP 是各场 SP 相乘。
  竞足   表里没有赔率，只有让球线。用时间 + 球队名模糊匹配同一场的北单 SP 当参考：
         - 北单让球线=0 的场次，主胜/客胜概率 ≥ 50% 推胜平负；
         - 有让球线的场次，用「热门方赢盘」概率当下限（赢盘本身就是赢球的子集），|线|=0/1 要 ≥ 50%，|线|=2 要 ≥ 40%；
         - 竞足让球线和北单线相同、且赢盘概率 ≥ 50% 时，再加一个让球胜平负。
         - 数据矛盾（竞足说主队让球、北单却是客队更热）的场次不推，并在运行结果里提示。
  竞篮   主队让分绝对值 ≥ 10 的大热门推胜负，并给相邻的胜分差区间。
  传统足彩  胜负彩每场给 单选/双选/全包；任选九取把握最高的 9 场；4场进球、6场半全场按热门强弱给固定模板（把握最低）。
  综合推单（v2.5，composite.py）  选单标准不变（上面这些），但每场推荐都会算一个「综合概率」＝赔率/盘口 70% + 数据模型 30%
         （去掉庄家抽水后对数加权合并），再按两队数据小幅加减。它用来排序、打星、写在帖子里、挑任九、选防冷重点，
         并单独出一条「综合推单」帖；它只是更好的概率估计，不是命中保证，战绩统计页会逐档核对说的和实际差多少。
  脚本光看赔率拿不到伤停、近况这类信息，所以有两条路补：
    ① 自动：加 --team-data（操作台「设置」里勾「自动抓两队数据」）。每次运行抓两队的近况、伤停、交锋，
       和推单方向对比：数据支持的才推，数据反对的不推，没查到数据的场次也不推。数据来源 --source：
         sina  读新浪彩票的公开文章（竞彩情报/足彩伤停/交战记录），免费、不要密钥（sina_data.py）；
               再加上脚本自己攒的赛果库（每次运行存下 500 网昨日已开奖的比分），没有文章的比赛用它算近况；
               竞篮（篮球）不靠新浪：每次更新会读 500 网「篮球完场页」存比分，用它建数据模型（bb_data.py），免费、不要密钥；
         api   API-Football 接口，近 6 场战绩+进失球、联赛排名、伤停、交锋，要自己注册密钥（team_data.py）；
         both  新浪优先，新浪没有的比赛再用接口补；auto（默认）= 填了密钥就 both，没填就 sina。
       先用 python gen_tips.py --check-data 测试能不能用。
    ② 手动：manual.json 人工修正（见 --manual）。手写的对比优先于自动抓的。
  澳客赔率（加 --market；操作台默认开，market_data.py）：读澳客（okooo.cn）的竞彩赛程页和凯利方差页，两个页面，守 robots.txt 和它写的访问时间段。
    · 竞足自己的 SP：竞足没配上北单的场次，改用它当参考赔率（赛事编号+开赛时间精确配对）；
    · 市场共识：每场约 25 家公司的最新赔率去水后取中位数，补进两队数据对比；推荐方向是「某队赢」而市场只给它很低的赢球概率时，
      「数据支持」降成「部分支持」（不进串关），低于 30% 算「数据不支持」。读不到只提示，不影响出推单。

manual.json（都可省略，格式见同目录 manual.example.json）
  exclude_teams  含这个队名的场次：不推，胜负彩改全包，任九不选（用来排除有伤停/赛前消息的场次）
  sfc_overrides  胜负彩手动指定某一场，如 {"2": "3/1"}
  extra_picks    手动加的推荐，同样会被次日自动结算。支持：
                 竞足（胜平负/让球胜平负/总进球/半全场/比分）、竞篮（胜负/胜分差）、北单（key 写场次号，如 "93"）
  match_notes    每场的「两队数据对比」（近况/排名/伤停/交锋），会挂在这场推单下面一行。这里是手填的；
                 想让脚本每次自动抓就用 --team-data。每条的 verdict：support 数据支持 / mixed 部分支持（不进串关）/ against 数据反对（这场撤掉）。
  require_notes  true = 没有对比数据的场次一律不推，保证发出去的每场都有数据依据
  day            这份对比对应的销售日 YYYY-MM-DD；换了一天自动失效（旧数据不会套到新比赛上）
  sources        数据来源，写进运行提示（不用发）
"""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import sys
import tempfile
import time
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from xml.etree import ElementTree as ET
from zipfile import ZipFile

__version__ = "3.1.4-esports.5"

import layout as L                      # 文件夹整理：各种文件放哪个分类文件夹（缺这个文件会提示）

IMPORT_ERRORS: Dict[str, str] = {}      # 哪个附加模块没载入成功、为什么（界面用来给出看得懂的提示）
try:                                   # 战绩统计（stats.py）：缺这个文件时其余功能照常用
    import stats as ST
except Exception as _exc:  # noqa: BLE001
    ST = None
    IMPORT_ERRORS["stats.py"] = f"{type(_exc).__name__}: {_exc}"
try:                                   # 发帖前把关（guard.py）：同上
    import guard as GD
except Exception as _exc:  # noqa: BLE001
    GD = None
    IMPORT_ERRORS["guard.py"] = f"{type(_exc).__name__}: {_exc}"
try:                                   # 综合推单（composite.py）：缺这个文件时退回只看赔率，其余功能照常用
    import composite as C
except Exception as _exc:  # noqa: BLE001
    C = None
    IMPORT_ERRORS["composite.py"] = f"{type(_exc).__name__}: {_exc}"
try:                                   # 每日关键词（keywords.py）：缺这个文件时不出关键词，其余功能照常用
    import keywords as KW
except Exception as _exc:  # noqa: BLE001
    KW = None
    IMPORT_ERRORS["keywords.py"] = f"{type(_exc).__name__}: {_exc}"
try:                                   # 评论话术（commentary.py）：缺这个文件时不出评论话术，其余功能照常用
    import commentary as CM
except Exception as _exc:  # noqa: BLE001
    CM = None
    IMPORT_ERRORS["commentary.py"] = f"{type(_exc).__name__}: {_exc}"


class Laps:
    """每一步花了多少秒（运行日志末尾给一行「用时」，哪一步慢一眼就看得出来）。"""

    def __init__(self) -> None:
        self.t0 = self.last = time.perf_counter()
        self.items: List[Tuple[str, float]] = []

    def lap(self, name: str) -> None:
        t = time.perf_counter()
        self.items.append((name, t - self.last))
        self.last = t

    def total(self) -> float:
        return time.perf_counter() - self.t0

    def text(self, min_s: float = 0.5) -> str:
        big = [f"{n} {d:.1f}秒" for n, d in self.items if d >= min_s]
        return f"总共 {self.total():.1f} 秒" + ("：" + "｜".join(big) if big else "（每一步都很快）")


class TipsError(Exception):
    """可以直接显示给用户看的错误（读不了表、manual.json 格式不对、写不了文件……）。"""

# ════════════════════════════════════════════════════════════════════════════
# 可调参数
# ════════════════════════════════════════════════════════════════════════════
BD_MIN_P = 0.55            # 北单：最热方向概率下限（v2.3/v2.4 曾收紧到 0.60，v2.5 改回 0.55：选单不收紧，把功夫放在预测模型上）
BD_TOP_N = 8               # 北单：最多推几场
ZC_FULL = {"sfc": 14, "jq4": 4, "zc6": 6}        # 传统足彩每一期应有几场（少了说明抓到的不全）
ZC_NAME = {"sfc": "胜负彩/任九", "jq4": "4场进球", "zc6": "6场半全场"}
JC_MAX = 8                 # 竞足：最多推几场
JL_MIN_LINE = 10.0         # 竞篮：主让分绝对值下限
DRAW_GUARD = 0.29          # 数据模型算平局概率 ≥ 这个值，竞足推荐后面写「防平」
COLD_MAX = 0.60            # 「防冷重点」：推荐方赢球概率（模型算的）最低的一场，只有 ≤ 这个值才提
BD_SP_MIN = 0.0            # 北单：参考赔率(SP)下限（0 = 不限）
BD_SP_MAX = 0.0            # 北单：参考赔率(SP)上限（0 = 不限）
COMBO_MAX_LEGS = 4         # 串关最多几场（0 = 不出串关；串得越多命中概率越低，想少串就把 rules.json 里的「串关最多腿数」改小）
JC_MIN_WIN = 0.0           # 竞足胜平负：热门队「直接赢球」的概率下限（0 = 不限；想挡掉平手盘上的不稳热门，在 rules.json 里调高）
JC_HCP_MIN = 0.50          # 竞足让球胜平负：热门「赢盘」概率下限
NEED_SUPPORT = 0           # 1 = 两队数据只是「部分支持」的单场也不推；0 = 照推（只是不进串关）
COMBO_LEG_MIN = 0.0        # 串关里每一场的把握下限（0 = 不限）
COMP_W_MDL = 0.30          # 综合推单：数据模型占综合概率的多少（其余是赔率/盘口）。不改这一项时，会随历史战绩自动校正（composite_weights.json）
COMP_TOP_N = 6             # 综合推单帖：最多列几场
SHOW_KW = 1                # 每天出不出「今日关键词」（按今天赛事整理的搜索词，一行一个词，不影响推单）：1 = 出，0 = 不出
KW_TOP_N = 12              # 今日关键词：最多取几场热门对阵的搜索词
SHOW_CM = 1                # 每天出不出「评论话术」（给每场比赛配多种人设的评论区话术，只引用真实数据，不影响推单）：1 = 出，0 = 不出
CM_MATCH_MAX = 30          # 评论话术：最多写几场比赛（有推荐的优先，其余的按热度排）
CM_PER = 6                 # 评论话术：有推荐的场次，每场写几条（每条换一种人设）
CM_WATCH_PER = 3           # 评论话术：没有推荐的场次（只观战不表态），每场写几条
CM_MAX_LEN = 42           # 评论话术：每条最长多少字
CM_RECAP_N = 5             # 评论话术：「昨日回顾」最多写几条（命中的和没中的都说）
CM_EMOJI = 0               # 评论话术：每条前面带不带人设的小表情：1 = 带，0 = 不带
SHOW_NINE = 1              # 出不出任九（要连中 9 场，命中概率本来就很低）：1 = 出，0 = 不出
SHOW_JQ4 = 1               # 出不出 4场进球（每场要同时猜准主客队进球数）：1 = 出，0 = 不出
SHOW_ZC6 = 1               # 出不出 6场半全场（每场要猜准半场和全场）：1 = 出，0 = 不出
# 以前（v2.2 及更早）的宽松标准：测试和对比用，日常想回到旧标准直接改 rules.json 里对应项
LEGACY_RULES = {"BD_MIN_P": 0.55, "COMBO_MAX_LEGS": 4, "JC_MIN_WIN": 0.0, "JC_HCP_MIN": 0.50, "NEED_SUPPORT": 0, "COMBO_LEG_MIN": 0.0,
                "SHOW_NINE": 1, "SHOW_JQ4": 1, "SHOW_ZC6": 1}
EXCL_LEAGUES: List[str] = []   # 不推的联赛（联赛名里含有这些字就跳过）
POST_LEAD_MIN = 30         # 建议发帖时间：比该帖里最早开赛的比赛提前几分钟
DRIFT_MIN_PCT = 0.08       # 临场变动：参考赔率相对变化超过这个比例才提醒
THR_BY_LINE = {0: 0.50, 1: 0.50, 2: 0.40}   # 盘口越深，赢盘概率门槛越低；≥3 用 0.35
THR_DEEP = 0.35
DOUBLE_MARGIN = 0.15       # 胜负彩：低于单选门槛不超过这个值 → 双选；再低 → 全包
LINE_BONUS = 0.08          # 排序用：每深 1 球盘口，把握分 +0.08（赢 2 球的难度比赢 1 球大）
CONFLICT_GAP = 0.05        # 竞足/北单方向矛盾的判定：北单胜负概率差至少这么大
MATCH_MINUTES = 20         # 跨表配对：开赛时间最多差几分钟
MATCH_TIGHT_MIN = 5          # 跨表配对：「一边队名认得出」的宽松配对，开赛时间最多差几分钟
BD_EARLY_MIN = 10            # 北单表里的开赛时间比竞足早 10 分钟（北单 00:35、竞足 00:45 是同一场），算宽松配对时要先扣掉
MATCH_MIN_SCORE, MATCH_MIN_SIDE = 0.6, 0.4   # 跨表配对：两队名相似度（均值/各自最低）
EXPIRE_DAYS = 4            # 超过这么多天还没结果的推单标为作废
RECENT_DAYS = 7            # 总览帖里「近 N 日累计」
DEFAULT_LIMIT = 25000      # X Premium 长帖；普通账号用 --limit 280 自动拆成串
KEEP_PICK_DAYS = 365       # 历史里保留多少天的推单（更早的、已有结果的会清掉；战绩统计用的就是这些）
SLIM_PICK_DAYS = 45        # 超过这么多天的推单，把占地方的「两队数据对比」文字去掉（数据标记、模型概率、赛果都留着，统计照常）
KEEP_POST_DAYS = 30        # 每天发出的推文原文保留多少天
DAILY_PLAYS = ("竞足", "竞篮", "北单")   # 赛果按「销售日」出现在每天的「昨日已开奖」表里的玩法（传统足彩不是）

_CTA_MARK = "\x00CTA\x00"                                         # 帖子排好顺序后，再把这个占位换成互动语（这样相邻帖子一定不重样）
CTA_PLAIN = "👍有用点个赞｜🔁转发给球友｜🔔关注不错过"          # 朴素版帖子结尾的互动语（推特：点赞/转发/关注）
CTA_DEFAULT = [                                                  # 自媒体版：每条帖子结尾的互动语。第 1 句用在总览帖（引导关注），其余的轮流用
    "🔔 关注并开启小铃铛，每天开赛前准时更新",
    "👍 觉得有用点个赞，让更多球友看到",
    "🔁 转发给身边的球友，赛后一起对答案",
    "🔖 收藏这条，赛后回来对账",
    "💬 你怎么看？评论区聊聊你的思路",
    "📣 关注 + 转发，明天继续公示战绩",
]
OLD_GREET = ["各位好，今日推单来了", "兄弟们，今天的方案出炉", "今日份推单，请查收", "新的一天，先看结论再看依据"]       # 以前默认的开场白；brand.json 里还是这四句就换成新的钩子
OLD_TIPS = ("⚠️仅供参考，理性购彩，未满18岁禁止购彩", "⚠️仅供参考，理性购彩")   # 以前版本默认写的提示语；brand.json 里还是这句就换成互动语
TAGS ={"总览": "#竞彩 #足球推荐", "竞足": "#竞彩足球 #足球推荐", "北单": "#北京单场 #北单推荐",
        "竞篮": "#竞彩篮球", "胜负彩": "#胜负彩 #任选九 #传统足彩", "进球半全场": "#4场进球 #6场半全场 #传统足彩", "复盘": "#竞彩 #足球复盘", "综合推单": "#综合推单 #足球推荐"}

PLAY_ORDER = ["竞足", "竞足串关", "北单", "北单串关", "竞篮", "竞篮串关", "胜负彩", "任九", "4场进球", "6场半全场"]
BUCKETS = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 25), (26, 999)]
BJT = timezone(timedelta(hours=8))


# ════════════════════════════════════════════════════════════════════════════
# 1. 读 xlsx（标准库；兼容 inlineStr 和 sharedStrings 两种写法）
# ════════════════════════════════════════════════════════════════════════════
_M = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_R = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}"
_P = "{http://schemas.openxmlformats.org/package/2006/relationships}"


def _rich(node: ET.Element) -> str:
    out = []
    for child in node:
        if child.tag == _M + "t":
            out.append(child.text or "")
        elif child.tag == _M + "r":
            t = child.find(_M + "t")
            out.append((t.text or "") if t is not None else "")
    return "".join(out)


def _col(ref: str) -> int:
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group():
        n = n * 26 + ord(ch) - 64
    return n


def read_workbook(path: Path) -> Dict[str, List[Dict[str, str]]]:
    """返回 {表名: [ {表头: 文本} ]}，表头在第 1 行。"""
    sheets: Dict[str, List[Dict[str, str]]] = {}
    with ZipFile(path) as z:
        shared: List[str] = []
        if "xl/sharedStrings.xml" in z.namelist():
            for si in ET.fromstring(z.read("xl/sharedStrings.xml")).iter(_M + "si"):
                shared.append(_rich(si))
        wb = ET.fromstring(z.read("xl/workbook.xml"))
        rels = {r.get("Id"): r.get("Target") for r in ET.fromstring(z.read("xl/_rels/workbook.xml.rels")).iter(_P + "Relationship")}
        for s in wb.iter(_M + "sheet"):
            target = rels.get(s.get(_R + "id")) or ""
            member = target[1:] if target.startswith("/") else "xl/" + target
            rows: List[Dict[int, str]] = []
            for row in ET.fromstring(z.read(member)).iter(_M + "row"):
                vals: Dict[int, str] = {}
                for pos, c in enumerate(row.findall(_M + "c"), 1):
                    idx = _col(c.get("r")) if c.get("r") else pos
                    kind = c.get("t", "n")
                    if kind == "inlineStr":
                        node = c.find(_M + "is")
                        vals[idx] = _rich(node) if node is not None else ""
                    else:
                        v = c.find(_M + "v")
                        text = v.text if v is not None and v.text is not None else ""
                        if kind == "s":
                            try:
                                text = shared[int(text)]
                            except (ValueError, IndexError):
                                text = ""
                        vals[idx] = text
                rows.append(vals)
            if len(rows) >= 2:
                head = rows[0]
                recs = [{t: v.get(i, "") for i, t in head.items() if t} for v in rows[1:]]
                sheets[s.get("name")] = [r for r in recs if any(r.values())]
            else:
                sheets[s.get("name")] = []
    return sheets


# ════════════════════════════════════════════════════════════════════════════
# 2. 小工具
# ════════════════════════════════════════════════════════════════════════════
def num(s: Any) -> Optional[float]:
    try:
        return float(str(s).strip())
    except (TypeError, ValueError):
        return None


def line_of(s: Any) -> float:
    v = num(str(s).replace("＋", "+").replace("－", "-"))
    return 0.0 if v is None else v


def fmt_line(v: float) -> str:
    return "0" if v == 0 else f"{v:+g}"


def parse_dt(s: str) -> Optional[datetime]:
    try:
        return datetime.strptime(s.strip(), "%Y-%m-%d %H:%M")
    except (ValueError, AttributeError):
        return None


def thr_for(line: float) -> float:
    return THR_BY_LINE.get(int(abs(line)), THR_DEEP) if abs(line) < 3 else THR_DEEP


def weight(text: str) -> int:
    """X 的字数权重（近似）：拉丁/常用标点算 1，中文、全角符号、emoji 算 2。"""
    w = 0
    for ch in text:
        o = ord(ch)
        w += 1 if (o <= 0x10FF or 0x2000 <= o <= 0x200D or 0x2010 <= o <= 0x201F or 0x2032 <= o <= 0x2037) else 2
    return w


def split_post(text: str, limit: int) -> List[str]:
    """超过上限就拆成一串。按「段落（空行隔开）」整段放，一段太长才按行拆——标题行不会孤零零留在上一条末尾。"""
    if weight(text) <= limit:
        return [text]
    budget = limit - weight(" (10/10)")
    chunks: List[str] = [""]
    for para in text.split("\n\n"):
        sep = "\n\n" if chunks[-1] else ""
        if weight(chunks[-1] + sep + para) <= budget:
            chunks[-1] += sep + para
        elif weight(para) <= budget:
            chunks.append(para)
        else:                                           # 单段就超长（比如一长串推荐）：只好按行拆
            first = True
            for line in para.split("\n"):
                sep = ("\n\n" if first else "\n") if chunks[-1] else ""
                if chunks[-1] and weight(chunks[-1] + sep + line) > budget:
                    chunks.append(line)
                else:
                    chunks[-1] += sep + line
                first = False
    n = len(chunks)
    return [f"{c} ({i}/{n})" for i, c in enumerate(chunks, 1)]


from reliability import atomic_batch, beijing_now
try:
    import esports_data as ES
except ImportError:
    ES = None


def atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ════════════════════════════════════════════════════════════════════════════
# 0b. 规则文件 rules.json（把「推多少场、排除哪些联赛、赔率范围……」放到一个文件里让人改）
# ════════════════════════════════════════════════════════════════════════════
RULE_FILE = "rules.json"
# （中文设置项, 程序里的变量名, 类型, 最小, 最大, 说明）
RULE_SPECS: List[Tuple[str, str, Any, float, float, str]] = [
    ("竞足最多场数", "JC_MAX", int, 1, 30, "竞足每天最多推几场（挑把握最大的）"),
    ("北单最多场数", "BD_TOP_N", int, 1, 40, "北单每天最多推几场（挑赔率最低的热门）"),
    ("北单最低概率", "BD_MIN_P", float, 0.30, 0.95, "北单：最热方向的概率要达到多少才推（0.55 就是 55%）"),
    ("北单SP下限", "BD_SP_MIN", float, 0, 50, "北单：参考赔率低于这个数不推（0 = 不限）"),
    ("北单SP上限", "BD_SP_MAX", float, 0, 100, "北单：参考赔率高于这个数不推（0 = 不限）"),
    ("竞篮最小让分", "JL_MIN_LINE", float, 0, 60, "竞篮：主队让分的绝对值要 ≥ 这个数才推（只推大热门）"),
    ("串关最多腿数", "COMBO_MAX_LEGS", int, 0, 4, "串关最多几场合一张（0 = 不出串关；2 串 1 比 4 串 1 容易中得多，想少串就改小）"),
    ("竞足平手盘最低概率", "JC_MIN_WIN", float, 0, 0.95, "竞足胜平负：热门队直接赢球的概率要达到多少才推（0 = 不限；写 0.60 就是 60%；让球线 0 的平手盘才用得上）"),
    ("竞足让球最低概率", "JC_HCP_MIN", float, 0.30, 0.95, "竞足让球胜平负：热门赢盘的概率要达到多少才推（0.50 就是 50%）"),
    ("只推数据支持", "NEED_SUPPORT", int, 0, 1, "1 = 两队数据只是「部分支持」的单场也不推；0 = 照推（但不进串关）"),
    ("串关每场最低把握", "COMBO_LEG_MIN", float, 0, 0.95, "串关里每一场的把握要达到多少才能进串关（0 = 不限）"),
    ("模型占比", "COMP_W_MDL", float, 0, 0.8, "综合推单里，数据模型占综合概率的多少（其余是赔率/盘口）：0.30 = 30%，0 = 不用模型。不改这一项，脚本会按历史战绩自动校正"),
    ("综合推单场数", "COMP_TOP_N", int, 1, 12, "「综合推单」帖里最多列几场（按综合概率从高到低）"),
    ("出今日关键词", "SHOW_KW", int, 0, 1, "1 = 每天另外出一份「今日关键词」（一行一个词，按今天的真实赛事整理）；0 = 不出"),
    ("关键词对阵数", "KW_TOP_N", int, 3, 40, "今日关键词里最多取几场热门对阵的搜索词（场数越多，词表越长）"),
    ("出评论话术", "SHOW_CM", int, 0, 1, "1 = 每天另外出一份「评论话术」（每场比赛多种人设的评论区话术，只引用当天真实数据）；0 = 不出"),
    ("评论话术场数", "CM_MATCH_MAX", int, 1, 80, "评论话术最多写几场比赛（有推荐的优先，其余按热度排）"),
    ("每场话术条数", "CM_PER", int, 1, 8, "有推荐的场次，每场写几条话术（每条换一种人设；最多等于启用的人设个数）"),
    ("观战话术条数", "CM_WATCH_PER", int, 0, 8, "没有推荐的场次（只观战、不表态），每场写几条话术（0 = 不写这些场次）"),
    ("话术最长字数", "CM_MAX_LEN", int, 30, 140, "评论每条最长多少字（简短模式最多48字，超长换整句）"),
    ("昨日回顾条数", "CM_RECAP_N", int, 0, 12, "评论话术里「昨日回顾」最多写几条（命中的和没中的轮流说；0 = 不写）"),
    ("话术带表情", "CM_EMOJI", int, 0, 1, "1 = 每条话术前面带人设的小表情；0 = 不带"),
    ("出任九", "SHOW_NINE", int, 0, 1, "1 = 出任九（要连中 9 场，命中概率本来就很低）；0 = 不出"),
    ("出4场进球", "SHOW_JQ4", int, 0, 1, "1 = 出 4场进球（每场要猜准两队进球数，命中概率低）；0 = 不出"),
    ("出6场半全场", "SHOW_ZC6", int, 0, 1, "1 = 出 6场半全场（每场要猜准半场和全场，命中概率低）；0 = 不出"),
    ("防平阈值", "DRAW_GUARD", float, 0.15, 0.50, "模型算的平局概率 ≥ 这个数，竞足推荐后面写「防平」"),
    ("防冷阈值", "COLD_MAX", float, 0.30, 0.95, "推荐方赢球概率最低的一场 ≤ 这个数，才写「防冷重点」"),
    ("排除联赛", "EXCL_LEAGUES", list, 0, 0, "联赛名里含有这些字的比赛不推，例如 [\"友谊赛\", \"女足\"]"),
    ("发帖提前分钟", "POST_LEAD_MIN", int, 0, 600, "「建议发帖时间」比这条帖里最早开赛的比赛提前几分钟"),
    ("赔率变动提醒比例", "DRIFT_MIN_PCT", float, 0.01, 0.50, "再次更新时，参考赔率变化超过这个比例就提醒（0.08 = 8%）"),
]
RULE_PCT = {"COMP_W_MDL", "BD_MIN_P", "DRAW_GUARD", "COLD_MAX", "DRIFT_MIN_PCT", "JC_MIN_WIN", "JC_HCP_MIN", "COMBO_LEG_MIN"}
RULE_DEFAULTS: Dict[str, Any] = {spec[1]: (list(globals()[spec[1]]) if spec[2] is list else globals()[spec[1]]) for spec in RULE_SPECS}
RULE_NOTE = ("这是推单的规则设置：改冒号后面的数字就行（别动引号、冒号和逗号），存盘后下次点「一键更新」生效。"
             "改乱了也没事：看不懂的项会自动用默认值，并在运行日志里告诉你；整个文件删掉就恢复默认。")


RULES_VERSION = 4                                         # 规则文件版本：2 = v2.3 精选标准；3 = 任九/4场进球/6场半全场默认照出；4 = v2.5 选单标准改回宽松
# （文件版本从哪版起, 到哪版止(不含), 设置项, 旧默认值, 新默认值）：文件版本落在 [起, 止) 里时升级一次，且只动没被你改过的（值还是旧默认值）
RULE_UPGRADES = [
    (1, 3, "出任九", 0, 1), (1, 3, "出4场进球", 0, 1), (1, 3, "出6场半全场", 0, 1),            # v2.4：这三个玩法默认照出
    (2, 4, "北单最低概率", 0.60, 0.55), (2, 4, "串关最多腿数", 2, 4),                           # v2.5：撤销 v2.3 的收紧——只动「还是 v2.3 默认值」的项，你自己改过的不碰
    (2, 4, "竞足平手盘最低概率", 0.60, 0.0), (2, 4, "竞足让球最低概率", 0.58, 0.50),
    (2, 4, "只推数据支持", 1, 0), (2, 4, "串关每场最低把握", 0.60, 0.0),
]
LAST_RULE_UPGRADE: List[str] = []                         # 最近一次 ensure_rules_file 做了什么升级（run() 读它写日志）


def rules_default_json() -> Dict[str, Any]:
    d: Dict[str, Any] = {"说明": RULE_NOTE, "规则版本": RULES_VERSION}
    for cn, var, *_ in RULE_SPECS:
        d[cn] = RULE_DEFAULTS[var]
    d["各项说明"] = {spec[0]: spec[5] for spec in RULE_SPECS}
    return d


def ensure_rules_file(folder: Path) -> bool:
    """第一次运行时把默认规则写成 rules.json（已有就不动）；老版本缺了新设置项，只补缺的，已有的原样保留。返回是不是新建的。"""
    path = L.p(folder, RULE_FILE)
    LAST_RULE_UPGRADE.clear()
    try:
        if not path.exists():
            atomic_write(path, json.dumps(rules_default_json(), ensure_ascii=False, indent=2))
            return True
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            ver = data.get("规则版本", 1)
            upg: List[str] = []
            if isinstance(ver, bool) or not isinstance(ver, int) or ver < RULES_VERSION:
                fver = 1 if isinstance(ver, bool) or not isinstance(ver, int) else ver
                for v_lo, v_hi, cn, old, new in RULE_UPGRADES:
                    v = data.get(cn)
                    if v_lo <= fver < v_hi and isinstance(v, (int, float)) and not isinstance(v, bool) and abs(v - old) < 1e-9:   # 还是旧默认值（没被你改过）→ 换成新标准
                        data[cn] = new
                        upg.append(f"{cn} {old:g}→{new:g}")
                data["规则版本"] = RULES_VERSION
            miss = [spec[0] for spec in RULE_SPECS if spec[0] not in data]
            if miss or upg or "各项说明" not in data or data.get("规则版本") != ver:
                dflt = rules_default_json()
                merged = {k: (data[k] if k in data else dflt[k]) for k in dflt}
                merged["各项说明"] = dflt["各项说明"]
                merged.update({k: v for k, v in data.items() if k not in merged})
                atomic_write(path, json.dumps(merged, ensure_ascii=False, indent=2))
                LAST_RULE_UPGRADE.extend(upg + [f"新增 {x}={dflt[x]}" for x in miss])
    except (OSError, ValueError):
        pass
    return False


def apply_rules(folder: Optional[Path]) -> Tuple[List[str], List[str]]:
    """读 rules.json，把设置套到全局参数上。没有文件/某项不对 → 用默认值。返回（和默认不同的项, 提醒）。
    操作台是一直开着的，所以每次都先把所有参数恢复成默认再套，删掉文件或删掉某项就自动恢复。"""
    g = globals()
    for var, val in RULE_DEFAULTS.items():
        g[var] = list(val) if isinstance(val, list) else val
    changed: List[str] = []
    warns: List[str] = []
    if folder is None:
        return changed, warns
    path = L.p(folder, RULE_FILE)
    if not path.exists():
        return changed, warns
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return changed, [f"规则文件 {RULE_FILE} 读不了（{exc}），这次按默认规则运行。删掉它会自动重建。"]
    if not isinstance(data, dict):
        return changed, [f"规则文件 {RULE_FILE} 格式不对（最外层应是 {{ }}），这次按默认规则运行。"]
    known = {spec[0] for spec in RULE_SPECS} | {"说明", "各项说明", "规则版本"}
    for k in data:
        if k not in known:
            warns.append(f"规则文件里的「{k}」不认识，已忽略（是不是写错了字？）")
    for cn, var, typ, lo, hi, _doc in RULE_SPECS:
        if cn not in data:
            continue
        v = data[cn]
        if typ is list:
            if isinstance(v, str):
                v = [x.strip() for x in re.split(r"[,，、;；\s]+", v) if x.strip()]
            if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
                warns.append(f"规则「{cn}」应是一个文字列表，例如 [\"友谊赛\"]，已用默认值")
                continue
            v = [x.strip() for x in v if x.strip()]
        else:
            if isinstance(v, bool) or not isinstance(v, (int, float)):
                try:
                    v = float(str(v).strip().rstrip("%％"))
                    if str(data[cn]).strip().endswith(("%", "％")):
                        v = v / 100
                except ValueError:
                    warns.append(f"规则「{cn}」应是数字，已用默认值 {RULE_DEFAULTS[var]}")
                    continue
            if var in RULE_PCT and 1 < v <= 100:            # 写成 55 的，当 55% 理解
                v = v / 100
            if v != v or v in (float("inf"), float("-inf")) or v < lo or v > hi:
                warns.append(f"规则「{cn}」={data[cn]} 不在 {lo:g}～{hi:g} 之间，已用默认值 {RULE_DEFAULTS[var]}")
                continue
            v = int(round(v)) if typ is int else float(v)
        g[var] = v
        if v != RULE_DEFAULTS[var]:
            changed.append(f"{cn}={('、'.join(v) if typ is list else v)}")
    if g["BD_SP_MAX"] and g["BD_SP_MIN"] and g["BD_SP_MAX"] < g["BD_SP_MIN"]:
        warns.append("规则里「北单SP上限」比「下限」还小，两个都不限制了")
        g["BD_SP_MIN"], g["BD_SP_MAX"] = 0.0, 0.0
    return changed, warns


def league_excluded(lg: Any) -> bool:
    s = str(lg or "")
    return any(x and x in s for x in EXCL_LEAGUES)


# ════════════════════════════════════════════════════════════════════════════
# 0c. 历史文件的滚动备份和自动恢复
# ════════════════════════════════════════════════════════════════════════════
BACKUP_KEEP = 7
BACKUP_DIR = "历史备份"


def _history_ok(h: Any) -> bool:
    return isinstance(h, dict) and isinstance(h.get("picks"), dict)


def backup_dir_of(path: Path) -> Path:
    return L.p(Path(path).parent, BACKUP_DIR)


def list_backups(path: Path) -> List[Path]:
    """最近的备份，新的在前。"""
    d = backup_dir_of(path)
    stem = Path(path).stem
    try:
        fs = [f for f in d.glob(f"{stem}_*.json") if f.is_file()]
    except OSError:
        return []
    return sorted(fs, key=lambda f: f.name, reverse=True)


def rotate_backup(path: Path, keep: int = BACKUP_KEEP) -> Optional[Path]:
    """写新历史之前，把现在这份（读得出才备份）存一份到「历史备份」文件夹，同一天只留最后一份，最多留 keep 天。"""
    path = Path(path)
    try:
        if not path.exists():
            return None
        text = path.read_text(encoding="utf-8")
        if not _history_ok(json.loads(text)):
            return None
        d = backup_dir_of(path)
        d.mkdir(parents=True, exist_ok=True)
        dest = d / f"{path.stem}_{datetime.now(BJT):%Y-%m-%d}.json"
        atomic_write(dest, text)
        for old in list_backups(path)[keep:]:
            try:
                old.unlink()
            except OSError:
                pass
        return dest
    except (OSError, ValueError):
        return None


STATS_TXT, STATS_CSV = "战绩统计.txt", "战绩统计.csv"


def write_stats_files(hist: Dict[str, Any], day: str, folder: Path, csv_too: bool = True) -> Optional[Path]:
    """把战绩统计写成 战绩统计.txt（和 .csv）放在脚本文件夹里。写不了就算了（只是附加功能），返回 txt 路径。"""
    if ST is None:
        return None
    try:
        S = ST.compute(hist, day, DRAW_GUARD)
        out = L.p(folder, STATS_TXT)
        atomic_write(out, ST.report_text(S))
        if csv_too:
            ST.export_csv(hist, L.p(folder, STATS_CSV))
        return out
    except (OSError, ValueError, KeyError, TypeError):
        return None


def save_history(path: Path, hist: Dict[str, Any]) -> None:
    rotate_backup(path)
    atomic_write(path, json.dumps(hist, ensure_ascii=False, indent=1))


# ════════════════════════════════════════════════════════════════════════════
# 3. 跨表配对（竞足 / 传统足彩 ↔ 北单）：开赛时间相近 + 队名模糊相似
# ════════════════════════════════════════════════════════════════════════════
def _norm(name: str) -> str:
    return re.sub(r"[\s·\-—_.()（）]|FC|CF|SC", "", (name or "").upper())


_ALIAS: Any = None          # 球队别名表（sina_data.ZhNames）；run() 开头装上，用来认出「狼队＝伍尔弗汉普顿」这类不同写法


def use_aliases(folder: Optional[Path]) -> None:
    """装上球队别名表（读 sina_data 里内置的 + 你文件夹里的 team_alias.json / team_alias_auto.json）。装不上就算了，只是少一层认队名。"""
    global _ALIAS
    _ALIAS = None
    if folder is None:
        return
    try:
        import sina_data as SD
        _ALIAS = SD.ZhNames(folder)
    except Exception:                                  # noqa: BLE001 —— 别名只是加分项，出错不能挡住推单
        _ALIAS = None


def _same_team(a: str, b: str) -> bool:
    if _ALIAS is None or not a or not b:
        return False
    try:
        return _ALIAS.canon(a) == _ALIAS.canon(b)
    except Exception:                                  # noqa: BLE001
        return False


def sim(a: str, b: str) -> float:
    a0, b0 = a, b
    try:
        import sina_data as SD
        if not SD.marks_ok(a, b):
            return 0.0
    except ImportError:
        pass
    a, b = _norm(a), _norm(b)
    if not a or not b:
        return 0.0
    if a == b or (min(len(a), len(b)) >= 2 and (a in b or b in a)):
        return 1.0
    if _same_team(a0, b0):
        return 1.0
    sa, sb = set(a), set(b)
    return len(sa & sb) / min(len(sa), len(sb))


def kick_close(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """宽松配对用的开球时间判断。a 是竞足/传统足彩，b 是北单：北单的时间通常比竞足早 BD_EARLY_MIN 分钟，
    所以「竞足比北单晚 0~10 分钟」是正常的，再各放 MATCH_TIGHT_MIN 分钟余量（也就是晚 -5 ~ 15 分钟）。"""
    if not (a.get("dt") and b.get("dt")):
        return False
    gap = (a["dt"] - b["dt"]).total_seconds() / 60
    return -MATCH_TIGHT_MIN <= gap <= BD_EARLY_MIN + MATCH_TIGHT_MIN


def _score(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    if a["dt"] and b["dt"] and abs((a["dt"] - b["dt"]).total_seconds()) > MATCH_MINUTES * 60:
        return 0.0
    s1, s2 = sim(a["h"], b["h"]), sim(a["a"], b["a"])
    if min(s1, s2) < MATCH_MIN_SIDE:
        # 开赛时间几乎一样（≤5 分钟）、而且有一边队名完全认得出来：多半是同一场，只是另一边两个表写法差太多
        # （例：竞足「伍尔弗汉普顿」、北单「狼队」又没进别名表）。只给刚过线的分数，排在正经配上的后面。
        if kick_close(a, b) and max(s1, s2) >= 1.0:
            return MATCH_MIN_SCORE
        return 0.0
    sc = (s1 + s2) / 2
    return sc if sc >= MATCH_MIN_SCORE else 0.0


def norm_rows(rows: List[Dict[str, str]], h: str, a: str, t: str, lg: str = "") -> List[Dict[str, Any]]:
    return [{"h": r.get(h, ""), "a": r.get(a, ""), "dt": parse_dt(r.get(t, "")), "lg": (r.get(lg, "") if lg else "")} for r in rows]


def lg_same(x: str, y: str) -> bool:
    """两个表里的联赛写法是不是同一个联赛：完全一样、一个包含另一个（欧罗巴＝欧罗巴联赛），或首尾字相同（瑞超＝瑞典超）。"""
    x, y = _norm(x), _norm(y)
    if not x or not y:
        return False
    if x == y or (min(len(x), len(y)) >= 2 and (x in y or y in x)):
        return True
    return min(len(x), len(y)) >= 2 and x[0] == y[0] and x[-1] == y[-1]


WEAK_MIN_SIM = 0.5          # 保守配对：另一边队名至少要有这么多字相同（布鲁马波＝布洛马波卡纳：相同的字占 75%）


def pair_one_to_one(A: List[Dict[str, Any]], B: List[Dict[str, Any]], weak: Optional[List[Tuple[int, int]]] = None) -> Dict[int, int]:
    """先按队名相似度配；剩下的再做一轮保守配对：开球时间对得上（kick_close：北单比竞足早 10 分钟也算）、联赛一样，而且两边（在没配上的场次里）这个
    「联赛+开球时间」都只有这一场，并且至少有一边队名有一半以上的字相同——这样基本不可能配错。保守配上的 (竞足序号, 北单序号) 追加进 weak。"""
    cands = sorted(((_score(a, b), i, j) for i, a in enumerate(A) for j, b in enumerate(B)), reverse=True)
    ua, ub, out = set(), set(), {}
    for sc, i, j in cands:
        if sc <= 0:
            break
        if i in ua or j in ub:
            continue
        ua.add(i); ub.add(j); out[i] = j
    left_a = [i for i in range(len(A)) if i not in ua and A[i].get("dt") and A[i].get("lg")]
    left_b = [j for j in range(len(B)) if j not in ub and B[j].get("dt") and B[j].get("lg")]

    def near(x: Dict[str, Any], y: Dict[str, Any]) -> bool:
        return kick_close(x, y) and lg_same(x["lg"], y["lg"])
    for i in left_a:
        ca = [j for j in left_b if near(A[i], B[j])]
        if len(ca) != 1:
            continue
        j = ca[0]
        back = [k for k in left_a if near(A[k], B[j])]
        if len(back) != 1:
            continue
        if max(sim(A[i]["h"], B[j]["h"]), sim(A[i]["a"], B[j]["a"])) < WEAK_MIN_SIM:
            continue
        out[i] = j
        if weak is not None:
            weak.append((i, j))
    return out


def best_match(a: Dict[str, Any], B: List[Dict[str, Any]]) -> Optional[int]:
    best, bj = 0.0, None
    for j, b in enumerate(B):
        sc = _score(a, b)
        if sc > best:
            best, bj = sc, j
    return bj


# ════════════════════════════════════════════════════════════════════════════
# 4. 单场分析：北单 SP → 概率 → 热门方向 / 把握
# ════════════════════════════════════════════════════════════════════════════
def bd_probs(r: Dict[str, str]) -> Optional[List[float]]:
    sp = [num(r.get("让球胜SP")), num(r.get("让球平SP")), num(r.get("让球负SP"))]
    if any(x is None or x <= 1 for x in sp):
        return None
    inv = [1 / x for x in sp]
    t = sum(inv)
    return [x / t for x in inv]


def analyse(bd: Dict[str, str], jc_line: Optional[float]) -> Dict[str, Any]:
    """fav: '3' 主队热门 / '0' 客队热门；lb: 热门方「赢盘」概率（也是它赢球概率的下限）；adj: 排序用把握分。"""
    p = bd_probs(bd)
    L = line_of(bd.get("让球"))
    info: Dict[str, Any] = {"L": L, "p": p, "jcL": jc_line, "conflict": False, "fav": None, "lb": None, "adj": None, "win_p": None}
    if p is None:
        return info
    pw, _, pl = p
    if L == 0 and jc_line not in (None, 0):
        fav_jc = "3" if jc_line < 0 else "0"
        fav_bd = "3" if pw > pl else "0"
        if fav_jc != fav_bd and abs(pw - pl) >= CONFLICT_GAP:
            info["conflict"] = True
            return info
    if L < 0:
        fav, lb = "3", pw
    elif L > 0:
        fav, lb = "0", pl
    else:
        fav, lb = ("3", pw) if pw >= pl else ("0", pl)
    # 热门「直接赢球」的概率：让球线 0 就是 lb 本身；让 1 球以上时，「让球平」就是热门只赢了让球数那么多，也算它赢球，所以加上平的概率（深盘时是保守的下限）
    info.update(fav=fav, lb=lb, adj=lb + LINE_BONUS * abs(L), win_p=lb + (p[1] if L != 0 else 0.0))
    return info


def direction_hint(info: Dict[str, Any]) -> str:
    """没有明确热门（矛盾/概率低）时，给半全场等玩法一个倾向：优先竞足让球线方向，其次北单。"""
    if info.get("fav") and not info.get("conflict"):
        return info["fav"]
    if info.get("jcL") not in (None, 0):
        return "3" if info["jcL"] < 0 else "0"
    if info.get("L"):
        return "3" if info["L"] < 0 else "0"
    p = info.get("p")
    if p:
        return "3" if p[0] >= p[2] else "0"
    return "3"


# ════════════════════════════════════════════════════════════════════════════
# 5. 推单数据结构
# ════════════════════════════════════════════════════════════════════════════
def mk_pick(day: str, play: str, market: str, key: str, home: str, away: str,
            pick: List[str], label: str, **extra: Any) -> Dict[str, Any]:
    d = {"id": f"{day}|{play}|{market}|{key}", "date": day, "play": play, "market": market, "key": key,
         "home": home, "away": away, "pick": pick, "label": label, "status": "pending", "result": ""}
    d.update(extra)
    return d


STAR_TIERS = (0.55, 0.65, 0.75)      # 综合概率（赔率+模型+两队数据）：竞足胜平负推荐方直接赢球的概率 <55% 不给星，55–65% 一档，65–75% 二档，≥75% 三档
STAR_TIERS_OLD = (0.45, 0.55, 0.65)  # composite.py 缺失时退回 v2.4 的算法：只看模型（校准后）算的赢球概率


def star_of(p: Dict[str, Any]) -> Optional[Tuple[int, float]]:
    """竞足胜平负的「信心档位」(★数 1–3, 综合概率)。只在综合概率里真的掺了回测过关的数据模型时才有。
    ★ 只是把「综合概率」换成好读的档位——它准不准，战绩统计页里会逐档核对，没区分度就自动不显示。"""
    if p.get("play") != "竞足" or p.get("market") != "胜平负":
        return None
    if C is not None:
        if not C.has_model(p):
            return None
        tier = sum(p["cp"] >= t for t in STAR_TIERS)
        return (tier, float(p["cp"])) if tier else None
    m = p.get("mdl")                                  # composite.py 缺失：v2.4 的老算法
    if not (isinstance(m, dict) and m.get("ok")):
        return None
    pk = list(p.get("pick") or [])
    pp = m.get("ph") if pk == ["胜"] else m.get("pa") if pk == ["负"] else None
    if not isinstance(pp, (int, float)):
        return None
    tier = sum(pp >= t for t in STAR_TIERS_OLD)
    if tier == 0:
        return None
    return min(3, tier + (1 if p.get("cmp_v") == "support" else 0)), float(pp)


COMP_W_USE: Optional[float] = None   # run() 按历史战绩校正出来的模型占比；None = 用 COMP_W_MDL


def comp_w() -> float:
    """综合概率里模型占多少：rules.json 里「模型占比」改过就听你的；没改就用按历史战绩校正出来的（样本不够时是默认 30%）。"""
    if COMP_W_USE is not None and abs(COMP_W_MDL - RULE_DEFAULTS["COMP_W_MDL"]) < 1e-12:
        return COMP_W_USE
    return COMP_W_MDL


def comp_pick(p: Dict[str, Any], info: Optional[Dict[str, Any]], kind: str) -> None:
    """给一条足球单场推荐算综合概率（赔率 + 数据模型 + 两队数据），写进推单，并按它更新排序分 conf 和星级。composite.py 缺了就什么也不做。"""
    if C is None or not info:
        return
    c = C.football(info, p.get("mdl"), p.get("cmp_v"), kind, comp_w())
    if not c:
        return
    C.attach(p, c)
    if "conf" in p:
        p["conf"] = round(c["adj"], 3)
    st_ = star_of(p)
    if st_:
        p["star"], p["pp"] = st_[0], round(st_[1], 3)
    else:
        p.pop("star", None)
        p.pop("pp", None)


def mk_combo(day: str, play: str, legs: List[Dict[str, Any]], sp: Optional[float] = None) -> Dict[str, Any]:
    n = len(legs)
    return {"id": f"{day}|{play}串关|{n}串1", "date": day, "play": play + "串关", "market": "串关", "key": f"{n}串1",
            "label": f"{n}串1", "legs": [x["id"] for x in legs], "sp": sp, "status": "pending", "result": ""}


# ════════════════════════════════════════════════════════════════════════════
# 6. 生成今日推单
# ════════════════════════════════════════════════════════════════════════════
class Manual:
    def __init__(self, data: Optional[Dict[str, Any]] = None):
        data = data or {}
        self.exclude_teams: List[str] = list(data.get("exclude_teams", []))
        self.sfc_overrides: Dict[str, str] = {str(k): str(v) for k, v in data.get("sfc_overrides", {}).items()}
        self.extra_picks: List[Dict[str, Any]] = list(data.get("extra_picks", []))
        # 两队数据对比：每场写一条真实查到的对比（近况/排名/伤停/交锋），脚本只负责把它挂到推单下面，自己不会上网查。
        #   match_notes  [{"teams": ["托林斯|托伦斯", "桑德兰"], "verdict": "support|mixed|against", "note": "…", "why": "…"}]
        #                teams 两项各写队名里的几个字（"|" 隔开可写多个叫法）；verdict：support 数据支持 / mixed 部分支持 / against 数据反对（这场撤掉）
        #   require_notes true = 没有对比数据的场次一律不推（保证发出去的每一场都有数据依据）
        #   day          这份对比对应的销售日 YYYY-MM-DD；换了一天自动失效，免得旧数据套到新比赛上
        #   sources      数据来源，写进运行提示（不用发）
        self.match_notes: List[Dict[str, Any]] = [n for n in data.get("match_notes", []) if isinstance(n, dict)]
        self.require_notes: bool = bool(data.get("require_notes", False))
        self.notes_day: Optional[str] = data.get("day") or None
        self.sources: List[str] = [str(s) for s in data.get("sources", [])]
        self.notes_on: bool = True
        # 自动抓来的两队数据（见 team_data.py）：只对本次运行有效，排在手写 match_notes 后面（手写的优先）
        self.auto_notes: List[Dict[str, Any]] = []
        self.auto_required: bool = False

    def set_day(self, day: str) -> None:
        self.notes_on = self.notes_day is None or self.notes_day == day

    def set_auto(self, notes: List[Dict[str, Any]], required: bool = True) -> None:
        self.auto_notes = [n for n in notes if isinstance(n, dict)]
        self.auto_required = required

    def has_notes(self) -> bool:
        return bool(self.auto_notes) or self.auto_required or (self.notes_on and bool(self.match_notes or self.require_notes))

    @staticmethod
    def _find(notes: List[Dict[str, Any]], text: str) -> Optional[Dict[str, Any]]:
        for n in notes:
            teams = n.get("teams")
            if isinstance(teams, list) and len(teams) == 2 and all(
                    any(a and a in text for a in str(t).split("|")) for t in teams):
                return n
        return None

    def note_for(self, *names: Optional[str]) -> Optional[Dict[str, Any]]:
        text = "".join(n or "" for n in names)
        if self.notes_on:
            hit = self._find(self.match_notes, text)
            if hit is not None:
                return hit
        return self._find(self.auto_notes, text)

    def verdict(self, *names: Optional[str]) -> Optional[str]:
        v = (self.note_for(*names) or {}).get("verdict")
        return v if v in ("support", "mixed", "against") else None

    def lean(self, *names: Optional[str]) -> Optional[str]:
        """这场数据看好哪边：主队 '3' / 客队 '0'（note 里写 "lean": "home" 或 "away"）；没写返回 None。"""
        return {"home": "3", "away": "0"}.get((self.note_for(*names) or {}).get("lean") or "")

    def excluded(self, *names: str) -> bool:
        if any(t and t in (n or "") for t in self.exclude_teams for n in names):
            return True
        if self.has_notes():
            nt = self.note_for(*names)
            if nt is None:
                return self.auto_required or (self.notes_on and self.require_notes)
            return nt.get("verdict") == "against"
        return False


def generate(wb: Dict[str, List[Dict[str, str]]], day: str, manual: Manual, wide: bool = False, market: Any = None) -> Dict[str, Any]:
    """wide=True：候选池放宽（北单多留几场、竞足多留几场），用来先找出「需要查两队数据的场次」，再按数据定稿。
    market：可选，market_data.Market（澳客的竞足 SP 和各公司赔率）。给了它：竞足没配上北单的场次，改用竞足自己的 SP 当参考；
    每场足球推荐的澳客记录放进 meta["mkt"]（键是「主队|客队」），供 run() 给两队数据对比补市场共识。"""
    warnings: List[str] = []
    picks: List[Dict[str, Any]] = []
    meta: Dict[str, Any] = {"bd_fetch": "", "sfc_issue": "", "sfc_deadline": "", "jq4_issue": "", "zc6_issue": "",
                            "jl_league": "", "mkt": {}, "mkt_fb": [], "fb_diag": []}
    manual.set_day(day)
    if manual.notes_day and not manual.notes_on:
        warnings.append(f"manual.json 里的两队数据对比是 {md(manual.notes_day)} 的，今天不适用，已忽略（要用请重新查今天的比赛）")

    def mkp(*a: Any, **k: Any) -> Dict[str, Any]:       # 造一条推荐，并把这场的「两队数据对比」挂上去
        p = mk_pick(*a, **k)
        nt = manual.note_for(p.get("home"), p.get("away"))
        if nt and nt.get("note"):
            p["cmp"], p["cmp_v"] = str(nt["note"]), (nt.get("verdict") if nt.get("verdict") in ("support", "mixed", "against") else None)
        if nt and isinstance(nt.get("mdl"), dict):               # 数据模型算的比分/进球数/胜平负概率（帖子里的「比分参考」用）
            p["mdl"] = nt["mdl"]
        if nt and isinstance(nt.get("bbm"), dict):               # 篮球数据模型：预计净胜分（综合推单用）
            p["bbm"] = nt["bbm"]
        if C is None:                                            # composite.py 缺了：星级退回 v2.4 的算法（有综合概率时，星级在 comp_pick 里算）
            st_ = star_of(p)
            if st_:
                p["star"], p["pp"] = st_[0], round(st_[1], 3)
        return p

    def solid(ps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:     # 串关只用「数据支持」的单场；数据只是部分支持的单场不进串关
        return [x for x in ps if x.get("cmp_v") != "mixed"]

    jc = [r for r in wb.get("竞足-今日未开赛", []) if r.get("停售") != "是" and not league_excluded(r.get("联赛"))]
    bd = [r for r in wb.get("北单-今日未开赛", []) if not league_excluded(r.get("联赛"))]
    A = norm_rows(jc, "主队", "客队", "开赛时间(北京时间)", "联赛")
    B = norm_rows(bd, "主队", "客队", "开赛时间(北京时间)", "联赛")
    weak_pairs: List[Tuple[int, int]] = []
    jc2bd = pair_one_to_one(A, B, weak_pairs)
    if weak_pairs:                  # 保守配上的：把两边叫法不同的队名记下来（run() 存进 team_alias_auto.json，以后自动认得）
        meta["weak_pairs"] = [f"{jc[i].get('主队', '')}vs{jc[i].get('客队', '')}＝{bd[j].get('主队', '')}vs{bd[j].get('客队', '')}" for i, j in weak_pairs]
        meta["alias_pairs"] = [(x, y) for i, j in weak_pairs
                               for x, y in ((jc[i].get("主队", ""), bd[j].get("主队", "")), (jc[i].get("客队", ""), bd[j].get("客队", "")))
                               if x and y and not _same_team(x, y) and _norm(x) != _norm(y)]
    bd2jc = {j: i for i, j in jc2bd.items()}
    infos = {j: analyse(bd[j], line_of(jc[bd2jc[j]].get("让球")) if j in bd2jc else None) for j in range(len(bd))}
    for j, info in infos.items():
        if info["conflict"]:
            r, c = bd[j], jc[bd2jc[j]]
            warnings.append(f"数据矛盾已跳过：{c.get('赛事编号')} {c.get('主队')}vs{c.get('客队')}"
                            f"（竞足让球线{c.get('让球')}，北单线{r.get('让球')}且客/主概率为{info['p'][2]:.0%}/{info['p'][0]:.0%}）")
    used_bd = set(jc2bd.values())

    def mrec(c: Dict[str, str]) -> Optional[Dict[str, Any]]:      # 竞足一行 → 澳客那一场（按赛事编号 + 开赛时间精确配）
        return market.lookup(c.get("赛事编号", ""), c.get("开赛时间(北京时间)", "")) if market else None

    def fb_info(c: Dict[str, str]) -> Optional[Dict[str, Any]]:
        """竞足没配上北单时：用澳客页上竞足自己的 SP 当参考赔率，算法和北单一样（让球线必须和表里的竞足让球线一致，否则不用）。"""
        rec = mrec(c)
        if not rec or rec.get("ended"):
            return None
        rq = rec.get("rq", 0)
        if line_of(c.get("让球")) != rq:
            return None
        sp3 = rec.get("rqsp") if rq != 0 else rec.get("sp")
        if not sp3:
            return None
        return analyse({"让球": fmt_line(rq), "让球胜SP": str(sp3[0]), "让球平SP": str(sp3[1]), "让球负SP": str(sp3[2])}, float(rq))

    for i, c in enumerate(jc):
        if i not in jc2bd:
            if fb_info(c) is not None:                    # 有竞足自己的 SP，下面照常出推荐，不用提醒「没配上」
                dt0 = A[i]["dt"]
                near_bd = [B[j] for j in range(len(B)) if j not in used_bd and dt0 is not None and B[j]["dt"] is not None
                           and abs((B[j]["dt"] - dt0).total_seconds()) <= MATCH_MINUTES * 60]
                if near_bd:
                    meta.setdefault("fb_diag", []).append(
                        f"{c.get('赛事编号')} {c.get('主队')}vs{c.get('客队')}（{c.get('联赛', '')} {dt0:%H:%M}）←→ 北单同一时间："
                        + "、".join(f"{b['h']}vs{b['a']}（{b.get('lg', '')} {b['dt']:%H:%M}）" for b in near_bd[:4]))
                continue
            dt = A[i]["dt"]
            same = [B[j] for j in range(len(B)) if j not in used_bd and dt is not None and B[j]["dt"] is not None
                    and abs((B[j]["dt"] - dt).total_seconds()) <= MATCH_MINUTES * 60]
            why = ("北单同一开球时间没有未配上的比赛，应该是北单没开这场" if not same else
                   "北单同一开球时间有：" + "、".join(f"{b['h']}vs{b['a']}" for b in same[:3]) + "（队名叫法差太多没认出，是同一场的话告诉我）")
            warnings.append(f"竞足 {c.get('赛事编号')} {c.get('主队')}vs{c.get('客队')} 没配上北单，无参考赔率，未推（{why}）")
    if bd:
        meta["bd_fetch"] = (bd[0].get("抓取时间(北京时间)") or "")[11:16]

    def longer(x: str, y: str) -> str:   # 竞足和北单的队名都可能被站点截短，取较长的那个
        return x if len(x) >= len(y) else y

    def jc_names(j: int) -> Tuple[str, str]:
        if j in bd2jc:
            c = jc[bd2jc[j]]
            return longer(c.get("主队", ""), bd[j].get("主队", "")), longer(c.get("客队", ""), bd[j].get("客队", ""))
        return bd[j].get("主队", ""), bd[j].get("客队", "")

    # —— 北单 ——
    cands = []
    for j, r in enumerate(bd):
        info = infos[j]
        if info["p"] is None or info["conflict"] or manual.excluded(r.get("主队"), r.get("客队")):
            continue
        pw, _, pl = info["p"]
        side = "胜" if pw >= pl else "负"
        sp = num(r["让球胜SP" if side == "胜" else "让球负SP"])
        if sp is not None and ((BD_SP_MIN and sp < BD_SP_MIN) or (BD_SP_MAX and sp > BD_SP_MAX)):
            continue
        if max(pw, pl) >= BD_MIN_P:
            cands.append((sp, j, side, max(pw, pl)))
    pool: List[Tuple[Dict[str, Any], int]] = []
    for sp, j, side, p in cands:
        r = bd[j]
        pk = mkp(day, "北单", "让球胜平负", f"{r['期号']}-{r['场次']}", r["主队"], r["客队"], [side],
                 f"让球{side}", no=r["场次"], issue=r["期号"], line=fmt_line(info_line(infos[j])), sp=sp, prob=round(p, 3),
                 kick=r.get("开赛时间(北京时间)", ""), lg=r.get("联赛", ""))
        comp_pick(pk, infos[j], "line")                              # 综合概率（赔率+模型+两队数据），排序用；没有模型时就是赔率概率
        pool.append((pk, j))
    # 排序：综合概率从高到低（没有综合概率就按赔率概率），同分看 SP 低的、场次靠前的
    pool.sort(key=lambda x: (-(x[0].get("cp") if x[0].get("cp") is not None else x[0]["prob"]), x[0].get("sp") if x[0].get("sp") is not None else 99.0, x[1]))
    bd_picks = []
    for pk, j in pool:
        if len(bd_picks) >= BD_TOP_N + (6 if wide else 0):
            break
        r = bd[j]
        if NEED_SUPPORT and pk.get("cmp_v") == "mixed":              # 规则里设了「只推数据支持」：两队数据只是部分支持的不推
            continue
        if j in bd2jc and mrec(jc[bd2jc[j]]):
            meta["mkt"][f"{r['主队']}|{r['客队']}"] = mrec(jc[bd2jc[j]])
        bd_picks.append(pk)
    picks += bd_picks
    bd_solid = [x for x in solid(bd_picks) if (x.get("prob") or 0) >= COMBO_LEG_MIN]
    for n in (2, 3, 4):
        if n <= COMBO_MAX_LEGS and len(bd_solid) >= n:
            prod = math.prod(x["sp"] for x in bd_solid[:n])
            picks.append(mk_combo(day, "北单", bd_solid[:n], round(prod, 2)))

    # —— 竞足 ——
    jc_picks = []
    for i, c in enumerate(jc):
        j = jc2bd.get(i)
        if j is not None:
            info = infos[j]
            hn, an = jc_names(j)          # 竞足的队名常被截短（如「格风暴」），连同北单的全名一起查排除/对比
        else:
            info = fb_info(c)
            if info is None:
                continue
            hn, an = c.get("主队", ""), c.get("客队", "")
        if info["conflict"] or not info["fav"] or manual.excluded(c.get("主队"), c.get("客队"), hn, an):
            continue
        if mrec(c):
            meta["mkt"][f"{hn}|{an}"] = mrec(c)
        if j is None:
            meta["mkt_fb"].append(f"{c.get('赛事编号')} {hn}vs{an}")
        L = info["L"]
        if info["lb"] >= thr_for(L) and (info.get("win_p") or 0) >= JC_MIN_WIN:        # 入选条件看赔率概率（和以前一样，综合概率不用来挡单）
            res = "胜" if info["fav"] == "3" else "负"
            pk_ = mkp(day, "竞足", "胜平负", c["赛事编号"], hn, an, [res], res,
                      line=c.get("让球", ""), conf=round(info["adj"], 3), kick=c.get("开赛时间(北京时间)", ""), lg=c.get("联赛", ""))
            comp_pick(pk_, info, "plain")
            jc_picks.append(pk_)
        if L != 0 and info["jcL"] == L and info["lb"] >= JC_HCP_MIN:
            res = "胜" if L < 0 else "负"
            pk_ = mkp(day, "竞足", "让球胜平负", c["赛事编号"], hn, an, [res], f"让球{res}",
                      line=c.get("让球", ""), conf=round(info["adj"], 3), kick=c.get("开赛时间(北京时间)", ""), lg=c.get("联赛", ""))
            comp_pick(pk_, info, "line")
            jc_picks.append(pk_)
    if NEED_SUPPORT:                                                  # 两队数据只是部分支持：精选标准下不推（这场的胜平负、让球一起撤）
        jc_picks = [p for p in jc_picks if p.get("cmp_v") != "mixed"]
    plain = sorted([p for p in jc_picks if p["market"] == "胜平负"], key=lambda p: -p["conf"])[:JC_MAX + (4 if wide else 0)]
    keep = {p["key"] for p in plain}
    jc_picks = [p for p in jc_picks if p["key"] in keep]
    jc_picks.sort(key=lambda p: (-p["conf"], p["market"] != "胜平负"))
    picks += jc_picks
    plain_solid = [x for x in solid(plain) if x["conf"] >= COMBO_LEG_MIN]
    for n in (2, 3):
        if n <= COMBO_MAX_LEGS and len(plain_solid) >= n:
            picks.append(mk_combo(day, "竞足", plain_solid[:n]))

    # —— 竞篮 ——
    jl_rows = [r for r in wb.get("竞篮-今日未开赛", []) if r.get("停售") != "是" and not league_excluded(r.get("联赛"))]
    jl_picks = []
    for r in jl_rows:
        L = line_of(r.get("让分"))
        if abs(L) < JL_MIN_LINE or manual.excluded(r.get("主队"), r.get("客队")):
            continue
        home_fav = L < 0
        res, side = ("主胜", "主胜") if home_fav else ("主负", "客胜")
        pk_ = mkp(day, "竞篮", "胜负", r["赛事编号"], r["主队"], r["客队"], [res], side, line=fmt_line(L),
                  total=r.get("预设总分", ""), lg=r.get("联赛", ""), conf=abs(L), kick=r.get("开赛时间(北京时间)", ""))
        if C is not None:                                            # 综合概率：盘口预计净胜分 + 篮球模型预计净胜分
            C.attach(pk_, C.basketball(L, home_fav, pk_.get("bbm"), pk_.get("cmp_v"), comp_w()))
        jl_picks.append(pk_)
        m = abs(L)
        k = next((i for i, (lo, hi) in enumerate(BUCKETS) if lo <= int(m) <= hi), None)
        if k is not None:
            use = [k] + ([k + 1] if m - BUCKETS[k][0] >= 2.5 and k + 1 < len(BUCKETS) else [])
            vals = [("主胜" if home_fav else "主负") + (f"{BUCKETS[i][0]}-{BUCKETS[i][1]}" if BUCKETS[i][1] < 999 else f"{BUCKETS[i][0]}+") for i in use]
            show = [v[2:] for v in vals]
            jl_picks.append(mkp(day, "竞篮", "胜分差", r["赛事编号"], r["主队"], r["客队"], vals,
                                    "/".join(show), line=fmt_line(L), total=r.get("预设总分", ""), lg=r.get("联赛", ""), conf=abs(L), kick=r.get("开赛时间(北京时间)", "")))
    if NEED_SUPPORT:
        jl_picks = [p for p in jl_picks if p.get("cmp_v") != "mixed"]
    jl_picks.sort(key=lambda p: (-p["conf"], p["market"] != "胜负"))
    picks += jl_picks
    plain_jl = solid([p for p in jl_picks if p["market"] == "胜负"])
    if len(plain_jl) >= 2 and COMBO_MAX_LEGS >= 2:
        picks.append(mk_combo(day, "竞篮", plain_jl[:2]))
    leagues = {r.get("联赛") for r in jl_rows if r.get("联赛")}
    meta["jl_league"] = leagues.pop() if len(leagues) == 1 else ""
    if not jl_rows:                                                  # 竞篮一条都没有时，说清楚是为什么（日志/备查里看）
        meta["jl_note"] = "竞篮：今天表里没有在售的竞篮场次。"
    elif not any(abs(line_of(r.get("让分"))) >= JL_MIN_LINE for r in jl_rows):
        shown = "、".join(f"{r.get('主队', '')}{fmt_line(line_of(r.get('让分')))}" for r in jl_rows[:8])
        meta["jl_note"] = (f"竞篮：今天 {len(jl_rows)} 场，没有主让分绝对值 ≥{JL_MIN_LINE:g} 的大热门，所以没有推（竞篮只推大热门；今天的让分：{shown}）。")

    # —— 传统足彩 ——
    zc = wb.get("传统足彩-在售期", [])
    games: Dict[str, List[Dict[str, str]]] = defaultdict(list)
    for r in zc:
        g = game_kind(r.get("玩法", ""))
        if g:
            games[g].append(r)
    for g_, show_ in (("jq4", SHOW_JQ4), ("zc6", SHOW_ZC6)):          # 命中概率本来就低的玩法：规则里关着就不推（日志里说一声）
        if not show_ and games.get(g_):
            meta.setdefault("zc_off", []).append(ZC_NAME[g_])
            games[g_] = []
    for g_, need_ in ZC_FULL.items():                 # 期号数据不全（比如 4场进球 只抓到 1 场）→ 这期不推，免得发出一张残缺的票
        n_ = len(games.get(g_, []))
        if 0 < n_ < need_:
            warnings.append(f"{ZC_NAME[g_]}这一期只抓到 {n_} 场（应有 {need_} 场），数据不全，这期不推；等网站补全后再点「一键更新」。")
            games[g_] = []
    zc_match: Dict[int, Optional[int]] = {}
    for g, rows in games.items():
        for r in rows:
            n = {"h": r.get("主队", ""), "a": r.get("客队", ""), "dt": parse_dt(r.get("开赛时间(北京时间)", ""))}
            zc_match[id(r)] = best_match(n, B)

    def names_for(r: Dict[str, str]) -> Tuple[str, str]:
        j = zc_match.get(id(r))
        return jc_names(j) if j is not None else (r.get("主队", ""), r.get("客队", ""))

    def zc_info(r: Dict[str, str]) -> Dict[str, Any]:
        j = zc_match.get(id(r))
        return infos[j] if j is not None else {"p": None, "conflict": False, "fav": None, "lb": None, "adj": None, "L": 0.0, "jcL": None}

    def zc_excluded(r: Dict[str, str]) -> bool:
        h, a = names_for(r)
        return manual.excluded(h, a, r.get("主队"), r.get("客队"))

    sfc = sorted(games.get("sfc", []), key=lambda r: int(num(r.get("序号")) or 0))
    sfc_picks = []
    if sfc:
        meta["sfc_issue"] = sfc[0].get("期号", "")
        dl = sfc[0].get("售彩截止(北京时间)", "")
        meta["sfc_deadline"] = dl
        for r in sfc:
            seq = str(int(num(r.get("序号")) or 0))
            h, a = names_for(r)
            info = zc_info(r)
            opts = sfc_options(info, zc_excluded(r))
            if seq in manual.sfc_overrides:
                opts = [o for o in manual.sfc_overrides[seq].replace("，", "/").replace(",", "/").split("/") if o in "310"]
                opts = [o for o in "310" if o in opts] or opts
            zh = [{"3": "胜", "1": "平", "0": "负"}[o] for o in opts]
            pk_ = mkp(day, "胜负彩", "胜负彩", f"{r.get('期号')}-{seq}", h, a, zh, "/".join(opts),
                      issue=r.get("期号"), seq=seq, fav=info["fav"], adj=info["adj"], single=len(opts) == 1,
                      excl=zc_excluded(r) or info["conflict"] or info["adj"] is None, kick=r.get("开赛时间(北京时间)", ""))
            if not pk_["excl"]:
                comp_pick(pk_, info, "plain")                            # 综合概率只用来给任九排序（单选/双选/全包的标准不变）
            sfc_picks.append(pk_)
        picks += sfc_picks
        ranked = [p for p in sfc_picks if not p["excl"] and p["fav"]]
        ranked.sort(key=lambda p: (p.get("cmp_v") != "support", -(p["cp"] if p.get("cp") is not None else p["adj"]), int(p["seq"])))   # 有数据支持的优先进任九，再按综合概率
        top9 = sorted(ranked[:9], key=lambda p: int(p["seq"]))
        if len(top9) == 9 and not SHOW_NINE:
            meta.setdefault("zc_off", []).insert(0, "任九")
        elif len(top9) == 9:
            for p in top9:
                p["nine"] = "胜" if p["fav"] == "3" else "负"
            combo = {"id": f"{day}|任九|任九|{sfc[0].get('期号')}", "date": day, "play": "任九", "market": "任九", "key": sfc[0].get("期号", ""),
                     "label": "任九单选9场", "legs": [], "status": "pending", "result": "", "issue": sfc[0].get("期号"),
                     "nine": [{"seq": p["seq"], "pick": p["nine"], "label": "3" if p["fav"] == "3" else "0"} for p in top9]}
            picks.append(combo)

    jq4 = sorted(games.get("jq4", []), key=lambda r: int(num(r.get("序号")) or 0))
    for r in jq4:
        meta["jq4_issue"] = r.get("期号", "")
        seq = str(int(num(r.get("序号")) or 0))
        h, a = names_for(r)
        info = zc_info(r)
        ph, pa = goals_template(info, zc_excluded(r))
        picks.append(mkp(day, "4场进球", "4场进球", f"{r.get('期号')}-{seq}", h, a, [], f"{'/'.join(ph)} : {'/'.join(pa)}".replace("/", ","),
                             issue=r.get("期号"), seq=seq, pick_home=ph, pick_away=pa, kick=r.get("开赛时间(北京时间)", "")))

    zc6 = sorted(games.get("zc6", []), key=lambda r: int(num(r.get("序号")) or 0))
    for r in zc6:
        meta["zc6_issue"] = r.get("期号", "")
        seq = str(int(num(r.get("序号")) or 0))
        h, a = names_for(r)
        vals = htft_template(zc_info(r), zc_excluded(r), manual.lean(h, a, r.get("主队"), r.get("客队")))
        picks.append(mkp(day, "6场半全场", "6场半全场", f"{r.get('期号')}-{seq}", h, a, vals, "/".join(vals),
                             issue=r.get("期号"), seq=seq, kick=r.get("开赛时间(北京时间)", "")))

    # —— 手动加的推荐 ——
    for ex in manual.extra_picks:
        p = build_extra(ex, day, jc, bd, jl_rows)
        if p:
            picks.append(p)
        else:
            warnings.append(f"extra_picks 找不到对应场次，已忽略：{ex}")

    # —— 两队数据对比的汇总提示（只在用了对比数据时出现）——
    if manual.has_notes():
        pairs = [("竞足", c.get("主队", "") + (jc_names(jc2bd[i])[0] if i in jc2bd else ""),
                  c.get("客队", "") + (jc_names(jc2bd[i])[1] if i in jc2bd else "")) for i, c in enumerate(jc)] \
            + [("北单", r.get("主队"), r.get("客队")) for r in bd] \
            + [("竞篮", r.get("主队"), r.get("客队")) for r in jl_rows] + [("传统", r.get("主队"), r.get("客队")) for r in zc]
        used = {id(manual.note_for(h, a)) for _, h, a in pairs if manual.note_for(h, a)}
        for nt in (manual.match_notes if manual.notes_on else []) + manual.auto_notes:
            if nt.get("verdict") == "against" and id(nt) in used:
                names = " vs ".join(str(t).split("|")[0] for t in nt.get("teams", []))
                warnings.append(f"两队数据不支持热门方向，已撤掉单关推荐：{names}（{nt.get('why') or nt.get('note')}）")
        if not manual.auto_required and manual.notes_on and manual.require_notes:   # 自动抓取时由 run() 报「哪几场没取到」
            miss: Dict[str, int] = defaultdict(int)
            for kind, h, a in pairs:
                if kind != "传统" and manual.note_for(h, a) is None:
                    miss[kind] += 1
            if miss:
                warnings.append("这些场次没有两队数据对比，按规则不推：" + "、".join(f"{k}{v}场" for k, v in miss.items()))
    for p_ in picks:                                                # 让球分布表只在算综合概率时用，不存进历史（省空间）
        if isinstance(p_.get("mdl"), dict) and "ln" in p_["mdl"]:
            p_["mdl"] = {k: v for k, v in p_["mdl"].items() if k != "ln"}
    return {"picks": picks, "warnings": warnings, "meta": meta}


def info_line(info: Dict[str, Any]) -> float:
    return info.get("L", 0.0)


def game_kind(s: str) -> Optional[str]:
    if "4场" in s or "进球" in s:
        return "jq4"
    if "半全场" in s:
        return "zc6"
    if "胜负" in s or "任选" in s:
        return "sfc"
    return None


def sfc_options(info: Dict[str, Any], excluded: bool) -> List[str]:
    if excluded or info.get("conflict") or not info.get("fav"):
        return ["3", "1", "0"]
    fav, lb, L = info["fav"], info["lb"], info["L"]
    thr = thr_for(L)
    if lb >= thr:
        return [fav]
    if lb >= thr - DOUBLE_MARGIN:
        return [o for o in "310" if o in (fav, "1")]
    return ["3", "1", "0"]


def goals_template(info: Dict[str, Any], excluded: bool) -> Tuple[List[str], List[str]]:
    """4场进球模板（把握最低）：热门强 → 热门 2 球、对手 1 球；热门中等 → 热门 1~2 球；否则双方 1~2 球。"""
    both = (["1", "2"], ["1", "2"])
    if excluded or info.get("conflict") or not info.get("fav") or info.get("adj") is None:
        return both
    strong, mid = info["adj"] >= 0.60, info["adj"] >= 0.50
    fav_goals = ["2"] if strong else ["1", "2"] if mid else None
    if fav_goals is None:
        return both
    dog = ["1"]
    return (fav_goals, dog) if info["fav"] == "3" else (dog, fav_goals)


def htft_template(info: Dict[str, Any], excluded: bool, lean: Optional[str] = None) -> List[str]:
    d = lean or direction_hint(info)
    strong = (not excluded) and (not info.get("conflict")) and info.get("adj") is not None and info["adj"] >= 0.50
    if strong:
        return ["胜胜", "平胜"] if d == "3" else ["负负", "平负"]
    return ["平平", "平胜"] if d == "3" else ["平平", "平负"]


def build_extra(ex: Dict[str, Any], day: str, jc, bd, jl) -> Optional[Dict[str, Any]]:
    play, market, key = ex.get("play"), ex.get("market"), str(ex.get("key", ""))
    pick = [str(x) for x in ex.get("pick", [])]
    note = ex.get("note", "")
    if not pick:
        return None
    if play == "竞足":
        r = next((x for x in jc if x.get("赛事编号") == key), None)
        if r and market in ("胜平负", "让球胜平负", "总进球", "半全场", "比分"):
            return mk_pick(day, "竞足", market, key, r["主队"], r["客队"], pick, f"{market} {'/'.join(pick)}", note=note, extra=True)
    if play == "竞篮":
        r = next((x for x in jl if x.get("赛事编号") == key), None)
        if r and market in ("胜负", "胜分差"):
            return mk_pick(day, "竞篮", market, key, r["主队"], r["客队"], pick, f"{market} {'/'.join(pick)}", note=note, extra=True)
    if play == "北单":
        r = next((x for x in bd if x.get("场次") == key), None)
        if r:
            return mk_pick(day, "北单", "让球胜平负", f"{r['期号']}-{r['场次']}", r["主队"], r["客队"], pick, f"让球{'/'.join(pick)}",
                           no=r["场次"], issue=r["期号"], line=r.get("让球", ""), note=note, extra=True)
    return None


# ════════════════════════════════════════════════════════════════════════════
# 7. 结算：用「昨日已开奖」判定历史推单
# ════════════════════════════════════════════════════════════════════════════
def build_results(wb: Dict[str, List[Dict[str, str]]]) -> Dict[str, Dict[Any, Dict[str, str]]]:
    res: Dict[str, Dict[Any, Dict[str, str]]] = {"竞足": {}, "竞篮": {}, "北单": {}, "传统": {}}
    for r in wb.get("竞足-昨日已开奖", []):
        res["竞足"][(r.get("销售日"), r.get("赛事编号"))] = r
    for r in wb.get("竞篮-昨日已开奖", []):
        res["竞篮"][(r.get("销售日"), r.get("赛事编号"))] = r
    for r in wb.get("北单-昨日已开奖", []):
        res["北单"][(r.get("期号"), r.get("场次"))] = r
    for r in wb.get("传统足彩-已开奖", []):
        g = game_kind(r.get("玩法", ""))
        if g:
            res["传统"][(g, r.get("期号"), str(int(num(r.get("序号")) or 0)))] = r
    return res


def parse_score(s: str) -> Optional[Tuple[int, int]]:
    m = re.match(r"\s*(\d+)\s*[:：-]\s*(\d+)\s*$", s or "")
    return (int(m.group(1)), int(m.group(2))) if m else None


def judge(p: Dict[str, Any], res: Dict[str, Dict[Any, Dict[str, str]]]) -> Optional[Tuple[str, str]]:
    """返回 (hit|miss, 结果说明)；结果还没出返回 None。"""
    play, market = p["play"], p["market"]
    if play == "竞足":
        r = res["竞足"].get((p["date"], p["key"]))
        if not r:
            return None
        val = {"胜平负": r.get("胜平负"), "让球胜平负": r.get("让球胜平负"), "总进球": r.get("总进球"),
               "半全场": r.get("半全场"), "比分": r.get("全场比分")}.get(market)
        if val is None or val == "":
            return None
        return ("hit" if val in p["pick"] else "miss", f"{r.get('全场比分')} {market}{val}")
    if play == "竞篮":
        r = res["竞篮"].get((p["date"], p["key"]))
        sc = parse_score(r.get("终场比分(客:主)", "")) if r else None
        if not sc:
            return None
        a, h = sc
        won = "主胜" if h > a else "主负"
        if market == "胜负":
            return ("hit" if won in p["pick"] else "miss", f"{a}:{h} {won}")
        m = abs(h - a)
        b = next(((lo, hi) for lo, hi in BUCKETS if lo <= m <= hi), (26, 999))
        val = won + (f"{b[0]}-{b[1]}" if b[1] < 999 else f"{b[0]}+")
        return ("hit" if val in p["pick"] else "miss", f"{a}:{h} {val}")
    if play == "北单":
        r = res["北单"].get((p.get("issue"), p.get("no")))
        sc = parse_score(r.get("比分", "")) if r else None
        if not sc:
            return None
        h, a = sc
        d = h + line_of(r.get("让球")) - a
        val = "胜" if d > 0 else "平" if d == 0 else "负"
        return ("hit" if val in p["pick"] else "miss", f"{h}:{a} 让球{val}")
    if play in ("胜负彩", "4场进球", "6场半全场"):
        g = {"胜负彩": "sfc", "4场进球": "jq4", "6场半全场": "zc6"}[play]
        r = res["传统"].get((g, p.get("issue"), p.get("seq")))
        if not r:
            return None
        raw = r.get("彩果", "")
        if g == "jq4":
            sc = parse_score(raw)
            if not sc:
                return None
            cat = lambda x: str(min(x, 3))
            ok = cat(sc[0]) in p["pick_home"] and cat(sc[1]) in p["pick_away"]
            return ("hit" if ok else "miss", raw)
        return ("hit" if raw in p["pick"] else "miss", raw)
    return None


def _close(p: Dict[str, Any], status: str, result: str, today: str) -> None:
    """推单出结果：写状态、说明，并记下是哪天结算的（复盘帖里「补结算」靠它）。"""
    p["status"], p["result"], p["settled_at"] = status, result, today


def settle(hist: Dict[str, Any], wb: Dict[str, List[Dict[str, str]]], today: str) -> int:
    res = build_results(wb)
    picks: Dict[str, Dict[str, Any]] = hist["picks"]
    changed = 0
    for p in picks.values():
        if p["status"] == "pending" and "legs" not in p:
            out = judge(p, res)
            if out:
                _close(p, out[0], out[1], today)
                changed += 1
    changed += _settle_combos(hist, res, today)
    cutoff = (datetime.strptime(today, "%Y-%m-%d") - timedelta(days=EXPIRE_DAYS)).strftime("%Y-%m-%d")
    for p in picks.values():
        if p["status"] == "pending" and p["date"] < cutoff:
            _close(p, "void", "超期无结果", today)
    return changed


def _settle_combos(hist: Dict[str, Any], res: Dict[str, Dict[Any, Dict[str, str]]], today: str) -> int:
    """串关/任九：腿都出结果了才结算。"""
    picks: Dict[str, Dict[str, Any]] = hist["picks"]
    changed = 0
    for p in picks.values():
        if p["status"] != "pending" or "legs" not in p:
            continue
        if p["play"] == "任九":
            legs = [picks.get(f"{p['date']}|胜负彩|胜负彩|{p['issue']}-{x['seq']}") for x in p["nine"]]
            ok = []
            for x, leg in zip(p["nine"], legs):
                if not leg or leg["status"] == "pending":
                    ok.append(None)
                elif leg["status"] == "void":
                    ok.append(None)
                else:
                    r = res["传统"].get(("sfc", p["issue"], x["seq"]))
                    raw = r.get("彩果") if r else leg.get("raw")          # 官方彩果优先；官方还没出时用赛果库算出的
                    ok.append((raw == x["pick"]) if raw else None)
            if None in ok:
                continue
            _close(p, "hit" if all(ok) else "miss", f"{sum(ok)}/9", today)
            changed += 1
            continue
        legs = [picks.get(i) for i in p["legs"]]
        sts = [l["status"] if l else "void" for l in legs]
        if "void" in sts:
            _close(p, "void", "有场次作废", today)
        elif "miss" in sts:
            _close(p, "miss", f"{sts.count('hit')}/{len(sts)}", today)
        elif all(s == "hit" for s in sts):
            _close(p, "hit", f"{len(sts)}/{len(sts)}", today)
        else:
            continue
        changed += 1
    return changed


LOCAL_PLAYS = ("竞足", "北单", "胜负彩", "4场进球")      # 能只靠全场比分算出结果的玩法（半全场要半场比分、竞篮要篮球比分，赛果库里没有）


LOCAL_KICK_MIN = 10          # 找本地比分时，开球时间最多差几分钟（竞彩和完场页的开球时间是同一个来源，应该一模一样）


def _local_match(db: Any, p: Dict[str, Any]) -> Tuple[Optional[Dict[str, Any]], str, List[Dict[str, Any]], List[Tuple[str, str]]]:
    """在自己的赛果库里找这场比赛的完场比分。返回 (比分行或None, 原因, 同一开球时间的其他比赛, 可以学的队名对应[(竞彩叫法, 完场页叫法)])。
    三层，一层比一层松：
      a 两队名（认别名）都对得上，开球时间前后 14 小时内，只有一条；
      b 开球时间前后 10 分钟内，主队或客队有一边（认别名）一样，另一边就是对手——只有一条才算；
      c 开球时间前后 10 分钟内，两边名字都有点像（两边相似度合计 ≥1.2、每边 ≥0.4），而且比第二名明显更像。
    青年队/女足/U21 这类标记两边不一致的不算。b、c 找到的，另一边的叫法会记成别名（以后直接用 a）。
    原因：ok / nokick（推单没有开球时间）/ none（库里这个时间没有比赛）/ names（有同一时间的比赛但队名对不上）/ ambiguous（对上不止一条）。"""
    kick = parse_dt(p.get("kick") or "")
    if kick is None or not p.get("home") or not p.get("away"):
        return None, "nokick", [], []
    names = db.names
    ch, ca = names.canon(p["home"]), names.canon(p["away"])
    rows = db.rows_by_day(kick.strftime("%Y-%m-%d"))
    near: List[Dict[str, Any]] = []
    hits: List[Dict[str, Any]] = []
    for r in rows:
        rk = parse_dt(r["k"])
        if rk is None:
            continue
        gap = abs((rk - kick).total_seconds())
        if gap <= LOCAL_KICK_MIN * 60:
            near.append(r)
        if gap <= 14 * 3600 and names.canon(r["h"]) == ch and names.canon(r["a"]) == ca:
            hits.append(r)
    if len(hits) == 1:
        return hits[0], "ok", near, []
    if len(hits) > 1:
        return None, "ambiguous", near, []
    import sina_data as SD
    cand = [r for r in near if SD.marks_ok(p["home"], r["h"]) and SD.marks_ok(p["away"], r["a"])]
    one = [r for r in cand if names.canon(r["h"]) == ch or names.canon(r["a"]) == ca]
    if len(one) == 1:
        r = one[0]
        pairs = [(ours, theirs) for ours, theirs in ((p["home"], r["h"]), (p["away"], r["a"]))
                 if names.canon(ours) != names.canon(theirs) and SD.name_sim(ours, theirs) >= 0.25]
        return r, "ok", near, pairs
    if len(one) > 1:
        return None, "ambiguous", near, []
    scored = sorted(((SD.name_sim(p["home"], r["h"]) + SD.name_sim(p["away"], r["a"]), SD.name_sim(p["home"], r["h"]), SD.name_sim(p["away"], r["a"]), r)
                     for r in cand), key=lambda x: -x[0])
    if scored and scored[0][0] >= 1.2 and min(scored[0][1], scored[0][2]) >= 0.4 and (len(scored) == 1 or scored[0][0] - scored[1][0] >= 0.25):
        r = scored[0][3]
        return r, "ok", near, [(ours, theirs) for ours, theirs in ((p["home"], r["h"]), (p["away"], r["a"])) if names.canon(ours) != names.canon(theirs)]
    return None, ("names" if near else "none"), near, []


def _local_find(db: Any, p: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """只要比分行（看 _local_match）。"""
    return _local_match(db, p)[0]


def judge_local(p: Dict[str, Any], hs: int, as_: int) -> Optional[Tuple[str, str]]:
    """用全场比分算结果（和官方赛果页同一口径：90 分钟含伤停补时）。算不了返回 None。"""
    play, market = p["play"], p.get("market")
    sc = f"{hs}:{as_}"
    if play == "北单":
        d = hs + line_of(p.get("line")) - as_
        val = "胜" if d > 0 else "平" if d == 0 else "负"
        return ("hit" if val in p["pick"] else "miss", f"{sc} 让球{val}（赛果库）")
    if play == "竞足" and market in ("胜平负", "让球胜平负"):
        d = hs - as_ + (line_of(p.get("line")) if market == "让球胜平负" else 0)
        val = "胜" if d > 0 else "平" if d == 0 else "负"
        return ("hit" if val in p["pick"] else "miss", f"{sc} {market}{val}（赛果库）")
    if play == "胜负彩":
        raw = "胜" if hs > as_ else "平" if hs == as_ else "负"          # 和官方「彩果」同一写法
        p["raw"] = raw
        return ("hit" if raw in p["pick"] else "miss", f"{raw}（{sc}，赛果库）")
    if play == "4场进球":
        cat = lambda x: str(min(x, 3))
        ok = cat(hs) in p["pick_home"] and cat(as_) in p["pick_away"]
        return ("hit" if ok else "miss", f"{sc}（赛果库）")
    return None


def settle_local(hist: Dict[str, Any], wb: Dict[str, List[Dict[str, str]]], today: str, folder: Path, say: Optional[Callable[[str], None]] = None,
                 now: Optional[datetime] = None) -> int:
    """官方赛果页还没出结果的推单，用自己赛果库（results_db.json，每次更新从 500 完场页攒的）里已有的完场比分直接结算。
    只处理 LOCAL_PLAYS；找比赛的办法看 _local_match（队名要对得上且只有一条才算）；说明里标「赛果库」。
    之后官方结果出来也不会改（已经结算的不动）。没结算的写清原因（库里没这场/有这场但队名对不上）。返回结算条数。"""
    try:
        import sina_data as SD
        db = SD.ResultsDB(Path(folder))
    except Exception:  # noqa: BLE001 —— 赛果库只是加分项
        return 0
    if not db.rows:
        return 0
    now = now or datetime.now(timezone(timedelta(hours=8))).replace(tzinfo=None)
    n = 0
    pairs: List[Tuple[str, str]] = []
    miss: List[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]] = []
    for p in hist["picks"].values():
        if p["status"] != "pending" or "legs" in p or p.get("play") not in LOCAL_PLAYS:
            continue
        try:
            r, why, near, pr = _local_match(db, p)
            out = judge_local(p, r["hs"], r["as"]) if r else None
        except Exception:  # noqa: BLE001
            r, why, near, pr, out = None, "none", [], [], None
        if out:
            _close(p, out[0], out[1], today)
            pairs += pr
            n += 1
        else:
            miss.append((p, why, near))
    learned = 0
    if pairs:
        try:
            learned = db.names.learn(pairs)
        except Exception:  # noqa: BLE001
            learned = 0
    if n:
        n += _settle_combos(hist, build_results(wb), today)
    if say:
        if n:
            say(f"官方赛果页还没出结果的推单，用自己赛果库里的完场比分结算了 {n} 条（说明里标了「赛果库」）"
                + (f"；顺便对上了 {learned} 个队名，以后直接认" if learned else ""))
        say_miss(miss, now, say)
    return n


def say_miss(miss: List[Tuple[Dict[str, Any], str, List[Dict[str, Any]]]], now: datetime, say: Callable[[str], None]) -> None:
    """没能用赛果库结算的推单：是比赛还没踢完/库里还没有，还是库里有同一时间的比赛但队名对不上。"""
    if not miss:
        return
    early, noname, others = [], [], []
    for p, why, near in miss:
        k = parse_dt(p.get("kick") or "")
        if why == "none" and k is not None and k + timedelta(hours=3) > now:
            early.append(p)                                  # 比赛才开始不久/还没开始：正常等
        elif why == "names":
            noname.append((p, near))
        else:
            others.append((p, why))
    parts = []
    if early:
        parts.append(f"{len(early)} 条比赛还没踢完")
    if others:
        parts.append(f"{len(others)} 条库里还没有这场的完场比分（完场页没更新或没收）")
    if noname:
        parts.append(f"{len(noname)} 条库里有同一开球时间的比赛，但队名对不上")
    say("本地结算没找到比分的推单：" + "；".join(parts))
    for p, near in noname[:4]:
        lst = "、".join(f"{r['h']}vs{r['a']}" for r in near[:3])
        say(f"    {p.get('play')} {p.get('home')}vs{p.get('away')}（{(p.get('kick') or '')[5:]}）：库里同时间有 {lst}")


def tally(hist: Dict[str, Any], dates: List[str]) -> Dict[str, Tuple[int, int, int]]:
    """{玩法: (命中, 已判定总数, 待结果数)}"""
    t: Dict[str, List[int]] = defaultdict(lambda: [0, 0, 0])
    for p in hist["picks"].values():
        if p["date"] not in dates:
            continue
        if p["status"] == "hit":
            t[p["play"]][0] += 1; t[p["play"]][1] += 1
        elif p["status"] == "miss":
            t[p["play"]][1] += 1
        elif p["status"] == "pending":
            t[p["play"]][2] += 1
    return {k: (v[0], v[1], v[2]) for k, v in t.items()}


def tally_text(t: Dict[str, Tuple[int, int, int]], pct: bool = False) -> str:
    parts = []
    for play in PLAY_ORDER:
        if play in t and t[play][1] > 0:
            h, n, _ = t[play]
            parts.append(f"{play}{h}/{n}" + (f"({h / n:.0%})" if pct else ""))
    return " ".join(parts)


# ——— 数据把关的「自我检验」：被两队数据撤掉的、没数据没推的，其实赛果怎样？（影子记账：只记账，不发帖）———
SINGLE_PLAYS = ("竞足", "北单", "竞篮")
FILTER_MIN = 6             # 已出结果的样本合计少于这么多条，不显示把关效果（太少说明不了什么）


def shadow_picks(wb: Dict[str, List[Dict[str, str]]], day: str, manual: "Manual", final: List[Dict[str, Any]], market: Any = None) -> List[Dict[str, Any]]:
    """没有两队数据把关时本来会推、现在没推的单场推荐：原因 against（数据反对，撤了）或 nodata（没取到数据，不推）。"""
    import copy
    m0 = copy.copy(manual)
    m0.match_notes, m0.require_notes, m0.auto_notes, m0.auto_required = [], False, [], False
    keep = {p["id"] for p in final}
    out: List[Dict[str, Any]] = []
    for p in generate(wb, day, m0, market=market)["picks"]:
        if "legs" in p or p["id"] in keep or p["play"] not in SINGLE_PLAYS:
            continue
        nt = manual.note_for(p.get("home"), p.get("away"))
        why = "nodata" if nt is None else "against" if nt.get("verdict") == "against" else ""
        if why:
            out.append(dict(p, why=why))
    return out


GATE_LOOSE = {"JC_MIN_WIN": 0.0, "JC_HCP_MIN": 0.50, "NEED_SUPPORT": 0, "BD_MIN_P": 0.55}     # 以前的宽松标准（单场的部分）


def use_legacy_rules() -> None:
    """回到 v2.2 及更早的宽松标准（测试和对比用）。日常想回到旧标准，改 rules.json 里对应项就行。"""
    RULE_DEFAULTS.update(LEGACY_RULES)
    globals().update(LEGACY_RULES)


def gates_active() -> bool:
    """现在的单场标准比以前的宽松标准更严吗（是的话才需要记「被挡下的」）。"""
    return any(globals()[k] > v + 1e-9 for k, v in GATE_LOOSE.items())


def gate_shadow(wb: Dict[str, List[Dict[str, str]]], day: str, manual: "Manual", final: List[Dict[str, Any]], market: Any = None) -> List[Dict[str, Any]]:
    """按以前的宽松标准、同样的两队数据再生成一遍：多出来的单场就是「被精选门槛挡下」的。只记账，不发帖——以后对赛果，检验挡下的是不是真的更容易不中。"""
    g = globals()
    saved = {k: g[k] for k in GATE_LOOSE}
    try:
        for k, v in GATE_LOOSE.items():
            g[k] = min(saved[k], v) if k != "NEED_SUPPORT" else 0
        loose = generate(wb, day, manual, market=market)["picks"]
    finally:
        g.update(saved)
    keep = {p["id"] for p in final}
    return [dict(p, why="gate") for p in loose if "legs" not in p and p.get("play") in SINGLE_PLAYS and p["id"] not in keep]


def settle_shadow(hist: Dict[str, Any], wb: Dict[str, List[Dict[str, str]]], today: str) -> int:
    sh = hist.get("shadow") or {}
    if not sh:
        return 0
    res = build_results(wb)
    n = 0
    for p in sh.values():
        if p.get("status") == "pending":
            out = judge(p, res)
            if out:
                _close(p, out[0], out[1], today)
                n += 1
    cutoff = _shift(today, -EXPIRE_DAYS)
    for p in sh.values():
        if p.get("status") == "pending" and p["date"] < cutoff:
            _close(p, "void", "超期无结果", today)
    return n


def filter_stats(hist: Dict[str, Any]) -> Tuple[Dict[str, Tuple[int, int]], str]:
    """数据把关效果：{类别: (命中, 已出结果)} 和一句话。类别：support 数据支持（推了）｜mixed 部分支持（推了）｜
    against 数据反对（撤了，假如没撤）｜nodata 没取到数据（没推，假如推了）。样本不够返回空文字。"""
    t: Dict[str, List[int]] = {k: [0, 0] for k in ("support", "mixed", "against", "nodata", "gate")}
    for p in hist["picks"].values():
        if "legs" in p or p.get("play") not in SINGLE_PLAYS or p.get("status") not in ("hit", "miss"):
            continue
        if p.get("cmp_v") in ("support", "mixed"):
            t[p["cmp_v"]][1] += 1
            t[p["cmp_v"]][0] += p["status"] == "hit"
    for p in (hist.get("shadow") or {}).values():
        if p.get("status") in ("hit", "miss") and p.get("why") in ("against", "nodata", "gate"):
            t[p["why"]][1] += 1
            t[p["why"]][0] += p["status"] == "hit"
    stats = {k: (v[0], v[1]) for k, v in t.items()}
    if sum(n for _, n in stats.values()) < FILTER_MIN:
        return stats, ""
    names = {"support": "数据支持的", "mixed": "部分支持的", "against": "被数据撤掉的（假如没撤）", "nodata": "没数据没推的（假如推了）",
             "gate": "被精选门槛挡下的（假如推了）"}
    parts = [f"{names[k]} {h}/{n}（{h / n:.0%}）" for k, (h, n) in stats.items() if n]
    return stats, "两队数据把关效果（累计，单场推荐）：" + "｜".join(parts) + "。样本还小，只作参考；撤掉/挡下的命中率明显低，才说明把关有用。"


# ════════════════════════════════════════════════════════════════════════════
# 8. 昨日赛果一句话
# ════════════════════════════════════════════════════════════════════════════
def facts_jz(wb: Dict[str, List[Dict[str, str]]]) -> str:
    jz = [r for r in wb.get("竞足-昨日已开奖", []) if parse_score(r.get("全场比分", ""))]
    if not jz:
        return ""
    c = Counter(r.get("胜平负") for r in jz)
    seg = f"竞足{len(jz)}场主胜{c['胜']}、客胜{c['负']}、平{c['平']}"
    hot = sum(1 for r in jz if (num(r.get("胜平负奖金")) or 99) < 2)
    cold = sorted([r for r in jz if (num(r.get("胜平负奖金")) or 0) >= 2.5], key=lambda r: -num(r["胜平负奖金"]))
    if hot:
        seg += f"，低赔热门（赔率<2）打出{hot}场"
    if cold:
        ex = "、".join(f"{r['主队']}{r['胜平负']}{r['客队']}" for r in cold[:3])
        seg += f"，另有{len(cold)}场赔率2.5以上的冷门（{ex}）"
    by: Dict[str, List[int]] = defaultdict(list)
    for r in jz:
        h, a = parse_score(r["全场比分"])
        by[r.get("联赛", "")].append(h + a)
    best = max(((lg, sum(v) / len(v), len(v)) for lg, v in by.items() if len(v) >= 3), key=lambda x: x[1], default=None)
    if best and best[1] >= 3.5:
        seg += f"，{best[0]}{best[2]}场场均{best[1]:.1f}球"
    return seg


def facts_bd(wb: Dict[str, List[Dict[str, str]]]) -> str:
    bd = [r for r in wb.get("北单-昨日已开奖", []) if parse_score(r.get("比分", ""))]
    if not bd:
        return ""
    c: Counter = Counter()
    for r in bd:
        h, a = parse_score(r["比分"])
        d = h + line_of(r.get("让球")) - a
        c["胜" if d > 0 else "平" if d == 0 else "负"] += 1
    return f"北单{len(bd)}场让球胜{c['胜']}/平{c['平']}/负{c['负']}"


def facts_jl(wb: Dict[str, List[Dict[str, str]]]) -> str:
    jl = [r for r in wb.get("竞篮-昨日已开奖", []) if parse_score(r.get("终场比分(客:主)", ""))]
    if not jl:
        return ""
    cover = big = 0
    for r in jl:
        a, h = parse_score(r["终场比分(客:主)"])
        cover += h + line_of(r.get("让分")) - a > 0
        tot = num(r.get("预设总分"))
        big += tot is not None and h + a > tot
    return f"竞篮{len(jl)}场主队过盘{cover}场、{big}场开大分"


def facts_zc(wb: Dict[str, List[Dict[str, str]]], game: str) -> str:
    """传统足彩最近一期的开奖（表里要有「传统足彩-已开奖」：抓取时带 --keep-older-draws，操作台默认就带）。"""
    rows = sorted([r for r in wb.get("传统足彩-已开奖", []) if game_kind(r.get("玩法", "")) == game],
                  key=lambda r: int(num(r.get("序号")) or 0))
    if not rows:
        return ""
    issue, dd = rows[0].get("期号", ""), rows[0].get("开奖日期", "")
    when = f"（{md(dd)}开奖）" if re.match(r"\d{4}-\d{2}-\d{2}$", dd or "") else ""
    res = [r.get("彩果", "") for r in rows]
    if game == "sfc":
        c = Counter(res)
        return f"胜负彩第{issue}期{when}：{c['胜']}胜{c['平']}平{c['负']}负"
    name = "4场进球" if game == "jq4" else "6场半全场"
    return f"{name}第{issue}期{when}：" + " ".join(f"{'①②③④⑤⑥⑦⑧⑨⑩⑪⑫⑬⑭'[min(i, 14) - 1]}{x}" for i, x in enumerate(res, 1))


def results_sentence(wb: Dict[str, List[Dict[str, str]]]) -> str:
    """窗口里「昨日赛果概况」那一句（竞足+北单+竞篮）。"""
    parts = [x for x in (facts_jz(wb), facts_bd(wb), facts_jl(wb)) if x]
    return "；".join(parts) + "。" if parts else "昨日暂无可复盘的赛果。"


# ════════════════════════════════════════════════════════════════════════════
# 8b. 昨日推单逐条复盘（把「昨天发出去的推单」一条一条对上赛果，输了也如实列出）
# ════════════════════════════════════════════════════════════════════════════
def md(day: str) -> str:
    d = datetime.strptime(day, "%Y-%m-%d")
    return f"{d.month}月{d.day}日"


def _nat(s: Any) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


def _shift(day: str, n: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


def review_scope(hist: Dict[str, Any], day: str) -> Tuple[Optional[str], List[Dict[str, Any]]]:
    """复盘哪些推单 → (复盘日, 推单列表)。
    复盘日 = 今天之前、最近一个有「已出结果」推单的日子，当天的推单全列（没出结果的标 ⏳）；
    另外加上更早日子里「今天刚出结果」的推单（比如传统足彩要隔几天才开奖），归入「补结算」。作废的不列。"""
    picks = hist["picks"]
    done_days = sorted({p["date"] for p in picks.values() if p["date"] < day and p["status"] in ("hit", "miss")})
    rd = done_days[-1] if done_days else None
    items = [p for p in picks.values()
             if p["date"] < day and p["status"] != "void"
             and (p["date"] == rd or (p.get("settled_at") == day and p["status"] in ("hit", "miss")))]
    order = {n: i for i, n in enumerate(PLAY_ORDER)}
    items.sort(key=lambda p: (p["date"], order.get(p["play"], 99), _nat(describe_pick(p, picks)[1]), p.get("market", "")))
    return rd, items


REVIEW_FAMILIES = [("竞足", "竞足", "竞足串关"), ("北单", "北单", "北单串关"), ("竞篮", "竞篮", "竞篮串关"),
                   ("胜负彩", "胜负彩", "任九"), ("4场进球", "4场进球", None), ("6场半全场", "6场半全场", None)]
REVIEW_LINE_W = 200        # 复盘帖里一行最多的字数权重（一行写不下就换行，免得单行超过 280）


def _icon(p: Dict[str, Any]) -> str:
    return {"hit": "✅", "miss": "❌", "pending": "⏳"}.get(p["status"], "•")


def _sid(p: Dict[str, Any]) -> str:
    """场次的短写：周四002 → 002；北单 93；传统足彩 序号。"""
    if p.get("no"):
        return str(p["no"])
    if p.get("seq"):
        return str(p["seq"])
    m = re.search(r"\d+$", str(p.get("key", "")))
    return m.group() if m else str(p.get("key", ""))


def _short_result(p: Dict[str, Any]) -> str:
    r = p.get("result") or ""
    if p["play"] == "竞篮":
        return r.split(" ", 1)[1] if " " in r else r
    if p["play"] in ("竞足", "北单"):
        return r.split(" ", 1)[0]
    return r


def _token(p: Dict[str, Any]) -> str:
    """一条推单的短写：✅002托林斯负(0:3)。结果没出的写 ⏳。"""
    lab = p["label"] if p.get("market") in ("胜平负", "胜负", "让球胜平负") else f"{p.get('market', '')}{p['label']}"
    res = _short_result(p) if p["status"] in ("hit", "miss") else ""
    if res == lab:                                  # 竞篮「主胜(主胜)」这种重复不写
        res = ""
    return f"{_icon(p)}{_sid(p)}{p.get('home', '')}{lab}" + (f"({res})" if res else "")


def _wrap(tokens: List[str], max_w: int = REVIEW_LINE_W) -> List[str]:
    lines: List[str] = []
    cur = ""
    for t in tokens:
        if cur and weight(cur + " " + t) > max_w:
            lines.append(cur)
            cur = t
        else:
            cur = (cur + " " + t) if cur else t
    if cur:
        lines.append(cur)
    return lines


def _record_lines(rows: List[Dict[str, Any]], fam: str, single: str, combo: Optional[str], when: str) -> List[str]:
    """某个玩法「我们推过的单」的对账行：📋昨日竞足推单 4/8（50%）＋逐条（命中和未中都列）。"""
    ones = [p for p in rows if p["play"] == single]
    combos = [p for p in rows if combo and p["play"] == combo]
    if not ones and not combos:
        return []
    h, n = sum(p["status"] == "hit" for p in ones), sum(p["status"] in ("hit", "miss") for p in ones)
    out = [f"📋{when}{fam}推单 {h}/{n}（{h / n:.0%}）" if n else f"📋{when}{fam}推单（结果未出）"]
    if single in DAILY_PLAYS:                      # 竞足/北单/竞篮：每场都列（命中和未中），这是门面
        out += _wrap([_token(p) for p in ones])
    elif ones:                                      # 传统足彩 14 场太长：全中就一句话，否则只列没中的（带实际彩果）
        miss = [p for p in ones if p["status"] == "miss"]
        wait = [p for p in ones if p["status"] == "pending"]
        if miss:
            out += _wrap([f"❌{_sid(p)}({_short_result(p)})" for p in miss])
        elif not wait:
            out.append("全部命中🎯")
        if wait:
            out.append("⏳结果未出：" + " ".join(_sid(p) for p in wait))
    if combos:
        parts = []
        for p in combos:
            label = "任九" if p["play"] == "任九" else p["label"]
            parts.append(f"{_icon(p)}{label}" + (f"({p['result']})" if p.get("result") else ""))
        out.append("🎯串关 " + " ".join(parts) if combo != "任九" else "🎯" + " ".join(parts))
    return out


FACTS = {"竞足": facts_jz, "北单": facts_bd, "竞篮": facts_jl,
         "胜负彩": lambda wb: facts_zc(wb, "sfc"), "4场进球": lambda wb: facts_zc(wb, "jq4"), "6场半全场": lambda wb: facts_zc(wb, "zc6")}


def review_section(fams: List[str], wb: Dict[str, List[Dict[str, str]]], hist: Dict[str, Any], day: str) -> List[str]:
    """每种玩法文章里的「📊昨日复盘」：①昨日赛果概况 ②我们昨天推的单逐条对账（命中和未中都列）③之前漏结算、今天才出结果的单。
    两样都没有（比如第一天）就写一句，不留空。"""
    rd, items = review_scope(hist, day)
    when = "昨日" if rd == _shift(day, -1) else (md(rd) if rd else "昨日")
    lines: List[str] = ["📊昨日复盘"]
    for fam in fams:
        fact = FACTS[fam](wb)
        if fact:
            lines.append(fact)
    got = False
    for fam, single, combo in REVIEW_FAMILIES:
        if fam not in fams:
            continue
        main = [p for p in items if p["date"] == rd]
        rec = _record_lines(main, fam, single, combo, when)
        late = [p for p in items if p["date"] != rd]
        for d in sorted({p["date"] for p in late}):
            rec += _record_lines([p for p in late if p["date"] == d], fam, single, combo, f"{md(d)}补结算·")
        if rec:
            got = True
            lines += rec
    if len(lines) == 1:
        lines.append("今天起开始记录，明天起逐条对账本篇推单")
    elif not got and rd is None:
        pass                                         # 有赛果概况就够了；还没有我们的推单可对账
    return lines


def gap_dates(hist: Dict[str, Any], day: str) -> List[str]:
    """哪些销售日的推单该补抓赛果：它们还有竞足/竞篮/北单单场没出结果，而「今日」这张表只带昨日赛果，够不着。
    只看还没超期（EXPIRE_DAYS 天内）的；今天表里的「昨日」不算（已经用过了）。"""
    lo, hi = _shift(day, -EXPIRE_DAYS), _shift(day, -1)
    return sorted({p["date"] for p in hist["picks"].values()
                   if p["status"] == "pending" and "legs" not in p and p["play"] in DAILY_PLAYS and lo <= p["date"] < hi})


def _pending_split(mine: List[Dict[str, Any]]) -> str:
    """没出结果的推单按玩法分一下（串关要等它的每一场都出结果），好看出是哪一类卡住了。"""
    c = Counter(p["play"] for p in mine if p["status"] == "pending")
    return ("没出结果的有：" + "、".join(f"{k} {v} 条" for k, v in sorted(c.items(), key=lambda kv: -kv[1])) + "。") if c else ""


def continuity_notes(hist: Dict[str, Any], day: str, backfilled: List[str], failed: List[str]) -> List[str]:
    """给人看的「衔接情况」：昨天的推单有没有接上、有没有断档。"""
    picks = hist["picks"]
    before = [p for p in picks.values() if p["date"] < day]
    notes: List[str] = []
    if not before:
        return ["这是第一次运行（或历史是空的），还没有昨日推单可复盘。今天的推单已记入历史，明天更新时会自动复盘。"]
    prev = max(p["date"] for p in before)
    gap_days = (datetime.strptime(day, "%Y-%m-%d") - datetime.strptime(prev, "%Y-%m-%d")).days - 1
    if gap_days > 0:
        notes.append(f"上次生成推单是 {md(prev)}，之后有 {gap_days} 天没有推单记录——没生成的日子没有推单，所以没有复盘。")
    mine = [p for p in before if p["date"] == prev]
    pend = sum(p["status"] == "pending" for p in mine)
    done = sum(p["status"] in ("hit", "miss") for p in mine)
    if prev in failed:
        pass                                           # 下面会有「补抓没成功」的警告，这里不重复说
    elif done == 0 and pend:
        notes.append(f"{md(prev)}的 {pend} 条推单结果还都没出（比赛可能没打完，或赛果还没更新），晚点再点一次更新就会接上。" + _pending_split(mine))
    elif pend:
        notes.append(f"{md(prev)}还有 {pend} 条推单没出结果（场次没打完或赛果还没更新），之后更新会自动补上。" + _pending_split(mine))
    if backfilled:
        notes.append("已自动补抓并结算漏掉的日子：" + "、".join(md(d) for d in backfilled) + "。")
    left = Counter(p["date"] for p in picks.values()
                   if p["status"] == "pending" and "legs" not in p and p["play"] in DAILY_PLAYS and p["date"] in set(failed))
    for d in sorted(left):
        notes.append(f"⚠ {md(d)}的 {left[d]} 条推单还没结算：那天之后没有更新过，补抓赛果也没成功。"
                     f"超过 {EXPIRE_DAYS} 天仍无结果会标为作废，不计入命中率。")
    return notes


def prune(hist: Dict[str, Any], day: str) -> None:
    """清理太老的记录，历史文件不会越长越大。"""
    lo_pick, lo_post = _shift(day, -KEEP_PICK_DAYS), _shift(day, -KEEP_POST_DAYS)
    for pid in [i for i, p in hist["picks"].items() if p["date"] < lo_pick and p["status"] != "pending"]:
        del hist["picks"][pid]
    for d in [d for d in (hist.get("odds") or {}) if d < _shift(day, -3)]:
        del hist["odds"][d]
    lo_slim = _shift(day, -SLIM_PICK_DAYS)
    for p in hist["picks"].values():
        if p.get("date", "9") < lo_slim and p.get("status") != "pending":
            p.pop("cmp", None)
    for d, r in hist["runs"].items():
        if d < lo_post:
            r.pop("posts", None)
    for d in [d for d in hist.get("backfilled", {}) if d < lo_pick]:
        del hist["backfilled"][d]
    for pid in [i for i, p in (hist.get("shadow") or {}).items() if p.get("date", "") < lo_pick and p.get("status") != "pending"]:
        del hist["shadow"][pid]


# ════════════════════════════════════════════════════════════════════════════
# 9. 渲染 X 帖子
# ════════════════════════════════════════════════════════════════════════════


CMP_MARK = {"support": "✓", "mixed": "△", "against": "✗"}


def cmp_line(p: Dict[str, Any]) -> str:
    """这场的「两队数据对比」一行（没有对比数据返回空串）。"""
    if not p.get("cmp"):
        return ""
    return f"📈{CMP_MARK.get(p.get('cmp_v') or '', '')}{p['cmp']}"


def cmp_legend(ps: List[Dict[str, Any]]) -> str:
    vs = {p.get("cmp_v") for p in ps if p.get("cmp")}
    if not vs:
        return ""
    names = {"support": "✓数据支持", "mixed": "△部分支持", "against": "✗数据反对，不单选"}
    return "📈两队数据对比（" + " ".join(names[v] for v in ("support", "mixed", "against") if v in vs) + "）"


def render(gen: Dict[str, Any], day: str, wb: Dict[str, List[Dict[str, str]]], hist: Dict[str, Any],
           settled_day: Optional[str], style: str = "clean", brand: Optional[Dict[str, Any]] = None) -> List[Tuple[str, str]]:
    """渲染帖子。style="media"（run 的默认）：自媒体版，带固定栏目风格（见 render_media / brand.json）；
    style="clean"：朴素的可直接发版本——每个玩法只有「标题＋推单＋串关＋提示＋标签」，
    昨日复盘单独成一篇放最后，两队数据对比不进帖子（另存在备查里）；style="full"：每篇都带昨日复盘和每场的两队数据对比。"""
    if style == "media":
        return render_media(gen, day, wb, hist, settled_day, brand or dict(BRAND_DEFAULT))
    clean = style != "full"
    picks = gen["picks"]
    meta = gen["meta"]
    by_play = defaultdict(list)
    for p in picks:
        by_play[p["play"]].append(p)
    pmap = {p["id"]: p for p in picks}
    posts: List[Tuple[str, str]] = []
    rev_fams: List[str] = []                                 # 出了帖子的玩法 → 复盘里要对账的玩法

    def cl(p: Dict[str, Any]) -> str:
        return "" if clean else cmp_line(p)

    def lg(ps: List[Dict[str, Any]]) -> str:
        return "" if clean else cmp_legend(ps)

    def top(title: str, fams: List[str]) -> List[str]:
        rev_fams.extend(fams)
        if clean:
            return [title, ""]
        return [title + "｜昨日复盘＋今日推单", ""] + review_section(fams, wb, hist, day) + ["", "🔥今日推单"]

    def nt(p: Dict[str, Any]) -> str:                        # 括号里的补充说明（干净版不要）
        return "" if clean or not p.get("note") else f"（{p['note']}）"

    def hcp_label(p: Dict[str, Any]) -> str:                 # 让球负 → 让球(+1)负
        lab = str(p["label"])
        ln = f"({p['line']})" if p.get("line") else ""
        return "让球" + ln + lab[2:] if lab.startswith("让球") else lab

    # 竞足：同一场的「胜平负」「让球」放在一行，不再让读的人猜括号里的让球数是给谁的
    jc = [p for p in by_play["竞足"]]
    if jc:
        lines = top(f"⚽【竞足热门推单】{md(day)}", ["竞足"])
        if lg(jc):
            lines.append(lg(jc))
        order: List[str] = []
        for p in jc:
            if p["key"] not in order:
                order.append(p["key"])
        for k in order:                                  # 同一场的几条推荐合成一行，对比只写一次
            grp = [p for p in jc if p["key"] == k]
            segs = []
            for p in grp:
                if p["market"] == "胜平负":
                    segs.append(f"胜平负 {p['label']}")
                elif p["market"] == "让球胜平负":
                    segs.append(hcp_label(p))
                else:
                    segs.append(f"{p['label']}{nt(p)}")
            lines.append(f"{k} {grp[0]['home']}vs{grp[0]['away']}｜" + "｜".join(segs))
            if cl(grp[0]):
                lines.append(cl(grp[0]))
        cb = sorted([c for c in by_play["竞足串关"]], key=lambda c: c["label"])
        if cb:
            lines.append("")
            first = [pmap[i] for i in cb[0]["legs"]]
            lines.append(f"🎯{cb[0]['label']}：" + "+".join(f"{x['key']}{x['label']}" for x in first))
            for c in cb[1:]:
                extra = [pmap[i] for i in c["legs"][len(first):]]
                lines.append(f"🎯{c['label']}：再加" + "+".join(f"{x['key']}{x['label']}" for x in extra))
        lines += ["", CTA_PLAIN, TAGS["竞足"]]
        posts.append(("竞足", "\n".join(lines)))

    # 北单
    bdp = [p for p in by_play["北单"]]
    if bdp:
        lines = top("🔥【北单热门推单】让球胜平负", ["北单"])
        if meta["bd_fetch"] and not clean:
            lines.append(f"（SP为{meta['bd_fetch']}抓取值，以出票为准）")
        if lg(bdp):
            lines.append(lg(bdp))
        if not clean:
            lines.append("")
        for p in bdp:
            sp = f"｜SP {p['sp']:.2f}" if p.get("sp") else ""
            lines.append(f"{p['no']} {p['home']}vs{p['away']}｜{hcp_label(p)}{sp}{nt(p)}")
            if cl(p):
                lines.append(cl(p))
        cb = sorted(by_play["北单串关"], key=lambda c: c["label"])
        if cb:
            lines.append("")
            for k, c in enumerate(cb):
                nos = [pmap[i]["no"] for i in c["legs"]]
                lines.append(f"🎯{c['label']}：" + ("+".join(nos) if k == 0 else "再加" + nos[-1]) + f"（SP {c['sp']:.2f}）")
        lines += [""] + (["ℹ️SP以出票为准"] if clean else []) + [CTA_PLAIN, TAGS["北单"]]
        posts.append(("北单", "\n".join(lines)))

    # 竞篮
    jl = [p for p in by_play["竞篮"]]
    if jl:
        lines = top(f"🏀【竞篮推单】{meta['jl_league'] or md(day)}", ["竞篮"])
        if lg(jl):
            lines.append(lg(jl))
        done = set()
        for p in jl:
            if p["key"] in done:
                continue
            done.add(p["key"])
            main = next((x for x in jl if x["key"] == p["key"] and x["market"] == "胜负"), None)
            buck = next((x for x in jl if x["key"] == p["key"] and x["market"] == "胜分差" and not x.get("extra")), None)
            ex = [x for x in jl if x["key"] == p["key"] and x.get("extra")]
            if main:
                line = f"{p['key']} {p['home']}(主){main['line']} vs {p['away']}｜{main['label']}"
                if buck:
                    line += f"｜胜分差 {buck['label']}"
                lines.append(line)
                if cl(main):
                    lines.append(cl(main))
            for x in ex:
                lines.append(f"{p['key']} {p['home']}vs{p['away']}｜{x['label']}{nt(x)}")
        cb = by_play["竞篮串关"]
        if cb:
            legs = [pmap[i] for i in cb[0]["legs"]]
            lines += ["", f"🎯{cb[0]['label']}：" + "+".join(x["key"][-3:] for x in legs) + " " + legs[0]["label"]]
        lines += ["", CTA_PLAIN, TAGS["竞篮"]]
        posts.append(("竞篮", "\n".join(lines)))

    # 胜负彩 / 任九
    sfc = sorted(by_play["胜负彩"], key=lambda p: int(p["seq"]))
    if sfc:
        dl = meta["sfc_deadline"]
        dl_txt = ""
        if dl:
            dl_txt = (f"今晚{dl[11:16]}" if dl[:10] == day else f"{md(dl[:10])}{dl[11:16]}") + "截止"
        lines = top(f"🏆【胜负彩{meta['sfc_issue']}／任选九】{dl_txt}", ["胜负彩"])
        if lg(sfc):
            lines.append(lg(sfc))
        for p in sfc:
            lines.append(f"{p['seq']} {p['home']}-{p['away']}｜{p['label']}")
            if cl(p):
                lines.append(cl(p))
        nine = by_play["任九"]
        if nine:
            lines += ["", "🎯任九单选9场：" + " ".join(f"{x['seq']}({x['label']})" for x in nine[0]["nine"])]
        lines += ["", CTA_PLAIN, TAGS["胜负彩"]]
        posts.append(("胜负彩任九", "\n".join(lines)))

    # 4场进球 / 6场半全场
    jq, zc6 = sorted(by_play["4场进球"], key=lambda p: int(p["seq"])), sorted(by_play["6场半全场"], key=lambda p: int(p["seq"]))
    if jq or zc6:
        title = "／".join(x for x in ((f"4场进球{meta['jq4_issue']}" if jq else ""), (f"6场半全场{meta['zc6_issue']}" if zc6 else "")) if x)
        fams = [f for f, on in (("4场进球", jq), ("6场半全场", zc6)) if on]
        lines = top(f"🎲【{title}】", fams)
        if lg(jq + zc6):
            lines.append(lg(jq + zc6))
        shown: set = set()                               # 两个玩法里同一场比赛，对比只写一次

        def once(p: Dict[str, Any]) -> None:
            if cl(p) and (p["home"], p["away"]) not in shown:
                shown.add((p["home"], p["away"]))
                lines.append(cl(p))
        if jq:
            lines.append("4场进球" if clean else "4场进球（主队球数/客队球数）")
            for p in jq:
                if clean:
                    lines.append(f"{p['seq']} {p['home']}vs{p['away']}｜主{','.join(p['pick_home'])}｜客{','.join(p['pick_away'])}")
                else:
                    lines.append(f"{p['seq']} {p['home']}vs{p['away']}：{','.join(p['pick_home'])} / {','.join(p['pick_away'])}")
                once(p)
            lines.append("")
        if zc6:
            lines.append("6场半全场" if clean else "6场半全场（每场两选）")
            for p in zc6:
                lines.append(f"{p['seq']} {p['home']}-{p['away']}｜{p['label']}" if clean else f"{p['seq']} {p['home']}-{p['away']}：{p['label']}")
                once(p)
            lines.append("")
        if clean:
            lines += ["⚠️把握偏低，小注博冷", CTA_PLAIN, TAGS["进球半全场"]]
        else:
            lines += ["📌这两个玩法把握偏低，小注博冷", CTA_PLAIN, TAGS["进球半全场"]]
        posts.append(("进球半全场", "\n".join(lines)))

    # 昨日复盘（干净版：单独一篇放最后，想发就发，不想发就跳过；没有内容就不出）
    if clean and posts:
        rv = review_section(rev_fams, wb, hist, day)
        if not (len(rv) == 2 and rv[1].startswith("今天起开始记录")):
            posts.append(("昨日复盘", "\n".join(rv + ["", CTA_PLAIN, TAGS["复盘"]])))

    # 总览（放最前，只一小条：战绩 + 导览）
    head = [f"📊{md(day)}竞彩热门推单来了"]
    if settled_day:
        t = tally(hist, [settled_day])
        txt = tally_text(t)
        if txt:
            pend = sum(v[2] for v in t.values())
            head.append(f"✅{md(settled_day)}推单战绩｜{txt}" + (f"（另有{pend}条结果未出）" if pend else ""))
    recent = [(datetime.strptime(day, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, RECENT_DAYS + 1)]
    ct = tally_text(tally(hist, recent), pct=True)
    n_days = len({p["date"] for p in hist["picks"].values() if p["date"] in recent and p["status"] in ("hit", "miss")})
    if ct and n_days >= 2:                       # 只有一天的数据时，「近7日」和「昨日」一模一样，不重复写
        head.append(f"📈近{RECENT_DAYS}日累计｜{ct}")
    names = [n for n, _ in posts if n != "昨日复盘"]
    if names:
        head.append("🔥" + "·".join(names) + ("，往下看👇" if clean else "，每篇都附昨日复盘＋今日推单👇"))
    head += [CTA_PLAIN, TAGS["总览"]]
    posts.insert(0, ("总览", "\n".join(head)))
    return posts


# ════════════════════════════════════════════════════════════════════════════
# 9b. 自媒体版排版（固定栏目风格）
# ════════════════════════════════════════════════════════════════════════════
BRAND_FILE = "brand.json"
BRAND_DEFAULT: Dict[str, Any] = {
    "说明": "这是帖子的固定风格设置：改引号里的文字就行（别动冒号和逗号），存盘后下次点「一键更新」就生效。想用回朴素排版，把「朴素版」改成 true。"
            "「互动语」是每条帖子结尾的点赞/转发/关注号召：第一句用在总览帖，其余的轮流用；「提示语」留空就不写那一行。"
            "「图片风格」：按玩法＝每种玩法的图片各有一套配色和图案（竞足绿色球场、北单中国红、竞篮橙色球场线……），统一＝所有图片都用同一套深蓝；「图片配色」选浅色或深色底。"
            "「开场白」是总览帖开头的钩子：{n}=今日精选场数、{core1}=最看好的一场、{yday}=昨日单场战绩，用到的数据今天没有就跳过这句，每天轮流用一句。",
    "栏目名": "今日热推",
    "口号": "数据说话 · 命中不吹 · 未中不删",
    "署名": "",
    "话题标签": "#今日热推",
    "行动号召": "明天同一时间见👋",
    "观望语": "宁缺毋滥，没把握的单不推",
    "流派": "三看一防",
    "方法": "看赔率·看两队数据·看模型｜防平·防冷",
    "开场白": ["⚡今日{n}场单场推荐｜每场都对过两队数据", "📊{yday}｜命中不吹，未中不删", "🧠赔率、近况、模型三项对上才推｜宁缺毋滥"],
    "显示比分": True,
    "显示依据": True,
    "重点关注": True,
    "图片配色": "浅色",
    "图片风格": "按玩法",
    "图片水印": "",
    "互动语": list(CTA_DEFAULT),
    "提示语": "",
    "每日一句": ["量力而行，小注怡情", "只投输得起的钱", "看懂再买，不懂不碰", "连红别飘，连黑别追", "控制注额，比选对更重要",
                 "数据是参考，不是保证", "赛前冷静，赛后复盘"],
    "分隔线": "━━━━━━━━━━━━",
    "榜单勋章": ["🥇", "🥈", "🥉"],
    "显示数据标记": True,
    "显示星级": True,
    "显示综合概率": True,
    "串号": True,
    "朴素版": False,
}


def load_brand(folder: Optional[Path]) -> Dict[str, Any]:
    """读 brand.json（没有或写坏了就用默认的）。只认已知的项，类型不对的项用默认值。"""
    b = dict(BRAND_DEFAULT)
    if folder is None:
        return b
    try:
        data = json.loads(L.p(folder, BRAND_FILE).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return b
    if not isinstance(data, dict):
        return b
    for k, dv in BRAND_DEFAULT.items():
        v = data.get(k)
        if v is None:
            continue
        if isinstance(dv, bool):
            if isinstance(v, bool):
                b[k] = v
        elif isinstance(dv, str):
            if isinstance(v, str):
                b[k] = v.strip()
        elif isinstance(dv, list):
            if isinstance(v, list) and all(isinstance(x, str) for x in v) and v:
                b[k] = [x.strip() for x in v if x.strip()] or dv
    if b.get("提示语") in OLD_TIPS:                  # 还是以前默认的那句 → 不再写（想要的话自己在 brand.json 里重新填）
        b["提示语"] = ""
    if b.get("开场白") == OLD_GREET:                 # 还是以前默认的四句寒暄 → 换成新的钩子
        b["开场白"] = list(BRAND_DEFAULT["开场白"])
    return b


def ensure_brand_file(folder: Path) -> bool:
    """第一次用自媒体版时，把默认设置写成 brand.json 放在脚本文件夹里，方便改。已经有了就不动。返回是不是新建的。"""
    path = L.p(folder, BRAND_FILE)
    if path.exists():
        return False
    try:
        atomic_write(path, json.dumps(BRAND_DEFAULT, ensure_ascii=False, indent=2))
        return True
    except OSError:
        return False


def brand_add_missing(folder: Path) -> List[str]:
    """brand.json 是以前版本生成的：缺了新增的设置项就把缺的（默认值）补进去；还是以前默认的「提示语」「开场白」就换成新的；
    你自己改过的原样保留。返回做了哪些改动。"""
    path = L.p(folder, BRAND_FILE)
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, dict):
        return []
    miss = [k for k in BRAND_DEFAULT if k not in data]
    old_tip = data.get("提示语") in OLD_TIPS                                  # 以前默认的免责提示，没被改过 → 清空
    old_greet = data.get("开场白") == OLD_GREET                               # 以前默认的四句寒暄，没被改过 → 换成新的钩子
    if not miss and not old_tip and not old_greet:
        return []
    merged = {k: (data[k] if k in data else BRAND_DEFAULT[k]) for k in BRAND_DEFAULT}
    merged.update({k: v for k, v in data.items() if k not in merged})        # 用户自己加的别的项也留着
    if old_tip:
        merged["提示语"] = ""
    if old_greet:
        merged["开场白"] = list(BRAND_DEFAULT["开场白"])
    if (old_tip or old_greet or "互动语" in miss) and str(data.get("说明", "")).startswith("这是帖子的固定风格设置") and "开场白" not in str(data.get("说明", "")):
        merged["说明"] = BRAND_DEFAULT["说明"]                                # 说明文字还是默认的，顺手更新
    try:
        atomic_write(path, json.dumps(merged, ensure_ascii=False, indent=2))
    except OSError:
        return []
    return miss + (["提示语（原来那句已清空，不再写）"] if old_tip else []) + (["开场白（换成新的开头钩子）"] if old_greet else [])


def jl_idle_info(wb: Dict[str, List[Dict[str, str]]]) -> Optional[Dict[str, Any]]:
    """竞篮一条都没推时，说明今天竞篮是什么情况（没有在售场次就返回 None，不用说）。"""
    rows = [r for r in wb.get("竞篮-今日未开赛", []) if r.get("停售") != "是" and not league_excluded(r.get("联赛"))]
    if not rows:
        return None
    shown = [f"{r.get('主队', '')}{fmt_line(line_of(r.get('让分')))}" for r in rows]
    big = [t for r, t in zip(rows, shown) if abs(line_of(r.get("让分"))) >= JL_MIN_LINE]
    return {"n": len(rows), "shown": shown, "big": big}


def _hcp_label(p: Dict[str, Any]) -> str:                   # 让球负 → 让球(+1)负
    lab = str(p["label"])
    ln = f"({p['line']})" if p.get("line") else ""
    return "让球" + ln + lab[2:] if lab.startswith("让球") else lab


def _tally_rows(t: Dict[str, Tuple[int, int, int]]) -> List[str]:
    """战绩公示的几行：竞彩单场 / 传统足彩 / 串关＋任九（只列有结果的）。"""
    def one(plays: Tuple[str, ...]) -> str:
        return "｜".join(f"{pl} {t[pl][0]}/{t[pl][1]}" for pl in plays if pl in t and t[pl][1] > 0)
    comb = [pl for pl in ("竞足串关", "北单串关", "竞篮串关") if pl in t and t[pl][1] > 0]
    l3 = []
    if comb:
        l3.append(f"串关 {sum(t[pl][0] for pl in comb)}/{sum(t[pl][1] for pl in comb)}")
    if "任九" in t and t["任九"][1] > 0:
        l3.append(f"任九 {t['任九'][0]}/{t['任九'][1]}")
    return [x for x in (one(("竞足", "北单", "竞篮")), one(("胜负彩", "4场进球", "6场半全场")), "｜".join(l3)) if x]


def push_day_no(hist: Dict[str, Any], day: str) -> int:
    """今天是我们发推单的第几天（历史里有推单的不同日期数，含今天）。"""
    ds = {p.get("date") for p in hist.get("picks", {}).values() if p.get("date") and p["date"] <= day}
    ds.add(day)
    return len(ds)


def _split_cmp(txt: str) -> List[str]:
    """两队数据那一句拆成一条条（按「；」「。」），给「核心判断」「📊依据」用。"""
    return [x.strip() for x in str(txt or "").replace("。", "；").split("；") if x.strip()]


def _review_summary(hist: Dict[str, Any], day: str) -> List[str]:
    """昨日分项战绩（胜平负/让球分开算百分比）＋比分参考命中。只数我们自己推过的单场、结果已出的。"""
    rd, items = review_scope(hist, day)
    if rd is None:
        return []
    main = [p for p in items if p["date"] == rd and "legs" not in p and p["status"] in ("hit", "miss")]

    def frac(ps: List[Dict[str, Any]]) -> str:
        h, n = sum(p["status"] == "hit" for p in ps), len(ps)
        return f"{h}/{n}（{h / n:.0%}）"
    out: List[str] = []
    jz = [p for p in main if p["play"] == "竞足"]
    segs = []
    for mk, lab in (("胜平负", "胜平负"), ("让球胜平负", "让球")):
        ps = [p for p in jz if p["market"] == mk]
        if ps:
            segs.append(f"{lab} {frac(ps)}")
    if segs:
        out.append("🧭竞足：" + "｜".join(segs))
    bd = [p for p in main if p["play"] == "北单"]
    if bd:
        out.append(f"🧭北单：让球 {frac(bd)}")
    jl = [p for p in main if p["play"] == "竞篮" and p["market"] == "胜负"]
    if jl:
        out.append(f"🧭竞篮：胜负 {frac(jl)}")
    # 比分参考：只数当时带了模型比分的场次（同一场只算一次）
    seen: set = set()
    n_s = h_s = 0
    for p in jz + bd:
        m = p.get("mdl")
        mt = re.match(r"\s*(\d+:\d+)", str(p.get("result") or ""))
        if not (isinstance(m, dict) and m.get("ok") and mt) or (p.get("home"), p.get("away")) in seen:
            continue
        seen.add((p.get("home"), p.get("away")))
        n_s += 1
        h_s += mt.group(1) in m.get("top", [])
    if n_s:
        out.append(f"🎯比分参考（模型推算）：命中 {h_s}/{n_s}")
    if ST is not None:
        ms = ST.miss_summary([p for p in main if p["status"] == "miss"])
        if ms:
            out.append(ms)
    return out


def auto_period_kinds(day: str) -> List[str]:
    """哪天自动出周报/月报：销售日是周一 → 上周的周报；是每月 1 号 → 上个月的月报。"""
    d = datetime.strptime(day, "%Y-%m-%d")
    return (["周报"] if d.weekday() == 0 else []) + (["月报"] if d.day == 1 else [])


def period_range(day: str, kind: str, rolling: bool = False) -> Tuple[str, str]:
    """周报/月报统计哪一段（含首尾）。rolling=True：截至昨天的最近 7/30 天（按钮用）；否则上一个整周/整月（自动用）。"""
    d = datetime.strptime(day, "%Y-%m-%d")
    if rolling:
        return _shift(day, -(7 if kind == "周报" else 30)), _shift(day, -1)
    if kind == "周报":
        return _shift(day, -7), _shift(day, -1)
    last = d.replace(day=1) - timedelta(days=1)
    return last.replace(day=1).strftime("%Y-%m-%d"), last.strftime("%Y-%m-%d")


def period_lines(hist: Dict[str, Any], day: str, kind: str, B: Dict[str, Any], rolling: bool = False) -> Optional[List[str]]:
    """周报/月报帖子（一行一个元素）；样本太少（已出结果的单场不到 5 条）或没有 stats.py 返回 None。"""
    if ST is None:
        return None
    lo, hi = period_range(day, kind, rolling)
    tags = " ".join(x for x in (B.get("话题标签", ""), TAGS["复盘"]) if x)
    ctas = [x for x in (B.get("互动语") or []) if x]
    tail = "\n".join(x for x in ((ctas[0] if ctas else ""), B.get("提示语", "")) if x)      # 周报/月报的结尾：关注号召（+ 如果设了提示语）
    txt = ST.period_post(hist, lo, hi, kind, B["栏目名"], B["分隔线"], B.get("口号", ""), tail, tags)
    return txt.split("\n") if txt else None


def render_media(gen: Dict[str, Any], day: str, wb: Dict[str, List[Dict[str, str]]], hist: Dict[str, Any],
                 settled_day: Optional[str], B: Dict[str, Any]) -> List[Tuple[str, str]]:
    """自媒体版（「三看一防」流派）：每条帖子都是同一套固定栏目风格——栏目头、分隔线、热度榜勋章、逐场卡片
    （方向＋防平／比分参考／进球数／一句依据）、核心方向与防冷重点、战绩公示、固定提示语和话题标签。
    所有数字都来自真实数据（战绩、天数、场数、两队数据、数据模型推算），没有数据的部分直接不写，不写「稳赚/必中」之类的话。"""
    picks, meta = gen["picks"], gen["meta"]
    by_play: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for p in picks:
        by_play[p["play"]].append(p)
    pmap = {p["id"]: p for p in picks}
    sep, name = B["分隔线"], B["栏目名"]
    medals = list(B["榜单勋章"])
    show_mark = bool(B["显示数据标记"])
    star_ok, star_note = ST.star_trust(hist) if ST is not None else (True, "")
    show_stars = bool(B.get("显示星级", True)) and star_ok
    show_score, show_basis = bool(B.get("显示比分", True)), bool(B.get("显示依据", True))
    cp_ok, cp_note = C.cp_trust(hist) if C is not None else (False, "")
    show_cp = C is not None and bool(B.get("显示综合概率", True)) and cp_ok
    rev_fams: List[str] = []
    posts: List[Tuple[str, List[str]]] = []

    def medal(i: int) -> str:
        return medals[i] if i < len(medals) else "🔹"

    def has_cp(p: Dict[str, Any]) -> bool:                                  # 综合概率里真的掺了模型，才写「综合」
        return show_cp and C is not None and C.has_model(p)

    def mark(p: Dict[str, Any]) -> str:
        return ((" " + "★" * p["star"] if show_stars and isinstance(p.get("star"), int) else "")
                + (f" 综合{p['cp']:.0%}" if has_cp(p) else "")
                + (" ⚠️分歧" if has_cp(p) and p.get("cp_div") else "")
                + (" 📈" if show_mark and p.get("cmp_v") == "support" else ""))

    def kick(p: Dict[str, Any]) -> str:
        m = re.match(r"(\d{4}-\d{2}-\d{2}) (\d{2}:\d{2})", str(p.get("kick") or ""))
        if not m:
            return ""
        return f" ⏰{m.group(2)}" + ("(次日)" if m.group(1) > day else "")

    def legend(ps: List[Dict[str, Any]]) -> str:
        sup = show_mark and any(p.get("cmp_v") == "support" for p in ps)
        stars = show_stars and any(isinstance(p.get("star"), int) for p in ps)
        cpb = any(has_cp(p) for p in ps)
        bits = (["★越多=综合把握越大"] if stars else []) + (["综合=赔率+模型+数据"] if cpb else []) \
            + (["⚠️分歧=赔率和模型看法差得多"] if any(has_cp(p) and p.get("cp_div") for p in ps) else []) + (["📈=两队数据支持"] if sup else [])
        return "（" + "｜".join(bits) + "）" if bits else ""

    def mdl_of(ps: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:      # 回测过关的数据模型卡片（没过关不写比分）
        return next((p["mdl"] for p in ps if isinstance(p.get("mdl"), dict) and p["mdl"].get("ok")), None)

    def backed(p: Dict[str, Any]) -> str:                                    # 胜平负推荐 → 「桑德兰胜」
        return f"{p['home']}胜" if p["label"] == "胜" else (f"{p['away']}胜" if p["label"] == "负" else str(p["label"]))

    def score_line(m: Optional[Dict[str, Any]]) -> str:
        if not (show_score and m):
            return ""
        return "🎯比分参考 " + "｜".join(m["top"]) + "　⚽进球 " + "、".join(str(x) for x in m["goals"]) + "球"

    def basis_line(p: Dict[str, Any]) -> str:                                # 两队近况各一句（只取前两句，更多的放「重点关注」）
        parts = [re.split(r"[（、]", x)[0] for x in _split_cmp(p.get("cmp")) if "近" in x and not x.startswith("数据模型")][:2]
        return ("📊" + "｜".join(parts)) if (show_basis and parts) else ""

    def head(icon: str, play: str, sub: str = "") -> List[str]:
        return [f"{icon}【{name}·{play}】{sub}", sep]

    ctas = [x for x in (B.get("互动语") or []) if x]
    day_no = push_day_no(hist, day)
    cta_n = [0]

    def next_cta() -> str:                                      # 结尾互动语：总览用第 1 句（引导关注），其余帖子按顺序轮流用后面的，相邻帖子不重样
        if len(ctas) == 1:
            return ctas[0]
        rest = ctas[1:]
        s = rest[(day_no - 1 + cta_n[0]) % len(rest)]
        cta_n[0] += 1
        return s

    def foot(tag_key: str, extra: Optional[List[str]] = None, tags_more: str = "", first: bool = False) -> List[str]:
        out = [""] + (extra or []) + [sep]
        if ctas:
            out.append(ctas[0] if first else _CTA_MARK)
        if B.get("提示语"):
            out.append(B["提示语"])
        if B["署名"]:
            out.append(B["署名"])
        out.append(" ".join(x for x in (B["话题标签"], TAGS.get(tag_key, ""), tags_more) if x))
        return out

    # —— 竞足 ——
    jc = by_play["竞足"]
    jc_groups: List[List[Dict[str, Any]]] = []
    if jc:
        rev_fams.append("竞足")
        order: List[str] = []
        for p in jc:
            if p["key"] not in order:
                order.append(p["key"])
        jc_groups = [[p for p in jc if p["key"] == k] for k in order]
        lines = head("⚽", "竞足", md(day))
        lines.append(f"热度榜 TOP{len(order)}{legend(jc)}")
        lines.append("")
        for i, grp in enumerate(jc_groups):
            g0 = grp[0]
            m = mdl_of(grp)
            segs = []
            for p in grp:
                if p["market"] == "胜平负":
                    draw = " 防平" if (m and m["pd"] >= DRAW_GUARD) else ""
                    segs.append(f"胜平负：{backed(p)}{draw}")
                elif p["market"] == "让球胜平负":
                    segs.append(_hcp_label(p))
                else:
                    segs.append(str(p["label"]))
            lines.append(f"{medal(i)} {g0['key']}" + (f"｜{g0['lg']}" if g0.get("lg") else "") + kick(g0))
            lines.append(f"{g0['home']} vs {g0['away']}")
            lines.append("🧭" + "｜".join(segs) + mark(g0))
            for extra in (score_line(m), basis_line(g0)):
                if extra:
                    lines.append(extra)
            lines.append("")
        lines.pop()
        cb = sorted(by_play["竞足串关"], key=lambda c: c["label"])
        if cb:
            lines.append("")
            first = [pmap[i] for i in cb[0]["legs"]]
            lines.append(f"🎯{cb[0]['label']}：" + "+".join(f"{x['key']}{x['label']}" for x in first))
            for c in cb[1:]:
                extra = [pmap[i] for i in c["legs"][len(first):]]
                lines.append(f"🎯{c['label']}：再加" + "+".join(f"{x['key']}{x['label']}" for x in extra))
        posts.append(("竞足", lines + foot("竞足", ["💡防平＝数据模型算平局概率偏高"] if any("防平" in x for x in lines) else None)))

    # —— 北单 ——
    bdp = by_play["北单"]
    if bdp:
        rev_fams.append("北单")
        lines = head("🔥", "北单", "让球胜平负")
        lines.append(f"SP热度榜 TOP{len(bdp)}{legend(bdp)}")
        lines.append("")
        for i, p in enumerate(bdp):
            sp = f"｜SP {p['sp']:.2f}" if p.get("sp") else ""
            lines.append(f"{medal(i)} {p['no']} {p['home']}vs{p['away']}｜{_hcp_label(p)}{sp}{mark(p)}")
            sl = score_line(mdl_of([p]))
            if sl:
                lines.append("　" + sl)
        cb = sorted(by_play["北单串关"], key=lambda c: c["label"])
        if cb:
            lines.append("")
            for k, c in enumerate(cb):
                nos = [pmap[i]["no"] for i in c["legs"]]
                lines.append(f"🎯{c['label']}：" + ("+".join(nos) if k == 0 else "再加" + nos[-1]) + f"（SP {c['sp']:.2f}）")
        posts.append(("北单", lines + foot("北单", ["SP为抓取时的值，以出票为准"])))

    # —— 竞篮 ——
    jl = by_play["竞篮"]
    if jl:
        rev_fams.append("竞篮")
        lines = head("🏀", "竞篮", meta.get("jl_league") or md(day))
        keys: List[str] = []
        for p in jl:
            if p["key"] not in keys:
                keys.append(p["key"])
        lines.append(f"大热门榜 TOP{len(keys)}（让分越大越靠前）{legend(jl)}")
        lines.append("")
        for i, k in enumerate(keys):
            main = next((x for x in jl if x["key"] == k and x["market"] == "胜负"), None)
            buck = next((x for x in jl if x["key"] == k and x["market"] == "胜分差" and not x.get("extra")), None)
            ex = [x for x in jl if x["key"] == k and x.get("extra")]
            g0 = next(x for x in jl if x["key"] == k)
            if main:
                lines.append(f"{medal(i)} {k}" + (f"｜{g0['lg']}" if g0.get("lg") else "") + kick(g0))
                lines.append(f"{g0['home']}(主){main['line']} vs {g0['away']}")
                lines.append("🧭" + str(main["label"]) + (f"｜胜分差 {buck['label']}" if buck else "") + mark(main))
                bl = basis_line(main)
                if bl:
                    lines.append(bl)
            for x in ex:
                lines.append(f"{k} {x['home']}vs{x['away']}｜{x['label']}")
            lines.append("")
        lines.pop()
        cb = by_play["竞篮串关"]
        if cb:
            legs = [pmap[i] for i in cb[0]["legs"]]
            lines += ["", f"🎯{cb[0]['label']}：" + "+".join(x["key"][-3:] for x in legs) + " " + legs[0]["label"]]
        posts.append(("竞篮", lines + foot("竞篮")))
    jl_idle = None if jl else jl_idle_info(wb)
    if jl_idle:                                                     # 今天有竞篮场次却一条没推：写一条说明放进今日推单，别让人以为篮球没跑
        rev_fams.append("竞篮")
        lines = head("🏀", "竞篮", "今日观望")
        lines.append("🙅今日竞篮不出手")
        if jl_idle["big"]:
            lines.append(f"今天共{jl_idle['n']}场，有{len(jl_idle['big'])}场让分≥{JL_MIN_LINE:g}的大热门（{'｜'.join(jl_idle['big'][:6])}），"
                         "但没有通过把关（两队数据不支持、没取到数据或被排除），按规则不推")
        else:
            lines.append(f"今天共{jl_idle['n']}场，没有让分≥{JL_MIN_LINE:g}的大热门（竞篮只推大热门）")
        lines.append("📋今日让分：" + "｜".join(jl_idle["shown"][:8]))
        if B.get("观望语"):
            lines.append("💬" + B["观望语"])
        posts.append(("竞篮", lines + foot("竞篮")))

    # —— 胜负彩 / 任九 ——
    sfc = sorted(by_play["胜负彩"], key=lambda p: int(p["seq"]))
    if sfc:
        rev_fams.append("胜负彩")
        dl = meta.get("sfc_deadline") or ""
        dl_txt = ""
        if dl:
            dl_txt = (f"今晚{dl[11:16]}" if dl[:10] == day else f"{md(dl[:10])}{dl[11:16]}") + "截止"
        lines = head("🏆", f"胜负彩{meta.get('sfc_issue', '')}／任选九", dl_txt)
        lines.append("🎯单选 🔸双选 ⚪全包" + legend(sfc))
        lines.append("")
        for p in sfc:
            n_opt = len(str(p["label"]).split("/"))
            tier = "🎯" if n_opt == 1 else ("🔸" if n_opt == 2 else "⚪")
            lines.append(f"{int(p['seq']):02d} {p['home']}-{p['away']} ▶ {p['label']} {tier}{mark(p)}")
        nine = by_play["任九"]
        if nine:
            lines += ["", "🎯任九单选9场：" + " ".join(f"{x['seq']}({x['label']})" for x in nine[0]["nine"])]
        posts.append(("胜负彩任九", lines + foot("胜负彩")))

    # —— 4场进球 / 6场半全场 ——
    jq, zc6 = sorted(by_play["4场进球"], key=lambda p: int(p["seq"])), sorted(by_play["6场半全场"], key=lambda p: int(p["seq"]))
    if jq or zc6:
        title = "／".join(x for x in ((f"4场进球{meta.get('jq4_issue', '')}" if jq else ""), (f"6场半全场{meta.get('zc6_issue', '')}" if zc6 else "")) if x)
        rev_fams += [f for f, on in (("4场进球", jq), ("6场半全场", zc6)) if on]
        lines = head("🎲", title)
        lines.append("🧊把握偏低，小注博冷")
        lines.append("")
        if jq:
            lines.append("【4场进球】主队球数｜客队球数")
            for p in jq:
                lines.append(f"{p['seq']} {p['home']}vs{p['away']} ▶ 主{','.join(p['pick_home'])}｜客{','.join(p['pick_away'])}")
            lines.append("")
        if zc6:
            lines.append("【6场半全场】每场两选")
            for p in zc6:
                lines.append(f"{p['seq']} {p['home']}-{p['away']} ▶ {p['label']}")
            lines.append("")
        if lines[-1] == "":
            lines.pop()
        posts.append(("进球半全场", lines + foot("进球半全场")))

    # —— 综合推单（赔率 + 数据模型 + 两队数据 合成的综合概率，把今天所有单场放在一起排）——
    comp_post: Tuple[str, List[str]] = ("", [])
    ents: List[Dict[str, Any]] = []
    for p in by_play["竞足"]:
        if p["market"] == "胜平负" and p.get("cp") is not None:
            ents.append({"p": p, "tag": f"竞足{p['key'][-3:]}", "txt": backed(p), "sp": ""})
    for p in by_play["北单"]:
        if p.get("cp") is not None:
            ents.append({"p": p, "tag": f"北单{p['no']}", "txt": _hcp_label(p), "sp": f"｜SP {p['sp']:.2f}" if p.get("sp") else ""})
    for p in by_play["竞篮"]:
        if p["market"] == "胜负" and p.get("cp") is not None:
            ents.append({"p": p, "tag": f"竞篮{p['key'][-3:]}", "txt": f"{p['label']}（{p['home']}{p['line']}）", "sp": ""})
    ents.sort(key=lambda e: (-e["p"]["cp"], e["p"].get("kick") or ""))
    merged: List[Dict[str, Any]] = []
    for e in ents:                                                       # 同一场在竞足和北单里都有：只列综合概率高的那条，另一个玩法写在后面
        dup = next((m_ for m_ in merged if _same_team(m_["p"]["home"], e["p"]["home"]) and _same_team(m_["p"]["away"], e["p"]["away"])), None)
        if dup is not None:
            dup.setdefault("also", []).append(e["tag"])
        else:
            merged.append(e)
    if merged:
        top_n = merged[:max(1, COMP_TOP_N)]
        w_ = comp_w()
        any_model = any(C is not None and C.has_model(e["p"]) for e in top_n)
        lines = head("🧮", "综合推单", md(day))
        lines.append(("赔率 + 数据模型 + 两队数据 → 一个综合概率，高→低排" if any_model else "赔率 + 两队数据 → 综合排序（今天数据模型没过回测，没掺进去）")
                     + f" TOP{len(top_n)}")
        lines.append("")
        for i, e in enumerate(top_n):
            p = e["p"]
            lines.append(f"{medal(i)} {e['tag']}｜{p['home']} vs {p['away']}" + kick(p))
            star = (" " + "★" * p["star"]) if (show_stars and isinstance(p.get("star"), int)) else ""
            cp_t = f"｜综合{p['cp']:.0%}" if show_cp else ""
            lines.append(f"👉{e['txt']}{e['sp']}{cp_t}{star}" + (" ⚠️分歧" if (show_cp and p.get("cp_div") and C is not None and C.has_model(p)) else ""))
            if show_cp and show_basis:
                bits = [f"赔率{p['cp_m']:.0%}" if isinstance(p.get("cp_m"), (int, float)) else ""]
                bits.append(f"模型{p['cp_q']:.0%}" if isinstance(p.get("cp_q"), (int, float)) else "模型—")
                v = p.get("cmp_v")
                if show_mark:                                    # 「显示数据标记」关掉时，连 📈 这一栏的说明也不写
                    bits.append("📈数据支持" if v == "support" else "△数据部分支持" if v == "mixed" else "")
                if e.get("also"):
                    bits.append("另有" + "、".join(e["also"]))
                lines.append("　" + "｜".join(b for b in bits if b))
            elif e.get("also"):
                lines.append("　另有" + "、".join(e["also"]))
            lines.append("")
        lines.pop()
        notes_ = []
        if any_model:
            notes_.append(f"💡综合＝赔率 {1 - w_:.0%} + 模型 {w_:.0%} 合并，再按两队数据小幅加减；估算而已，不是保证")
        if show_cp and any(p.get("cp_div") and C.has_model(p) for p in (e["p"] for e in top_n)):
            notes_.append("⚠️分歧＝赔率和模型对这一方的看法差得多，拿不准就少买或跳过")
        if C is not None and not cp_ok and cp_note:
            notes_.append("ℹ️综合概率暂不显示百分比（战绩里还没看出区分度，数据多了自动恢复）")
        comp_post = ("综合推单", lines + foot("综合推单", notes_ or None))

    # —— 重点关注（单场深度：今天竞足榜里第一个有两队数据的场次）——
    focus = next((g for g in jc_groups if g[0].get("cmp")), None) if B.get("重点关注", True) else None
    focus_post: Tuple[str, List[str]] = ("", [])
    if focus:
        g0 = focus[0]
        m = mdl_of(focus)
        plain = next((p for p in focus if p["market"] == "胜平负"), None)
        lines = head("🔍", "重点关注", "今日最值得细看的一场")
        lines.append(f"{g0['key']}" + (f"｜{g0['lg']}" if g0.get("lg") else "") + kick(g0))
        lines.append(f"{g0['home']} vs {g0['away']}")
        segs = []
        if plain:
            segs.append(f"胜平负：{backed(plain)}" + (" 防平" if (m and m["pd"] >= DRAW_GUARD) else ""))
        segs += [_hcp_label(p) for p in focus if p["market"] == "让球胜平负"]
        lines.append("🧭" + "｜".join(segs) + mark(g0))
        if m and show_score:
            lines.append("🎯比分参考 " + "｜".join(m["top"]))
            lines.append("⚽进球数 " + "、".join(str(x) for x in m["goals"]) + "球")
        lines += ["", "⚔️核心判断"]
        bullets = [x for x in _split_cmp(g0["cmp"]) if not x.startswith("数据模型")][:6]
        if m:
            bullets.insert(min(2, len(bullets)), f"数据模型推算：预计进球 {g0['home']}{m['lh']:.1f}:{g0['away']}{m['la']:.1f}，"
                                                  f"胜平负 {m['ph']:.0%}/{m['pd']:.0%}/{m['pa']:.0%}")
        lines += ["• " + x for x in bullets]
        focus_post = ("重点关注", lines + foot("竞足", None, f"#{g0['home']}vs{g0['away']}"))

    # —— 昨日战绩公示 ——
    rev_label_ov = ""
    if posts:
        rv = review_section(rev_fams, wb, hist, day)
        if not (len(rv) == 2 and rv[1].startswith("今天起开始记录")):
            has_rec = any(l.startswith("📋") for l in rv)             # 有我们自己推过的单可以对账，才叫「战绩公示」；只有赛果概况就叫「昨日赛果」
            rev_label = "战绩公示" if has_rec else "赛果"
            summ = _review_summary(hist, day) if has_rec else []
            lines = [f"📊【{name}·昨日{rev_label}】", sep] + (["💬命中不吹，未中不删，逐条公示👇"] if has_rec else []) + [""]
            if summ:
                lines += ["📌昨日分项"] + summ + [""]
            lines += rv[1:]
            posts.append(("昨日复盘", lines + foot("复盘")))
            rev_label_ov = "战绩公示" if has_rec else "昨日赛果"
    if posts:                                                    # 周一出上周周报、每月 1 号出上月月报（样本太少就不出）
        for kind in auto_period_kinds(day):
            pl_ = period_lines(hist, day, kind, B)
            if pl_:
                posts.append((kind, pl_))

    # —— 总览（放最前）——
    singles = []
    for play, label in (("竞足", "竞足"), ("北单", "北单"), ("竞篮", "竞篮")):
        n = len({p["key"] for p in by_play[play]}) if play != "北单" else len(by_play[play])
        if n:
            singles.append(f"{label}{n}场")
    if jl_idle:
        singles.append("竞篮观望")
    if by_play["胜负彩"]:
        singles.append("胜负彩任九")
    if by_play["4场进球"] or by_play["6场半全场"]:
        singles.append("进球半全场")
    head_l = [f"🔥【{name}】{md(day)}｜第{day_no}天", sep]
    core = []                                                   # 核心方向：竞足榜前两场（读得懂的「某队胜」）＋北单榜首
    for g in jc_groups[:2]:
        pl = next((p for p in g if p["market"] == "胜平负"), None)
        if pl:
            core.append(backed(pl) + mark(pl))
        else:
            core.append(f"{g[0]['home']}vs{g[0]['away']} {_hcp_label(g[0])}" + mark(g[0]))
    if bdp:
        core.append(f"北单{bdp[0]['home']}vs{bdp[0]['away']} {_hcp_label(bdp[0])}" + mark(bdp[0]))
    n_single = len(jc_groups) + len(bdp) + len({p["key"] for p in jl})        # 今天精选了几场单场
    yday = ""                                                   # 昨日单场战绩（只算已出结果的，少于 3 条不写）
    if settled_day:
        ty = {k: v for k, v in tally(hist, [settled_day]).items() if k in SINGLE_PLAYS}
        yh, yn = sum(v[0] for v in ty.values()), sum(v[1] for v in ty.values())
        if yn >= 3:
            yday = f"昨日单场 {yh}/{yn}（{yh / yn:.0%}）"
    hook_vals = {"n": str(n_single) if n_single else "", "core1": core[0] if core else "", "yday": yday}
    hooks = []                                                  # 开头钩子：「开场白」里的句子，用到的数据今天没有就跳过这句；轮流用
    for tpl in B.get("开场白", []):
        keys = re.findall(r"\{(\w+)\}", tpl)
        if tpl and all(hook_vals.get(k) for k in keys):
            hooks.append(re.sub(r"\{(\w+)\}", lambda m_: hook_vals[m_.group(1)], tpl))
    if n_single == 0:
        hooks = ["🙅今日没有够把握的单场，宁缺毋滥"] + [h for h in hooks if "精选" not in h]
    if hooks:
        head_l.append(hooks[0] if n_single == 0 else hooks[(day_no - 1) % len(hooks)])
    if singles:
        head_l.append("📌今日精选：" + "｜".join(singles))
    if core:
        head_l.append("🎯核心方向：" + "｜".join(core))
    cold = None                                                 # 防冷重点：推荐方「赢球概率」最低的一场（综合概率；没有就用模型算的），低于 60% 才提
    for g in jc_groups:
        pl, m = next((p for p in g if p["market"] == "胜平负"), None), mdl_of(g)
        if pl and m:
            use_cp = C is not None and C.has_model(pl)
            pr = pl["cp"] if use_cp else (m["ph"] if pl["label"] == "胜" else m["pa"])
            if cold is None or pr < cold[0]:
                cold = (pr, g[0], pl, use_cp)
    if cold and cold[0] <= COLD_MAX:
        head_l.append(f"⚠️防冷重点：{cold[1]['home']}vs{cold[1]['away']}（{'综合' if cold[3] else '模型'}算{cold[2]['home'] if cold[2]['label'] == '胜' else cold[2]['away']}赢球仅{cold[0]:.0%}）")
    if settled_day:
        t = tally(hist, [settled_day])
        rows = _tally_rows(t)
        if rows:
            pend = sum(v[2] for v in t.values())
            head_l.append(f"✅{md(settled_day)}战绩公示" + (f"（另有{pend}条结果未出）" if pend else ""))
            head_l += rows
    recent = [(datetime.strptime(day, "%Y-%m-%d") - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, RECENT_DAYS + 1)]
    t7 = {k: v for k, v in tally(hist, recent).items() if k in SINGLE_PLAYS}
    ct = tally_text(t7, pct=True)
    n_days = len({p["date"] for p in hist["picks"].values() if p["date"] in recent and p["status"] in ("hit", "miss")})
    if ct and n_days >= 2:
        head_l.append(f"📈近{RECENT_DAYS}日（单场）：{ct}")
    if B.get("方法") and any(isinstance(p.get("mdl"), dict) and p["mdl"].get("ok") for p in picks):   # 方法一行：只有这次真的用了回测过关的数据模型才写（写了「看模型」就得真看了）
        head_l.append("🧠" + (f"{B['流派']}｜" if B.get("流派") else "") + B["方法"])
    names = ([comp_post[0]] if comp_post[0] else []) + ([focus_post[0]] if focus else []) + [n for n, _ in posts if n != "昨日复盘"]
    head_l.append(sep)
    if names:
        head_l.append("👇" + "·".join(names) + (("·" + rev_label_ov) if rev_label_ov else "") + "，逐条往下看")
    tips = [x for x in B["每日一句"] if x]
    if tips:
        head_l.append("💬今日一句：" + tips[(day_no - 1) % len(tips)])
    if B["口号"]:
        head_l.append("📣" + B["口号"])
    if B["行动号召"]:
        head_l.append(B["行动号召"])
    head_l += foot("总览", first=True)[1:]                      # foot 开头的空行去掉（上面已经有分隔了）
    posts.insert(0, ("总览", head_l))
    k_ = 1
    if comp_post[0]:
        posts.insert(k_, comp_post)
        k_ += 1
    if focus:
        posts.insert(k_, focus_post)

    # —— 串号 🧵 ——
    out: List[Tuple[str, str]] = []
    n_all = len(posts)
    for i, (nm, ls) in enumerate(posts, 1):
        ls = [next_cta() if l == _CTA_MARK else l for l in ls]          # 按最终顺序给每条帖子分配结尾互动语
        if B["串号"] and n_all > 1:
            ls[0] = f"{ls[0]}｜🧵{i}/{n_all}"
        out.append((nm, "\n".join(ls)))
    return out


# ════════════════════════════════════════════════════════════════════════════
# 9b. 每日关键词（keywords.py）：按今天在售的赛事整理搜索词（一行一个词），不影响推单本身
# ════════════════════════════════════════════════════════════════════════════
KW_SHEETS = (("竞足-今日未开赛", "竞足"), ("北单-今日未开赛", "北单"), ("竞篮-今日未开赛", "竞篮"))
KW_EXTRA = {"竞足": (("jz_line", "让球"),), "北单": (("bd_line", "让球"),), "竞篮": (("jl_line", "让分"), ("jl_total", "预设总分"))}
KW_TRAD = {"胜负彩/任选九": ("胜负彩", "任九"), "6场半全场": ("6场半全场",), "4场进球": ("4场进球",)}


def kw_matches(wb: Dict[str, List[Dict[str, str]]], picks: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
    """今天在售的赛事（竞足/北单/竞篮；去掉停售和被排除的联赛；竞足和北单里的同一场只算一次）＋今天有哪些玩法。
    今天有推荐的场次标上 rec / star / cp，关键词排序用。"""
    ms: List[Dict[str, Any]] = []
    plays_on: List[str] = []
    for sheet, play in KW_SHEETS:
        rows = [r for r in wb.get(sheet, []) if r.get("停售") != "是" and not league_excluded(r.get("联赛"))
                and (r.get("主队") or "").strip() and (r.get("客队") or "").strip()]
        if rows:
            plays_on.append(play)
        for r in rows:
            h, a = r["主队"].strip(), r["客队"].strip()
            kick = (r.get("开赛时间(北京时间)") or "").strip()
            cur = {"h": h, "a": a, "dt": parse_dt(kick), "lg": r.get("联赛", "")}
            xtra = {k_: (r.get(c_) or "").strip() for k_, c_ in KW_EXTRA.get(play, ()) if (r.get(c_) or "").strip()}      # 评论话术用：让球线／让分／预设总分
            key = (r.get("赛事编号") or "").strip() or (f"北单{str(r.get('场次') or '').strip()}" if play == "北单" else "")
            dup = next((m for m in ms if _score(m["_n"], cur) > 0), None)
            if dup is not None:
                if play not in dup["plays"]:
                    dup["plays"].append(play)
                if key and key not in dup["keys"]:
                    dup["keys"].append(key)
                if len(h) > len(dup["home"]):                 # 两个表里叫法不一样（格风暴／格拉茨风暴）：取更完整的那个
                    dup["home"] = h
                if len(a) > len(dup["away"]):
                    dup["away"] = a
                for k_, v_ in xtra.items():
                    dup["x"].setdefault(k_, v_)
                continue
            ms.append({"plays": [play], "keys": [key] if key else [], "lg": (r.get("联赛") or "").strip(), "home": h, "away": a,
                       "kick": kick, "_n": cur, "x": xtra})
    for p in picks:
        if p.get("play") not in ("竞足", "北单", "竞篮") or not p.get("home") or not p.get("away"):
            continue
        pn = {"h": p["home"], "a": p["away"], "dt": parse_dt(str(p.get("kick") or "")), "lg": ""}
        m = next((m_ for m_ in ms if _score(m_["_n"], pn) > 0), None)
        if m is None:
            continue
        m["rec"] = True
        m.setdefault("picks", []).append(p)
        if isinstance(p.get("star"), int):
            m["star"] = max(m.get("star", 0), p["star"])
        if isinstance(p.get("cp"), (int, float)):
            m["cp"] = max(m.get("cp", 0.0), float(p["cp"]))
    for m in ms:
        m.pop("_n", None)
    for r in wb.get("传统足彩-在售期", []):
        for f in KW_TRAD.get(str(r.get("玩法") or "").strip(), ()):
            if f not in plays_on:
                plays_on.append(f)
    return ms, plays_on


def make_keywords(wb: Dict[str, List[Dict[str, str]]], gen: Dict[str, Any], day: str, folder: Path,
                  say: Callable[[str], None], create: bool = True) -> Optional[Dict[str, Any]]:
    """生成今天的关键词（词库在 设置\\关键词库.json，你自己加的热词在 设置\\热词.txt）。出任何问题只提示、不影响推单。"""
    if KW is None or not SHOW_KW:
        return None
    try:
        lex_path, hot_path = L.p(folder, KW.LEX_FILE), L.p(folder, KW.HOT_FILE)
        if create and ensure_lexicon_and_hot(folder):
            say(f"· 已生成 {KW.LEX_FILE}（每日关键词用的词库）和 {KW.HOT_FILE}（放你自己看到的真正热搜词），想改就改")
        lex, w1 = KW.load_lexicon(lex_path)
        hot, w2 = KW.load_hot(hot_path)
        for w_ in w1 + w2:
            say("⚠ " + w_)
        ms, plays_on = kw_matches(wb, gen["picks"])
        meta = gen.get("meta") or {}
        issues = {"胜负彩": meta.get("sfc_issue", ""), "任九": meta.get("sfc_issue", ""), "4场进球": meta.get("jq4_issue", ""),
                  "6场半全场": meta.get("zc6_issue", "")}
        bad = list(getattr(GD, "FORBIDDEN", [])) if GD is not None else []
        kw = KW.build(day, ms, lex, hot=hot, plays_on=plays_on, issues=issues, top_n=KW_TOP_N, bad=bad)
        kw["warns"] = w1 + w2
        return kw
    except Exception as exc:  # noqa: BLE001 —— 关键词只是附带的东西，出任何问题都不能拖垮推单
        say(f"· 每日关键词这一步出错了（{type(exc).__name__}: {exc}），已跳过，推单不受影响")
        return None


def cm_entries(wb: Dict[str, List[Dict[str, str]]], picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """评论话术要写的比赛：今天在售的赛事（同 kw_matches，竞足/北单/竞篮里的同一场只算一次，带上各自的推荐）＋
    只出现在传统足彩里的场次（胜负彩推荐、4场进球、6场半全场）。"""
    ms, _plays = kw_matches(wb, picks)
    for m in ms:
        m.setdefault("picks", [])
    for p in picks:
        if p.get("play") not in ("胜负彩", "4场进球", "6场半全场") or "legs" in p or not p.get("home") or not p.get("away"):
            continue
        pn = {"h": p["home"], "a": p["away"], "dt": parse_dt(str(p.get("kick") or "")), "lg": ""}
        m = next((m_ for m_ in ms if _score({"h": m_["home"], "a": m_["away"], "dt": parse_dt(str(m_.get("kick") or "")), "lg": ""}, pn) > 0), None)
        if m is None:
            m = {"plays": [], "keys": [], "lg": str(p.get("lg") or ""), "home": p["home"], "away": p["away"], "kick": str(p.get("kick") or ""), "x": {}, "picks": []}
            ms.append(m)
        if p["play"] not in m["plays"]:
            m["plays"].append(p["play"])
        if p["play"] == "胜负彩":
            m["picks"].append(p)
    return ms


def make_comments(wb: Dict[str, List[Dict[str, str]]], gen: Dict[str, Any], day: str, folder: Path, say: Callable[[str], None],
                  hist: Dict[str, Any], brand: Optional[Dict[str, Any]], create: bool = True, seed: int = 0) -> Optional[Dict[str, Any]]:
    """生成今天的评论话术（句库在 设置\\话术库.json）。话术里的数字全部来自当天的真实数据；显示星级/综合概率/比分/依据的开关和战绩可信度，和帖子里的一致。
    出任何问题只提示、不影响推单。"""
    if CM is None or not SHOW_CM:
        return None
    try:
        B = brand or dict(BRAND_DEFAULT)
        lib_path = L.p(folder, CM.LIB_FILE)
        if create and CM.ensure_lib_file(lib_path) == ["新建话术库"]:
            say(f"· 已生成 {CM.LIB_FILE}（评论句库：编辑「简短评论」可调整短句口吻）")
        bad = list(getattr(GD, "FORBIDDEN", [])) if GD is not None else []
        lib, warns = CM.load_lib(lib_path, bad)
        for w_ in warns:
            say("⚠ " + w_)
        star_ok = ST.star_trust(hist)[0] if ST is not None else True
        cp_ok = C.cp_trust(hist)[0] if C is not None else False
        flags = {"stars": bool(B.get("显示星级", True)) and star_ok,
                 "cp": C is not None and bool(B.get("显示综合概率", True)) and cp_ok,
                 "score": bool(B.get("显示比分", True)), "basis": bool(B.get("显示依据", True))}
        rd, items = review_scope(hist, day)
        recap = CM.recap_from_hist(items) if rd else []
        data = CM.collect(day, cm_entries(wb, gen["picks"]), flags, draw_guard=DRAW_GUARD, cold_max=COLD_MAX,
                          has_model=(lambda p: C is not None and C.has_model(p)), recap=recap, max_matches=CM_MATCH_MAX)
        out = CM.compose(data, lib, seed=seed, per=CM_PER, watch_per=CM_WATCH_PER, max_len=CM_MAX_LEN, recap_n=CM_RECAP_N, bad=bad, emoji=bool(CM_EMOJI))
        return {"data": data, "out": out, "text": out["text"], "plain": out["plain"], "warns": warns, "n_match": out["n_match"], "n_line": out["n_line"],
                "opts": {"per": CM_PER, "watch_per": CM_WATCH_PER, "max_len": CM_MAX_LEN, "recap_n": CM_RECAP_N, "emoji": bool(CM_EMOJI)}}
    except Exception as exc:  # noqa: BLE001 —— 评论话术只是附带的东西，出任何问题都不能拖垮推单
        say(f"· 评论话术这一步出错了（{type(exc).__name__}: {exc}），已跳过，推单不受影响")
        return None


def ensure_lexicon_and_hot(folder: Path) -> bool:
    """第一次用时把词库和热词文件写出来（已有的不动）。返回这次有没有新建。"""
    if KW is None:
        return False
    a = bool(KW.ensure_lexicon_file(L.p(folder, KW.LEX_FILE)) == ["新建词库"])
    b = KW.ensure_hot_file(L.p(folder, KW.HOT_FILE))
    return a or b


# ════════════════════════════════════════════════════════════════════════════
# 10. 主流程
# ════════════════════════════════════════════════════════════════════════════
def detect_day(wb, path: Path, override: Optional[str]) -> str:
    if override:
        return override
    for name in ("竞足-今日未开赛", "竞篮-今日未开赛", "北单-今日未开赛", "传统足彩-在售期"):
        for r in wb.get(name, []):
            if re.match(r"\d{4}-\d{2}-\d{2}$", r.get("销售日", "") or ""):
                return r["销售日"]
    m = re.search(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else datetime.now(BJT).strftime("%Y-%m-%d")


def load_history(path: Path, log=None) -> Dict[str, Any]:
    """读历史。读不了（文件坏了）→ 先把坏文件留成 .bak，再从「历史备份」里找最近一份好的自动恢复；一份都没有才重新开始。"""
    def say(msg: str) -> None:
        if log:
            log(msg)
        else:
            print(msg, file=sys.stderr)

    path = Path(path)
    if path.exists():
        h: Any = None
        try:
            h = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            h = None
        if _history_ok(h):
            h.setdefault("runs", {})
            return h
        say(f"⚠ 历史文件 {path.name} 读不了，已留一份 .bak")
        try:
            path.replace(path.with_suffix(".bak"))
        except OSError:
            pass
        for b in list_backups(path):
            try:
                h = json.loads(b.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            if _history_ok(h):
                h.setdefault("runs", {})
                say(f"✅ 已从备份 {b.name} 自动恢复历史（{len(h['picks'])} 条推单）；备份之后新增的记录（最多是最近一次更新的）会缺")
                try:
                    atomic_write(path, json.dumps(h, ensure_ascii=False, indent=1))
                except OSError:
                    pass
                return h
        say("⚠ 没有可用的备份，历史只能重新开始")
    return {"version": 1, "picks": {}, "runs": {}}


def fetched_at(wb: Dict[str, List[Dict[str, str]]]) -> str:
    """表里「今日」那几张表的抓取时间（北京时间），界面用来提醒数据新不新。"""
    for name in ("北单-今日未开赛", "竞足-今日未开赛", "竞篮-今日未开赛", "传统足彩-在售期"):
        for r in wb.get(name, []):
            t = (r.get("抓取时间(北京时间)") or "").strip()
            if t:
                return t
    return ""


def validate_live_workbook(wb, expected_day, now=None, max_age_hours=6):
    """自动更新只接受有采集状态证明的当日数据；手动重生成仍可使用历史表。"""
    now = now or beijing_now()
    states = wb.get("采集状态", [])
    if not states:
        raise TipsError("缺少采集状态，不能确认数据完整性；请重新一键更新。")
    schedules = [r for r in states if expected_day in r.get("栏目", "") and "赛程" in r.get("栏目", "")]
    if not schedules:
        raise TipsError("没有今日销售日的赛程采集状态，已停止生成。")
    extra_live = [r for r in states if "北京单场 今日未开赛" in r.get("栏目", "")
                  or "传统足彩在售期" in r.get("栏目", "")]
    failed = [r for r in schedules + extra_live if r.get("状态", "").strip() not in ("成功", "无表格数据")]
    if failed:
        raise TipsError("今日关键赛程未更新：" + "；".join(r.get("栏目", "") + "：" + r.get("状态", "") for r in failed)
                        + "。请重试失败项。")
    for name in ("竞足-今日未开赛", "竞篮-今日未开赛", "北单-今日未开赛", "传统足彩-在售期"):
        for row in wb.get(name, []):
            stamp = row.get("抓取时间(北京时间)", "").strip()
            try:
                fetched = datetime.fromisoformat(stamp).replace(tzinfo=None)
            except (ValueError, TypeError):
                raise TipsError(f"{name} 有记录缺少有效抓取时间，已停止生成。")
            age = (now - fetched).total_seconds()
            if age > max_age_hours * 3600 or age < -300:
                raise TipsError(f"{name} 数据已过期或抓取时间异常（{stamp}），请更新后生成。")
    return True


def collect_issues(wb: Dict[str, List[Dict[str, str]]]) -> List[str]:
    """采集状态表里标为「失败」的栏目（不一定影响推单，但值得让人看到）。"""
    return [f"{r.get('栏目', '')}：{r.get('说明', '')}" for r in wb.get("采集状态", []) if (r.get("状态") or "").strip() in ("失败", "沿用旧数据")]


def open_game_keys(wb: Dict[str, List[Dict[str, str]]]) -> set:
    """这张表里「还没开赛」的场次，格式 (玩法, key)，和推单里的 (play, key) 对得上。"""
    keys = set()
    for r in wb.get("竞足-今日未开赛", []):
        keys.add(("竞足", r.get("赛事编号", "")))
    for r in wb.get("竞篮-今日未开赛", []):
        keys.add(("竞篮", r.get("赛事编号", "")))
    for r in wb.get("北单-今日未开赛", []):
        keys.add(("北单", f"{r.get('期号')}-{r.get('场次')}"))
    names = {"sfc": "胜负彩", "jq4": "4场进球", "zc6": "6场半全场"}
    for r in wb.get("传统足彩-在售期", []):
        g = game_kind(r.get("玩法", ""))
        if g:
            keys.add((names[g], f"{r.get('期号')}-{int(num(r.get('序号')) or 0)}"))
    return keys


def cleanup_for_regen(hist: Dict[str, Any], day: str, wb: Dict[str, List[Dict[str, str]]]) -> int:
    """同一天重新生成前，清掉当天「还没结算、而且比赛还没开」的旧推单（比如你刚把某队加进排除名单）。
    已经开赛的场次不动——它们的推单已经发出去了，明天还要结算；串关/任九每次按最新单场重算，所以一并重建。"""
    open_keys = open_game_keys(wb)
    drop = [pid for pid, p in hist["picks"].items()
            if p["date"] == day and p["status"] == "pending" and ("legs" in p or (p["play"], p["key"]) in open_keys)]
    for pid in drop:
        del hist["picks"][pid]
    return len(drop)


def pick_need(p: Dict[str, Any]) -> Tuple[Optional[str], int]:
    """这条推荐要哪一方赢、至少净胜几球：(home|away|None, 球数)。让球盘按让球线算（如 让球胜、主队-1 → 主队要净胜 2 球）。"""
    play, market, label = p.get("play"), p.get("market"), str(p.get("label", ""))
    if play in ("北单", "竞足") and market == "让球胜平负":
        try:
            L = float(str(p.get("line", "0")).replace("＋", "+").replace("－", "-") or 0)
        except ValueError:
            return None, 1
        if label.endswith("胜"):
            return "home", int(math.floor(-L)) + 1
        if label.endswith("负"):
            return "away", int(math.floor(L)) + 1
        return None, 1
    if play == "竞足" and market == "胜平负":
        return ("home", 1) if label == "胜" else ("away", 1) if label == "负" else (None, 1)
    if play == "竞篮" and market == "胜负":
        return ("home", 1) if label.startswith("主胜") else ("away", 1) if label.startswith("客胜") else (None, 1)
    if play == "胜负彩":
        return ("home", 1) if p.get("fav") == "3" else ("away", 1) if p.get("fav") == "0" else (None, 1)
    return None, 1


def enrich_match_leagues(matches, wb):
    """从同主客队、同开球时间的原始行找联赛，冲突时留空。"""
    for match in matches:
        if match.get("lg"):
            continue
        leagues = set()
        for rows in wb.values():
            for row in rows:
                if row.get("主队", "").strip() != match["home"] or row.get("客队", "").strip() != match["away"]:
                    continue
                dt = parse_dt(row.get("开赛时间(北京时间)", ""))
                if dt and dt.replace(tzinfo=None) == match["kick"].replace(tzinfo=None) and row.get("联赛"):
                    leagues.add(row["联赛"].strip())
        if len(leagues) == 1:
            match["lg"] = leagues.pop()


def collect_matches(picks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """从一批推荐里整理出「需要查两队数据的比赛」，按重要性排好序（先竞足/北单/竞篮，后传统足彩）。"""
    order: List[Tuple[str, str]] = []
    info: Dict[Tuple[str, str], Dict[str, Any]] = {}
    for p in picks:
        if "legs" in p or not p.get("home") or not p.get("away"):
            continue
        kick = parse_dt(p.get("kick") or "")
        if kick is None:
            continue
        k = (p["home"], p["away"])
        m = info.get(k)
        if m is None:
            m = info[k] = {"home": p["home"], "away": p["away"], "kick": kick.replace(tzinfo=BJT),
                           "sport": "basketball" if p["play"] == "竞篮" else "football", "side": None, "need": 1,
                           "line": p.get("line") if p["play"] == "竞篮" else None,
                           "total": p.get("total") if p["play"] == "竞篮" else None,
                           "lg": p.get("lg", ""), "_conflict": False}
            order.append(k)
        side, need = pick_need(p)
        if side:
            if m["side"] in (None, side) and not m["_conflict"]:
                m["side"], m["need"] = side, max(m["need"], need)
            else:
                m["side"], m["_conflict"] = None, True
    out = []
    for k in order:
        m = info[k]
        m.pop("_conflict", None)
        out.append(m)
    return out


def describe_pick(p: Dict[str, Any], picks: Dict[str, Dict[str, Any]]) -> Tuple[str, str, str, str]:
    """给界面用的一行描述：(类型, 场次, 对阵, 推荐)。"""
    if p["play"] == "任九":
        return ("任九", p.get("issue", ""), "任选九 单选9场", " ".join(f"{x['seq']}({x['label']})" for x in p["nine"]))
    if "legs" in p:
        names = []
        for i in p["legs"]:
            leg = picks.get(i)
            names.append(f"{leg.get('no') or leg.get('seq') or leg['key']}{leg['label']}" if leg else "（场次不在）")
        sp = f"（SP {p['sp']:.2f}）" if p.get("sp") else ""
        return ("串关", p["label"], "全部命中才算中", " + ".join(names) + sp)
    match = f"{p['home']}vs{p['away']}" if p.get("away") else p.get("home", "")
    note = f"（{p['note']}）" if p.get("note") else ""
    return (p["market"], str(p.get("no") or p.get("seq") or p["key"]), match, p["label"] + note)


def make_blocks(posts: List[Tuple[str, str]], limit: int) -> List[Dict[str, Any]]:
    blocks = []
    for name, text in posts:
        pieces = split_post(text, limit)
        for k, piece in enumerate(pieces, 1):
            blocks.append({"name": name, "k": k, "n": len(pieces), "text": piece, "weight": weight(piece)})
    return blocks


def basis_lines(picks: List[Dict[str, Any]]) -> List[str]:
    """每场推单的「两队数据对比」依据（干净版帖子里不放，存在文件末尾备查）。同一场只写一次。"""
    out: List[str] = []
    seen: set = set()
    for play in PLAY_ORDER:
        for p in picks:
            if p.get("play") != play or not p.get("cmp") or (p.get("home"), p.get("away")) in seen:
                continue
            seen.add((p.get("home"), p.get("away")))                 # 同一场出现在几个玩法里，依据一样，只写一次
            tag = str(p.get("no") or p.get("seq") or p.get("key") or "")
            cps = ""
            if isinstance(p.get("cp"), (int, float)):                            # 综合概率的三路来源（备查）
                cps = (f"｜综合{p['cp']:.0%}（赔率{p['cp_m']:.0%}" if isinstance(p.get("cp_m"), (int, float)) else f"｜综合{p['cp']:.0%}（")
                cps += (f"、模型{p['cp_q']:.0%}" if isinstance(p.get("cp_q"), (int, float)) else "、模型未参与") + f"、来源{p.get('cp_src', '')}" + ("、分歧" if p.get("cp_div") else "") + "）"
            out.append(f"{play} {tag} {p['home']}vs{p['away']}｜{CMP_MARK.get(p.get('cmp_v') or '', '')}{p['cmp']}{cps}")
    return out


def format_txt(res: Dict[str, Any]) -> str:
    """推单文案文件：前面是可以直接复制去发的帖子，最后才是「备查（不用发）」——运行提示和每场的数据依据。"""
    lim = res["limit"] if res["limit"] < DEFAULT_LIMIT else None
    parts = []
    for b in res["blocks"]:
        tag = b["name"] + (f" 第{b['k']}/{b['n']}条" if b["n"] > 1 else "")
        w = f"｜字数权重 {b['weight']}/{lim}" if lim else ""
        parts.append(f"======== {tag}{w} ========\n{b['text']}\n")
    out = "\n".join(parts)
    tips = list(res.get("notes") or []) + list(res["warnings"])
    basis = list(res.get("basis") or [])
    pre = list(res.get("preflight_lines") or [])
    dls = [r for r in (res.get("deadlines") or []) if r.get("text") and r.get("status") != "na"]
    drift = list(res.get("drift") or [])
    if tips or basis or pre or dls or drift:
        out += "\n######## 备查（以下不用发） ########\n"
        if pre:
            out += "【发帖前检查】\n" + "\n".join(pre) + "\n\n"
        if dls:
            out += "【建议发帖时间】\n" + "\n".join(f"· {r['post']}：{r['text']}" for r in dls) + "\n\n"
        if drift:
            out += "【临场变动（和上一次生成相比）】\n" + "\n".join("· " + d["text"] for d in drift) + "\n\n"
        if tips:
            out += "【运行提示】\n" + "\n".join("· " + w for w in tips) + "\n"
        if basis:
            out += "\n【每场推单的两队数据对比依据】（✓数据支持 △部分支持）\n" + "\n".join("· " + w for w in basis) + "\n"
    return out


def result_rows(wb: Dict[str, List[Dict[str, str]]]) -> List[Dict[str, Any]]:
    """昨日已开奖的足球比分（竞足、北单）→ 存进「自己的赛果库」用的行。"""
    rows: List[Dict[str, Any]] = []
    for sheet, col in (("竞足-昨日已开奖", "全场比分"), ("北单-昨日已开奖", "比分"), ("竞彩足球赛果", "全场比分")):   # 最后一张是 export 的 full 模式（补历史赛果）
        for r in wb.get(sheet, []):
            sc, k = parse_score(r.get(col, "")), (r.get("开赛时间(北京时间)") or "").strip()[:16]
            if sc and parse_dt(k) and r.get("主队") and r.get("客队"):
                rows.append({"k": k, "h": r["主队"].strip(), "a": r["客队"].strip(), "hs": sc[0], "as": sc[1], "lg": r.get("联赛", "")})
    return rows


def store_results(folder: Path, wbs: List[Dict[str, List[Dict[str, str]]]], say=None) -> int:
    """把赛果存进 results_db.json（脚本自己攒的近况数据）。第一次还会读文件夹里已有的旧表。出任何问题都不影响主流程。"""
    try:
        import sina_data as SD
        db = SD.ResultsDB(Path(folder))
        first = not db.path.exists()
        rows: List[Dict[str, Any]] = []
        for w in wbs:
            rows += result_rows(w)
        if first:
            for f in L.find_xlsx(folder)[-60:]:
                try:
                    rows += result_rows(read_workbook(f))
                except Exception:  # noqa: BLE001
                    continue
        n = db.add(rows)
        if n or first:
            db.save()
        if n and say:
            say(f"赛果库：新存 {n} 场比分（共 {len(db.rows)} 场）；攒够了，没有新浪文章的比赛也能自己算近况")
        if db.learned:
            db.save()
            if say:
                say(f"赛果库：同一场比赛在竞彩和完场页里写法不同，自动对上了 {db.learned} 个队名（记在 {SD.AUTO_ALIAS_FILE}，重复的比分已合并）")
        return n
    except Exception:  # noqa: BLE001
        return 0


HISTORY_DAYS = 30


def _bb_extra(res: Dict[str, Any], run, say) -> None:
    """足球完场页读完之后，顺带把篮球完场页的比分也存进篮球赛果库（竞篮的两队数据对比用）。篮球出任何问题都不影响足球。"""
    try:
        import bb_data as BB
    except Exception:  # noqa: BLE001
        return
    try:
        r = run(BB)
        res["bb"] = r
    except Exception as exc:  # noqa: BLE001
        if "已停止" in str(exc):
            raise
        say(f"  ⚠ 篮球比分这次没存成：{type(exc).__name__}: {exc}（不影响足球）")


def wanchang_history(folder: Path, days: int = HISTORY_DAYS, *, log=None, cancel=None, proxy: str = "") -> Dict[str, Any]:
    """补历史赛果（主办法）：读 500 网「完场」页，一页就是一个比赛日的全部比分（每天 200 多场，不只是竞彩），存进赛果库。
    每页间隔 2.5 秒左右，30 天约 1～2 分钟。返回 sina_data.wanchang_fill 的统计字典；不抛异常。"""
    import sina_data as SD
    say = log or (lambda m: None)
    days = max(1, min(60, int(days)))
    say(f"▶ 读 500 网完场页，补最近 {days} 天的全部比分（每页隔 {SD.WC_GAP:g} 秒，约 {max(1, round(days * (SD.WC_GAP + 1) / 60))} 分钟）")
    res = SD.wanchang_fill(Path(folder), days, log=say, cancel=cancel, proxy=proxy)
    _bb_extra(res, lambda BB: BB.lq_fill(Path(folder), BB.recent_labels(days), log=say, cancel=cancel, proxy=proxy), say)
    return res


def wanchang_daily(folder: Path, *, log=None, cancel=None, proxy: str = "") -> Dict[str, Any]:
    """每次更新时读 500 网完场页，存最近几个比赛日的全部比分（赛果库还很空时，第一次自动补 30 天）。不抛异常。"""
    import sina_data as SD
    res = SD.wanchang_daily(Path(folder), log=log, cancel=cancel, proxy=proxy)
    _bb_extra(res, lambda BB: BB.lq_daily(Path(folder), log=log, cancel=cancel, proxy=proxy), log or (lambda m: None))
    return res


def coverage_text(folder: Path, xlsx: Optional[Path] = None) -> str:
    """按赛果库算：最新数据表里今天的候选场次，有几场两队都有够用的近况。读不了就返回空串。"""
    try:
        import sina_data as SD
        xlsx = Path(xlsx) if xlsx else _newest_xlsx(Path(folder))
        if xlsx is None:
            return ""
        wb = read_workbook(xlsx)
        day = detect_day(wb, xlsx, None)
        need = collect_matches(generate(wb, day, Manual(), wide=True)["picks"])
        need = [m for m in need if m.get("sport") != "basketball"]
        if not need:
            return ""
        n_ok, total, miss = SD.db_coverage(Path(folder), need)
        txt = f"按 {xlsx.name} 里的 {total} 场足球候选算，有 {n_ok} 场两队在赛果库里都有 {SD.DB_MIN_FORM} 场以上近况"
        if miss:
            txt += f"；库里一场都没有的队：{'、'.join(miss[:8])}" + ("等" if len(miss) > 8 else "")
        return txt + "。"
    except Exception:  # noqa: BLE001
        return ""


def store_history(folder: Path, xlsx: Path, say=None) -> Tuple[int, int, int, str]:
    """补历史赛果：读 export_500_all.py --mode full 抓到的表，把「竞彩足球赛果」里已踢完的比分存进赛果库。
    返回 (表里读到几场, 新存几场, 库里共几场, 覆盖的日期范围文字)。"""
    import sina_data as SD
    wb = read_workbook(Path(xlsx))
    rows = result_rows(wb)
    db = SD.ResultsDB(Path(folder))
    n = db.add(rows)
    db.save()
    days = sorted({r["k"][:10] for r in rows})
    span = f"{days[0]} ～ {days[-1]}，其中 {len(days)} 天有比赛" if days else ""
    if say:
        say(f"赛果库：表里读到 {len(rows)} 场比分，新存 {n} 场，库里共 {len(db.rows)} 场" + (f"；覆盖 {span}" if span else ""))
    return len(rows), n, len(db.rows), span


def scraper_history(scraper: Path, out_dir: Path, days: int = HISTORY_DAYS, *, python: Optional[str] = None, log=None,
                    timeout: int = 1800) -> Optional[Path]:
    """命令行用：运行 export_500_all.py --mode full --days N，一次抓最近 N 个销售日的竞彩足球赛果，返回 xlsx 路径。"""
    import subprocess
    say = log or (lambda m: None)
    out = Path(out_dir) / f"历史赛果_{datetime.now(BJT):%Y-%m-%d}.xlsx"
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    cmd = [python or sys.executable, str(scraper), "--mode", "full", "--days", str(days), "--output", str(out), "--no-reuse-previous"]
    say(f"▶ 抓最近 {days} 天的竞彩足球赛果：{' '.join(cmd[1:])}（约 3～10 分钟）")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                           stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
    except (OSError, subprocess.TimeoutExpired) as exc:
        say(f"⚠ 运行采集脚本失败：{exc}")
        return None
    if r.returncode >= 2 or not out.exists():
        say(f"⚠ 抓历史赛果没成功（退出码 {r.returncode}）")
        return None
    return out


def run(xlsx: Path, history_path: Path, manual_path: Optional[Path] = None, *, limit: int = DEFAULT_LIMIT,
        settle_only: bool = False, fresh: bool = False, save: bool = True, day: Optional[str] = None,
        output: Any = None, log=None, backfill: Optional[Callable[[str], Optional[Path]]] = None,
        fill_results: Optional[Callable[[Callable[[str], None]], None]] = None, style: str = "media",
        team_data: Optional[Callable[[List[Dict[str, Any]], str], Tuple[List[Dict[str, Any]], List[str]]]] = None,
        market: Optional[Callable[[], Any]] = None, images: bool = False, browser: str = "",
        cancel: Optional[Callable[[], bool]] = None, now: Optional[datetime] = None, strict_live: bool = False,
        include_esports: bool = True, esports_proxy: str = "") -> Dict[str, Any]:
    """完整流程：读表 → 结算历史推单（漏了的日子自动补）→ 生成今日推单 → 渲染帖子 → 写文件/历史。命令行和桌面操作台都调用它。

    output    None 不写文本文件；"auto" 写到当前文件夹的 推单文案_日期.txt；给一个文件夹则写进该文件夹；给文件路径则写到该路径。
    fresh     同一天重新生成时，先清掉当天还没开赛的旧推单（见 cleanup_for_regen）。
    log       可选回调 log(str)，用来报告进度；出错抛 TipsError（消息可直接给用户看）。
    team_data 可选回调 team_data(matches, day) -> (notes, problems)：每次运行自动抓两队真实数据（见 team_data.py 的 Provider.notes_for）。
              给了它：先按赔率找出候选场次 → 抓数据 → 只推「有数据对比、且数据不反对」的场次；一场数据都没取到就不出推单。
    style     帖子样式。"media"（默认）：自媒体版——固定栏目风格（栏目头/热度榜勋章/战绩公示/串号/固定收尾），文字都在 brand.json 里改；
              "clean"：朴素版，可以直接发——只有推单本身，昨日复盘单独一篇放最后，两队数据对比放文件末尾的「备查」；
              "full"：每篇都带昨日复盘＋每场的两队数据对比（旧样式）。
    market    可选回调 market() -> market_data.Market：读澳客的竞足 SP 和各公司赔率（见 market_data.py、make_market）。给了它：
              竞足没配上北单的场次改用竞足自己的 SP 当参考；两队数据对比里补一句市场共识（市场很不看好推荐方就降级）。读不到只提示。
    fill_results 可选回调 fill_results(say)：存完昨日比分后调用，用来读 500 网完场页攒更多赛果（见 sina_data.wanchang_daily）；出错只提示、不影响推单。
    backfill  可选回调：给它一个日期 YYYY-MM-DD（相当于 export_500_all.py --date 的「今日」），它去采集并返回 xlsx 路径，
              失败返回 None；想中止整个流程就抛 TipsError。用来补结算「漏更新的那几天」的推单。
              不给也行：只会用文件夹里已有的 500网数据_日期.xlsx 来补。
    """
    say = log or (lambda m: None)
    laps = Laps()
    now = now or datetime.now(BJT).replace(tzinfo=None)                  # 北京时间（不带时区）：发帖前检查、建议发帖时间用
    xlsx, history_path = Path(xlsx), Path(history_path)
    use_aliases(xlsx.parent)                 # 竞足/北单配对时认「狼队＝伍尔弗汉普顿」这类别名
    rules_dir = history_path.parent
    if save and ensure_rules_file(rules_dir):
        say(f"已新建规则文件 {RULE_FILE}（里面是推多少场、排除联赛等设置，想改就改，不改就按默认）")
    elif LAST_RULE_UPGRADE:
        say("规则文件已升级（还是旧默认值的项换成新默认值，你自己改过的不动；新增项补上默认值）：" + "；".join(LAST_RULE_UPGRADE)
            + "。如果其中哪项你本来就是特意设的，把 rules.json 里那一项改回去就行。")
    rules_changed, rules_warns = apply_rules(rules_dir)
    for w_ in rules_warns:
        say("⚠ " + w_)
    if rules_changed:
        say("按你的规则文件运行：" + "；".join(rules_changed))
    try:
        wb = read_workbook(xlsx)
    except Exception as exc:  # noqa: BLE001
        raise TipsError(f"读不了 {xlsx.name}：{exc}") from exc
    laps.lap("读表")
    manual = Manual()
    if manual_path:
        try:
            manual = Manual(json.loads(Path(manual_path).read_text(encoding="utf-8")))
        except (OSError, ValueError, TypeError, AttributeError) as exc:
            raise TipsError(f"manual.json 读取失败：{exc}") from exc

    day = detect_day(wb, xlsx, day)
    if strict_live and not settle_only:
        expected_day = now.strftime("%Y-%m-%d")
        if day != expected_day:
            raise TipsError(f"数据销售日 {day} 与北京时间今日 {expected_day} 不一致，已停止生成。")
        validate_live_workbook(wb, expected_day, now=now)
    hist = load_history(history_path, say)
    changed = settle(hist, wb, day)
    settle_shadow(hist, wb, day)

    # 漏更新的日子：那天的推单要等「那天的第二天」的表才能结算，今天这张表够不着 → 用本地旧表，没有就补抓
    backfilled: List[str] = []
    failed: List[str] = []
    done_marks: Dict[str, str] = hist.setdefault("backfilled", {})
    extra_wbs: List[Dict[str, List[Dict[str, str]]]] = []
    for gd in gap_dates(hist, day):
        if gd in done_marks:
            continue
        nxt = _shift(gd, 1)
        src: Optional[Path] = None
        local = xlsx.parent / f"500网数据_{nxt}.xlsx"
        if local.exists() and local.resolve() != xlsx.resolve():
            src = local
            say(f"{md(gd)}的推单还没结算，用本地已有的 {local.name} 补结算")
        elif backfill is not None:
            say(f"{md(gd)}的推单还没结算（那天之后没更新过），补抓 {nxt} 的赛果……")
            try:
                src = backfill(nxt)
            except TipsError:
                raise
            except Exception as exc:  # noqa: BLE001
                say(f"⚠ 补抓 {nxt} 失败：{exc}")
        if src is None:
            failed.append(gd)
            if backfill is None and not local.exists():
                say(f"⚠ {md(gd)}的推单没法结算：没有 {local.name}，也没开补抓")
            continue
        try:
            wb2 = read_workbook(Path(src))
        except Exception as exc:  # noqa: BLE001
            say(f"⚠ 读不了补抓的表 {Path(src).name}：{exc}")
            failed.append(gd)
            continue
        n = settle(hist, wb2, day)
        settle_shadow(hist, wb2, day)
        extra_wbs.append(wb2)
        changed += n
        done_marks[gd] = datetime.now(BJT).strftime("%Y-%m-%d %H:%M")
        backfilled.append(gd)
        say(f"补结算 {md(gd)}：{n} 条")

    laps.lap("结算和补抓")
    if save:
        store_results(history_path.parent, [wb] + extra_wbs, say)
        if fill_results is not None:
            try:
                fill_results(say)
            except TipsError:
                raise
            except Exception as exc:  # noqa: BLE001
                say(f"⚠ 读 500 网完场页出错（不影响推单）：{exc}")
        changed += settle_local(hist, wb, day, history_path.parent, say)
    laps.lap("赛果库和完场页")
    settled_dates = sorted({p["date"] for p in hist["picks"].values() if p["status"] in ("hit", "miss") and p["date"] < day})
    settled_day = settled_dates[-1] if settled_dates else None
    notes = continuity_notes(hist, day, backfilled, failed)
    say(f"今日销售日 {day}｜本次结算 {changed} 条｜历史推单共 {len(hist['picks'])} 条")
    for n_ in notes:
        say(("" if n_.startswith("⚠") else "· ") + n_)
    res: Dict[str, Any] = {"day": day, "xlsx": xlsx.name, "settled": changed, "settled_day": settled_day, "limit": limit,
                           "yesterday": results_sentence(wb), "fetched_at": fetched_at(wb), "collect_issues": collect_issues(wb),
                           "notes": notes, "backfilled": backfilled, "unsettled_days": failed,
                           "warnings": [], "blocks": [], "picks": 0, "meta": {}, "txt": "",
                           "rules_changed": rules_changed, "rules_warns": rules_warns}
    if rules_warns:
        res["notes"] = list(res["notes"]) + ["⚠ 规则文件：" + w for w in rules_warns]
    try:
        if settle_only:
            prune(hist, day)
            if save:
                save_history(history_path, hist)
                write_stats_files(hist, day, history_path.parent)
            return res

        global COMP_W_USE
        COMP_W_USE = None
        if C is not None:                                      # 综合推单：模型占比（rules.json 里没改过，就按历史战绩每周校正一次；样本不够就是默认）
            try:
                if save:
                    fit_ = C.refit_and_save(rules_dir, hist, RULE_DEFAULTS["COMP_W_MDL"])
                    if fit_.get("changed") and fit_.get("reason"):
                        say("· 综合推单：" + fit_["reason"])
                COMP_W_USE, w_txt = C.load_weight(rules_dir, RULE_DEFAULTS["COMP_W_MDL"])
                say("· 综合推单：" + (f"模型占比 {COMP_W_MDL:.0%}（rules.json 里设的）" if abs(COMP_W_MDL - RULE_DEFAULTS["COMP_W_MDL"]) > 1e-12 else w_txt))
            except Exception as exc:  # noqa: BLE001 —— 只是综合概率的校正，出任何问题都用默认占比
                COMP_W_USE = None
                say(f"· 综合推单的占比校正没成功（{type(exc).__name__}: {exc}），用默认占比")
        mkt = None
        if market is not None:
            try:
                mkt = market()
            except Exception as exc:  # noqa: BLE001
                if "已停止" in str(exc):
                    raise TipsError("已停止。") from exc
                say(f"· 澳客的赔率这次没读成（{type(exc).__name__}: {exc}），不影响推单")
            if mkt is not None:
                for e in getattr(mkt, "errors", []):
                    if "已停止" in e:
                        raise TipsError("已停止。")
                    say("· " + e + "（不影响推单，只是少了这一层赔率参考）")
                if mkt:
                    say("· " + mkt.summary())
        laps.lap("澳客赔率")
        if team_data is not None:
            gen0 = generate(wb, day, manual, wide=True, market=mkt)
            need = [m for m in collect_matches(gen0["picks"]) if manual.note_for(m["home"], m["away"]) is None]
            enrich_match_leagues(need, wb)
            for m in need:
                m["mkt"] = gen0["meta"].get("mkt", {}).get(f"{m['home']}|{m['away']}")
            say(f"自动抓取两队数据：{len(need)} 场比赛……（读过的会缓存；第一次可能要几分钟）")
            try:
                auto, problems = team_data(need, day)
            except TipsError:
                raise
            except Exception as exc:  # noqa: BLE001
                if "已停止" in str(exc):                 # 用户自己点了停止，不用提示「关掉这个功能」
                    raise TipsError("已停止。") from exc
                raise TipsError(f"自动抓取两队数据失败：{exc}\n（暂时不想用这个功能：操作台「设置」里关掉「自动抓两队数据」；"
                                f"命令行就不要加 --team-data。）") from exc
            for pr in problems:
                say("· " + pr)
            if need and not auto:
                raise TipsError("一场两队数据都没取到，所以不出推单（没有数据对比就不推）。原因见上面的日志；"
                                "常见原因：接口来源——密钥没填对、免费套餐不含当前赛季；新浪来源——今天的文章还没发、网站改版；"
                                "共同的——队名叫法对不上（补进 team_alias.json / team_names.json）。")
            if mkt:
                try:
                    import market_data as MD
                    nchg = MD.annotate(auto, need, say)
                    if nchg:
                        say(f"· 市场共识让 {nchg} 场的数据结论降了级（推荐方向和各家公司的赔率对不上）")
                except Exception as exc:  # noqa: BLE001  市场这层出问题不能拖垮推单
                    say(f"· 市场共识这一步出错了（{type(exc).__name__}: {exc}），已跳过")
            manual.set_auto(auto, True)
            lack = [f"{m['home']}vs{m['away']}" for m in need if manual.note_for(m["home"], m["away"]) is None]
            lack = [x for x in lack if not any(x in pr for pr in problems)]       # 原因已经在上面逐条说过的，不重复
            if lack:
                say("· 这几场没取到两队数据，按规则不推：" + "、".join(lack))
                res["notes"] = list(res["notes"]) + ["这几场没取到两队数据（没有对应文章/额度不够/队名对不上），按规则不推：" + "、".join(lack)]
            label = getattr(getattr(team_data, "__self__", team_data), "source_text", None) or "接口自动抓取（API-Football/API-Basketball，api-sports.io）"
            res["notes"] = list(res["notes"]) + [f"两队数据来自{label}：本次 {len(auto)} 场；"
                                                 "规则见 team_data.py。查不到的内容一律不写。"] + [f"数据抓取：{x}" for x in problems]
        laps.lap("两队数据")
        gen = generate(wb, day, manual, market=mkt)
        res["drift"] = []
        if GD is not None:                                    # 临场变动：和同一天上一次生成时的赔率/让球线比
            try:
                res["drift"] = GD.odds_drift((hist.get("odds") or {}).get(day), gen["picks"], now, DRIFT_MIN_PCT)
                hist.setdefault("odds", {})[day] = GD.odds_snapshot(gen["picks"], now)
            except Exception:  # noqa: BLE001 —— 只是提醒，出任何问题都不影响出推单
                res["drift"] = []
            for d_ in res["drift"][:8]:
                say(("⛔ " if d_["level"] == "error" else "⚠ " if d_["level"] == "warn" else "· ") + "临场变动：" + d_["text"])
            hot = [d_["text"] for d_ in res["drift"] if d_["level"] in ("error", "warn")]
            if hot:
                res["notes"] = list(res["notes"]) + [f"⚠ 临场变动 {len(hot)} 处（和上一次生成相比）：" + hot[0] + (f"……另 {len(hot) - 1} 处见「推单文案」备查" if len(hot) > 1 else "")]
        if gen["meta"].get("mkt_fb"):
            msg = (f"竞足有 {len(gen['meta']['mkt_fb'])} 场没配上北单，改用澳客页上竞足自己的 SP 当参考赔率：" + "、".join(gen["meta"]["mkt_fb"][:6])
                   + ("等" if len(gen["meta"]["mkt_fb"]) > 6 else ""))
            say("· " + msg)
            res["notes"] = list(res["notes"]) + [msg]
            if gen["meta"].get("fb_diag"):
                say("  没配上北单的原因线索：" + "；".join(gen["meta"]["fb_diag"][:3]))
        if gen["meta"].get("weak_pairs"):
            learned = 0
            if _ALIAS is not None and gen["meta"].get("alias_pairs"):
                try:
                    learned = _ALIAS.learn(gen["meta"]["alias_pairs"])
                except Exception:  # noqa: BLE001  记不下来不影响出推单
                    learned = 0
            msg = ("竞足和北单有 " + str(len(gen["meta"]["weak_pairs"])) + " 场队名叫法差太多，但开球时间、联赛都一样且各自只此一场，当作同一场用北单赔率："
                   + "、".join(gen["meta"]["weak_pairs"][:4]))
            if learned:
                msg += f"；已记下 {learned} 个队名对应（存在 team_alias_auto.json，认错了就删掉那一行）"
            say("· " + msg)
            res["notes"] = list(res["notes"]) + [msg]
        res["notes"] = list(res["notes"]) + [play_summary(gen["picks"], bool(manual.auto_required or (manual.notes_on and manual.require_notes)))]
        if gen["meta"].get("jl_note"):
            say("· " + gen["meta"]["jl_note"])
            res["notes"] = list(res["notes"]) + [gen["meta"]["jl_note"]]
        if manual.notes_on and manual.match_notes:
            res["notes"] = list(res["notes"]) + [
                f"推单带了两队数据对比（manual.json 的 match_notes，共 {len(manual.match_notes)} 场）。这部分是手填的，换一天就要重新填（自动抓取的见 --team-data）。"
            ] + [f"数据来源：{s}" for s in manual.sources] + ["「前瞻」是网站编辑写的预测比分，只是一家之言；没查到的数据一律不写。"]
        # 同一天重跑：默认合并——新生成的覆盖同 id 的旧推单，已开赛场次（这次不会再出现）的旧推单保留，保证还能结算。
        # fresh：先清掉当天还没开赛的旧推单（改了排除名单/手动推荐后用），已开赛的仍保留。已结算的推单任何时候都不会被覆盖。
        if fresh:
            cleanup_for_regen(hist, day, wb)
        shadow_new: List[Dict[str, Any]] = []
        if manual.has_notes():                                 # 影子记账：把「被数据撤掉/没数据没推」的单场记下来，以后对赛果，检验把关有没有用
            shadow_new += shadow_picks(wb, day, manual, gen["picks"], market=mkt)
        gate_hit: List[Dict[str, Any]] = []
        if gates_active():                                     # 精选门槛挡下的单场：同样只记账
            seen_ = {p["id"] for p in shadow_new}
            gate_hit = [p for p in gate_shadow(wb, day, manual, gen["picks"], market=mkt) if p["id"] not in seen_]
            shadow_new += gate_hit
        if manual.has_notes() or shadow_new:
            sh = hist.setdefault("shadow", {})
            for sid in [i for i, p in sh.items() if p.get("date") == day and p.get("status") == "pending"]:
                del sh[sid]                                    # 今天重新生成：先清掉今天还没出结果的旧影子（现在可能已经推了）
            kept = {p["id"] for p in gen["picks"]}
            for p in shadow_new:
                if p["id"] not in kept and (p["id"] not in sh or sh[p["id"]].get("status") == "pending"):
                    sh[p["id"]] = p
        if gate_hit:
            names_ = list(dict.fromkeys(f"{p['home']}vs{p['away']}" for p in gate_hit))
            msg = (f"精选门槛今天挡下了 {len(names_)} 场单场（把握不够，或两队数据只是部分支持）：" + "、".join(names_[:6]) + ("等" if len(names_) > 6 else "")
                   + "。脚本会记账，之后看挡下的是不是真的更容易不中。")
            say("· " + msg)
            res["notes"] = list(res["notes"]) + [msg]
        if gen["meta"].get("zc_off"):
            msg = ("、".join(gen["meta"]["zc_off"]) + "：命中概率本来就低，按规则没推（想推：在 rules.json 里把「"
                   + "」「".join(("出任九" if x == "任九" else "出" + x) for x in gen["meta"]["zc_off"]) + "」改成 1）。")
            say("· " + msg)
            res["notes"] = list(res["notes"]) + [msg]
        for p in gen["picks"]:
            old = hist["picks"].get(p["id"])
            if old is not None and old.get("status") != "pending":
                continue
            hist["picks"][p["id"]] = p

        fstats, ftxt = filter_stats(hist)
        res["filter_stats"] = ftxt
        if ftxt:
            res["notes"] = list(res["notes"]) + [ftxt]
        brand = load_brand(Path(history_path).parent)
        if style == "media" and brand.get("朴素版"):
            style = "clean"
        if style == "media" and save and ensure_brand_file(Path(history_path).parent):
            res["notes"] = list(res["notes"]) + [f"已生成 {BRAND_FILE}（帖子的栏目名、口号、话题标签等固定风格都在里面，改了文字再点一次「一键更新」就生效）"]
            say(f"· 已生成 {BRAND_FILE}：帖子的栏目名、口号、话题标签等固定风格都在里面，想改就改")
        if style == "media" and save:
            added = brand_add_missing(Path(history_path).parent)
            if added:
                res["notes"] = list(res["notes"]) + [f"{BRAND_FILE} 新增了设置项：{'、'.join(added)}（用的默认值，想改就改）"]
                say(f"· {BRAND_FILE} 新增了设置项：{'、'.join(added)}")
        laps.lap("生成推单")
        posts = render(gen, day, wb, hist, settled_day, style, brand)
        # 电竞单独收集和渲染，不混入足球/篮球结算、赔率或命中率。
        res["esports"] = None
        if include_esports and ES is not None:
            try:
                esports = ES.build(history_path.parent, day, now=now, proxy=esports_proxy,
                                   cancel=cancel, log=say, write=save)
                if cancel and cancel():
                    raise TipsError("已停止。")
                res["esports"] = esports
                if esports.get("enabled") and esports.get("text"):
                    posts.append(("电竞预测", esports["text"]))
                    res["notes"] = list(res.get("notes") or []) + list(esports.get("notes") or [])
            except TipsError:
                raise
            except Exception as exc:
                if cancel and cancel():
                    raise TipsError("已停止。")
                say("· 电竞预测未生成（" + type(exc).__name__ + "），其他推单继续。")
        elif include_esports:
            say("· 缺少电竞模块 esports_data.py，本次不生成电竞预测。")

        res.update(blocks=make_blocks(posts, limit), warnings=gen["warnings"], picks=len(gen["picks"]), meta=gen["meta"],
                   basis=basis_lines(gen["picks"]) if style != "full" else [], style=style,
                   posts=[{"name": n, "text": t} for n, t in posts])
        laps.lap("排版")
        res["keywords"] = make_keywords(wb, gen, day, history_path.parent, say, create=save)
        if res["keywords"]:
            laps.lap("今日关键词")
        res["comments"] = make_comments(wb, gen, day, history_path.parent, say, hist, brand, create=save)
        if res["comments"]:
            laps.lap("评论话术")
        prev_posts = (hist["runs"].get(day) or {}).get("posts")
        guard_picks = list(gen["picks"])
        for e in (res.get("esports") or {}).get("picks", []):
            if all(k in e for k in ("home", "away", "kick")):
                guard_picks.append({"play":"电竞", "market":"系列赛", "key":"|".join(str(e.get(k, "")) for k in ("game", "home", "away", "kick")),
                                    "home":e["home"], "away":e["away"], "kick":e["kick"]})
        res["preflight"], res["deadlines"], res["preflight_lines"] = [], [], []
        if GD is not None:                                    # 发帖前自检 + 建议发帖时间
            try:
                pf = GD.preflight(posts, guard_picks, now, fetched=res["fetched_at"], limit=limit, prev_posts=prev_posts,
                                  weight=weight, splitter=split_post)
                res["preflight"], res["preflight_lines"] = pf, GD.issue_lines(pf)
                dl_ = GD.deadlines(posts, guard_picks, gen["meta"], now, POST_LEAD_MIN)
                res["deadlines"] = GD.deadlines_json(dl_)
            except Exception as exc_:  # noqa: BLE001
                say(f"· 发帖前检查这一步出错了（{type(exc_).__name__}: {exc_}），已跳过")
            for l_ in res["preflight_lines"]:
                if not l_.startswith("ℹ"):
                    say(l_)
        # 把今天发出去的推文原文也存进历史：明天复盘时对得上、也能随时在「昨日复盘」页翻出来看
        hist["runs"][day] = {"generated_at": datetime.now(BJT).strftime("%Y-%m-%d %H:%M"), "source": xlsx.name,
                             "count": len(gen["picks"]), "limit": limit, "posts": [{"name": n, "text": t} for n, t in posts]}
        prune(hist, day)
        out: Optional[Path] = None
        if output is not None:
            name_ = f"推单文案_{day}.txt"
            if output == "auto":
                out = L.p(history_path.parent, name_) if L.is_organized(history_path.parent) else Path(name_)
            else:
                out = Path(output)
                if out.is_dir():
                    out = L.p(out, name_)               # 整理后的结构：放进「推单」文件夹；旧结构：就在这个文件夹里
            exports = {}
            res["txt"] = str(out)
            if res.get("keywords"):
                kwp = out.with_name(f"热搜关键词_{day}.txt")
                exports[kwp] = res["keywords"]["text"]
                res["kw_txt"] = str(kwp)
            if res.get("comments"):
                cmp_ = out.with_name(f"评论话术_{day}.txt")
                exports[cmp_] = res["comments"]["plain"]
                res["cm_txt"] = str(cmp_)
            esports = res.get("esports") or {}
            if esports.get("enabled") and esports.get("text"):
                ep = out.with_name(f"电竞推单_{day}.txt")
                exports[ep] = esports["text"]
                exports[L.d(history_path.parent, L.REP) / f"电竞预测来源_{day}.json"] = json.dumps(esports, ensure_ascii=False, indent=1)
                exports[L.d(history_path.parent, L.REP) / f"电竞逐场诊断_{day}.txt"] = ES.diagnostics_text(esports)
                refs = esports.get("references") or {}
                if refs.get("enabled"):
                    exports[L.d(history_path.parent, L.REP) / f"电竞参考报告_{day}.txt"] = refs["summary"]
                res["esports_txt"] = str(ep)
            if save:
                rotate_backup(history_path)
                exports[history_path] = json.dumps(hist, ensure_ascii=False, indent=1)
            exports[out] = format_txt(res)
            res["batch_id"] = atomic_batch(exports, out.with_name(f"导出批次_{day}.json"))
        elif save:
            save_history(history_path, hist)
        if save:
            sp_ = write_stats_files(hist, day, history_path.parent)
            if sp_:
                res["stats_txt"] = str(sp_)
    except OSError as exc:
        raise TipsError(f"写文件失败：{exc}（文件是不是被别的程序占用了？）") from exc
    laps.lap("发帖前检查和写文件")
    for w in gen["warnings"]:
        say("⚠ " + w)
    head = f"已写出 {out}（{len(posts)} 组帖子，推单 {len(gen['picks'])} 条）" if out else f"已生成 {len(posts)} 组帖子，推单 {len(gen['picks'])} 条"
    say(head + (f"；历史已更新 {history_path}" if save else ""))
    if images and posts:
        say("▶ 生成图片快照（浏览器在后台截图，不会弹窗，约 20～40 秒）…")
        r = make_snapshots(posts, Path(history_path).parent, day, brand, log=say, browser=browser, cancel=cancel)
        res["images"] = r
        if r["files"]:
            note = f"图片快照 {len(r['files'])} 张已存到 {r['dir']}（{len(posts)} 条帖子；太长的拆成了「图1、图2」）"
            res["notes"] = list(res["notes"]) + [note]
            say("· " + note)
        if r["error"]:
            res["notes"] = list(res["notes"]) + ["⚠ 图片快照：" + r["error"]]
            say("⚠ 图片快照：" + r["error"])
        laps.lap("图片快照")
    res["timing"] = [(n, round(d, 2)) for n, d in laps.items]
    say("⏱ 用时：" + laps.text())
    return res


def module_versions(folder: Path) -> Dict[str, str]:
    """脚本文件夹里各个文件的版本号（读文件里的 __version__ = "x"，不执行它们）。"""
    out: Dict[str, str] = {"gen_tips": __version__}
    pd_ = L.prog_dir(folder)
    for f in sorted(list(pd_.glob("*.py")) + list(pd_.glob("*.pyw"))):
        if f.stem == "gen_tips":
            continue
        try:
            m = re.search(r'^[ \t]*__version__[ \t]*=[ \t]*([\'"])([^\'"\r\n]+)\1', f.read_text(encoding="utf-8-sig", errors="replace")[:20000], re.M)
        except OSError:
            continue
        if m:
            out[f.stem] = m.group(2)
    return out


DIAG_FILE = "诊断报告.txt"


def write_diagnostics(folder: Path, log_tail: Optional[List[str]] = None, browser: str = "") -> Optional[Path]:
    """一键诊断包：把排查问题要看的信息写成 诊断报告.txt（密钥已打码）。返回路径；写不了返回 None。"""
    if GD is None:
        return None
    folder = Path(folder)
    try:
        def _br() -> Optional[str]:
            import snapshot as SN
            return SN.find_browser(browser)
        txt = GD.diagnostics(folder, versions=module_versions(folder), log_tail=log_tail, browser=_br, now=datetime.now())
        out = L.p(folder, DIAG_FILE)
        atomic_write(out, txt)
        return out
    except Exception:  # noqa: BLE001
        return None


def make_snapshots(posts: List[Tuple[str, str]], folder: Path, day: str, brand: Optional[Dict[str, Any]] = None,
                   log: Optional[Callable[[str], None]] = None, browser: str = "",
                   cancel: Optional[Callable[[], bool]] = None) -> Dict[str, Any]:
    """给每条帖子做一张图片（PNG），存进 folder/推单图片_日期。靠 snapshot.py + 电脑自带的 Edge/Chrome；任何问题都只写进 error，不抛异常。"""
    try:
        import snapshot as SN
    except ImportError:
        return {"files": [], "html": None, "dir": "", "browser": "", "error": "缺少 snapshot.py（要和 gen_tips.py 放在同一个文件夹）。"}
    out = L.p(folder, SN.IMG_DIR_FMT.format(day=day))
    try:
        return SN.make_images(list(posts), out, B=brand or load_brand(None), browser=browser, log=log or (lambda s: None), cancel=cancel)
    except Exception as exc:  # noqa: BLE001 —— 图片只是加分项，绝不拖垮出推单
        return {"files": [], "html": None, "dir": str(out), "browser": "", "error": f"做图时出错：{exc}"}


def play_summary(picks: List[Dict[str, Any]], gated: bool) -> str:
    """一句话说清今天每种玩法各推了几条；单场玩法是 0 条时说明原因，免得以为是出了故障。"""
    cnt: Dict[str, int] = {}
    for p in picks:
        cnt[p.get("play", "")] = cnt.get(p.get("play", ""), 0) + 1
    parts = [f"{n} {cnt[n]}" for n in PLAY_ORDER if cnt.get(n)]
    text = "今天各玩法推单：" + ("｜".join(parts) if parts else "一条都没有")
    zero = [n for n in SINGLE_PLAYS if not cnt.get(n)]
    if zero:
        text += f"。{'、'.join(zero)} 的单场是 0 条"
        text += ("：有数据对比才推，没取到两队数据（或竞足没配上北单赔率）的场次按规则不推，原因见上面几行；赛果库攒得越久，能出的场次越多"
                 if gated else "：当天表里没有符合条件的场次")
    return text


def _newest_xlsx(folder: Path) -> Optional[Path]:
    """文件夹里日期最新的 500网数据_日期.xlsx（按文件名里的日期，不看修改时间——补抓的旧表不会被误认成最新）。"""
    found = L.find_xlsx(folder)
    return max(found, key=lambda p: (re.search(r"\d{4}-\d{2}-\d{2}", p.name).group(), p.stat().st_mtime), default=None)


def scraper_backfill(scraper: Path, out_dir: Path, *, python: Optional[str] = None, log=None, timeout: int = 900
                     ) -> Callable[[str], Optional[Path]]:
    """命令行用的补抓回调：运行 export_500_all.py --date 日期 --output 文件夹/500网数据_日期.xlsx。"""
    import subprocess

    def fetch(d: str) -> Optional[Path]:
        say = log or (lambda m: None)
        out = out_dir / f"500网数据_{d}.xlsx"
        out_dir.mkdir(parents=True, exist_ok=True)
        if out.exists():
            out.unlink()                 # 不让它「沿用上次」的旧内容
        cmd = [python or sys.executable, str(scraper), "--date", d, "--output", str(out), "--keep-older-draws", "--no-reuse-previous"]
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                               stdin=subprocess.DEVNULL, env=dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1"))
        except (OSError, subprocess.TimeoutExpired) as exc:
            say(f"⚠ 运行采集脚本失败：{exc}")
            return None
        if r.returncode >= 2 or not out.exists():
            say(f"⚠ 采集 {d} 没成功（退出码 {r.returncode}）")
            return None
        return out

    return fetch


def make_team_data(folder: Path, key: str = "", *, log=None, cancel=None, proxy: str = "", max_requests: Optional[int] = None,
                   source: str = "auto"):
    """造「自动抓两队数据」的回调（给 run(team_data=…)）。
    source：sina 新浪彩票公开文章（免费，不要密钥）｜api API-Football 接口（要密钥）｜both 新浪优先、没有的用接口补｜
            auto 填了密钥就是 both，没填就是 sina。密钥来源：key 参数 > 环境变量 API_FOOTBALL_KEY > folder 里的 api_key.txt。"""
    folder = Path(folder)
    src = (source or "auto").lower()
    if src not in ("auto", "sina", "api", "both"):
        raise TipsError(f"数据来源只能是 sina / api / both / auto，不能是 {source!r}")
    k = ""
    if src != "sina":
        try:
            import team_data as T            # 和本文件放在同一个文件夹
        except ImportError as exc:
            raise TipsError("找不到 team_data.py（它要和 gen_tips.py 放在同一个文件夹）") from exc
        k = T.load_key(folder, key)
    if src == "auto":
        src = "both" if k else "sina"
    if src == "api" and not k:
        raise TipsError("数据来源选了「接口」，需要先填接口密钥：到 https://dashboard.api-football.com/register 免费注册，"
                        "把密钥填进操作台「设置」，或存进 api_key.txt（命令行用法）。想不用密钥就改选「新浪」。")
    api = None
    if k:
        import team_data as T                # noqa: F811
        api = T.Provider(k, L.p(folder, "data_cache"), max_requests=max_requests, log=log, cancel=cancel, proxy=proxy)
    if src == "api":
        return api.notes_for
    try:
        import sina_data as SD
    except ImportError as exc:
        raise TipsError("找不到 sina_data.py（它要和 gen_tips.py 放在同一个文件夹）") from exc
    sina = SD.SinaProvider(folder, log=log, cancel=cancel, proxy=proxy)
    if src == "both" and api is not None:
        return SD.ChainProvider(sina, api.notes_for, log=log)
    return sina


def make_market(folder: Path, *, log=None, cancel=None, proxy: str = ""):
    """造「读澳客赔率」的回调（给 run(market=…)）。读不到只会返回空的结果，不抛异常。"""
    def go():
        import market_data as MD                       # 和本文件放在同一个文件夹；缺了就当没有这一层
        return MD.fetch(Path(folder), log=log, cancel=cancel, proxy=proxy)
    return go


def check_data(folder: Path, key: str = "", source: str = "auto", *, log=None, cancel=None, proxy: str = "") -> List[str]:
    """「测试连接」：返回要给用户看的几行。新浪（免费）和接口（要密钥）各测各的，按 source 决定测哪个。"""
    folder = Path(folder)
    src = (source or "auto").lower()
    lines: List[str] = []
    k = ""
    try:
        import team_data as T
        k = T.load_key(folder, key)
    except ImportError:
        T = None  # type: ignore[assignment]
    if src == "auto":
        src = "both" if k else "sina"
    if src in ("sina", "both"):
        try:
            import sina_data as SD
            lines.append("【新浪彩票（免费，不要密钥）】")
            lines += SD.SinaProvider(folder, log=log, cancel=cancel, proxy=proxy).check()
        except ImportError:
            lines.append("找不到 sina_data.py（它要和 gen_tips.py 放在同一个文件夹）")
    if src in ("api", "both"):
        lines.append("【接口 API-Football（要密钥）】")
        if T is None:
            lines.append("找不到 team_data.py（它要和 gen_tips.py 放在同一个文件夹）")
        elif not k:
            lines.append("没有填接口密钥（只用新浪的话可以不填）。")
        else:
            lines += T.Provider(k, L.p(folder, "data_cache"), log=log, cancel=cancel, proxy=proxy).check()
    return lines


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="读取 500 网 xlsx，结算昨日推单并生成今日 X 推单文案")
    ap.add_argument("xlsx", type=Path, nargs="?", help="export_500_all.py 导出的 xlsx；不写则取当前文件夹里最新的 500网数据_*.xlsx")
    ap.add_argument("--history", type=Path, default=None, help="历史推单文件，默认脚本文件夹里的 tips_history.json（整理后在「数据库」文件夹）")
    ap.add_argument("--manual", type=Path, help="人工修正 manual.json（可选）")
    ap.add_argument("--output", type=Path, help="文案输出路径，默认 推单文案_日期.txt")
    ap.add_argument("--date", help="指定今日销售日 YYYY-MM-DD，默认取表里的销售日")
    ap.add_argument("--limit", type=int, default=DEFAULT_LIMIT, help="单帖字数上限（权重），普通账号用 280 会自动拆成串")
    ap.add_argument("--settle-only", action="store_true", help="只结算，不生成今日推单")
    ap.add_argument("--no-save", action="store_true", help="不写历史文件（试跑）")
    ap.add_argument("--fresh", action="store_true", help="同一天重跑时，先清掉当天还没开赛的旧推单再写入（已开赛的保留）")
    ap.add_argument("--backfill", action="store_true",
                    help="漏更新了某天时，自动调用同目录的 export_500_all.py 补抓那天的赛果来结算（没开这个就只用文件夹里已有的旧表）")
    ap.add_argument("--team-data", action="store_true",
                    help="每次运行自动抓两队真实数据（近况/伤停/交锋）并和推单方向对比；默认读新浪彩票公开文章（免费，不要密钥，见 sina_data.py）")
    ap.add_argument("--source", choices=("auto", "sina", "api", "both"), default="auto",
                    help="两队数据来源：sina 新浪（免费）｜api 接口（要密钥，见 team_data.py）｜both 新浪优先接口补漏｜auto 有密钥就 both、没有就 sina（默认）")
    ap.add_argument("--api-key", default="", help="接口密钥；不写则读环境变量 API_FOOTBALL_KEY 或同目录 api_key.txt")
    ap.add_argument("--max-requests", type=int, default=None, help="一次运行最多发多少次接口请求（不写：免费版 90 次，付费套餐自动放宽）")
    ap.add_argument("--check-data", action="store_true", help="只测试两队数据接口能不能用，不生成推单")
    ap.add_argument("--history-days", type=int, default=0, metavar="N",
                    help=f"补历史赛果：读 500 网完场页，补最近 N 天（1～31，建议 {HISTORY_DAYS}）的全部比分存进赛果库（results_db.json），然后退出；"
                         "读不到完场页时改用 export_500_all.py 抓竞彩赛果。没有新浪文章的比赛靠它算近况。一次就行，之后每天自动攒")
    ap.add_argument("--wanchang", action="store_true",
                    help="结算/生成之前，先读 500 网完场页存最近几天的全部比分（操作台默认就是这样；命令行要写这个开关）")
    ap.add_argument("--market", action="store_true",
                    help="生成推单前读澳客（okooo.cn）的竞足 SP 和各公司赔率（见 market_data.py）：竞足没配上北单的场次用竞足自己的 SP，"
                         "两队数据对比里补市场共识。操作台默认就是这样；命令行要写这个开关")
    ap.add_argument("--full-posts", action="store_true",
                    help="帖子用旧样式：每篇带昨日复盘＋每场两队数据对比（默认是干净版：只有推单，复盘单独一篇，对比放文件末尾备查）")
    ap.add_argument("--fetch", action="store_true", help="先运行 export_500_all.py --keep-older-draws 抓取今天的数据（命令行版的「一键更新」第一步，run_daily.bat 用它）")
    ap.add_argument("--diagnose", action="store_true", help="生成 诊断报告.txt（版本、设置、文件清单、历史概况、错误日志；密钥已打码），遇到问题把它发给我")
    ap.add_argument("--stats", action="store_true", help="只更新并显示 战绩统计.txt（分玩法/近7日/近30日命中率、连红连黑、各类检验）")
    ap.add_argument("--images", action="store_true", help="生成推单后，再给每条帖子做一张图片快照（推单图片_日期 文件夹，需要电脑里有 Edge 或 Chrome）")
    ap.add_argument("--no-esports", action="store_true", help="本次不生成电竞预测（默认读取电竞设置.json）")
    ap.add_argument("--version", action="version", version=__version__)
    args = ap.parse_args(argv)

    for stream in (sys.stdout, sys.stderr):      # Windows 重定向/老控制台是 GBK，遇到 ⚠ 等符号会报错，改成无法显示就替换
        try:
            stream.reconfigure(errors="replace")
        except (AttributeError, ValueError):
            pass
    here = L.app_root(__file__)
    L.migrate(here, print)                       # 整理后的结构：把根目录里散着的旧文件归进分类文件夹（只移动，不删除）
    if args.history is None:
        args.history = L.p(here, "tips_history.json")
    if args.diagnose:
        p_ = write_diagnostics(here)
        print(f"已生成 {p_}" if p_ else "诊断报告没生成成功（缺 guard.py 或文件夹不能写）")
        return 0 if p_ else 2
    if args.stats:
        if ST is None:
            print("缺少 stats.py（要和 gen_tips.py 放在同一个文件夹）", file=sys.stderr)
            return 2
        hist_ = load_history(Path(args.history), print)
        today_ = datetime.now(BJT).strftime("%Y-%m-%d")
        sp_ = write_stats_files(hist_, today_, here)
        print(ST.report_text(ST.compute(hist_, today_, DRAW_GUARD)))
        print(f"已更新 {sp_}" if sp_ else "")
        return 0
    if args.check_data:
        for line in check_data(here, args.api_key, args.source, log=print):
            print(line)
        return 0
    if args.history_days:
        nd = max(1, min(31, args.history_days))
        res = wanchang_history(here, nd, log=print)
        if res["ok"] or res["skipped"]:
            print(f"赛果库：读了 {res['ok']} 页，新存 {res['added']} 场" + (f"，另有 {res['skipped']} 天之前补过、跳过" if res["skipped"] else "")
                  + f"，共 {res['total']} 场" + (f"（{res['span']}）" if res["span"] else ""))
            cov = coverage_text(here)
            if cov:
                print(cov)
            return 0
        print("⚠ 完场页没读成" + (f"：{res['errors'][0]}" if res["errors"] else "") + "，改用旧办法（抓竞彩赛果）")
        scraper = L.prog_dir(here) / "export_500_all.py"
        if not scraper.exists():
            print("找不到 export_500_all.py（它要和 gen_tips.py 放在同一个文件夹）", file=sys.stderr)
            return 2
        got = scraper_history(scraper, L.p(here, "backfill"), nd, log=print)
        if got is None:
            return 2
        try:
            store_history(here, got, say=print)
        except Exception as exc:  # noqa: BLE001
            print(f"没能把赛果存进赛果库：{exc}", file=sys.stderr)
            return 2
        return 0
    if args.fetch:
        import subprocess
        scraper_ = L.prog_dir(here) / "export_500_all.py"
        if not scraper_.exists():
            print("找不到 export_500_all.py（它要和 gen_tips.py 放在同一个文件夹）", file=sys.stderr)
            return 2
        print("▶ 开始抓取：export_500_all.py --keep-older-draws")
        try:
            rc_ = subprocess.run([sys.executable, str(scraper_), "--keep-older-draws"], cwd=str(L.d(here, L.DAY)), stdin=subprocess.DEVNULL).returncode
        except OSError as exc:
            print(f"没能启动抓取脚本：{exc}", file=sys.stderr)
            return 2
        if rc_ >= 2:
            print("抓取失败，已停止。检查网络/代理后再运行；想先用旧数据，把命令里的 --fetch 去掉。", file=sys.stderr)
            return 2
    if args.xlsx is None:
        args.xlsx = _newest_xlsx(here) or _newest_xlsx(Path.cwd())
        if args.xlsx is None:
            print("当前文件夹里没有 500网数据_*.xlsx，请先运行 export_500_all.py，或把 xlsx 文件名写在命令后面", file=sys.stderr)
            return 2
        print(f"使用最新的表：{args.xlsx.name}")
    cb = None
    if args.backfill:
        scraper = Path(__file__).resolve().parent / "export_500_all.py"
        if scraper.exists():
            cb = scraper_backfill(scraper, L.p(here, "backfill"), log=print)
        else:
            print("⚠ 找不到 export_500_all.py，没法补抓（它要和 gen_tips.py 放在同一个文件夹）", file=sys.stderr)
    try:
        td = make_team_data(here, args.api_key, log=print, max_requests=args.max_requests, source=args.source) if args.team_data and not args.settle_only else None
        fill = None
        if args.wanchang:
            def fill(say):
                wanchang_daily(here, log=say)
        run(args.xlsx, args.history, args.manual, limit=args.limit, settle_only=args.settle_only, fresh=args.fresh,
            save=not args.no_save, day=args.date, strict_live=bool(args.fetch and not args.date), output=None if args.settle_only else (args.output or "auto"), log=print, backfill=cb,
            fill_results=fill, team_data=td, style="full" if args.full_posts else "media",
            market=make_market(here, log=print) if args.market and not args.settle_only else None,
            images=bool(args.images) and not args.settle_only, include_esports=not args.no_esports)
    except TipsError as exc:
        print(exc, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
