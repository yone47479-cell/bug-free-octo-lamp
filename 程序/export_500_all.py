#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""500 网公开数据分表导出工具。

只依赖 Python 3.9+ 标准库。把 500 网公开页面中确实收到的内容导出为一个 Excel 工作簿；
失败、无数据、未覆盖的栏目一律如实写入「采集状态」，绝不伪造数据。

用法
  python export_500_all.py                                   # 默认：各彩种「今日未开赛」+「昨日已开奖」
  python export_500_all.py --date 2026-10-13                 # 以指定日期为「今日」
  python export_500_all.py --keep-older-draws                # 数字彩/传统足彩：昨天没开奖的也保留最近一期
  python export_500_all.py --save-html pages/                # 把抓到的网页另存一份，便于排查版式变化
  python export_500_all.py --mode full --days 7              # 完整模式：向前追溯 7 个销售日的全部数据
  python export_500_all.py --url https://liansai.500.com/... # 附加页面，可重复
  python export_500_all.py --workers 1 --strict --summary-json run.json

两种模式
  focus（默认）  竞彩足球、竞彩篮球、北京单场、传统足彩、数字彩，每类只取两样：
                 「今日未开赛」 开赛时间晚于运行时刻的场次，附「距开赛」倒计时；
                 「昨日已开奖」 昨日已有比分/赛果/开奖号码的记录。
                 竞彩、北单以 500 网的销售日为准（销售日含次日凌晨开赛的场次）；
                 取消、延期、尚未出结果的场次不会混入。
                 传统足彩「在售期」是目前在售、尚未开赛的期次；「已开奖」是最近一期开奖结果；
                 数字彩只有开奖页（待开奖的期次官方售彩页不允许程序读取），所以只有「已开奖」。
                 默认只保留昨日开奖的期次，被排除的期次会在采集状态里说明；加 --keep-older-draws 可保留最近一期。
  full           每个销售日的赛程、赛果、篮球，再加各彩种最新页（旧版行为）。

工作簿（工作表顺序固定，表头在第 1 行，可直接用 pandas 读取）
  focus  竞足-今日未开赛 / 竞足-昨日已开奖 / 竞篮-今日未开赛 / 竞篮-昨日已开奖 /
         北单-今日未开赛 / 北单-昨日已开奖 / 传统足彩-在售期 / 传统足彩-已开奖 / 数字彩-已开奖 /
         [联赛比赛扩展原表，仅在使用 --url 时] / 采集状态
  full   采集状态 / 竞彩足球赛程 / 竞彩足球赛果 / 竞彩篮球原表 / 传统足彩及数字彩原表 / 联赛比赛扩展原表

数据来源与可靠度
  竞彩足球赛果、传统足彩与数字彩开奖页的解析已用真实页面核对；
  竞彩篮球赛程、北京单场、传统足彩销售页的解析依据公开页面的可见文本编写，若 500 网改版，
  相应栏目会在「采集状态」里标为失败或「无数据」，不会写入猜测的内容。可用 --save-html 留存网页以便修正。
  不访问 500 网 robots.txt 禁止抓取的地址（如带 expect= 的往期页）；22 选 5 已停售，不收录。

退出码
  0    至少一项采集成功（加 --strict 时还要求没有任何「失败」）
  1    仅 --strict：有栏目失败
  2    本次没有取到任何新数据，或命令行参数错误
  3    无法写出输出文件，或发生未预期的内部错误
  130  被 Ctrl-C 中断（已取得的进度已保存在输出文件中）

安全与可靠性
  * 只访问 500.com 及其子域名，重定向后的地址同样校验；
  * 只对网络抖动与 429/5xx 重试，指数退避并遵守 Retry-After；连续失败的主机会熔断，避免空等；
  * 单页 8 MB 上限（含 gzip 解压后），异常页面不会耗尽内存；
  * 写 Excel 时先写临时文件再原子替换；目标文件被占用时，最终结果改存带时间的新文件名；
  * 网页内容一律作为纯文本写入单元格，不会被 Excel 当作公式执行；
  * 重跑时若某天的赛程/赛果这次没取到，沿用同一输出文件里上次的记录，并在状态表标明。
