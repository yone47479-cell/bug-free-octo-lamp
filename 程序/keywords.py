# -*- coding: utf-8 -*-
"""keywords.py —— 每日关键词：按「今天真实在售的赛事」整理出当天可以用的搜索词，输出就是一行一个词的纯词表（没有说明、没有 #）。

它做什么
  · 每天从当天的赛事表（联赛、主队、客队、开赛时间、赛事编号）整理出关键词，按这个顺序一行一个：
    你自己加的热词 → 热门对阵的搜索说法（「A vs B」「A vs B预测」「前瞻」「比分预测」「推荐」）→ 球队 → 联赛（名字＋说法）→ 玩法词 → 核心词 → 日期词。
  · 排序只靠三样看得见的东西：联赛热门程度（词库里的档位）＋球队是不是知名球队（词库里的名单）＋今天有没有推荐这场。
  · 词库放在「设置\\关键词库.json」，第一次运行自动生成，想加联赛、加球队、改说法都直接改它。

它不做什么
  · 不连 X / 微博 / 百度的实时热搜榜，也看不到任何搜索量：那些要登录、要接口，抓取还违反网站规则。所以这里的「热」是按词库估的，不是平台数据。
  · 想用真正的热搜：把你在 X 趋势页或别的地方看到的词一行一个粘进「设置\\热词.txt」，它们会排在最前面（和今天赛事对得上的更靠前）。
  · 没有当天赛事数据时，只给固定的核心词和日期词，不编对阵。
  · 含违禁词（guard.FORBIDDEN，如「稳赚」「必中」）的词一律不出。

只用 Python 标准库。
"""
from __future__ import annotations

import copy
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

__version__ = "1.1"

LEX_FILE, HOT_FILE = "关键词库.json", "热词.txt"
LEX_VERSION = 1
WEEK = "一二三四五六日"
TIER_TXT = {5: "最热联赛", 4: "热门联赛", 3: "一般联赛", 2: "小联赛", 1: "冷门赛事"}
FAMILY_ORDER = ("竞足", "北单", "竞篮", "胜负彩", "任九", "4场进球", "6场半全场")

LEX_NOTE = ("这是「每日关键词」用的词库：想加联赛、加球队、改搜索说法，直接改下面的文字就行（别动引号、冒号和逗号）。"
            "改乱了也没事：看不懂的项自动用默认值，并在运行日志里告诉你；整个文件删掉会重新生成默认的。"
            "排序只看三样：联赛档位（「联赛」里的「档」，5 最热 1 最冷）、球队在不在「知名球队」、今天有没有推荐这场。"
            "注意：这是按词库估的热度，不是 X/微博/百度的实时搜索量。")

