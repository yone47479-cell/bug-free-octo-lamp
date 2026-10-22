#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""免费的「两队数据」来源：新浪彩票的公开文章 + 自己攒的赛果库（只用 Python 3.9+ 标准库）。

和 team_data.py（API-Football 接口，要密钥）并列，二选一或一起用，都从 gen_tips.make_team_data 接进推单流程。

读什么（都是新浪体育/彩票网站上谁都能看的文章，没有账号、没有密钥）：
  * 「[小炮APP]竞彩情报」：一场比赛一篇，写了两队近 10 场战绩、主客场战绩、场均进失球、连胜连败、伤停；
  * 「足彩伤停」：每期 14 场，列出每队的伤病、停赛球员和「主力」标记；
  * 「交战记录」：每期 14 场，两队近 10 年交手几次、各胜几场。
  * 自己攒的赛果库 results_db.json：每次运行把 500 网「昨日已开奖」的比分存起来，时间一长，
    就能自己算出两队近况（新浪没有这场文章时用它补）。
然后用和 team_data.py 同一套透明规则（见 team_data.judge）和推单方向比一比：support 支持 / mixed 部分支持 / against 反对。

规矩（写在代码里、不会绕开）：
  * 先读 robots.txt，不让读的地址不读；带「?」参数的地址一律不读（新浪彩票的 robots 明确禁止 /*?*）。
  * 只读 sina.com.cn / sina.cn 下的普通文章页；每次最多读 60 个网页，每页之间隔 0.7 秒以上；读过的缓存，不重复读。
  * 只摘「数字事实」（几胜几平几负、缺几人……）写进推单；不抄文章原文，也不抄编辑写的预测和推荐。
  * 读不到、认不出的内容一律不写、不编；没数据的场次按规则不推。
  * 文章是自由文字，不是规整的数据表：认字靠规则，难免有漏读和错读。第一次在你电脑上跑，
    如果「读到了文章但没认出内容」，会把读到的文字存进 sina_debug 文件夹，把那个文件发给我就能改规则。

单独测试：  python sina_data.py --check
"""

from __future__ import annotations

import argparse
import hashlib
import html as htmllib
import json
import math
import random
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as L
from reliability import atomic_write_text
import team_data as T

try:                                   # 数据模型（用自己的赛果库算）：缺这个文件也不影响其他功能
    import match_model as MM
except ImportError:                    # pragma: no cover
    MM = None
try:
    import bb_data as BB
except Exception:  # noqa: BLE001  篮球模块缺了不影响足球
    BB = None

__version__ = "1.3"

BJT = timezone(timedelta(hours=8))
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36 tips-script/1.5"
INDEX_URLS = (
    "https://sports.sina.com.cn/lottery/index.shtml",     # 新浪彩票（体育频道）首页：当天的伤停/交战记录/竞彩情报入口
    "https://sports.sina.com.cn/l/football/",             # 竞技彩票栏目
    "https://lottery.sina.com.cn/",                       # 新浪彩票首页
)
HOST_OK = re.compile(r"^(?:[a-z0-9-]+\.)*sina\.(?:com\.cn|cn)$")
ART_RE = re.compile(r"^https?://sports\.sina\.com\.cn/l/(\d{4})-(\d{2})-(\d{2})/doc-[a-z0-9]+\.shtml$")
MAX_PAGES = 60              # 一次运行最多读多少个网页
PAGE_DELAY = 0.7            # 两次读网页之间至少隔多少秒
TTL_INDEX = 20 * 60         # 栏目页缓存
TTL_ART_FRESH = 3 * 3600    # 当天/昨天的文章缓存（伤停消息会更新）
TTL_ART_OLD = 7 * 86400     # 更早的文章
DB_KEEP_DAYS = 200
AUTO_ALIAS_FILE = "team_alias_auto.json"      # 脚本自己对上的队名（竞彩叫法 → 完场页叫法）
DB_MIN_FORM = 4             # 自存赛果：两队都至少有这么多场，才拿来算近况
DEBUG_KEEP = 30


# ═══════════════════════ 1. 中文队名：同一支球队的不同叫法 ═══════════════════════
# 每行一支球队，「|」隔开不同叫法（500 网的叫法、新浪的叫法……）。不全：认不出的队名会在运行提示里列出来，
# 补进 team_alias.json 就行（格式 {"500网里的叫法": "新浪的叫法|另一种叫法"}）。
GROUPS = """
阿森纳|兵工厂
曼城|曼彻斯特城
曼联|曼彻斯特联
利物浦
切尔西
热刺|托特纳姆热刺|托特纳姆
纽卡斯尔|纽卡斯尔联|纽卡
阿斯顿维拉|维拉
西汉姆联|西汉姆
布莱顿|布莱顿霍夫
水晶宫
富勒姆
布伦特福德|布伦特福特
伯恩茅斯|伯恩茅
埃弗顿
诺丁汉森林|诺丁汉
狼队|伍尔弗|伍尔弗汉普顿|伍尔夫汉普顿
伯恩利
利兹联|利兹
桑德兰
拜仁慕尼黑|拜仁
多特蒙德
勒沃库森|药厂|勒沃
莱比锡红牛|莱比锡|RB莱比锡
法兰克福|美因河畔法兰克福
斯图加特
弗赖堡
霍芬海姆|霍芬海
沃尔夫斯堡
门兴格拉德巴赫|门兴
云达不莱梅|不莱梅
美因茨
奥格斯堡
埃尔夫斯堡|埃夫斯堡
柏林联合|联合柏林
柏林赫塔|赫塔柏林|赫塔
科隆
汉堡
圣保利
海登海姆
荷尔斯泰因|荷尔斯泰因基尔|基尔
沙尔克04|沙尔克
国际米兰|国米
AC米兰
尤文图斯|尤文
那不勒斯
罗马|AS罗马
拉齐奥
亚特兰大
佛罗伦萨|紫百合|佛罗伦
博洛尼亚
都灵
萨索洛
乌迪内斯|乌迪内
热那亚
维罗纳|埃拉斯维罗纳
卡利亚里
帕尔马
科莫
莱切
克雷莫纳|克雷莫内塞
比萨
皇家马德里|皇马
巴塞罗那|巴萨
马德里竞技|马竞
赫罗纳|赫罗那
皇家社会|皇社
毕尔巴鄂竞技|毕尔巴鄂
比利亚雷亚尔|黄色潜水艇|维拉利尔
塞维利亚|塞维利
皇家贝蒂斯|贝蒂斯
瓦伦西亚
塞尔塔|塞尔塔维戈|维戈塞尔塔
赫塔菲
奥萨苏纳
拉斯帕尔马斯
马洛卡|皇家马洛卡
巴列卡诺
阿拉维斯|阿拉维
莱万特
埃尔切
西班牙人
拉科鲁尼亚|拉科鲁|拉科
奥维耶多|皇家奥维耶多
巴黎圣日耳曼|巴黎圣曼|大巴黎
马赛
摩纳哥
里昂
里尔
尼斯
朗斯
雷恩
斯特拉斯堡
南特
图卢兹
布雷斯特
蒙彼利埃
兰斯
勒阿弗尔
洛里昂
欧塞尔
昂热
梅斯
巴黎FC
本菲卡
波尔图
葡萄牙体育|里斯本竞技|里斯本体育
布拉加
阿贾克斯
费耶诺德
埃因霍温|PSV|PSV埃因霍温
奈梅亨
凯尔特人|凯尔特
格拉斯哥流浪者|流浪者
萨尔茨堡红牛|萨尔茨堡
格拉茨风暴
贝西克塔斯
加拉塔萨雷
费内巴切
特拉布宗体育|特拉布宗
奥林匹亚科斯
帕纳辛纳科斯
塞萨洛尼基PAOK|PAOK
萨格勒布迪纳摩|萨格勒布迪那摩
布加勒斯特迪纳摩|布加勒斯特迪那摩|CS布加勒斯特迪纳摩
哈伊杜克|哈伊杜克斯普利特
贝尔格莱德红星|红星
贝尔格莱德游击队|游击队|贝游击
安德莱赫特
布鲁日
圣吉联合|圣吉罗斯联合|圣吉罗斯|联合圣吉
索非亚列夫斯基|列夫斯基
索非亚中央陆军|索菲亚中央陆军|中央陆军
费伦茨瓦罗斯|费伦茨瓦罗什
比尔森胜利|比尔森
布拉格斯巴达|斯巴达布拉格
布拉格斯拉维亚|斯拉维亚布拉格|斯拉维亚
托伦斯|托林斯|托雷斯
利勒斯特罗姆
波兹南莱赫|波兹南|莱赫
北西兰
哈茨|哈茨
亚布洛内茨
克拉约瓦大学|克拉约瓦
帕福斯FC|帕福斯
OFI克里特|OFI
弗洛西|弗罗西诺内|弗洛西诺内
阿纳西|昂纳西|阿讷西
格勒诺|格勒诺布尔
布鲁马|布鲁马波卡纳
佐加顿|佐加顿斯
科特布|科特布斯|科特布斯
精英|SBV精英|精英斯
波城|波城FC
南锡
克莱蒙|克莱蒙特
第戎
布洛涅
拉瓦勒
甘冈
纽伦堡
勒芒
海伦芬
韦斯特洛|韦斯特鲁
阿尔克马尔青年队|阿克马尔青年队|阿尔克马尔青年
科布漫步者|科布漫步者队
奥地利维也纳青年队|奥地利维也纳青年
"""


_TEAM_MARK = re.compile(r"女|U\d{2}|青年|青少年|业余|[BC]队|二队|三队|预备|梯队|后备|Ⅱ|Ⅲ|(?<![a-z])(?:II|III|B|C)$", re.I)


def clean(n: str) -> str:
    """队名标准化：小写、去空格和括号里的说明（括号里是 U21/女足/青年队 这类标记的要保留，它们是另一支球队）。"""
    s = re.sub(r"[（(][^）)]*[）)]", lambda m: m.group(0) if _TEAM_MARK.search(m.group(0)) else "", str(n or ""))
    s = re.sub(r"[\s　​·・\-—_]+", "", s).lower()
    return s




def name_sim(a: str, b: str) -> float:
    """两个队名像不像（0～1）：写法一样 1；一个包含另一个 0.9；否则看两字组合的重合度（昂纳西/安纳西 约 0.5）。"""
    if not marks_ok(a, b):
        return 0.0
    a, b = clean(a), clean(b)
    if not a or not b:
        return 0.0
    if a == b:
        return 1.0
    if min(len(a), len(b)) >= 2 and (a in b or b in a):
        return 0.9
    ga = {a[i:i + 2] for i in range(len(a) - 1)} or {a}
    gb = {b[i:i + 2] for i in range(len(b) - 1)} or {b}
    return 2 * len(ga & gb) / (len(ga) + len(gb))


def team_marks(name: str) -> Tuple[Any, ...]:
    """保留女足、年龄组和B/C队身份；不能只比较是否存在某种标记。"""
    text = re.sub(r"[\s（）()]", "", str(name or "")).lower()
    ages = tuple(sorted(set(re.findall(r"u(\d{2})", text))))
    female = "女" in text
    if "业余" in text:
        reserve = "amateur"
    elif re.search(r"c队|三队|ⅲ|(?<![a-z])(?:iii|c)$", text):
        reserve = "c"
    elif re.search(r"b队|二队|预备|后备|ⅱ|(?<![a-z])(?:ii|b)$", text):
        reserve = "b"
    else:
        reserve = ""
    youth = bool(re.search(r"青年|青少年|梯队", text)) and not ages
    return female, ages, reserve, youth


def marks_ok(a: str, b: str) -> bool:
    return team_marks(a) == team_marks(b)


def resolve_match_names(match: Dict[str, Any]) -> Dict[str, Any]:
    """有明确联赛上下文才解析歧义简称，保持外部传入的数据不变。"""
    out = dict(match)
    league = norm(match.get("lg", ""))
    if league in ("意甲", "意大利甲级联赛", "意大利甲级", "seriea"):
        for side in ("home", "away"):
            if clean(out.get(side, "")) == "亚特兰":
                out[side] = "亚特兰大"
    # 「社会」可能指不同梯队，不能只凭简称或相似度确定身份。
    return out


def norm(s: str) -> str:
    """文章标题/正文用的标准化：小写、去空白（不删括号里的字）。"""
    return re.sub(r"[\s\u3000\u200b·・\-—_]+", "", str(s or "")).lower()


class ZhNames:
    def __init__(self, folder: Optional[Path] = None):
        self._gid: Dict[str, int] = {}
        self._groups: Dict[int, List[str]] = {}
        self._next = 0
        for line in GROUPS.strip().splitlines():
            self.add_group(line.split("|"))
        self.folder = Path(folder) if folder is not None else None
        if folder is not None:
            for fn in ("team_alias.json", AUTO_ALIAS_FILE):          # 手写的 + 脚本自己对上的
                try:
                    data = json.loads(L.p(folder, fn).read_text(encoding="utf-8"))
                    for k, v in (data.items() if isinstance(data, dict) else []):
                        self.add_group([str(k)] + str(v).split("|"))
                except (OSError, ValueError, AttributeError):
                    pass

    def learn(self, pairs: List[Tuple[str, str]]) -> int:
        """记住「竞彩叫法 → 完场页叫法」的对应（存进 team_alias_auto.json，以后每次自动用）。返回新增条数。"""
        new = [(a, b) for a, b in pairs if a and b and marks_ok(a, b) and self.canon(a) != self.canon(b)]
        if not new:
            return 0
        for a, b in new:
            self.add_group([b, a])
        if self.folder is not None:
            path = L.p(self.folder, AUTO_ALIAS_FILE)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                data = data if isinstance(data, dict) else {}
            except (OSError, ValueError):
                data = {}
            for a, b in new:
                data[a] = b
            try:
                path.write_text(json.dumps(data, ensure_ascii=False, indent=0, sort_keys=True), encoding="utf-8")
            except OSError:
                pass
        return len(new)

    def add_group(self, names: List[str]) -> None:
        safe = [x for x in names if clean(x)]
        if safe:
            safe = [x for x in safe if marks_ok(safe[0], x)]
        keys = [self._strip_suffix(clean(x)) for x in safe]
        if not keys:
            return
        ids = {self._gid[k] for k in keys if k in self._gid}
        gid = min(ids) if ids else self._next
        if not ids:
            self._next += 1
        members = self._groups.setdefault(gid, [])
        for g in ids:                      # 合并已有的组
            if g != gid:
                members.extend(self._groups.pop(g, []))
        for k in keys:
            if k not in members:
                members.append(k)
        for k in members:
            self._gid[k] = gid

    @staticmethod
    def _strip_suffix(k: str) -> str:
        for suf in ("足球俱乐部", "俱乐部", "足球会", "fc", "cf"):
            if k.endswith(suf) and len(k) - len(suf) >= 3:
                return k[: -len(suf)]
        return k

    def canon(self, name: str) -> str:
        k = self._strip_suffix(clean(name))
        gid = self._gid.get(k)
        return self._groups[gid][0] if gid is not None else k

    def variants(self, name: str) -> List[str]:
        """这支球队在文章里可能的写法（长的在前）。"""
        k = self._strip_suffix(clean(name))
        out = {k}
        gid = self._gid.get(k)
        if gid is not None:
            out.update(self._groups[gid])
        return sorted((x for x in out if len(x) >= 2), key=lambda x: -len(x))

    @staticmethod
    def partial(name: str) -> Optional[str]:
        """去掉最后一个字的写法（凯尔特人→凯尔特）；只在「文章里找不到全名」时兜底用，且至少 3 个字。"""
        k = clean(name)
        return k[:-1] if len(k) >= 4 else None


# ═══════════════════════ 2. 网页 → 纯文字 ═══════════════════════
def html_to_text(raw: str) -> str:
    s = re.sub(r"(?is)<(script|style|noscript|svg|iframe|head)\b.*?</\1\s*>", " ", raw)
    s = re.sub(r"(?s)<!--.*?-->", " ", s)
    s = re.sub(r"(?i)<\s*(br|/p|/div|/li|/tr|/h[1-6]|/section|/article|/table|/ul|/ol|/dd|/dt)\b[^>]*>", "\n", s)
    s = re.sub(r"(?i)</t[dh]\s*>", " ", s)
    s = re.sub(r"(?s)<[^>]+>", "", s)
    s = htmllib.unescape(s).replace("　", " ").replace("\xa0", " ").replace("​", "")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in s.splitlines()]
    return "\n".join(ln for ln in lines if ln)


def html_title(raw: str) -> str:
    m = re.search(r"(?is)<title[^>]*>(.*?)</title>", raw)
    t = htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(1))) if m else ""
    return re.sub(r"\s+", " ", t).strip()


def html_links(raw: str, base: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    seen = set()
    for m in re.finditer(r"(?is)<a\b[^>]*?href\s*=\s*[\"']([^\"'#]+)[\"'][^>]*>(.*?)</a\s*>", raw):
        url = urllib.parse.urljoin(base, htmllib.unescape(m.group(1)).strip())
        title = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", m.group(2)))).strip()
        if url not in seen:
            seen.add(url)
            out.append((url, title))
    return out


_FOOT = ("责任编辑", "新浪声明", "声明：新浪网", "免责声明", "相关推荐", "相关阅读", "热门推荐", "版权所有")


def article_body(text: str) -> str:
    """去掉导航/页脚，只留文章正文（按「标题行→页脚标记」截取；认不出就返回全文）。"""
    lines = text.splitlines()
    start = 0
    for i, ln in enumerate(lines):
        if ("竞彩情报" in ln or "足彩伤停" in ln or "交战记录" in ln) and len(ln) < 80:
            start = i + 1
            break
    end = len(lines)
    for i in range(start, len(lines)):
        if any(f in lines[i] for f in _FOOT) and len(lines[i]) < 60:
            end = i
            break
    body = lines[start:end]
    if sum(len(x) for x in body) < 150 and end < len(lines):       # 页脚标记出现在正文前面（侧栏/广告）：别把正文截没了
        body = lines[start:]
    keep = [ln for ln in body if len(ln) >= 18 or re.search(r"[，。；：:]", ln) or re.search(r"主队|客队|利好|利空", ln)]
    return "\n".join(keep if keep else body)


# ═══════════════════════ 3. 从「竞彩情报」正文里认数字 ═══════════════════════
_CN = {"一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
NUM = r"(?:\d{1,2}|[一二两三四五六七八九十]{1,3})"


def cn2int(s: str) -> Optional[int]:
    s = str(s)
    if s.isdigit():
        return int(s)
    if s == "十":
        return 10
    if s.startswith("十") and len(s) == 2 and s[1] in _CN:
        return 10 + _CN[s[1]]
    if len(s) == 2 and s[1] == "十" and s[0] in _CN:
        return _CN[s[0]] * 10
    if len(s) == 3 and s[1] == "十" and s[0] in _CN and s[2] in _CN:
        return _CN[s[0]] * 10 + _CN[s[2]]
    return _CN.get(s) if len(s) == 1 else None


_WL = r"(?:(\d{1,2})\s*胜(?:(\d{1,2})\s*平)?(?:(\d{1,2})\s*负)?|(\d{1,2})\s*平(?:(\d{1,2})\s*负)?|(\d{1,2})\s*负)"
# ① 「近10场……7胜3平」（中间可以隔一个逗号：「近15场正式比赛，萨尔茨堡红牛取得11胜4平」）
REC_RE = re.compile(r"(?:近期?|最近)(" + NUM + r")(场|个)([^。；;！？!?\d]{0,22}?)" + _WL)
# ② 没写「近」的：「6场比赛4胜1平」「7场正式比赛中取得4胜2平1负」「本赛季7轮联赛仅取得1胜3平3负」
REC2_RE = re.compile(r"(?<![近期\d])(" + NUM + r")(场|轮)([^。；;！？!?，,\d]{0,14}?)" + _WL)
# ③ 赛季至今的总战绩：「新赛季至今各项赛事取得4胜2平1负」（场数 = 三个数相加）
SEASON_RE = re.compile(r"(?:至今|目前|截至目前|本赛季|新赛季|赛季至今)([^。；;！？!?\d]{0,18}?)(\d{1,2})\s*胜\s*(\d{1,2})\s*平\s*(\d{1,2})\s*负")
SKIP_ALL = re.compile(r"执教|上赛季|上个赛季|去赛季|去年")                       # 教练战绩、去年的战绩，不算球队现在的状态
SKIP_LOOSE = re.compile(r"主帅|教练|历史|此前|曾|前任|过去")                    # 只对「没写近」的两种写法生效
GF_RE = re.compile(r"场均(?:进球|进|打进|入球)(?:数)?(?:仅为|仅有|仅|达到?|约|高达|为)?(\d(?:\.\d+)?)")
GA_RE = re.compile(r"场均(?:失球|丢球|失|丢)(?:数)?(?:仅为|仅有|仅|约|高达|达到?|为)?(\d(?:\.\d+)?)")
GA_TOT_RE = re.compile(r"(?<![\d])(" + NUM + r")场[^。；;]{0,24}?(?:仅|只)?(?:丢|失)(\d{1,2})球")
STREAKS = (
    (re.compile(r"(" + NUM + r")(?:场)?(?:比赛|联赛|正赛)?连胜"), "win", "连胜"),
    (re.compile(r"(" + NUM + r")(?:场)?(?:比赛|联赛|正赛)?连败"), "lose", "连败"),
    (re.compile(r"(" + NUM + r")场不败"), "unbeaten", "场不败"),
    (re.compile(r"(" + NUM + r")场不胜"), "winless", "场不胜"),
    (re.compile(r"连续(" + NUM + r")场(?:失球|丢球)"), "concede", "场连续失球"),
    (re.compile(r"(" + NUM + r")场(?:零封|没有失球|未失球)"), "clean", "场零封"),
)
H2H_WORD = re.compile(r"交锋|交手|对阵|相遇|对战|往绩")
WDL_RE = re.compile(r"(\d{1,2})胜(?:(\d{1,2})平)?(?:(\d{1,2})负)?|(\d{1,2})平(?:(\d{1,2})负)?")
ABS_RE = re.compile(r"缺阵|伤缺|缺席|无法出战|不能出战|不会出战|无法随队|无法参赛|无法上场|不能参赛|缺战|将缺|停赛|禁赛|赛季报销|伤停|因伤|报销|无缘")
DOUBT_RE = re.compile(r"成疑|存疑|伤疑|疑问|疑虑|悬念|不确定|能否|待定|可能|或将|或许|恐将|疑似|不排除|带伤")
STRONG_ABS = re.compile(r"缺阵|伤缺|缺席|无法出战|不能出战|不会出战|无法随队|无法参赛|无法上场|赛季报销|报销")
_JOIN = ("预计", "预期", "将", "可能", "恐", "大概率", "确定", "已确定", "或", "也", "都", "均", "出战", "继续", "仍")
BACK_RE = re.compile(r"复出|回归|恢复|伤愈|重返|归队|有望出战|可以出战|能够出战|能出战|有望首发|重新进入|可出战|康复|已复")
PAST_RE = re.compile(r"上一轮|上轮|上场|上周|此前|之前|曾|上个|上赛季|去年|前一|对阵.{0,8}时|年前")
KEY_RE = re.compile(r"主力|核心|头号|大将|球星|队长|王牌|主将")
MANY_RE = re.compile(r"多名|多人|多位|数名|不少|大量")
_BULLET = re.compile(r"^\s*(?:[•·▪■●◆◇○▶►★☆※]|\d{1,2}[.、．)）]|[①②③④⑤⑥⑦⑧⑨⑩])\s*")


def new_side() -> Dict[str, Any]:
    return {"rec": [], "venue": [], "gf": None, "ga": None, "ga_tot": None, "streak": None, "key": 0, "out": 0, "doubt": 0,
            "h2h": None, "seen": 0, "many": False}


_CONN = re.compile(r"^(?:与此同时|同时|反观|另一方面|另一边|相比之下|相较之下|此外|另外|不过|但是|但|而|至于|再看|反之|同样|然而|整体而言|总体而言|综合来看|其中)[，,、 ]*")


def _lead_side(s: str, vh: List[str], av: List[str]) -> Optional[str]:
    """句子开头是哪支球队（或「主队」「客队」）。"""
    for _ in range(2):                                    # 「反观塞尔塔，……」「与此同时，皇家社会……」：去掉句首连接词再看是哪支球队
        s2 = _CONN.sub("", s.strip(), count=1)
        if s2 == s.strip():
            break
        s = s2
    k = clean(s)
    best: Tuple[int, Optional[str]] = (0, None)
    for side, vs in (("h", vh), ("a", av)):
        for v in vs:
            if k.startswith(v) and len(v) > best[0]:
                best = (len(v), side)
    if best[1]:
        return best[1]
    if re.match(r"\s*(?:主队|主场球队|东道主)", s):
        return "h"
    if re.match(r"\s*(?:客队|客场球队)", s):
        return "a"
    return None


def _persons(clause: str, upto: int) -> int:
    if MANY_RE.search(clause):
        return 3
    return min(4, 1 + len(re.findall(r"、|和|及|与", clause[:upto])))


def _scan_injury(sentence: str, st: Dict[str, Any]) -> None:
    """一句话里的伤停：缺阵（计人数，带「主力/核心」的单独记）、存疑。过去的事、复出的、没说清的都不算。"""
    parts = [p for p in re.split(r"[，,]", sentence) if p]
    clauses: List[str] = []
    for p in parts:                                   # 「某某受到膝伤影响，预计无法出战」：说动作的半句并回前一句
        if clauses and p.startswith(_JOIN):
            clauses[-1] += "，" + p
        else:
            clauses.append(p)
    for cl in clauses:
        if PAST_RE.search(cl):
            continue
        a = ABS_RE.search(cl)
        soft = DOUBT_RE.search(cl)
        if not a and not soft:
            continue
        if BACK_RE.search(cl) and not STRONG_ABS.search(cl):
            continue
        if soft:
            st["doubt"] = min(3, st["doubt"] + 1)
            continue
        n = _persons(cl, a.start() if a else len(cl))
        if MANY_RE.search(cl):
            st["many"] = True                          # 「多名主力伤缺」：只知道是多人，不知道几个——写「缺多人」，不编数字
        if KEY_RE.search(cl):
            st["key"] = min(3, st["key"] + n)
        else:
            st["out"] = min(4, st["out"] + n)


def _wdl(m: "re.Match[str]", n: int, g0: int) -> Optional[Dict[str, int]]:
    """把一次「X胜Y平Z负」的匹配整理成 {n,w,d,l}；数字对不上就返回 None（不猜）。g0 = 胜平负第一组的编号。"""
    if m.group(g0) is not None:
        w, d, l = int(m.group(g0)), m.group(g0 + 1), m.group(g0 + 2)
    elif m.group(g0 + 3) is not None:
        w, d, l = 0, m.group(g0 + 3), m.group(g0 + 4)
    else:
        w, d, l = 0, None, m.group(g0 + 5)
    d_ = int(d) if d is not None else None
    l_ = int(l) if l is not None else None
    if d_ is None and l_ is not None:
        d_ = n - w - l_
    elif l_ is None and d_ is not None:
        l_ = n - w - d_
    elif d_ is None and l_ is None:
        return None
    if d_ is None or l_ is None or d_ < 0 or l_ < 0 or w + d_ + l_ > n + 1 or w + d_ + l_ < 3:
        return None
    return {"n": w + d_ + l_ if w + d_ + l_ <= n else n, "w": w, "d": d_, "l": l_}


def _records(s: str) -> List[Tuple[Dict[str, int], str]]:
    """一句话里的战绩 → [({n,w,d,l}, 前后文)]。三种写法见 REC_RE / REC2_RE / SEASON_RE；教练战绩、去年战绩不要。"""
    out: List[Tuple[Dict[str, int], str]] = []
    if SKIP_ALL.search(s):
        return out
    spans: List[Tuple[int, int]] = []
    loose_ok = not SKIP_LOOSE.search(s)
    for rx, kind in ((REC_RE, 1), (REC2_RE, 2)):
        if kind == 2 and not loose_ok:
            continue
        for m in rx.finditer(s):
            if any(m.start() < e and m.end() > b for b, e in spans):
                continue
            n = cn2int(m.group(1))
            if not n or n < 3 or n > 40:
                continue
            rec = _wdl(m, n, 4)
            if rec is None:
                continue
            spans.append(m.span())
            out.append((rec, m.group(3) or ""))
    if loose_ok:
        for m in SEASON_RE.finditer(s):
            if any(m.start() < e and m.end() > b for b, e in spans):
                continue
            w, d, l = int(m.group(2)), int(m.group(3)), int(m.group(4))
            if w + d + l < 5 or w + d + l > 40:
                continue
            spans.append(m.span())
            out.append(({"n": w + d + l, "w": w, "d": d, "l": l}, m.group(1) or ""))
    return out


def parse_intel(text: str, vh: List[str], av: List[str]) -> Dict[str, Dict[str, Any]]:
    """从一篇「竞彩情报」正文里，按球队认出：近N场战绩、主客场战绩、场均进失球、连胜连败、伤停人数、交锋。
    每句话归给「开头点名的球队」，没点名的归给上一句的球队（文章是一队一段地写的）。认不出就不要，不猜。"""
    sides = {"h": new_side(), "a": new_side()}
    cur: Optional[str] = None
    for line in text.splitlines():
        lead_line = clean(line)
        if len(line) <= 24 and not re.search(r"\d|[，。；！？]", line):    # 短行、没数字没标点：可能是小标题（「本菲卡（主队）」）
            hs_ = any(v in lead_line for v in vh)
            as_ = any(v in lead_line for v in av)
            if hs_ != as_:
                cur = "h" if hs_ else "a"
                continue
            if hs_ and as_:
                cur = None
                continue
        for raw in re.split(r"[。！？!?；;]+", line):
            s = _BULLET.sub("", raw).strip()
            if not s:
                continue
            sub = _lead_side(s, vh, av)
            if sub:
                cur = sub
            if re.match(r"\s*(?:两队|双方|两者)", s):
                continue
            side = cur
            if side is None:
                continue
            st = sides[side]
            st["seen"] += 1
            for rec_, ctx in _records(s):
                if "欧" in ctx or "杯" in ctx or "友谊" in ctx or "资格赛" in ctx:
                    continue                                          # 欧战/杯赛单独的战绩，不当作整体近况
                if "主场" in ctx:
                    if side == "h":
                        st["venue"].append(rec_)
                elif "客场" in ctx:
                    if side == "a":
                        st["venue"].append(rec_)
                else:
                    st["rec"].append(rec_)
            g = GF_RE.search(s)
            if g and st["gf"] is None:
                st["gf"] = float(g.group(1))
            g = GA_RE.search(s)
            if g and st["ga"] is None:
                st["ga"] = float(g.group(1))
            g = GA_TOT_RE.search(s)
            if g and st["ga_tot"] is None and cn2int(g.group(1)):
                st["ga_tot"] = (cn2int(g.group(1)), int(g.group(2)))
            for rx, kind, word in STREAKS:
                g = rx.search(s)
                if g:
                    k = cn2int(g.group(1))
                    if k and k >= 3 and (st["streak"] is None or k > st["streak"][1]):
                        st["streak"] = (kind, k, word)
            if H2H_WORD.search(s) and _lead_side(s, vh, av):
                g = WDL_RE.search(s)
                if g and st["h2h"] is None:
                    if g.group(1) is not None:
                        w, d, l = int(g.group(1)), int(g.group(2) or 0), int(g.group(3) or 0)
                    else:
                        w, d, l = 0, int(g.group(4)), int(g.group(5) or 0)
                    if 0 < w + d + l <= 30:
                        st["h2h"] = {"w": w, "d": d, "l": l}
            _scan_injury(s, st)
    return sides


# ═══════════════════════ 4. 「足彩伤停」「交战记录」：表格式文章 ═══════════════════════
INJ_RE = re.compile(r"(?P<team>[^\s：:，,()（）]{2,14})\s*伤病[:：]\s*(?P<inj>.*?)\s*停赛[:：]\s*(?P<sus>.*?)"
                    r"(?=\s*[^\s：:，,()（）]{2,14}\s*伤病[:：]|\n|$)", re.S)


def _players(seg: str) -> Tuple[int, int]:
    """一串球员 → (总人数, 其中标「主力」的)。「无」→ 0。"""
    seg = seg.strip().strip("。；; ")
    if not seg or seg in ("无", "无。", "暂无", "—", "-"):
        return 0, 0
    groups = re.findall(r"[^\s、，,;；()（）]+[（(][^）)]*[）)]", seg)
    if groups:
        return len(groups), sum(1 for g in groups if "主力" in g)
    parts = [p for p in re.split(r"[、，,;；\s]+", seg) if p]
    return len(parts), sum(1 for p in parts if "主力" in p)


def parse_injury_table(text: str) -> Dict[str, Dict[str, Any]]:
    """「足彩伤停」文章 → {队名: {out: 总人数, key: 主力人数}}。队名是文章里的原样写法。"""
    out: Dict[str, Dict[str, Any]] = {}
    flat = re.sub(r"[ \t]+", " ", text)
    for m in INJ_RE.finditer(flat):
        team = re.sub(r"^[\d.、．)）\-]+", "", m.group("team"))
        if len(team) < 2:
            continue
        sus = m.group("sus")[:80]
        n1, k1 = _players(m.group("inj"))
        n2, k2 = _players(sus)
        out.setdefault(clean(team), {"team": team, "out": n1 + n2, "key": k1 + k2})
    return out


H2H_ROW = re.compile(r"(?P<h>[^\s\d:：%（）()]{2,14})\s*(?:vs|VS|Vs|对|[-—])?\s*(?P<a>[^\s\d:：%（）()]{2,14})\s+"
                     r"(?P<n>\d{1,3})\s+(?P<w>\d{1,3})\s+(?P<d>\d{1,3})\s+(?P<l>\d{1,3})(?=\s|$)")


# 新浪真实写法（2026-10 取样）：一场一段话，没有表格——
#   「伯恩茅斯 VS 桑德兰两队近10年的交战次数为5场，伯恩茅斯1胜2平2负，赢球概率为20.0%，平局概率为40.0%，输球概率为40.0%。」
H2H_SENT = re.compile(r"(?P<h>[^\s，。,.、；;：:\d（）()]{2,14}?)\s*(?:VS|vs|Vs|对阵)\s*(?P<a>[^\s，。,.、；;：:\d（）()]{2,14}?)\s*两队近\s*(?P<y>\d{1,2})\s*年"
                      r"(?:的)?(?:交战|交锋|交手)(?:次数)?为\s*(?P<n>\d{1,3})\s*场[，,]\s*(?P<t>[^\s，。,.\d]{2,14}?)\s*"
                      r"(?P<w>\d{1,3})\s*胜\s*(?P<d>\d{1,3})\s*平\s*(?P<l>\d{1,3})\s*负")


def parse_h2h_table(text: str) -> List[Dict[str, Any]]:
    """「交战记录」文章 → [{h, a, n, w, d, l}]（w/d/l 都是文章里「前一支球队」的胜/平/负）。
    认两种写法：一场一句话（新浪现在的写法）；一行一场的表格（序号/主队/客队/次数/胜/平/负）。"""
    rows = []
    flat = re.sub(r"[ \t]+", " ", text)
    for m in H2H_SENT.finditer(flat):
        n, w, d, l = (int(m.group(k)) for k in ("n", "w", "d", "l"))
        if not n or w + d + l != n:
            continue
        h, a, t = m.group("h"), m.group("a"), m.group("t")
        if clean(t) == clean(a) and clean(t) != clean(h):      # 句子里说的是「客队」的战绩 → 换成主队的角度
            w, l = l, w
        rows.append({"h": h, "a": a, "n": n, "w": w, "d": d, "l": l, "y": int(m.group("y"))})
    if rows:
        return rows
    for m in H2H_ROW.finditer(flat):
        n, w, d, l = (int(m.group(k)) for k in ("n", "w", "d", "l"))
        if n and w + d + l == n:
            rows.append({"h": m.group("h"), "a": m.group("a"), "n": n, "w": w, "d": d, "l": l})
    return rows


# ═══════════════════════ 5. 读网页（robots、限速、缓存） ═══════════════════════
class Fetcher:
    def __init__(self, cache_dir: Path, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
                 proxy: str = "", sleep: Callable[[float], None] = time.sleep, max_pages: int = MAX_PAGES, delay: float = PAGE_DELAY,
                 host_ok: "re.Pattern[str]" = HOST_OK):
        self.cache_dir, self.log = Path(cache_dir), log or (lambda m: None)
        self.cancel = cancel or (lambda: False)
        self.sleep, self.max_pages, self.delay, self.host_ok = sleep, max_pages, delay, host_ok
        handlers: List[Any] = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        self.pages = 0
        self.fail = 0
        self._last = 0.0
        self._robots: Dict[str, Optional[urllib.robotparser.RobotFileParser]] = {}

    # —— robots ——
    def _rp(self, scheme: str, host: str) -> Optional[urllib.robotparser.RobotFileParser]:
        key = f"{scheme}://{host}"
        if key in self._robots:
            return self._robots[key]
        rp: Optional[urllib.robotparser.RobotFileParser] = urllib.robotparser.RobotFileParser()
        try:
            req = urllib.request.Request(key + "/robots.txt", headers={"User-Agent": UA})
            with self.opener.open(req, timeout=15) as r:
                body = r.read(300000).decode("utf-8", "replace")
            rp.parse(body.splitlines())                       # type: ignore[union-attr]
        except urllib.error.HTTPError:
            rp = None                                          # 没有 robots.txt（404 等）：没有限制
        except (urllib.error.URLError, OSError):
            rp = None
        self._robots[key] = rp
        return rp

    def allowed(self, url: str) -> bool:
        u = urllib.parse.urlsplit(url)
        if u.scheme not in ("http", "https") or not self.host_ok.match((u.hostname or "").lower()):
            return False
        if u.query:                                           # 带「?」的地址不读（新浪彩票 robots：Disallow /*?*）
            return False
        rp = self._rp(u.scheme, u.netloc)
        return True if rp is None else rp.can_fetch("*", url)

    def crawl_delay(self) -> float:
        d = self.delay
        for rp in self._robots.values():
            try:
                c = rp.crawl_delay("*") if rp else None
            except Exception:  # noqa: BLE001
                c = None
            if c:
                d = max(d, float(c))
        return d

    # —— 缓存 ——
    def _cpath(self, url: str) -> Path:
        return self.cache_dir / (hashlib.sha1(url.encode("utf-8")).hexdigest()[:20] + ".json")

    def _read_cache(self, url: str, ttl: float) -> Optional[Dict[str, Any]]:
        try:
            d = json.loads(self._cpath(url).read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return None
            age = time.time() - float(d["t"])
            if d.get("url") == url and math.isfinite(age) and 0 <= age < ttl:
                return d
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _write_cache(self, d: Dict[str, Any]) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._cpath(d["url"]), json.dumps(d, ensure_ascii=False))
        except OSError:
            pass

    @staticmethod
    def _decode(raw: bytes, ctype: str) -> str:
        enc = ""
        m = re.search(r"charset=([\w-]+)", ctype or "", re.I)
        if m:
            enc = m.group(1)
        else:
            mb = re.search(rb"charset=[\"']?([\w-]+)", raw[:4000], re.I)
            if mb:
                enc = mb.group(1).decode("ascii", "ignore")
        for e in (enc, "utf-8", "gb18030"):
            if not e:
                continue
            try:
                return raw.decode(e)
            except (LookupError, UnicodeDecodeError):
                continue
        return raw.decode("utf-8", "replace")

    def get(self, url: str, ttl: float) -> Dict[str, Any]:
        """返回 {url, t, title, text, links}（links 是 [(网址, 标题)]）。失败抛 DataError。"""
        if not self.allowed(url):
            raise T.DataError(f"这个地址不读（robots.txt 不让读，或带「?」参数）：{url}", "other")
        hit = self._read_cache(url, ttl)
        if hit is not None:
            return hit
        for attempt in range(3):
            if self.cancel():
                raise T.DataError("已停止。", "other", True)
            if self.pages >= self.max_pages:
                raise T.DataError(f"这次已经读了 {self.pages} 个网页（上限 {self.max_pages}），其余没读。", "quota")
            wait = self.crawl_delay() - (time.time() - self._last)
            if wait > 0:
                self.sleep(wait + random.uniform(0, 0.3))
            req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                                       "Accept-Language": "zh-CN,zh;q=0.9"})
            self._last = time.time()
            try:
                with self.opener.open(req, timeout=25) as resp:
                    raw, ctype = resp.read(3_000_000), resp.headers.get("Content-Type", "")
                self.pages += 1
                self.fail = 0
            except urllib.error.HTTPError as exc:
                self.pages += 1
                if exc.code in (404, 410):
                    raise T.DataError(f"网页不存在（HTTP {exc.code}）：{url}", "other")
                self.fail += 1
                if exc.code in (403, 429, 503) and attempt < 2:
                    self.sleep(4 * (attempt + 1))
                    continue
                if self.fail >= 4:
                    raise T.DataError(f"网站连续拒绝访问（HTTP {exc.code}）。可能是访问太频繁或被网络拦截，稍后再试。", "net", True)
                raise T.DataError(f"网页读取失败（HTTP {exc.code}）：{url}", "other")
            except (urllib.error.URLError, OSError) as exc:
                self.fail += 1
                if self.fail >= 3:
                    raise T.DataError(f"网络连不上新浪网站（{exc}）。检查网络，或在设置里填代理。", "net", True)
                self.sleep(2 * (attempt + 1))
                continue
            html = self._decode(raw, ctype)
            d = {"url": url, "t": time.time(), "title": html_title(html), "text": html_to_text(html), "links": html_links(html, url)}
            self._write_cache(d)
            return d
        raise T.DataError(f"网页多次重试仍失败：{url}", "other")


# ═══════════════════════ 6. 自己攒的赛果库 ═══════════════════════
DEDUP_GAP_MIN = 360     # 判定「同一场比赛」时，两条比分的开球时间最多差多少分钟（竞彩和完场页同一场时间应该一样；放宽到 6 小时防个别写错）


class ResultsDB:
    """每次运行把 500 网「昨日已开奖」里的足球比分存下来（竞足+北单，每天约 50～60 场）。时间一长，就能自己算两队近况。"""

    def __init__(self, folder: Path, names: Optional[ZhNames] = None):
        self.path = L.p(folder, "results_db.json")
        self.names = names or ZhNames(folder)
        self.rows: List[Dict[str, Any]] = []
        self.wc_days: Dict[str, int] = {}          # 完场页里已经完整读过的「比赛日」：{日期: 当天读到几场}
        try:
            d = json.loads(self.path.read_text(encoding="utf-8"))
            self.rows = [r for r in d.get("rows", []) if isinstance(r, dict)]
            wd = d.get("wc_days")
            if isinstance(wd, dict):
                self.wc_days = {str(k): int(v) for k, v in wd.items() if isinstance(v, (int, float))}
        except (OSError, ValueError, AttributeError):
            pass
        self._idx: Optional[Dict[str, List[int]]] = None
        self._dd: Optional[Tuple[set, set, Dict[str, list]]] = None
        self.hints: List[Tuple[str, str]] = []     # 同一场比赛的两种队名写法（add 时攒的）
        self.learned = 0                           # 这次运行里从赛果自己学到几个队名对应

    def _dd_put(self, dd: Tuple[set, set, Dict[str, list]], r: Dict[str, Any]) -> None:
        have, ids, fz = dd
        d, ch, ca = r["k"][:10], self.names.canon(r["h"]), self.names.canon(r["a"])
        have.add((d, ch, ca))
        if r.get("id"):
            ids.add(str(r["id"]))
        fz.setdefault(d, []).append((r["hs"], r["as"], ch, ca, r["h"], r["a"], r["k"]))

    @staticmethod
    def _gap_min(k1: str, k2: str) -> float:
        try:
            return abs((datetime.strptime(k1, "%Y-%m-%d %H:%M") - datetime.strptime(k2, "%Y-%m-%d %H:%M")).total_seconds()) / 60
        except ValueError:
            return 9999.0

    def _hint(self, ours: str, theirs: str) -> None:
        """同一场比赛两种写法 → 记一对「可能是同一队」。像得太离谱（sim<0.34）或一个是青年队/女足的不记。"""
        if ours and theirs and self.names.canon(ours) != self.names.canon(theirs) and marks_ok(ours, theirs) and name_sim(ours, theirs) >= 0.34:
            self.hints.append((ours, theirs))

    def add(self, rows: List[Dict[str, Any]]) -> int:
        """rows: [{k: 'YYYY-MM-DD HH:MM'(北京时间开赛), h, a, hs, as, lg, id(可选)}]。返回新增条数。
        去重三道：①同一天+同样的两队名；②同一个比赛编号 id；③同一天、同样的比分、开球时间差不多、且主队或客队写法相同
        （竞彩赛果和完场页对同一场的队名写法偶尔不一样，免得一场比赛被算两次）。
        第③道命中时，另一边的两种写法很可能是同一支球队的两种叫法：像的话记成别名（self.learned 记新学到几个）。"""
        if self._dd is None:
            self._dd = (set(), set(), {})
            for r in self.rows:
                try:
                    self._dd_put(self._dd, r)
                except (KeyError, TypeError):
                    continue
        have, ids, fz = self._dd
        n = 0
        for r in rows:
            try:
                if not r["h"] or not r["a"]:
                    continue
                hs, as_ = int(r["hs"]), int(r["as"])
                d, ch, ca = r["k"][:10], self.names.canon(r["h"]), self.names.canon(r["a"])
                rid = str(r["id"]) if r.get("id") else ""
                if (d, ch, ca) in have or (rid and rid in ids):
                    continue
                dup = None
                for x, y, cx, cy, rh, ra, rk in fz.get(d, ()):
                    if x == hs and y == as_ and (ch == cx or ca == cy) and self._gap_min(r["k"], rk) <= DEDUP_GAP_MIN:
                        dup = (rh, ra, ch == cx)
                        break
                if dup:
                    if dup[2]:
                        self._hint(r["a"], dup[1])
                    else:
                        self._hint(r["h"], dup[0])
                    continue
                row = {"k": r["k"], "h": r["h"], "a": r["a"], "hs": hs, "as": as_, "lg": r.get("lg", "")}
                if rid:
                    row["id"] = rid
                self.rows.append(row)
                self._dd_put(self._dd, row)
                n += 1
            except (KeyError, TypeError, ValueError):
                continue
        if n:
            self._idx = None
        self._flush_hints()
        return n

    def _flush_hints(self) -> int:
        """把攒下的「同一队两种写法」记进别名文件；记了之后同一场比赛被存成两条的，合并成一条。返回新记的个数。"""
        if not self.hints:
            return 0
        pairs, self.hints = self.hints, []
        try:
            k = self.names.learn(pairs)
        except Exception:  # noqa: BLE001
            return 0
        if k:
            self.learned += k
            self._idx = self._dd = None
            self._dedupe()
        return k

    def _dedupe(self) -> int:
        """别名变了以后，把同一天、同样比分、开球时间差不多、有一边队名（按别名算）相同的重复比分合并成一条（有比赛编号的留下）。"""
        keep: List[Dict[str, Any]] = []
        seen: Dict[Tuple[str, int, int], List[Tuple[str, str, str]]] = {}
        drop = 0
        for r in sorted(self.rows, key=lambda r: (0 if r.get("id") else 1, r["k"])):
            try:
                key = (r["k"][:10], int(r["hs"]), int(r["as"]))
                ch, ca = self.names.canon(r["h"]), self.names.canon(r["a"])
            except (KeyError, TypeError, ValueError):
                keep.append(r)
                continue
            if any((ch == cx or ca == cy) and self._gap_min(r["k"], rk) <= DEDUP_GAP_MIN for cx, cy, rk in seen.get(key, ())):
                drop += 1
                continue
            seen.setdefault(key, []).append((ch, ca, r["k"]))
            keep.append(r)
        if drop:
            self.rows = keep
            self._idx = self._dd = None
        return drop

    def save(self) -> None:
        cut = (datetime.now(BJT) - timedelta(days=DB_KEEP_DAYS)).strftime("%Y-%m-%d")
        n0 = len(self.rows)
        self.rows = [r for r in self.rows if r["k"][:10] >= cut]
        if len(self.rows) != n0:
            self._idx = self._dd = None
        self.rows.sort(key=lambda r: r["k"])
        self._idx = None
        self.wc_days = {k: v for k, v in self.wc_days.items() if k >= cut}
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps({"v": 1, "rows": self.rows, "wc_days": self.wc_days}, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self.path)
        except OSError:
            pass

    def _index(self) -> Dict[str, List[int]]:
        if self._idx is None:
            ix: Dict[str, List[int]] = {}
            for i, r in enumerate(self.rows):
                for k in (self.names.canon(r["h"]), self.names.canon(r["a"])):
                    ix.setdefault(k, []).append(i)
            self._idx = ix
        return self._idx

    def rows_by_day(self, day: str) -> List[Dict[str, Any]]:
        """开赛日是 day 或前后一天的比分行（找某场比赛的赛果用）。"""
        try:
            d0 = datetime.strptime(day, "%Y-%m-%d")
        except ValueError:
            return []
        keep = {(d0 + timedelta(days=k)).strftime("%Y-%m-%d") for k in (-1, 0, 1)}
        return [r for r in self.rows if r["k"][:10] in keep]

    def form(self, name: str, before: str, n: int = T.FORM_N) -> Optional[Dict[str, Any]]:
        """某队开赛前（before='YYYY-MM-DD HH:MM'）最近 n 场：{n,w,d,l,gf,ga,ppg,gd}。没有返回 None。"""
        k = self.names.canon(name)
        rows = sorted((self.rows[i] for i in self._index().get(k, [])
                       if self.rows[i]["k"] < before and "友谊" not in str(self.rows[i].get("lg", ""))),   # 友谊赛常派替补，不算近况
                      key=lambda r: r["k"], reverse=True)[:n]
        if not rows:
            return None
        w = d = l = gf = ga = 0
        for r in rows:
            mine, theirs = (r["hs"], r["as"]) if self.names.canon(r["h"]) == k else (r["as"], r["hs"])
            gf, ga = gf + mine, ga + theirs
            if mine > theirs:
                w += 1
            elif mine == theirs:
                d += 1
            else:
                l += 1
        c = len(rows)
        return {"n": c, "w": w, "d": d, "l": l, "gf": gf, "ga": ga, "ppg": (3 * w + d) / c, "gd": (gf - ga) / c}

    def h2h(self, home: str, away: str, before: str) -> Optional[Dict[str, int]]:
        hk, ak = self.names.canon(home), self.names.canon(away)
        hw = dr = aw = 0
        for i in self._index().get(hk, []):
            r = self.rows[i]
            if r["k"] >= before:
                continue
            rh, ra = self.names.canon(r["h"]), self.names.canon(r["a"])
            if {rh, ra} != {hk, ak}:
                continue
            mine, theirs = (r["hs"], r["as"]) if rh == hk else (r["as"], r["hs"])
            hw, dr, aw = hw + (mine > theirs), dr + (mine == theirs), aw + (mine < theirs)
        return {"n": hw + dr + aw, "hw": hw, "d": dr, "aw": aw} if hw + dr + aw else None


# ═══════════════════════ 6b. 500 网「完场」页：全部赛事的比分（攒赛果库的主要来源） ═══════════════════════
WC_HOST = "https://live.500.com"
WC_GAP = 2.5            # 两次读完场页之间至少隔多少秒
WC_FIRST_DAYS = 30      # 赛果库里完整读过的「比赛日」还很少时，第一次自动补这么多天
WC_DAILY_DAYS = 3       # 平时每次更新检查最近几个比赛日（漏掉的会补上）
WC_MIN_DONE = 10        # 完整读过的比赛日少于这个数，就当作「第一次」

_WC_LABEL = re.compile(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日\s*[（(]\s*星期")
_WC_TR = re.compile(r"<tr\b([^>]*)>(.*?)</tr\s*>", re.S | re.I)
_WC_MAIN = re.compile(r'class="mainName"[^>]*>(.*?)</span>', re.S)
_WC_AWAY = re.compile(r'class="clientName"[^>]*>(.*?)</span>', re.S)
_WC_S1 = re.compile(r'class="clt1"[^>]*>\s*(\d+)\s*</a>')
_WC_S3 = re.compile(r'class="clt3"[^>]*>\s*(\d+)\s*</a>')
_WC_TIME = re.compile(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")
_WC_90 = re.compile(r"90分钟\s*\[\s*(\d+)\s*-\s*(\d+)\s*\]")


def _wc_txt(h: str) -> str:
    return re.sub(r"\s+", "", htmllib.unescape(re.sub(r"<[^>]+>", "", h or "")))


def parse_wanchang(html: str) -> Tuple[Optional[str], List[Dict[str, Any]], Dict[str, int]]:
    """500 网完场页 → (页面上的比赛日 'YYYY-MM-DD', 已完场比赛 [{k,h,a,hs,as,lg,id,et}], 统计 {rows,done,other,bad})。
    比分：有「90分钟[a-b]」备注（加时/点球）的按 90 分钟比分算胜平负，没有就用页面比分。改期/中断/未开赛的不收。"""
    m = _WC_LABEL.search(html)
    label = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    trs = _WC_TR.findall(html)
    notes: Dict[str, Tuple[int, int]] = {}
    for attrs, body in trs:
        pm = re.search(r'parentid\s*=\s*"a(\d+)"', attrs)
        nm = _WC_90.search(body) if pm else None
        if pm and nm:
            notes[pm.group(1)] = (int(nm.group(1)), int(nm.group(2)))
    rows: List[Dict[str, Any]] = []
    stat = {"rows": 0, "done": 0, "other": 0, "bad": 0}
    for attrs, body in trs:
        im = re.search(r'\bid\s*=\s*"a(\d+)"', attrs)
        if not im or "gy=" not in attrs:
            continue
        stat["rows"] += 1
        sm = re.search(r'<span class="red">\s*([^<]*?)\s*</span>', body)
        if not sm or sm.group(1) != "完":
            stat["other"] += 1
            continue
        hm, am, s1, s3, tm = _WC_MAIN.search(body), _WC_AWAY.search(body), _WC_S1.search(body), _WC_S3.search(body), _WC_TIME.search(body)
        home, away = _wc_txt(hm.group(1)) if hm else "", _wc_txt(am.group(1)) if am else ""
        if not (home and away and s1 and s3 and tm and label):
            stat["bad"] += 1
            continue
        y, mon = int(label[:4]), int(label[5:7])
        mm = int(tm.group(1))
        if mon == 12 and mm == 1:
            y += 1
        elif mon == 1 and mm == 12:
            y -= 1
        hs, as_ = int(s1.group(1)), int(s3.group(1))
        et = im.group(1) in notes
        if et:
            hs, as_ = notes[im.group(1)]
        tds = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.S)
        rows.append({"k": f"{y:04d}-{mm:02d}-{int(tm.group(2)):02d} {int(tm.group(3)):02d}:{tm.group(4)}", "h": home, "a": away,
                     "hs": hs, "as": as_, "lg": _wc_txt(tds[0]) if tds else "", "id": im.group(1), "et": et})
        stat["done"] += 1
    return label, rows, stat


_WC_TIME_ONLY = re.compile(r"(?<![\d:])(\d{1,2}):(\d{2})(?![\d:])")
_WC_GY = re.compile(r"""\bgy\s*=\s*["']([^"']*)["']""")


def parse_wanchang_fixtures(html: str) -> List[Dict[str, Any]]:
    """完场页里还没完场的场次（未开赛/进行中）→ [{k,h,a,lg,id}]。只用来把竞彩的队名对上完场页的队名，不进赛果库。
    没完场的行和完场的行长得不完全一样，所以几处都留了后路：队名先找 mainName/clientName，找不到就用行上的 gy="联赛,主队,客队"；
    开球时间先找「月-日 时:分」，找不到只有「时:分」时按比赛日窗口（当天 10:00 到次日 10:00）补出日期。"""
    m = _WC_LABEL.search(html)
    if not m:
        return []
    label_y, label_m, label_d = int(m.group(1)), int(m.group(2)), int(m.group(3))
    try:
        label_dt = datetime(label_y, label_m, label_d)
    except ValueError:
        return []
    out: List[Dict[str, Any]] = []
    for attrs, body in _WC_TR.findall(html):
        im = re.search(r'\bid\s*=\s*["\']a(\d+)["\']', attrs)
        gm = _WC_GY.search(attrs)
        if not im or not gm:
            continue
        sm = re.search(r'<span class="red">\s*([^<]*?)\s*</span>', body)
        if sm and sm.group(1) in ("完", "改期", "取消", "腰斩"):
            continue
        hm, am = _WC_MAIN.search(body), _WC_AWAY.search(body)
        home, away = _wc_txt(hm.group(1)) if hm else "", _wc_txt(am.group(1)) if am else ""
        gy = [x.strip() for x in htmllib.unescape(gm.group(1)).split(",")]
        if not (home and away) and len(gy) == 3 and gy[1] and gy[2]:
            home, away = gy[1], gy[2]
        if not (home and away):
            continue
        tds = re.findall(r"<td\b[^>]*>(.*?)</td>", body, re.S)
        tm = _WC_TIME.search(body)
        if tm:
            y, mm, dd, hh, mi = label_y, int(tm.group(1)), int(tm.group(2)), int(tm.group(3)), tm.group(4)
            if label_m == 12 and mm == 1:
                y += 1
            elif label_m == 1 and mm == 12:
                y -= 1
        else:
            t2 = next((_WC_TIME_ONLY.search(_wc_txt(c)) for c in tds[:5] if _WC_TIME_ONLY.search(_wc_txt(c))), None)
            if not t2:
                continue
            hh, mi = int(t2.group(1)), t2.group(2)
            d0 = label_dt if hh >= 10 else label_dt + timedelta(days=1)
            y, mm, dd = d0.year, d0.month, d0.day
        out.append({"k": f"{y:04d}-{mm:02d}-{dd:02d} {int(hh):02d}:{mi}", "h": home, "a": away,
                    "lg": _wc_txt(tds[0]) if tds else (gy[0] if gy else ""), "id": im.group(1)})
    return out


def _wc_sample_rows(html: str, n: int = 4) -> List[str]:
    """没完场的行的原始 HTML（读不出赛程时存下来，方便对照真实结构改解析）。"""
    out: List[str] = []
    for attrs, body in _WC_TR.findall(html):
        if not re.search(r'\bid\s*=\s*["\']a\d+["\']', attrs) or "gy" not in attrs:
            continue
        sm = re.search(r'<span class="red">\s*([^<]*?)\s*</span>', body)
        if sm and sm.group(1) == "完":
            continue
        out.append(re.sub(r"\s+", " ", f"<tr {attrs}>{body}</tr>")[:1500])
        if len(out) >= n:
            break
    return out


def _robots_rules(text: str) -> List[Tuple[bool, str]]:
    """robots.txt 里「所有爬虫（*）」这一组的规则。没写 User-agent 的后续行并入上一组；支持 * 和 $ 通配。"""
    groups: Dict[str, List[Tuple[bool, str]]] = {}
    cur: List[str] = []
    started = False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if started:
                cur, started = [], False
            cur.append(v.lower())
            for a in cur:
                groups.setdefault(a, [])
        elif k in ("disallow", "allow"):
            started = True
            for a in cur or ["*"]:
                groups.setdefault(a, []).append((k == "allow", v))
        else:
            started = True
    return groups.get("*", [])


def _robots_ok(rules: List[Tuple[bool, str]], path_query: str) -> bool:
    best, allowed = -1, True
    for allow, rule in rules:
        if not rule:
            continue
        pat = re.escape(rule).replace(r"\*", ".*")
        if pat.endswith(r"\$"):
            pat = pat[:-2] + "$"
        if re.match("^" + pat, path_query) and (len(rule) > best or (len(rule) == best and allow)):
            best, allowed = len(rule), allow
    return allowed


class WanchangFetcher:
    """读 500 网完场页：先看 robots.txt，只读它允许的地址；每次读之间隔 WC_GAP 秒；连续失败就停。"""
    retry_codes: Tuple[int, ...] = (403, 429, 503)       # 遇到这些状态码，隔几秒再试（最多 3 次）；其他网站的读取可以改得更保守

    def __init__(self, *, host: Optional[str] = None, gap: Optional[float] = None, proxy: str = "",
                 sleep: Callable[[float], None] = time.sleep, cancel: Optional[Callable[[], bool]] = None):
        self.host = (host or WC_HOST).rstrip("/")
        self.gap = WC_GAP if gap is None else gap
        self.sleep, self.cancel = sleep, cancel or (lambda: False)
        handlers: List[Any] = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        self.rules: Optional[List[Tuple[bool, str]]] = None
        self.rules_ready = False
        self.pages = 0
        self.fail = 0
        self._last = 0.0

    def _get(self, url: str) -> Tuple[Optional[int], str, str]:
        req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml",
                                                   "Accept-Language": "zh-CN,zh;q=0.9"})
        try:
            with self.opener.open(req, timeout=25) as resp:
                raw, ctype = resp.read(6_000_000), resp.headers.get("Content-Type", "")
                code = resp.getcode()
        except urllib.error.HTTPError as exc:
            return exc.code, "", f"HTTP {exc.code}"
        except (urllib.error.URLError, OSError, ValueError) as exc:
            return None, "", f"{type(exc).__name__}: {exc}"
        return code, Fetcher._decode(raw, ctype), ""

    def _pause(self) -> None:
        wait = self.gap - (time.time() - self._last)
        if wait > 0:
            self.sleep(wait + random.uniform(0, 0.3))
        self._last = time.time()

    def check_robots(self) -> str:
        """返回错误文字；空串表示可以继续。robots.txt 不存在（404）当作没有限制；读不到就不继续。"""
        if self.rules_ready:
            return ""
        code, text, err = self._get(self.host + "/robots.txt")
        if code == 200:
            self.rules = _robots_rules(text)
        elif code in (404, 410):
            self.rules = None
        else:
            return f"读不到网站的 robots.txt（{err or code}），为守规矩就不继续了"
        self.rules_ready = True
        return ""

    def path_for(self, label: Optional[str]) -> str:
        """某个比赛日的页面地址（足球完场页）。篮球完场页（bb_data.py）换一个地址用同一套读取规矩。"""
        return "/wanchang.php" + (f"?e={label}" if label else "")

    def page(self, label: Optional[str] = None) -> Tuple[str, str]:
        """读某个比赛日的完场页（label=None 是网站默认的那一页）。返回 (html, 错误文字)。错误文字非空表示没读成。"""
        if self.cancel():
            return "", "已停止"
        err = self.check_robots()
        if err:
            return "", err
        pq = self.path_for(label)
        if self.rules is not None and not _robots_ok(self.rules, pq):
            return "", f"网站的 robots.txt 不允许读 {pq}"
        for attempt in range(3):
            self._pause()
            code, html, err = self._get(self.host + pq)
            if code == 200 and html:
                self.pages += 1
                self.fail = 0
                return html, ""
            if code in (404, 410):
                return "", f"页面不存在（HTTP {code}）"
            self.fail += 1
            if code in self.retry_codes and attempt < 2:
                self.sleep(4 * (attempt + 1))
                continue
            if code is None and attempt < 1:
                self.sleep(2)
                continue
            return "", err or f"HTTP {code}"
        return "", "多次重试仍失败"


def _wc_day_done(label: str, now: datetime) -> bool:
    """这个「比赛日」（label 当天 10:00 到次日 10:00 前后）到次日中午之后才算踢完、可以记为完整。"""
    try:
        end = datetime.strptime(label, "%Y-%m-%d") + timedelta(days=1, hours=12)
    except ValueError:
        return False
    return now.replace(tzinfo=None) >= end


WC_FIXTURES_FILE = "wc_fixtures.json"       # 完场页里今天/昨天还没踢完的场次（用来对队名），每次更新时刷新


def wanchang_fill(folder: Path, days: int, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
                  proxy: str = "", sleep: Callable[[float], None] = time.sleep, host: Optional[str] = None, gap: Optional[float] = None,
                  force: bool = False, now: Optional[datetime] = None, labels: Optional[List[str]] = None) -> Dict[str, Any]:
    """从完场页补最近 days 个比赛日的比分（再加上「今天」这一天，踢完多少存多少），存进赛果库。已经完整读过的日子跳过（force=True 重读）。
    返回 {pages, ok, rows, added, total, skipped, errors, stopped, blocked, span}。任何问题都不抛异常。"""
    say = log or (lambda m: None)
    cancel = cancel or (lambda: False)
    now = now or datetime.now(BJT)
    res: Dict[str, Any] = {"pages": 0, "ok": 0, "rows": 0, "added": 0, "total": 0, "skipped": 0, "errors": [], "stopped": False,
                           "blocked": False, "span": "", "aliases": 0}
    try:
        db = ResultsDB(Path(folder))
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"赛果库打不开：{exc}")
        return res
    fetcher = WanchangFetcher(host=host, gap=gap, proxy=proxy, sleep=sleep, cancel=cancel)
    today = now.astimezone(BJT).replace(tzinfo=None) if now.tzinfo else now
    today_s = today.strftime("%Y-%m-%d")
    if labels is None:
        labels = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, max(1, int(days)) + 1)]   # 含今天这一天（踢完多少算多少，下次再补）
    fixtures: List[Dict[str, Any]] = []
    seen_days: set = set()
    try:
        for label in labels:
            if cancel():
                res["stopped"] = True
                break
            if not force and label in db.wc_days and _wc_day_done(label, today):
                res["skipped"] += 1
                continue
            html, err = fetcher.page(label)
            if err == "已停止":
                res["stopped"] = True
                break
            res["pages"] += 1
            if err:
                if "robots" in err:
                    res["errors"].append(f"{label}：{err}")
                    res["blocked"] = True
                    say(f"  ⚠ {label}：没读到（{err}）")
                    break
                if label != today_s:                         # 「今天」这一页读不到不算问题（只是加分项）
                    res["errors"].append(f"{label}：{err}")
                    say(f"  ⚠ {label}：没读到（{err}）")
                if fetcher.fail >= 3:
                    say("  连续 3 次没读到，先停下（网络或网站的问题，过一会再试）")
                    break
                continue
            page_label, rows, stat = parse_wanchang(html)
            if page_label != label:
                if label != today_s:
                    res["errors"].append(f"{label}：页面显示的是 {page_label or '（认不出日期）'}，跳过")
                    say(f"  ⚠ {label}：页面显示的日期是 {page_label or '认不出'}，这天跳过")
                continue
            res["ok"] += 1
            res["rows"] += len(rows)
            if label >= (today - timedelta(days=1)).strftime("%Y-%m-%d"):
                fx = parse_wanchang_fixtures(html)
                fixtures += fx
                if stat["other"] >= 20 and not fx:                  # 页面上有一大堆没完场的行，却一行也读不出来：把样例存下来
                    try:
                        L.p(folder, "wc_debug_rows.txt").write_text(
                            f"{label} 页面里 {stat['other']} 行没完场，赛程一行都没认出来。样例行：\n\n" + "\n\n".join(_wc_sample_rows(html)) + "\n", encoding="utf-8")
                    except OSError:
                        pass
                    say(f"  ⚠ {label}：页面里有 {stat['other']} 行没完场的比赛，但认不出队名/开球时间（样例已存进 wc_debug_rows.txt，发给我就能修）")
            added = db.add(rows)
            res["added"] += added
            if rows and _wc_day_done(label, today):
                db.wc_days[label] = len(rows)
            seen_days.update(r["k"][:10] for r in rows)
            bad = f"，{stat['bad']} 行没认出" if stat["bad"] else ""
            say(f"  {label}：读到 {len(rows)} 场已完场（改期/中断 {stat['other']} 场），新存 {added} 场{bad}")
            if res["ok"] % 5 == 0:
                db.save()
    except Exception as exc:  # noqa: BLE001
        res["errors"].append(f"出错：{exc}")
        say(f"  ⚠ 读完场页出错：{exc}")
    finally:
        try:
            if res["added"] or db.wc_days:
                db.save()
        except Exception:  # noqa: BLE001
            pass
        if fixtures:
            try:
                L.p(folder, WC_FIXTURES_FILE).write_text(json.dumps({"t": today.strftime("%Y-%m-%d %H:%M"), "rows": fixtures}, ensure_ascii=False,
                                                                       separators=(",", ":")), encoding="utf-8")
            except OSError:
                pass
    res["aliases"] = db.learned
    res["total"] = len(db.rows)
    days_ = sorted({r["k"][:10] for r in db.rows})
    res["span"] = f"{days_[0]} ～ {days_[-1]}" if days_ else ""
    return res


WC_BACK_DAYS = 60       # 赛果库往前补到多少天（每次更新最多补 WC_BACK_PER_RUN 天，几次更新就补齐；也可以点「补历史赛果」一次补完）
WC_BACK_PER_RUN = 12


def wanchang_daily(folder: Path, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
                   proxy: str = "", sleep: Callable[[float], None] = time.sleep, host: Optional[str] = None,
                   gap: Optional[float] = None, now: Optional[datetime] = None) -> Dict[str, Any]:
    """每次更新时调用：存最近几个比赛日的全部比分（含今天踢完的），并把更早的日子逐步补到 WC_BACK_DAYS 天。
    赛果库里还没攒多少时（第一次），一次补最近 30 天。"""
    say = log or (lambda m: None)
    now_ = now or datetime.now(BJT)
    today = (now_.astimezone(BJT).replace(tzinfo=None) if now_.tzinfo else now_)
    try:
        done_days = set(ResultsDB(Path(folder)).wc_days)
    except Exception:  # noqa: BLE001
        done_days = set()
    first = len(done_days) < WC_MIN_DONE
    recent = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(0, WC_DAILY_DAYS + 1)]
    older = [(today - timedelta(days=k)).strftime("%Y-%m-%d") for k in range(WC_DAILY_DAYS + 1, (WC_FIRST_DAYS if first else WC_BACK_DAYS) + 1)]
    older = [d for d in older if d not in done_days][: (WC_FIRST_DAYS if first else WC_BACK_PER_RUN)]
    labels = recent + older
    verbose = first or bool(older)
    say("读 500 网完场页，攒两队近况用的比分" + (f"（{'第一次：补最近 %d 天' % WC_FIRST_DAYS if first else '再往前补 %d 天' % len(older)}，约 {max(1, round(len(labels) * (WC_GAP + 1) / 60))} 分钟）……" if verbose else "……"))
    r = wanchang_fill(folder, 0, log=(say if verbose else None), cancel=cancel, proxy=proxy, sleep=sleep, host=host, gap=gap, now=now, labels=labels)
    if r["errors"] and not r["ok"]:
        say(f"⚠ 完场页没读成：{r['errors'][0]}（不影响今天的推单，只是赛果库没增加）")
    elif not r["ok"] and r["skipped"]:
        say(f"赛果库：最近几天的比分之前都存过了，共 {r['total']} 场" + (f"（{r['span']}）" if r["span"] else ""))
    else:
        say(f"赛果库：读了 {r['ok']} 页，新存 {r['added']} 场，共 {r['total']} 场" + (f"（{r['span']}）" if r["span"] else ""))
    if r.get("aliases"):
        say(f"赛果库：同一场比赛在竞彩和完场页里写法不同，自动对上了 {r['aliases']} 个队名（记在 {AUTO_ALIAS_FILE}，重复的比分已合并）")
    return r


def db_coverage(folder: Path, matches: List[Dict[str, Any]]) -> Tuple[int, int, List[str]]:
    """按赛果库算：这些比赛里，有几场两队都有 ≥DB_MIN_FORM 场近况。返回 (够的场数, 总场数, 库里完全没有的队名)。"""
    db = ResultsDB(Path(folder))
    ok, miss = 0, []
    for m in matches:
        before = m["kick"].strftime("%Y-%m-%d %H:%M") if hasattr(m.get("kick"), "strftime") else "9999"
        have = True
        for t in (m["home"], m["away"]):
            f = db.form(t, before)
            if not f or f["n"] < DB_MIN_FORM:
                have = False
                if not f and t not in miss:
                    miss.append(t)
        ok += have
    return ok, len(matches), miss


# ═══════════════════════ 7. 提供者 ═══════════════════════
def _best(recs: List[Dict[str, int]]) -> Optional[Dict[str, int]]:
    return max(recs, key=lambda r: r["n"]) if recs else None


def _ppg(r: Dict[str, int]) -> float:
    return (3 * r["w"] + r["d"]) / r["n"]


class SinaProvider:
    """notes_for(matches, day) → (notes, problems)，和 team_data.Provider 同一个接口。"""

    def __init__(self, folder: Path, *, log: Optional[Callable[[str], None]] = None, cancel: Optional[Callable[[], bool]] = None,
                 proxy: str = "", sleep: Callable[[float], None] = time.sleep, index_urls: Tuple[str, ...] = INDEX_URLS,
                 art_re: "re.Pattern[str]" = ART_RE, host_ok: "re.Pattern[str]" = HOST_OK, max_pages: int = MAX_PAGES,
                 delay: float = PAGE_DELAY, use_db: bool = True):
        self.folder = Path(folder)
        self.log = log or (lambda m: None)
        self.names = ZhNames(self.folder)
        self.f = Fetcher(L.p(self.folder, "data_cache") / "sina", log=self.log, cancel=cancel, proxy=proxy, sleep=sleep,
                         max_pages=max_pages, delay=delay, host_ok=host_ok)
        self.index_urls, self.art_re = index_urls, art_re
        self.db = ResultsDB(self.folder, self.names) if use_db else None
        self.model: Any = None                 # 数据模型（match_model.Model），在 notes_for 里用赛果库建
        self.model_check: Optional[Dict[str, Any]] = None
        self.source_text = "新浪彩票公开文章（竞彩情报/足彩伤停/交战记录）"
        self.debug_dir = L.p(self.folder, "sina_debug")
        self._dumped = 0
        self._skipped = 0
        self.api_backup = False          # 有接口来补时（两个都用），篮球的提示不用说

    def __call__(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        return self.notes_for(matches, day)

    # —— 发现文章 ——
    def _kind(self, title: str) -> str:
        if "竞彩情报" in title:
            return "intel"
        if "足彩伤停" in title or ("伤停" in title and "足彩" in title):
            return "injury"
        if "交战记录" in title:
            return "h2h"
        return ""

    def _collect_links(self, page: Dict[str, Any], found: Dict[str, Dict[str, Any]]) -> None:
        for url, title in page.get("links", []):
            m = self.art_re.match(url)
            if not m or url in found:
                continue
            kind = self._kind(title)
            if kind:
                found[url] = {"url": url, "title": title, "date": f"{m.group(1)}-{m.group(2)}-{m.group(3)}", "kind": kind}

    def _ttl(self, date: str, day: str) -> float:
        return TTL_ART_FRESH if date >= _shift(day, -1) else TTL_ART_OLD

    def _debug(self, kind: str, art: Dict[str, Any], text: str, raw: str = "") -> None:
        """读到了文章却没认出内容：把文字存下来，方便改规则。text = 截出的正文；raw = 网页全部文字（正文截错时用得上）。"""
        try:
            self.debug_dir.mkdir(parents=True, exist_ok=True)
            self._dumped += 1
            name = f"{art['date']}_{kind}_{hashlib.sha1(art['url'].encode()).hexdigest()[:6]}.txt"
            body = f"{art['title']}\n{art['url']}\n\n{text[:9000]}"
            if raw and raw != text:
                body += f"\n\n======== 网页全部文字（前 9000 字） ========\n{raw[:9000]}"
            (self.debug_dir / name).write_text(body, encoding="utf-8")
            files = sorted(self.debug_dir.glob("*.txt"), key=lambda p: p.stat().st_mtime)
            for old in files[:-DEBUG_KEEP]:
                old.unlink()
        except OSError:
            pass

    def _discover(self, day: str, problems: List[str]) -> Dict[str, Dict[str, Any]]:
        found: Dict[str, Dict[str, Any]] = {}
        ok = 0
        last_exc: Optional[Exception] = None
        for u in self.index_urls:
            try:
                self._collect_links(self.f.get(u, TTL_INDEX), found)
                ok += 1
            except T.DataError as exc:
                if exc.fatal or exc.kind == "net":
                    raise RuntimeError(str(exc))
                last_exc = exc
        if not ok:
            raise RuntimeError(f"新浪彩票的栏目页一个都没读到（{last_exc}）。可能网站改版或网络被拦；可以在设置里换成「接口」来源。")
        lo, hi = _shift(day, -3), _shift(day, 1)
        return {u: a for u, a in found.items() if lo <= a["date"] <= hi}

    # —— 主流程 ——
    def notes_for(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """足球走新浪文章 + 自存赛果库 + 数据模型；篮球走 500 网篮球完场页存下来的赛果库（bb_data.py）。"""
        original_fb = [m for m in matches if m.get("sport") != "basketball"]
        fb = [resolve_match_names(m) for m in original_fb]
        original_keys = {(m["home"], m["away"]): (original["home"], original["away"])
                         for m, original in zip(fb, original_fb)}
        bb = [m for m in matches if m.get("sport") == "basketball"]
        notes: List[Dict[str, Any]] = []
        problems: List[str] = []
        src_bits: List[str] = []
        if fb:
            n1, p1 = self._notes_football(fb, day)
            for note in n1:
                key = tuple(note.get("mk") or ())
                if key in original_keys:
                    note["mk"] = list(original_keys[key])
            notes += n1
            problems += p1
            src_bits.append(self.source_text)
        elif not bb:
            return [], ["新浪的文章只有足球，这批比赛里没有足球。"]
        if bb:
            n2: List[Dict[str, Any]] = []
            p2: List[str] = []
            if BB is None:
                p2 = [f"篮球数据模块（bb_data.py）没放在同一个文件夹里，{len(bb)} 场篮球没有数据对比。"]
            else:
                try:
                    n2, p2 = BB.notes_for(self.folder, bb, log=self.log)
                except Exception as exc:  # noqa: BLE001  篮球出错不能拖垮足球
                    n2, p2 = [], [f"篮球数据对比出错了（{type(exc).__name__}: {exc}），{len(bb)} 场篮球这次没有数据对比。"]
            got = {tuple(n.get("mk") or ()) for n in n2}
            left = [m for m in bb if (m["home"], m["away"]) not in got]
            notes += n2
            problems += p2
            if left and not self.api_backup and not p2:
                problems.append(f"{len(left)} 场篮球没有数据对比（要用接口补请在设置里选「两个都用」并填接口密钥）。")
            if n2:
                src_bits.append(f"500网篮球赛果库 {len(n2)} 场（自建模型）")
        if src_bits:
            self.source_text = "；".join(src_bits)
        return notes, problems

    def _notes_football(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        problems: List[str] = []
        notes: List[Dict[str, Any]] = []
        self._skipped = 0
        fb = matches
        if self.db is not None:
            try:
                nl = self._learn_aliases(fb)
            except Exception:  # noqa: BLE001
                nl = 0
            if nl:
                self.log(f"  对上了 {nl} 个队名（竞彩叫法 = 完场页叫法，记在 {AUTO_ALIAS_FILE}，以后自动用）"
                         + (f"；其中 {self._learn_late} 个是按「同一支队前后 3 小时内只踢一场」对上的（完场页的开球时间和竞彩差了一点）" if getattr(self, "_learn_late", 0) else ""))
            elif getattr(self, "_learn_info", ""):
                self.log(f"  队名对齐：{self._learn_info}；这次没有新对上的队名")
            used = self._used_auto_aliases(fb)
            if used:
                self.log("  今天用到的自动队名对应（竞彩叫法＝完场页叫法；认错了就删掉 " + AUTO_ALIAS_FILE + " 里那一行）："
                         + "、".join(f"{a}＝{b}" for a, b in used[:8]) + ("等" if len(used) > 8 else ""))
            self.db = ResultsDB(self.folder, self.names)      # 重新读（刚存进去的今天的赛果也算）
            self._build_model()
        if not fb:
            return [], ["新浪的文章只有足球，这批比赛里没有足球。"]
        names = self.names
        vmap = {(m["home"], m["away"]): (names.variants(m["home"]), names.variants(m["away"])) for m in fb}
        self.log("  新浪彩票：读栏目页，找当天的竞彩情报/足彩伤停/交战记录……")
        arts = self._discover(day, problems)
        by_kind = {k: [a for a in arts.values() if a["kind"] == k] for k in ("intel", "injury", "h2h")}
        self.log(f"  找到 竞彩情报 {len(by_kind['intel'])} 篇、足彩伤停 {len(by_kind['injury'])} 篇、交战记录 {len(by_kind['h2h'])} 篇")

        # 1) 表格式文章（每期 14 场）：全读
        inj_tab: Dict[str, Dict[str, Any]] = {}
        h2h_rows: List[Dict[str, Any]] = []
        for a in sorted(by_kind["injury"], key=lambda x: x["date"]):
            try:
                txt = self.f.get(a["url"], self._ttl(a["date"], day))["text"]
            except T.DataError as exc:
                self._fatal_or_note(exc, problems, "足彩伤停")
                continue
            tab = parse_injury_table(txt)
            if not tab:
                self._debug("injury", a, txt)
                problems.append(f"读到了足彩伤停《{a['title'][:20]}》但没认出表格（读到的文字已存进 sina_debug 文件夹）。")
            inj_tab.update(tab)                            # 日期靠后的覆盖前面的
        for a in sorted(by_kind["h2h"], key=lambda x: x["date"]):
            try:
                txt = self.f.get(a["url"], self._ttl(a["date"], day))["text"]
            except T.DataError as exc:
                self._fatal_or_note(exc, problems, "交战记录")
                continue
            rows = parse_h2h_table(txt)
            if not rows:
                self._debug("h2h", a, txt)
                problems.append(f"读到了交战记录《{a['title'][:20]}》但没认出表格（读到的文字已存进 sina_debug 文件夹）。")
            h2h_rows += rows

        # 2) 竞彩情报：标题里点了我们的球队的，才读
        title_hit: Dict[Tuple[str, str], List[Dict[str, Any]]] = {}
        for key, (vh, av) in vmap.items():
            for a in by_kind["intel"]:
                if self._title_has(a["title"], key, vh, av):
                    title_hit.setdefault(key, []).append(a)
        texts: Dict[str, str] = {}
        raws: Dict[str, str] = {}
        queue = sorted({a["url"] for lst in title_hit.values() for a in lst})
        fetched = 0
        for url in queue:
            a = arts[url]
            try:
                page = self.f.get(url, self._ttl(a["date"], day))
            except T.DataError as exc:
                self._fatal_or_note(exc, problems, "竞彩情报")
                if exc.kind == "quota":
                    break
                continue
            fetched += 1
            texts[url] = article_body(page["text"])
            raws[url] = page["text"]
            self.log(f"    读了 [{fetched}/{len(queue)}] {a['title'][:30]}")
            self._collect_links(page, arts)                # 文章里的「相关推荐」也可能有别的竞彩情报
        # 文章里新发现的竞彩情报（标题里点了我们球队的）再读一轮
        extra = []
        for key, (vh, av) in vmap.items():
            for a in arts.values():
                if a["kind"] == "intel" and a["url"] not in texts and a not in title_hit.get(key, []) and a["date"] >= _shift(day, -1):
                    if self._title_has(a["title"], key, vh, av):
                        title_hit.setdefault(key, []).append(a)
                        extra.append(a["url"])
        for url in sorted(set(extra)):
            a = arts[url]
            try:
                pg = self.f.get(url, self._ttl(a["date"], day))
                texts[url] = article_body(pg["text"])
                raws[url] = pg["text"]
            except T.DataError as exc:
                self._fatal_or_note(exc, problems, "竞彩情报")
                if exc.kind == "quota":
                    break

        # 3) 逐场对上、认数字、判定
        parsed_any = False
        why: Dict[str, List[str]] = {"noart": [], "nomatch": [], "oneside": [], "norec": []}
        inj_by_canon = {names.canon(v["team"]): v for v in inj_tab.values()}
        for m in fb:
            if self.f.cancel():
                raise RuntimeError("已停止。")
            vh, av = vmap[(m["home"], m["away"])]
            cands = title_hit.get((m["home"], m["away"]), [])
            hit = self._resolve_intel(m, vh, av, cands, texts)
            sides = None
            src_intel = None
            vs = f"{m['home']}vs{m['away']}"
            if hit is not None:
                art, vh2, av2 = hit
                sides = parse_intel(texts[art["url"]], vh2, av2)
                got = sum(len(s["rec"]) + len(s["venue"]) for s in sides.values())
                if got == 0 and not any(s["key"] or s["out"] or s["doubt"] for s in sides.values()):
                    self._debug("intel", art, texts[art["url"]], raws.get(art["url"], ""))
                    problems.append(f"{vs}：读到了竞彩情报但没认出战绩/伤停（文字已存进 sina_debug 文件夹）。")
                    sides = None
                else:
                    parsed_any = True
                    src_intel = art
            hi = inj_by_canon.get(names.canon(m["home"]))
            ai = inj_by_canon.get(names.canon(m["away"]))
            h2h = self._h2h_for(m, h2h_rows, sides)
            kick = m["kick"].astimezone(BJT).strftime("%Y-%m-%d %H:%M")
            note = self._make_note(m, sides, hi, ai, h2h, kick, problems)
            if note is not None:
                notes.append(note)
                continue
            # 没出数据：弄清是哪种原因（运行日志里写出来；读到了但没对上的，把文章文字存进 sina_debug）
            if hit is None:
                if cands:
                    why["nomatch"].append(vs)
                    c0 = cands[0]
                    self._debug("nomatch", c0, texts.get(c0["url"], ""), raws.get(c0["url"], ""))
                    self.log(f"    {vs}：标题点到了这场，但正文里没同时找到两队的名字（读了《{c0['title'][:24]}》）")
                else:
                    why["noart"].append(vs)
                    self.log(f"    {vs}：新浪没有这场的竞彩情报文章")
            elif sides is not None:
                hs_ = self._stats(sides["h"], True)
                as_ = self._stats(sides["a"], False)
                if (hs_ is None) != (as_ is None):
                    miss = m["away"] if as_ is None else m["home"]
                    why["oneside"].append(vs)
                    self.log(f"    {vs}：文章里只写了一队的近况，{miss}的战绩没写（两队都要有才能对比）")
                else:
                    why["norec"].append(vs)
                    self.log(f"    {vs}：文章里两队都没写「几胜几平几负」")
                self._debug("partial", hit[0], texts[hit[0]["url"]], raws.get(hit[0]["url"], ""))
        if not notes and fb:
            if not by_kind["intel"] and not inj_tab:
                problems.append("新浪栏目页里今天没找到竞彩情报/足彩伤停文章（可能还没发，下午再试；或网站改版）。")
            elif not parsed_any:
                problems.append("读到了文章，但没有一篇能对上今天的比赛（队名叫法不同？可把对照写进 team_alias.json）。")
        parts = []
        if why["noart"]:
            parts.append(f"{len(why['noart'])} 场新浪没写这场的竞彩情报（只写热门场次）")
        if why["oneside"]:
            parts.append(f"{len(why['oneside'])} 场文章只写了一队的近况")
        if why["norec"]:
            parts.append(f"{len(why['norec'])} 场文章里没有「几胜几平几负」")
        if why["nomatch"]:
            parts.append(f"{len(why['nomatch'])} 场文章标题点到了但正文队名没对上（文章已存进 sina_debug）")
        if parts:
            problems.append("新浪没给出数据的原因：" + "；".join(parts) + "。")
        got = {tuple(n.get("mk") or ()) for n in notes}
        problems += self._db_diag([m for m in fb if (m["home"], m["away"]) not in got])
        if self._skipped:
            problems.append(f"有 {self._skipped} 篇文章按 robots.txt 不让读，已跳过。")
        db_n = sum(1 for n in notes if n.get("src") == "db")
        sina_n = len(notes) - db_n
        self.source_text = f"新浪彩票公开文章（竞彩情报/足彩伤停/交战记录）{sina_n} 场" + (f"、自存赛果 {db_n} 场" if db_n else "")
        problems.append(f"本次读了 {self.f.pages} 个网页。")
        for n in notes:
            n.pop("src", None)
        return notes, problems

    def _build_model(self) -> None:
        """用赛果库建数据模型并回测（回测不过关就只显示、不参与判断）。任何问题都不影响出推单。"""
        self.model, self.model_check = None, None
        if MM is None or self.db is None or not self.db.rows:
            return
        try:
            self.model_check = MM.run_check(self.folder, self.db, log=self.log)
            self.model = MM.build_model(self.db, self.model_check)
            self.log("  " + MM.check_text(self.model_check))
        except Exception as exc:  # noqa: BLE001
            self.model, self.model_check = None, None
            self.log(f"  数据模型没建成（{exc}），这次不用")

    def _learn_aliases(self, fb: List[Dict[str, Any]]) -> int:
        """用完场页里今天的赛程（同一开球时间的场次）把竞彩的队名对上完场页的队名。
        同一时刻一支球队只踢一场：只要一边写法一样，另一边就是同一场的对手；两边都不一样，要两边都像、且比第二名明显更像才算。"""
        self._learn_info = ""
        self._fx_rows = []
        try:
            fx = json.loads(L.p(self.folder, WC_FIXTURES_FILE).read_text(encoding="utf-8")).get("rows", [])
        except (OSError, ValueError, AttributeError):
            self._learn_info = f"没有读到完场页的赛程文件（{WC_FIXTURES_FILE}），队名没法自动对齐"
            return 0
        by_k: Dict[str, List[Dict[str, Any]]] = {}
        for r in fx:
            if isinstance(r, dict) and r.get("k") and r.get("h") and r.get("a"):
                by_k.setdefault(r["k"], []).append(r)
        names, pairs = self.names, []
        same_time = 0
        for m in fb:
            cands = by_k.get(m["kick"].astimezone(BJT).strftime("%Y-%m-%d %H:%M"))
            if not cands:
                continue
            same_time += 1
            scored = []
            for r in cands:
                if not (marks_ok(m["home"], r["h"]) and marks_ok(m["away"], r["a"])):
                    continue
                sh, sa = name_sim(m["home"], r["h"]), name_sim(m["away"], r["a"])
                exact = names.canon(m["home"]) == names.canon(r["h"]) or names.canon(m["away"]) == names.canon(r["a"])
                scored.append((sh + sa + (1.0 if exact else 0.0), exact, sh, sa, r))
            if not scored:
                continue
            scored.sort(key=lambda x: -x[0])
            if len(scored) > 1 and scored[0][0] - scored[1][0] < 0.25:
                continue
            _, exact, sh, sa, r = scored[0]
            if not exact and not (sh + sa >= 1.2 and min(sh, sa) >= 0.4):
                continue
            for ours, theirs in ((m["home"], r["h"]), (m["away"], r["a"])):
                if names.canon(ours) != names.canon(theirs):
                    pairs.append((ours, theirs))
        # 第二轮：开球时间对不上（差 3 小时内）也行。只要有一边的队名和完场页某场「完全一样」，而且在这段时间里只有这一场，
        # 另一边就是它的对手；我们这边那个名字必须是「赛果库还不认识的」（认识的就不动，免得把别的球队改成这队）。
        self._fx_rows = []
        for r in fx:
            if isinstance(r, dict) and r.get("k") and r.get("h") and r.get("a"):
                try:
                    self._fx_rows.append((datetime.strptime(r["k"], "%Y-%m-%d %H:%M"), r))
                except ValueError:
                    continue
        late = 0
        self._learn_late = 0
        try:
            index = self.db._index() if self.db is not None else {}
        except Exception:  # noqa: BLE001
            index = {}
        for m in fb:
            if all(names.canon(t) in index for t in (m["home"], m["away"])):
                continue
            hit = self._fx_near_exact(m, 3 * 3600)
            if len(hit) != 1:
                continue
            r, home_same = hit[0]
            if self._fx_appear(m["home"] if home_same else m["away"], m, 3 * 3600) != 1:      # 这支队在这段时间里出现在不止一场（任何一边）→ 不敢对
                continue
            ours, theirs = (m["away"], r["a"]) if home_same else (m["home"], r["h"])
            if names.canon(ours) in index or names.canon(ours) == names.canon(theirs):
                continue
            if (ours, theirs) not in pairs:
                pairs.append((ours, theirs))
                late += 1
        self._learn_late = late
        self._learn_info = (f"完场页的赛程里有 {len(fx)} 场；竞彩的 {len(fb)} 场里有 {same_time} 场在完场页找得到同一开球时间的比赛"
                            f"（找不到的多半是完场页没收这场，或开球时间写法不一样）"
                            + (f"；另有 {late} 个队名是按「同一支队在前后 3 小时内只踢一场」对上的" if late else ""))
        learned = names.learn(pairs) if pairs else 0
        if learned and self.db is not None:
            self.db._idx = None
        return learned

    def _used_auto_aliases(self, fb: List[Dict[str, Any]]) -> List[Tuple[str, str]]:
        """team_alias_auto.json 里、今天这批比赛的队名用到的那几条（日志里列出来，方便核对有没有对错）。"""
        try:
            data = json.loads(L.p(self.folder, AUTO_ALIAS_FILE).read_text(encoding="utf-8"))
        except (OSError, ValueError, AttributeError):
            return []
        if not isinstance(data, dict):
            return []
        out: List[Tuple[str, str]] = []
        seen: set = set()
        for m in fb:
            for t in (m["home"], m["away"]):
                if t in data and t not in seen:
                    seen.add(t)
                    out.append((t, str(data[t]).split("|")[0]))
        return out

    def _fx_appear(self, name: str, m: Dict[str, Any], within: float) -> int:
        """完场页赛程里、开球时间相差 within 秒以内，这支队（队名完全一样）出现在几场里（主客队都算）。"""
        kick = m["kick"].astimezone(BJT).replace(tzinfo=None)
        c = self.names.canon(name)
        return sum(1 for dt, r in getattr(self, "_fx_rows", [])
                   if abs((dt - kick).total_seconds()) <= within and c in (self.names.canon(r["h"]), self.names.canon(r["a"])))

    def _fx_near_exact(self, m: Dict[str, Any], within: float) -> List[Tuple[Dict[str, Any], bool]]:
        """完场页赛程里、开球时间相差 within 秒以内、并且有「一边队名和竞彩完全一样（另一边不一样）」的场次：[(那一行, 主队是不是一样)]。"""
        out: List[Tuple[Dict[str, Any], bool]] = []
        kick = m["kick"].astimezone(BJT).replace(tzinfo=None)
        for dt, r in getattr(self, "_fx_rows", []):
            if abs((dt - kick).total_seconds()) > within:
                continue
            if not (marks_ok(m["home"], r["h"]) and marks_ok(m["away"], r["a"])):
                continue
            eh = self.names.canon(m["home"]) == self.names.canon(r["h"])
            ea = self.names.canon(m["away"]) == self.names.canon(r["a"])
            if eh != ea:
                out.append((r, eh))
        return out

    def _fx_clue(self, m: Dict[str, Any], index: Dict[str, List[int]]) -> None:
        """队名在赛果库里找不到时，再写一行线索：完场页赛程里（前后 3 小时）有没有含「库里认识的那支队」的比赛，它的对手写成了什么。"""
        try:
            known = [t for t in (m["home"], m["away"]) if self.names.canon(t) in index]
            if not known or not getattr(self, "_fx_rows", None):
                return
            kick = m["kick"].astimezone(BJT).replace(tzinfo=None)
            found = []
            for dt, r in self._fx_rows:
                if abs((dt - kick).total_seconds()) > 3 * 3600:
                    continue
                if any(self.names.canon(t) in (self.names.canon(r["h"]), self.names.canon(r["a"])) for t in known):
                    found.append(f"{r['h']}vs{r['a']}（{r.get('lg', '')} {dt:%H:%M}）")
            if found:
                self.log(f"      完场页赛程里含 {'/'.join(known)} 的：{'、'.join(found[:3])}")
            else:
                self.log(f"      完场页赛程（前后 3 小时）里没找到含 {'/'.join(known)} 的比赛：完场页可能没收这场，或把 {'/'.join(known)} 写成了别的名字")
        except Exception:  # noqa: BLE001
            pass

    def _db_diag(self, ms: List[Dict[str, Any]]) -> List[str]:
        """没出数据的比赛：赛果库里这两队各有几场？是队名在库里找不到（叫法不同），还是比赛场数不够？写进日志，方便对症处理。"""
        if self.db is None or not ms:
            return []
        db = self.db
        index = db._index()
        raw: Dict[str, str] = {}
        for r in db.rows:
            for t in (r["h"], r["a"]):
                raw.setdefault(self.names.canon(t), t)
        n_name = n_few = 0
        shown = 0
        for m in ms:
            kick = m["kick"].astimezone(BJT).strftime("%Y-%m-%d %H:%M")
            parts, why = [], ""
            for t in (m["home"], m["away"]):
                f = db.form(t, kick)
                n = f["n"] if f else 0
                if n >= DB_MIN_FORM:
                    parts.append(f"{t} {n} 场")
                    continue
                if self.names.canon(t) not in index:
                    near = sorted(((name_sim(t, c), c) for c in raw if marks_ok(t, c)), reverse=True)[:2]
                    near = [raw[c] for sc, c in near if sc >= 0.5]
                    parts.append(f"{t}：库里没有这个名字" + (f"（像：{'、'.join(near)}）" if near else "")
                                 + ("；此简称有一线队/梯队歧义，需要赛程中的完整队名，不自动合并" if clean(t) == "社会" else ""))
                    why = "name"
                else:
                    parts.append(f"{t} 只有 {n} 场（要 ≥{DB_MIN_FORM}）")
                    why = why or "few"
            if why == "name":
                n_name += 1
            elif why == "few":
                n_few += 1
            if shown < 12:
                self.log(f"    赛果库：{m['home']}vs{m['away']} → " + "；".join(parts))
                shown += 1
                if why == "name":
                    self._fx_clue(m, index)
        out = []
        bits = []
        if n_name:
            bits.append(f"{n_name} 场有队名在赛果库里找不到（叫法和完场页不同）")
        if n_few:
            bits.append(f"{n_few} 场有球队在库里的比赛不到 {DB_MIN_FORM} 场")
        if bits:
            out.append("赛果库没能补上的原因：" + "；".join(bits) + "。")
        return out

    def _title_has(self, title: str, key: Tuple[str, str], vh: List[str], av: List[str]) -> bool:
        """标题里点了这场比赛的哪支球队（含「去掉最后一个字」的叫法）。"""
        t = norm(title)
        if any(v in t for v in vh) or any(v in t for v in av):
            return True
        for nm in key:
            p = self.names.partial(nm)
            if p and p in t:
                return True
        return False

    def _fatal_or_note(self, exc: T.DataError, problems: List[str], what: str) -> None:
        if exc.fatal or exc.kind == "net" or "已停止" in str(exc):
            raise RuntimeError(str(exc))
        if "robots" in str(exc):
            self._skipped += 1
            return
        if exc.kind != "quota":
            problems.append(f"{what}读取失败：{exc}")
        else:
            problems.append(str(exc))

    def _resolve_intel(self, m: Dict[str, Any], vh: List[str], av: List[str], cands: List[Dict[str, Any]], texts: Dict[str, str]
                       ) -> Optional[Tuple[Dict[str, Any], List[str], List[str]]]:
        best: Optional[Tuple[int, str, Dict[str, Any], List[str], List[str]]] = None
        loose: List[Tuple[Dict[str, Any], List[str], List[str]]] = []
        for a in cands:
            body = norm(texts.get(a["url"], ""))
            if not body:
                continue
            ch, ca = sum(body.count(v) for v in vh), sum(body.count(v) for v in av)
            if ch and ca:
                score = ch + ca
                key = (score, a["date"])
                if best is None or key > (best[0], best[1]):
                    best = (score, a["date"], a, vh, av)
                continue
            # 兜底：一边找不到全名，试「去掉最后一个字」的叫法（凯尔特人→凯尔特）
            for side, miss, vs in (("a", ca, av), ("h", ch, vh)):
                if miss:
                    continue
                other = m["away"] if side == "a" else m["home"]
                p = self.names.partial(other)
                if p and p in body and ((side == "a" and ch) or (side == "h" and ca)):
                    loose.append((a, vh, av + [p]) if side == "a" else (a, vh + [p], av))
        if best is not None:
            return best[2], best[3], best[4]
        if len(loose) == 1:
            return loose[0]
        return None

    def _h2h_for(self, m: Dict[str, Any], rows: List[Dict[str, Any]], sides: Optional[Dict[str, Dict[str, Any]]]) -> Optional[Dict[str, int]]:
        hk, ak = self.names.canon(m["home"]), self.names.canon(m["away"])
        for r in rows:
            rh, ra = self.names.canon(r["h"]), self.names.canon(r["a"])
            if (rh, ra) == (hk, ak):
                return {"n": r["n"], "hw": r["w"], "d": r["d"], "aw": r["l"], "y": r.get("y", 0)}
            if (rh, ra) == (ak, hk):
                return {"n": r["n"], "hw": r["l"], "d": r["d"], "aw": r["w"], "y": r.get("y", 0)}
        if sides:
            h, a = sides["h"]["h2h"], sides["a"]["h2h"]
            if h:
                return {"n": h["w"] + h["d"] + h["l"], "hw": h["w"], "d": h["d"], "aw": h["l"]}
            if a:
                return {"n": a["w"] + a["d"] + a["l"], "hw": a["l"], "d": a["d"], "aw": a["w"]}
        return None

    @staticmethod
    def _stats(st: Optional[Dict[str, Any]], is_home: bool) -> Optional[Dict[str, Any]]:
        """情报里认出的战绩 → 判定用的 {n,w,d,l,ppg,gd,...}。主客场战绩也有时，和整体各占一半。"""
        if not st:
            return None
        rec, ven = _best(st["rec"]), _best(st["venue"])
        base = rec or (ven if ven and ven["n"] >= 5 else None)
        if base is None:
            return None
        ppg = _ppg(base)
        if rec and ven and ven["n"] >= 5:
            ppg = 0.5 * ppg + 0.5 * _ppg(ven)
        gf, ga = st["gf"], st["ga"]
        if ga is None and st["ga_tot"] and st["ga_tot"][0] >= 3:
            ga = st["ga_tot"][1] / st["ga_tot"][0]
        if ga is not None:
            ga = round(ga, 2)
        gd = (gf - ga) if gf is not None and ga is not None else None
        return {"n": base["n"], "w": base["w"], "d": base["d"], "l": base["l"], "ppg": ppg, "gd": gd, "gf": gf, "ga": ga,
                "venue": ven, "streak": st["streak"], "is_home": is_home}

    def _make_note(self, m: Dict[str, Any], sides: Optional[Dict[str, Dict[str, Any]]], hi: Optional[Dict[str, Any]],
                   ai: Optional[Dict[str, Any]], h2h: Optional[Dict[str, int]], kick: str, problems: List[str]) -> Optional[Dict[str, Any]]:
        hs = self._stats(sides["h"], True) if sides else None
        as_ = self._stats(sides["a"], False) if sides else None
        src_h = src_a = "sina"
        if hs is None or as_ is None:                      # 新浪没写这场某一队的近况 → 那一队用自存赛果补（至少 DB_MIN_FORM 场）
            if self.db is not None:
                if hs is None:
                    dh = self.db.form(m["home"], kick)
                    if dh and dh["n"] >= DB_MIN_FORM:
                        hs, src_h = dict(dh, venue=None, streak=None, gf=None, ga=None, goals=(dh["gf"], dh["ga"])), "db"
                if as_ is None:
                    da = self.db.form(m["away"], kick)
                    if da and da["n"] >= DB_MIN_FORM:
                        as_, src_a = dict(da, venue=None, streak=None, gf=None, ga=None, goals=(da["gf"], da["ga"])), "db"
            if hs is None or as_ is None:
                return None
            if h2h is None and self.db is not None:
                h2h = self.db.h2h(m["home"], m["away"], kick)
        src = "db" if src_h == "db" and src_a == "db" else "sina"

        def inj(side: Optional[Dict[str, Any]], tab: Optional[Dict[str, Any]], sr: str) -> Optional[Dict[str, int]]:
            if tab is not None:                            # 足彩伤停表：球员名单，最可靠
                return {"out": tab["out"] + tab["key"], "q": 0, "key": tab["key"], "n": tab["out"]}
            if side is not None and sides is not None and sr == "sina":
                return {"out": 2 * side["key"] + side["out"], "q": side["doubt"], "key": side["key"], "n": side["key"] + side["out"],
                        "many": bool(side.get("many"))}
            return None

        hinj = inj(sides["h"] if sides else None, hi, src_h)
        ainj = inj(sides["a"] if sides else None, ai, src_a)
        if (hinj is None) != (ainj is None):               # 只有一边有伤停信息：另一边当作没有（文章没提）
            if hinj is None:
                hinj = {"out": 0, "q": 0, "key": 0, "n": 0}
            else:
                ainj = {"out": 0, "q": 0, "key": 0, "n": 0}
        extra, mtxt, mdl = 0.0, "", None
        if MM is not None and getattr(self, "model", None) is not None:
            try:
                pred = self.model.predict(m["home"], m["away"], kick)
                if pred:
                    extra, adj_txt = MM.adjust(pred, m.get("side"), int(m.get("need") or 1), bool((self.model_check or {}).get("ok")))
                    mtxt = MM.describe(pred, m["home"], m["away"]) + ("；" + adj_txt if adj_txt else "")
                    mdl = MM.card(pred, bool((self.model_check or {}).get("ok")))
            except Exception:  # noqa: BLE001 —— 模型只是加分项
                extra, mtxt, mdl = 0.0, "", None
        verdict, lean, score, why = T.judge(m.get("side"), int(m.get("need") or 1), hs, as_, hinj, ainj, h2h, extra=extra)
        txt = self._part(m["home"], hs, hinj, True) + "；" + self._part(m["away"], as_, ainj, False)
        if h2h and h2h["n"]:
            txt += (f"；近{h2h['y']}年交战{h2h['n']}次{m['home']}{h2h['hw']}胜{h2h['d']}平{h2h['aw']}负" if h2h.get("y")
                    else f"；近{h2h['n']}次交锋{m['home']}{h2h['hw']}胜{h2h['d']}平{h2h['aw']}负")
        if mtxt:
            txt += "；" + mtxt
        n = T.finish_note(m, txt, verdict, lean, score, why)
        n["src"] = src
        if mtxt:
            n["model"] = True
        if mdl:
            n["mdl"] = mdl                       # 比分参考/进球数/胜平负概率：帖子里用（只有回测过关才写）
        return n

    @staticmethod
    def _part(zh: str, st: Dict[str, Any], inj: Optional[Dict[str, int]], home: bool) -> str:
        s = f"{zh}近{st['n']}场{st['w']}胜{st['d']}平{st['l']}负"
        ex: List[str] = []
        if st.get("gf") is not None and st.get("ga") is not None:
            ex.append(f"场均进{st['gf']:g}失{st['ga']:g}")
        elif st.get("gf") is not None:
            ex.append(f"场均进{st['gf']:g}")
        elif st.get("goals"):                                       # 自存赛果：进失球合计
            ex.append(f"进{st['goals'][0]}失{st['goals'][1]}")
        v = st.get("venue")
        if v:
            ex.append(f"{'主场' if home else '客场'}近{v['n']}场{v['w']}胜{v['d']}平{v['l']}负")
        if st.get("streak"):
            ex.append(f"{st['streak'][1]}{st['streak'][2]}")
        if ex:
            s += "（" + "，".join(ex) + "）"
        if inj is not None:
            if inj.get("many"):
                s += "、缺多人" + ("（含主力）" if inj.get("key") else "")
            elif inj.get("n"):
                s += f"、缺{inj['n']}人" + (f"含{inj['key']}名主力" if inj.get("key") else "")
            if inj.get("q"):
                s += f"、{inj['q']}处存疑"
        return s

    # —— 测试连接 ——
    def check(self) -> List[str]:
        out: List[str] = []
        day = datetime.now(BJT).strftime("%Y-%m-%d")
        try:
            arts = self._discover(day, [])
        except RuntimeError as exc:
            return [f"✘ {exc}"]
        by = {k: [a for a in arts.values() if a["kind"] == k] for k in ("intel", "injury", "h2h")}
        out.append(f"✔ 新浪彩票栏目页能读：近几天共找到 竞彩情报 {len(by['intel'])} 篇、足彩伤停 {len(by['injury'])} 篇、交战记录 {len(by['h2h'])} 篇")
        today = [a for a in arts.values() if a["date"] == day]
        out.append(f"  其中今天（{day}）的 {len(today)} 篇" + ("" if today else "——今天的还没发，下午再试"))
        pick = sorted(by["intel"], key=lambda a: a["date"], reverse=True)[:1]
        if pick:
            a = pick[0]
            try:
                page = self.f.get(a["url"], TTL_ART_FRESH)
                out.append("✔ 读了一篇竞彩情报，认出：" + probe_text(article_body(page["text"])))
            except T.DataError as exc:
                out.append(f"✘ 读竞彩情报失败：{exc}")
        pick = sorted(by["injury"], key=lambda a: a["date"], reverse=True)[:1]
        if pick:
            try:
                tab = parse_injury_table(self.f.get(pick[0]["url"], TTL_ART_FRESH)["text"])
                out.append(f"{'✔' if tab else '✘'} 足彩伤停表认出 {len(tab)} 支球队" + ("" if tab else "（格式没认出来）"))
            except T.DataError as exc:
                out.append(f"✘ 读足彩伤停失败：{exc}")
        pick = sorted(by["h2h"], key=lambda a: a["date"], reverse=True)[:1]
        if pick:
            try:
                rows = parse_h2h_table(self.f.get(pick[0]["url"], TTL_ART_FRESH)["text"])
                out.append(f"{'✔' if rows else '✘'} 交战记录表认出 {len(rows)} 场" + ("" if rows else "（格式没认出来）"))
            except T.DataError as exc:
                out.append(f"✘ 读交战记录失败：{exc}")
        if self.db:
            out.append(f"自存赛果库：{len(self.db.rows)} 场（每次运行会自动添加 500 网昨日已开奖的比分）")
        out.append(f"（这次测试读了 {self.f.pages} 个网页）")
        return out



class ChainProvider:
    """先用第一个来源（新浪），它没覆盖的比赛再交给第二个来源（接口）补。"""

    def __init__(self, first: SinaProvider, second: Callable[[List[Dict[str, Any]], str], Tuple[List[Dict[str, Any]], List[str]]],
                 log: Optional[Callable[[str], None]] = None):
        self.first, self.second = first, second
        self.log = log or (lambda m: None)
        self.first.api_backup = True
        self.source_text = first.source_text

    def __call__(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        return self.notes_for(matches, day)

    def notes_for(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        problems: List[str] = []
        try:
            n1, p1 = self.first.notes_for(matches, day)
        except RuntimeError as exc:
            if "已停止" in str(exc):
                raise
            n1, p1 = [], [f"新浪来源没成功：{exc}"]
        problems += p1
        done = {tuple(n.get("mk") or ()) for n in n1}
        left = [m for m in matches if (m["home"], m["away"]) not in done]
        n2: List[Dict[str, Any]] = []
        if left:
            self.log(f"  新浪没覆盖的 {len(left)} 场，改用接口补……")
            try:
                n2, p2 = self.second(left, day)
                problems += p2
            except RuntimeError as exc:
                if "已停止" in str(exc):
                    raise
                problems.append(f"接口补数据没成功：{exc}")
        self.source_text = self.first.source_text + (f"；接口 API-Football 补 {len(n2)} 场" if n2 else "")
        return n1 + n2, problems


def probe_text(body: str) -> str:
    """不管是哪支球队，数一数这段文字里认出了多少项（测试用）。"""
    recs = sum(len(_records(x)) for x in re.split(r"[。！？!?；;\n]+", body))
    goals = len(GF_RE.findall(body))
    inj = sum(1 for s in re.split(r"[。！？!?；;\n]", body) for cl in re.split(r"[，,]", s) if ABS_RE.search(cl) or DOUBT_RE.search(cl))
    st = sum(1 for rx, _, _ in STREAKS if rx.search(body))
    return f"战绩 {recs} 处、场均进球 {goals} 处、伤停 {inj} 句、连胜连败 {st} 处" + ("" if recs or inj else "（一项都没认出来，文章格式可能变了）")


def _shift(day: str, n: int) -> str:
    return (datetime.strptime(day, "%Y-%m-%d") + timedelta(days=n)).strftime("%Y-%m-%d")


# ═══════════════════════ 8. 命令行 ═══════════════════════
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="测试新浪彩票的免费两队数据能不能读")
    ap.add_argument("--check", action="store_true", help="测试：读栏目页，看能找到几篇、认出什么")
    ap.add_argument("--url", default="", help="读一篇指定的新浪文章，看能认出什么（调试用）")
    ap.add_argument("--proxy", default="")
    a = ap.parse_args(argv)
    here = L.app_root(__file__)
    prov = SinaProvider(here, log=print, proxy=a.proxy)
    if a.url:
        page = prov.f.get(a.url, 60)
        body = article_body(page["text"])
        print(page["title"])
        print(probe_text(body))
        print("---- 正文前 1500 字 ----")
        print(body[:1500])
        return 0
    for line in prov.check():
        print(line)
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    raise SystemExit(main())