"""

from __future__ import annotations

import argparse
import json
import math
import logging
import os
import posixpath
import random
import re
import sys
import threading
import time
import unicodedata
import zlib
from collections import Counter
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass, field, fields, replace
from datetime import date, datetime, timedelta, timezone
from enum import Enum, IntEnum
from functools import partial
from html.parser import HTMLParser
from http.client import HTTPException
from pathlib import Path
from typing import (Any, Callable, Dict, Iterable, Iterator, List, Mapping, Optional,
                    Sequence, Tuple)
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from xml.etree import ElementTree as ET
from xml.sax.saxutils import escape as xml_escape
from zipfile import BadZipFile, ZIP_DEFLATED, ZipFile

__version__ = "2.3.1"
logger = logging.getLogger("export500")


# ════════════════════════════════════════════════════════════════════════════
# 1. 配置与常量
# ════════════════════════════════════════════════════════════════════════════

BEIJING = timezone(timedelta(hours=8))          # 固定偏移，不依赖系统时区数据库
TIME_FORMAT = "%Y-%m-%d %H:%M:%S"
ALLOWED_DOMAIN = "500.com"

RESULT_BASE = "https://open.500.com/iframe/kaijiang/"
SCHEDULE_URL = "https://trade.500.com/jczq/index.php"
TRADE_BASE = "https://trade.500.com/"             # 销售页：竞彩篮球、北京单场、传统足彩
JCLQ_PAGE, BJDC_PAGE = "jclq/index.php", "bjdc/index.php"
# 传统足彩：销售页（还没开赛的在售期）与开奖页（已开奖的最新一期）。玩法名两边保持一致
ZUCAI_SALE_PAGES: Dict[str, str] = {
    "胜负彩/任选九": "sfc/index.php", "4场进球": "jqc/index.php", "6场半全场": "bqc/index.php"}
ZUCAI_RESULT_PAGES: Dict[str, Tuple[str, str]] = {   # 玩法 -> (开奖页文件名, 页面版式)
    "胜负彩/任选九": ("sfc.php", "sfc"), "4场进球": ("jq4.php", "jq4"), "6场半全场": ("zc6.php", "zc6")}
LATEST_PAGES: Dict[str, str] = {                # 栏目名 -> 开奖页文件名（保持原有顺序）
    "足彩胜负任九": "sfc.php", "四场进球": "jq4.php", "六场半全": "zc6.php",
    "北京单场": "zqdc.php", "大乐透": "dlt.php", "七星彩": "qxc.php",
    "排列3": "pls.php", "排列5": "plw.php", "22选5": "eexw.php",
    "双色球": "ssq.php", "福彩3D": "sd.php", "七乐彩": "qlc.php",
}
UNCOVERED_ITEMS = (
    "竞彩各玩法赛前完整SP", "欧赔亚盘大小球连续快照", "所有联赛历史赛季",
    "全部比赛阵容伤停天气", "赛中技术统计球员事件", "全部历史彩票期号", "自行计算的近期状态与疲劳指标",
)
UNCOVERED_NOTE = ("没有稳定且已核实的公开批量接口；不能伪装为已导出。"
                  "可用 --url 添加具体页面，但仅保存可见表格。")



@dataclass(frozen=True)
class Lottery:
    """一种数字彩：名称、开奖页文件名、开奖号码的断开方式。"""
    name: str
    page: str
    layout: str          # pairs：每 2 位一个号码；digits：每 1 位一个号码；qxc：前 6 位单个数字 + 末 2 位特别号


# 22 选 5 的开奖页还停在 2013 年，已停售，不收录
DRAW_LOTTERIES: Tuple[Lottery, ...] = (
    Lottery("大乐透", "dlt.php", "pairs"), Lottery("七星彩", "qxc.php", "qxc"),
    Lottery("排列3", "pls.php", "digits"), Lottery("排列5", "plw.php", "digits"),
    Lottery("双色球", "ssq.php", "pairs"), Lottery("福彩3D", "sd.php", "digits"),
    Lottery("七乐彩", "qlc.php", "pairs"),
)

DEFAULT_DAYS, MAX_DAYS = 2, 31
DEFAULT_TIMEOUT = 10.0                  # 单次请求超时（秒）
DEFAULT_RETRIES = 2                     # 仅对临时性错误的额外重试次数
DEFAULT_BACKOFF = 1.5                   # 退避基数（秒）：1.5、3、6 ……
MAX_BACKOFF = 20.0
DEFAULT_MIN_INTERVAL = 0.3              # 同一主机相邻请求的最小间隔（秒），对网站友好
DEFAULT_WORKERS, MAX_WORKERS = 4, 16
BREAKER_THRESHOLD = 5                   # 同一主机连续失败这么多次后熔断
CHECKPOINT_SECONDS = 5.0                # 进度文件的最小保存间隔

MAX_BODY_BYTES = 8 * 1024 * 1024
MAX_RAW_FIELDS = 24                     # 原始表每行最多保留的字段数
MOJIBAKE_LIMIT = 8                      # 页面中替换字符超过此数即判定编码损坏
MAX_CELL_CHARS = 32767                  # Excel 单元格字符上限
MAX_SHEET_ROWS = 1_048_576              # Excel 单表行数上限（含表头）
MAX_READ_BYTES = 200 * 1024 * 1024      # 读取旧工作簿的大小上限
NOTE_LIMIT = 240

USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "Chrome/120 Safari/537.36")
RETRYABLE_STATUS = frozenset({408, 425, 429, 500, 502, 503, 504})
UNRELIABLE_CHARSETS = frozenset({"iso-8859-1", "latin-1", "latin1", "ascii", "us-ascii"})
QUALITY_WORDS = ("开奖", "比赛", "赛果", "奖金", "竞彩足球", "主队", "双色球")

MATCH_CODE = re.compile(r"周[一二三四五六日天]\d{3}")
CODE_ANYWHERE = re.compile(r"周[一二三四五六日天]\d{3}")
SCORE = re.compile(r"(?<!\d)(\d{1,2})\s*[:：-]\s*(\d{1,2})(?!\d)")
BRACKETED = re.compile(r"[(（]([^)）]*)[)）]")           # 括号内是半场比分
META_CHARSET = re.compile(rb"<meta[^>]+charset\s*=\s*[\"']?\s*([\w-]+)", re.IGNORECASE)
VERSUS = re.compile(r"\s+[vV][sS]\s+")
KICKOFF = re.compile(r"(?:(\d{4}-\d{2}-\d{2})\s*)?(?:(\d{2}-\d{2})\s+)?(\d{2}:\d{2})")
PLAIN_NUMBER = re.compile(r"\d+(?:\.\d+)?")
UNSAFE_XML_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
INVALID_SHEET_CHARS = re.compile(r"[\[\]:*?/\\]")

SHEET_STATUS = "采集状态"
SHEET_SCHEDULE = "竞彩足球赛程"
SHEET_RESULTS = "竞彩足球赛果"
SHEET_BASKETBALL = "竞彩篮球原表"
SHEET_LOTTERY = "传统足彩及数字彩原表"
SHEET_EXTRA = "联赛比赛扩展原表"
# 默认（focus）模式的数据表：每个彩种一组，名字以彩种开头
SHEET_UPCOMING = "竞足-今日未开赛"
SHEET_SETTLED = "竞足-昨日已开奖"
SHEET_BB_UPCOMING = "竞篮-今日未开赛"
SHEET_BB_SETTLED = "竞篮-昨日已开奖"
SHEET_BJ_UPCOMING = "北单-今日未开赛"
SHEET_BJ_SETTLED = "北单-昨日已开奖"
SHEET_ZC_UPCOMING = "传统足彩-在售期"
SHEET_ZC_SETTLED = "传统足彩-已开奖"
SHEET_DRAWS = "数字彩-已开奖"

MODE_FOCUS, MODE_FULL = "focus", "full"


# ════════════════════════════════════════════════════════════════════════════
# 2. 异常、状态与数据模型
# ════════════════════════════════════════════════════════════════════════════

class ExportError(Exception):
    """本工具所有「可预期失败」的基类；消息可直接展示给使用者。"""


class UrlNotAllowedError(ExportError):
    """地址不在允许范围内（非 500.com、非 https、含账号密码等）。"""


class FetchError(ExportError):
    def __init__(self, message: str, *, retryable: bool = False,
                 retry_after: Optional[float] = None) -> None:
        super().__init__(message)
        self.retryable = retryable
        self.retry_after = retry_after


class CircuitOpenError(FetchError):
    """同一主机连续失败过多，本次运行不再继续请求它。"""


class PageMismatchError(ExportError):
    """页面内容与请求不符（例如页面显示的日期不是请求的日期）。"""


class PageStructureError(ExportError):
    """页面能打开，但内容结构和预期对不上（多半是网站改版）。"""


class EncodingProblemError(ExportError):
    """网页编码损坏，拒绝导出乱码。"""


class Status(str, Enum):
    SUCCESS = "成功"
    NO_DATA = "无表格数据"
    STALE = "沿用旧数据"
    FAILED = "失败"
    NOT_COVERED = "未覆盖"


@dataclass(frozen=True)
class FootballResult:
    """竞彩足球赛果：字段保持网页原文，比分已拆分为半场/全场。"""
    sales_day: str
    code: str
    league: str
    kickoff: str
    home: str
    away: str
    half_score: str
    full_score: str
    handicap: str
    handicap_spf: str
    handicap_spf_odds: str
    spf: str
    spf_odds: str
    total_goals: str
    total_goals_odds: str
    half_full: str
    half_full_odds: str
    source_url: str
    fetched_at: str


@dataclass(frozen=True)
class Fixture:
    """竞彩足球赛程。"""
    sales_day: str
    code: str
    league: str
    kickoff: str
    home: str
    away: str
    handicap: str
    stopped: str
    raw_pairing: str
    source_url: str
    fetched_at: str
    countdown: str = ""        # 仅「今日未开赛」使用：抓取时刻距开赛还有多久


@dataclass(frozen=True)
class BasketballFixture:
    """竞彩篮球赛程。注意：篮球页面客队在前、主队在后。"""
    sales_day: str
    code: str
    league: str
    kickoff: str
    away: str
    home: str
    spread: str                # 让分（正数：客队让主队；负数：主队让客队）
    total: str                 # 预设总分
    stopped: str
    raw_pairing: str
    source_url: str
    fetched_at: str
    countdown: str = ""


@dataclass(frozen=True)
class BasketballResult:
    """竞彩篮球赛果。终场比分的顺序是 客队:主队。"""
    sales_day: str
    code: str
    league: str
    kickoff: str
    away: str
    home: str
    final_score: str
    moneyline: str             # 胜负彩果：主胜 / 主负
    spread: str
    margin: str                # 胜分差彩果
    total: str
    total_result: str          # 大小分彩果：大 / 小
    source_url: str
    fetched_at: str


@dataclass(frozen=True)
class BjdcMatch:
    """北京单场（销售页里的一行；已结束的场次带比分）。"""
    sales_day: str             # 页面按「10:00--次日10:00」分组，这里是分组日期
    code: str                  # 场次序号（同一期内唯一）
    issue: str
    league: str
    kickoff: str
    home: str
    handicap: str
    away: str
    score: str
    sp_win: str
    sp_draw: str
    sp_lose: str
    source_url: str
    fetched_at: str
    countdown: str = ""


@dataclass(frozen=True)
class ZucaiFixture:
    """传统足彩在售期的一场比赛。"""
    game: str
    issue: str
    seq: str
    league: str
    kickoff: str
    home: str
    away: str
    deadline: str
    source_url: str
    fetched_at: str
    countdown: str = ""


@dataclass(frozen=True)
class ZucaiResult:
    """传统足彩已开奖的一场比赛（开奖页只给球队简称和彩果，没有比分）。"""
    game: str
    issue: str
    draw_date: str
    seq: str
    home: str
    away: str
    result: str
    raw_result: str
    source_url: str
    fetched_at: str
    relative_day: str = ""


@dataclass(frozen=True)
class DrawResult:
    """数字彩的一期开奖。"""
    lottery: str
    issue: str
    draw_date: str
    numbers: str
    raw_numbers: str
    order: str
    number_type: str
    sales_pool: str
    prizes: str
    source_url: str
    fetched_at: str
    relative_day: str = ""


@dataclass(frozen=True)
class RawRow:
    """原样保存的网页表格行。"""
    category: str
    table_index: int
    row_index: int
    header: str
    field_count: int
    fields: Tuple[str, ...]
    source_url: str
    fetched_at: str


@dataclass(frozen=True)
class StatusRecord:
    item: str
    status: Status
    count: int
    note: str
    source_url: str
    fetched_at: str


@dataclass(frozen=True)
class ParseOutcome:
    rows: Tuple[Any, ...] = ()
    note: str = ""


@dataclass(frozen=True)
class Page:
    """一次成功抓取的页面。url 是请求地址（写入「来源网址」），final_url 是重定向后的地址。"""
    url: str
    final_url: str
    html: str
    fetched_at: str


# ════════════════════════════════════════════════════════════════════════════
# 3. 工作表定义（列顺序与表头沿用原脚本，下游读取不受影响）
# ════════════════════════════════════════════════════════════════════════════

class Kind(Enum):
    TEXT = "text"          # 左对齐文本
    CENTER = "center"      # 居中文本
    ODDS = "odds"          # 奖金：能解析成数字就按数字存（0.00），否则按文本
    INT = "int"            # 整数
    STATUS = "status"      # 采集状态：按取值着色


@dataclass(frozen=True)
class Column:
    title: str
    attr: str = ""
    kind: Kind = Kind.TEXT
    getter: Optional[Callable[[Any], Any]] = None

    def value(self, record: Any) -> Any:
        return self.getter(record) if self.getter else getattr(record, self.attr)


@dataclass(frozen=True)
class SheetSpec:
    name: str
    columns: Tuple[Column, ...]
    record_type: Optional[type] = None     # 仅需要从旧工作簿还原记录的表才设置
    order: Optional[Callable[[Any], Any]] = None     # 汇总多个任务的结果时，整张表统一按它排序
    unique: Optional[Callable[[Any], Any]] = None    # 不同任务可能给出同一场比赛：按它去重，新数据优先于沿用的旧数据

    def record_from_mapping(self, mapping: Mapping[str, str]) -> Any:
        """用「表头 -> 文本」还原一条记录；这张表没有的字段留空。"""
        assert self.record_type is not None
        values = {f.name: "" for f in fields(self.record_type)}
        values.update({c.attr: str(mapping.get(c.title, "")) for c in self.columns if c.attr})
        return self.record_type(**values)


def _raw_field(index: int) -> Callable[[RawRow], str]:
    return lambda row: row.fields[index] if index < len(row.fields) else ""


_TAIL = (Column("来源网址", "source_url"), Column("抓取时间(北京时间)", "fetched_at"))

STATUS_SPEC = SheetSpec(SHEET_STATUS, (
    Column("栏目", "item"), Column("状态", "status", Kind.STATUS), Column("记录数", "count", Kind.INT),
    Column("说明", "note"), *_TAIL))

SCHEDULE_SPEC = SheetSpec(SHEET_SCHEDULE, (
    Column("销售日", "sales_day", Kind.CENTER), Column("赛事编号", "code", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("主队", "home"), Column("客队", "away"),
    Column("让球", "handicap", Kind.CENTER), Column("停售", "stopped", Kind.CENTER),
    Column("页面原始对阵", "raw_pairing"), *_TAIL), Fixture)

RESULT_SPEC = SheetSpec(SHEET_RESULTS, (
    Column("销售日", "sales_day", Kind.CENTER), Column("赛事编号", "code", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("主队", "home"), Column("客队", "away"),
    Column("半场比分", "half_score", Kind.CENTER), Column("全场比分", "full_score", Kind.CENTER),
    Column("让球", "handicap", Kind.CENTER),
    Column("让球胜平负", "handicap_spf", Kind.CENTER), Column("让球胜平负奖金", "handicap_spf_odds", Kind.ODDS),
    Column("胜平负", "spf", Kind.CENTER), Column("胜平负奖金", "spf_odds", Kind.ODDS),
    Column("总进球", "total_goals", Kind.CENTER), Column("总进球奖金", "total_goals_odds", Kind.ODDS),
    Column("半全场", "half_full", Kind.CENTER), Column("半全场奖金", "half_full_odds", Kind.ODDS),
    *_TAIL), FootballResult)

RAW_COLUMNS = (
    Column("分类", "category"), Column("页面表序号", "table_index", Kind.INT),
    Column("行序号", "row_index", Kind.INT), Column("网页表头", "header"),
    Column("原始字段数", "field_count", Kind.INT),
    *[Column(f"字段{i}", getter=_raw_field(i - 1)) for i in range(1, MAX_RAW_FIELDS + 1)],
    *_TAIL)

def _match_key(record: Any) -> Tuple[str, str]:
    return record.sales_day, record.code


UPCOMING_SPEC = SheetSpec(SHEET_UPCOMING, (
    Column("销售日", "sales_day", Kind.CENTER), Column("赛事编号", "code", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("距开赛(抓取时)", "countdown", Kind.CENTER),
    Column("主队", "home"), Column("客队", "away"),
    Column("让球", "handicap", Kind.CENTER), Column("停售", "stopped", Kind.CENTER),
    Column("页面原始对阵", "raw_pairing"), *_TAIL), Fixture, lambda record: match_order(record), _match_key)

SETTLED_SPEC = SheetSpec(SHEET_SETTLED, RESULT_SPEC.columns, FootballResult,
                         lambda record: match_order(record), _match_key)

BB_UPCOMING_SPEC = SheetSpec(SHEET_BB_UPCOMING, (
    Column("销售日", "sales_day", Kind.CENTER), Column("赛事编号", "code", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("距开赛(抓取时)", "countdown", Kind.CENTER),
    Column("客队", "away"), Column("主队", "home"),
    Column("让分", "spread", Kind.CENTER), Column("预设总分", "total", Kind.CENTER),
    Column("停售", "stopped", Kind.CENTER), Column("页面原始对阵", "raw_pairing"), *_TAIL),
    BasketballFixture, lambda record: match_order(record), _match_key)

BB_SETTLED_SPEC = SheetSpec(SHEET_BB_SETTLED, (
    Column("销售日", "sales_day", Kind.CENTER), Column("赛事编号", "code", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("客队", "away"), Column("主队", "home"),
    Column("终场比分(客:主)", "final_score", Kind.CENTER), Column("胜负", "moneyline", Kind.CENTER),
    Column("让分", "spread", Kind.CENTER), Column("胜分差", "margin", Kind.CENTER),
    Column("预设总分", "total", Kind.CENTER), Column("大小分", "total_result", Kind.CENTER), *_TAIL),
    BasketballResult, lambda record: match_order(record), _match_key)

BJ_UPCOMING_SPEC = SheetSpec(SHEET_BJ_UPCOMING, (
    Column("销售日", "sales_day", Kind.CENTER), Column("场次", "code", Kind.CENTER),
    Column("期号", "issue", Kind.CENTER), Column("联赛", "league"),
    Column("开赛时间(北京时间)", "kickoff"), Column("距开赛(抓取时)", "countdown", Kind.CENTER),
    Column("主队", "home"), Column("让球", "handicap", Kind.CENTER), Column("客队", "away"),
    Column("让球胜SP", "sp_win", Kind.ODDS), Column("让球平SP", "sp_draw", Kind.ODDS),
    Column("让球负SP", "sp_lose", Kind.ODDS), *_TAIL), order=lambda record: bjdc_order(record))

BJ_SETTLED_SPEC = SheetSpec(SHEET_BJ_SETTLED, (
    Column("销售日", "sales_day", Kind.CENTER), Column("场次", "code", Kind.CENTER),
    Column("期号", "issue", Kind.CENTER), Column("联赛", "league"),
    Column("开赛时间(北京时间)", "kickoff"), Column("主队", "home"),
    Column("让球", "handicap", Kind.CENTER), Column("客队", "away"),
    Column("比分", "score", Kind.CENTER), *_TAIL), order=lambda record: bjdc_order(record))

ZC_UPCOMING_SPEC = SheetSpec(SHEET_ZC_UPCOMING, (
    Column("玩法", "game"), Column("期号", "issue", Kind.CENTER), Column("序号", "seq", Kind.CENTER),
    Column("联赛", "league"), Column("开赛时间(北京时间)", "kickoff"),
    Column("距开赛(抓取时)", "countdown", Kind.CENTER), Column("主队", "home"), Column("客队", "away"),
    Column("售彩截止(北京时间)", "deadline"), *_TAIL), order=lambda record: zucai_order(record))

ZC_SETTLED_SPEC = SheetSpec(SHEET_ZC_SETTLED, (
    Column("玩法", "game"), Column("期号", "issue", Kind.CENTER), Column("开奖日期", "draw_date", Kind.CENTER),
    Column("相对今天", "relative_day", Kind.CENTER), Column("序号", "seq", Kind.CENTER),
    Column("主队(页面简称)", "home"), Column("客队(页面简称)", "away"),
    Column("彩果", "result", Kind.CENTER), Column("彩果(页面原值)", "raw_result", Kind.CENTER), *_TAIL),
    record_type=ZucaiResult, order=lambda record: zucai_result_order(record))

DRAW_SPEC = SheetSpec(SHEET_DRAWS, (
    Column("彩种", "lottery"), Column("期号", "issue", Kind.CENTER), Column("开奖日期", "draw_date", Kind.CENTER),
    Column("相对今天", "relative_day", Kind.CENTER), Column("开奖号码", "numbers"),
    Column("开奖号码(原样)", "raw_numbers"), Column("出球顺序", "order"), Column("号码类型", "number_type", Kind.CENTER),
    Column("销量与奖池", "sales_pool"), Column("各奖级中奖情况", "prizes"), *_TAIL),
    record_type=DrawResult, order=lambda record: draw_order(record))

# full 模式：工作表顺序固定（旧版本按位置读取过这些表，保持不变最安全）
ALL_SPECS: Tuple[SheetSpec, ...] = (
    STATUS_SPEC, SCHEDULE_SPEC, RESULT_SPEC,
    SheetSpec(SHEET_BASKETBALL, RAW_COLUMNS),
    SheetSpec(SHEET_LOTTERY, RAW_COLUMNS),
    SheetSpec(SHEET_EXTRA, RAW_COLUMNS),
)
EXTRA_SPEC = ALL_SPECS[-1]
# focus 模式（默认）：打开文件先看到数据表，采集状态放最后；只有用了 --url 才多一张扩展原表
FOCUS_DATA_SPECS: Tuple[SheetSpec, ...] = (
    UPCOMING_SPEC, SETTLED_SPEC, BB_UPCOMING_SPEC, BB_SETTLED_SPEC, BJ_UPCOMING_SPEC, BJ_SETTLED_SPEC,
    ZC_UPCOMING_SPEC, ZC_SETTLED_SPEC, DRAW_SPEC)
SPEC_BY_NAME: Dict[str, SheetSpec] = {spec.name: spec for spec in ALL_SPECS + FOCUS_DATA_SPECS}


def specs_for_mode(mode: str, has_extra_urls: bool) -> Tuple[SheetSpec, ...]:
    if mode == MODE_FULL:
        return ALL_SPECS
    return FOCUS_DATA_SPECS + ((EXTRA_SPEC,) if has_extra_urls else ()) + (STATUS_SPEC,)

# 赛果页每行 <td> 的位置 -> 字段（页面改版时只需改这里）
RESULT_CELLS = {
    "code": 0, "league": 1, "kickoff": 2, "home": 3, "handicap": 4, "away": 5, "score": 6,
    "handicap_spf": 8, "handicap_spf_odds": 9, "spf": 11, "spf_odds": 12,
    "total_goals": 14, "total_goals_odds": 15, "half_full": 17, "half_full_odds": 18,
}
MIN_RESULT_CELLS = 7


# ════════════════════════════════════════════════════════════════════════════
# 4. 通用小工具
# ════════════════════════════════════════════════════════════════════════════

Clock = Callable[[], datetime]


def beijing_now() -> datetime:
    return datetime.now(BEIJING)


def format_time(moment: datetime) -> str:
    return moment.astimezone(BEIJING).strftime(TIME_FORMAT)


def display_width(text: str) -> int:
    """显示宽度：全角字符占 2 格，用来估算 Excel 列宽。"""
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def normalize_handicap(raw: str) -> str:
    """页面里的正让球值是裸数字（1、2），统一显示为 +1、+2；0 与负数保持原样。"""
    raw = raw.strip()
    return f"+{raw}" if raw.isascii() and raw.isdigit() and int(raw) else raw


def parse_scores(text: str) -> Tuple[str, str]:
    """'(1:0) 2:1' -> ('1:0', '2:1')。

    括号里是半场比分，括号外是全场比分。只有半场、尚未踢完时全场返回空串，
    不会把半场比分误当全场（原脚本会）。没有括号但出现两个比分时，第一个视为半场。
    """
    half = ""
    bracket = BRACKETED.search(text)
    if bracket:
        found = SCORE.search(bracket.group(1))
        if found:
            half = f"{found.group(1)}:{found.group(2)}"
    rest = list(SCORE.finditer(BRACKETED.sub(" ", text)))
    full = f"{rest[-1].group(1)}:{rest[-1].group(2)}" if rest else ""
    if not bracket and len(rest) > 1:
        half = f"{rest[0].group(1)}:{rest[0].group(2)}"
    return half, full


def cell_at(cells: Sequence[str], index: int) -> str:
    return cells[index] if index < len(cells) else ""


def unique_by_code(records: Iterable[Any]) -> List[Any]:
    """按赛事编号去重，保留首次出现，顺序与页面一致。"""
    seen: Dict[str, Any] = {}
    for record in records:
        seen.setdefault(record.code, record)
    return list(seen.values())


def clip(text: str, limit: int = NOTE_LIMIT) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= limit else text[:limit - 1] + "…"


KICKOFF_FORMAT = "%Y-%m-%d %H:%M"
SHORT_KICKOFF = re.compile(r"(\d{2})-(\d{2})\s+(\d{2}:\d{2})")    # 赛果页写法：10-15 08:30（没有年份）


def parse_kickoff(text: str) -> Optional[datetime]:
    """'2026-10-15 08:30' -> 北京时间的带时区时间；无法解析返回 None。"""
    try:
        return datetime.strptime(text.strip(), KICKOFF_FORMAT).replace(tzinfo=BEIJING)
    except ValueError:
        return None


def normalize_kickoff(raw: str, sales_day: str) -> str:
    """把赛果页没有年份的开赛时间（'10-15 08:30'）补成赛程页的写法 'YYYY-MM-DD HH:MM'。

    年份取销售日所在年；12 月的销售日遇到 1 月开赛（开赛月份比销售日早 6 个月以上）则进位到下一年。
    格式不认识就原样返回，绝不凭空编造。
    """
    raw = raw.strip()
    match = SHORT_KICKOFF.fullmatch(raw)
    if not match:
        return raw
    try:
        day = datetime.strptime(sales_day, "%Y-%m-%d")
        month, dom = int(match.group(1)), int(match.group(2))
        year = day.year + (1 if month < day.month - 6 else 0)
        datetime(year, month, dom)                      # 校验日期真实存在（如 02-30 会报错）
    except ValueError:
        return raw
    return f"{year:04d}-{month:02d}-{dom:02d} {match.group(3)}"


def format_countdown(delta: timedelta) -> str:
    """距开赛的时长：'2天3小时' / '9小时31分' / '45分钟'。"""
    minutes = max(0, int(delta.total_seconds() // 60))
    days, rest = divmod(minutes, 1440)
    hours, mins = divmod(rest, 60)
    if days:
        return f"{days}天{hours}小时"
    return f"{hours}小时{mins}分" if hours else f"{mins}分钟"


def code_number(code: str) -> int:
    """'周三014' -> 14，用于同一销售日内按编号排序。"""
    digits = code[-3:]
    return int(digits) if digits.isdigit() else 0


def match_order(record: Any) -> Tuple[str, str, int]:
    """赛事排序：先按开赛时间，再按销售日、编号。"""
    return record.kickoff, record.sales_day, code_number(record.code)


# ════════════════════════════════════════════════════════════════════════════
# 5. HTTP 层：地址白名单、限速、重试退避、熔断、gzip 与编码识别
# ════════════════════════════════════════════════════════════════════════════

@dataclass(frozen=True)
class UrlPolicy:
    """允许访问的地址范围。默认只放行 500.com 及其子域名的 https 地址。"""
    domain: str = ALLOWED_DOMAIN
    schemes: Tuple[str, ...] = ("https",)
    upgrade_http: bool = True              # 把用户给的 http:// 自动升级为 https://

    def host_allowed(self, host: str) -> bool:
        host = host.lower().rstrip(".")
        return host == self.domain or host.endswith("." + self.domain)

    def validate(self, url: str, *, upgrade: bool = True) -> str:
        """返回规范化后的地址（去掉 #片段）；不合规则抛 UrlNotAllowedError。"""
        url = url.strip()
        if not url or re.search(r"[\x00-\x20\x7f]", url):
            raise UrlNotAllowedError("地址为空，或含有空格/控制字符")
        try:
            parts = urlsplit(url)
            host = parts.hostname or ""
            port = parts.port
        except ValueError as exc:
            raise UrlNotAllowedError(f"地址无法解析：{exc}") from exc
        scheme = parts.scheme.lower()
        netloc = parts.netloc
        if scheme == "http" and upgrade and self.upgrade_http and "https" in self.schemes:
            scheme = "https"
            netloc = host if port in (None, 80) else f"{host}:{port}"
        if scheme not in self.schemes:
            raise UrlNotAllowedError(f"只允许 {'/'.join(self.schemes)} 地址：{scheme or '（无协议）'}")
        if parts.username or parts.password:
            raise UrlNotAllowedError("地址中不允许包含账号或密码")
        if not self.host_allowed(host):
            raise UrlNotAllowedError(f"只允许 {self.domain} 域名：{host or '（空）'}")
        return urlunsplit((scheme, netloc, parts.path, parts.query, ""))