DEFAULT_LEX: Dict[str, Any] = {
    "词库版本": LEX_VERSION,
    "说明": LEX_NOTE,
    "核心词": ["竞彩足球", "今日竞彩", "竞彩推荐", "足球推荐", "足球预测", "比分预测", "今日足球", "赛事前瞻",
               "赔率分析", "数据分析", "进球数预测", "两队近况", "防平", "防冷", "竞彩串关", "串关推荐",
               "北京单场", "胜负彩任九", "竞彩篮球", "篮球推荐"],
    "玩法词": {
        "竞足": ["竞彩足球", "胜平负", "让球胜平负", "竞彩串关"],
        "北单": ["北京单场", "北单推荐", "北单让球胜平负", "北单SP", "北单串关"],
        "竞篮": ["竞彩篮球", "篮球推荐", "让分胜负", "胜分差"],
        "胜负彩": ["胜负彩", "足彩胜负", "14场胜负"],
        "任九": ["任选九", "任九推荐", "足彩任九"],
        "4场进球": ["4场进球", "进球彩"],
        "6场半全场": ["6场半全场", "半全场"],
    },
    "期号模板": ["{期号}期{玩法}"],
    "对阵模板": ["{主}vs{客}", "{主}vs{客}预测", "{主}vs{客}前瞻", "{主}vs{客}比分预测", "{主}vs{客}推荐"],
    "联赛模板": ["{联赛}推荐", "{联赛}前瞻", "{联赛}比分预测", "{联赛}今日赛事"],
    "时间模板": ["{月}月{日}日竞彩", "{月}月{日}日竞彩推荐", "{月}月{日}日足球推荐", "{周}竞彩", "{周}竞彩足球", "{周}足球推荐"],
    # 联赛：按顺序匹配（排前面的优先；比如「美职篮」要排在「美职」前面，「女足世界杯」要排在「世界杯」前面）。名＝统一叫法，含＝表里联赛名里出现这些字就算它，
    # 档＝1～5 热门程度，词＝除了模板之外再多给的几个说法
    "联赛": [
        {"名": "女足", "含": ["女足", "女子"], "档": 1, "词": []},
        {"名": "青年赛", "含": ["U17", "U18", "U19", "U20", "U21", "U23", "青年", "预备"], "档": 1, "词": []},
        {"名": "世界杯", "含": ["世界杯"], "档": 5, "词": []},
        {"名": "欧洲杯", "含": ["欧洲杯"], "档": 5, "词": []},
        {"名": "欧冠", "含": ["欧冠", "欧洲冠军联赛"], "档": 5, "词": ["欧冠联赛"]},
        {"名": "欧联", "含": ["欧罗巴", "欧联"], "档": 4, "词": ["欧联杯", "欧罗巴联赛"]},
        {"名": "欧协联", "含": ["欧协联", "欧会杯"], "档": 3, "词": ["欧会杯"]},
        {"名": "欧国联", "含": ["欧国联"], "档": 4, "词": []},
        {"名": "世预赛", "含": ["世预赛", "世界杯预选"], "档": 4, "词": []},
        {"名": "亚洲杯", "含": ["亚洲杯"], "档": 4, "词": []},
        {"名": "美洲杯", "含": ["美洲杯"], "档": 4, "词": []},
        {"名": "亚冠二级", "含": ["亚冠二级", "亚冠联2", "亚冠杯"], "档": 3, "词": []},
        {"名": "亚冠", "含": ["亚冠"], "档": 4, "词": ["亚冠联赛"]},
        {"名": "英超", "含": ["英超"], "档": 5, "词": ["英格兰超级联赛"]},
        {"名": "英冠", "含": ["英冠"], "档": 3, "词": []},
        {"名": "西甲", "含": ["西甲"], "档": 4, "词": []},
        {"名": "意甲", "含": ["意甲"], "档": 4, "词": []},
        {"名": "德甲", "含": ["德甲"], "档": 4, "词": []},
        {"名": "法甲", "含": ["法甲"], "档": 3, "词": []},
        {"名": "荷甲", "含": ["荷甲"], "档": 3, "词": []},
        {"名": "葡超", "含": ["葡超"], "档": 3, "词": []},
        {"名": "土超", "含": ["土超"], "档": 3, "词": []},
        {"名": "苏超", "含": ["苏超"], "档": 3, "词": []},
        {"名": "中超", "含": ["中超"], "档": 4, "词": []},
        {"名": "日职乙", "含": ["日职乙", "日乙"], "档": 2, "词": []},
        {"名": "日职", "含": ["日职"], "档": 3, "词": ["日本职业联赛"]},
        {"名": "韩K", "含": ["韩K", "韩职"], "档": 3, "词": []},
        {"名": "NBA", "含": ["NBA", "美职篮"], "档": 5, "词": ["NBA常规赛"]},
        {"名": "美职", "含": ["美职"], "档": 3, "词": ["美职联"]},
        {"名": "澳超", "含": ["澳超"], "档": 3, "词": []},
        {"名": "沙特联", "含": ["沙特"], "档": 3, "词": []},
        {"名": "解放者杯", "含": ["解放者"], "档": 3, "词": []},
        {"名": "CBA", "含": ["CBA", "中职篮"], "档": 4, "词": ["中国男篮"]},
        {"名": "欧篮联", "含": ["欧篮联", "欧冠篮球"], "档": 3, "词": ["欧洲篮球联赛"]},
    ],
    # 知名球队：和表里的队名「完全一样」才算（用 500 网的叫法；全名和简称都写上）。只用来排序，不代表别的
    "知名球队": [
        "曼城", "曼联", "利物浦", "阿森纳", "切尔西", "热刺", "纽卡斯尔", "阿斯顿维拉",
        "皇马", "皇家马德里", "巴萨", "巴塞罗那", "马竞", "马德里竞技",
        "尤文", "尤文图斯", "国米", "国际米兰", "AC米兰", "那不勒斯", "罗马",
        "拜仁", "拜仁慕尼黑", "多特", "多特蒙德", "勒沃库森", "莱比锡",
        "巴黎", "巴黎圣日耳曼", "马赛", "摩纳哥", "里昂",
        "本菲卡", "波尔图", "葡萄牙体育", "阿贾克斯", "埃因霍温", "凯尔特人", "流浪者", "加拉塔萨雷", "费内巴切", "贝西克塔斯",
        "中国", "日本", "韩国", "巴西", "阿根廷", "法国", "英格兰", "德国", "西班牙", "葡萄牙", "荷兰", "意大利", "比利时", "克罗地亚", "乌拉圭", "美国", "墨西哥",
        "湖人", "勇士", "尼克斯", "76人", "雷霆", "马刺", "掘金", "热火", "快船", "太阳", "雄鹿", "独行侠", "森林狼", "公牛", "篮网",
    ],
    "屏蔽词": [],
}

