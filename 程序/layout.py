# -*- coding: utf-8 -*-
"""layout.py —— 文件夹整理：各种文件该放哪个分类文件夹，旧的「全堆在一起」的文件第一次启动时自动归位。

整理后的样子（根目录 = 你放脚本的那个文件夹）：
  启动操作台.bat、run_daily.bat       ← 根目录只留这两个，双击「启动操作台.bat」就行
  程序\\      所有 .py / .pyw 脚本（不用打开）
  设置\\      rules.json（规则）、brand.json（栏目名/口号）、关键词库.json、热词.txt、话术库.json、manual.json（人工修正）、console_settings.json、api_key.txt
  每日数据\\  500网数据_日期.xlsx（每天抓的表）、backfill\\（补抓漏掉的日子）
  推单\\      推单文案_日期.txt、热搜关键词_日期.txt、评论话术_日期.txt、推单图片_日期\\（要发的东西都在这）
  报告\\      战绩统计.txt/.csv、诊断报告.txt、错误日志、排查用的调试文件
  数据库\\    tips_history.json（历史推单）、results_db.json（赛果库）等脚本自己用的数据、历史备份\\、data_cache\\
  说明\\      使用说明
  旧版文件\\  搬家时发现的旧脚本/重名文件（只移动、绝不删除，确认没用了可自己删）

兼容旧结构：只有「程序\\gen_tips.py」存在时才按分类文件夹放；否则（所有文件都在一个文件夹里的老样子）原样不动。
所有读写文件的地方都通过本文件的 p()/d() 找路径，所以改分类只改这一处。纯标准库。
"""
from __future__ import annotations

import re
import shutil
from datetime import datetime
from pathlib import Path
from typing import Callable, List, Optional, Union

__version__ = "1.7"

PROG, SET, DAY, OUT, REP, DB, DOC, OLD = "程序", "设置", "每日数据", "推单", "报告", "数据库", "说明", "旧版文件"
SUBDIRS = (PROG, SET, DAY, OUT, REP, DB, DOC, OLD)
MARKER = "gen_tips.py"                         # 「程序」文件夹里有它，就说明是整理过的结构

FILE_DIR = {
    # 设置：你可能会打开、修改的
    "rules.json": SET, "brand.json": SET, "manual.json": SET, "manual.example.json": SET,
    "console_settings.json": SET, "api_key.txt": SET, "电竞设置.json": SET, "电竞参考设置.json": SET, "team_alias.json": SET, "team_names.json": SET,
    "关键词库.json": SET, "热词.txt": SET, "话术库.json": SET,
    # 报告：战绩、诊断、出问题时发给我的文件
    "战绩统计.txt": REP, "战绩统计.csv": REP, "诊断报告.txt": REP, "console_error.log": REP, "wc_debug_rows.txt": REP,
    "sina_debug": REP,
    # 数据库：脚本自己读写的数据
    "tips_history.json": DB, "results_db.json": DB, "bb_results_db.json": DB, "wc_fixtures.json": DB, "market_latest.json": DB,
    "esports_matches.json": DB, "esports_history_cache.json": DB, "esports_source_cache.json": DB, "model_check.json": DB, "bb_model_check.json": DB, "composite_weights.json": DB, "team_alias_auto.json": DB, "team_names_learned.json": DB,
    "console_last_run.json": DB, "console.lock": DB, "console.run": DB, "data_cache": DB, "历史备份": DB,
    # 每日数据
    "backfill": DAY,
    # 说明
    "文件夹说明.txt": DOC,
}

# 属于这套工具的脚本（搬家时如果在根目录、「程序」里还没有，就搬进「程序」；其他不认识的 .py 当旧文件处理）
KNOWN_PROGRAMS = ("console_ui", "console_config", "bb_data", "commentary", "composite", "export_500_all", "gen_tips", "guard", "keywords", "layout", "leisu_probe", "lq_probe", "market_data", "match_model",
                  "sina_data", "snapshot", "source_probe", "stats", "team_data", "tips_console", "wanchang_probe", "reliability", "esports_data", "esports_refs", "esports_history", "esports_sources")

