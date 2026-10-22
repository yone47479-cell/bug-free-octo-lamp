#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""每次运行自动抓取「两队真实数据」并和推单方向对比（只用 Python 3.9+ 标准库）。

数据来源：API-Sports 的官方接口（足球 API-Football、篮球 API-Basketball，同一个密钥）。
  * 需要你自己注册一个账号拿密钥（免费版每天 100 次请求）：https://dashboard.api-football.com/register
  * 500 网自己的分析页（odds.500.com/fenxi）robots.txt 禁止机器读取，所以不用。

每场比赛抓：两队最近 6 场战绩（含进失球）、联赛排名、双方伤停人数、最近 5 次交锋。
  * 付费套餐：逐队直接查，以上四项都有。
  * 免费套餐：接口只开放 2022～2024 赛季，本赛季的球队近况/伤停/排名/交锋都不让直接查（实测会报 "Free plans do not
    have access to this season"）。所以脚本自动改成「一天一天读过去几十天的当天全部比赛」，自己拼出每队近况；
    这种方式只有「近况」（战绩+进失球），没有伤停、排名、交锋（帖子里不写这几项）。读过的日子会缓存，以后每天基本只补一天。
然后按一套固定、透明的规则和推单方向比一比：
    support 数据支持 / mixed 部分支持 / against 数据反对（这场撤掉）
规则写在下面「判定」那一段，阈值可以改。接口查不到的内容一律不写，不编。

本文件不依赖 gen_tips.py：gen_tips.run(team_data=Provider(...).notes_for) 把它接进推单流程。
单独测试连接：  python team_data.py --check --key 你的密钥
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import math
import os
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import layout as L
from reliability import atomic_write_text

__version__ = "1.1"

BJT = timezone(timedelta(hours=8))
FOOTBALL_BASE = "https://v3.football.api-sports.io/"
BASKET_BASE = "https://v1.basketball.api-sports.io/"

# ───────────────────────── 可调参数 ─────────────────────────
MAX_REQUESTS = 90          # 一次运行最多发多少次接口请求（免费版每天 100 次，留一点余量）
RESERVE = 3                # 接口告诉我们当天只剩这么多次时，停手
FORM_N = 6                 # 看最近几场
H2H_N = 5                  # 看最近几次交锋
KICK_TOL_MIN = 45          # 开赛时间和接口里的差在这么多分钟以内才算同一场
TTL_FIXTURES = 30 * 60     # 缓存多久（秒）：当天比赛列表
TTL_FORM = 6 * 3600        # 球队近况
TTL_INJ = 3 * 3600         # 伤停
TTL_H2H = 7 * 86400        # 交锋
TTL_STAND = 12 * 3600      # 积分榜
MAX_SWEEP_DAYS = 45        # 免费版：逐日读比赛列表时，足球最多往前读多少天（每队读够 6 场就提前停）
MAX_SWEEP_DAYS_BB = 30     # 篮球
TTL_PAST_DAY = 90 * 86400  # 过去 2 天以上的某一天，比赛结果不会再变，缓存 90 天
TTL_RECENT_DAY = 3600      # 昨天、今天的还会变，只缓存 1 小时
BLOCK_TTL = 12 * 3600      # 发现「套餐不给」的项目，记住多久（秒），期间不再白花请求去试；点「测试连接」会清掉这个记忆
# 判定阈值（分数 = 状态分差 + 0.5×场均净胜球差 − 伤停差修正 ± 交锋修正，越大越支持推单方向）
SUPPORT_NEED1 = 0.6        # 只要赢球就行：分数 ≥ 这个 → 数据支持
SUPPORT_BIG = 1.4          # 要净胜 2 球及以上（让球盘）：分数 ≥ 这个才算支持
AGAINST = -0.8             # 分数 ≤ 这个 → 数据反对


class DataError(Exception):
    """接口出错。kind: auth 密钥问题 / plan 套餐不含 / quota 额度用完 / rate 每分钟超限 / net 网络 / other。"""

    def __init__(self, msg: str, kind: str = "other", fatal: bool = False):
        super().__init__(msg)
        self.kind, self.fatal = kind, fatal


class Budget:
    def __init__(self, max_requests: Optional[int] = None):
        """max_requests 不写：默认 MAX_REQUESTS；接口告诉我们每天额度很大（付费套餐）时自动放宽。"""
        self.explicit = max_requests is not None
        self.max, self.used = (max_requests if max_requests is not None else MAX_REQUESTS), 0
        self.daily_left: Optional[int] = None
        self.daily_limit: Optional[int] = None

    def exhausted(self) -> bool:
        return self.used >= self.max or (self.daily_left is not None and self.daily_left <= RESERVE)