_LIST_KEYS = ("核心词", "期号模板", "对阵模板", "联赛模板", "时间模板", "知名球队", "屏蔽词")
_NOTES = {
    "核心词": "每天都能用的固定词，和当天赛事无关",
    "玩法词": "按玩法分的词，只写今天真的有的玩法",
    "期号模板": "传统足彩有期号时用：{期号} {玩法}",
    "对阵模板": "每场对阵的搜索说法：{主} {客} 会换成球队名",
    "联赛模板": "每个联赛的搜索说法：{联赛}",
    "时间模板": "日期词：{月} {日} {周}（周一～周日）",
    "联赛": "名＝统一叫法，含＝联赛名里含这些字就算它（排前面的优先），档＝1～5 热门程度，词＝额外的说法",
    "知名球队": "和表里队名完全一样才算知名球队，只用来排序",
    "屏蔽词": "词里含有这些字的一律不出",
}


# ════════════════════════════════════════════════════════════════════════════
# 词库文件
# ════════════════════════════════════════════════════════════════════════════
def lexicon_default_json() -> Dict[str, Any]:
    d = copy.deepcopy(DEFAULT_LEX)
    d["各项说明"] = dict(_NOTES)
    return d


def _atomic_write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    tmp.replace(path)


def ensure_lexicon_file(path: Path) -> List[str]:
    """第一次运行时把默认词库写成 关键词库.json（已有就不动）；老文件缺了新项只补缺的。返回做了什么（空 = 什么都没做）。"""
    done: List[str] = []
    try:
        if not path.exists():
            _atomic_write(path, json.dumps(lexicon_default_json(), ensure_ascii=False, indent=2))
            return ["新建词库"]
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        if isinstance(data, dict):
            miss = [k for k in DEFAULT_LEX if k not in data]
            if miss or "各项说明" not in data:
                dflt = lexicon_default_json()
                merged = {k: (data[k] if k in data else dflt[k]) for k in dflt}
                merged["各项说明"] = dflt["各项说明"]
                merged.update({k: v for k, v in data.items() if k not in merged})
                _atomic_write(path, json.dumps(merged, ensure_ascii=False, indent=2))
                done = [f"补上 {k}" for k in miss]
    except (OSError, ValueError):
        pass
    return done


def _str_list(v: Any) -> Optional[List[str]]:
    if isinstance(v, str):
        v = [x for x in re.split(r"[,，、;；\n]+", v)]
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        return None
    return [x.strip() for x in v if x.strip()]