README_TEXT = """文件夹说明（脚本会自动整理，不用手动搬）
====================================
根目录只留两个启动文件，平时只双击「启动操作台.bat」：

  程序\\      所有脚本，不用打开。更新版本时，把新版文件解压到这个根目录覆盖就行
  设置\\      想改的设置：rules.json（推多少场、排除联赛）、brand.json（栏目名/口号/话题标签）、manual.json（人工修正）
  每日数据\\  每天从 500 网抓下来的表（500网数据_日期.xlsx）；backfill 里是补抓漏掉日子的表
  推单\\      要发的东西：推单文案_日期.txt、热搜关键词_日期.txt（当天的搜索词，一行一个词）、评论话术_日期.txt（每场比赛多种人设的评论区话术）、推单图片_日期 文件夹
  报告\\      战绩统计.txt / 战绩统计.csv、诊断报告.txt、错误日志（出问题把里面的文件发给我）
  数据库\\    脚本自己用的数据（历史推单、赛果库、历史备份……），别手动改
  旧版文件\\  搬家时发现的旧脚本、重名文件。只是挪过来，没删；确认没用了可以自己删

搬家时不会删除任何文件：同名的会放进「旧版文件」。
"""


def _is_org(folder: Path) -> bool:
    return (folder / PROG / MARKER).is_file()


def find_root(folder: Union[str, Path]) -> Path:
    """从 folder 往上最多找 3 层，找到有「程序\\gen_tips.py」的那一层就是根目录；找不到就是 folder 自己（旧的平铺结构）。"""
    f = Path(folder)
    try:
        f = f.resolve()
    except OSError:
        pass
    cur = f
    for _ in range(4):
        if _is_org(cur):
            return cur
        if cur.parent == cur:
            break
        cur = cur.parent
    return Path(folder)


def is_organized(folder: Union[str, Path]) -> bool:
    return _is_org(find_root(folder))


def app_root(script_file: Union[str, Path]) -> Path:
    """脚本自己所在位置对应的根目录：在「程序」文件夹里就是上一层，否则就是脚本所在文件夹。"""
    return find_root(Path(script_file).resolve().parent)


def where(name: str) -> str:
    """这个文件/文件夹该放哪个分类文件夹；返回 "" 表示留在根目录。"""
    if name in FILE_DIR:
        return FILE_DIR[name]
    if name.startswith("500网数据_") and name.endswith(".xlsx"):
        return DAY
    if name.startswith("电竞推单_") and name.endswith(".txt"):
        return OUT
    if name.startswith("推单文案_") or name.startswith("推单图片_") or name.startswith("热搜关键词_") or name.startswith("评论话术_"):
        return OUT
    if "_probe_" in name:
        return REP
    if name.startswith("新功能说明") or name.startswith("使用说明"):
        return DOC
    if name.endswith((".py", ".pyw")):
        return PROG
    return ""


def p(folder: Union[str, Path], name: str) -> Path:
    """文件（或文件夹）name 的完整路径。旧结构：folder/name；整理后的结构：根目录/分类文件夹/name（分类文件夹不存在会先建好）。
    整理后的位置没有、根目录里却还有一份（搬家没成功）→ 先用根目录里的那份，不会丢数据。"""
    root = find_root(folder)
    if not _is_org(root):
        return Path(folder) / name
    sub = where(name)
    if not sub:
        return root / name
    dest = root / sub / name
    if not dest.exists() and (root / name).exists():
        return root / name
    try:
        (root / sub).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return dest


def d(folder: Union[str, Path], sub: str) -> Path:
    """分类文件夹本身（如 每日数据）。旧结构里没有分类文件夹，就是 folder 自己。"""
    root = find_root(folder)
    if not _is_org(root):
        return Path(folder)
    try:
        (root / sub).mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return root / sub


def prog_dir(folder: Union[str, Path]) -> Path:
    root = find_root(folder)
    return root / PROG if _is_org(root) else Path(folder)


