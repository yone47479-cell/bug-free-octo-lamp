# -*- coding: utf-8 -*-
"""
match_model.py —— 用自己的赛果库（results_db.json，每次更新从 500 网完场页攒的真实比分）给每场比赛算一份「数据模型」依据。
只用 Python 标准库；不上网；队名走赛果库同一套别名，所以没有「队名对不上」的问题。

那 100 个网站里大部分“深度数据”（泊松预测、xG 趋势、大小球/双方进球率、主客场分开的战绩、休息天数、赛程密度……）
本质上都是拿比分算出来的统计。我们有两万多场真实比分，直接自己算，既不依赖外站、不踩它们的抓取限制，也不会错配队名。

模型（刻意做得简单、可检查）：
  1. 每队取开赛前最近 N_GAMES 场（友谊赛不算），越近权重越大（DECAY），进球/失球先按主客场差异校正；
  2. 往联赛平均靠拢（SHRINK 个“虚拟场次”），样本少时不会算出极端值；
  3. 预计进球 λ主 = 主场系数 × 主队攻 × 客队守 ÷ 联赛场均，λ客同理；
  4. 两个泊松分布相乘 → 比分概率表 → 胜平负、净胜 N 球、大 2.5 球、双方进球。
它不知道伤停、首发、战意，只是“两队近况 + 联赛水平”的数学推算，和新浪文章、北单 SP 一起做交叉印证，不是单独的结论。

自动回测：每次运行都用赛果库里最近一段时间的比赛做「只用赛前数据」的滚动回测，看模型比“只看联赛主客胜平比例”的基准好不好。
回测不过关（比基准差、或场次太少）时，模型只显示、不参与判断（model_check.json 里记着）。

v1.2 新增（都是「可选部件」，默认全关；每周自动择优时，只有在赛果库上前后两半时间都明显变好才会打开）：
  · 长期实力：除了最近几场的状态，再掺一份近 30 场的长期水平（状态会骗人，长期水平更稳）；
  · 主客场分开：主队的实力多参考它的主场比赛，客队多参考客场比赛（有的队主场特别强）；
  · 对手强弱：为每队滚动维护一份「进攻/防守等级」（踢赢强队比踢赢弱队更值钱），和近况模型各占一部分；
  · 低比分修正：0:0、1:1、1:0 的实际概率和独立泊松有点出入（Dixon–Coles），可以修一下。
  另外每场多存一张「让球分布表」（让 -3～+3 球时，胜/平/负各多少），给「综合推单」把模型概率和北单/竞足赔率放到同一个让球线上合并。

两个自动「自我校正」（都用赛果库回测验证，验证不通过就不启用，结果记在 model_check.json）：
  · 概率校准：泊松模型常常「吹过头」（比如说把握 55% 的比赛实际只赢 47%）。用回测里的「模型概率 vs 实际结果」拟合两个小参数
    （把概率往中间收一收、把平局概率调一调），前 70% 的场次拟合、后 30% 的场次验证，验证里对数损失真的变好才启用；
  · 参数自动择优：每队看最近几场（N_GAMES）、近的比赛多重要（DECAY）、往联赛平均靠拢多少（SHRINK），每周在赛果库上试一遍，
    挑校准后对数损失最低的一组，比默认好得足够多才换。
"""
from __future__ import annotations

import argparse
import bisect
import json
import hashlib
import math
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import layout as L
from reliability import atomic_write_text

__version__ = "1.4"
N_GAMES = 8            # 每队看最近几场
DECAY = 0.85           # 越近的比赛权重越大（第 i 场前的比赛权重 DECAY**i）
SHRINK = 3.0           # 往联赛平均靠拢的“虚拟场次”
MIN_GAMES = 4          # 每队至少要有这么多场赛前比分，否则不算
MAX_GOALS = 9          # 比分表算到每队 9 球（再多的概率小到可以忽略，最后会归一）
LG_MIN = 40            # 一个联赛的比分少于这么多场，就用全部联赛的平均
LAMBDA_MIN, LAMBDA_MAX = 0.25, 4.0
BT_DAYS = 45           # 回测看最近多少天的比赛
BT_MIN_N = 150         # 回测场次少于这个，不能证明模型靠谱
BT_MAX_N = 4000        # 回测最多评估这么多场（超过就隔几场抽一场，让每次更新的回测不超过几秒）
BT_MARGIN = 0.003      # 模型的对数损失要比基准至少低这么多才算“比基准好”
ADJ_MAX = 0.4          # 模型最多给“数据对比分”加减多少（原来的分：≥0.6 支持，≤-0.8 反对）
ADJ_SLOPE = 2.0
CHECK_FILE = "model_check.json"
CAL_MIN_N = 120          # 概率校准：回测样本至少这么多场才敢拟合
CAL_VAL_FRAC = 0.30      # 校准：最后这一段时间的比赛留着验证，不参与拟合
CAL_MIN_GAIN = 0.0005    # 校准：验证段的对数损失要至少降低这么多才启用
TUNE_EVERY_DAYS = 7      # 参数自动择优：多少天重新选一次
TUNE_MIN_GAIN = 0.002    # 参数自动择优：比默认的对数损失至少好这么多才换（每多打开一个新部件，门槛再抬高一半：试的组合越多，越容易碰巧）
TUNE_MAX_EVAL = 1200     # 择优时每组参数最多评估多少场（越少越快）
TUNE_BUDGET_S = 90.0     # 择优最多花多少秒（超了就用目前最好的）
# 模型参数（顺序固定）：近 n 场、衰减、收缩 ｜ 长期占比、主客场分开占比、对手强弱等级占比、等级学习速度、等级遗忘、低比分修正
PARAM_KEYS = ("n", "decay", "shrink", "lw", "vw", "rw", "eta", "kap", "rho")
PARAM_DEFAULT = (N_GAMES, DECAY, SHRINK, 0.0, 0.0, 0.0, 0.03, 0.01, 0.0)
NEW_KEYS = ("lw", "vw", "rw", "rho")                       # 打开了才算「新部件」；eta/kap 只在 rw>0 时才有用
TUNE_GRID = {"n": (5, 6, 8, 10, 12, 15, 20), "decay": (0.75, 0.80, 0.85, 0.90, 0.95), "shrink": (1.0, 2.0, 3.0, 5.0, 8.0, 12.0),
             "lw": (0.0, 0.25, 0.5, 0.75, 1.0), "vw": (0.0, 0.25, 0.5), "rw": (0.0, 0.3, 0.5, 0.7, 0.85, 1.0),
             "eta": (0.008, 0.015, 0.03, 0.05), "kap": (0.002, 0.004, 0.01, 0.025), "rho": (0.0, -0.04, -0.08, -0.12)}