def load_lexicon(path: Optional[Path]) -> Tuple[Dict[str, Any], List[str]]:
    """读词库。没有文件/某项写得不对 → 那一项用默认值。返回（词库, 提醒）。"""
    lex = copy.deepcopy(DEFAULT_LEX)
    warns: List[str] = []
    if path is None or not Path(path).exists():
        return lex, warns
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as exc:
        return lex, [f"关键词库 {LEX_FILE} 读不了（{exc}），这次用默认词库。删掉它会自动重建。"]
    if not isinstance(data, dict):
        return lex, [f"关键词库 {LEX_FILE} 格式不对（最外层应是 {{ }}），这次用默认词库。"]
    known = set(DEFAULT_LEX) | {"各项说明", "每帖标签数"}          # 「每帖标签数」是 v2.6 的老项（现在不出标签了），文件里还有也不提醒
    for k in data:
        if k not in known:
            warns.append(f"关键词库里的「{k}」不认识，已忽略（是不是写错了字？）")
    for k in _LIST_KEYS:
        if k in data:
            v = _str_list(data[k])
            if v is None:
                warns.append(f"关键词库「{k}」应是一个文字列表，例如 [\"词一\", \"词二\"]，已用默认值")
            else:
                lex[k] = v
    if "玩法词" in data:
        pw = data["玩法词"]
        if isinstance(pw, dict) and all(isinstance(k, str) and _str_list(v) is not None for k, v in pw.items()):
            lex["玩法词"] = {k: _str_list(v) or [] for k, v in pw.items()}
        else:
            warns.append("关键词库「玩法词」应是 {\"竞足\": [\"词\"…], …} 这样的格式，已用默认值")
    if "联赛" in data:
        out: List[Dict[str, Any]] = []
        ok = isinstance(data["联赛"], list)
        for e in data["联赛"] if ok else []:
            inc = _str_list(e.get("含")) if isinstance(e, dict) else None
            tier = e.get("档") if isinstance(e, dict) else None
            if (not isinstance(e, dict) or not isinstance(e.get("名"), str) or not e["名"].strip() or not inc
                    or isinstance(tier, bool) or not isinstance(tier, int) or not 1 <= tier <= 5):
                warns.append(f"关键词库「联赛」里有一项写得不对（要有 名、含、档(1～5)）：{str(e)[:40]}，这一项已跳过")
                continue
            extra = _str_list(e.get("词", [])) or []
            out.append({"名": e["名"].strip(), "含": inc, "档": tier, "词": extra})
        if ok:
            lex["联赛"] = out
        else:
            warns.append("关键词库「联赛」应是一个列表，已用默认值")
    lex["词库版本"] = LEX_VERSION
    return lex, warns


def load_hot(path: Optional[Path]) -> Tuple[List[str], List[str]]:
    """读 热词.txt：一行一个词，# 开头是注释，「词 | 备注」只取竖线前面。没有文件就是空的。"""
    if path is None or not Path(path).exists():
        return [], []
    try:
        raw = Path(path).read_text(encoding="utf-8-sig")
    except (OSError, UnicodeDecodeError) as exc:
        return [], [f"热词文件 {HOT_FILE} 读不了（{exc}），这次没用上。保存成 UTF-8 的 txt 就行。"]
    words: List[str] = []
    seen: set = set()
    warns: List[str] = []
    for line in raw.splitlines():
        w = re.split(r"[|｜]", line, 1)[0].strip()
        if not w or w.startswith(("#", "＃")) and not w.lstrip("#＃").strip() or w.startswith("//"):
            continue
        if w.startswith(("#", "＃")) and " " in w:          # 「# 这是注释」；而「#欧冠」这种话题词保留
            continue
        w = w.strip()
        if len(w) > 30:
            warns.append(f"热词「{w[:12]}…」太长（超过 30 个字），已跳过")
            continue
        if w.lower() in seen:
            continue
        seen.add(w.lower())
        words.append(w)
    if len(words) > 200:
        warns.append(f"热词文件有 {len(words)} 个词，只用前 200 个")
        words = words[:200]
    return words, warns