def find_xlsx(folder: Union[str, Path]) -> List[Path]:
    """所有「500网数据_日期.xlsx」（整理后在「每日数据」，没搬成功的根目录里那份也算），按文件名里的日期从旧到新。"""
    root = find_root(folder)
    dirs = [Path(folder)] if not _is_org(root) else [root / DAY, root]
    seen, out = set(), []
    for dd in dirs:
        try:
            for f in dd.glob("500网数据_*.xlsx"):
                if f.name not in seen and re.search(r"\d{4}-\d{2}-\d{2}", f.name):
                    seen.add(f.name)
                    out.append(f)
        except OSError:
            continue
    return sorted(out, key=lambda f: f.name)


def out_file(folder: Union[str, Path], name: str) -> Path:
    """要发的文件（推单文案……）放哪：整理后放「推单」；旧结构放 folder。"""
    return p(folder, name)


# ────────────────────────────────────────────────────────────────────────────
# 搬家
# ────────────────────────────────────────────────────────────────────────────
def _unique(dst: Path) -> Path:
    if not dst.exists():
        return dst
    stamp = datetime.now().strftime("%m%d-%H%M%S")
    cand = dst.with_name(f"{dst.stem}_搬家前{stamp}{dst.suffix}")
    n = 2
    while cand.exists():
        cand = dst.with_name(f"{dst.stem}_搬家前{stamp}_{n}{dst.suffix}")
        n += 1
    return cand


def _merge_dir(src: Path, dst: Path, moved: List[str], base: Path) -> None:
    """文件夹 src 并入 dst：dst 不存在就整个搬过去；存在就把里面没有的搬进去，重名的留在原处不动。"""
    if not dst.exists():
        shutil.move(str(src), str(dst))
        moved.append(f"{src.name}\\ → {dst.parent.name}\\")
        return
    for child in list(src.iterdir()):
        t = dst / child.name
        if t.exists():
            continue
        shutil.move(str(child), str(t))
    try:
        src.rmdir()
        moved.append(f"{src.name}\\ → {dst.parent.name}\\（合并）")
    except OSError:
        pass


def migrate(folder: Union[str, Path], log: Optional[Callable[[str], None]] = None) -> List[str]:
    """把根目录里散着的旧文件按分类搬进文件夹（只在整理后的结构下才做；只移动、不删除）。返回「搬了什么」的清单，没搬就是空。
    同名文件已经在目标位置：目标那份保留，根目录这份放进「旧版文件」。被别的程序占用搬不动的会跳过，下次启动再试。"""
    root = find_root(folder)
    if not _is_org(root):
        return []
    moved: List[str] = []
    say = log or (lambda s: None)
    for s in SUBDIRS:
        try:
            (root / s).mkdir(parents=True, exist_ok=True)
        except OSError:
            return moved
    progs = {f.name for f in (root / PROG).glob("*.py*")}
    for entry in sorted(root.iterdir(), key=lambda e: e.name):
        name = entry.name
        if name in SUBDIRS:
            continue
        try:
            if entry.is_dir():
                if name == "__pycache__":
                    shutil.rmtree(entry, ignore_errors=True)       # 只是缓存，会自动重新生成
                    continue
                sub = where(name)
                if sub:
                    _merge_dir(entry, root / sub / name, moved, root)
                continue
            sub = where(name)
            if name.endswith((".py", ".pyw")):
                stem = entry.stem
                if name in progs:
                    dst_dir = OLD                                  # 「程序」里已经有新的了，根目录这份是旧的
                elif stem in KNOWN_PROGRAMS:
                    dst_dir = PROG
                else:
                    dst_dir = OLD                                  # 不是这套工具的脚本（比如手动备份的 gen_tips11.py）
                sub = dst_dir
            if not sub:
                continue
            target = root / sub / name
            if target.exists():
                if sub == OLD:
                    target = _unique(target)
                else:
                    target = _unique(root / OLD / name)
                    sub = OLD
            shutil.move(str(entry), str(target))
            moved.append(f"{name} → {sub}\\")
        except OSError as exc:
            say(f"  整理文件夹：{name} 暂时没搬成（{exc}），下次启动再试")
    readme = root / DOC / "文件夹说明.txt"
    if moved and not readme.exists():
        try:
            readme.write_text(README_TEXT, encoding="utf-8")
        except OSError:
            pass
    if moved:
        say(f"整理文件夹：已把 {len(moved)} 项归进分类文件夹（只移动、没删除任何文件；说明见 说明\\文件夹说明.txt）")
    return moved