@dataclass(frozen=True)
class HttpConfig:
    timeout: float = DEFAULT_TIMEOUT
    retries: int = DEFAULT_RETRIES
    backoff: float = DEFAULT_BACKOFF
    max_backoff: float = MAX_BACKOFF
    min_interval: float = DEFAULT_MIN_INTERVAL
    max_bytes: int = MAX_BODY_BYTES
    breaker_threshold: int = BREAKER_THRESHOLD
    user_agent: str = USER_AGENT


class RateLimiter:
    """同一主机相邻请求至少相隔 min_interval 秒；线程安全，各线程先预约时间段再各自等待。"""

    def __init__(self, min_interval: float, monotonic: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        self._interval = max(0.0, min_interval)
        self._monotonic = monotonic
        self._sleep = sleep
        self._next: Dict[str, float] = {}
        self._lock = threading.Lock()

    def wait(self, key: str) -> None:
        if self._interval <= 0:
            return
        with self._lock:
            now = self._monotonic()
            slot = max(now, self._next.get(key, 0.0))
            self._next[key] = slot + self._interval
        if slot > now:
            self._sleep(slot - now)


class CircuitBreaker:
    """同一主机连续失败达到阈值后熔断，本次运行不再请求它；任一次成功即清零。threshold<=0 表示关闭。"""

    def __init__(self, threshold: int) -> None:
        self._threshold = threshold
        self._failures: Dict[str, int] = {}
        self._lock = threading.Lock()

    def check(self, host: str) -> None:
        if self._threshold <= 0:
            return
        with self._lock:
            count = self._failures.get(host, 0)
        if count >= self._threshold:
            raise CircuitOpenError(f"{host} 已连续 {count} 次请求失败，已熔断，本次运行不再尝试")

    def success(self, host: str) -> None:
        with self._lock:
            self._failures.pop(host, None)

    def failure(self, host: str) -> None:
        with self._lock:
            self._failures[host] = self._failures.get(host, 0) + 1


class _PolicyRedirectHandler(HTTPRedirectHandler):
    """重定向后的地址同样要通过白名单，防止被跳转到站外。"""

    def __init__(self, policy: UrlPolicy) -> None:
        super().__init__()
        self._policy = policy

    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        self._policy.validate(newurl, upgrade=False)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _normalize_charset(name: str) -> str:
    name = name.strip().lower()
    return "gb18030" if name in ("gb2312", "gbk", "gb_2312-80") else name


def _text_quality(text: str) -> int:
    """编码择优：中文关键词越多越好，替换字符和常见乱码越少越好。"""
    return (sum(text.count(word) for word in QUALITY_WORDS) * 20
            - text.count("\ufffd") * 10 - text.count("锟斤拷") * 10)


def decode_html(raw: bytes, declared: Optional[str] = None) -> str:
    """依次尝试 HTTP 头声明、<meta> 声明、UTF-8、GB18030，再按内容质量择优。

    500 网的子页有时错误声明字符集，所以不能只信声明；严格解码失败的编码直接淘汰，
    其余候选按质量打分，分数相同时靠前者优先（声明优先于猜测）。
    """
    meta = META_CHARSET.search(raw[:4096])
    names = [declared, meta.group(1).decode("ascii", "ignore") if meta else None, "utf-8", "gb18030"]
    candidates: List[str] = []
    tried = set()
    for name in names:
        if not name:
            continue
        name = _normalize_charset(name)
        if name in tried or name in UNRELIABLE_CHARSETS:
            continue
        tried.add(name)
        try:
            candidates.append(raw.decode(name))
        except (LookupError, UnicodeError):
            continue
    if not candidates:
        candidates = [raw.decode("gb18030", "replace"), raw.decode("utf-8", "replace")]
    return max(candidates, key=_text_quality).lstrip("﻿")


def gunzip_limited(data: bytes, limit: int) -> bytes:
    """解压 gzip，解压后超过 limit 字节即放弃（防压缩炸弹）。"""
    decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
    try:
        out = decompressor.decompress(data, limit + 1)
    except zlib.error as exc:
        raise FetchError(f"gzip 解压失败：{exc}", retryable=True) from exc
    if len(out) > limit:
        raise FetchError("单页解压后超过大小上限，已停止")
    if not decompressor.eof:
        raise FetchError("gzip 数据被截断", retryable=True)
    return out


def _retry_after(headers: Any) -> Optional[float]:
    value = headers.get("Retry-After") if headers is not None else None
    value = (value or "").strip()
    return float(value) if value.isdigit() else None


class HttpClient:
    """线程安全的 HTTP GET 客户端；所有请求都经过白名单、限速、重试与熔断。"""

    def __init__(self, config: HttpConfig = HttpConfig(), policy: UrlPolicy = UrlPolicy(), *,
                 sleep: Callable[[float], None] = time.sleep,
                 monotonic: Callable[[], float] = time.monotonic,
                 rng: Callable[[], float] = random.random) -> None:
        self.config = config
        self.policy = policy
        self._sleep = sleep
        self._rng = rng
        self._opener = build_opener(_PolicyRedirectHandler(policy))
        self._limiter = RateLimiter(config.min_interval, monotonic, sleep)
        self._breaker = CircuitBreaker(config.breaker_threshold)

    def get(self, url: str) -> Tuple[str, str]:
        """返回 (最终地址, 解码后的网页文本)。失败统一抛 FetchError / UrlNotAllowedError。"""
        safe_url = self.policy.validate(url)
        host = (urlsplit(safe_url).hostname or "").lower()
        self._breaker.check(host)
        attempts = self.config.retries + 1
        last: Optional[FetchError] = None
        for attempt in range(attempts):
            self._limiter.wait(host)
            try:
                result = self._attempt(safe_url)
            except FetchError as exc:
                if not exc.retryable:
                    self._breaker.success(host)        # 服务器有响应，只是这次请求不被接受
                    raise
                last = exc
                if attempt + 1 < attempts:
                    delay = self._delay(attempt, exc.retry_after)
                    logger.warning("%s 请求异常（%s），%.1f 秒后重试（%d/%d）",
                                   host, exc, delay, attempt + 1, attempts - 1)
                    self._sleep(delay)
                continue
            self._breaker.success(host)
            return result
        self._breaker.failure(host)
        raise FetchError(f"{last}（已尝试 {attempts} 次）", retryable=True)

    def _delay(self, attempt: int, retry_after: Optional[float]) -> float:
        cfg = self.config
        delay = min(cfg.max_backoff, cfg.backoff * 2 ** attempt)
        if retry_after is not None:
            delay = min(cfg.max_backoff, max(delay, retry_after))
        return delay * (0.8 + 0.4 * self._rng())       # ±20% 抖动，避免多线程同时重试

    def _attempt(self, url: str) -> Tuple[str, str]:
        request = Request(url, headers={
            "User-Agent": self.config.user_agent,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "zh-CN,zh;q=0.9",
            "Accept-Encoding": "gzip",
        })
        limit = self.config.max_bytes
        try:
            with self._opener.open(request, timeout=self.config.timeout) as response:
                raw = response.read(limit + 1)
                content_encoding = (response.headers.get("Content-Encoding") or "").lower()
                declared = response.headers.get_content_charset()
                final_url = response.geturl()
        except HTTPError as exc:
            retry_after = _retry_after(exc.headers)
            reason = f"HTTP {exc.code} {exc.reason}"
            exc.close()
            raise FetchError(reason, retryable=exc.code in RETRYABLE_STATUS,
                             retry_after=retry_after) from exc
        except (URLError, OSError, HTTPException, EOFError) as exc:
            # 连接失败、超时、连接被重置、TLS 握手失败等
            raise FetchError(f"{type(exc).__name__}: {exc}", retryable=True) from exc
        except ValueError as exc:
            raise FetchError(f"请求参数无效：{exc}") from exc
        if len(raw) > limit:
            raise FetchError(f"单页超过 {limit // 1024 // 1024} MB，已停止")
        if "gzip" in content_encoding:
            raw = gunzip_limited(raw, limit)
        return final_url, decode_html(raw, declared)


# ════════════════════════════════════════════════════════════════════════════
# 6. HTML 解析
# ════════════════════════════════════════════════════════════════════════════

@dataclass
class HtmlRow:
    attrs: Dict[str, str]
    texts: List[str] = field(default_factory=list)
    th_flags: List[bool] = field(default_factory=list)
    pos: Tuple[int, int] = (0, 0)          # <tr> 在网页源码里的 (行号, 列号)，用来判断它排在哪个日期标题之后

    @property
    def is_header(self) -> bool:
        return bool(self.th_flags) and all(self.th_flags)


@dataclass
class _TableState:
    rows: List[HtmlRow] = field(default_factory=list)
    row: Optional[HtmlRow] = None
    cell: Optional[List[str]] = None
    cell_is_th: bool = False


class DocumentParser(HTMLParser):
    """把网页里所有 <table> 解析为「行列表」，每行保留 <tr> 的属性和各单元格文字。

    * tables[0] 是兜底容器：收纳写在 <table> 之外的 <tr>（500 网个别页面如此）；
    * 能容忍缺少 </td>、</tr>、</table> 的松散写法：遇到新的 td/tr 就为上一个收尾；
    * 嵌套表格各自独立成表，同时它的文字也并入外层单元格（与肉眼看到的一致）；
    * <script>/<style> 里的文字不会混进单元格。
    """

    _SKIPPED = frozenset({"script", "style"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        base = _TableState()
        self.tables: List[List[HtmlRow]] = [base.rows]
        self._stack: List[_TableState] = [base]
        self._skip_depth = 0

    # —— 标签事件 ——
    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in self._SKIPPED:
            self._skip_depth += 1
            return
        state = self._stack[-1]
        if tag == "table":
            inner = _TableState()
            self.tables.append(inner.rows)
            self._stack.append(inner)
        elif tag == "tr":
            self._close_row(state)
            state.row = HtmlRow({key: value or "" for key, value in attrs}, pos=self.getpos())
        elif tag in ("td", "th") and state.row is not None:
            self._close_cell(state)
            state.cell, state.cell_is_th = [], tag == "th"
        elif tag == "br":
            self._add_text(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIPPED:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        state = self._stack[-1]
        if tag in ("td", "th"):
            self._close_cell(state)
        elif tag == "tr":
            self._close_row(state)
        elif tag == "table" and len(self._stack) > 1:
            self._close_row(state)
            self._stack.pop()

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            self._add_text(data)

    def close(self) -> None:
        super().close()
        for state in self._stack:          # 文档结束时仍未闭合的行也要收尾
            self._close_row(state)

    # —— 内部 ——
    def _add_text(self, text: str) -> None:
        for state in self._stack:          # 内层文字同时并入所有仍打开的外层单元格
            if state.cell is not None:
                state.cell.append(text)

    @staticmethod
    def _close_cell(state: _TableState) -> None:
        if state.cell is not None and state.row is not None:
            state.row.texts.append(" ".join("".join(state.cell).split()))
            state.row.th_flags.append(state.cell_is_th)
        state.cell = None

    def _close_row(self, state: _TableState) -> None:
        self._close_cell(state)
        if state.row is not None:
            state.rows.append(state.row)
        state.row = None

    def iter_rows(self) -> Iterator[HtmlRow]:
        for rows in self.tables:
            yield from rows


def parse_document(html: str) -> DocumentParser:
    parser = DocumentParser()
    parser.feed(html)
    parser.close()
    return parser


class _TextCollector(HTMLParser):
    _BLOCKS = frozenset({"br", "p", "div", "tr", "td", "th", "li", "table", "h1", "h2", "h3", "h4", "span", "a"})

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: List[str] = []
        self._skip = 0

    def handle_starttag(self, tag: str, attrs: List[Tuple[str, Optional[str]]]) -> None:
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BLOCKS:
            self.parts.append(" ")

    def handle_endtag(self, tag: str) -> None:
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)

    def handle_data(self, data: str) -> None:
        if not self._skip:
            self.parts.append(data)


def page_text(html: str) -> str:
    """网页上所有看得见的文字（含表格之外的），空白折叠成单个空格。用来读「当前第N期」之类的页头文字。"""
    collector = _TextCollector()
    collector.feed(html)
    collector.close()
    return " ".join("".join(collector.parts).split())


def html_position(html: str, index: int) -> Tuple[int, int]:
    """把源码字符下标换成和 HtmlRow.pos 相同的 (行号, 列号)。"""
    return html.count("\n", 0, index) + 1, index - (html.rfind("\n", 0, index) + 1)


# ════════════════════════════════════════════════════════════════════════════
# 7. 三类页面的解析：赛果、赛程、原始表
# ════════════════════════════════════════════════════════════════════════════

def parse_football(page: Page, day: str) -> ParseOutcome:
    """竞彩足球赛果页。页面必须明确带有请求的日期，否则视为默认日期页，拒绝使用。"""
    if not re.search(r"""value\s*=\s*["']?""" + re.escape(day) + r"(?!\d)", page.html):
        raise PageMismatchError("页面没有请求日期，避免把默认日期误认为目标日期")
    results: List[FootballResult] = []
    for row in parse_document(page.html).iter_rows():
        cells = row.texts
        if len(cells) < MIN_RESULT_CELLS or not MATCH_CODE.fullmatch(cells[0]):
            continue
        values = {name: cell_at(cells, index) for name, index in RESULT_CELLS.items()}
        values["kickoff"] = normalize_kickoff(values["kickoff"], day)      # 补全年份，与赛程页一致
        half, full = parse_scores(values.pop("score"))
        results.append(FootballResult(
            sales_day=day, half_score=half, full_score=full,
            handicap=normalize_handicap(values.pop("handicap")),
            source_url=page.url, fetched_at=page.fetched_at, **values))
    return ParseOutcome(tuple(unique_by_code(results)))


def weekday_prefixes(day: str) -> Tuple[str, ...]:
    index = datetime.strptime(day, "%Y-%m-%d").weekday()
    return ("周日", "周天") if index == 6 else ("周" + "一二三四五六"[index],)


def _fixtures_from_attributes(rows: Iterable[HtmlRow], day: str, page: Page) -> List[Fixture]:
    """赛程的权威信息写在 <tr data-...> 里。

    data-matchdate 是自然开赛日，data-processdate 才是竞彩销售日；同一销售日常包含次日凌晨
    开赛的场次，所以必须按销售日过滤。没有销售日属性时退而按编号里的星期判断。
    """
    prefixes = weekday_prefixes(day)
    fixtures: List[Fixture] = []
    for row in rows:
        attrs = row.attrs
        code = attrs.get("data-matchnum", "")
        if not MATCH_CODE.fullmatch(code):
            continue
        process_day = attrs.get("data-processdate", "")
        if process_day and process_day != day:
            continue
        if not process_day and not code.startswith(prefixes):
            continue
        fixtures.append(Fixture(
            sales_day=day, code=code,
            league=attrs.get("data-simpleleague", ""),
            kickoff=" ".join(p for p in (attrs.get("data-matchdate", ""), attrs.get("data-matchtime", "")) if p),
            home=attrs.get("data-homename") or attrs.get("data-homefullname") or attrs.get("data-homesxname", ""),
            away=attrs.get("data-awayname") or attrs.get("data-awayfullname") or attrs.get("data-awaysxname", ""),
            handicap=normalize_handicap(attrs.get("data-rangqiu", "")),
            stopped={"1": "是", "0": "否"}.get(attrs.get("data-isend", ""), ""),
            raw_pairing=" vs ".join((attrs.get("data-homesxname", ""), attrs.get("data-awaysxname", ""))),
            source_url=page.url, fetched_at=page.fetched_at))
    return fixtures


def _fixtures_from_cells(rows: Iterable[HtmlRow], day: str, page: Page) -> List[Fixture]:
    """有些页面的对阵只是可见单元格，没有 data-* 属性；此时尽力解析并保留原始文字。"""
    prefixes = weekday_prefixes(day)
    fixtures: List[Fixture] = []
    for row in rows:
        values = row.texts
        if not values:
            continue
        match = CODE_ANYWHERE.search(values[0])
        if not match or not match.group().startswith(prefixes):
            continue
        text = " | ".join(values)
        timestamp = ""
        found = KICKOFF.search(text)
        if found:
            if found.group(1):
                date_part = found.group(1)
            elif found.group(2):
                date_part = f"{day[:4]}-{found.group(2)}"
            else:
                date_part = day
            timestamp = f"{date_part} {found.group(3)}"
        pairing = next((v for v in values if VERSUS.search(v)), "")
        teams = VERSUS.split(pairing, maxsplit=1) if pairing else []
        fixtures.append(Fixture(
            sales_day=day, code=match.group(), league=cell_at(values, 1), kickoff=timestamp,
            home=teams[0] if len(teams) == 2 else "", away=teams[1] if len(teams) == 2 else "",
            handicap="", stopped="", raw_pairing=text,
            source_url=page.url, fetched_at=page.fetched_at))
    return fixtures


def parse_schedule(page: Page, day: str) -> ParseOutcome:
    document = parse_document(page.html)
    fixtures = _fixtures_from_attributes(document.iter_rows(), day, page)
    note = ""
    if not fixtures:
        fixtures = _fixtures_from_cells(document.iter_rows(), day, page)
        if fixtures:
            note = "页面没有赛事属性，改按可见单元格解析（让球、停售可能为空）"
    return ParseOutcome(tuple(unique_by_code(fixtures)), note)


def parse_raw(page: Page, label: str) -> ParseOutcome:
    """原样保存网页所有表格行；不把导航之类的通用表格误判为结构化赛果。"""
    out: List[RawRow] = []
    truncated = 0
    for table_index, table in enumerate(parse_document(page.html).tables, 1):
        header = ""
        for row_index, row in enumerate(table, 1):
            texts = row.texts
            if not any(texts):
                continue
            if row.is_header:
                header = " | ".join(texts)
                continue
            truncated += len(texts) > MAX_RAW_FIELDS
            out.append(RawRow(
                category=label, table_index=table_index, row_index=row_index, header=header,
                field_count=len(texts), fields=tuple(texts[:MAX_RAW_FIELDS]),
                source_url=page.url, fetched_at=page.fetched_at))
    note = (f"{truncated} 行字段超过 {MAX_RAW_FIELDS} 个，超出部分未保存（「原始字段数」列为真实数量）"
            if truncated else "")
    return ParseOutcome(tuple(out), note)


# ── 其他彩种：竞彩篮球、北京单场、传统足彩、数字彩 ─────────────────────────────

BROKEN_CHARS = re.compile("[�-]")        # 乱码占位符与私有区字符
CJK_GAP = re.compile(r"(?<=[一-鿿])\s+(?=[一-鿿])")
RANK_MARK = re.compile(r"^\s*\[\d+\]\s*|\s*\[\d+\]\s*$")   # 球队前后的联赛排名，如 [35]波兹南
LOOSE_VERSUS = re.compile(r"\s*[vV][sS]\s*")
HHMM = re.compile(r"\d{2}:\d{2}")
HANDICAP_CELL = re.compile(r"[+-]?\d{1,2}")
SP_VALUE = re.compile(r"\d+\.\d{2}")
SP_TRIPLE = re.compile(r"(?:\d+\.\d{2}){3}")
BJDC_GROUP_HEADER = re.compile(r"(\d{4}-\d{2}-\d{2})(?:\s|&nbsp;|<[^>]*>)*星期[一二三四五六日天]")
BJDC_SALES_DAY_START = "10:00"                             # 北单销售日：当天 10:00 到次日 10:00
DRAW_CAPTION = re.compile(r"第\s*(\d{4,8})\s*期\s*开奖日期[:：]\s*(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日")
TRADE_KICKOFF = re.compile(r"(\d{2}-\d{2})\s+(\d{2}:\d{2})")
GAME_RESULT = {"3": "胜", "1": "平", "0": "负"}
MAX_PRIZE_CHARS = 1500


def strip_rank(text: str) -> str:
    previous = None
    while previous != text:
        previous, text = text, RANK_MARK.sub("", text)
    return text.strip()


def clean_team_name(text: str) -> Tuple[str, bool]:
    """去掉联赛排名、页面自身的乱码字符和汉字之间的填充空格；第二个返回值表示原文含乱码。"""
    dirty = bool(BROKEN_CHARS.search(text))
    return CJK_GAP.sub("", BROKEN_CHARS.sub("", strip_rank(text))).strip(), dirty


def _split_pairing(text: str) -> List[str]:
    """'A VS B' 拆成两队；兼容 VS 两侧没有空白的写法。"""
    parts = VERSUS.split(text, maxsplit=1)
    if len(parts) != 2:
        parts = LOOSE_VERSUS.split(text, maxsplit=1)
    return parts if len(parts) == 2 else []


def _first_attr(attrs: Mapping[str, str], *names: str) -> str:
    return next((attrs[name] for name in names if attrs.get(name)), "")


def _short_kickoff(text: str, reference_day: str) -> str:
    """单元格里的 'MM-DD HH:MM'（或带年份的写法）-> 'YYYY-MM-DD HH:MM'；认不出来返回空串。"""
    found = KICKOFF.search(text)
    if not found or not (found.group(1) or found.group(2)):
        return ""
    if found.group(1):
        return f"{found.group(1)} {found.group(3)}"
    return normalize_kickoff(f"{found.group(2)} {found.group(3)}", reference_day)


# —— 竞彩篮球 ——

def _basketball_from_attributes(rows: Iterable[HtmlRow], day: str, page: Page) -> List[BasketballFixture]:
    """与竞彩足球同一套 <tr data-...> 写法；篮球特有的属性名没有核实过，取不到就留空。"""
    prefixes = weekday_prefixes(day)
    out: List[BasketballFixture] = []
    for row in rows:
        attrs = row.attrs
        code = attrs.get("data-matchnum", "")
        if not MATCH_CODE.fullmatch(code):
            continue
        process_day = attrs.get("data-processdate", "")
        if process_day and process_day != day:
            continue
        if not process_day and not code.startswith(prefixes):
            continue
        out.append(BasketballFixture(
            sales_day=day, code=code, league=attrs.get("data-simpleleague", ""),
            kickoff=" ".join(p for p in (attrs.get("data-matchdate", ""), attrs.get("data-matchtime", "")) if p),
            away=attrs.get("data-awaysxname", ""), home=attrs.get("data-homesxname", ""),
            spread=_first_attr(attrs, "data-rangfen", "data-rf", "data-rangqiu"),
            total=_first_attr(attrs, "data-zf", "data-yszf", "data-total"),
            stopped={"1": "是", "0": "否"}.get(attrs.get("data-isend", ""), ""),
            raw_pairing="", source_url=page.url, fetched_at=page.fetched_at))
    return out


def _basketball_from_cells(rows: Iterable[HtmlRow], day: str, page: Page) -> List[BasketballFixture]:
    """可见单元格版式：编号 | 联赛 | 开赛时间 | 客队 VS 主队 | 让分胜负 | 大小分 | …"""
    prefixes = weekday_prefixes(day)
    out: List[BasketballFixture] = []
    for row in rows:
        values = row.texts
        match = CODE_ANYWHERE.search(values[0]) if values else None
        if not match or not match.group().startswith(prefixes):
            continue
        pair_index = next((i for i, v in enumerate(values) if i >= 2 and _split_pairing(v)), None)
        teams = _split_pairing(values[pair_index]) if pair_index is not None else []
        spread = total = ""
        if pair_index is not None:
            spread_cell = cell_at(values, pair_index + 1)
            total_cell = cell_at(values, pair_index + 2)
            found = re.search(r"(?<![\d.])[+-]\d+(?:\.\d)?(?![\d.])", spread_cell)
            spread = found.group() if found else ""
            found = re.search(r"(?<![\d.+-])\d{2,3}\.\d(?![\d.])", total_cell)
            total = found.group() if found else ""
        out.append(BasketballFixture(
            sales_day=day, code=match.group(), league=cell_at(values, 1),
            kickoff=_short_kickoff(" ".join(values[1:4]), day),
            away=strip_rank(teams[0]) if teams else "", home=strip_rank(teams[1]) if teams else "",
            spread=spread, total=total, stopped="", raw_pairing=" | ".join(values),
            source_url=page.url, fetched_at=page.fetched_at))
    return out


def parse_basketball_schedule(page: Page, day: str) -> ParseOutcome:
    document = parse_document(page.html)
    fixtures = _basketball_from_attributes(document.iter_rows(), day, page)
    note = ""
    if not fixtures:
        fixtures = _basketball_from_cells(document.iter_rows(), day, page)
        if fixtures:
            note = "页面没有赛事属性，改按可见单元格解析（让分、总分、停售可能为空）"
    return ParseOutcome(tuple(unique_by_code(fixtures)), note)


BB_RESULT_MIN_CELLS = 12
BB_SCORE = re.compile(r"\d{1,3}:\d{1,3}")
BB_LINE = re.compile(r"[+-]?\d+(?:\.\d)?")


def parse_basketball_results(page: Page, day: str) -> ParseOutcome:
    """竞彩篮球赛果。

    开奖页的日期参数不是销售日：夜里 0 点以后才开赛的场次出现在「次日」的页面里。所以调用方会把
    销售日当天和次日两个页面都抓一遍，这里只保留编号星期与销售日一致、开赛日在销售日当天或次日的行。
    """
    prefixes = weekday_prefixes(day)
    first = datetime.strptime(day, "%Y-%m-%d").date()
    allowed = {first.isoformat(), (first + timedelta(days=1)).isoformat()}
    results: List[BasketballResult] = []
    for row in parse_document(page.html).iter_rows():
        cells = row.texts
        if len(cells) < BB_RESULT_MIN_CELLS or not MATCH_CODE.fullmatch(cells[0]) or not cells[0].startswith(prefixes):
            continue
        kickoff = normalize_kickoff(cells[2], day)
        parsed = parse_kickoff(kickoff)
        if parsed is None or parsed.date().isoformat() not in allowed:
            continue
        score = cell_at(cells, 6).replace("：", ":").replace(" ", "")
        moneyline = cell_at(cells, 7)
        spread = cell_at(cells, 11)
        total = cell_at(cells, 17)
        total_result = cell_at(cells, 18)
        margin = cell_at(cells, 14)
        results.append(BasketballResult(
            sales_day=day, code=cells[0], league=cells[1], kickoff=kickoff,
            away=cell_at(cells, 3), home=cell_at(cells, 5),
            final_score=score if BB_SCORE.fullmatch(score) else "",
            moneyline=moneyline if re.fullmatch(r"主[胜负]", moneyline) else "",
            spread=spread if BB_LINE.fullmatch(spread) else "",
            margin=margin if margin not in ("--", "-") else "",
            total=total if PLAIN_NUMBER.fullmatch(total) else "",
            total_result=total_result if total_result in ("大", "小") else "",
            source_url=page.url, fetched_at=page.fetched_at))
    return ParseOutcome(tuple(unique_by_code(results)))


# —— 北京单场 ——

def is_score_cell(text: str) -> bool:
    """'3:0' 这样的比分单元格；排除 '15:35' 这样的钟点。"""
    if not re.fullmatch(r"(\d{1,2})\s*[:：]\s*(\d{1,2})", text):
        return False
    clock = re.fullmatch(r"(\d{2}):(\d{2})", text)          # 恰好 'HH:MM' 才当作钟点（带空格的 '3 : 0' 是比分）
    looks_like_clock = bool(clock) and int(clock.group(1)) <= 23 and int(clock.group(2)) <= 59
    return not looks_like_clock


def parse_bjdc(page: Page) -> ParseOutcome:
    """北京单场销售页：当前期全部场次，按「日期 星期X (10:00--次日10:00)」分组，开赛时间只有钟点。

    每行：场次 | 联赛 | 开赛钟点 | 主队 | 让球 | 客队 | … 让球胜平负 SP … 已结束的场次另有比分。
    球队前后可能带联赛排名 [12]，单元格边界在不同场次间有差别，所以按内容而不是固定列号取值。
    """
    html = page.html
    visible = page_text(html)
    found = re.search(r"(\d{5,7})\s*当前期", visible) or re.search(r"当前期\s*[:：]?\s*(\d{5,7})", visible)
    issue = found.group(1) if found else ""
    headers = [(html_position(html, m.start()), m.group(1)) for m in BJDC_GROUP_HEADER.finditer(html)]
    matches: List[BjdcMatch] = []
    skipped = no_group = 0
    for row in parse_document(html).iter_rows():
        cells = row.texts
        base = next((i for i in range(min(4, len(cells)))
                     if cells[i].isdigit() and i + 2 < len(cells) and HHMM.fullmatch(cells[i + 2])), None)
        if base is None:
            continue
        tokens = [t for t in (strip_rank(c) for c in cells[base + 3:]) if t]
        at = next((i for i, t in enumerate(tokens) if i >= 1 and HANDICAP_CELL.fullmatch(t)), None)
        if at is None or at + 1 >= len(tokens):
            skipped += 1
            continue
        home, handicap, away = tokens[at - 1], tokens[at], tokens[at + 1]
        tail = tokens[at + 2:]
        score = next((re.sub(r"\s", "", t).replace("：", ":") for t in tail if is_score_cell(t)), "")
        sp = next((SP_VALUE.findall(t) for t in tail if SP_TRIPLE.fullmatch(t)), [])
        if not sp:
            for i in range(len(tail) - 2):
                if all(re.fullmatch(r"\d+\.\d{2}", t) for t in tail[i:i + 3]):
                    sp = tail[i:i + 3]
                    break
        group = ""
        for position, day in headers:
            if position <= row.pos:
                group = day
            else:
                break
        kickoff = ""
        if group:
            clock = cells[base + 2]
            day_of_kickoff = datetime.strptime(group, "%Y-%m-%d").date()
            if clock < BJDC_SALES_DAY_START:                 # 凌晨开赛的场次属于前一个销售日
                day_of_kickoff += timedelta(days=1)
            kickoff = f"{day_of_kickoff.isoformat()} {clock}"
        else:
            no_group += 1
        matches.append(BjdcMatch(
            sales_day=group, code=cells[base], issue=issue, league=cells[base + 1], kickoff=kickoff,
            home=home, handicap=normalize_handicap(handicap), away=away, score=score,
            sp_win=sp[0] if len(sp) == 3 else "", sp_draw=sp[1] if len(sp) == 3 else "",
            sp_lose=sp[2] if len(sp) == 3 else "", source_url=page.url, fetched_at=page.fetched_at))
    notes = []
    if skipped:
        notes.append(f"{skipped} 行认不出主客队，已跳过")
    if no_group:
        notes.append(f"{no_group} 行找不到所属日期，无法判断开赛时间")
    if matches and not issue:
        notes.append("没有找到期号")
    return ParseOutcome(tuple(unique_by_code(matches)), "；".join(notes))


# —— 传统足彩 ——

def parse_zucai_sale(page: Page, game: str) -> ParseOutcome:
    """传统足彩销售页：页头写着「当前第N期」和售彩截止时间，下面是该期的全部场次。"""
    visible = page_text(page.html)
    reference_day = page.fetched_at[:10]
    found = re.search(r"当前第\s*(\d{4,8})\s*期", visible)
    issue = found.group(1) if found else ""
    found = re.search(r"售彩截止时间[:：]?\s*(\d{2}-\d{2}\s+\d{2}:\d{2})", visible)
    deadline = _short_kickoff(found.group(1), reference_day) if found else ""
    fixtures: List[ZucaiFixture] = []
    for row in parse_document(page.html).iter_rows():
        cells = row.texts
        base = next((i for i in range(min(3, len(cells)))
                     if cells[i].isdigit() and 1 <= int(cells[i]) <= 14 and i + 3 < len(cells)
                     and TRADE_KICKOFF.search(cells[i + 2])), None)
        if base is None:
            continue
        kickoff = _short_kickoff(cells[base + 2], reference_day)
        teams = next((_split_pairing(c) for c in cells[base + 3:] if _split_pairing(c)), [])
        if not teams:                                         # 进球彩/半全场：主队、客队各占一格
            plain = [c for c in cells[base + 3:base + 5] if c]
            teams = plain if len(plain) == 2 else []
        if not teams:
            continue
        fixtures.append(ZucaiFixture(
            game=game, issue=issue, seq=cells[base], league=cells[base + 1], kickoff=kickoff,
            home=clean_team_name(teams[0])[0], away=clean_team_name(teams[1])[0], deadline=deadline,
            source_url=page.url, fetched_at=page.fetched_at))
    seen: Dict[str, ZucaiFixture] = {}
    for fixture in fixtures:
        seen.setdefault(fixture.seq, fixture)
    notes = []
    if seen and not issue:
        notes.append("没有找到期号")
    if seen and not deadline:
        notes.append("没有找到售彩截止时间")
    return ParseOutcome(tuple(seen.values()), "；".join(notes))


def _find_caption(document: DocumentParser) -> Optional[Tuple[List[HtmlRow], int, "re.Match[str]"]]:
    for table in document.tables:
        for index, row in enumerate(table):
            found = DRAW_CAPTION.search(" ".join(row.texts))
            if found:
                return table, index, found
    return None


def _draw_date(found: "re.Match[str]") -> str:
    year, month, day = int(found.group(2)), int(found.group(3)), int(found.group(4))
    try:
        return date(year, month, day).isoformat()
    except ValueError:
        return ""


def parse_zucai_result(page: Page, game: str, layout: str) -> ParseOutcome:
    """传统足彩开奖页（只显示最近一期）。

    页面是横向排版：一行球队简称，下面一行彩果（3 胜 1 平 0 负）。
    sfc：每场一个球队名 + 一个彩果；jq4：每场两个球队 + 各自进球数；zc6：每场一个球队 + 半场、全场两个彩果。
    球队名是页面按字节截断的，常带乱码，已去掉乱码字符。
    """
    located = _find_caption(parse_document(page.html))
    if not located:
        return ParseOutcome()
    table, index, caption = located
    issue, draw_date = caption.group(1), _draw_date(caption)
    names: Optional[List[str]] = None
    results: Optional[List[str]] = None
    for row in table[index + 1:]:
        texts = row.texts
        if len(texts) <= 1:
            if results is not None:
                break
            continue
        if names is None:
            names = texts
        elif set(texts) <= {"半", "全"}:
            continue
        else:
            results = texts
            break
    per_match = 2 if layout == "zc6" else 1
    if not names or not results or len(results) != len(names) * per_match:
        raise PageStructureError(
            f"开奖页结构与预期不符：球队 {len(names or [])} 个，彩果 {len(results or [])} 个")
    cleaned = [clean_team_name(n) for n in names]
    broken = sum(1 for _, dirty in cleaned if dirty)
    rows: List[ZucaiResult] = []
    common = dict(game=game, issue=issue, draw_date=draw_date, source_url=page.url, fetched_at=page.fetched_at)
    if layout == "jq4":
        for k in range(len(names) // 2):
            goals = results[2 * k:2 * k + 2]
            rows.append(ZucaiResult(seq=str(k + 1), home=cleaned[2 * k][0], away=cleaned[2 * k + 1][0],
                                    result=":".join(goals), raw_result=",".join(goals), **common))
    elif layout == "zc6":
        for k in range(len(names)):
            half, full = results[2 * k:2 * k + 2]
            rows.append(ZucaiResult(seq=str(k + 1), home=cleaned[k][0], away="",
                                    result=GAME_RESULT.get(half, "?") + GAME_RESULT.get(full, "?"),
                                    raw_result=f"{half},{full}", **common))
    else:
        for k in range(len(names)):
            rows.append(ZucaiResult(seq=str(k + 1), home=cleaned[k][0], away="",
                                    result=GAME_RESULT.get(results[k], results[k]), raw_result=results[k], **common))
    note = f"第 {issue} 期，开奖日期 {draw_date}"
    if broken:
        note += f"；{broken} 个球队名在页面上本身就有乱码，已去掉乱码字符"
    return ParseOutcome(tuple(rows), note)


# —— 数字彩 ——

def format_draw_numbers(raw: str, layout: str) -> str:
    groups = raw.split()
    if not groups or not all(g.isdigit() for g in groups):
        return raw
    if layout == "pairs":
        if any(len(g) % 2 for g in groups):
            return raw
        return " + ".join(" ".join(g[i:i + 2] for i in range(0, len(g), 2)) for g in groups)
    if layout == "qxc":
        digits = "".join(groups)
        return f"{' '.join(digits[:-2])} + {digits[-2:]}" if len(digits) == 8 else raw
    return " + ".join(" ".join(g) for g in groups)


def parse_draw(page: Page, lottery: Lottery) -> ParseOutcome:
    """数字彩开奖页（只显示最近一期）：期号、开奖日期、开奖号码、销量奖池、各奖级中奖情况。"""
    document = parse_document(page.html)
    located = _find_caption(document)
    if not located:
        return ParseOutcome()
    table, _, caption = located
    raw = order = number_type = sales_pool = ""
    for row in document.iter_rows():
        text = " ".join(row.texts)
        if not raw:
            found = re.search(r"开奖号码[:：]\s*([\d ]+?)(?=\s*(?:出球顺序|号码类型|$))", text)
            if found:
                raw = " ".join(found.group(1).split())
                found = re.search(r"出球顺序[:：]\s*([\d,，|]+)", text)
                order = found.group(1) if found else ""
                found = re.search(r"号码类型[:：]\s*(\S+)", text)
                number_type = found.group(1) if found else ""
        if not sales_pool and "销量" in text and "本期" in text:
            sales_pool = clip(text, 120)
    if not raw:
        raise PageStructureError("开奖页里没有找到开奖号码")
    prizes: List[str] = []
    for container in document.tables:
        header = next((i for i, row in enumerate(container) if row.texts[:1] == ["奖项"]), None)
        if header is not None:
            prizes = [" ".join(row.texts) for row in container[header + 1:] if any(row.texts)]
            break
    detail = " | ".join(prizes)
    if len(detail) > MAX_PRIZE_CHARS:
        detail = detail[:MAX_PRIZE_CHARS - 1] + "…"
    record = DrawResult(
        lottery=lottery.name, issue=caption.group(1), draw_date=_draw_date(caption),
        numbers=format_draw_numbers(raw, lottery.layout), raw_numbers=raw, order=order,
        number_type=number_type, sales_pool=sales_pool, prizes=detail,
        source_url=page.url, fetched_at=page.fetched_at)
    return ParseOutcome((record,), f"第 {record.issue} 期，开奖日期 {record.draw_date}")



# ════════════════════════════════════════════════════════════════════════════
# 8. Excel 写入（纯标准库手写 OOXML，流式输出）
# ════════════════════════════════════════════════════════════════════════════

NS_MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
NS_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
NS_PKG_REL = "http://schemas.openxmlformats.org/package/2006/relationships"
NS_CORE = "http://schemas.openxmlformats.org/package/2006/metadata/core-properties"
XML_HEADER = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
MIN_COLUMN_WIDTH, MAX_COLUMN_WIDTH, WIDTH_SAMPLE_ROWS = 10, 52, 200


class Style(IntEnum):
    """cellXfs 的下标。新增样式时同步修改 _XF_TABLE。"""
    DEFAULT = 0
    HEADER = 1
    HEADER_CENTER = 2
    TEXT = 3
    TEXT_ALT = 4
    CENTER = 5
    CENTER_ALT = 6
    ODDS = 7
    ODDS_ALT = 8
    INT = 9
    INT_ALT = 10
    STATUS_OK = 11
    STATUS_WARN = 12
    STATUS_BAD = 13
    STATUS_NA = 14


# (fontId, fillId, borderId, numFmtId, 水平对齐, 缩进)；numFmtId 1 = "0"，2 = "0.00"
_XF_TABLE = (
    (0, 0, 0, 0, None, 0),        # DEFAULT
    (1, 2, 0, 0, "left", 1),      # HEADER
    (1, 2, 0, 0, "center", 0),    # HEADER_CENTER
    (0, 0, 1, 0, "left", 1),      # TEXT
    (0, 3, 1, 0, "left", 1),      # TEXT_ALT（斑马纹）
    (0, 0, 1, 0, "center", 0),    # CENTER
    (0, 3, 1, 0, "center", 0),    # CENTER_ALT
    (0, 0, 1, 2, "center", 0),    # ODDS
    (0, 3, 1, 2, "center", 0),    # ODDS_ALT
    (0, 0, 1, 1, "center", 0),    # INT
    (0, 3, 1, 1, "center", 0),    # INT_ALT
    (2, 4, 1, 0, "center", 0),    # STATUS_OK    绿
    (2, 5, 1, 0, "center", 0),    # STATUS_WARN  黄
    (2, 6, 1, 0, "center", 0),    # STATUS_BAD   红
    (2, 7, 1, 0, "center", 0),    # STATUS_NA    灰
)
_FONTS = ((11, False, "FF243845"), (11, True, "FFFFFFFF"), (11, True, "FF243845"))   # 字号、加粗、颜色
_FILLS = ("FF194451", "FFEAF4F2", "FFDDF3E8", "FFFFF1CC", "FFFBDDDD", "FFE9ECEF")   # fillId 从 2 开始
_BODY_STYLES = {
    Kind.TEXT: (Style.TEXT, Style.TEXT_ALT), Kind.CENTER: (Style.CENTER, Style.CENTER_ALT),
    Kind.ODDS: (Style.ODDS, Style.ODDS_ALT), Kind.INT: (Style.INT, Style.INT_ALT),
}
_STATUS_STYLES = {
    Status.SUCCESS.value: Style.STATUS_OK, Status.NO_DATA.value: Style.STATUS_WARN,
    Status.STALE.value: Style.STATUS_WARN, Status.FAILED.value: Style.STATUS_BAD,
    Status.NOT_COVERED.value: Style.STATUS_NA,
}


def column_letter(index: int) -> str:
    """1 -> A，26 -> Z，27 -> AA。"""
    letters = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def clean_text(value: Any) -> str:
    """转为可安全写入 XML 的文本：去掉 XML 不允许的控制字符，超长单元格截断。"""
    if isinstance(value, Enum):
        value = value.value
    text = UNSAFE_XML_CHARS.sub("", "" if value is None else str(value))
    return text if len(text) <= MAX_CELL_CHARS else text[:MAX_CELL_CHARS - 1] + "…"


def text_cell(ref: str, text: str, style: Style) -> str:
    """内容一律按内联字符串保存，不会被 Excel 当作公式执行。"""
    if not text:
        return f'<c r="{ref}" s="{int(style)}"/>'
    return (f'<c r="{ref}" s="{int(style)}" t="inlineStr"><is>'
            f'<t xml:space="preserve">{xml_escape(text)}</t></is></c>')


def body_cell(ref: str, column: Column, value: Any, alt: bool) -> str:
    text = clean_text(value)
    kind = column.kind
    if kind is Kind.STATUS:
        return text_cell(ref, text, _STATUS_STYLES.get(text, Style.CENTER))
    if kind is Kind.ODDS and PLAIN_NUMBER.fullmatch(text):
        return f'<c r="{ref}" s="{int(_BODY_STYLES[kind][alt])}"><v>{text}</v></c>'
    if kind is Kind.INT and text.isascii() and text.isdigit():
        return f'<c r="{ref}" s="{int(_BODY_STYLES[kind][alt])}"><v>{text}</v></c>'
    shown = Kind.CENTER if kind in (Kind.ODDS, Kind.INT) else kind     # 非数字的奖金（如 "-"）按居中文本
    return text_cell(ref, text, _BODY_STYLES[shown][alt])


def column_widths(spec: SheetSpec, rows: Sequence[Any]) -> List[int]:
    sample = rows[:WIDTH_SAMPLE_ROWS]
    widths = []
    for column in spec.columns:
        longest = max([display_width(column.title)] +
                      [display_width(clean_text(column.value(row))) for row in sample])
        widths.append(min(MAX_COLUMN_WIDTH, max(MIN_COLUMN_WIDTH, longest + 4)))
    return widths


def filter_range(spec: SheetSpec, row_count: int) -> str:
    return f"A1:{column_letter(len(spec.columns))}{max(1, row_count + 1)}"


def sheet_chunks(spec: SheetSpec, rows: Sequence[Any], *, selected: bool) -> Iterator[str]:
    """分块生成一张工作表的 XML，避免把整张表拼成一个巨大的字符串。"""
    letters = [column_letter(i) for i in range(1, len(spec.columns) + 1)]
    cols = "".join(f'<col min="{i}" max="{i}" width="{w}" customWidth="1"/>'
                   for i, w in enumerate(column_widths(spec, rows), 1))
    tab = ' tabSelected="1"' if selected else ""
    yield (XML_HEADER + f'<worksheet xmlns="{NS_MAIN}"><sheetPr><pageSetUpPr fitToPage="1"/></sheetPr>'
           f'<dimension ref="A1:{letters[-1]}{max(1, len(rows) + 1)}"/>'
           f'<sheetViews><sheetView{tab} workbookViewId="0">'
           '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
           '<selection pane="bottomLeft" activeCell="A2" sqref="A2"/></sheetView></sheetViews>'
           f'<sheetFormatPr defaultRowHeight="20"/><cols>{cols}</cols><sheetData>')
    header = "".join(
        text_cell(f"{letter}1", clean_text(column.title),
                  Style.HEADER if column.kind is Kind.TEXT else Style.HEADER_CENTER)
        for letter, column in zip(letters, spec.columns))
    yield f'<row r="1" ht="28" customHeight="1">{header}</row>'
    batch: List[str] = []
    for number, record in enumerate(rows, 2):
        alt = number % 2 == 1
        cells = "".join(body_cell(f"{letter}{number}", column, column.value(record), alt)
                        for letter, column in zip(letters, spec.columns))
        batch.append(f'<row r="{number}">{cells}</row>')
        if len(batch) >= 500:
            yield "".join(batch)
            batch.clear()
    if batch:
        yield "".join(batch)
    yield (f'</sheetData><autoFilter ref="{filter_range(spec, len(rows))}"/>'
           '<pageMargins left="0.4" right="0.4" top="0.5" bottom="0.5" header="0.3" footer="0.3"/>'
           '<pageSetup paperSize="9" orientation="landscape" fitToWidth="1" fitToHeight="0"/></worksheet>')


def styles_xml() -> str:
    fonts = "".join(
        f'<font>{"<b/>" if bold else ""}<sz val="{size}"/><color rgb="{color}"/><name val="Microsoft YaHei"/></font>'
        for size, bold, color in _FONTS)
    fills = ('<fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>' +
             "".join(f'<fill><patternFill patternType="solid"><fgColor rgb="{rgb}"/></patternFill></fill>'
                     for rgb in _FILLS))
    borders = ('<border><left/><right/><top/><bottom/><diagonal/></border>'
               '<border><left/><right/><top/><bottom style="thin"><color rgb="FFD3E3DE"/></bottom><diagonal/></border>')
    xfs = []
    for font, fill, border, num_fmt, align, indent in _XF_TABLE:
        indent_attr = f' indent="{indent}"' if indent else ""
        alignment = f'<alignment horizontal="{align}" vertical="center"{indent_attr}/>' if align else ""
        xfs.append(f'<xf numFmtId="{num_fmt}" fontId="{font}" fillId="{fill}" borderId="{border}" xfId="0" '
                   f'applyFont="1" applyFill="1" applyBorder="1" applyNumberFormat="1" '
                   f'applyAlignment="{1 if align else 0}">{alignment}</xf>')
    return (XML_HEADER + f'<styleSheet xmlns="{NS_MAIN}">'
            f'<fonts count="{len(_FONTS)}">{fonts}</fonts>'
            f'<fills count="{len(_FILLS) + 2}">{fills}</fills><borders count="2">{borders}</borders>'
            '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
            f'<cellXfs count="{len(xfs)}">{"".join(xfs)}</cellXfs>'
            '<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles></styleSheet>')


def validate_sheet_names(names: Sequence[str]) -> None:
    for name in names:
        if not name or len(name) > 31 or INVALID_SHEET_CHARS.search(name) or name.startswith("'") or name.endswith("'"):
            raise ExportError(f"工作表名称不合法（1～31 个字符，不能含 []:*?/\\）：{name!r}")
    if len({n.lower() for n in names}) != len(names):
        raise ExportError("工作表名称重复（Excel 不区分大小写）")


def write_workbook(path: Path, sheets: Sequence[Tuple[SheetSpec, Sequence[Any]]], *,
                   created: datetime, creator: str = "export_500_all") -> None:
    validate_sheet_names([spec.name for spec, _ in sheets])
    count = len(sheets)
    ct = "application/vnd.openxmlformats-officedocument.spreadsheetml"
    content_types = (
        XML_HEADER + '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
        '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
        '<Default Extension="xml" ContentType="application/xml"/>'
        f'<Override PartName="/xl/workbook.xml" ContentType="{ct}.sheet.main+xml"/>'
        f'<Override PartName="/xl/styles.xml" ContentType="{ct}.styles+xml"/>'
        '<Override PartName="/docProps/core.xml" ContentType="application/vnd.openxmlformats-package.core-properties+xml"/>' +
        "".join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="{ct}.worksheet+xml"/>'
                for i in range(1, count + 1)) + "</Types>")
    root_rels = (
        XML_HEADER + f'<Relationships xmlns="{NS_PKG_REL}">'
        f'<Relationship Id="rId1" Type="{NS_REL}/officeDocument" Target="xl/workbook.xml"/>'
        f'<Relationship Id="rId2" Type="{NS_PKG_REL}/metadata/core-properties" Target="docProps/core.xml"/>'
        '</Relationships>')
    book_rels = (
        XML_HEADER + f'<Relationships xmlns="{NS_PKG_REL}">' +
        "".join(f'<Relationship Id="rId{i}" Type="{NS_REL}/worksheet" Target="worksheets/sheet{i}.xml"/>'
                for i in range(1, count + 1)) +
        f'<Relationship Id="rId{count + 1}" Type="{NS_REL}/styles" Target="styles.xml"/></Relationships>')
    sheet_tags, defined = [], []
    for index, (spec, rows) in enumerate(sheets):
        quoted = "'" + xml_escape(spec.name.replace("'", "''")) + "'"
        absolute = re.sub(r"([A-Z]+)(\d+)", r"$\1$\2", filter_range(spec, min(len(rows), MAX_SHEET_ROWS - 1)))
        sheet_tags.append(f'<sheet name="{xml_escape(spec.name)}" sheetId="{index + 1}" r:id="rId{index + 1}"/>')
        defined.append(f'<definedName name="_xlnm._FilterDatabase" localSheetId="{index}" hidden="1">{quoted}!{absolute}</definedName>')
        defined.append(f'<definedName name="_xlnm.Print_Titles" localSheetId="{index}">{quoted}!$1:$1</definedName>')
    workbook = (XML_HEADER + f'<workbook xmlns="{NS_MAIN}" xmlns:r="{NS_REL}">'
                '<bookViews><workbookView activeTab="0"/></bookViews>'
                f'<sheets>{"".join(sheet_tags)}</sheets><definedNames>{"".join(defined)}</definedNames></workbook>')
    stamp = created.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    core = (XML_HEADER + f'<cp:coreProperties xmlns:cp="{NS_CORE}" xmlns:dc="http://purl.org/dc/elements/1.1/" '
            'xmlns:dcterms="http://purl.org/dc/terms/" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">'
            f'<dc:title>500 网公开数据导出</dc:title><dc:creator>{xml_escape(creator)}</dc:creator>'
            f'<dcterms:created xsi:type="dcterms:W3CDTF">{stamp}</dcterms:created></cp:coreProperties>')
    with ZipFile(path, "w", ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", root_rels)
        archive.writestr("docProps/core.xml", core)
        archive.writestr("xl/workbook.xml", workbook)
        archive.writestr("xl/_rels/workbook.xml.rels", book_rels)
        archive.writestr("xl/styles.xml", styles_xml())
        for index, (spec, rows) in enumerate(sheets, 1):
            if len(rows) > MAX_SHEET_ROWS - 1:
                logger.warning("「%s」共 %d 行，超过 Excel 单表上限，只保存前 %d 行",
                               spec.name, len(rows), MAX_SHEET_ROWS - 1)
                rows = rows[:MAX_SHEET_ROWS - 1]
            with archive.open(f"xl/worksheets/sheet{index}.xml", "w") as stream:
                for chunk in sheet_chunks(spec, rows, selected=index == 1):
                    stream.write(chunk.encode("utf-8"))


def save_workbook(path: Path, sheets: Sequence[Tuple[SheetSpec, Sequence[Any]]], *,
                  created: datetime, allow_fallback: bool, clock: Clock = beijing_now) -> Path:
    """先写临时文件再原子替换，写到一半出错不会留下损坏的 xlsx。

    目标文件正被 Excel 占用（Windows 上无法替换）时：allow_fallback=True 改存为带时间的新文件名，
    否则抛 ExportError（中途保存进度时用，避免每次都生成新文件）。返回实际保存的路径。
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        write_workbook(temp, sheets, created=created)
        try:
            os.replace(temp, path)
            return path
        except PermissionError as exc:
            if not allow_fallback:
                raise ExportError(f"{path.name} 正被其他程序占用（可能已在 Excel 中打开）") from exc
            fallback = path.with_name(f"{path.stem}_{clock():%H%M%S}{path.suffix}")
            logger.warning("%s 正被其他程序占用（可能已在 Excel 中打开），改存为 %s", path.name, fallback.name)
            try:
                os.replace(temp, fallback)
            except PermissionError as exc2:
                raise ExportError(f"无法写入 {path.name}，备用文件 {fallback.name} 也被占用") from exc2
            return fallback
    finally:
        temp.unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# 9. Excel 读取：按「表名 + 表头」还原上次的赛程/赛果，用于本次取不到时沿用
# ════════════════════════════════════════════════════════════════════════════
# 只读取我们自己上次导出（或被 Excel 另存后）的文件；用标准库 ElementTree，不执行任何内容。

_M = "{%s}" % NS_MAIN
_R = "{%s}" % NS_REL
_PR = "{%s}" % NS_PKG_REL


def _rich_text(node: ET.Element) -> str:
    """<si> 或 <is> 节点里的文字，忽略拼音注释（rPh）。"""
    parts = []
    for child in node:
        if child.tag == _M + "t":
            parts.append(child.text or "")
        elif child.tag == _M + "r":
            run = child.find(_M + "t")
            parts.append((run.text or "") if run is not None else "")
    return "".join(parts)


def _shared_strings(archive: ZipFile) -> List[str]:
    try:
        stream = archive.open("xl/sharedStrings.xml")
    except KeyError:
        return []
    strings: List[str] = []
    with stream:
        for _, element in ET.iterparse(stream):
            if element.tag == _M + "si":
                strings.append(_rich_text(element))
                element.clear()
    return strings


def _sheet_member(archive: ZipFile, sheet_name: str) -> str:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rid = next((s.get(_R + "id") for s in workbook.iter(_M + "sheet") if s.get("name") == sheet_name), None)
    if rid is None:
        raise KeyError(sheet_name)
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    for rel in rels.iter(_PR + "Relationship"):
        if rel.get("Id") == rid:
            target = rel.get("Target") or ""
            return target[1:] if target.startswith("/") else posixpath.normpath("xl/" + target)
    raise KeyError(rid)


def _column_index(ref: str) -> int:
    letters = re.match(r"[A-Z]+", ref)
    if not letters:
        raise ValueError(f"单元格引用无效：{ref!r}")
    index = 0
    for char in letters.group():
        index = index * 26 + ord(char) - 64
    return index


def _cell_value(cell: ET.Element, shared: Sequence[str]) -> str:
    kind = cell.get("t", "n")
    if kind == "inlineStr":
        node = cell.find(_M + "is")
        return _rich_text(node) if node is not None else ""
    node = cell.find(_M + "v")
    text = node.text if node is not None and node.text is not None else ""
    if kind == "s":
        try:
            return shared[int(text)]
        except (ValueError, IndexError):
            return ""
    return text


def read_sheet(path: Path, sheet_name: str) -> List[Dict[str, str]]:
    """读取一张表，返回 [{表头: 文本}]。文件不存在、损坏或没有该表时返回空列表（损坏会记警告）。"""
    if not path.exists():
        return []
    try:
        if path.stat().st_size > MAX_READ_BYTES:
            raise ExportError("旧文件过大")
        with ZipFile(path) as archive:
            member = _sheet_member(archive, sheet_name)
            if archive.getinfo(member).file_size > MAX_READ_BYTES:
                raise ExportError("旧工作表过大")
            shared = _shared_strings(archive)
            rows: List[Dict[int, str]] = []
            with archive.open(member) as stream:
                for _, element in ET.iterparse(stream):
                    if element.tag != _M + "row":
                        continue
                    values: Dict[int, str] = {}
                    for position, cell in enumerate(element.findall(_M + "c"), 1):
                        ref = cell.get("r")
                        values[_column_index(ref) if ref else position] = _cell_value(cell, shared)
                    rows.append(values)
                    element.clear()
    except KeyError:
        return []                                  # 旧文件里没有这张表，属正常情况
    except (OSError, BadZipFile, ET.ParseError, ValueError, ExportError) as exc:
        logger.warning("无法读取旧文件 %s 的「%s」，本次不沿用旧数据：%s", path.name, sheet_name, exc)
        return []
    if len(rows) < 2:
        return []
    headers = rows[0]
    records = []
    for values in rows[1:]:
        record = {title: values.get(index, "") for index, title in headers.items() if title}
        if any(record.values()):
            records.append(record)
    return records


def load_previous(path: Path, specs: Sequence[SheetSpec]) -> Dict[str, List[Any]]:
    """还原上次导出里的赛程、赛果记录（按表名和表头匹配，不依赖工作表顺序）。

    只处理能还原成记录的表（设置了 record_type 的赛程/赛果类工作表）。
    """
    previous: Dict[str, List[Any]] = {}
    for spec in specs:
        if spec.record_type is None:
            continue
        rows = read_sheet(path, spec.name)
        if spec.record_type in (ZucaiResult, DrawResult):
            records = [spec.record_from_mapping(row) for row in rows
                       if row.get("期号") and re.fullmatch(r"\d{4}-\d{2}-\d{2}", row.get("开奖日期", ""))
                       and (row.get("彩种") if spec.record_type is DrawResult else row.get("玩法"))]
        else:
            records = [spec.record_from_mapping(row) for row in rows if row.get("赛事编号") and row.get("销售日")]
        if records:
            previous[spec.name] = records
    return previous


# ════════════════════════════════════════════════════════════════════════════
# 10. 任务清单与单任务执行
# ════════════════════════════════════════════════════════════════════════════

DEFAULT_POLICY = UrlPolicy()
Parser = Callable[[Page], ParseOutcome]
# 视图：(解析出的全部记录, 当前时刻) -> (要写入工作表的记录, 一句说明)；用于筛选、排序、补充派生列
View = Callable[[Sequence[Any], datetime], Tuple[List[Any], str]]


def is_settled(result: FootballResult) -> bool:
    """已开奖：有全场比分，并且胜平负赛果已公布（占位符 - 不算）。"""
    return bool(result.full_score) and result.spf not in ("", "-", "--")


def is_basketball_settled(result: BasketballResult) -> bool:
    return bool(result.final_score) and bool(result.moneyline)


def settled_view(rows: Sequence[Any], now: datetime,
                 done: Callable[[Any], bool] = is_settled) -> Tuple[List[Any], str]:
    """只保留已开奖的场次，按开赛时间从早到晚排列。"""
    kept = sorted((r for r in rows if done(r)), key=match_order)
    pending = len(rows) - len(kept)
    note = f"页面共 {len(rows)} 场，已开奖 {len(kept)} 场"
    if pending:
        note += f"；{pending} 场尚未开奖或已取消，未保留"
    return kept, note


def upcoming_view(rows: Sequence[Any], now: datetime,
                  order: Optional[Callable[[Any], Any]] = None) -> Tuple[List[Any], str]:
    """只保留开赛时间晚于当前时刻的场次（按开赛时间排列），并补上「距开赛」。

    开赛时间无法解析时无从比较，退而求其次：页面标明「未停售」的才保留，并在说明里提示。
    """
    kept: List[Any] = []
    unknown = 0
    for fixture in rows:
        kickoff = parse_kickoff(fixture.kickoff)
        if kickoff is not None:
            if kickoff > now:
                kept.append(replace(fixture, countdown=format_countdown(kickoff - now)))
        elif getattr(fixture, "stopped", "") == "否":
            kept.append(fixture)
            unknown += 1
    kept.sort(key=order or match_order)
    note = f"页面共 {len(rows)} 场，未开赛 {len(kept)} 场"
    if unknown:
        note += f"；其中 {unknown} 场无法解析开赛时间，按「未停售」处理"
    return kept, note


def bjdc_order(match: BjdcMatch) -> Tuple[str, int]:
    return match.kickoff, code_number(match.code)


def zucai_order(fixture: ZucaiFixture) -> Tuple[str, str, int]:
    return fixture.kickoff, fixture.game, int(fixture.seq) if fixture.seq.isdigit() else 0


def _game_index(game: str) -> int:
    names = list(ZUCAI_RESULT_PAGES)
    return names.index(game) if game in names else len(names)


def zucai_result_order(result: ZucaiResult) -> Tuple[int, int]:
    return _game_index(result.game), int(result.seq) if result.seq.isdigit() else 0


def draw_order(result: DrawResult) -> int:
    names = [lottery.name for lottery in DRAW_LOTTERIES]
    return names.index(result.lottery) if result.lottery in names else len(names)


def bjdc_upcoming_view(rows: Sequence[BjdcMatch], now: datetime,
                       days: Sequence[str]) -> Tuple[List[BjdcMatch], str]:
    """北单：只要今日、昨日两个销售日里，开赛时间晚于当前时刻的场次。"""
    kept: List[BjdcMatch] = []
    for match in rows:
        kickoff = parse_kickoff(match.kickoff)
        if match.sales_day in days and kickoff is not None and kickoff > now:
            kept.append(replace(match, countdown=format_countdown(kickoff - now)))
    kept.sort(key=bjdc_order)
    return kept, f"当前期页面共 {len(rows)} 场，今日未开赛 {len(kept)} 场"


def bjdc_settled_view(rows: Sequence[BjdcMatch], now: datetime, day: str) -> Tuple[List[BjdcMatch], str]:
    """北单：昨日销售日里已经有比分的场次。"""
    in_day = [m for m in rows if m.sales_day == day]
    kept = sorted((m for m in in_day if m.score), key=bjdc_order)
    note = f"当前期页面共 {len(rows)} 场；{day} 销售日 {len(in_day)} 场，已有比分 {len(kept)} 场"
    if not in_day:
        note += "；当前期页面里没有这一天（可能刚好换期）"
    return kept, note


def relative_day_label(draw_date: str, today: date) -> str:
    try:
        days = (today - date.fromisoformat(draw_date)).days
    except ValueError:
        return ""
    return {0: "今日", 1: "昨日", 2: "前日"}.get(days, f"{days}天前" if days > 2 else f"{-days}天后")


def drawn_view(rows: Sequence[Any], now: datetime, keep_older: bool = False) -> Tuple[List[Any], str]:
    """开奖页只显示最近一期。默认只保留昨日开奖的；keep_older 时每种彩票的最新一期都保留，并标明是哪天开的。"""
    today = now.date()
    yesterday = (today - timedelta(days=1)).isoformat()
    labelled = [replace(r, relative_day=relative_day_label(r.draw_date, today)) for r in rows]
    kept = labelled if keep_older else [r for r in labelled if r.draw_date == yesterday]
    kept_names = {getattr(r, "lottery", "") or getattr(r, "game", "") for r in kept}
    dropped: Dict[str, str] = {}
    for r in labelled:
        name = getattr(r, "lottery", "") or getattr(r, "game", "")
        if name not in kept_names:
            dropped.setdefault(name, f"{name}第{r.issue}期（{r.draw_date[5:]}）")
    note = f"保留 {len(kept)} 条"
    if dropped:
        note += "；最新一期不是昨日开奖，未保留：" + "、".join(dropped.values()) + "（加 --keep-older-draws 可保留）"
    return kept, note


@dataclass(frozen=True)
class Task:
    """一个采集栏目：抓哪个地址、用什么解析、结果去哪张表。"""
    key: str                      # 写入「采集状态」的栏目名
    sheet: str                    # 结果写入的工作表
    url: str
    parse: Parser
    day: str = ""                 # 非空表示按销售日取数，失败时可沿用上次同一天的记录
    detail: str = ""              # 成功时附在状态说明里的固定文字
    fallback_url: str = ""        # 主地址解析不出数据时再试的备用地址
    strict_encoding: bool = True  # 网页乱码过多时拒绝导出（赛程只读标签属性，不检查）
    view: Optional[View] = None   # 解析后再做的筛选/排序；None 表示原样保存
    reuse_tag: Tuple[str, str] = ("", "")  # 开奖失败时按彩种/玩法恢复，不跨栏目混用


@dataclass(frozen=True)
class TaskResult:
    task: Task
    status: Status
    rows: Tuple[Any, ...]
    note: str
    url: str
    fetched_at: str


def _results_task(day: str, sheet: str, view: Optional[View] = None) -> Task:
    return Task(
        key=f"竞彩足球赛果 {day}", sheet=sheet, day=day, view=view,
        url=RESULT_BASE + "jczq.php?" + urlencode({"d": day}),
        parse=partial(parse_football, day=day))


def _schedule_task(day: str, sheet: str, view: Optional[View] = None, detail: str = "") -> Task:
    return Task(
        key=f"竞彩足球赛程 {day}", sheet=sheet, day=day, view=view, detail=detail, strict_encoding=False,
        url=SCHEDULE_URL + "?" + urlencode({"date": day, "g": "2", "playid": "269"}),
        fallback_url=SCHEDULE_URL + "?" + urlencode({"date": day}),
        parse=partial(parse_schedule, day=day))


def _basketball_schedule_task(day: str, view: Optional[View] = None, detail: str = "") -> Task:
    return Task(
        key=f"竞彩篮球赛程 {day}", sheet=SHEET_BB_UPCOMING, day=day, view=view, detail=detail, strict_encoding=False,
        url=TRADE_BASE + JCLQ_PAGE + "?" + urlencode({"date": day}),
        fallback_url=TRADE_BASE + JCLQ_PAGE + "?" + urlencode({"date": day, "playid": "313", "g": "2"}),
        parse=partial(parse_basketball_schedule, day=day))


def _basketball_results_task(sales_day: str, page_day: str, view: Optional[View] = None) -> Task:
    return Task(
        key=f"竞彩篮球赛果 {sales_day}（页面日期 {page_day}）", sheet=SHEET_BB_SETTLED, day=sales_day, view=view,
        detail="夜里 0 点后开赛的场次在次日页面，所以销售日当天和次日两页都读",
        url=RESULT_BASE + "jclq.php?" + urlencode({"d": page_day}),
        parse=partial(parse_basketball_results, day=sales_day))


def build_tasks(end_day: date, days: int, extra_urls: Sequence[str], mode: str = MODE_FOCUS,
                keep_older_draws: bool = False) -> List[Task]:
    """任务顺序即「采集状态」里的顺序。

    focus（默认）：竞彩足球、竞彩篮球、北京单场、传统足彩、数字彩，每类只取「今日未开赛」和「昨日已开奖」。
    full：每个销售日的赛果、赛程、篮球，然后是各彩种最新页。
    两种模式最后都附上用户用 --url 指定的额外页面。
    """
    tasks: List[Task] = []
    if mode == MODE_FOCUS:
        today, yesterday = end_day.isoformat(), (end_day - timedelta(days=1)).isoformat()
        early_note = "用于补上昨日销售日里尚未开赛的场次（凌晨时段）"
        # 竞彩足球
        tasks.append(_schedule_task(today, SHEET_UPCOMING, upcoming_view))
        tasks.append(_schedule_task(yesterday, SHEET_UPCOMING, upcoming_view, detail=early_note))
        tasks.append(_results_task(yesterday, SHEET_SETTLED, settled_view))
        # 竞彩篮球
        tasks.append(_basketball_schedule_task(today, upcoming_view))
        tasks.append(_basketball_schedule_task(yesterday, upcoming_view, detail=early_note))
        basketball_settled = partial(settled_view, done=is_basketball_settled)
        tasks.append(_basketball_results_task(yesterday, yesterday, basketball_settled))
        tasks.append(_basketball_results_task(yesterday, today, basketball_settled))
        # 北京单场：同一个页面既有未开赛的场次也有已结束场次的比分，抓一次、拆成两张表
        bjdc_url = TRADE_BASE + BJDC_PAGE
        bjdc_note = "销售页只显示当前期（约跨 3 天）；比分来自销售页里已结束的场次"
        tasks.append(Task(key="北京单场 今日未开赛", sheet=SHEET_BJ_UPCOMING, url=bjdc_url, parse=parse_bjdc,
                          view=partial(bjdc_upcoming_view, days=(today, yesterday)),
                          detail=bjdc_note, strict_encoding=False))
        tasks.append(Task(key="北京单场 昨日已开奖", sheet=SHEET_BJ_SETTLED, url=bjdc_url, parse=parse_bjdc,
                          view=partial(bjdc_settled_view, day=yesterday),
                          detail=bjdc_note, strict_encoding=False))
        # 传统足彩：销售页给在售期的场次，开奖页给最近一期的彩果
        for game, page in ZUCAI_SALE_PAGES.items():
            tasks.append(Task(
                key=f"传统足彩在售期 {game}", sheet=SHEET_ZC_UPCOMING, url=TRADE_BASE + page, strict_encoding=False,
                parse=partial(parse_zucai_sale, game=game), view=partial(upcoming_view, order=zucai_order),
                detail="页面标注的当前期；只保留还没开赛的场次"))
        for game, (page, layout) in ZUCAI_RESULT_PAGES.items():
            tasks.append(Task(
                key=f"传统足彩开奖 {game}", sheet=SHEET_ZC_SETTLED, url=RESULT_BASE + page, strict_encoding=False,
                parse=partial(parse_zucai_result, game=game, layout=layout),
                view=partial(drawn_view, keep_older=keep_older_draws), reuse_tag=("game", game), detail="开奖页只显示最近一期"))
        # 数字彩
        for lottery in DRAW_LOTTERIES:
            tasks.append(Task(
                key=f"{lottery.name} 开奖", sheet=SHEET_DRAWS, url=RESULT_BASE + lottery.page,
                parse=partial(parse_draw, lottery=lottery),
                reuse_tag=("lottery", lottery.name),
                view=partial(drawn_view, keep_older=keep_older_draws), detail="开奖页只显示最近一期"))
    else:
        for offset in range(days):
            day = (end_day - timedelta(days=offset)).isoformat()
            tasks.append(_results_task(day, SHEET_RESULTS))
            tasks.append(_schedule_task(day, SHEET_SCHEDULE))
            tasks.append(Task(
                key=f"竞彩篮球 {day}", sheet=SHEET_BASKETBALL,
                url=RESULT_BASE + "jclq.php?" + urlencode({"d": day}),
                parse=partial(parse_raw, label=f"竞彩篮球 {day}"),
                detail="原表保存，含页面其他表格"))
        for name, page in LATEST_PAGES.items():
            tasks.append(Task(
                key=f"{name} 最新公开页", sheet=SHEET_LOTTERY, url=RESULT_BASE + page,
                parse=partial(parse_raw, label=name),
                detail="只代表页面当前展示期号；不能当作历史全量"))
    for number, url in enumerate(extra_urls, 1):
        tasks.append(Task(
            key=f"额外页面 {number}", sheet=SHEET_EXTRA, url=url,
            parse=partial(parse_raw, label="联赛或比赛详情"),
            detail="保存网页静态表格；动态栏目可能不可见"))
    return tasks


def fetch_page(client: HttpClient, url: str, clock: Clock) -> Page:
    final_url, html = client.get(url)
    return Page(url=url, final_url=final_url, html=html, fetched_at=format_time(clock()))


class PageCache:
    """同一次运行里，相同地址只抓一次（比如北单的「未开赛」和「已开奖」来自同一个页面）。

    第一个来取的线程负责抓，其余的等它的结果；抓取失败时大家拿到同一个错误，不会重复重试。
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._futures: Dict[str, "Future[Page]"] = {}

    def get(self, url: str, loader: Callable[[], Page]) -> Page:
        with self._lock:
            future = self._futures.get(url)
            owner = future is None
            if future is None:
                future = self._futures[url] = Future()
        if owner:
            try:
                future.set_result(loader())
            except BaseException as exc:  # noqa: BLE001 — 结果要原样交给所有等待者
                future.set_exception(exc)
        return future.result()


def save_page_html(directory: Path, page: Page) -> None:
    """把抓到的网页源码存一份，方便网站改版、解析失败时拿来排查。失败不影响采集。"""
    parts = urlsplit(page.url)
    stem = re.sub(r"[^\w.-]+", "_", f"{parts.netloc}{parts.path}_{parts.query}").strip("_")[:120] or "page"
    try:
        directory.mkdir(parents=True, exist_ok=True)
        header = f"<!-- 来源：{page.url}  抓取时间：{page.fetched_at}  （已统一转为 UTF-8） -->\n"
        (directory / f"{stem}.html").write_text(header + page.html, encoding="utf-8")
    except OSError as exc:
        logger.warning("无法保存网页 %s：%s", page.url, exc)


def run_task(task: Task, client: HttpClient, clock: Clock, cache: Optional[PageCache] = None,
             html_dir: Optional[Path] = None) -> TaskResult:
    """执行一个任务。预期内外的所有异常都收敛为「失败」结果，绝不影响其他任务。"""
    url, fetched_at = task.url, format_time(clock())
    logger.debug("开始抓取：%s", task.key)

    def load(address: str) -> Page:
        def fetch() -> Page:
            fetched = fetch_page(client, address, clock)
            if html_dir is not None:
                save_page_html(html_dir, fetched)
            return fetched
        return cache.get(address, fetch) if cache is not None else fetch()

    problems = []
    empty = None
    for address in dict.fromkeys(a for a in (task.url, task.fallback_url) if a):
        try:
            page = load(address)
            if task.strict_encoding and page.html.count("\ufffd") > MOJIBAKE_LIMIT:
                raise EncodingProblemError("网页编码损坏，已拒绝导出乱码")
            outcome = task.parse(page)
            note = "；".join(x for x in (task.detail, outcome.note,
                ("主地址失败或无数据，已使用备用地址：" + "；".join(problems)) if address != task.url else "") if x)
            if outcome.rows:
                return TaskResult(task, Status.SUCCESS, outcome.rows, note, address, page.fetched_at)
            empty = TaskResult(task, Status.NO_DATA, (), note + "；页面无可解析数据", address, page.fetched_at)
            problems.append("主地址无数据" if address == task.url else "备用地址无数据")
        except Exception as exc:
            logger.debug("%s 地址失败：%s", task.key, address, exc_info=True)
            problems.append(f"{type(exc).__name__}: {exc}")
    if empty is not None:
        return replace(empty, note=clip(empty.note + "；" + "；".join(problems)))
    return TaskResult(task, Status.FAILED, (), clip("；".join(problems)), url, fetched_at)


def reconcile(result: TaskResult, previous: Mapping[str, Sequence[Any]]) -> TaskResult:
    """本次没取到数据（失败或无数据）时，沿用上次导出里同一销售日的记录，并明确标注。

    previous 里只有能还原成记录的赛程/赛果类工作表，所以原始表不会被沿用。
    """
    task = result.task
    if result.rows:
        return result
    if task.reuse_tag[0]:
        # 合法空页面不能据此认定网络故障；只有抓取/解析失败才保留开奖旧值。
        if result.status is not Status.FAILED:
            return result
        attr, name = task.reuse_tag
        cached = tuple(r for r in previous.get(task.sheet, ()) if getattr(r, attr, None) == name)
    elif task.day:
        cached = tuple(r for r in previous.get(task.sheet, ()) if r.sales_day == task.day)
    else:
        return result
    if not cached:
        return result
    if result.status is Status.FAILED:
        note = clip(result.note) + "；已保留上次记录（旧数据，不代表本次采集成功；日期及抓取时间见原记录）"
    else:
        note = "本次未取到新数据；沿用本机上次成功记录，抓取时间见原记录"
    return replace(result, status=Status.STALE, rows=cached, note=note)


def finalize(result: TaskResult, previous: Mapping[str, Sequence[Any]], now: datetime) -> TaskResult:
    """先按需沿用旧记录，再套用任务的视图（筛选/排序）。

    沿用来的旧记录也要重新筛选：比如上次还没开赛的场次，现在可能已经开赛，不能再算「未开赛」。
    """
    result = reconcile(result, previous)
    view = result.task.view
    if view is None or not result.rows:
        return result
    kept, view_note = view(result.rows, now)
    note = "；".join(part for part in (result.note, view_note) if part)
    return replace(result, rows=tuple(kept), note=note)


# ════════════════════════════════════════════════════════════════════════════
# 11. 汇总与并发执行
# ════════════════════════════════════════════════════════════════════════════

class Ledger:
    """按任务顺序汇集结果（与完成先后无关），并生成要写入各工作表的数据。"""

    def __init__(self, specs: Sequence[SheetSpec]) -> None:
        self._specs = tuple(specs)
        self._results: Dict[int, TaskResult] = {}

    def add(self, index: int, result: TaskResult) -> None:
        self._results[index] = result

    def results(self) -> List[TaskResult]:
        return [self._results[i] for i in sorted(self._results)]

    def sheets(self, uncovered: Sequence[StatusRecord] = ()) -> List[Tuple[SheetSpec, List[Any]]]:
        rows: Dict[str, List[Any]] = {spec.name: [] for spec in self._specs}
        stale_keys: Dict[str, set] = {spec.name: set() for spec in self._specs}
        by_name = {spec.name: spec for spec in self._specs}
        for result in self.results():
            spec = by_name[result.task.sheet]
            if spec.unique is None:
                rows[spec.name].extend(result.rows)
            else:
                self._merge(spec, rows[spec.name], stale_keys[spec.name], result.rows,
                            stale=result.status is Status.STALE)
            rows[SHEET_STATUS].append(StatusRecord(
                result.task.key, result.status, len(result.rows), result.note, result.url, result.fetched_at))
        rows[SHEET_STATUS].extend(uncovered)
        for spec in self._specs:
            if spec.order is not None:
                rows[spec.name].sort(key=spec.order)
        return [(spec, rows[spec.name]) for spec in self._specs]

    @staticmethod
    def _merge(spec: SheetSpec, existing: List[Any], stale_keys: set, new_rows: Sequence[Any],
               *, stale: bool) -> None:
        """把 new_rows 并入 existing（就地修改）。同一场比赛被多个任务给出时只留一条：
        本次新取到的优先于沿用的旧记录。"""
        assert spec.unique is not None
        index = {spec.unique(row): i for i, row in enumerate(existing)}
        for row in new_rows:
            key = spec.unique(row)
            if key not in index:
                index[key] = len(existing)
                existing.append(row)
                (stale_keys.add if stale else stale_keys.discard)(key)
            elif key in stale_keys and not stale:
                existing[index[key]] = row
                stale_keys.discard(key)

    def counts(self) -> "Counter[Status]":
        return Counter(r.status for r in self.results())


@dataclass(frozen=True)
class RunOptions:
    end_day: date
    days: int
    extra_urls: Tuple[str, ...]
    output: Path
    mode: str = MODE_FOCUS
    workers: int = DEFAULT_WORKERS
    reuse_previous: bool = True
    checkpoint_seconds: float = CHECKPOINT_SECONDS
    keep_older_draws: bool = False
    save_html: Optional[Path] = None


@dataclass
class RunReport:
    results: List[TaskResult]
    counts: "Counter[Status]"
    saved: Path
    started: datetime
    finished: datetime
    interrupted: bool = False


def _uncovered_records(clock: Clock) -> List[StatusRecord]:
    stamp = format_time(clock())
    return [StatusRecord(item, Status.NOT_COVERED, 0, UNCOVERED_NOTE, "", stamp) for item in UNCOVERED_ITEMS]


def _log_result(done: int, total: int, result: TaskResult) -> None:
    line = f"[{done}/{total}] {result.task.key}：{result.status.value}，{len(result.rows)} 条"
    if result.status is Status.FAILED:
        logger.warning("%s（%s）", line, result.note)
    else:
        logger.info(line)


def execute(tasks: Sequence[Task], client: HttpClient, options: RunOptions, *,
            clock: Clock = beijing_now, resume: Optional[Mapping[str, Any]] = None) -> RunReport:
    """并发执行全部任务，边做边保存进度；被 Ctrl-C 中断时保存已取得的部分后返回。"""
    started = clock()                              # 同时作为本次判断「是否已开赛」的统一时刻
    specs = specs_for_mode(options.mode, bool(options.extra_urls))
    previous = load_previous(options.output, specs) if options.reuse_previous else {}
    ledger = Ledger(specs)
    last_save = time.monotonic()
    interrupted = False
    warned_locked = False

    def checkpoint() -> None:
        nonlocal last_save, warned_locked
        last_save = time.monotonic()
        try:
            save_workbook(options.output, ledger.sheets(), created=started, allow_fallback=False, clock=clock)
        except ExportError as exc:                 # 进度文件被占用不应中断采集，最终保存时会另存
            if not warned_locked:
                logger.warning("暂时无法保存进度：%s；采集继续，结束时会再次保存", exc)
                warned_locked = True

    workers = max(1, min(options.workers, len(tasks) or 1))
    pool = ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fetch")
    cache = PageCache()
    registry = {c.__name__: c for c in (FootballResult, Fixture, BasketballFixture, BasketballResult,
                 BjdcMatch, ZucaiFixture, ZucaiResult, DrawResult, RawRow)}
    retained = {r['item']: r for r in (resume or {}).get('items', [])
                if r.get('status') in (Status.SUCCESS.value, Status.NO_DATA.value) and 'rows' in r}
    pending = []
    for index, task in enumerate(tasks):
        old = retained.get(task.key)
        if old:
            try:
                records = []
                for row in old['rows']:
                    values = dict(row['data'])
                    if row['type'] == 'RawRow':
                        for key in values:
                            if isinstance(values[key], list):
                                values[key] = tuple(values[key])
                    records.append(registry[row['type']](**values))
                result = TaskResult(task, Status(old['status']), tuple(records), old.get('note', ''),
                                    old['url'], old['fetched_at'])
                ledger.add(index, finalize(result, previous, started))
                continue
            except (KeyError, TypeError, ValueError):
                logger.warning("%s 的摘要无法恢复，重新抓取此项", task.key)
        pending.append((index, task))
    logger.info("保留 %d 项，只抓取/重试 %d 项", len(tasks) - len(pending), len(pending))
    futures = {pool.submit(run_task, task, client, clock, cache, options.save_html): index
               for index, task in pending}
    try:
        for done, future in enumerate(as_completed(futures), 1):
            result = finalize(future.result(), previous, started)
            ledger.add(futures[future], result)
            _log_result(done, len(pending), result)
            if time.monotonic() - last_save >= options.checkpoint_seconds:
                checkpoint()
    except KeyboardInterrupt:
        interrupted = True
        logger.warning("收到中断信号，正在保存已取得的进度……")
    finally:
        pool.shutdown(wait=not interrupted, cancel_futures=True)
    uncovered = _uncovered_records(clock) if options.mode == MODE_FULL and not interrupted else []
    saved = save_workbook(options.output, ledger.sheets(uncovered), created=started,
                          allow_fallback=True, clock=clock)
    return RunReport(ledger.results(), ledger.counts(), saved, started, clock(), interrupted)


def exit_code(report: RunReport, *, strict: bool) -> int:
    if report.interrupted:
        return 130
    if not report.counts[Status.SUCCESS]:
        return 2
    if strict and report.counts[Status.FAILED]:
        return 1
    return 0


def write_summary(path: Path, report: RunReport, options: RunOptions) -> None:
    """机器可读的运行摘要，便于调度系统/监控读取。原子写入。"""
    payload = {
        "version": __version__,
        "started_at": format_time(report.started),
        "finished_at": format_time(report.finished),
        "duration_seconds": round((report.finished - report.started).total_seconds(), 2),
        "mode": options.mode,
        "keep_older_draws": options.keep_older_draws,
        "end_day": options.end_day.isoformat(),
        "days": options.days,
        "output": str(report.saved.resolve()),
        "interrupted": report.interrupted,
        "counts": {status.value: report.counts[status] for status in Status if report.counts[status]},
        "items": [{"item": r.task.key, "status": r.status.value, "records": len(r.rows),
                   "note": r.note, "url": r.url, "fetched_at": r.fetched_at,
                   "rows": [{"type": type(row).__name__, "data": asdict(row)} for row in r.rows]} for r in report.results],
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + ".tmp")
    try:
        temp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


# ════════════════════════════════════════════════════════════════════════════
# 12. 命令行
# ════════════════════════════════════════════════════════════════════════════

def iso_date(text: str) -> date:
    try:
        return datetime.strptime(text, "%Y-%m-%d").date()
    except ValueError:
        raise argparse.ArgumentTypeError(f"日期格式须为 YYYY-MM-DD，收到：{text!r}") from None


def bounded_int(low: int, high: int) -> Callable[[str], int]:
    def convert(text: str) -> int:
        try:
            value = int(text)
        except ValueError:
            value = low - 1
        if not low <= value <= high:
            raise argparse.ArgumentTypeError(f"需要 {low}～{high} 之间的整数，收到：{text!r}")
        return value
    return convert


def positive_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = 0.0
    if not math.isfinite(value) or not value > 0:                       # 同时排除 0、负数与 NaN
        raise argparse.ArgumentTypeError(f"需要大于 0 的数字，收到：{text!r}")
    return value


def non_negative_float(text: str) -> float:
    try:
        value = float(text)
    except ValueError:
        value = -1.0
    if not math.isfinite(value) or not value >= 0:
        raise argparse.ArgumentTypeError(f"需要不小于 0 的数字，收到：{text!r}")
    return value


def build_parser(policy: UrlPolicy, clock: Clock = beijing_now) -> argparse.ArgumentParser:
    def checked_url(text: str) -> str:
        try:
            return policy.validate(text)
        except UrlNotAllowedError as exc:
            raise argparse.ArgumentTypeError(str(exc)) from None

    parser = argparse.ArgumentParser(
        prog="export_500_all.py",
        description="从 500 网公开页面导出单个 Excel 工作簿；未取到的数据会如实标注状态。")
    parser.add_argument("--mode", choices=(MODE_FOCUS, MODE_FULL), default=MODE_FOCUS,
                        help="focus（默认）：竞彩足球、竞彩篮球、北京单场、传统足彩、数字彩，"
                             "只导出「今日未开赛」和「昨日已开奖」；full：导出全部页面的完整数据（赛程、赛果、各彩种原表）")
    parser.add_argument("--date", type=iso_date, metavar="YYYY-MM-DD",
                        help="北京时间的「今日」销售日，默认今天；「昨日」为其前一天")
    parser.add_argument("--days", type=bounded_int(1, MAX_DAYS), default=None, metavar="N",
                        help=f"仅 full 模式：向前追溯的销售日天数，默认 {DEFAULT_DAYS}（今天和昨天），最大 {MAX_DAYS}")
    parser.add_argument("--url", action="append", default=[], type=checked_url, metavar="URL",
                        help="额外指定 500.com 联赛或比赛详情页，可重复")
    parser.add_argument("--output", type=Path, metavar="FILE.xlsx",
                        help="保存路径，默认当前文件夹下 500网数据_日期.xlsx")
    net = parser.add_argument_group("网络与并发")
    net.add_argument("--timeout", type=positive_float, default=DEFAULT_TIMEOUT, metavar="SEC",
                     help=f"单次请求超时秒数，默认 {DEFAULT_TIMEOUT:g}")
    net.add_argument("--retries", type=bounded_int(0, 10), default=DEFAULT_RETRIES, metavar="N",
                     help=f"遇到网络抖动或 429/5xx 时的重试次数，默认 {DEFAULT_RETRIES}")
    net.add_argument("--workers", type=bounded_int(1, MAX_WORKERS), default=DEFAULT_WORKERS, metavar="N",
                     help=f"并发抓取线程数，默认 {DEFAULT_WORKERS}；1 表示逐个抓取")
    net.add_argument("--min-interval", type=non_negative_float, default=DEFAULT_MIN_INTERVAL, metavar="SEC",
                     help=f"同一主机相邻请求的最小间隔秒数，默认 {DEFAULT_MIN_INTERVAL:g}")
    net.add_argument("--max-consecutive-failures", type=bounded_int(0, 100), default=BREAKER_THRESHOLD,
                     metavar="N", help=f"同一主机连续失败 N 次后不再请求它，默认 {BREAKER_THRESHOLD}；0 表示关闭")
    run = parser.add_argument_group("运行控制")
    run.add_argument("--retry-failed", type=Path, metavar="SUMMARY.json", help="读取同日摘要，仅重试失败/沿用旧数据的栏目，保留成功栏目")
    run.add_argument("--strict", action="store_true", help="任一栏目「失败」时以退出码 1 结束，便于调度系统告警")
    run.add_argument("--checkpoint-seconds", type=non_negative_float, default=CHECKPOINT_SECONDS, metavar="SEC",
                     help=f"采集过程中保存进度的最小间隔秒数，默认 {CHECKPOINT_SECONDS:g}；0 表示每完成一项就保存")
    run.add_argument("--no-reuse-previous", dest="reuse_previous", action="store_false",
                     help="本次没取到的赛程/赛果不沿用上次文件里的记录")
    run.add_argument("--keep-older-draws", action="store_true",
                     help="传统足彩和数字彩只显示最近一期；默认只留昨日开奖的，加上它则每种都保留最新一期")
    run.add_argument("--save-html", type=Path, metavar="DIR",
                     help="把抓到的每个网页源码存进这个文件夹，网站改版或某栏目解析失败时用来排查")
    run.add_argument("--summary-json", type=Path, metavar="FILE", help="另存一份机器可读的运行摘要（JSON）")
    run.add_argument("--log-file", type=Path, metavar="FILE", help="把详细日志同时写入文件")
    run.add_argument("-v", "--verbose", action="store_true", help="在终端显示调试日志")
    run.add_argument("-q", "--quiet", action="store_true", help="终端只显示警告和错误")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    return parser


def configure_logging(*, verbose: bool, quiet: bool, log_file: Optional[Path]) -> None:
    """进度和警告走标准错误，最终结果走标准输出；可选地把完整日志写入文件。"""
    logger.setLevel(logging.DEBUG)
    logger.propagate = False
    for handler in list(logger.handlers):
        logger.removeHandler(handler)
        handler.close()
    console = logging.StreamHandler(sys.stderr)
    console.setLevel(logging.DEBUG if verbose else logging.WARNING if quiet else logging.INFO)
    console.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(message)s" if verbose else "%(message)s"))
    logger.addHandler(console)
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.FileHandler(log_file, encoding="utf-8")
        handler.setLevel(logging.DEBUG)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s [%(threadName)s] %(message)s"))
        logger.addHandler(handler)
    for stream in (sys.stdout, sys.stderr):
        # 旧版 Windows 控制台（GBK）遇到生僻字时用占位符代替，而不是崩溃
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure:
            reconfigure(errors="replace")


def resolve_output(parser: argparse.ArgumentParser, output: Optional[Path], end_day: date) -> Path:
    if output is None:
        return Path.cwd() / f"500网数据_{end_day.isoformat()}.xlsx"
    if not output.suffix:
        return output.with_suffix(".xlsx")
    if output.suffix.lower() != ".xlsx":
        parser.error(f"--output 必须是 .xlsx 文件，收到：{output}")
    return output


def main(argv: Optional[Sequence[str]] = None, *, clock: Clock = beijing_now,
         policy: Optional[UrlPolicy] = None) -> int:
    policy = policy or DEFAULT_POLICY
    parser = build_parser(policy, clock)
    args = parser.parse_args(argv)
    if args.mode == MODE_FOCUS and args.days is not None:
        parser.error(f"--days 只用于 --mode {MODE_FULL}；默认模式固定导出「今日未开赛」和「昨日已开奖」")
    days = args.days if args.days is not None else DEFAULT_DAYS
    end_day = args.date or clock().date()
    options = RunOptions(end_day=end_day, days=days, extra_urls=tuple(args.url),
                         output=resolve_output(parser, args.output, end_day),
                         mode=args.mode, workers=args.workers, reuse_previous=args.reuse_previous,
                         checkpoint_seconds=args.checkpoint_seconds,
                         keep_older_draws=args.keep_older_draws, save_html=args.save_html)
    configure_logging(verbose=args.verbose, quiet=args.quiet, log_file=args.log_file)

    client = HttpClient(HttpConfig(timeout=args.timeout, retries=args.retries,
                                   min_interval=args.min_interval,
                                   breaker_threshold=args.max_consecutive_failures), policy)
    tasks = build_tasks(end_day, days, options.extra_urls, mode=args.mode, keep_older_draws=args.keep_older_draws)
    if args.mode == MODE_FOCUS:
        logger.info("开始采集：%s 的未开赛场次 + %s 的已开奖结果（竞足/竞篮/北单/传统足彩/数字彩），共 %d 个栏目，并发 %d",
                    end_day, end_day - timedelta(days=1), len(tasks), args.workers)
    else:
        logger.info("开始采集（完整模式）：%s 起向前 %d 个销售日，共 %d 个栏目，并发 %d",
                    end_day, days, len(tasks), args.workers)
    try:
        resume = None
        if args.retry_failed:
            try:
                resume = json.loads(args.retry_failed.read_text(encoding="utf-8"))
            except (OSError, ValueError) as exc:
                raise ExportError(f"重试摘要读不了：{exc}") from exc
            if (resume.get('end_day') != end_day.isoformat() or resume.get('mode') != args.mode
                    or resume.get('days') != days or resume.get('keep_older_draws') != options.keep_older_draws
                    or Path(resume.get('output', '')).resolve() != options.output.resolve()):
                raise ExportError("重试摘要的日期、输出路径或采集模式不一致，请一键更新")
        report = execute(tasks, client, options, clock=clock, resume=resume)
        if args.summary_json:
            write_summary(args.summary_json, report, options)
    except ExportError as exc:
        logger.error("无法保存结果：%s", exc)
        return 3
    except Exception:  # noqa: BLE001 — 保证调度系统总能拿到明确的退出码
        logger.critical("发生未预期的内部错误", exc_info=True)
        return 3

    counts = report.counts
    print(f"已保存：{report.saved.resolve()}；本次成功 {counts[Status.SUCCESS]} 项，"
          f"沿用旧数据 {counts[Status.STALE]} 项，失败 {counts[Status.FAILED]} 项。")
    if not report.interrupted and not counts[Status.SUCCESS]:
        print("注意：本次没有新数据；文件仅有采集状态和可能保留的旧记录。", file=sys.stderr)
    return exit_code(report, strict=args.strict)


if __name__ == "__main__":
    raise SystemExit(main())