def hot_default_text() -> str:
    return ("# 这里放你自己看到的真正热搜词（比如 X 趋势页上和足球、篮球有关的），一行一个词。\n"
            "# 以 # 开头并且后面有空格的行是注释，不会用。写不写 # 前缀的话题词（如 #欧冠）都行。\n"
            "# 脚本每天会拿它们和当天赛事对号入座：对上赛事的排在最前面，对不上的紧跟其后；词表里一律不带 # 。\n"
            "# 例：\n"
            "# 欧冠\n"
            "# 皇马\n")


def ensure_hot_file(path: Path) -> bool:
    try:
        if path.exists():
            return False
        _atomic_write(path, hot_default_text())
        return True
    except OSError:
        return False


# ════════════════════════════════════════════════════════════════════════════
# 小工具
# ════════════════════════════════════════════════════════════════════════════
def _fill(tpl: str, **kw: str) -> str:
    out = tpl
    for k, v in kw.items():
        out = out.replace("{" + k + "}", v)
    return "" if ("{" in out or "}" in out) else out


def _dedupe(items: Sequence[str]) -> List[str]:
    seen: set = set()
    out: List[str] = []
    for x in items:
        k = x.lower()
        if x and k not in seen:
            seen.add(k)
            out.append(x)
    return out


def league_info(lg: Any, lex: Dict[str, Any]) -> Tuple[str, int, List[str]]:
    """联赛名 → （统一叫法, 档位, 额外说法）。词库里没有的联赛：叫法去掉结尾的「联赛」，档位 2。"""
    s = str(lg or "").strip()
    for e in lex["联赛"]:
        if any(tok and tok in s for tok in e["含"]):
            return e["名"], e["档"], list(e.get("词") or [])
    name = s[:-2] if s.endswith("联赛") and len(s) > 3 else s
    return (name or "未标联赛"), 2, []


def _famous(team: str, lex: Dict[str, Any]) -> bool:
    return team.strip() in set(lex["知名球队"])


def score_match(m: Dict[str, Any], lex: Dict[str, Any]) -> Tuple[int, List[str]]:
    canon, tier, _ = league_info(m.get("lg"), lex)
    n_f = int(_famous(m["home"], lex)) + int(_famous(m["away"], lex))
    s = tier * 10 + 6 * n_f
    why = [f"{canon}（{TIER_TXT[tier]}）"]
    if n_f:
        why.append("两队都是知名球队" if n_f == 2 else "含知名球队")
    if m.get("rec"):
        star = m.get("star") if isinstance(m.get("star"), int) else 0
        s += 4 + (2 if star >= 2 else 0)
        why.append("今日有推荐" + ("★" * star if star else ""))
    if len(m.get("plays") or []) > 1:
        s += 2
        why.append("竞足和北单都有")
    return s, why


def _kick_hm(k: Any) -> str:
    m = re.search(r"(\d{2}:\d{2})", str(k or ""))
    return m.group(1) if m else ""


# ════════════════════════════════════════════════════════════════════════════
# 主函数
# ════════════════════════════════════════════════════════════════════════════
LEAGUE_TOP = 6                       # 联赛词只给最热的前几个联赛，别把清单撑得太长


def _clean(w: Any) -> str:
    """一个词只能是干净的一行：去掉 #、换行和首尾空格（不出话题标签）。"""
    return re.sub(r"[#＃\r\n\t]+", "", str(w or "")).strip()