LONG_N, LONG_DECAY, LONG_SHRINK = 30, 0.97, 6.0           # 长期实力：看近 30 场，衰减慢，往联赛平均靠得更多
VENUE_N, VENUE_SHRINK = 10, 4.0                           # 主客场分开：同场地最近 10 场，先验是该队不分场地的实力
LINES = (-3, -2, -1, 0, 1, 2, 3)                          # 「让球分布表」存哪几条让球线（主队让球为负）


def _is_friendly(lg: str) -> bool:
    return "友谊" in (lg or "")


def _parse(k: str) -> Optional[datetime]:
    try:
        return datetime.strptime(k[:16], "%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        return None


def poisson_grid(lh: float, la: float, maxg: int = MAX_GOALS, rho: float = 0.0) -> List[List[float]]:
    """P[i][j] = 主队进 i 球、客队进 j 球的概率（独立泊松，归一）。rho≠0 时按 Dixon–Coles 修正 0:0/0:1/1:0/1:1 四个低比分。"""
    def pmf(lam: float) -> List[float]:
        p = [math.exp(-lam)]
        for i in range(1, maxg + 1):
            p.append(p[-1] * lam / i)
        return p
    ph, pa = pmf(lh), pmf(la)
    g = [[ph[i] * pa[j] for j in range(maxg + 1)] for i in range(maxg + 1)]
    if rho:
        g[0][0] *= max(0.0, 1 - lh * la * rho)
        g[0][1] *= max(0.0, 1 + lh * rho)
        g[1][0] *= max(0.0, 1 + la * rho)
        g[1][1] *= max(0.0, 1 - rho)
    s = sum(sum(r) for r in g) or 1.0
    return [[x / s for x in r] for r in g]


def line_table(g: List[List[float]], lines: Tuple[int, ...] = LINES) -> Dict[str, List[float]]:
    """让球分布表：主队让球 L（L<0 = 主队让 |L| 球，L>0 = 主队受让 L 球）时，[让球胜, 让球平, 让球负] 的概率（比分表直接算，没校准）。"""
    n = len(g)
    diff: Dict[int, float] = {}
    for i in range(n):
        for j in range(n):
            diff[i - j] = diff.get(i - j, 0.0) + g[i][j]
    out: Dict[str, List[float]] = {}
    for L_ in lines:
        w = sum(v for d, v in diff.items() if d + L_ > 0)
        dr = diff.get(-L_, 0.0)
        out[str(L_)] = [w, dr, max(0.0, 1.0 - w - dr)]
    return out


def summarize(g: List[List[float]]) -> Dict[str, Any]:
    n = len(g)
    ph = sum(g[i][j] for i in range(n) for j in range(n) if i > j)
    pd = sum(g[i][i] for i in range(n))
    pa = sum(g[i][j] for i in range(n) for j in range(n) if i < j)
    over25 = sum(g[i][j] for i in range(n) for j in range(n) if i + j >= 3)
    btts = sum(g[i][j] for i in range(1, n) for j in range(1, n))
    top = sorted(((g[i][j], i, j) for i in range(n) for j in range(n)), reverse=True)[:3]
    return {"ph": ph, "pd": pd, "pa": pa, "o25": over25, "btts": btts, "top": [(f"{i}:{j}", p) for p, i, j in top]}


def card(p: Dict[str, Any], ok: bool) -> Dict[str, Any]:
    """把一场的模型输出压成帖子里要用的几个数：最可能的 3 个比分、最可能的连续 3 个总进球数、胜平负概率、预计进球。
    ok = 回测有没有过关（没过关的只存着，帖子里不写）。全部是从两队近况推算的，不是预测保证。
    ln = 让球分布表（让 -3～+3 球时 [让球胜, 平, 负] 的概率；0 线用校准后的胜平负，其余线按校准的「收缩」程度一起往中间收），给综合推单用。"""
    g = p["grid"]
    n = len(g)
    tot = [0.0] * (2 * n - 1)
    for i in range(n):
        for j in range(n):
            tot[i + j] += g[i][j]
    k = max(range(len(tot) - 2), key=lambda t: tot[t] + tot[t + 1] + tot[t + 2])
    ln = line_table(g)
    cal = p.get("calib")
    for key, v in ln.items():
        if key == "0":
            v = [p["ph"], p["pd"], p["pa"]]
        elif cal and p.get("calibrated"):
            v = list(calibrate(tuple(v), {"alpha": cal.get("alpha", 1.0), "wd": 1.0}))
        ln[key] = [round(x, 4) for x in v]
    return {"ok": bool(ok), "top": [s for s, _ in p["top"]], "ptop": [round(q, 3) for _, q in p["top"]],
            "goals": [k, k + 1, k + 2], "pg": round(sum(tot[k:k + 3]), 3),
            "lh": round(p["lh"], 2), "la": round(p["la"], 2),
            "ph": round(p["ph"], 3), "pd": round(p["pd"], 3), "pa": round(p["pa"], 3),
            "o25": round(p["o25"], 3), "btts": round(p["btts"], 3), "cal": bool(p.get("calibrated")), "ln": ln}


def margin_prob(g: List[List[float]], side: str, need: int) -> float:
    """推荐方净胜 need 球及以上的概率（need=1 就是赢球）。"""
    n = len(g)
    if side == "home":
        return sum(g[i][j] for i in range(n) for j in range(n) if i - j >= need)
    return sum(g[i][j] for i in range(n) for j in range(n) if j - i >= need)


def pad_params(params: Optional[Any]) -> Tuple[float, ...]:
    """参数元组补全：老版本只有 (n, decay, shrink) 三个，后面的新部件按默认（全关）补上。"""
    base = list(PARAM_DEFAULT)
    if params:
        for i, v in enumerate(list(params)[:len(base)]):
            base[i] = v
    return tuple(base)


class Model:
    """滚动模型：add_game 一场场加进来（按时间顺序），predict 只会用开赛时间之前的比赛。"""

    def __init__(self, canon: Any = None, params: Optional[Tuple[float, ...]] = None, calib: Optional[Dict[str, float]] = None):
        self.canon = canon or (lambda s: s)
        self.P: Tuple[float, ...] = pad_params(params)                                                # 近几场、衰减、收缩、长期占比、主客场占比、等级占比、等级学习速度、遗忘、低比分修正
        self.calib: Optional[Dict[str, float]] = calib                                               # 概率校准（None = 不校准）
        self.team: Dict[str, Dict[str, list]] = {}          # 队 → {"k": [时间...], "g": [(is_home, gf, ga, lg)...]}
        self.lg: Dict[str, List[float]] = {}                # 联赛 → [场数, 主队进球合计, 客队进球合计]
        self.rat: Dict[str, List[float]] = {}               # 队 → [进攻等级, 防守等级]（对数尺度，只在 rw>0 时滚动维护）
        self.all = [0, 0.0, 0.0]
        self.n_games = 0

    @classmethod
    def from_db(cls, db: Any, params: Optional[Tuple[float, ...]] = None, calib: Optional[Dict[str, float]] = None) -> "Model":
        m = cls(db.names.canon, params, calib)
        for r in sorted(db.rows, key=lambda r: r["k"]):
            m.add_game(r)
        return m

    def add_game(self, r: Dict[str, Any]) -> None:
        try:
            k, hs, as_ = r["k"], int(r["hs"]), int(r["as"])
            h, a = self.canon(r["h"]), self.canon(r["a"])
        except (KeyError, TypeError, ValueError):
            return
        lg = r.get("lg", "") or ""
        if _is_friendly(lg):
            return
        if self.P[5] > 0:
            self._rate(h, a, hs, as_, lg)                    # 等级更新要用「这场之前」的联赛场均，所以放在更新联赛统计之前
        for key, is_home, gf, ga in ((h, 1, hs, as_), (a, 0, as_, hs)):
            t = self.team.setdefault(key, {"k": [], "g": []})
            if t["k"] and k < t["k"][-1]:                    # 乱序插入（一般不会发生）
                i = bisect.bisect_right(t["k"], k)
                t["k"].insert(i, k)
                t["g"].insert(i, (is_home, gf, ga, lg))
            else:
                t["k"].append(k)
                t["g"].append((is_home, gf, ga, lg))
        s = self.lg.setdefault(lg, [0, 0.0, 0.0])
        s[0] += 1; s[1] += hs; s[2] += as_
        self.all[0] += 1; self.all[1] += hs; self.all[2] += as_
        self.n_games += 1

    # —— 查询 ——
    def games(self, name: str, before: str, n: Optional[int] = None) -> List[Tuple[str, int, int, int, str]]:
        """开赛前最近 n 场（不给就用模型的 N_GAMES），最近的在前：[(时间, 是否主场, 进, 失, 联赛)]"""
        n = self.P[0] if n is None else n
        t = self.team.get(self.canon(name))
        if not t:
            return []
        i = bisect.bisect_left(t["k"], before)
        lo = max(0, i - n)
        return [(t["k"][j],) + t["g"][j] for j in range(i - 1, lo - 1, -1)]

    def base(self, lg: str) -> Tuple[float, float, str]:
        """联赛场均 (主队进球, 客队进球, 用的是哪个口径)。"""
        s = self.lg.get(lg)
        if s and s[0] >= LG_MIN:
            return s[1] / s[0], s[2] / s[0], lg
        if self.all[0] >= LG_MIN:
            return self.all[1] / self.all[0], self.all[2] / self.all[0], "全部联赛"
        return 1.45, 1.15, "默认值"

    def league_of(self, home: str, away: str, before: str) -> str:
        for nm in (home, away):
            for g in self.games(nm, before, 3):
                if g[4]:
                    return g[4]
        return ""

    def _rate(self, h: str, a: str, hs: int, as_: int, lg: str) -> None:
        """滚动更新两队的进攻/防守等级：实际进球比「按当前等级该进的」多，进攻等级就涨、对手防守等级就差一点（泊松回归的一步梯度）。"""
        mh, ma, _ = self.base(lg)
        eta, kap = self.P[6], self.P[7]
        rh = self.rat.setdefault(h, [0.0, 0.0])
        ra = self.rat.setdefault(a, [0.0, 0.0])
        lh = mh * math.exp(rh[0] + ra[1])
        la = ma * math.exp(ra[0] + rh[1])
        dh, da = hs - lh, as_ - la
        keep = 1.0 - kap
        clamp = lambda x: max(-1.2, min(1.2, x))            # noqa: E731
        rh[0], ra[1] = clamp(rh[0] * keep + eta * dh), clamp(ra[1] * keep + eta * dh)
        ra[0], rh[1] = clamp(ra[0] * keep + eta * da), clamp(rh[1] * keep + eta * da)

    def _strength(self, games: List[Tuple[str, int, int, int, str]], mh: float, ma: float,
                  prior: Optional[Tuple[float, float]] = None, shrink: Optional[float] = None, decay: Optional[float] = None) -> Optional[Tuple[float, float]]:
        mu = (mh + ma) / 2.0
        fh, fa = mh / mu, ma / mu
        sw = sa = sd = 0.0
        decay = self.P[1] if decay is None else decay
        shrink = self.P[2] if shrink is None else shrink
        p_att, p_def = prior if prior else (mu, mu)
        for i, (_, is_home, gf, ga, _) in enumerate(games):
            w = decay ** i
            sw += w
            sa += w * (gf / (fh if is_home else fa))        # 把主客场的进球差异先除掉
            sd += w * (ga / (fa if is_home else fh))
        if sw <= 0:
            return None
        return (sa + shrink * p_att) / (sw + shrink), (sd + shrink * p_def) / (sw + shrink)

    def _team_strength(self, name: str, before: str, games: List[Tuple[str, int, int, int, str]], is_home: int,
                       mh: float, ma: float) -> Optional[Tuple[float, float]]:
        """一队的 (进攻, 防守) 强度：近况为主，按参数掺入长期实力和同场地（主/客场）实力。"""
        st = self._strength(games, mh, ma)
        if not st:
            return None
        lw, vw = self.P[3], self.P[4]
        if lw > 0:
            lg_ = self._strength(self.games(name, before, LONG_N), mh, ma, shrink=LONG_SHRINK, decay=LONG_DECAY)
            if lg_:
                st = ((1 - lw) * st[0] + lw * lg_[0], (1 - lw) * st[1] + lw * lg_[1])
        if vw > 0:
            vg = [g for g in self.games(name, before, 40) if g[1] == is_home][:VENUE_N]
            if len(vg) >= 3:
                v = self._strength(vg, mh, ma, prior=st, shrink=VENUE_SHRINK)
                if v:
                    st = ((1 - vw) * st[0] + vw * v[0], (1 - vw) * st[1] + vw * v[1])
        return st

    def predict(self, home: str, away: str, before: str, lg: str = "", lean: bool = False) -> Optional[Dict[str, Any]]:
        """lean=True：回测/择优时用，不算休息天数、主客场战绩这些只给帖子文字用的辅助统计（快很多）。"""
        gh, ga_ = self.games(home, before), self.games(away, before)
        if len(gh) < MIN_GAMES or len(ga_) < MIN_GAMES:
            return None
        lg = lg or self.league_of(home, away, before)
        mh, ma, basis = self.base(lg)
        mu = (mh + ma) / 2.0
        sh, sa = self._team_strength(home, before, gh, 1, mh, ma), self._team_strength(away, before, ga_, 0, mh, ma)
        if not sh or not sa:
            return None
        lam_h = max(LAMBDA_MIN, min(LAMBDA_MAX, (mh / mu) * sh[0] * sa[1] / mu))
        lam_a = max(LAMBDA_MIN, min(LAMBDA_MAX, (ma / mu) * sa[0] * sh[1] / mu))
        rw = self.P[5]
        if rw > 0:                                                # 掺入「对手强弱等级」算出的进球期望（对数尺度上加权平均）
            rh_, ra_ = self.rat.get(self.canon(home), (0.0, 0.0)), self.rat.get(self.canon(away), (0.0, 0.0))
            lr_h = max(LAMBDA_MIN, min(LAMBDA_MAX, mh * math.exp(rh_[0] + ra_[1])))
            lr_a = max(LAMBDA_MIN, min(LAMBDA_MAX, ma * math.exp(ra_[0] + rh_[1])))
            lam_h = math.exp((1 - rw) * math.log(lam_h) + rw * math.log(lr_h))
            lam_a = math.exp((1 - rw) * math.log(lam_a) + rw * math.log(lr_a))
        g = poisson_grid(lam_h, lam_a, rho=self.P[8])
        out = summarize(g)
        out.update(lh=lam_h, la=lam_a, grid=g, n=(len(gh), len(ga_)), lg=lg, basis=basis, base=(mh, ma), calib=self.calib)
        out["ph0"], out["pd0"], out["pa0"] = out["ph"], out["pd"], out["pa"]
        out["calibrated"] = False
        if self.calib:
            out["ph"], out["pd"], out["pa"] = calibrate((out["ph"], out["pd"], out["pa"]), self.calib)
            out["calibrated"] = True
        if lean:
            return out
        out["rest"] = (self._rest(gh, before), self._rest(ga_, before))
        out["load14"] = (self._load(gh, before), self._load(ga_, before))
        out["h_venue"] = self._venue(self.games(home, before, 40), 1)
        out["a_venue"] = self._venue(self.games(away, before, 40), 0)
        out["h_ou"], out["a_ou"] = self._ou(gh[:6]), self._ou(ga_[:6])
        return out

    # —— 辅助统计 ——
    @staticmethod
    def _rest(games: List[Tuple[str, int, int, int, str]], before: str) -> Optional[float]:
        a, b = _parse(games[0][0]) if games else None, _parse(before)
        return round((b - a).total_seconds() / 86400, 1) if a and b else None

    @staticmethod
    def _load(games: List[Tuple[str, int, int, int, str]], before: str) -> int:
        b = _parse(before)
        if not b:
            return 0
        lo = (b - timedelta(days=14)).strftime("%Y-%m-%d %H:%M")
        return sum(1 for g in games if g[0] >= lo)

    @staticmethod
    def _venue(games: List[Tuple[str, int, int, int, str]], is_home: int, n: int = 5) -> Optional[Dict[str, int]]:
        rows = [g for g in games if g[1] == is_home][:n]
        if len(rows) < 3:
            return None
        w = sum(1 for g in rows if g[2] > g[3]); d = sum(1 for g in rows if g[2] == g[3])
        return {"n": len(rows), "w": w, "d": d, "l": len(rows) - w - d, "gf": sum(g[2] for g in rows), "ga": sum(g[3] for g in rows)}

    @staticmethod
    def _ou(games: List[Tuple[str, int, int, int, str]]) -> Optional[Dict[str, int]]:
        if len(games) < 4:
            return None
        return {"n": len(games), "over": sum(1 for g in games if g[2] + g[3] >= 3), "btts": sum(1 for g in games if g[2] > 0 and g[3] > 0)}


# ═══════════════════════ 文字依据 + 对“数据对比分”的微调 ═══════════════════════
def describe(p: Dict[str, Any], home: str, away: str) -> str:
    """一句话依据（写进备查）。数字都是从赛果库推算的，不是网上抄的。"""
    s = (f"数据模型（按两队近{p['n'][0]}/{p['n'][1]}场进失球+{p['lg'] or '联赛'}场均推算）：预计进球{home}{p['lh']:.1f}:{away}{p['la']:.1f}，"
         f"胜平负{p['ph']:.0%}/{p['pd']:.0%}/{p['pa']:.0%}，大2.5球{p['o25']:.0%}，双方进球{p['btts']:.0%}")
    bits = []
    hv, av = p.get("h_venue"), p.get("a_venue")
    if hv:
        bits.append(f"{home}主场近{hv['n']}场{hv['w']}胜{hv['d']}平{hv['l']}负")
    if av:
        bits.append(f"{away}客场近{av['n']}场{av['w']}胜{av['d']}平{av['l']}负")
    r = p.get("rest") or (None, None)
    if r[0] is not None and r[1] is not None:
        if min(r) <= 3.5 or abs(r[0] - r[1]) >= 3:
            bits.append(f"休息{home}{r[0]:g}天/{away}{r[1]:g}天")
    ld = p.get("load14") or (0, 0)
    if max(ld) >= 4:
        bits.append(f"近14天已踢{home}{ld[0]}场/{away}{ld[1]}场")
    if bits:
        s += "；" + "，".join(bits)
    return s


def adjust(p: Dict[str, Any], side: Optional[str], need: int, trusted: bool) -> Tuple[float, str]:
    """推荐方向 side（home/away）要净胜 need 球：模型给它的概率高还是低？返回 (给数据对比分加减多少, 一句说明)。
    trusted=False（回测没过关）时只给说明，不加减分。"""
    if side not in ("home", "away") or "grid" not in p:
        return 0.0, ""
    pr = margin_prob(p["grid"], side, max(1, need))
    if need <= 1 and p.get("calibrated"):                 # 校准过的「赢球概率」比比分表直接算出来的更可靠
        pr = p["ph"] if side == "home" else p["pa"]
    ref = 0.50 if need <= 1 else 0.35
    delta = max(-ADJ_MAX, min(ADJ_MAX, ADJ_SLOPE * (pr - ref)))
    what = "赢球" if need <= 1 else f"净胜{need}球以上"
    txt = f"模型算推荐方{what}概率{pr:.0%}"
    if not trusted:
        return 0.0, txt + "（回测未过关，只参考）"
    return round(delta, 2), txt


# ═══════════════════════ 概率校准 ═══════════════════════
def calibrate(probs: Tuple[float, float, float], c: Dict[str, float]) -> Tuple[float, float, float]:
    """把模型算的 (主胜, 平, 客胜) 概率校准一下：先开 alpha 次方（<1 就是往中间收，不那么极端），平局再乘 wd（>1 就是平局更多一点），再归一。"""
    a, wd = float(c.get("alpha", 1.0)), float(c.get("wd", 1.0))
    q = [max(1e-9, probs[0]) ** a, max(1e-9, probs[1]) ** a * wd, max(1e-9, probs[2]) ** a]
    t = sum(q)
    return (q[0] / t, q[1] / t, q[2] / t)


def _ll_cal(lp: List[Tuple[float, float, float]], ys: List[int], a: float, wd: float) -> float:
    """lp 是已经取过对数的概率；返回平均对数损失。"""
    lwd = math.log(wd)
    tot = 0.0
    exp = math.exp
    for (l0, l1, l2), y in zip(lp, ys):
        e0, e1, e2 = exp(a * l0), exp(a * l1 + lwd), exp(a * l2)
        z = e0 + e1 + e2
        tot += math.log(z) - (a * l0 if y == 0 else a * l1 + lwd if y == 1 else a * l2)
    return tot / max(1, len(ys))


def fit_calibration(samples: List[Dict[str, Any]]) -> Optional[Dict[str, float]]:
    """在这些回测样本上找让对数损失最小的 (alpha, wd)：交替在网格上找，几轮就收敛。样本太少返回 None。"""
    if len(samples) < 30:
        return None
    lp = [tuple(math.log(max(1e-9, x)) for x in s["p"]) for s in samples]
    ys = [s["y"] for s in samples]
    a, wd = 1.0, 1.0
    best = _ll_cal(lp, ys, a, wd)
    for _ in range(3):
        for cand in [0.3 + 0.025 * i for i in range(37)]:
            v = _ll_cal(lp, ys, cand, wd)
            if v < best - 1e-12:
                best, a = v, cand
        for cand in [0.8 + 0.025 * i for i in range(33)]:
            v = _ll_cal(lp, ys, a, cand)
            if v < best - 1e-12:
                best, wd = v, cand
    return {"alpha": round(a, 3), "wd": round(wd, 3), "ll": best, "n": len(samples)}


def _split_cal(samples: List[Dict[str, Any]]) -> Tuple[Optional[Dict[str, Any]], Optional[Dict[str, float]]]:
    """按日期训练60%、验证20%、测试20% → (验证说明, 最终采用的校准或 None)。验证段对数损失没明显变好就不采用。"""
    n = len(samples)
    info: Dict[str, Any] = {"n": n}
    if n < CAL_MIN_N:
        info.update(applied=False, reason=f"回测样本只有 {n} 场（要 ≥{CAL_MIN_N}），不做概率校准")
        return info, None
    fit_s, val_s, test_s = date_split(samples, lambda r: r["k"])
    if min(len(fit_s), len(val_s), len(test_s)) < 30:
        info.update(applied=False, reason="按日期切分后样本不足，不做概率校准")
        return info, None
    c = fit_calibration(fit_s)
    if c is None or len(val_s) < 30:
        info.update(applied=False, reason="样本不够，不做概率校准")
        return info, None
    lp = [tuple(math.log(max(1e-9, x)) for x in s["p"]) for s in val_s]
    ys = [s["y"] for s in val_s]
    raw, cal = _ll_cal(lp, ys, 1.0, 1.0), _ll_cal(lp, ys, c["alpha"], c["wd"])
    info.update(val_n=len(val_s), val_raw=round(raw, 4), val_cal=round(cal, 4), fit_alpha=c["alpha"], fit_wd=c["wd"])
    if raw - cal < CAL_MIN_GAIN:
        info.update(applied=False, reason=f"校准在验证段没有明显变好（{raw:.4f}→{cal:.4f}），不启用")
        return info, None
    full = c  # 保留训练段拟合值，最终测试段不参与校准
    info.update(applied=True, alpha=full["alpha"], wd=full["wd"], reason="")
    return info, {"alpha": full["alpha"], "wd": full["wd"]}


# ═══════════════════════ 回测 ═══════════════════════
def _outcome(hs: int, as_: int) -> int:
    return 0 if hs > as_ else 1 if hs == as_ else 2


def _collect(rows: List[Dict[str, Any]], canon: Any, days: int, params: Optional[Tuple[float, ...]], max_eval: int,
             stats: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
    """滚动回测：按时间顺序一场场过，预测每场时只用它开赛前的比赛；只评估最后 days 天里的比赛（太多就隔几场抽一场）。
    返回样本列表（时间顺序）：{"p": 模型 (主,平,客) 概率, "y": 实际结果 0/1/2, "prior": 基准概率, "o25": 模型大2.5球概率, "ov": 实际是否大2.5球, "ovp": 基准大球率}。"""
    last = _parse(rows[-1]["k"]) if rows else None
    cut = (last - timedelta(days=days)).strftime("%Y-%m-%d %H:%M") if last else "0000"
    stride = max(1, -(-sum(1 for r in rows if r["k"] >= cut) // max_eval))
    seen = 0
    m = Model(canon, params)
    cnt: Dict[str, List[int]] = {}                      # 联赛 → 主/平/客 场数（赛前累计）
    allc = [0, 0, 0]
    over_cnt = [0, 0]
    out: List[Dict[str, Any]] = []
    for r in rows:
        try:
            hs, as_ = int(r["hs"]), int(r["as"])
        except (KeyError, TypeError, ValueError):
            continue
        if r["k"] >= cut:
            seen += 1
        if r["k"] >= cut and (seen - 1) % stride == 0:
            p = m.predict(r["h"], r["a"], r["k"], r.get("lg", ""), lean=True)
            if p:
                c = cnt.get(r.get("lg", ""), [0, 0, 0])
                tot = sum(c) if sum(c) >= LG_MIN else None
                prior = [x / tot for x in c] if tot else ([x / sum(allc) for x in allc] if sum(allc) >= LG_MIN else [0.45, 0.27, 0.28])
                prior = [max(0.02, x) for x in prior]
                sp = sum(prior)
                out.append({"k": r["k"], "p": (p["ph"], p["pd"], p["pa"]), "y": _outcome(hs, as_), "prior": [x / sp for x in prior],
                            "o25": p["o25"], "ov": 1 if hs + as_ >= 3 else 0,
                            "ovp": over_cnt[1] / over_cnt[0] if over_cnt[0] >= LG_MIN else 0.5})
        m.add_game(r)
        c = cnt.setdefault(r.get("lg", "") or "", [0, 0, 0]); y2 = _outcome(hs, as_)
        c[y2] += 1; allc[y2] += 1
        over_cnt[0] += 1; over_cnt[1] += (1 if hs + as_ >= 3 else 0)
    return out


def _score(samples: List[Dict[str, Any]], calib: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """一批样本的成绩：预测方向对的比例、对数损失、Brier（模型 vs 基准）、把握分段、大 2.5 球。calib 不为空就先校准再算。"""
    n = len(samples)
    hit = 0
    ll = ll0 = br = br0 = o_br = o_br0 = 0.0
    bins: Dict[str, List[int]] = {"40-50%": [0, 0], "50-60%": [0, 0], "60-70%": [0, 0], "70%+": [0, 0]}
    for s in samples:
        probs = calibrate(s["p"], calib) if calib else s["p"]
        y, prior = s["y"], s["prior"]
        ll += -math.log(max(1e-9, probs[y])); ll0 += -math.log(max(1e-9, prior[y]))
        br += sum((probs[i] - (1 if i == y else 0)) ** 2 for i in range(3))
        br0 += sum((prior[i] - (1 if i == y else 0)) ** 2 for i in range(3))
        arg = max(range(3), key=lambda i: probs[i])
        hit += (arg == y)
        mx = probs[arg]
        if mx >= 0.4:
            key = "40-50%" if mx < 0.5 else "50-60%" if mx < 0.6 else "60-70%" if mx < 0.7 else "70%+"
            bins[key][0] += 1; bins[key][1] += (arg == y)
        o_br += (s["o25"] - s["ov"]) ** 2; o_br0 += (s["ovp"] - s["ov"]) ** 2
    return {"acc": hit / n, "logloss": ll / n, "base_logloss": ll0 / n, "brier": br / n, "base_brier": br0 / n,
            "bins": {k: (v[0], (v[1] / v[0]) if v[0] else None) for k, v in bins.items()}, "o_brier": o_br / n, "o_base_brier": o_br0 / n}


def _gate(sc: Dict[str, Any]) -> Tuple[bool, str]:
    better = sc["logloss"] <= sc["base_logloss"] - BT_MARGIN
    hi = [v for k, v in sc["bins"].items() if k in ("60-70%", "70%+") and v[0] >= 20]
    calib_ok = all(v[1] >= 0.5 for v in hi)
    if not better:
        return False, "模型的预测没有比“只看联赛主客胜平比例”更准，只显示、不参与判断"
    if not calib_ok:
        return False, "模型说把握≥60%的比赛实际赢的不到一半（过于自信），只显示、不参与判断"
    return True, ""


def backtest(rows: List[Dict[str, Any]], canon: Any = None, days: int = BT_DAYS, min_n: int = BT_MIN_N,
             params: Optional[Tuple[float, ...]] = None, calibrate_on: bool = True) -> Dict[str, Any]:
    """滚动回测（见 _collect）。基准 = 只看该联赛（赛前累计）主胜/平/客胜比例。返回统计字典，ok=True 表示模型比基准好、样本也够。
    calibrate_on：回测样本够的话，顺便拟合「概率校准」（按日期训练60%、验证20%、测试20%，验证通过才用）；过关与否按校准后的概率判断。"""
    rows = sorted((r for r in rows if not _is_friendly(r.get("lg", ""))), key=lambda r: r["k"])
    res: Dict[str, Any] = {"n": 0, "ok": False, "days": days, "reason": "", "calib": None}
    if len(rows) < 100:
        res["reason"] = "赛果库里比分还太少，没法回测"
        return res
    samples = _collect(rows, canon, days, params, BT_MAX_N)
    n = len(samples)
    res.update(n=n)
    if n < min_n:
        res["reason"] = f"最近{days}天能回测的比赛只有 {n} 场（要 ≥{min_n}），先不让模型参与判断"
        return res
    train_s, val_s, test_s = date_split(samples, lambda r: r["k"])
    if min(len(train_s), len(val_s), len(test_s)) < 30:
        res["reason"] = "按日期分开训练、验证和测试后样本不足，模型暂不参与判断"
        return res
    res.update(sample_total=n, n=len(test_s), split={"train": len(train_s), "validation": len(val_s), "test": len(test_s)},
               validation_scheme="chronological_date_60_20_20")
    raw = _score(test_s)
    cal_info, cal = (_split_cal(samples) if calibrate_on else ({"applied": False, "reason": "未做校准"}, None))
    sc = _score(test_s, cal) if cal else raw
    res.update(acc=sc["acc"], logloss=sc["logloss"], base_logloss=sc["base_logloss"], brier=sc["brier"], base_brier=sc["base_brier"],
               bins=sc["bins"], o_brier=sc["o_brier"], o_base_brier=sc["o_base_brier"])
    res["calib"], res["calib_info"] = cal, cal_info
    res["raw"] = {"logloss": raw["logloss"], "bins": raw["bins"], "acc": raw["acc"]}
    res["ok"], res["reason"] = _gate(sc)
    return res


def check_text(r: Dict[str, Any]) -> str:
    if not r.get("n") or "acc" not in r:
        return "模型回测：" + (r.get("reason") or "没数据")
    hi = r["bins"]
    sure = [f"{k}→实际{v[1]:.0%}（{v[0]}场）" for k, v in hi.items() if v[0] >= 10 and v[1] is not None]
    s = (f"模型独立测试（最近{r['days']}天，最终测试段 {r['n']} 场，每场只用赛前数据）：预测方向对 {r['acc']:.0%}；对数损失 {r['logloss']:.3f}（基准 {r['base_logloss']:.3f}，越小越好）"
         + (f"；把握分段：{'，'.join(sure)}" if sure else "") + "。"
         + ("过关，模型参与“数据对比分”（最多±%.1f）。" % ADJ_MAX if r["ok"] else (r.get("reason") or "不过关") + "。"))
    ci = r.get("calib_info") or {}
    if r.get("calib"):
        raw = r.get("raw") or {}
        s += (f" 概率校准已启用（收缩 {r['calib']['alpha']:.2f}、平局×{r['calib']['wd']:.2f}；验证段对数损失 {ci.get('val_raw', 0):.4f}→{ci.get('val_cal', 0):.4f}"
              + (f"，校准前总体 {raw['logloss']:.3f}" if raw.get("logloss") else "") + "）。")
    elif ci.get("reason"):
        s += " 概率校准：" + ci["reason"] + "。"
    t = r.get("tune") or {}
    if t.get("params"):
        pr = t["params"]
        vals = tuple(pr.get(k, d) for k, d in zip(PARAM_KEYS, PARAM_DEFAULT))
        s += (f" 参数：{params_text(vals)}" + ("（自动择优，比默认好）" if t.get("changed") else "（默认值，择优没找到明显更好的）")
              + f"，{t.get('date', '')} 选的。")
    return s


# ═══════════════════════ 参数自动择优 ═══════════════════════
def default_params() -> Tuple[float, ...]:
    return tuple(PARAM_DEFAULT)


def params_dict(pr: Tuple[float, ...]) -> Dict[str, float]:
    pr = pad_params(pr)
    out: Dict[str, float] = {}
    for k, v in zip(PARAM_KEYS, pr):
        out[k] = int(v) if k == "n" else round(float(v), 4)
    return out


def params_text(pr: Tuple[float, ...]) -> str:
    """参数的一句话说明（只列和默认不同的新部件）。"""
    d = params_dict(pr)
    s = f"近{d['n']}场、衰减{d['decay']:g}、收缩{d['shrink']:g}"
    if d["lw"] > 0:
        s += f"；长期实力占{d['lw']:.0%}"
    if d["vw"] > 0:
        s += f"；主客场分开占{d['vw']:.0%}"
    if d["rw"] > 0:
        s += f"；对手强弱等级占{d['rw']:.0%}（学习速度{d['eta']:g}、遗忘{d['kap']:g}）"
    if d["rho"]:
        s += f"；低比分修正{d['rho']:g}"
    return s


def n_new_parts(pr: Tuple[float, ...]) -> int:
    d = params_dict(pr)
    return sum(1 for k in NEW_KEYS if abs(d[k] - dict(zip(PARAM_KEYS, PARAM_DEFAULT))[k]) > 1e-12)


from reliability import date_split, beijing_now


def tune_params(rows: List[Dict[str, Any]], canon: Any = None, days: int = BT_DAYS, log: Any = None, budget_s: float = TUNE_BUDGET_S) -> Dict[str, Any]:
    """按日期分为训练60%、验证20%、测试20%；训练拟合校准，验证选参。
    固定最终候选后才检查测试段；未达到提升门槛就保留默认参数。
    同一天的样本不跨段，测试段不参与参数搜索或校准拟合。
    """
    import time
    t0 = time.monotonic()
    rows = sorted((r for r in rows if not _is_friendly(r.get("lg", ""))), key=lambda r: r["k"])
    out: Dict[str, Any] = {"date": beijing_now().strftime("%Y-%m-%d"), "changed": False, "tried": 0, "name_schema": 2, "validation_scheme": "chronological_date_60_20_20"}
    base = default_params()
    out["params"] = params_dict(base)
    if len(rows) < 100:
        out["reason"] = "赛果库里比分还太少，不做参数择优"
        return out
    cache: Dict[Tuple[float, ...], float] = {}
    smps: Dict[Tuple[float, ...], List[Dict[str, Any]]] = {}
    calibrations = {}

    def score(pr: Tuple[float, ...]) -> Optional[float]:
        if pr in cache:
            return cache[pr]
        if time.monotonic() - t0 > budget_s:
            return None
        smp = _collect(rows, canon, days, pr, TUNE_MAX_EVAL)
        if len(smp) < BT_MIN_N:
            return None
        train, val, test = date_split(smp, lambda r: r["k"])
        if min(len(train), len(val), len(test)) < 30:
            return None
        c = fit_calibration(train)
        v = _score(val, c)["logloss"]
        calibrations[pr] = c
        cache[pr] = v
        smps[pr] = smp
        out["tried"] += 1
        return v

    b0 = score(base)
    if b0 is None:
        out["reason"] = f"最近{days}天能评估的比赛太少，不做参数择优"
        return out
    best, bv = base, b0
    order = ("n", "decay", "shrink", "lw", "vw", "rw", "eta", "kap", "rho")
    for _round in range(3):
        moved = False
        for key in order:
            idx = PARAM_KEYS.index(key)
            if key in ("eta", "kap") and best[5] <= 0:            # 等级部件没打开时，调它的学习速度没有意义
                continue
            for cand in TUNE_GRID[key]:
                pr = list(best)
                pr[idx] = cand
                pr = tuple(int(x) if i == 0 else float(x) for i, x in enumerate(pr))
                if pr == best:
                    continue
                v = score(pr)
                # 新部件的候选值要多好一点才算数（防止多试了几十组、碰巧挑到一个）
                pen = TUNE_MIN_GAIN * 0.25 * max(0, n_new_parts(pr) - n_new_parts(best))
                if v is not None and v + pen < bv - 1e-9:
                    best, bv, moved = pr, v, True
        if not moved:
            break
    out["base_ll"], out["best_ll"] = round(b0, 4), round(bv, 4)
    need = TUNE_MIN_GAIN * (1 + 0.5 * n_new_parts(best))
    out["validation_scheme"] = "chronological_date_60_20_20"
    if b0 - bv >= need and best != base:
        bt, bv_rows, test_base = date_split(smps[base], lambda r: r["k"])
        nt, nv_rows, test_new = date_split(smps[best], lambda r: r["k"])
        same = [r["k"] for r in test_base] == [r["k"] for r in test_new]
        out["split"] = {"train": len(nt), "validation": len(nv_rows), "test": len(test_new)}
        gain = (_score(test_base, calibrations[base])["logloss"] -
                _score(test_new, calibrations[best])["logloss"]) if same else float("-inf")
        out["test_gain"] = round(gain, 4) if same else None
        if same and gain >= need:
            out["params"] = params_dict(best)
            out["changed"] = True
        else:
            out["reason"] = "独立测试段未达到提升门槛，保留默认参数"
    else:
        out["reason"] = f"验证段未发现足够提升（默认 {b0:.4f}，候选 {bv:.4f}），保留默认参数"
    if log:
        log(f"  参数择优：试了 {out['tried']} 组，" + (f"改用 {params_text(best)}（校准后对数损失 {b0:.4f}→{bv:.4f}）" if out["changed"] else out.get("reason", "")))
    return out


def params_of(chk: Optional[Dict[str, Any]]) -> Tuple[float, ...]:
    """model_check.json 里选好的参数（没有或不对就用默认；老版本只存了 n/decay/shrink，新部件按关闭补上）。"""
    try:
        t = (chk or {}).get("tune") or {}
        if t.get("changed") and t.get("validation_scheme") == "chronological_date_60_20_20":
            pr = t["params"]
            vals = [pr.get(k, d) for k, d in zip(PARAM_KEYS, PARAM_DEFAULT)]
            vals[0] = int(vals[0])
            return tuple(float(v) if i else int(v) for i, v in enumerate(vals))
    except (KeyError, TypeError, ValueError, AttributeError):
        pass
    return default_params()


def build_model(db: Any, chk: Optional[Dict[str, Any]]) -> "Model":
    """按回测检查的结果建模型：用选好的参数；校准通过的话带上校准（没过关的回测，校准也不用）。"""
    cal = (chk or {}).get("calib") if (chk or {}).get("ok") else None
    return Model.from_db(db, params_of(chk), cal or None)


def results_fingerprint(rows, canon=None):
    """比较实际比分、联赛、开球时间及队名映射，避免同场数的修正漏刷新。"""
    canon = canon or (lambda name: name)
    digest = hashlib.sha256()
    for row in sorted(rows, key=lambda r: r.get("k", "")):
        values = (row.get("k"), canon(row.get("h", "")), canon(row.get("a", "")),
                  row.get("hs"), row.get("as"), row.get("lg", ""))
        digest.update(json.dumps(values, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        digest.update(b"\n")
    return digest.hexdigest()


def run_check(folder: Path, db: Any = None, write: bool = True, log: Any = None, tune: bool = True) -> Dict[str, Any]:
    """读赛果库、（每周一次）参数择优、回测+校准、把结果存进 model_check.json（同一天同一份赛果库同一组参数不重复算）。不抛异常。"""
    folder = Path(folder)
    try:
        if db is None:
            import sina_data as SD
            db = SD.ResultsDB(folder)
        path = L.p(folder, CHECK_FILE)
        try:
            old = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(old, dict):
                old = {}
        except (OSError, ValueError):
            old = {}
        today = beijing_now().strftime("%Y-%m-%d")
        tune_info = old.get("tune") if isinstance(old.get("tune"), dict) else None
        if tune and db.rows:
            stale = (not tune_info) or tune_info.get("name_schema") != 2 or tune_info.get("validation_scheme") != "chronological_date_60_20_20" or not 0 <= _days_between(tune_info.get("date"), today) < TUNE_EVERY_DAYS
            if stale:
                if log:
                    log("  每周一次的模型参数择优（最多一分钟左右）…")
                tune_info = tune_params(db.rows, db.names.canon, log=log)
        params = params_of({"tune": tune_info})
        sig = f"independent-v3-content|{__version__}|{results_fingerprint(db.rows, db.names.canon)}|" + "|".join(str(x) for x in params)
        if old.get("sig") == sig and old.get("date") == today and (not tune or old.get("tune") == tune_info):
            if log:
                log("  模型回测：比分、队名映射和参数未变，复用今日校验结果。")
            return old
        res = backtest(db.rows, db.names.canon, params=params)
        res["sig"], res["date"] = sig, today
        if tune_info:
            res["tune"] = tune_info
        if write:
            try:
                atomic_write_text(path, json.dumps(res, ensure_ascii=False, indent=1))
            except OSError:
                if log:
                    log("  模型校验结果未能保存，已保留原文件；检查文件占用和目录权限，下次可能重新计算。")
        return res
    except Exception as exc:  # noqa: BLE001 —— 模型只是加分项，出任何问题都不影响出推单
        return {"n": 0, "ok": False, "reason": f"回测没跑成（{exc}）"}


def _days_between(a: Any, b: str) -> int:
    try:
        return (datetime.strptime(b, "%Y-%m-%d") - datetime.strptime(str(a), "%Y-%m-%d")).days
    except (ValueError, TypeError):
        return 999


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="数据模型回测：看模型在你的赛果库上准不准")
    ap.add_argument("--days", type=int, default=BT_DAYS)
    a = ap.parse_args(argv)
    here = L.app_root(__file__)
    import sina_data as SD
    db = SD.ResultsDB(here)
    if not db.rows:
        print("赛果库是空的（先点一次“一键更新”攒比分）")
        return 1
    r = backtest(db.rows, db.names.canon, days=a.days)
    print(f"赛果库 {len(db.rows)} 场。")
    print(check_text(r))
    if r.get("raw"):
        print("  校准前 把握分段：" + "，".join(f"{k}→实际{v[1]:.0%}（{v[0]}场）" for k, v in r["raw"]["bins"].items() if v[0] >= 10 and v[1] is not None))
    if r.get("bins"):
        for k, v in r["bins"].items():
            print(f"  模型最大把握 {k}：{v[0]} 场，实际猜对 {('%.0f%%' % (v[1] * 100)) if v[1] is not None else '-'}")
        print(f"  大2.5球 Brier：模型 {r['o_brier']:.3f}，基准 {r['o_base_brier']:.3f}")
    return 0


if __name__ == "__main__":
    if sys.platform == "win32":
        for s in (sys.stdout, sys.stderr):
            try:
                s.reconfigure(encoding="utf-8", errors="replace")
            except (AttributeError, OSError):
                pass
    raise SystemExit(main())