# ═══════════════════════ 1. 接口客户端（缓存 + 限速 + 额度保护） ═══════════════════════
class Client:
    def __init__(self, key: str, base: str, cache_dir: Path, budget: Budget, *, log: Optional[Callable[[str], None]] = None,
                 cancel: Optional[Callable[[], bool]] = None, proxy: str = "", sleep: Callable[[float], None] = time.sleep):
        self.key, self.base, self.cache_dir, self.budget = key, base, Path(cache_dir), budget
        self.log = log or (lambda m: None)
        self.cancel = cancel or (lambda: False)
        self.sleep = sleep
        self.minute_left: Optional[int] = None
        handlers: List[Any] = []
        if proxy:
            handlers.append(urllib.request.ProxyHandler({"http": proxy, "https": proxy}))
        self.opener = urllib.request.build_opener(*handlers)
        self.net_fail = 0

    # —— 缓存 ——
    def _cpath(self, ck: str) -> Path:
        return self.cache_dir / (hashlib.sha1(ck.encode("utf-8")).hexdigest()[:20] + ".json")

    def _cache_read(self, ck: str, ttl: int) -> Optional[Any]:
        try:
            d = json.loads(self._cpath(ck).read_text(encoding="utf-8"))
            if not isinstance(d, dict):
                return None
            age = time.time() - float(d["t"])
            if d.get("ck") == ck and math.isfinite(age) and 0 <= age < ttl:
                return d["data"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        return None

    def _cache_write(self, ck: str, data: Any) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            atomic_write_text(self._cpath(ck), json.dumps({"ck": ck, "t": time.time(), "data": data}, ensure_ascii=False))
        except OSError:
            pass

    @staticmethod
    def _errmsg(errs: Any) -> str:
        if isinstance(errs, dict):
            return "; ".join(f"{k}: {v}" for k, v in errs.items())
        if isinstance(errs, list):
            return "; ".join(str(x) for x in errs)
        return str(errs) if errs else ""

    def _read_headers(self, h: Any) -> None:
        def geti(name: str) -> Optional[int]:
            try:
                return int(h.get(name))
            except (TypeError, ValueError):
                return None
        left, lim, mleft = geti("x-ratelimit-requests-remaining"), geti("x-ratelimit-requests-limit"), geti("X-RateLimit-Remaining")
        if left is not None:
            self.budget.daily_left = left
        if lim is not None:
            self.budget.daily_limit = lim
            if not self.budget.explicit and lim > 150:
                self.budget.max = min(300, lim // 5)
        self.minute_left = mleft

    def get(self, path: str, params: Optional[Dict[str, Any]] = None, ttl: int = 3600,
            slim: Optional[Callable[[Any], Any]] = None) -> Any:
        """返回接口里的 response 字段。失败抛 DataError。"""
        params = {k: v for k, v in (params or {}).items() if v not in (None, "")}
        qs = urllib.parse.urlencode(sorted(params.items()))
        ck = f"{self.base}{path}?{qs}"
        hit = self._cache_read(ck, ttl)
        if hit is not None:
            return hit
        for attempt in range(4):
            if self.cancel():
                raise DataError("已停止。", "other", True)
            if self.budget.exhausted():
                raise DataError("接口请求额度用完（本次上限或当天剩余），其余场次没查。", "quota")
            if self.minute_left is not None and self.minute_left <= 0:
                self.log("  接口每分钟限次，等 62 秒……")
                self.sleep(62)
                self.minute_left = None
            req = urllib.request.Request(self.base + path + (("?" + qs) if qs else ""),
                                         headers={"x-apisports-key": self.key, "Accept": "application/json",
                                                  "User-Agent": "tips-script/1.0"})
            try:
                with self.opener.open(req, timeout=30) as resp:
                    raw, headers = resp.read(), resp.headers
                self.budget.used += 1
                self.net_fail = 0
            except urllib.error.HTTPError as exc:
                self.budget.used += 1
                if exc.code in (401, 403):
                    raise DataError(f"密钥无效或没有权限（HTTP {exc.code}）。请检查密钥有没有填对。", "auth", True)
                if exc.code == 429 and attempt < 3:
                    self.log("  接口提示请求太频繁，等 62 秒……")
                    self.sleep(62)
                    continue
                raise DataError(f"接口返回 HTTP {exc.code}")
            except (urllib.error.URLError, OSError) as exc:
                self.net_fail += 1
                if self.net_fail >= 3:
                    raise DataError(f"网络连不上接口（{exc}）。检查网络，或在设置里填代理。", "net", True)
                self.sleep(2 * (attempt + 1))
                continue
            self._read_headers(headers)
            try:
                data = json.loads(raw.decode("utf-8"))
            except ValueError:
                raise DataError("接口返回的内容不是 JSON，可能被网络代理拦了。")
            msg = self._errmsg(data.get("errors")) if isinstance(data, dict) else ""
            if msg:
                low = msg.lower()
                if "ratelimit" in low.replace(" ", "") or "too many requests" in low:
                    if attempt < 3:
                        self.log("  接口每分钟限次，等 62 秒……")
                        self.sleep(62)
                        continue
                    raise DataError(msg, "rate")
                if "token" in low or "apikey" in low.replace(" ", "") or "api key" in low or "suspend" in low or "not active" in low:
                    raise DataError(f"密钥有问题：{msg}", "auth", True)
                if "request" in low and ("limit" in low or "quota" in low):
                    raise DataError(f"今天的请求额度用完了：{msg}", "quota")
                if "plan" in low or "season" in low or "subscription" in low or "access" in low:
                    raise DataError(msg, "plan")
                raise DataError(msg)
            resp_data = data.get("response") if isinstance(data, dict) else None
            if resp_data is None:
                raise DataError("接口返回里没有 response 字段")
            if slim is not None:
                resp_data = slim(resp_data)
            self._cache_write(ck, resp_data)
            return resp_data
        raise DataError("接口多次重试仍失败")


# ═══════════════════════ 2. 中文队名 → 英文队名 ═══════════════════════
# 格式：中文名=英文名|别名。接口里的英文名可能有细微差别，所以尽量多写几个叫法。
# 查不到的队名，会在运行提示里列出来；把它们补进 team_names.json（格式 {"中文名": "英文名|别名"}）就行。
SEED = """
拜仁慕尼黑=Bayern Munich|Bayern
多特蒙德=Borussia Dortmund|Dortmund
勒沃库森=Bayer Leverkusen|Leverkusen
RB莱比锡=RB Leipzig|Leipzig
莱比锡=RB Leipzig|Leipzig
法兰克福=Eintracht Frankfurt|Frankfurt
弗赖堡=SC Freiburg|Freiburg
霍芬海姆=1899 Hoffenheim|TSG Hoffenheim|Hoffenheim
斯图加特=VfB Stuttgart|Stuttgart
沃尔夫斯堡=VfL Wolfsburg|Wolfsburg
门兴=Borussia Monchengladbach|Monchengladbach|Gladbach
柏林联合=Union Berlin
美因茨=Mainz 05|Mainz
奥格斯堡=Augsburg
不莱梅=Werder Bremen|Bremen
海登海姆=Heidenheim
圣保利=St. Pauli|Sankt Pauli
汉堡=Hamburger SV|Hamburg
科隆=FC Koln|Cologne
沙尔克=Schalke 04|Schalke
帕德博恩=Paderborn
埃尔弗斯堡=Elversberg
曼城=Manchester City
曼联=Manchester United
利物浦=Liverpool
阿森纳=Arsenal
切尔西=Chelsea
热刺=Tottenham|Tottenham Hotspur
纽卡斯尔=Newcastle|Newcastle United
阿斯顿维拉=Aston Villa
布莱顿=Brighton
西汉姆=West Ham
水晶宫=Crystal Palace
富勒姆=Fulham
伯恩茅斯=Bournemouth
布伦特福德=Brentford
狼队=Wolves|Wolverhampton
埃弗顿=Everton
诺丁汉森林=Nottingham Forest|Nottingham
莱斯特城=Leicester
伊普斯维奇=Ipswich
南安普顿=Southampton
桑德兰=Sunderland
利兹联=Leeds
伯恩利=Burnley
谢菲尔德联=Sheffield United
西布朗=West Brom|West Bromwich
诺维奇=Norwich
米德尔斯堡=Middlesbrough
考文垂=Coventry
斯托克城=Stoke
米尔沃尔=Millwall
牛津联=Oxford United|Oxford
林肯红魔=Lincoln City|Lincoln
曼斯菲尔德=Mansfield
皇家马德里=Real Madrid
皇马=Real Madrid
巴塞罗那=Barcelona
马德里竞技=Atletico Madrid|Atletico
塞维利亚=Sevilla
皇家社会=Real Sociedad
比利亚雷亚尔=Villarreal
毕尔巴鄂竞技=Athletic Club|Athletic Bilbao
皇家贝蒂斯=Real Betis|Betis
瓦伦西亚=Valencia
塞尔塔=Celta Vigo|Celta
赫罗纳=Girona
奥萨苏纳=Osasuna
赫塔费=Getafe
赫塔菲=Getafe
马略卡=Mallorca
西班牙人=Espanyol
拉斯帕尔马斯=Las Palmas
巴列卡诺=Rayo Vallecano|Vallecano
阿拉维斯=Alaves
莱万特=Levante
埃尔切=Elche
奥维耶多=Real Oviedo|Oviedo
马拉加=Malaga
拉科鲁尼亚=Deportivo La Coruna|Deportivo
桑坦德竞技=Racing Santander|Racing de Santander
尤文图斯=Juventus
国际米兰=Inter|Internazionale
AC米兰=AC Milan|Milan
那不勒斯=Napoli
罗马=AS Roma|Roma
拉齐奥=Lazio
亚特兰大=Atalanta
佛罗伦萨=Fiorentina
博洛尼亚=Bologna
都灵=Torino
乌迪内斯=Udinese
热那亚=Genoa
卡利亚里=Cagliari
维罗纳=Hellas Verona|Verona
莱切=Lecce
帕尔马=Parma
科莫=Como
萨索洛=Sassuolo
克雷莫纳=Cremonese
比萨=Pisa
威尼斯=Venezia
巴黎圣日耳曼=Paris Saint Germain|Paris Saint-Germain|PSG
马赛=Marseille
里昂=Lyon|Olympique Lyonnais
摩纳哥=Monaco
里尔=Lille
尼斯=Nice
朗斯=Lens
雷恩=Rennes|Stade Rennais
斯特拉斯堡=Strasbourg
南特=Nantes
图卢兹=Toulouse
布雷斯特=Brest|Stade Brestois 29
兰斯=Reims
蒙彼利埃=Montpellier
欧塞尔=Auxerre
昂热=Angers
勒阿弗尔=Le Havre
梅斯=Metz
洛里昂=Lorient
巴黎FC=Paris FC
本菲卡=Benfica
波尔图=FC Porto|Porto
葡萄牙体育=Sporting CP|Sporting Lisbon
布拉加=Braga|SC Braga
吉马良斯=Vitoria Guimaraes|Guimaraes
托林斯=Torreense
托伦斯=Torreense
通德拉=Tondela
阿贾克斯=Ajax
PSV=PSV Eindhoven|PSV
埃因霍温=PSV Eindhoven|PSV
费耶诺德=Feyenoord
AZ阿尔克马尔=AZ Alkmaar|AZ
特温特=Twente
奈梅亨=NEC Nijmegen|NEC
乌德勒支=Utrecht
圣吉联合=Union St. Gilloise|Union Saint-Gilloise|Union SG
圣吉尔联合=Union St. Gilloise|Union Saint-Gilloise|Union SG
圣吉罗斯=Union St. Gilloise|Union Saint-Gilloise|Union SG
安德莱赫特=Anderlecht
布鲁日=Club Brugge
根特=Gent
标准列日=Standard Liege
凯尔特人=Celtic
格拉斯哥流浪者=Rangers
流浪者=Rangers
哈茨=Hearts|Heart of Midlothian
加拉塔萨雷=Galatasaray
费内巴切=Fenerbahce
贝西克塔斯=Besiktas
特拉布宗=Trabzonspor
萨尔茨堡红牛=Red Bull Salzburg|Salzburg
格拉茨风暴=Sturm Graz
维也纳快速=Rapid Vienna|Rapid Wien
维也纳奥地利=Austria Vienna|Austria Wien
布拉格斯巴达=Sparta Praha|Sparta Prague
布拉格斯拉维亚=Slavia Praha|Slavia Prague
比尔森胜利=Viktoria Plzen|Plzen
比尔森=Viktoria Plzen|Plzen
亚布洛内茨=Jablonec
波兹南莱赫=Lech Poznan
华沙莱吉亚=Legia Warszawa|Legia
雅盖隆=Jagiellonia Bialystok|Jagiellonia
费伦茨瓦罗斯=Ferencvarosi TC|Ferencvaros
索非亚中央陆军=CSKA Sofia
索非亚列夫斯基=Levski Sofia
萨格勒布迪纳摩=Dinamo Zagreb
哈伊杜克=Hajduk Split|Hajduk
贝尔格莱德红星=Crvena Zvezda|Red Star Belgrade|Red Star
贝游击=Partizan
奥林匹亚科斯=Olympiacos|Olympiakos
帕纳辛纳科斯=Panathinaikos
AEK雅典=AEK Athens|AEK
OFI克里特=OFI Crete|OFI
帕福斯=Pafos|Paphos
奥莫尼亚=Omonia|Omonia Nicosia
利勒斯特罗姆=Lillestrom
布兰=Brann
博德闪耀=Bodo/Glimt|Bodo Glimt
维京=Viking
莫尔德=Molde
罗森博格=Rosenborg
米亚尔比=Mjallby
马尔默=Malmo
哥本哈根=FC Copenhagen|Copenhagen
北西兰=Nordsjaelland
奥胡斯=Aarhus|AGF
库普斯=KuPS
卢加诺=Lugano
图恩=Thun
巴塞尔=FC Basel|Basel
年轻人=Young Boys
采列=Celje
里加FC=Riga
阿拉拉特亚美尼亚=Ararat-Armenia|Ararat Armenia
巴尼亚卢卡战士=Borac Banja Luka|Borac
克拉约瓦大学=Universitatea Craiova|Craiova
克拉约瓦=Universitatea Craiova|Craiova
埃斯卡尔德斯国际=Inter Club d'Escaldes|Inter Escaldes
弗拉门戈=Flamengo
拉普大学=Estudiantes L.P.|Estudiantes La Plata|Estudiantes
拉普拉塔大学生=Estudiantes L.P.|Estudiantes La Plata|Estudiantes
拉普拉塔体操=Gimnasia L.P.|Gimnasia La Plata
阿纳多卢埃菲斯=Anadolu Efes|Efes
阿斯维尔=ASVEL|Villeurbanne
迪拜=Dubai Basketball|Dubai
巴黎篮球=Paris Basketball|Paris
马卡比特拉维夫=Maccabi Tel Aviv
哈波尔特拉维夫=Hapoel Tel Aviv
萨拉基里斯=Zalgiris
巴斯克尼亚=Baskonia
米兰安帕=Olimpia Milano|Armani Milan|EA7 Emporio Armani
维尔图斯博洛尼亚=Virtus Bologna
"""

_STOP = {"fc", "cf", "sc", "ac", "afc", "fk", "sk", "bk", "as", "ss", "us", "ik", "sv", "ud", "cd", "rcd", "club", "de", "the",
         "calcio", "nk", "hnk", "cp", "fcsb", "tsg", "vfb", "vfl", "1"}
_YOUTH = re.compile(r"\b(u\d\d|w|women|ii|iii|reserves?|youth)\b|\sb$")


def norm_en(s: str) -> str:
    s = unicodedata.normalize("NFKD", (s or "").lower())
    s = "".join(c for c in s if not unicodedata.combining(c))
    for a, b in (("ø", "o"), ("æ", "ae"), ("ß", "ss"), ("đ", "d"), ("ł", "l"), ("ð", "d"), ("þ", "th")):
        s = s.replace(a, b)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(t for t in s.split() if t not in _STOP)


def en_match(alias: str, api_name: str) -> bool:
    """alias（我们的英文叫法）和接口里的队名是不是同一支球队。"""
    if _YOUTH.search((api_name or "").lower()):
        return False
    a, b = norm_en(alias), norm_en(api_name)
    if not a or not b:
        return False
    if a == b:
        return True
    short, long_ = (a, b) if len(a) <= len(b) else (b, a)
    if (len(short.split()) >= 2 or len(short) >= 8) and (" " + short + " ") in (" " + long_ + " "):
        return True
    return difflib.SequenceMatcher(None, a, b).ratio() >= 0.9


class Names:
    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self.table: Dict[str, List[str]] = {}
        for line in SEED.strip().splitlines():
            if "=" in line:
                zh, en = line.split("=", 1)
                self.table[zh.strip()] = [x.strip() for x in en.split("|") if x.strip()]
        self.learned_path = L.p(self.folder, "team_names_learned.json")
        self.learned: Dict[str, Dict[str, Any]] = {}
        try:
            self.learned = json.loads(self.learned_path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            pass
        try:   # 用户自己补的对照表
            for zh, en in json.loads(L.p(self.folder, "team_names.json").read_text(encoding="utf-8")).items():
                self.table[str(zh).strip()] = [x.strip() for x in str(en).split("|") if x.strip()]
        except (OSError, ValueError, AttributeError):
            pass

    def aliases(self, zh: str) -> List[str]:
        zh = (zh or "").strip()
        if not zh:
            return []
        out: List[str] = []
        if zh in self.learned:
            out.append(str(self.learned[zh].get("en", "")))
        if zh in self.table:
            return out + self.table[zh]
        # 队名被截短/多字：键包含它，或它包含键（至少 2 个字），多个都沾边就全收
        hits = [k for k in self.table if len(k) >= 2 and len(zh) >= 2 and (k in zh or zh in k)]
        if not hits:
            ratio = [(difflib.SequenceMatcher(None, k, zh).ratio(), k) for k in self.table]
            best = max(ratio, default=(0.0, ""))
            hits = [best[1]] if best[0] >= 0.8 else []
        for k in hits:
            out += self.table[k]
        return [a for a in out if a]

    def learn(self, zh: str, en: str, tid: Any) -> None:
        if not zh or not en or zh in self.table:
            return
        self.learned[zh] = {"en": en, "id": tid}
        try:
            self.folder.mkdir(parents=True, exist_ok=True)
            self.learned_path.write_text(json.dumps(self.learned, ensure_ascii=False, indent=1), encoding="utf-8")
        except OSError:
            pass


# ═══════════════════════ 3. 从比赛列表里找到对应的那一场 ═══════════════════════
def _name_ok(names: Names, zh: str, api_name: str) -> Optional[bool]:
    """None = 我们不认识这个中文队名；True/False = 认识，是/不是这支。"""
    al = names.aliases(zh)
    if not al:
        return None
    return any(en_match(a, api_name) for a in al)


def find_fixture(names: Names, fixtures: List[Dict[str, Any]], home: str, away: str, kick: datetime) -> Tuple[Optional[Dict[str, Any]], str]:
    """返回 (比赛, 说明)。两边队名都对上才算；只认识一边时，开赛时间前后 15 分钟内含这支球队的比赛只有一场，也算（并记住另一边）。"""
    ts = kick.timestamp()
    near = [f for f in fixtures if abs(float(f.get("fixture", {}).get("timestamp") or 0) - ts) <= KICK_TOL_MIN * 60]
    both, home_only, away_only = [], [], []
    for f in near:
        h, a = f["teams"]["home"]["name"], f["teams"]["away"]["name"]
        oh, oa = _name_ok(names, home, h), _name_ok(names, away, a)
        if oh and oa:
            both.append(f)
        elif oh and oa is None:
            home_only.append(f)
        elif oa and oh is None:
            away_only.append(f)
    if len(both) == 1:
        return both[0], ""
    if len(both) > 1:
        best = min(both, key=lambda f: abs(float(f["fixture"]["timestamp"]) - ts))
        return best, ""
    tight = lambda fs: [f for f in fs if abs(float(f["fixture"]["timestamp"]) - ts) <= 15 * 60]
    if len(tight(home_only)) == 1:
        f = tight(home_only)[0]
        names.learn(away, f["teams"]["away"]["name"], f["teams"]["away"]["id"])
        return f, ""
    if len(tight(away_only)) == 1:
        f = tight(away_only)[0]
        names.learn(home, f["teams"]["home"]["name"], f["teams"]["home"]["id"])
        return f, ""
    unknown = [t for t in (home, away) if not names.aliases(t)]
    if unknown:
        return None, f"队名对照表里没有「{'、'.join(unknown)}」（补进 team_names.json 即可）"
    return None, "接口当天的比赛列表里没找到这场（可能赛事不在接口覆盖范围内，或开赛时间对不上）"


# ═══════════════════════ 4. 统计与判定 ═══════════════════════
FINISHED = {"FT", "AET", "PEN", "AOT"}


def _goals(fx: Dict[str, Any]) -> Tuple[Optional[int], Optional[int]]:
    g = fx.get("goals")
    if isinstance(g, dict) and g.get("home") is not None and g.get("away") is not None:
        return int(g["home"]), int(g["away"])
    sc = fx.get("scores")                      # 篮球
    if isinstance(sc, dict):
        try:
            return int(sc["home"]["total"]), int(sc["away"]["total"])
        except (KeyError, TypeError, ValueError):
            pass
    return None, None


def _status(fx: Dict[str, Any]) -> str:
    st = fx.get("fixture", {}).get("status") if "fixture" in fx else fx.get("status")
    return (st or {}).get("short", "") if isinstance(st, dict) else ""


def _ts(fx: Dict[str, Any]) -> float:
    v = fx.get("fixture", {}).get("timestamp") if "fixture" in fx else fx.get("timestamp")
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def finished_before(rows: List[Dict[str, Any]], before_ts: float) -> List[Dict[str, Any]]:
    ok = [f for f in rows if _status(f) in FINISHED and _ts(f) < before_ts and _goals(f)[0] is not None]
    ok.sort(key=_ts, reverse=True)
    return ok


def team_stats(rows: List[Dict[str, Any]], tid: Any, n: int = FORM_N) -> Dict[str, Any]:
    rows = rows[:n]
    w = d = l = gf = ga = 0
    for f in rows:
        h, a = _goals(f)
        home = str(f["teams"]["home"]["id"]) == str(tid)
        mine, theirs = (h, a) if home else (a, h)
        gf, ga = gf + mine, ga + theirs
        if mine > theirs:
            w += 1
        elif mine == theirs:
            d += 1
        else:
            l += 1
    k = len(rows)
    return {"n": k, "w": w, "d": d, "l": l, "gf": gf, "ga": ga,
            "ppg": (3 * w + d) / k if k else None, "gd": (gf - ga) / k if k else None}


def h2h_stats(rows: List[Dict[str, Any]], hid: Any, aid: Any) -> Dict[str, int]:
    hw = dr = aw = 0
    for f in rows:
        h, a = _goals(f)
        if h is None:
            continue
        hh = str(f["teams"]["home"]["id"]) == str(hid)
        mine, theirs = (h, a) if hh else (a, h)
        if mine > theirs:
            hw += 1
        elif mine == theirs:
            dr += 1
        else:
            aw += 1
    return {"n": hw + dr + aw, "hw": hw, "d": dr, "aw": aw}


def judge(side: Optional[str], need: int, hs: Dict[str, Any], as_: Dict[str, Any], hinj: Optional[Dict[str, int]],
          ainj: Optional[Dict[str, int]], h2h: Optional[Dict[str, int]], big_win: bool = False, extra: float = 0.0
          ) -> Tuple[str, Optional[str], Optional[float], str]:
    """返回 (verdict, lean, score, 理由)。side: 推单要的那一方 home/away；need: 要净胜几球（让球盘 ≥2）。"""
    if side not in ("home", "away"):
        return "mixed", None, None, "这场的推荐不是单一方向（平局或两个方向都有），只列数据、不下结论"
    if hs["n"] < 3 or as_["n"] < 3:
        return "mixed", None, None, "近况场次太少，没法下结论"
    x, y = (hs, as_) if side == "home" else (as_, hs)
    if x.get("gd") is not None and y.get("gd") is not None:
        score = (x["ppg"] - y["ppg"]) + 0.5 * (x["gd"] - y["gd"])
    else:                                      # 没有进失球数据（比如只读到「近10场9胜1负」）：只比战绩，按同样的量级放大一点
        score = 1.3 * (x["ppg"] - y["ppg"])
    if hinj is not None and ainj is not None:
        xi, yi = (hinj, ainj) if side == "home" else (ainj, hinj)
        score -= max(-0.5, min(0.5, 0.1 * (xi["out"] - yi["out"])))
    if h2h and h2h["n"] >= 3:
        xw, yw = (h2h["hw"], h2h["aw"]) if side == "home" else (h2h["aw"], h2h["hw"])
        score += max(-0.3, min(0.3, 0.1 * (xw - yw)))
    score += extra                              # 自己的数据模型（回测过关时）给的微调，最多 ±0.4
    thr = SUPPORT_BIG if (need >= 2 or big_win) else SUPPORT_NEED1
    if score >= thr:
        verdict, why = "support", "近况明显更好"
    elif score <= AGAINST:
        verdict, why = "against", "近况明显不如对手"
    else:
        verdict = "mixed"
        why = "近况接近" if abs(score) < 0.3 else ("近况占优但不足以支撑净胜2球以上" if score > 0 and (need >= 2 or big_win) else "近况略占优" if score > 0 else "近况略差")
    if abs(extra) >= 0.15:
        why += "；数据模型也看好" if extra > 0 else "；数据模型不看好"
    other = "away" if side == "home" else "home"
    lean = side if score >= 0.3 else other if score <= -0.3 else None
    return verdict, lean, round(score, 2), why


# ═══════════════════════ 5. 提供者：把比赛列表变成「两队对比」 ═══════════════════════
def _player_out(inj_rows: List[Dict[str, Any]], tid: Any) -> Dict[str, int]:
    out = q = 0
    seen = set()
    for r in inj_rows or []:
        try:
            if str(r["team"]["id"]) != str(tid):
                continue
            pid = r.get("player", {}).get("id") or r.get("player", {}).get("name")
            if pid in seen:
                continue
            seen.add(pid)
            typ = str(r.get("player", {}).get("type", "")).lower()
            if "question" in typ or "doubt" in typ:
                q += 1
            else:
                out += 1
        except (KeyError, TypeError):
            continue
    return {"out": out, "q": q}


def _standing_map(resp: Any) -> Dict[str, Dict[str, int]]:
    m: Dict[str, Dict[str, int]] = {}
    try:
        for item in resp or []:
            groups = item["league"]["standings"] if isinstance(item, dict) and "league" in item else [item]
            for grp in groups:
                for row in grp if isinstance(grp, list) else [grp]:
                    tid = str(row["team"]["id"])
                    if tid in m:
                        continue
                    if "rank" in row:                      # 足球
                        m[tid] = {"rank": int(row["rank"]), "pts": int(row.get("points") or 0),
                                  "played": int((row.get("all") or {}).get("played") or 0)}
                    elif "position" in row:                # 篮球
                        g = row.get("games") or {}
                        m[tid] = {"rank": int(row["position"]), "w": int((g.get("win") or {}).get("total") or 0),
                                  "l": int((g.get("lose") or {}).get("total") or 0)}
    except (KeyError, TypeError, ValueError):
        pass
    return m


# —— 缓存前先瘦身：逐日读比赛列表会存很多天，只留算近况要用的字段 ——
def _slim_list(fn: Callable[[Dict[str, Any]], Dict[str, Any]]) -> Callable[[Any], Any]:
    def run(resp: Any) -> Any:
        if not isinstance(resp, list):
            return resp
        out = []
        for x in resp:
            try:
                y = fn(x)
            except (KeyError, TypeError, AttributeError):
                y = None
            if y:
                out.append(y)
        return out
    return run


def _slim_fx(f: Dict[str, Any]) -> Dict[str, Any]:
    fx, lg, g = f["fixture"], f.get("league") or {}, f.get("goals") or {}
    return {"fixture": {"id": fx["id"], "timestamp": fx["timestamp"], "status": {"short": (fx.get("status") or {}).get("short", "")}},
            "league": {k: lg.get(k) for k in ("id", "name", "season", "round")},
            "teams": {s: {"id": f["teams"][s]["id"], "name": f["teams"][s]["name"]} for s in ("home", "away")},
            "goals": {"home": g.get("home"), "away": g.get("away")}}


def _slim_bg(g: Dict[str, Any]) -> Dict[str, Any]:
    lg, sc = g.get("league") or {}, g.get("scores") or {}
    return {"id": g["id"], "timestamp": g["timestamp"], "status": {"short": (g.get("status") or {}).get("short", "")},
            "league": {k: lg.get(k) for k in ("id", "name", "season")},
            "teams": {s: {"id": g["teams"][s]["id"], "name": g["teams"][s]["name"]} for s in ("home", "away")},
            "scores": {s: {"total": (sc.get(s) or {}).get("total")} for s in ("home", "away")}}


SLIM_FX, SLIM_BG = _slim_list(_slim_fx), _slim_list(_slim_bg)


class Provider:
    source_text = "接口自动抓取（API-Football/API-Basketball，api-sports.io）"

    def __init__(self, key: str, cache_dir: Path, *, max_requests: Optional[int] = None, log: Optional[Callable[[str], None]] = None,
                 cancel: Optional[Callable[[], bool]] = None, proxy: str = "", football_base: str = FOOTBALL_BASE,
                 basket_base: str = BASKET_BASE, sleep: Callable[[float], None] = time.sleep):
        self.key = key.strip()
        self.cache_dir = Path(cache_dir)
        self.log = log or (lambda m: None)
        self.fbud, self.bbud = Budget(max_requests), Budget(max_requests)     # 足球、篮球各算各的额度
        self.budget = self.fbud
        self.names = Names(self.cache_dir.parent if self.cache_dir.name == "data_cache" else self.cache_dir)
        kw = dict(log=self.log, cancel=cancel, proxy=proxy, sleep=sleep)
        self.fb = Client(self.key, football_base, self.cache_dir, self.fbud, **kw)
        self.bb = Client(self.key, basket_base, self.cache_dir, self.bbud, **kw)
        self.off: set = set()          # 本次运行里发现当前套餐不给的项目，如 "fb:injuries"
        self._prune_cache()

    def _blocks_path(self) -> Path:
        return self.cache_dir / "_blocks.json"

    def _load_blocks(self) -> set:
        try:
            d = json.loads(self._blocks_path().read_text(encoding="utf-8"))
            return {k for k, t in d.items() if time.time() - float(t) < BLOCK_TTL}
        except (OSError, ValueError, TypeError, AttributeError):
            return set()

    def _save_blocks(self) -> None:
        try:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._blocks_path().write_text(json.dumps({k: time.time() for k in self.off}), encoding="utf-8")
        except OSError:
            pass

    def _prune_cache(self) -> None:
        """清掉 100 天前的缓存文件（逐日读比赛列表会攒下不少小文件）。"""
        try:
            limit = time.time() - 100 * 86400
            for p in self.cache_dir.glob("*.json"):
                if p.stat().st_mtime < limit:
                    p.unlink()
        except OSError:
            pass

    # —— 连接测试 ——
    def check(self) -> List[str]:
        lines: List[str] = []
        if not self.key:
            return ["没有填密钥。注册地址：https://dashboard.api-football.com/register （免费版每天 100 次）"]
        try:
            self._blocks_path().unlink()                # 重新测一遍：之前记住的「套餐不给」作废（比如刚升级了套餐）
        except OSError:
            pass
        try:
            st = self.fb.get("status", {}, ttl=0)
            if isinstance(st, dict):
                sub, req = st.get("subscription") or {}, st.get("requests") or {}
                lines.append(f"✔ 密钥有效。套餐：{sub.get('plan', '?')}；今天已用 {req.get('current', '?')}/{req.get('limit_day', '?')} 次")
            else:
                lines.append("✔ 接口能连上，但 status 返回的格式和预期不同：" + json.dumps(st, ensure_ascii=False)[:200])
        except DataError as exc:
            return [f"✖ 连接失败：{exc}"]
        now = datetime.now(timezone.utc)
        today = now.strftime("%Y-%m-%d")
        fx: List[Dict[str, Any]] = []
        try:
            fx = self.fb.get("fixtures", {"date": today}, ttl=0, slim=SLIM_FX) or []
            lines.append(f"✔ 能取到今天（{today}，UTC）的足球比赛列表：{len(fx)} 场。")
            if not fx:
                lines.append("  列表是空的：可能今天确实没比赛，也可能你的套餐查不到当前赛季。")
        except DataError as exc:
            lines.append(f"✖ 取今天的比赛列表失败：{exc}")
            return lines
        past = (now - timedelta(days=7)).strftime("%Y-%m-%d")
        try:
            px = self.fb.get("fixtures", {"date": past}, ttl=0, slim=SLIM_FX) or []
            done = [f for f in px if _status(f) in FINISHED]
            if done:
                lines.append(f"✔ 能读到过去的比赛结果（{past}：{len(done)} 场已完赛）——脚本靠它算两队近况。")
            else:
                lines.append(f"△ {past} 的比赛列表里没有已完赛的场次（可能那天没比赛，也可能套餐不给）。")
        except DataError as exc:
            lines.append(f"✖ 读不到过去的比赛结果：{exc}")
            lines.append("  这样就没法算两队近况，这个功能要升级付费套餐才能用（价格见 https://www.api-football.com/pricing ）；"
                         "不升级的话，请在操作台关掉「自动抓两队数据」。")
            return lines
        if fx:
            try:
                self.fb.get("fixtures", {"team": fx[0]["teams"]["home"]["id"], "last": 3}, ttl=0)
                lines.append("✔ 能直接查球队近况（付费套餐的查法）：脚本会逐队查，数据更全（含伤停、排名、交锋）。")
            except DataError as exc:
                if exc.kind == "plan":
                    lines.append(f"△ 直接查球队近况/伤停/排名不行（{exc}）。脚本会改成「逐日读比赛列表」自己算近况："
                                 "对比里只有近况（战绩和进失球），没有伤停、排名、交锋。")
                else:
                    lines.append(f"△ 直接查球队近况失败：{exc}")
        return lines

    # —— 主入口 ——
    def notes_for(self, matches: List[Dict[str, Any]], day: str) -> Tuple[List[Dict[str, Any]], List[str]]:
        """matches: [{home, away, kick(datetime, 北京时间), sport('football'|'basketball'), side, need, line}]，按重要性排好序。
        返回 (notes, problems)。notes 可直接放进 manual 的 match_notes；problems 是要告诉用户的情况。致命错误（密钥/网络/用户停止）抛 RuntimeError。"""
        problems: List[str] = []
        notes: List[Dict[str, Any]] = []
        if not self.key:
            raise RuntimeError("没有填接口密钥。注册地址：https://dashboard.api-football.com/register （免费版每天 100 次请求）")
        self.off = self._load_blocks()
        fb = [m for m in matches if m.get("sport") != "basketball"]
        bb = [m for m in matches if m.get("sport") == "basketball"]
        errs: List[str] = []
        for name, fn, group in (("足球", self._football, fb), ("篮球", self._basketball, bb)):
            if not group:
                continue
            try:
                n, p = fn(group)
                notes += n
                problems += p
            except DataError as exc:
                if exc.kind in ("auth", "net") or "已停止" in str(exc):
                    raise RuntimeError(str(exc))
                errs.append(f"{name}数据没取到：{exc}")
        if errs and not notes:
            raise RuntimeError("；".join(errs))
        problems += errs
        names = {"injuries": "伤停", "h2h": "交锋", "standings": "联赛排名"}
        miss = [v for k, v in names.items() if any(o.endswith(":" + k) for o in self.off)]
        if miss:
            problems.append("当前套餐查不到" + "、".join(miss) + "，这几项本次没有（帖子里不写），对比只有近况。")
        used = f"本次用了 足球{self.fbud.used}次" + (f"、篮球{self.bbud.used}次" if self.bbud.used else "") + "接口请求"
        if self.fbud.daily_left is not None:
            used += f"，足球接口今天还剩 {self.fbud.daily_left} 次"
        problems.append(used)
        self._save_blocks()
        return notes, problems

    # ───────── 共用：逐日读比赛列表，拼出每队的已完赛记录 ─────────
    def _fixtures_on(self, c: Client, kick: datetime, path: str, slim: Callable[[Any], Any]) -> List[Dict[str, Any]]:
        d = kick.astimezone(timezone.utc).strftime("%Y-%m-%d")
        return c.get(path, {"date": d}, ttl=TTL_FIXTURES, slim=slim) or []

    def _sweep(self, c: Client, path: str, slim: Callable[[Any], Any], tids: set, pools: Dict[str, List[Dict[str, Any]]],
               earliest: datetime, max_days: int, problems: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """从 earliest 的前一天往回，一天一天读「当天所有比赛」，把涉及 tids 里球队的已完赛场次归到各队名下。
        读够每队 FORM_N 场就停。过去超过 2 天的日子结果不会再变，缓存 90 天，所以以后每天基本只补新的一天。"""
        idx: Dict[str, List[Dict[str, Any]]] = {t: [] for t in tids}
        seen: set = set()

        def add(rows: List[Dict[str, Any]]) -> None:
            for r in rows:
                if _status(r) not in FINISHED or _goals(r)[0] is None:
                    continue
                fid = (r.get("fixture") or {}).get("id") if "fixture" in r else r.get("id")
                if fid in seen:
                    continue
                seen.add(fid)
                for side in ("home", "away"):
                    t = str(r["teams"][side]["id"])
                    if t in idx:
                        idx[t].append(r)

        for rows in pools.values():
            add(rows)
        today = datetime.now(timezone.utc).date()
        start = earliest.astimezone(timezone.utc).date() - timedelta(days=1)
        got = 0
        for k in range(max_days):
            if all(len(v) >= FORM_N for v in idx.values()):
                break
            d = start - timedelta(days=k)
            ttl = TTL_PAST_DAY if (today - d).days >= 2 else TTL_RECENT_DAY
            try:
                rows = c.get(path, {"date": d.isoformat()}, ttl=ttl, slim=slim) or []
            except DataError as exc:
                if exc.kind == "quota":
                    problems.append(f"额度不够，近况只读到最近 {got} 天的比赛。")
                    break
                if exc.kind == "plan":
                    raise DataError(f"当前套餐连过去日期的比赛列表也不让读（{exc}）。要用「自动抓两队数据」只能升级付费套餐。", "plan", True)
                raise
            got += 1
            add(rows)
            if got % 10 == 0:
                self.log(f"  已读过去 {got} 天的比赛列表……")
        short = [t for t, v in idx.items() if len(v) < 3]
        if short and got >= max_days:
            problems.append(f"往前读了 {got} 天，仍有 {len(short)} 支球队不足 3 场比赛记录（休赛期或赛事不在接口覆盖内），这些场次会标为“近况太少”。")
        return idx

    # ───────── 足球 ─────────
    def _team_rows(self, c: Client, tid: Any, season: Any, kick_ts: float) -> List[Dict[str, Any]]:
        """逐队直接查最近的比赛（付费套餐的查法）。返回原始记录，用的时候再按开赛时间筛。"""
        try:
            return c.get("fixtures", {"team": tid, "last": FORM_N + 2}, ttl=TTL_FORM) or []
        except DataError as exc:
            if exc.fatal or exc.kind in ("quota", "net", "auth"):
                raise
            if exc.kind == "plan" and "season" in str(exc).lower():
                raise                                  # 套餐不含这个赛季：换成 season 参数也会被拒，别白花请求
            d1 = datetime.fromtimestamp(kick_ts, timezone.utc)
            return c.get("fixtures", {"team": tid, "season": season, "from": (d1 - timedelta(days=150)).strftime("%Y-%m-%d"),
                                      "to": (d1 - timedelta(days=1)).strftime("%Y-%m-%d")}, ttl=TTL_FORM) or []

    def _football(self, ms: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        c, off = self.fb, self.off
        problems: List[str] = []
        pool: Dict[str, List[Dict[str, Any]]] = {}
        resolved: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        self.log(f"  足球：{len(ms)} 场，先取当天比赛列表对号……")
        for m in ms:
            d = m["kick"].astimezone(timezone.utc).strftime("%Y-%m-%d")
            if d not in pool:
                pool[d] = self._fixtures_on(c, m["kick"], "fixtures", SLIM_FX)
            f, why = find_fixture(self.names, pool[d], m["home"], m["away"], m["kick"])
            if f is None:
                problems.append(f"{m['home']}vs{m['away']}：{why}")
            else:
                resolved.append((m, f))
        self.log(f"  对上 {len(resolved)}/{len(ms)} 场，开始读两队近况……")
        if not resolved:
            return [], problems
        # 先试「逐队直接查」；套餐不让（免费版只开放旧赛季）就改成逐日读比赛列表
        forms: Dict[str, List[Dict[str, Any]]] = {}
        mode = "days" if "fb:team" in off else "team"
        f0 = resolved[0][1]
        if mode == "team":
            try:
                forms[str(f0["teams"]["home"]["id"])] = self._team_rows(c, f0["teams"]["home"]["id"], f0.get("league", {}).get("season"),
                                                                        float(f0["fixture"]["timestamp"]))
            except DataError as exc:
                if exc.kind == "plan":
                    mode = "days"
                    off.add("fb:team")
                elif exc.fatal or exc.kind in ("auth", "net", "quota"):
                    raise
        if mode == "days":
            self.log("  当前套餐不让直接查球队近况，改成逐日读过去的比赛列表来算近况（第一次要读几十天，读过的会存起来）……")
            tids = {str(f["teams"][s]["id"]) for _, f in resolved for s in ("home", "away")}
            earliest = min(m["kick"] for m, _ in resolved)
            forms = self._sweep(c, "fixtures", SLIM_FX, tids, pool, earliest, MAX_SWEEP_DAYS, problems)
            problems.append("近况是逐日读比赛列表算出来的（近几十天内的各项比赛，含联赛、杯赛、欧战）。")
        data: Dict[int, Dict[str, Any]] = {}
        stop = False
        for i, (m, f) in enumerate(resolved):          # 阶段 B：近况 + 伤停（最重要）
            if stop:
                break
            hid, aid = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
            season = f.get("league", {}).get("season")
            ts = float(f["fixture"]["timestamp"])
            try:
                if mode == "team":
                    for t in (hid, aid):
                        if str(t) not in forms:
                            forms[str(t)] = self._team_rows(c, t, season, ts)
                rec: Dict[str, Any] = {"f": f, "hrows": finished_before(forms.get(str(hid), []), ts),
                                       "arows": finished_before(forms.get(str(aid), []), ts)}
                if "fb:injuries" not in off:
                    try:
                        rec["inj"] = c.get("injuries", {"fixture": f["fixture"]["id"]}, ttl=TTL_INJ) or []
                    except DataError as exc:
                        if exc.fatal or exc.kind in ("quota", "net", "auth"):
                            raise
                        if exc.kind == "plan":
                            off.add("fb:injuries")
                data[i] = rec
                self.log(f"  [{len(data)}/{len(resolved)}] {m['home']} vs {m['away']}")
            except DataError as exc:
                if exc.fatal or exc.kind in ("auth", "plan", "net"):
                    raise
                problems.append(str(exc))
                stop = exc.kind == "quota"
                data.pop(i, None)
        if "fb:h2h" not in off:                        # 阶段 C：交锋（额度够、套餐给才查）
            for i, rec in data.items():
                f = rec["f"]
                try:
                    rec["h2h"] = c.get("fixtures/headtohead", {"h2h": f"{f['teams']['home']['id']}-{f['teams']['away']['id']}", "last": H2H_N},
                                       ttl=TTL_H2H) or []
                except DataError as exc:
                    if exc.fatal or exc.kind in ("auth", "net"):
                        raise
                    if exc.kind == "plan":
                        off.add("fb:h2h")
                        break
                    if exc.kind == "quota":
                        problems.append("额度不够，部分比赛没查交锋/排名。")
                        break
        leagues: Dict[Tuple[Any, Any], Dict[str, Dict[str, int]]] = {}
        if "fb:standings" not in off:                  # 阶段 D：联赛排名（每个联赛查一次）
            stop_d = False
            for i, rec in data.items():
                if stop_d:
                    break
                f = rec["f"]
                season = f.get("league", {}).get("season")
                for side, rows, tid in (("h", rec["hrows"], f["teams"]["home"]["id"]), ("a", rec["arows"], f["teams"]["away"]["id"])):
                    lid = Counter(r["league"]["id"] for r in rows if str(r.get("league", {}).get("round", "")).startswith("Regular Season")
                                  ).most_common(1)
                    if not lid:
                        continue
                    lid_, sea = lid[0][0], next((r["league"].get("season") for r in rows if r["league"].get("id") == lid[0][0]), season)
                    if (lid_, sea) not in leagues:
                        try:
                            leagues[(lid_, sea)] = _standing_map(c.get("standings", {"league": lid_, "season": sea}, ttl=TTL_STAND))
                        except DataError as exc:
                            if exc.fatal or exc.kind in ("auth", "net"):
                                raise
                            leagues[(lid_, sea)] = {}
                            if exc.kind in ("plan", "quota"):
                                if exc.kind == "plan":
                                    off.add("fb:standings")
                                stop_d = True
                                break
                    rec["rank_" + side] = leagues[(lid_, sea)].get(str(tid))
        notes: List[Dict[str, Any]] = []
        for i, rec in data.items():
            m, f = resolved[i]
            hid, aid = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
            hs, as_ = team_stats(rec["hrows"], hid), team_stats(rec["arows"], aid)
            if hs["n"] == 0 or as_["n"] == 0:
                problems.append(f"{m['home']}vs{m['away']}：接口里查不到近况")
                continue
            inj = rec.get("inj")
            hinj = _player_out(inj, hid) if inj is not None else None
            ainj = _player_out(inj, aid) if inj is not None else None
            h2h = h2h_stats(finished_before(rec["h2h"], float(f["fixture"]["timestamp"])), hid, aid) if "h2h" in rec else None
            verdict, lean, score, why = judge(m.get("side"), int(m.get("need") or 1), hs, as_, hinj, ainj, h2h)
            notes.append(self._note(m, hs, as_, hinj, ainj, h2h, rec.get("rank_h"), rec.get("rank_a"), verdict, lean, score, why))
        return notes, problems

    # ───────── 篮球 ─────────
    def _basketball(self, ms: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[str]]:
        c, off = self.bb, self.off
        problems: List[str] = []
        notes: List[Dict[str, Any]] = []
        pool: Dict[str, List[Dict[str, Any]]] = {}
        resolved: List[Tuple[Dict[str, Any], Dict[str, Any]]] = []
        self.log(f"  篮球：{len(ms)} 场……")
        for m in ms:
            d = m["kick"].astimezone(timezone.utc).strftime("%Y-%m-%d")
            if d not in pool:
                pool[d] = self._fixtures_on(c, m["kick"], "games", SLIM_BG)
            games = [dict(g, fixture={"timestamp": g.get("timestamp"), "id": g.get("id")}) for g in pool[d]]
            f, why = find_fixture(self.names, games, m["home"], m["away"], m["kick"])
            if f is None:
                problems.append(f"{m['home']}vs{m['away']}：{why}")
            else:
                resolved.append((m, f))
        if not resolved:
            return notes, problems
        forms: Dict[str, List[Dict[str, Any]]] = {}
        mode = "days" if "bb:team" in off else "team"
        f0 = resolved[0][1]
        if mode == "team":
            try:
                forms[str(f0["teams"]["home"]["id"])] = c.get("games", {"team": f0["teams"]["home"]["id"],
                                                                        "season": (f0.get("league") or {}).get("season")}, ttl=TTL_FORM) or []
            except DataError as exc:
                if exc.kind == "plan":
                    mode = "days"
                    off.add("bb:team")
                elif exc.fatal or exc.kind in ("auth", "net", "quota"):
                    raise
        if mode == "days":
            self.log("  篮球：当前套餐不让直接查球队近况，改成逐日读比赛列表……")
            tids = {str(f["teams"][s]["id"]) for _, f in resolved for s in ("home", "away")}
            forms = self._sweep(c, "games", SLIM_BG, tids, pool, min(m["kick"] for m, _ in resolved), MAX_SWEEP_DAYS_BB, problems)
            problems.append("篮球近况同样是逐日读比赛列表算出来的。")
        for m, f in resolved:
            try:
                hid, aid = f["teams"]["home"]["id"], f["teams"]["away"]["id"]
                lg = f.get("league") or {}
                season, lid = lg.get("season"), lg.get("id")
                ts = float(f["fixture"]["timestamp"])
                if mode == "team":
                    for t in (hid, aid):
                        if str(t) not in forms:
                            forms[str(t)] = c.get("games", {"team": t, "season": season}, ttl=TTL_FORM) or []
                hrows, arows = finished_before(forms.get(str(hid), []), ts), finished_before(forms.get(str(aid), []), ts)
                h2h_rows: List[Dict[str, Any]] = []
                if "bb:h2h" not in off:
                    try:
                        h2h_rows = c.get("games", {"h2h": f"{hid}-{aid}"}, ttl=TTL_H2H) or []
                    except DataError as exc:
                        if exc.fatal or exc.kind in ("auth", "net"):
                            raise
                        if exc.kind == "plan":
                            off.add("bb:h2h")
                smap: Dict[str, Dict[str, int]] = {}
                if "bb:standings" not in off:
                    try:
                        smap = _standing_map(c.get("standings", {"league": lid, "season": season}, ttl=TTL_STAND))
                    except DataError as exc:
                        if exc.fatal or exc.kind in ("auth", "net"):
                            raise
                        if exc.kind == "plan":
                            off.add("bb:standings")
            except DataError as exc:
                if exc.fatal or exc.kind in ("auth", "plan", "net"):
                    raise
                problems.append(f"{m['home']}vs{m['away']}：{exc}")
                if exc.kind == "quota":
                    break
                continue
            hs, as_ = self._bstats(hrows, hid), self._bstats(arows, aid)
            if hs["n"] == 0 or as_["n"] == 0:
                problems.append(f"{m['home']}vs{m['away']}：接口里查不到近况")
                continue
            h2h = h2h_stats(finished_before(h2h_rows, ts), hid, aid)
            verdict, lean, score, why = self._bjudge(m.get("side"), hs, as_, smap.get(str(hid)), smap.get(str(aid)), abs(float(m.get("line") or 0)))
            notes.append(self._bnote(m, hs, as_, smap.get(str(hid)), smap.get(str(aid)), h2h, verdict, lean, score, why))
        return notes, problems

    @staticmethod
    def _bstats(rows: List[Dict[str, Any]], tid: Any) -> Dict[str, Any]:
        rows = rows[:FORM_N]
        w = l = 0
        diff = 0
        for f in rows:
            h, a = _goals(f)
            home = str(f["teams"]["home"]["id"]) == str(tid)
            mine, theirs = (h, a) if home else (a, h)
            diff += mine - theirs
            if mine > theirs:
                w += 1
            else:
                l += 1
        k = len(rows)
        return {"n": k, "w": w, "l": l, "avg": diff / k if k else None}

    @staticmethod
    def _bjudge(side: Optional[str], hs: Dict[str, Any], as_: Dict[str, Any], hr: Optional[Dict[str, int]], ar: Optional[Dict[str, int]],
                line: float) -> Tuple[str, Optional[str], Optional[float], str]:
        if side not in ("home", "away"):
            return "mixed", None, None, "这场的推荐不是单一方向，只列数据、不下结论"
        if hs["n"] < 3 or as_["n"] < 3:
            return "mixed", None, None, "近况场次太少，没法下结论"
        x, y = (hs, as_) if side == "home" else (as_, hs)
        score = 3 * (x["w"] / x["n"] - y["w"] / y["n"]) + 0.15 * (x["avg"] - y["avg"])
        xr, yr = (hr, ar) if side == "home" else (ar, hr)
        if xr and yr and xr.get("w") is not None and (xr["w"] + xr["l"]) and (yr["w"] + yr["l"]):
            score += 1.5 * (xr["w"] / (xr["w"] + xr["l"]) - yr["w"] / (yr["w"] + yr["l"]))
        thr = 1.8 if line >= 10 else 1.0
        if score >= thr:
            verdict, why = "support", "近况和战绩明显更好"
        elif score <= AGAINST:
            verdict, why = "against", "近况和战绩不如对手"
        else:
            verdict = "mixed"
            why = "近况接近" if abs(score) < 0.3 else ("占优但让分很深，赢球不等于赢够分差" if score > 0 and line >= 10 else "略占优" if score > 0 else "略差")
        other = "away" if side == "home" else "home"
        return verdict, (side if score >= 0.3 else other if score <= -0.3 else None), round(score, 2), why

    # ───────── 文案 ─────────
    @staticmethod
    def _teams_field(m: Dict[str, Any]) -> List[str]:
        return teams_field(m)

    def _note(self, m, hs, as_, hinj, ainj, h2h, rh, ra, verdict, lean, score, why) -> Dict[str, Any]:
        def part(zh: str, st: Dict[str, Any], rank: Optional[Dict[str, int]], inj: Optional[Dict[str, int]]) -> str:
            s = f"{zh}近{st['n']}场{st['w']}胜{st['d']}平{st['l']}负（进{st['gf']}失{st['ga']}）"
            if rank:
                s += f"、联赛第{rank['rank']}（{rank['pts']}分/{rank['played']}场）"
            if inj is not None:
                if inj["out"] and inj["q"]:
                    s += f"、缺{inj['out']}人另{inj['q']}人存疑"
                elif inj["out"]:
                    s += f"、缺{inj['out']}人"
                elif inj["q"]:
                    s += f"、{inj['q']}人伤停存疑"
                else:
                    s += "、无伤停记录"
            return s
        txt = part(m["home"], hs, rh, hinj) + "；" + part(m["away"], as_, ra, ainj)
        if h2h and h2h["n"]:
            txt += f"；近{h2h['n']}次交锋{m['home']}{h2h['hw']}胜{h2h['d']}平{h2h['aw']}负"
        return self._finish(m, txt, verdict, lean, score, why)

    def _bnote(self, m, hs, as_, hr, ar, h2h, verdict, lean, score, why) -> Dict[str, Any]:
        def part(zh: str, st: Dict[str, Any], rk: Optional[Dict[str, int]]) -> str:
            s = f"{zh}近{st['n']}场{st['w']}胜{st['l']}负（场均净胜{st['avg']:+.1f}）"
            if rk and rk.get("w") is not None:
                s += f"、赛季{rk['w']}胜{rk['l']}负排第{rk['rank']}"
            return s
        txt = part(m["home"], hs, hr) + "；" + part(m["away"], as_, ar)
        if h2h and h2h["n"]:
            txt += f"；近{h2h['n']}次交锋{m['home']}{h2h['hw']}胜{h2h['aw']}负"
        txt += "；伤停接口无此项"
        return self._finish(m, txt, verdict, lean, score, why)

    def _finish(self, m: Dict[str, Any], txt: str, verdict: str, lean: Optional[str], score: Optional[float], why: str) -> Dict[str, Any]:
        return finish_note(m, txt, verdict, lean, score, why)


def teams_field(m: Dict[str, Any]) -> List[str]:
    """给 manual 的 match_notes 用的队名写法：名字超过 3 个字时，再附一个前 3 个字的叫法，方便对上。"""
    def alt(n: str) -> str:
        return n if len(n) <= 3 else f"{n}|{n[:3]}"
    return [alt(m["home"]), alt(m["away"])]


def finish_note(m: Dict[str, Any], txt: str, verdict: str, lean: Optional[str], score: Optional[float], why: str) -> Dict[str, Any]:
    """把「两队数据那一句」+ 结论拼成一条 match_note（所有数据来源共用）。"""
    who = (m["home"] if m.get("side") == "home" else m["away"]) if m.get("side") in ("home", "away") else ""
    tail = {"support": f"数据支持{who}", "mixed": f"数据只部分支持{who}（{why}）" if who else why,
            "against": f"数据不支持{who}（{why}），不单选"}[verdict]
    note = txt + "。" + tail
    return {"teams": teams_field(m), "verdict": verdict, "note": note, "why": f"{m['home']}vs{m['away']}：{why}",
            "lean": {"home": "home", "away": "away"}.get(lean or ""), "score": score, "auto": True, "mk": [m["home"], m["away"]]}


# ═══════════════════════ 6. 命令行：测试连接 ═══════════════════════
def load_key(folder: Path, explicit: str = "") -> str:
    """密钥来源（优先级）：参数 > 环境变量 API_FOOTBALL_KEY / API_SPORTS_KEY > 文件夹里的 api_key.txt。"""
    if explicit.strip():
        return explicit.strip()
    for name in ("API_FOOTBALL_KEY", "API_SPORTS_KEY"):
        if os.environ.get(name, "").strip():
            return os.environ[name].strip()
    try:
        return L.p(folder, "api_key.txt").read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="测试两队数据接口能不能用")
    ap.add_argument("--check", action="store_true", help="测试连接（密钥是否有效、能不能取到今天的比赛）")
    ap.add_argument("--key", default="", help="接口密钥；不写则读环境变量或同目录 api_key.txt")
    ap.add_argument("--proxy", default="")
    a = ap.parse_args(argv)
    here = L.app_root(__file__)
    prov = Provider(load_key(here, a.key), L.p(here, "data_cache"), log=print, proxy=a.proxy)
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