def build(day: str, matches: Sequence[Dict[str, Any]], lex: Dict[str, Any], *, hot: Optional[Sequence[str]] = None,
          plays_on: Sequence[str] = (), issues: Optional[Dict[str, str]] = None, top_n: int = 12,
          bad: Sequence[str] = ()) -> Dict[str, Any]:
    """生成当天的关键词。输出就是纯词表：一行一个词，没有说明、没有标题、没有 #。

    matches   当天在售的赛事：{"plays": ["竞足", "北单"], "keys": ["周六001"], "lg", "home", "away", "kick", "rec": 今天有没有推荐, "star", "cp"}
    plays_on  今天有哪些玩法（竞足/北单/竞篮/胜负彩/任九/4场进球/6场半全场）
    issues    传统足彩期号，如 {"胜负彩": "26209", "4场进球": "26210"}
    bad       含这些字的词一律不出（违禁词＋词库里的屏蔽词）
    返回一个可以直接存成 json 的字典：「words」是词的列表，「text」就是一行一个词的文字（存成 txt 的就是它）。
    其余项（对阵排名、联赛场数、没对上的热词、被去掉的词）只是给程序和你自己检查用的，不会写进 txt。
    顺序：你自己的热词（和今天赛事对上的在前）→ 热门对阵的搜索说法 → 球队 → 联赛 → 玩法 → 核心词 → 日期词。
    """
    badl = [b for b in list(bad) + list(lex.get("屏蔽词") or []) if b]
    dropped: List[str] = []

    def keep(words: Sequence[str]) -> List[str]:
        out: List[str] = []
        for w in words:
            w = _clean(w)
            if not w:
                continue
            if any(b in w for b in badl):
                dropped.append(w)
                continue
            out.append(w)
        return _dedupe(out)

    try:
        d = datetime.strptime(day, "%Y-%m-%d")
    except ValueError:
        d = datetime.now()
        day = d.strftime("%Y-%m-%d")
    wk, mo, dd = "周" + WEEK[d.weekday()], str(d.month), str(d.day)
    ms = [dict(m) for m in matches if m.get("home") and m.get("away")]
    for m in ms:
        m["_score"], m["_why"] = score_match(m, lex)
    ms.sort(key=lambda m: (-m["_score"], str(m.get("kick") or "9999"), str(m.get("home"))))

    core = keep(lex["核心词"])
    times = keep([_fill(t, 月=mo, 日=dd, 周=wk) for t in lex["时间模板"]])

    # 联赛：统一叫法归并
    lg_map: Dict[str, Dict[str, Any]] = {}
    for m in ms:
        canon, tier, extra = league_info(m.get("lg"), lex)
        e = lg_map.setdefault(canon, {"name": canon, "n": 0, "tier": tier, "extra": extra})
        e["n"] += 1
    leagues = sorted(lg_map.values(), key=lambda e: (-e["tier"], -e["n"], e["name"]))
    for e in leagues:
        named = [] if e["name"] == "未标联赛" else [e["name"]]
        e["words"] = keep(named + [_fill(t, 联赛=e["name"]) for t in lex["联赛模板"]] + e["extra"]) if named else []

    # 对阵 TOP N
    top = ms[:max(1, int(top_n))]
    for fam_ in ("竞篮",):                                   # 足球场次太多时，篮球一场都上不了榜：给它留几个位置（最多 3 场）
        allf = [m for m in ms if fam_ in (m.get("plays") or [])]
        need = min(3, len(allf)) - sum(fam_ in (m.get("plays") or []) for m in top)
        if need > 0 and len(top) > need:
            extra = [m for m in allf if m not in top][:need]
            top = sorted(top[:len(top) - len(extra)] + extra, key=lambda m: (-m["_score"], str(m.get("kick") or "9999"), str(m.get("home"))))
    matches_out: List[Dict[str, Any]] = []
    for m in top:
        h, a = m["home"].strip(), m["away"].strip()
        canon, _, _ = league_info(m.get("lg"), lex)
        matches_out.append({
            "key": (m.get("keys") or [""])[0], "keys": list(m.get("keys") or []), "lg": canon, "home": h, "away": a,
            "kick": _kick_hm(m.get("kick")), "plays": list(m.get("plays") or []), "score": m["_score"], "why": m["_why"],
            "words": keep([_fill(t, 主=h, 客=a) for t in lex["对阵模板"]]),
        })

    # 球队词（热门对阵里的球队，知名球队排前面）
    teams: List[str] = []
    for m in top:
        for t in (m["home"].strip(), m["away"].strip()):
            if t and t not in teams:
                teams.append(t)
    teams = keep(sorted(teams, key=lambda t: (not _famous(t, lex),)))[:16]

    # 玩法词
    fam = [f for f in FAMILY_ORDER if f in set(plays_on)]
    play_words: Dict[str, List[str]] = {}
    for f in fam:
        ws = list(lex["玩法词"].get(f, []))
        iss = (issues or {}).get(f) or ""
        if iss:
            ws += [_fill(t, 期号=iss, 玩法=f if f != "任九" else "任选九") for t in lex["期号模板"]]
        play_words[f] = keep(ws)

    # 你自己加的热词：和今天赛事对得上的排最前
    hits: List[Dict[str, Any]] = []
    others: List[str] = []
    for raw in keep([str(w) for w in (hot or [])]):
        w = raw.replace(" ", "")
        got = []
        for m in ms:
            names = [m["home"].strip(), m["away"].strip(), str(m.get("lg") or ""), league_info(m.get("lg"), lex)[0]]
            if any(n and (n in w or (len(w) >= 2 and w in n)) for n in names):
                got.append(f"{(m.get('keys') or [''])[0]} {m['home'].strip()}vs{m['away'].strip()}".strip())
        if got:
            hits.append({"word": raw, "matches": got[:3]})
        else:
            others.append(raw)

    words: List[str] = [h["word"] for h in hits] + others
    if ms:
        for mo_ in matches_out:
            words += mo_["words"]
        words += teams
        for e in [e for e in leagues if e["words"]][:LEAGUE_TOP]:        # 没标联赛的那一组没有词，不占名额
            words += e["words"]
    for f in fam:
        words += play_words[f]
    words += core + times
    words = _dedupe([w for w in (_clean(w) for w in words) if w])

    return {
        "day": day, "weekday": wk, "ok": bool(ms), "n_matches": len(ms), "words": words,
        "text": ("\n".join(words) + "\n") if words else "",
        "core": core, "times": times, "teams": teams, "plays": play_words,
        "leagues": [{"name": e["name"], "n": e["n"], "tier": e["tier"], "words": e["words"]} for e in leagues],
        "matches": matches_out, "hot": {"hit": hits, "other": others}, "warns": [], "dropped": _dedupe(dropped),
    }


# ════════════════════════════════════════════════════════════════════════════
# 固定词库的文字版（给人看的；和脚本用的是同一份数据）
# ════════════════════════════════════════════════════════════════════════════
def lexicon_text(lex: Optional[Dict[str, Any]] = None, extra_lines: Sequence[str] = ()) -> str:
    lex = lex or DEFAULT_LEX
    j = lambda ws: "｜".join(ws)            # noqa: E731
    L = ["足球／篮球 竞彩类 常用关键词词库", "=" * 28,
         "说明：这是脚本「每日关键词」用的固定词库的文字版（脚本里是 设置\\关键词库.json，改那个文件就等于改这份）。",
         "词是按官方玩法叫法和常见搜索说法整理的，不是平台实时搜索量；排序里的「档」是估的热门程度。", ""]
    L += ["【一、核心词】每天都能用", j(lex["核心词"]), ""]
    L += ["【二、玩法词】"] + [f"{k}：{j(v)}" for k, v in lex["玩法词"].items()]
    L += [f"传统足彩有期号时再加：{j(lex['期号模板'])}", ""]
    L += ["【三、搜索说法模板】把 { } 换成当天的球队/联赛/日期"]
    L += [f"对阵：{j(lex['对阵模板'])}", f"联赛：{j(lex['联赛模板'])}", f"日期：{j(lex['时间模板'])}", ""]
    L += ["【四、联赛档位】5 最热 → 1 最冷（排序用；表里联赛名含「含」里的字就算它）"]
    for t in (5, 4, 3, 2, 1):
        es = [e for e in lex["联赛"] if e["档"] == t]
        if es:
            L.append(f"{t} 档（{TIER_TXT[t]}）：" + j(e["名"] + ("（含 " + "/".join(e["含"]) + "）" if e["含"] != [e["名"]] else "") for e in es))
    L += ["没写在这里的联赛按 2 档算。", ""]
    L += ["【五、知名球队】排序时加分（队名要和表里一模一样）", j(lex["知名球队"]), ""]
    L += list(extra_lines)
    return "\n".join(L).rstrip() + "\n"
