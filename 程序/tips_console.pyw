#!/usr/bin/env python3
# -*- coding: utf-8 -*-
r"""竞彩推单操作台（桌面窗口，不是网页）。只用 Python 自带的 tkinter，不用额外安装任何东西。

打开：双击根目录里的「启动操作台.bat」。
文件夹整理：根目录只留两个 bat，所有脚本在「程序」文件夹里（要放在一起，包括 layout.py、gen_tips.py、composite.py、keywords.py、stats.py、guard.py、team_data.py、sina_data.py、
match_model.py、export_500_all.py……都用最新版）；设置、每日数据、推单、报告、数据库分别在同名文件夹里。第一次启动会把旧的散落文件自动归位
（只移动，不删除；重名的和旧脚本放进「旧版文件」）。说明见「说明\文件夹说明.txt」。

每天只做一件事：点大按钮「一键更新」，它会依次
  ① 抓取数据   运行 export_500_all.py --keep-older-draws（昨日赛果 + 今日赛事）
  ② 复盘昨日   用昨日赛果判定 tips_history.json 里昨天发出的推单：命中 / 未中；
               如果中间漏了某天没更新，会自动补抓那天的赛果，把漏掉的推单也结算掉（不会断档）
  ③ 生成推单   按规则生成今日各玩法推单：每种玩法一篇，先「昨日复盘」（赛果概况＋昨天推的单逐条对账），
               再「今日推单」；存成 推单文案_日期.txt，并把发出去的推文原文记入历史
               （明天自动结算；也能在「昨日复盘」页翻出来看）
然后在「今日推单」页点「复制这条」，去 X 粘贴发布。

窗口里的几页
  今日推单   每条帖子一块，点「复制这条」；字数超限会标红
  今日关键词 按今天在售的赛事整理的搜索词，纯词表：一行一个词，没有说明、没有 #（也存成 推单\热搜关键词_日期.txt）；
             词库在 设置\关键词库.json，你自己看到的热搜词粘进 设置\热词.txt，会排在最前面
  评论话术   为今天每场比赛生成多种人设（数据官、盘口老炮、毒舌解说、热血球迷、冷门猎手、佛系老哥、段子手、战术教授）的评论区话术，
             话术里的数字全部来自当天真实数据；可按人设筛选、「换一批」、双击一条就复制这条、复制全部/纯话术（也存成 推单\评论话术_日期.txt）；
             句库在 设置\话术库.json，想改句子、加你自己的人设都在里面
  昨日复盘   昨日赛果概况 + 各玩法命中率 + 每条推单的命中/未中明细；可选任意一天，并查看那天发出的推文原文
  人工修正   有伤停/赛前消息时，排除某队、手动指定胜负彩、补推荐（保存在 manual.json）
  设置       右上角，三页：「更新」（自动更新、漏更新补抓、代理）；「两队数据」：每次生成推单前自动抓两队近况/伤停/交锋，
             和推单方向对比，数据不支持的不推（来源默认读新浪彩票的公开文章，免费、不用密钥；也可以接 API-Football 接口，
             设置里有「测试连接」按钮）；「每天自动运行」：用 Windows 的任务计划，到点自动打开本软件并更新
  战绩统计   分玩法/近7日/近30日命中率、连红连黑、两队数据/防平/模型把握/星级的检验、未中归因；可生成周报、月报，导出 CSV
  运行日志   抓取和生成过程的详细输出，出问题时看这里

今日推单页里每条帖子下面有「发帖前检查」（已开赛的场次、夸大用词、数据太旧……）和「建议发帖时间」（最早一场开赛前 30 分钟，过了会标红）；
再次更新时，赔率/让球线和上一次比有变化会提醒（临场变动）。右上角「规则设置」打开 rules.json（推多少场、排除联赛、赔率范围……），
「诊断包」一键生成 诊断报告.txt（遇到问题发给我，密钥已打码）。

这个文件会生成的小文件（整理后按类放进分类文件夹，旧结构里就都在同一个文件夹）
  数据库\  tips_history.json（历史推单，别删——复盘靠它）、results_db.json（赛果库，别删——越攒越有用）、console_last_run.json、
           data_cache/（接口和新浪网页的缓存，可删）、team_names_learned.json（自动记住的队名对照）、历史备份/（每天自动备份，最多 7 份，坏了自动恢复）
  设置\    console_settings.json、rules.json（规则设置，可改）、brand.json（栏目名/口号）、manual.json（人工修正）、api_key.txt（接口密钥，只在你自己电脑上）
  报告\    战绩统计.txt / 战绩统计.csv、诊断报告.txt、console_error.log、sina_debug/（读到新浪文章却没认出内容时存的文字，发给我就能改规则）
  每日数据\ 500网数据_日期.xlsx、backfill/（补抓漏掉日子的表）      推单\  推单文案_日期.txt、热搜关键词_日期.txt、评论话术_日期.txt、推单图片_日期/
  想补队名对照：在「设置」里新建 team_names.json，写成 {"中文队名": "英文队名"}（给接口用）；新建 team_alias.json，写成 {"500网叫法": "新浪叫法|另一种叫法"}（给新浪用）
  命令行参数：--run  启动后立刻「一键更新」（任务计划用）
"""

from __future__ import annotations

import json
import os
import queue
import re
import subprocess
import sys
import threading
import time
import traceback
import webbrowser
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

PROG_DIR = Path(__file__).resolve().parent              # 脚本所在的文件夹（整理后的结构里是「程序」）
sys.path.insert(0, str(PROG_DIR))
try:
    import layout as L                                  # 文件夹整理：各种文件放哪个分类文件夹
except ImportError:                                     # 缺 layout.py：先当旧结构用，启动后会提示补文件
    class L:                                            # type: ignore[no-redef]
        DAY = OUT = REP = ""

        @staticmethod
        def app_root(f: Any) -> Path:
            return Path(f).resolve().parent

        @staticmethod
        def migrate(f: Any, log: Any = None) -> List[str]:
            return []

        @staticmethod
        def p(folder: Any, name: str) -> Path:
            return Path(folder) / name

        @staticmethod
        def d(folder: Any, sub: str = "") -> Path:
            return Path(folder)

        @staticmethod
        def prog_dir(folder: Any) -> Path:
            return Path(folder)

        @staticmethod
        def find_xlsx(folder: Any) -> List[Path]:
            return sorted(Path(folder).glob("500网数据_*.xlsx"))

from reliability import BJT, beijing_now, atomic_batch

APP_DIR = L.app_root(__file__)                          # 根目录（整理后是「程序」的上一层）
MIGRATED = L.migrate(APP_DIR)                           # 先把散着的旧文件归位，再算下面这些路径（只移动、不删除）

EXPORT = L.prog_dir(APP_DIR) / "export_500_all.py"
if not EXPORT.exists() and (APP_DIR / "export_500_all.py").exists():
    EXPORT = APP_DIR / "export_500_all.py"
HISTORY = L.p(APP_DIR, "tips_history.json")
MANUAL = L.p(APP_DIR, "manual.json")
SETTINGS = L.p(APP_DIR, "console_settings.json")
LAST = L.p(APP_DIR, "console_last_run.json")
ERRLOG = L.p(APP_DIR, "console_error.log")
BACKFILL_DIR = L.p(APP_DIR, "backfill")   # 补抓漏掉那天的赛果时，抓来的表放这里（不会和每天的表混在一起）
BJT = timezone(timedelta(hours=8))
NEED_FILES = (("gen_tips.py", "3.1.4-esports.5"), ("stats.py", "1.2"), ("guard.py", "1.1"), ("snapshot.py", "1.4"), ("layout.py", "1.7"),
              ("match_model.py", "1.4"), ("sina_data.py", "1.3"), ("composite.py", "1.1"), ("keywords.py", "1.1"), ("commentary.py", "1.3"), ("reliability.py", "1.1"), ("team_data.py", "1.1"), ("export_500_all.py", "2.3.1"), ("esports_data.py", "1.3"), ("esports_sources.py", "1.0"), ("esports_history.py", "1.1"), ("esports_refs.py", "1.0"))   # 文件名, 这个版本需要的最低版本号


def _ver_tuple(v: str) -> tuple:
    return tuple(int(x) if x.isdigit() else 0 for x in re.split(r"[.\-]", v.strip()))


def file_problems() -> List[str]:
    """检查脚本文件夹里的文件是不是都放全、都是新版（读文件里的 __version__，不执行它们）。返回问题清单，空 = 都没问题。"""
    out: List[str] = []
    for name, need in NEED_FILES:
        f = L.prog_dir(APP_DIR) / name
        if not f.exists():
            out.append(f"缺少 {name}")
            continue
        try:
            m = re.search(r'^[ \t]*__version__[ \t]*=[ \t]*([\'"])([^\'"\r\n]+)\1', f.read_text(encoding="utf-8-sig", errors="replace")[:30000], re.M)
        except OSError:
            continue
        have = m.group(2) if m else "旧版（没有版本号）"
        if not m or _ver_tuple(have) < _ver_tuple(need):
            out.append(f"{name} 还是旧版本")
    return out


def file_problem_text(probs: List[str]) -> str:
    return ("文件没放全或没换成新版：" + "；".join(probs) + f"。请把我发的新版文件放进 {L.prog_dir(APP_DIR)}（有同名的就覆盖），然后关掉操作台重新打开。")


EXPORT_TIMEOUT = 15 * 60          # 抓取最长等多久（秒），超时自动结束
STALE_HOURS = 3                   # 数据抓取超过这么久就提醒「该更新了」

from console_ui import C, ConsoleShellMixin
from console_config import read_settings

EXAMPLE_MANUAL = {
    "exclude_teams": ["伯恩茅斯"],
    "sfc_overrides": {"2": "3/1"},
    "extra_picks": [{"play": "竞足", "market": "总进球", "key": "周四012", "pick": ["2", "3"], "note": "前瞻比分2:0"}],
    "day": "2026-10-15",
    "match_notes": [{"teams": ["托林斯|托伦斯", "桑德兰"], "verdict": "support", "note": "两队近况/排名/伤停对比（填你查到的真实数据）"}],
}

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
except ImportError:                               # 极少数精简版 Python 没带 tkinter
    tk = None


def load_settings() -> Dict[str, Any]:
    return read_settings(SETTINGS)


KEYFILE = L.p(APP_DIR, "api_key.txt")
KEY_URL = "https://dashboard.api-football.com/register"


def read_key() -> str:
    try:
        return KEYFILE.read_text(encoding="utf-8").strip().splitlines()[0].strip()
    except (OSError, IndexError):
        return ""


def clean_key(raw: str) -> str:
    return (raw or "").strip().strip("\"'“”‘’").strip()


def key_ok(k: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9_\-]{10,80}", k))


TASK_NAME = "500网推单每日更新"
LOCK = L.p(APP_DIR, "console.lock")
RUN_FLAG = L.p(APP_DIR, "console.run")
LOCK_STALE = 120                  # 窗口开着时每 30 秒更新一次锁文件；超过这么久没更新就当作窗口已经关了


def lock_fresh() -> bool:
    try:
        return time.time() - LOCK.stat().st_mtime < LOCK_STALE
    except OSError:
        return False


def touch_lock() -> None:
    try:
        LOCK.write_text(str(os.getpid()), encoding="utf-8")
    except OSError:
        pass


def pythonw_exe() -> str:
    exe = Path(sys.executable)
    if exe.name.lower() == "python.exe" and exe.with_name("pythonw.exe").exists():
        return str(exe.with_name("pythonw.exe"))
    return str(exe)


def sched_create_cmd(hhmm: str) -> List[str]:
    """Windows 任务计划：每天 hhmm 运行「pythonw 本文件 --run」（打开操作台并自动一键更新）。"""
    # Windows 任务计划的 /ST 使用本机时区，输入统一按北京时间解释。
    hh, mm = map(int, hhmm.split(":"))
    local_hhmm = beijing_now().replace(hour=hh, minute=mm, second=0, microsecond=0).replace(tzinfo=BJT).astimezone().strftime("%H:%M")
    tr = f'"{pythonw_exe()}" "{Path(__file__).resolve()}" --run'
    return ["schtasks", "/Create", "/TN", TASK_NAME, "/TR", tr, "/SC", "DAILY", "/ST", local_hhmm, "/F"]


def sched_run(args: List[str], runner: Any = None) -> "tuple[int, str]":
    try:
        r = (runner or subprocess.run)(args, capture_output=True, text=True, errors="replace", timeout=30, stdin=subprocess.DEVNULL,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        return r.returncode, ((r.stdout or "") + (r.stderr or "")).strip()
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)


def sched_exists(runner: Any = None) -> bool:
    return sys.platform.startswith("win") and sched_run(["schtasks", "/Query", "/TN", TASK_NAME], runner)[0] == 0


def sched_create(hhmm: str, runner: Any = None) -> "tuple[bool, str]":
    rc, out = sched_run(sched_create_cmd(hhmm), runner)
    return rc == 0, out


def sched_delete(runner: Any = None) -> "tuple[bool, str]":
    rc, out = sched_run(["schtasks", "/Delete", "/TN", TASK_NAME, "/F"], runner)
    return rc == 0, out


def newest_xlsx() -> Optional[Path]:
    """日期最新的 500网数据_日期.xlsx（按文件名里的日期选，不看修改时间）。"""
    found = L.find_xlsx(APP_DIR)
    return max(found, key=lambda p: (re.search(r"\d{4}-\d{2}-\d{2}", p.name).group(), p.stat().st_mtime), default=None)


def child_python() -> str:
    """抓取脚本用 python.exe 跑（带 CREATE_NO_WINDOW，不会弹黑窗）；本窗口若是 pythonw.exe 启动的，换回 python.exe。"""
    exe = Path(sys.executable)
    if exe.name.lower() == "pythonw.exe" and exe.with_name("python.exe").exists():
        return str(exe.with_name("python.exe"))
    return str(exe)


def natural_key(s: str) -> list:
    return [int(t) if t.isdigit() else t for t in re.split(r"(\d+)", str(s))]


def open_in_explorer(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))                    # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])


class App(ConsoleShellMixin, tk.Tk if tk else object):                # type: ignore[misc]
    STEPS = ("① 抓取数据", "② 复盘昨日", "③ 生成今日推单")

    def __init__(self, force_run: bool = False) -> None:
        import gen_tips as G                       # 放这里：缺文件/版本旧时能给出看得懂的提示
        if not hasattr(G, "run"):
            raise RuntimeError("gen_tips.py 是旧版本（缺少 run 函数）。请用这次一起发的新版 gen_tips.py 覆盖它。")
        self.G = G
        probs = file_problems()
        self.file_msg = file_problem_text(probs) if probs else ""
        super().__init__()
        self.title("竞彩推单操作台")
        self.geometry(f"{min(1180, max(960, self.winfo_screenwidth() - 80))}x{min(940, max(680, self.winfo_screenheight() - 90))}")
        self.minsize(960, 660)
        self.configure(bg=C["bg"])
        self.settings = load_settings()
        self.q: "queue.Queue[tuple]" = queue.Queue()
        self.busy = False
        self.cancel = threading.Event()
        self.proc: Optional[subprocess.Popen] = None
        self.blocks: List[Dict[str, Any]] = []
        self.result: Optional[Dict[str, Any]] = None
        self.manual_run = False
        self.img_busy = False
        self._flash_job: Optional[str] = None

        self._init_fonts()
        self._init_style()
        self._build()
        self.protocol("WM_DELETE_WINDOW", self.on_close)
        self.report_callback_exception = self._on_tk_error
        self.bind("<F5>", lambda e: self.start_update(True))

        self._load_last()
        self._refresh_review()
        self._refresh_stats()
        self._load_manual_text()
        self.after(100, self._poll)
        self.after(30000, self._tick)
        if MIGRATED:
            self._append_log(f"整理文件夹：已把 {len(MIGRATED)} 项旧文件归进分类文件夹（程序、设置、每日数据、推单、报告、数据库……）。只是移动，没删除任何文件；说明见 说明\\文件夹说明.txt。")
            for m_ in MIGRATED[:12]:
                self._append_log("  · " + m_)
            if len(MIGRATED) > 12:
                self._append_log(f"  · ……另外还有 {len(MIGRATED) - 12} 项")
            self._relink_schedule()
        if self.file_msg:
            self._append_log("⛔ " + self.file_msg)
        if not EXPORT.exists():
            self._set_status("找不到 export_500_all.py——「一键更新」抓不了数据。请把它放进这个文件夹。", "bad")
        elif self.file_msg:
            self._set_status("⛔ " + self.file_msg, "bad")
        elif force_run or self.settings.get("auto"):
            self.after(900, lambda: self.start_update(True, manual=False))
        touch_lock()

    # ════════════════════════════════════════════════════════════════════
    # 外观
    # ════════════════════════════════════════════════════════════════════
    def open_output_folder(self) -> None:
        self._safe(open_in_explorer, L.d(APP_DIR, L.OUT))

    # —— 今日推单 ——
    def _build_posts_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="今日推单")
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=10, pady=10)
        left = tk.Frame(pw, bg=C["card"])
        right = tk.Frame(pw, bg=C["card"])
        pw.add(left, weight=1)
        pw.add(right, weight=4)

        tk.Label(left, text="帖子（一块 = 发一条）", bg=C["card"], fg=C["muted"], font=self.f_small).pack(anchor="w")
        lbf = tk.Frame(left, bg=C["card"])
        lbf.pack(fill="both", expand=True, pady=(4, 6))
        self.lb = tk.Listbox(lbf, exportselection=False, activestyle="none", font=self.f_ui, width=24, bd=0, highlightthickness=1,
                             highlightbackground=C["line"], selectbackground=C["accent"], selectforeground="white")
        sb = ttk.Scrollbar(lbf, command=self.lb.yview)
        self.lb.configure(yscrollcommand=sb.set)
        self.lb.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.lb.bind("<<ListboxSelect>>", lambda e: self._show_block())
        self.lb.bind("<Double-Button-1>", lambda e: self.copy_current())
        ttk.Button(left, text="复制全部（带分隔线）", command=self.copy_all).pack(fill="x", pady=(0, 4))
        ttk.Button(left, text="另存为 txt…", command=self.save_txt).pack(fill="x", pady=(0, 4))
        self.btn_img = ttk.Button(left, text="生成图片快照", command=self.make_images_now)
        self.btn_img.pack(fill="x")
        ttk.Button(left, text="选择浏览器", command=self.choose_browser).pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="电竞预测设置", command=self.open_esports_settings).pack(fill="x", pady=(6, 0))
        ttk.Button(left, text="电竞参考设置", command=self.open_esports_reference_settings).pack(fill="x", pady=(6, 0))

        top = tk.Frame(right, bg=C["card"])
        top.pack(fill="x")
        self.blk_info = tk.Label(top, text="", bg=C["card"], fg=C["muted"], font=self.f_ui, anchor="w")
        self.blk_info.pack(side="left")
        self.btn_copy = tk.Button(top, text="复制这条", command=self.copy_current, bg=C["accent"], fg="white", activebackground=C["accent_dark"],
                                  activeforeground="white", relief="flat", bd=0, padx=18, pady=5, cursor="hand2", font=self.f_bold)
        self.btn_copy.pack(side="right")
        chk = tk.Frame(right, bg=C["card"])
        chk.pack(fill="x", pady=(4, 0))
        self.btn_chk = ttk.Button(chk, text="全部检查", command=self.show_all_checks)
        self.btn_chk.pack(side="right", padx=(8, 0))
        self.pf_lbl = tk.Label(chk, text="", bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w", justify="left")
        self.pf_lbl.pack(side="left", fill="x", expand=True)
        chk.bind("<Configure>", lambda e: self.pf_lbl.configure(wraplength=max(240, e.width - 110)))
        tf = tk.Frame(right, bg=C["card"])
        tf.pack(fill="both", expand=True, pady=(6, 0))
        self.txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"],
                           padx=14, pady=12, bg="#fbfbfc", state="disabled", spacing1=2, spacing3=2)
        sb2 = ttk.Scrollbar(tf, command=self.txt.yview)
        self.txt.configure(yscrollcommand=sb2.set)
        self.txt.pack(side="left", fill="both", expand=True)
        sb2.pack(side="right", fill="y")
        self._show_empty_posts()

    # —— 今日关键词 ——
    def open_esports_settings(self) -> None:
        try:
            import esports_data as ES
            ES.load_settings(APP_DIR, write=True)
            open_in_explorer(L.p(APP_DIR, "电竞设置.json"))
        except Exception as exc:
            messagebox.showerror("电竞设置", str(exc), parent=self)

    def open_esports_reference_settings(self) -> None:
        try:
            import esports_refs as ER
            ER.load_settings(APP_DIR, write=True)
            open_in_explorer(L.p(APP_DIR, "电竞参考设置.json"))
        except Exception as exc:
            messagebox.showerror("电竞参考设置", str(exc), parent=self)

    def _build_kw_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="今日关键词")
        bar = tk.Frame(f, bg=C["card"])
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.kw_info = tk.Label(bar, text="", bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        self.kw_info.pack(side="left")
        for text, cmd in (("编辑热词", self.open_hot), ("编辑词库", self.open_lex), ("复制全部", self.copy_kw_all)):
            ttk.Button(bar, text=text, command=cmd).pack(side="right", padx=(6, 0))
        tf = tk.Frame(f, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.kw_txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"],
                              padx=14, pady=12, bg="#fbfbfc", state="disabled", spacing1=2, spacing3=2)
        sb = ttk.Scrollbar(tf, command=self.kw_txt.yview)
        self.kw_txt.configure(yscrollcommand=sb.set)
        self.kw_txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self._show_kw(None)

    def _show_kw(self, kw: Optional[Dict[str, Any]]) -> None:
        self.kw = kw if isinstance(kw, dict) and kw.get("text") else None
        if self.kw:
            self.kw_info.configure(text=f"{self.kw.get('day', '')}｜{len(self.kw.get('words') or [])} 个词｜{self.kw.get('n_matches', 0)} 场在售赛事")
            self._set_text(self.kw_txt, self.kw["text"])
        else:
            self.kw_info.configure(text="")
            self._set_text(self.kw_txt, "还没有关键词。\n\n点上面蓝色的「一键更新」，更新完这里会出现今天的词表：一行一个词，没有说明、没有 #。\n"
                                        "你自己看到的热搜词，一行一个粘进「编辑热词」打开的文件里，下次更新会排在最前面。")

    def copy_kw_all(self) -> None:
        if self.kw:
            self._to_clipboard(self.kw["text"])
            self._set_status("已复制整份关键词（一行一个词）。", "ok")

    def _open_kw_file(self, name_attr: str) -> None:
        try:
            if getattr(self.G, "KW", None) is None:
                raise OSError("缺少 keywords.py（把新版的程序文件都放进「程序」文件夹）")
            self.G.ensure_lexicon_and_hot(APP_DIR)
            path = L.p(APP_DIR, getattr(self.G.KW, name_attr))
            if not path.exists():
                raise OSError(f"{path.name} 建不出来（文件夹不能写？）")
            open_in_explorer(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打不开文件", str(exc), parent=self)
            return
        self._set_status("已打开。改完存盘，再点「一键更新」（或「只用现有数据重新生成」）就按新的出关键词。", "ok")

    def open_hot(self) -> None:
        self._open_kw_file("HOT_FILE")

    def open_lex(self) -> None:
        self._open_kw_file("LEX_FILE")

    # —— 评论话术 ——
    CM_ALL = "全部人设"

    def _build_cm_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="评论话术")
        self.cm: Optional[Dict[str, Any]] = None
        self.cm_out: Optional[Dict[str, Any]] = None
        self.cm_seed = 0
        bar = tk.Frame(f, bg=C["card"])
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.cm_info = tk.Label(bar, text="", bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        self.cm_info.pack(side="left")
        for text, cmd in (("编辑话术库", self.open_cm_lib), ("复制纯话术", self.copy_cm_plain), ("复制全部", self.copy_cm_all), ("换一批", self.cm_next)):
            ttk.Button(bar, text=text, command=cmd).pack(side="right", padx=(6, 0))
        self.cm_who = tk.StringVar(value=self.CM_ALL)
        self.cm_box = ttk.Combobox(bar, textvariable=self.cm_who, values=[self.CM_ALL], state="readonly", width=12)
        self.cm_box.pack(side="right", padx=(6, 0))
        self.cm_box.bind("<<ComboboxSelected>>", lambda e: self._cm_recompose())
        tk.Label(bar, text="人设：", bg=C["card"], fg=C["muted"], font=self.f_small).pack(side="right")
        tip = tk.Label(f, text="一行一句评论，双击复制；关键词和评论文本默认自动导出到「推单」文件夹。",
                       bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        tip.pack(fill="x", padx=12)
        tf = tk.Frame(f, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=10, pady=(4, 10))
        self.cm_txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"],
                              padx=14, pady=12, bg="#fbfbfc", state="disabled", spacing1=2, spacing3=2)
        sb = ttk.Scrollbar(tf, command=self.cm_txt.yview)
        self.cm_txt.configure(yscrollcommand=sb.set)
        self.cm_txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.cm_txt.bind("<Double-Button-1>", self._cm_copy_line)
        self._show_cm(None)

    def _show_cm(self, cm: Optional[Dict[str, Any]]) -> None:
        self.cm = cm if isinstance(cm, dict) and cm.get("data") and cm.get("text") else None
        self.cm_out = None
        if self.cm:
            self.cm_seed = int((self.cm.get("out") or {}).get("seed") or 0)
            self.cm_who.set(self.cm.get("only") or self.CM_ALL)
            self._cm_recompose()
        else:
            self.cm_info.configure(text="")
            self._set_text(self.cm_txt, "还没有评论话术。\n\n点上面蓝色的「一键更新」，更新完这里会出现今天每场比赛的评论话术：\n"
                                        "多种人设（数据官、盘口老炮、毒舌解说、热血球迷、冷门猎手、佛系老哥、段子手、战术教授），每条只引用当天的真实数据。\n"
                                        "不满意就点「换一批」；想改句子、加你自己的人设，点「编辑话术库」。")

    def _cm_lib(self):
        CM = getattr(self.G, "CM", None)
        if CM is None:
            raise OSError("缺少 commentary.py（把新版的程序文件都放进「程序」文件夹）")
        bad = list(getattr(getattr(self.G, "GD", None), "FORBIDDEN", []) or [])
        lib, warns = CM.load_lib(L.p(APP_DIR, CM.LIB_FILE), bad)
        return CM, lib, warns, bad

    def _cm_recompose(self) -> None:
        if not self.cm:
            return
        try:
            CM, lib, warns, bad = self._cm_lib()
            names = CM.persona_names(lib)
            self.cm_box.configure(values=[self.CM_ALL] + names)
            who = self.cm_who.get()
            if who != self.CM_ALL and who not in names:
                who = self.CM_ALL
                self.cm_who.set(who)
            o = self.cm.get("opts") or {}
            out = CM.compose(self.cm["data"], lib, seed=self.cm_seed, per=int(o.get("per", 6)), watch_per=int(o.get("watch_per", 3)),
                             max_len=int(o.get("max_len", 110)), recap_n=int(o.get("recap_n", 5)), bad=bad, emoji=bool(o.get("emoji", True)),
                             only=[] if who == self.CM_ALL else [who])
        except Exception as exc:  # noqa: BLE001
            self.cm_info.configure(text="")
            self._set_text(self.cm_txt, f"评论话术显示不出来：{exc}")
            return
        self.cm_out = out
        for w in warns:
            if not getattr(self, "_cm_warned", None) or w not in self._cm_warned:
                self._cm_warned = (getattr(self, "_cm_warned", None) or []) + [w]
                self._append_log("⚠ " + w)
        self.cm_info.configure(text=f"{out['day']}｜{out['n_match']} 场｜{out['n_line']} 条｜第 {out['seed'] + 1} 批｜句库 {out.get('variant_count', 0)} 式" + ("" if who == self.CM_ALL else f"｜只看「{who}」"))
        self._set_text(self.cm_txt, out["text"])

    def cm_next(self) -> None:
        if self.busy:
            self._set_status("正在更新数据，完成后再换评论。", "warn")
            return
        if not self.cm:
            self._set_status("还没有评论话术：先点「一键更新」。", "warn")
            return
        self.cm_seed += 1
        self._cm_recompose()
        if self.cm_out and self.cm_out.get("seed") == self.cm_seed:
            try:
                path = L.p(APP_DIR, f"评论话术_{self.cm_out['day']}.txt")
                updated = dict(self.cm)
                updated["only"] = self.cm_who.get()
                updated.update(out=self.cm_out, text=self.cm_out["text"], plain=self.cm_out["plain"],
                               n_match=self.cm_out['n_match'], n_line=self.cm_out['n_line'])
                result = dict(self.result or {})
                result.update(comments=updated, cm_txt=str(path))
                atomic_batch({path: self.cm_out["plain"], LAST: json.dumps(result, ensure_ascii=False)},
                             path.parent / "评论批次.json")
                self.cm = updated
                self.result = result
            except OSError as exc:
                self._set_status(f"评论文本导出失败：{exc}", "bad")
                return
            self._set_status("已换一批并导出评论文本。", "ok")

    def copy_cm_all(self) -> None:
        if self.cm_out:
            self._to_clipboard(self.cm_out["text"])
            self._set_status("已复制评论文本（一行一句）。", "ok")

    def copy_cm_plain(self) -> None:
        if self.cm_out:
            self._to_clipboard(self.cm_out["plain"])
            self._set_status("已复制评论文本（一行一句）。", "ok")

    def _cm_copy_line(self, event) -> str:
        try:
            line = self.cm_txt.get("current linestart", "current lineend")
        except tk.TclError:
            return "break"
        if line.strip():
            self._to_clipboard(line.strip())
            self._set_status("已复制这一条。", "ok")
        return "break"

    def open_cm_lib(self) -> None:
        try:
            CM = getattr(self.G, "CM", None)
            if CM is None:
                raise OSError("缺少 commentary.py（把新版的程序文件都放进「程序」文件夹）")
            path = L.p(APP_DIR, CM.LIB_FILE)
            CM.ensure_lib_file(path)
            if not path.exists():
                raise OSError(f"{path.name} 建不出来（文件夹不能写？）")
            open_in_explorer(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打不开文件", str(exc), parent=self)
            return
        self._set_status("已打开。改完存盘，回来点「换一批」就按新句库出话术（不用重新更新）。", "ok")

    # —— 战绩统计 ——
    def _build_stats_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="战绩统计")
        bar = tk.Frame(f, bg=C["card"])
        bar.pack(fill="x", padx=10, pady=(10, 4))
        self.stats_info = tk.Label(bar, text="", bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        self.stats_info.pack(side="left")
        for text, cmd in (("导出 CSV", self.export_stats_csv), ("生成月报", lambda: self.show_period("月报")),
                          ("生成周报", lambda: self.show_period("周报")), ("刷新", self._refresh_stats)):
            ttk.Button(bar, text=text, command=cmd).pack(side="right", padx=(6, 0))
        tf = tk.Frame(f, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.stats_txt = tk.Text(tf, wrap="word", font=self.f_mono, bd=0, highlightthickness=1, highlightbackground=C["line"], padx=14, pady=10,
                                 bg="#fbfbfc", state="disabled", spacing1=1, spacing3=1)
        sb = ttk.Scrollbar(tf, command=self.stats_txt.yview)
        self.stats_txt.configure(yscrollcommand=sb.set)
        self.stats_txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.stats_txt.tag_configure("h", font=(self.f_mono[0], 10, "bold"), foreground=C["accent_dark"])
        self._set_text(self.stats_txt, "还没有统计。点「一键更新」后，这里会列出分玩法的命中率、连红连黑和各项检验。")

    def _refresh_stats(self) -> None:
        ST = getattr(self.G, "ST", None)
        if ST is None:
            err = (getattr(self.G, "IMPORT_ERRORS", {}) or {}).get("stats.py", "")
            self._set_text(self.stats_txt, "战绩统计用不了。" + (self.file_msg or (f"stats.py 没能载入（{err}）。把它重新覆盖一遍，再不行就点右上角「诊断包」把诊断报告.txt 发给我。" if err
                                                                           else "缺少 stats.py（要和 gen_tips.py 放在同一个文件夹）。")))
            self.stats_info.configure(text="")
            return
        try:
            day = (self.result or {}).get("day") or datetime.now(BJT).strftime("%Y-%m-%d")
            hist = self.G.load_history(HISTORY)
            S = ST.compute(hist, day, self.G.DRAW_GUARD)
            text = ST.report_text(S)
        except Exception as exc:  # noqa: BLE001 —— 统计只是附加页，别拖垮界面
            self._set_text(self.stats_txt, f"战绩统计算不出来：{exc}")
            return
        w = self.stats_txt
        w.configure(state="normal")
        w.delete("1.0", "end")
        for line in text.splitlines():
            head = bool(re.match(r"^[一二三四五六七八九十]+、", line)) or line.startswith("战绩统计")
            w.insert("end", line + "\n", "h" if head else "")
        w.configure(state="disabled")
        sh, sn = S["singles"]["累计"]
        self.stats_info.configure(text=(f"累计单场 {sh}/{sn}（{sh / sn:.0%}）｜近30日 {S['singles']['近30日'][0]}/{S['singles']['近30日'][1]}｜近7日 {S['singles']['近7日'][0]}/{S['singles']['近7日'][1]}"
                                        if sn else "还没有已出结果的推单"))

    def export_stats_csv(self) -> None:
        ST = getattr(self.G, "ST", None)
        if ST is None:
            return
        try:
            n = ST.export_csv(self.G.load_history(HISTORY), L.p(APP_DIR, self.G.STATS_CSV))
            self.G.write_stats_files(self.G.load_history(HISTORY), (self.result or {}).get("day") or datetime.now(BJT).strftime("%Y-%m-%d"), APP_DIR, csv_too=False)
        except OSError as exc:
            messagebox.showerror("导出失败", f"写不了 {self.G.STATS_CSV}：{exc}\n（是不是被 Excel 打开着？关掉再试）", parent=self)
            return
        self._set_status(f"已导出 {n} 条已出结果的推单到 {self.G.STATS_CSV}（Excel 可直接打开），战绩统计.txt 也已更新。", "ok")
        self._safe(open_in_explorer, L.d(APP_DIR, L.REP))

    def show_period(self, kind: str) -> None:
        """周报/月报：截至昨天的最近 7/30 天，只用真实结果；弹出窗口，可复制。样本太少不出。"""
        day = (self.result or {}).get("day") or datetime.now(BJT).strftime("%Y-%m-%d")
        try:
            lines = self.G.period_lines(self.G.load_history(HISTORY), day, kind, self.G.load_brand(APP_DIR), rolling=True)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror(kind, f"生成{kind}出错：{exc}", parent=self)
            return
        if not lines:
            messagebox.showinfo(kind, f"最近这段时间已出结果的单场推荐不到 5 条，样本太少，先不出{kind}。多攒几天再来。", parent=self)
            return
        text = "\n".join(lines)
        win = tk.Toplevel(self)
        win.title(kind)
        win.configure(bg=C["card"])
        win.geometry("560x460")
        win.transient(self)
        tf = tk.Frame(win, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"], padx=12, pady=10, bg="#fbfbfc")
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", text)
        txt.configure(state="disabled")

        def copy() -> None:
            self._to_clipboard(text)
            self._set_status(f"已复制{kind}，去 X 粘贴发布。", "ok")
        bar = tk.Frame(win, bg=C["card"])
        bar.pack(fill="x", padx=12, pady=(0, 10))
        ttk.Button(bar, text="复制", command=copy).pack(side="right")
        ttk.Button(bar, text="关闭", command=win.destroy).pack(side="right", padx=(0, 8))

    # —— 昨日复盘 ——
    def _build_review_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="昨日复盘")
        pw = ttk.PanedWindow(f, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=10, pady=10)
        left = tk.Frame(pw, bg=C["card"])
        right = tk.Frame(pw, bg=C["card"])
        pw.add(left, weight=2)
        pw.add(right, weight=3)
        placed = []

        def place_sash() -> None:                      # 第一次显示这一页时，把分隔线放在 40% 处（否则右边的明细会被挤没）
            w = pw.winfo_width()
            if not placed and w > 300:
                pw.sashpos(0, int(w * 0.40))
                placed.append(1)

        f.bind("<Map>", lambda e: self.after(30, place_sash))

        top = ttk.LabelFrame(left, text="昨日赛果概况（来自最新数据表）")
        top.pack(fill="x", pady=(0, 8))
        self.yest_lbl = tk.Label(top, text="还没有数据。点「一键更新」。", bg=C["card"], fg=C["head"], font=self.f_ui, anchor="nw", justify="left")
        self.yest_lbl.pack(fill="x", padx=10, pady=8)
        top.bind("<Configure>", lambda e: self.yest_lbl.configure(wraplength=max(240, e.width - 30)))

        ttk.Button(left, text="查看所选日期当天发出的推文原文", command=self.show_day_posts).pack(side="bottom", fill="x", pady=(8, 0))
        mid = ttk.LabelFrame(left, text="推单战绩（命中 / 已出结果）")
        mid.pack(fill="both", expand=True)
        cols = ("play", "yest", "recent", "all")
        sf = tk.Frame(mid, bg=C["card"])
        sf.pack(fill="both", expand=True, padx=8, pady=(8, 2))
        self.stats = ttk.Treeview(sf, columns=cols, show="headings", height=4, selectmode="none")
        for c, t, w in (("play", "玩法", 88), ("yest", "昨日推单", 96), ("recent", "近7日", 96), ("all", "累计", 110)):
            self.stats.heading(c, text=t)
            self.stats.column(c, width=w, anchor="w" if c == "play" else "center")
        ssb = ttk.Scrollbar(sf, command=self.stats.yview)
        self.stats.configure(yscrollcommand=ssb.set)
        self.stats.pack(side="left", fill="both", expand=True)
        ssb.pack(side="right", fill="y")
        self.stats_note = tk.Label(mid, text="", bg=C["card"], fg=C["muted"], font=self.f_small, anchor="nw", justify="left")
        self.stats_note.pack(fill="x", padx=10, pady=(2, 8))
        mid.bind("<Configure>", lambda e: self.stats_note.configure(wraplength=max(240, e.width - 30)))

        low = ttk.LabelFrame(right, text="推单明细")
        low.pack(fill="both", expand=True)
        bar = tk.Frame(low, bg=C["card"])
        bar.pack(fill="x", padx=10, pady=(8, 4))
        tk.Label(bar, text="日期：", bg=C["card"], font=self.f_ui).pack(side="left")
        self.cmb_date = ttk.Combobox(bar, state="readonly", width=12)
        self.cmb_date.pack(side="left")
        self.cmb_date.bind("<<ComboboxSelected>>", lambda e: self._fill_details())
        tk.Label(bar, text="   显示：", bg=C["card"], font=self.f_ui).pack(side="left")
        self.filter_var = tk.StringVar(value="all")
        for text, val in (("全部", "all"), ("命中", "hit"), ("未中", "miss"), ("待开奖", "pending")):
            ttk.Radiobutton(bar, text=text, value=val, variable=self.filter_var, command=self._fill_details).pack(side="left", padx=(4, 0))
        self.detail_count = tk.Label(low, text="", bg=C["card"], fg=C["muted"], font=self.f_ui, anchor="w")
        self.detail_count.pack(fill="x", padx=12, pady=(0, 4))
        tf = tk.Frame(low, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        cols = ("play", "no", "match", "pick", "cp", "result", "status")
        self.tree = ttk.Treeview(tf, columns=cols, show="headings", selectmode="browse")
        for c, t, w, a, st in (("play", "玩法", 112, "w", False), ("no", "场次", 76, "center", False), ("match", "对阵", 130, "w", True),
                               ("pick", "推荐", 84, "w", False), ("cp", "综合概率", 70, "center", False), ("result", "赛果", 108, "w", False),
                               ("status", "状态", 66, "center", False)):
            self.tree.heading(c, text=t)
            self.tree.column(c, width=w, anchor=a, stretch=st)
        sb = ttk.Scrollbar(tf, command=self.tree.yview)
        self.tree.configure(yscrollcommand=sb.set)
        self.tree.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.tree.tag_configure("hit", background=C["hit_bg"])
        self.tree.tag_configure("miss", background=C["miss_bg"])
        self.tree.tag_configure("pending", foreground=C["muted"])
        self.tree.tag_configure("void", foreground="#9ca3af")

    # —— 人工修正 ——
    def _build_manual_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="人工修正")
        tk.Label(f, justify="left", anchor="w", bg=C["card"], fg=C["head"], font=self.f_ui,
                 text="程序默认只看赔率；在「设置」里打开「自动抓两队数据」后，每次还会自动抓两队近况/伤停来对比。\n"
                      "你知道的情况在这里改：保存后，点上面的「只用现有数据重新生成」即可。手写的两队对比（match_notes）比自动抓的优先。\n"
                      "被排除的球队：这场不推，胜负彩改成 3/1/0 全包，任选九也不选它。").pack(fill="x", padx=14, pady=(12, 8))
        row = tk.Frame(f, bg=C["card"])
        row.pack(fill="x", padx=14)
        tk.Label(row, text="不想推的球队（写队名里的几个字就行）：", bg=C["card"], font=self.f_ui).pack(side="left")
        self.ent_team = ttk.Entry(row, width=18)
        self.ent_team.pack(side="left", padx=6)
        self.ent_team.bind("<Return>", lambda e: self.add_exclude())
        ttk.Button(row, text="加入排除并保存", command=self.add_exclude).pack(side="left")
        tk.Label(f, text="下面是 manual.json 的内容（高级：也可以手动改胜负彩选项、补推荐，格式看「放入示例」）：", bg=C["card"], fg=C["muted"],
                 font=self.f_small, anchor="w").pack(fill="x", padx=14, pady=(12, 4))
        tf = tk.Frame(f, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=14)
        self.man_txt = tk.Text(tf, font=self.f_mono, wrap="none", undo=True, bd=0, highlightthickness=1, highlightbackground=C["line"], padx=10, pady=8)
        sb = ttk.Scrollbar(tf, command=self.man_txt.yview)
        self.man_txt.configure(yscrollcommand=sb.set)
        self.man_txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        bar = tk.Frame(f, bg=C["card"])
        bar.pack(fill="x", padx=14, pady=10)
        ttk.Button(bar, text="保存", command=self.save_manual).pack(side="left")
        ttk.Button(bar, text="放入示例", command=self.fill_example).pack(side="left", padx=6)
        ttk.Button(bar, text="全部清空（删除 manual.json）", command=self.clear_manual).pack(side="left")
        self.man_msg = tk.Label(bar, text="", bg=C["card"], fg=C["muted"], font=self.f_ui, anchor="w", justify="left")
        self.man_msg.pack(side="left", padx=12)

    # —— 运行日志 ——
    def _build_log_tab(self) -> None:
        f = tk.Frame(self.nb, bg=C["card"])
        self.nb.add(f, text="运行日志")
        tf = tk.Frame(f, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=10, pady=(10, 4))
        self.log = tk.Text(tf, font=self.f_mono, wrap="word", bd=0, highlightthickness=1, highlightbackground=C["line"], padx=10, pady=8,
                           bg="#0f172a", fg="#e5e7eb", insertbackground="white", state="disabled")
        sb = ttk.Scrollbar(tf, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        self.log.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.log.tag_configure("warn", foreground="#fbbf24")
        self.log.tag_configure("bad", foreground="#f87171")
        self.log.tag_configure("head", foreground="#93c5fd", font=(self.f_mono[0], 10, "bold"))
        self.log.tag_configure("ok", foreground="#86efac")
        bar = tk.Frame(f, bg=C["card"])
        bar.pack(fill="x", padx=10, pady=(0, 10))
        ttk.Button(bar, text="清空日志", command=lambda: self._set_text(self.log, "")).pack(side="left")

    # ════════════════════════════════════════════════════════════════════
    # 小工具
    # ════════════════════════════════════════════════════════════════════
    @staticmethod
    def _set_text(widget: "tk.Text", text: str) -> None:
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _safe(self, fn, *a) -> None:
        try:
            fn(*a)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("出错了", str(exc), parent=self)

    def _relink_schedule(self) -> None:
        """搬家后，Windows 任务计划里记的还是旧位置：已经设置过「每天自动运行」的，按原来的时间重新登记一次（后台做，不卡界面）。"""
        if not sys.platform.startswith("win"):
            return
        t = str(self.settings.get("sched_time", "15:00"))

        def work() -> None:
            try:
                if sched_exists():
                    sched_create(t)
            except Exception:  # noqa: BLE001
                pass
        threading.Thread(target=work, daemon=True).start()

    def _set_status(self, text: str, kind: str = "muted") -> None:
        self.status.configure(text=text, fg=C.get(kind, C["muted"]))

    def _append_log(self, text: str) -> None:
        tag = ""
        if "⚠" in text or "警告" in text:
            tag = "warn"
        elif re.search(r"失败|出错|错误|Error|Traceback|异常", text):
            tag = "bad"
        elif text.startswith("▶") or text.startswith("——"):
            tag = "head"
        elif text.startswith("✔"):
            tag = "ok"
        self.log.configure(state="normal")
        self.log.insert("end", text.rstrip("\n") + "\n", tag)
        if int(self.log.index("end-1c").split(".")[0]) > 4000:
            self.log.delete("1.0", "1000.0")
        self.log.see("end")
        self.log.configure(state="disabled")

    def _on_tk_error(self, exc, val, tb) -> None:
        msg = "".join(traceback.format_exception(exc, val, tb))
        try:
            with open(ERRLOG, "a", encoding="utf-8") as fh:
                fh.write(f"[{beijing_now():%Y-%m-%d %H:%M:%S}]\n{msg}\n")
        except OSError:
            pass
        self._append_log("⚠ 界面内部出错（不影响数据，详情见 console_error.log）：\n" + msg)

    # ════════════════════════════════════════════════════════════════════
    # 设置
    # ════════════════════════════════════════════════════════════════════
    def _save_settings(self) -> None:
        try:
            self.G.atomic_write(SETTINGS, json.dumps(self.settings, ensure_ascii=False, indent=1))
        except OSError:
            pass

    def _on_mode(self) -> None:
        self.settings["limit"] = 280 if self.mode_var.get() == "280" else self.G.DEFAULT_LIMIT
        self._save_settings()
        if self.result and self.result.get("blocks") and not self.busy:
            self._set_status("字数模式已改。点「只用现有数据重新生成」，帖子会按新模式重新拆分。", "warn")

    def open_settings(self) -> None:
        win = tk.Toplevel(self)
        win.title("设置")
        win.configure(bg=C["card"])
        win.transient(self)
        win.resizable(False, False)
        auto = tk.BooleanVar(value=bool(self.settings.get("auto")))
        daily = tk.BooleanVar(value=bool(self.settings.get("daily")))
        dtime = tk.StringVar(value=str(self.settings.get("daily_time", "15:00")))
        proxy = tk.StringVar(value=str(self.settings.get("proxy", "")))
        bf = tk.BooleanVar(value=bool(self.settings.get("backfill", True)))
        pfull = tk.BooleanVar(value=bool(self.settings.get("post_full")))
        pimg = tk.BooleanVar(value=bool(self.settings.get("post_images")))
        tdon = tk.BooleanVar(value=bool(self.settings.get("team_data")))
        mkon = tk.BooleanVar(value=bool(self.settings.get("market", True)))
        src0 = str(self.settings.get("td_source") or ("both" if read_key() else "sina"))
        srcv = tk.StringVar(value=src0 if src0 in ("sina", "both", "api") else "sina")
        keyv = tk.StringVar(value=read_key())
        showkey = tk.BooleanVar(value=False)
        stime = tk.StringVar(value=str(self.settings.get("sched_time", "15:00")))
        pad = dict(padx=16, anchor="w")
        nb = ttk.Notebook(win)
        nb.pack(fill="both", expand=True, padx=12, pady=(12, 0))

        def page(title: str) -> "tk.Frame":
            f = tk.Frame(nb, bg=C["card"])
            nb.add(f, text=title)
            return f

        def note(parent: "tk.Frame", text: str, **kw: Any) -> "tk.Label":
            lb = tk.Label(parent, text=text, bg=C["card"], fg=C["muted"], font=self.f_small, justify="left", wraplength=560)
            lb.pack(**dict(pad, **kw))
            return lb

        # ───────── 第 1 页：更新 ─────────
        p1 = page("更新")
        tk.Label(p1, text="自动更新", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        ttk.Checkbutton(p1, text="打开本软件时自动「一键更新」", variable=auto).pack(**pad)
        row = tk.Frame(p1, bg=C["card"])
        row.pack(pady=(6, 0), **pad)
        ttk.Checkbutton(row, text="软件开着时，每天定时自动更新，时间（北京时间 时:分）：", variable=daily).pack(side="left")
        ttk.Entry(row, textvariable=dtime, width=7).pack(side="left", padx=6)
        note(p1, "这一项只在软件开着的时候才会执行。想让电脑到点自己打开软件更新，用「每天自动运行」那一页。")
        tk.Label(p1, text="漏更新的日子", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        ttk.Checkbutton(p1, text="某天忘了更新时，自动补抓那天的赛果，把当天的推单结算掉", variable=bf).pack(**pad)
        note(p1, "补抓多花约半分钟/天；最多往前补 3 天，更早的推单按作废处理。")
        tk.Label(p1, text="推文样式", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        ttk.Checkbutton(p1, text="用详细版：每篇都带昨日复盘，每场推单下面附两队数据对比", variable=pfull).pack(**pad)
        note(p1, "不勾（默认）：每篇只有推单本身，可以直接复制去发；昨日复盘单独一篇放最后，两队数据对比放在「推单文案」文件末尾备查。")
        ttk.Checkbutton(p1, text="更新完成后，自动给每条帖子生成图片快照（要电脑里有 Edge 或 Chrome，多花约半分钟）", variable=pimg).pack(pady=(8, 0), **pad)
        note(p1, "不勾也行：想要图片时，在「今日推单」页点「生成图片快照」。图片存在软件文件夹的「推单图片_日期」里，一条帖子一张（太长的拆成图1、图2）。")
        tk.Label(p1, text="网络代理（可留空）", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        ttk.Entry(p1, textvariable=proxy, width=44).pack(**pad)
        note(p1, "抓取不到数据、又需要代理时才填，例如 http://127.0.0.1:7890", pady=(0, 14))

        # ───────── 第 2 页：两队数据 ─────────
        p2 = page("两队数据")
        tk.Label(p2, text="每场推单都对比两队真实数据", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        ttk.Checkbutton(p2, text="每次生成推单前，自动抓两队近况、伤停、交锋，和推单方向对比", variable=tdon).pack(**pad)
        note(p2, "数据支持的才推；数据反对的不推；没查到数据的场次也不推（不编数据）。")
        ttk.Checkbutton(p2, text="再读澳客赔率（okooo.cn）：补市场共识；竞足没配上北单也能推", variable=mkon).pack(**pad)
        tk.Label(p2, text="数据从哪里来", bg=C["card"], font=self.f_bold).pack(pady=(10, 2), **pad)
        for text, val in (("新浪彩票公开文章（免费，不用注册、不用密钥）　← 推荐", "sina"),
                          ("新浪优先；新浪没有的比赛用接口补　（要接口密钥）", "both"),
                          ("只用接口 API-Football　（要接口密钥；免费版只有近况，没有伤停）", "api")):
            ttk.Radiobutton(p2, text=text, value=val, variable=srcv).pack(**dict(pad, pady=1))
        note(p2, "新浪的文章是自由文字，脚本靠规则认字，偶尔会漏读；读不到的场次会在运行提示里列出来，也不会乱推。"
                 "另外脚本每天会存下昨日已开奖的比分，攒够了，没有文章的比赛也能自己算近况；竞篮（篮球）用脚本自己攒的篮球比分算，不靠新浪。", pady=(4, 0))
        krow = tk.Frame(p2, bg=C["card"])
        krow.pack(pady=(8, 0), **pad)
        tk.Label(krow, text="接口密钥（只有选了接口才要）：", bg=C["card"], font=self.f_ui).pack(side="left")
        kent = ttk.Entry(krow, textvariable=keyv, width=30, show="•")
        kent.pack(side="left", padx=4)
        ttk.Checkbutton(krow, text="显示", variable=showkey,
                        command=lambda: kent.configure(show="" if showkey.get() else "•")).pack(side="left")
        brow = tk.Frame(p2, bg=C["card"])
        brow.pack(pady=(6, 0), **pad)
        btn_test = ttk.Button(brow, text="测试连接")
        btn_test.pack(side="left")
        ttk.Button(brow, text="打开接口注册页面", command=lambda: webbrowser.open(KEY_URL)).pack(side="left", padx=8)
        rbox = tk.Frame(p2, bg=C["card"])
        rbox.pack(padx=16, pady=(6, 14), anchor="w")
        res = tk.Text(rbox, height=12, width=70, wrap="word", font=self.f_small, bg="#f9fafb", relief="flat", highlightthickness=1,
                      highlightbackground=C["line"])
        rsb = ttk.Scrollbar(rbox, orient="vertical", command=res.yview)
        res.configure(yscrollcommand=rsb.set)
        res.pack(side="left")
        rsb.pack(side="left", fill="y")
        res.tag_configure("bad", foreground=C["bad"])
        res.tag_configure("ok", foreground=C["ok"])
        res.tag_configure("head", font=self.f_bold)

        def show(lines: List[str]) -> None:
            res.configure(state="normal")
            res.delete("1.0", "end")
            for ln in lines:
                st = ln.lstrip()
                tag = "bad" if st.startswith(("✖", "✘")) else "ok" if st.startswith("✔") else "head" if ln.startswith("【") else ""
                res.insert("end", ln + "\n", tag)
            res.configure(state="disabled")

        show(["点「测试连接」，看看现在能不能取到两队数据。", "（新浪的测试会读 3～5 个网页，约 10 秒；接口的测试会用掉 3～4 次接口请求。）"])

        def test() -> None:
            k = clean_key(keyv.get())
            src = srcv.get()
            if k and not key_ok(k):
                show(["✖ 接口密钥格式不对（只含字母和数字，注册后在网站的 Dashboard 页面复制）。"])
                return
            btn_test.configure(state="disabled")
            show(["正在测试……"])
            box: Dict[str, Any] = {}
            px = proxy.get().strip()                   # 界面变量只能在主线程里读，先取出来再交给后台线程

            def job() -> None:
                try:
                    box["lines"] = self.G.check_data(APP_DIR, k, src, proxy=px)
                except Exception as exc:  # noqa: BLE001
                    box["lines"] = [f"✖ 出错：{exc}"]

            threading.Thread(target=job, daemon=True).start()

            def poll() -> None:
                if not win.winfo_exists():
                    return
                if "lines" in box:
                    show(box["lines"])
                    btn_test.configure(state="normal")
                else:
                    win.after(150, poll)

            poll()

        btn_test.configure(command=test)

        # ───────── 第 3 页：每天自动运行 ─────────
        p3 = page("每天自动运行")
        tk.Label(p3, text="让电脑到点自己更新", bg=C["card"], font=self.f_bold).pack(pady=(14, 4), **pad)
        note(p3, "到点，Windows 的「任务计划」会自动打开本软件，抓数据、复盘昨日、生成今日推单；你回来直接去「今日推单」页复制就行。\n"
                 "要求：电脑开着、已登录（睡眠或关机时不会执行）。错过了也没事：开机后点一次「一键更新」，会自动补上漏掉的日子。")
        srow = tk.Frame(p3, bg=C["card"])
        srow.pack(pady=(8, 0), **pad)
        tk.Label(srow, text="每天几点（时:分，北京时间）：", bg=C["card"], font=self.f_ui).pack(side="left")
        ttk.Entry(srow, textvariable=stime, width=7).pack(side="left", padx=6)
        btn_on = ttk.Button(srow, text="设置每天自动运行")
        btn_on.pack(side="left", padx=(8, 0))
        btn_off = ttk.Button(srow, text="取消自动运行")
        btn_off.pack(side="left", padx=8)
        sched_msg = tk.Label(p3, text="", bg=C["card"], fg=C["muted"], font=self.f_small, justify="left", wraplength=560)
        sched_msg.pack(pady=(8, 14), **pad)
        is_win = sys.platform.startswith("win")
        if not is_win:
            sched_msg.configure(text="这一项只在 Windows 上可用（用 Windows 的任务计划）。")
            btn_on.configure(state="disabled")
            btn_off.configure(state="disabled")
        else:
            sched_msg.configure(text="正在查看当前状态……")
            sbox: Dict[str, Any] = {}
            threading.Thread(target=lambda: sbox.update(on=sched_exists()), daemon=True).start()

            def sched_poll() -> None:
                if not win.winfo_exists():
                    return
                if "on" in sbox:
                    sched_msg.configure(text=(f"✔ 已设置：每天 {self.settings.get('sched_time', '')} 自动运行。" if sbox["on"]
                                              else "还没有设置每天自动运行。"), fg=C["ok"] if sbox["on"] else C["muted"])
                else:
                    win.after(150, sched_poll)

            sched_poll()

        def sched_on() -> None:
            t = stime.get().strip()
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                sched_msg.configure(text="✖ 时间要写成 时:分，例如 15:00", fg=C["bad"])
                return
            if not Path(__file__).exists():
                sched_msg.configure(text="✖ 找不到 tips_console.pyw", fg=C["bad"])
                return
            ok_, out = sched_create(t)
            if ok_:
                self.settings["sched_time"] = t
                self._save_settings()
                sched_msg.configure(text=f"✔ 已设置：每天 {t} 自动打开操作台并更新。（到点要是软件已经开着，就直接在这个窗口里更新。）", fg=C["ok"])
            else:
                sched_msg.configure(text="✖ 没设置成功：" + (out or "Windows 没有说明原因") +
                                    "\n可以试试「用管理员身份运行」本软件后再点一次。", fg=C["bad"])

        def sched_off() -> None:
            if not sched_exists():
                sched_msg.configure(text="本来就没有设置每天自动运行。", fg=C["muted"])
                return
            ok_, out = sched_delete()
            sched_msg.configure(text="✔ 已取消每天自动运行。" if ok_ else "✖ 没取消成功：" + (out or ""), fg=C["ok"] if ok_ else C["bad"])

        btn_on.configure(command=sched_on)
        btn_off.configure(command=sched_off)

        def ok() -> None:
            t = dtime.get().strip()
            try:
                datetime.strptime(t, "%H:%M")
            except ValueError:
                messagebox.showerror("时间格式不对", "定时更新的时间要写成 时:分，例如 15:00", parent=win)
                return
            k = clean_key(keyv.get())
            if k and not key_ok(k):
                messagebox.showerror("密钥格式不对", "接口密钥只含字母和数字，请重新到网站 Dashboard 页面复制（不要带多余的字）。", parent=win)
                return
            if tdon.get() and srcv.get() in ("api", "both") and not k:
                messagebox.showerror("还没填密钥", "选了「接口」就需要接口密钥。\n点「打开接口注册页面」免费注册一个；\n只想用新浪的话，选第一项就不用密钥。", parent=win)
                return
            try:
                if k and k != read_key():
                    self.G.atomic_write(KEYFILE, k + "\n")
                elif not k and KEYFILE.exists():
                    KEYFILE.unlink()
            except OSError as exc:
                messagebox.showerror("密钥没能保存", f"写不了 api_key.txt：{exc}", parent=win)
                return
            self.settings.update(auto=auto.get(), daily=daily.get(), daily_time=t, proxy=proxy.get().strip(), backfill=bf.get(),
                                 team_data=tdon.get(), td_source=srcv.get(), post_full=pfull.get(), market=mkon.get(),
                                 post_images=pimg.get())
            self._save_settings()
            win.destroy()
            self._set_status("设置已保存。", "ok")

        bar = tk.Frame(win, bg=C["card"])
        bar.pack(fill="x", padx=18, pady=14)
        ttk.Button(bar, text="保存", command=ok).pack(side="right")
        ttk.Button(bar, text="取消", command=win.destroy).pack(side="right", padx=8)
        win.update_idletasks()
        win.geometry(f"+{self.winfo_x() + 120}+{self.winfo_y() + 70}")
        win.grab_set()

    # ════════════════════════════════════════════════════════════════════
    # 一键更新
    # ════════════════════════════════════════════════════════════════════
    def start_update(self, fetch: bool, manual: bool = True, retry_only: bool = False) -> None:
        if self.busy:
            return
        if fetch and not EXPORT.exists():
            messagebox.showerror("缺文件", "找不到 export_500_all.py。请把它放进本软件所在的文件夹。", parent=self)
            return
        self.busy, self.manual_run = True, manual
        self.cancel.clear()
        self._set_busy(True)
        self._set_step(0, "skip" if not fetch else "idle")
        self._set_step(1, "idle")
        self._set_step(2, "idle")
        self._append_log(f"—— {beijing_now():%Y-%m-%d %H:%M:%S} " + ("一键更新" if fetch else "用现有数据重新生成") + " ——")
        self._set_status("正在抓取数据…（一般 20～60 秒）" if fetch else "正在用现有数据重新生成…", "accent_dark")
        threading.Thread(target=self._worker, args=(fetch, retry_only), daemon=True).start()

    def retry_failed(self) -> None:
        if self.busy:
            return
        summary = L.d(APP_DIR, L.DAY) / "采集摘要.json"
        if not summary.exists():
            self._set_status("还没有采集摘要，请先一键更新。", "warn")
            return
        self.start_update(True, retry_only=True)

    def start_history(self, days: int = 30) -> None:
        """补历史赛果：读 500 网「完场」页，补最近 days 天的全部比分，存进赛果库（没有新浪文章的比赛靠它算近况）。只做一次就行。"""
        if self.busy:
            return
        if not messagebox.askyesno("补历史赛果", f"会去 500 网的「完场比分」页，读最近 {days} 天的全部比分（每天 200 多场，各个联赛都有），存进「赛果库」。\n"
                                   "这样没有新浪文章的比赛，也能用两队最近的比分算近况。\n\n"
                                   "大约 1～3 分钟，期间别关窗口（可以点「停止」）。只需要做一次，之后每天更新会自动继续攒。\n\n现在开始吗？", parent=self):
            return
        self.busy, self.manual_run = True, True
        self.cancel.clear()
        self._set_busy(True)
        self._append_log(f"—— {beijing_now():%Y-%m-%d %H:%M:%S} 补历史赛果（最近 {days} 天） ——")
        self._set_status(f"正在补历史赛果…（读 500 网完场页，最近 {days} 天，约 1～3 分钟）", "accent_dark")
        threading.Thread(target=self._history_worker, args=(days,), daemon=True).start()

    def _history_worker(self, days: int) -> None:
        q = self.q
        try:
            proxy = str(self.settings.get("proxy", "")).strip()
            res = self.G.wanchang_history(APP_DIR, days, log=lambda m: q.put(("log", m)), cancel=self.cancel.is_set, proxy=proxy)
            if self.cancel.is_set():
                q.put(("fail", "已停止。"))
                return
            if res["ok"] or res["skipped"]:
                cov = self.G.coverage_text(APP_DIR)
                span = f"（{res['span']}）" if res["span"] else ""
                skip = f"，另有 {res['skipped']} 天之前补过、跳过" if res["skipped"] else ""
                bad = f" 有 {len(res['errors'])} 天没读到，再点一次会补上。" if res["errors"] else ""
                q.put(("ok", f"补历史赛果完成：读了 {res['ok']} 页，新存 {res['added']} 场{skip}，赛果库共 {res['total']} 场{span}。{bad}{cov}"))
                return
            q.put(("log", "⚠ 完场页没读成" + (f"：{res['errors'][0]}" if res["errors"] else "") + "。改用旧办法：抓竞彩赛果（约 3～10 分钟）"))
            if not EXPORT.exists():
                q.put(("fail", "完场页没读成，旧办法又缺 export_500_all.py。检查网络/代理后再点一次「补历史赛果」。"))
                return
            q.put(("status", f"完场页没读成，改用旧办法抓竞彩赛果…（最近 {days} 天，约 3～10 分钟）"))
            err = self._fetch(hist=days)
            if err:
                q.put(("fail", err))
                return
            out = BACKFILL_DIR / f"历史赛果_{beijing_now():%Y-%m-%d}.xlsx"
            if not out.exists():
                q.put(("fail", "抓取结束了，但没有生成历史赛果表。看看「运行日志」页里抓取脚本说了什么。"))
                return
            read, added, total, span = self.G.store_history(APP_DIR, out, say=lambda m: q.put(("log", m)))
            if not read:
                q.put(("fail", "抓到了表，但里面没有已踢完的比分（可能 500 网这几天的页面读不到）。运行日志里能看到每一天的情况。"))
                return
            q.put(("ok", f"补历史赛果完成（旧办法）：新存 {added} 场，赛果库共 {total} 场（{span}）。之后每天的更新会自动继续攒。"))
        except Exception:  # noqa: BLE001
            q.put(("log", traceback.format_exc()))
            q.put(("fail", "补历史赛果出错了（详细信息在「运行日志」页）：" + traceback.format_exc().strip().splitlines()[-1]))
        finally:
            q.put(("end",))

    def stop(self) -> None:
        if not self.busy:
            return
        self.cancel.set()
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        self._set_status("正在停止…", "warn")

    def _set_busy(self, busy: bool) -> None:
        self.btn_go.configure(state="disabled" if busy else "normal", bg=C["accent_off"] if busy else C["accent"])
        self.btn_regen.configure(state="disabled" if busy else "normal")
        self.btn_retry.configure(state="disabled" if busy else "normal")
        self.btn_hist.configure(state="disabled" if busy else "normal")
        if getattr(self, "btn_img", None) is not None:
            self.btn_img.configure(state="disabled" if (busy or self.img_busy) else "normal")
        self.btn_stop.configure(state="normal" if busy else "disabled")
        if busy:
            self.bar.configure(mode="indeterminate")
            self.bar.start(12)
        else:
            self.bar.stop()
            self.bar.configure(mode="determinate", value=0)

    def _set_step(self, i: int, state: str) -> None:
        name = self.STEPS[i]
        style = {"idle": (name, C["muted"], self.f_ui), "run": (name + " …", C["accent"], self.f_bold),
                 "ok": ("✔ " + name[2:], C["ok"], self.f_bold), "fail": ("✖ " + name[2:], C["bad"], self.f_bold),
                 "skip": (name + "（跳过）", C["muted"], self.f_ui)}[state]
        self.step_lbls[i].configure(text=style[0], fg=style[1], font=style[2])

    # —— 后台线程：只往队列里放消息，不碰窗口 ——
    def _worker(self, fetch: bool, retry_only: bool = False) -> None:
        q, G = self.q, self.G
        try:
            t0 = time.time()
            if fetch:
                q.put(("step", 0, "run"))
                err = self._fetch(retry_only=retry_only)
                if err:
                    q.put(("step", 0, "fail"))
                    q.put(("fail", err))
                    return
                q.put(("step", 0, "ok"))
            xlsx = newest_xlsx()
            if xlsx is None:
                q.put(("fail", "文件夹里还没有 500网数据_日期.xlsx。请先点「一键更新」抓取数据。"))
                return
            if fetch:
                expected = L.d(APP_DIR, L.DAY) / f"500网数据_{beijing_now():%Y-%m-%d}.xlsx"
                if not expected.exists() or expected.stat().st_mtime < t0 - 5:
                    raise G.TipsError("本次未产生今日的新数据表，已停止生成；可手动选择现有数据重新生成。")
                xlsx = expected
                G.validate_live_workbook(G.read_workbook(xlsx), expected_day=f"{beijing_now():%Y-%m-%d}")
            q.put(("log", f"▶ 使用数据表：{xlsx.name}"))
            q.put(("step", 1, "run"))

            def on_log(msg: str) -> None:              # run() 在「结算完」和「开始生成」之间会报一行「今日销售日…」
                q.put(("log", msg))
                if "补抓" in msg and "失败" not in msg:
                    q.put(("status", "正在补抓漏掉那天的赛果，好把它的推单结算掉…（每天约半分钟）"))
                if msg.startswith("今日销售日"):
                    q.put(("step", 1, "ok"))
                    q.put(("step", 2, "run"))
                    q.put(("status", "正在生成今日推单…"))
                if msg.startswith("读 500 网完场页"):
                    q.put(("status", "正在读 500 网完场页，攒两队近况用的比分…（平时几秒；第一次会补 30 天，约 1～3 分钟）"))
                if msg.startswith("自动抓取两队数据"):
                    q.put(("status", "正在抓取两队真实数据…（读新浪文章/接口，可能要几分钟，请不要关窗口；读过的会缓存）"))

            def backfill(day: str) -> Optional[Path]:  # 漏更新的日子：抓那天的第二天的表，里面的「昨日已开奖」就是那天的赛果
                if not EXPORT.exists():
                    return None
                err = self._fetch(day)
                if self.cancel.is_set():
                    raise G.TipsError("已停止。")
                if err:
                    q.put(("log", "⚠ " + err))
                    return None
                out = BACKFILL_DIR / f"500网数据_{day}.xlsx"
                return out if out.exists() else None

            td = None
            if self.settings.get("team_data"):
                td = G.make_team_data(APP_DIR, "", log=on_log, cancel=self.cancel.is_set, proxy=str(self.settings.get("proxy", "")).strip(),
                                      source=str(self.settings.get("td_source") or "auto"))
            mkt_cb = (G.make_market(APP_DIR, log=on_log, cancel=self.cancel.is_set, proxy=str(self.settings.get("proxy", "")).strip())
                      if self.settings.get("market", True) else None)

            def fill_results(say) -> None:             # 存完昨日比分后：读 500 网完场页，把前几天的全部比分也存进赛果库
                G.wanchang_daily(APP_DIR, log=say, cancel=self.cancel.is_set, proxy=str(self.settings.get("proxy", "")).strip())
                if self.cancel.is_set():
                    raise G.TipsError("已停止。")

            res = G.run(xlsx, HISTORY, MANUAL if MANUAL.exists() else None, limit=int(self.settings.get("limit", 280)),
                        fresh=True, output=APP_DIR, log=on_log, backfill=backfill if self.settings.get("backfill", True) else None,
                        fill_results=fill_results if self.settings.get("wanchang", True) else None, team_data=td,
                        style="full" if self.settings.get("post_full") else "media", market=mkt_cb,
                        images=bool(self.settings.get("post_images")), browser=str(self.settings.get("browser", "")).strip(),
                        cancel=self.cancel.is_set, esports_proxy=str(self.settings.get("proxy", "")).strip())
            q.put(("step", 2, "ok"))
            q.put(("done", res, fetch))
        except G.TipsError as exc:
            hint = "（数据表是不是还开着 Excel？先关掉再试）" if "Permission" in str(exc) or "拒绝访问" in str(exc) else ""
            q.put(("fail", str(exc) + hint))
        except Exception:  # noqa: BLE001
            q.put(("log", traceback.format_exc()))
            q.put(("fail", "出错了（详细信息在「运行日志」页）：" + traceback.format_exc().strip().splitlines()[-1]))
        finally:
            q.put(("end",))

    def _fetch(self, day: Optional[str] = None, hist: int = 0, retry_only: bool = False) -> str:
        """运行 export_500_all.py；成功返回空字符串，失败返回要给用户看的原因。
        day 不为空：补抓模式——以 day 为「今日」抓一遍，表存进 backfill 文件夹（里面的「昨日已开奖」就是 day 前一天的赛果）。"""
        q = self.q
        env = dict(os.environ, PYTHONIOENCODING="utf-8", PYTHONUTF8="1")
        proxy = str(self.settings.get("proxy", "")).strip()
        if proxy:
            env.update(HTTP_PROXY=proxy, HTTPS_PROXY=proxy, http_proxy=proxy, https_proxy=proxy)
            q.put(("log", f"使用代理：{proxy}"))
        cmd = [child_python(), "-u", str(EXPORT), "--keep-older-draws"]
        if hist:                                   # 补历史赛果：full 模式一次抓最近 hist 个销售日的竞彩足球赛果
            out = BACKFILL_DIR / f"历史赛果_{beijing_now():%Y-%m-%d}.xlsx"
            try:
                BACKFILL_DIR.mkdir(exist_ok=True)
                if out.exists():
                    out.unlink()
            except OSError as exc:
                return f"补历史用的文件夹不能写：{exc}"
            cmd = [child_python(), "-u", str(EXPORT), "--mode", "full", "--days", str(hist), "--output", str(out), "--no-reuse-previous"]
            q.put(("log", f"▶ 补历史赛果：export_500_all.py --mode full --days {hist}（约 3～10 分钟）"))
        elif day:
            out = BACKFILL_DIR / f"500网数据_{day}.xlsx"
            try:
                BACKFILL_DIR.mkdir(exist_ok=True)
                if out.exists():
                    out.unlink()                       # 不让它「沿用上次」的旧内容
            except OSError as exc:
                return f"补抓用的文件夹不能写：{exc}"
            cmd += ["--date", day, "--output", str(out), "--no-reuse-previous"]
            q.put(("log", f"▶ 补抓 {day}：export_500_all.py --date {day}"))
        else:
            q.put(("log", "▶ 开始抓取：export_500_all.py --keep-older-draws"))
        summary = L.d(APP_DIR, L.DAY) / "采集摘要.json"
        if not day and not hist:
            cmd += ["--summary-json", str(summary)]
            if retry_only:
                cmd += ["--retry-failed", str(summary)]
        try:
            proc = subprocess.Popen(cmd, cwd=str(L.d(APP_DIR, L.DAY)), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                    text=True, encoding="utf-8", errors="replace", env=env,
                                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as exc:
            return f"没能启动抓取脚本：{exc}"
        self.proc = proc
        timed_out = threading.Event()
        def expire():
            timed_out.set()
            try:
                proc.terminate()
            except OSError:
                pass
        timer = threading.Timer(EXPORT_TIMEOUT * (3 if hist else 1), expire)
        timer.start()
        try:
            assert proc.stdout is not None
            for line in proc.stdout:
                if line.strip():
                    q.put(("log", line.rstrip()))
            rc = proc.wait()
        finally:
            timer.cancel()
            self.proc = None
        if self.cancel.is_set():
            return "已停止。"
        if timed_out.is_set():
            return "抓取超时，已终止任务；本次不会用旧表继续生成。"
        if rc not in (0, 1):
            why = {2: "这次没有取到任何新数据", 3: "抓取脚本写不出文件或内部出错"}.get(rc, f"抓取脚本异常退出（代码 {rc}）")
            if hist:
                return f"补历史赛果失败：{why}。网络通了以后再点一次「补历史赛果」。"
            if day:
                return f"补抓 {day} 失败：{why}。这一天的推单先不结算，下次更新会再试。"
            return f"抓取失败：{why}。多半是网络不通——检查网络/代理（右上角「设置」可填代理）后重试；想先用旧数据，点「只用现有数据重新生成」。"
        return ""

    # —— 主线程：每 100 毫秒取一次队列 ——
    def _poll(self) -> None:
        try:
            while True:
                msg = self.q.get_nowait()
                kind = msg[0]
                if kind == "log":
                    self._append_log(msg[1])
                    progress = re.search(r"\[(\d+)/(\d+)\]", msg[1])
                    if progress:
                        done, total = map(int, progress.groups())
                        self.bar.stop()
                        self.bar.configure(mode="determinate", value=100 * done / max(1, total))
                        self._set_status(msg[1], "accent_dark")
                elif kind == "step":
                    self._set_step(msg[1], msg[2])
                elif kind == "status":
                    self._set_status(msg[1], "accent_dark")
                elif kind == "ok":
                    self._append_log("✔ " + msg[1])
                    self._set_status(msg[1], "ok")
                elif kind == "done":
                    self._on_done(msg[1], msg[2])
                elif kind == "fail":
                    self._on_fail(msg[1])
                elif kind == "images":
                    self._on_images(msg[1], msg[2], msg[3])
                elif kind == "end":
                    self.busy = False
                    self._set_busy(False)
        except queue.Empty:
            pass
        self.after(100, self._poll)

    def _on_fail(self, msg: str) -> None:
        for i, lb in enumerate(self.step_lbls):
            if "…" in lb.cget("text"):
                self._set_step(i, "fail")
        self._append_log("✖ " + msg)
        self._set_status(msg, "bad")
        if self.manual_run and not self.cancel.is_set():
            messagebox.showerror("没有更新成功", msg, parent=self)

    def _on_done(self, res: Dict[str, Any], fetched: bool) -> None:
        self.result = res
        self.blocks = res.get("blocks", [])
        res["saved_at"] = beijing_now().strftime("%Y-%m-%d %H:%M")
        try:
            keep = ("day", "xlsx", "settled", "settled_day", "limit", "yesterday", "fetched_at", "collect_issues", "warnings", "blocks",
                    "picks", "txt", "saved_at", "notes", "backfilled", "unsettled_days", "basis", "style", "images",
                    "preflight", "preflight_lines", "deadlines", "drift", "rules_changed", "rules_warns", "timing", "stats_txt",
                    "keywords", "kw_txt", "comments", "cm_txt", "batch_id", "esports", "esports_txt", "posts")
            self.G.atomic_write(LAST, json.dumps({k: res.get(k) for k in keep}, ensure_ascii=False))
        except OSError:
            pass
        if fetched:
            self.settings["last_ok"] = beijing_now().strftime("%Y-%m-%d")
            self._save_settings()
        for w in res.get("collect_issues", []):
            self._append_log("⚠ 采集状态里有失败项（不一定影响推单）：" + w)
        self._render_result(res)
        self._refresh_review()
        self._refresh_stats()
        done = f"更新完成：判定了 {res['settled']} 条已出结果的推单，今日生成 {res['picks']} 条"
        if (res.get("esports") or {}).get("picks"):
            done += f"，另有电竞 {(len(res['esports']['picks']))} 场"
        if res.get("txt"):
            done += f"，文案已存为 {Path(res['txt']).name}"
        left_over = res.get("unsettled_days") or []
        if left_over:
            done += f"。注意：{len(left_over)} 天的推单没能结算，见下面的提示"
        self._append_log("✔ " + done)
        self._set_status(done + "。", "warn" if left_over else "ok")
        self.nb.select(0)

    # ════════════════════════════════════════════════════════════════════
    # 图片快照
    # ════════════════════════════════════════════════════════════════════
    def _current_posts(self) -> "tuple[str, List[tuple]]":
        """今日推单的完整帖子（没拆成 280 字小块的）：先看这次更新带的，没有就去历史里找当天那份。"""
        res = self.result or {}
        day = str(res.get("day") or "")
        posts = [(p["name"], p["text"]) for p in res.get("posts") or []]
        if not posts and day:
            run = self.G.load_history(HISTORY).get("runs", {}).get(day) or {}
            posts = [(p["name"], p["text"]) for p in run.get("posts", [])]
        return day, posts

    def choose_browser(self) -> str:
        if self.busy or self.img_busy:
            self._set_status("正在执行任务，完成后再设置浏览器。", "warn")
            return ""
        path = filedialog.askopenfilename(parent=self, title="选择截图浏览器：chrome.exe 或 msedge.exe",
            filetypes=[("浏览器程序", "*.exe"), ("所有文件", "*")])
        if not path:
            return ""
        import snapshot as SN
        exe = SN.find_browser(path)
        # 必须确认选中项本身有效，不能悄悄用另一个自动检测结果代替。
        if not Path(path).is_file() or not exe or Path(exe).resolve() != Path(path).resolve():
            messagebox.showerror("浏览器路径无效", "请选择浏览器的实际程序文件，不要选快捷方式。", parent=self)
            return ""
        if Path(exe).name.lower() not in ("chrome.exe", "msedge.exe", "chromium.exe", "brave.exe", "chrome", "chromium", "msedge", "google-chrome"):
            messagebox.showerror("不支持此浏览器", "截图需要Chrome、Edge或Chromium，请选择对应程序。", parent=self)
            return ""
        updated = dict(self.settings, browser=exe)
        try:
            self.G.atomic_write(SETTINGS, json.dumps(updated, ensure_ascii=False, indent=1))
        except OSError as exc:
            messagebox.showerror("浏览器设置未保存", str(exc), parent=self)
            return ""
        self.settings = updated
        self._append_log(f"截图浏览器已保存：{exe}")
        self._set_status("浏览器路径已保存，可以生成图片快照。", "ok")
        return exe

    def make_images_now(self) -> None:
        if self.busy or self.img_busy:
            return
        day, posts = self._current_posts()
        if not posts:
            messagebox.showinfo("还没有推单", "先点「一键更新」生成今日推单，再来生成图片。", parent=self)
            return
        import snapshot as SN
        resolved = SN.find_browser(str(self.settings.get("browser", "")))
        if not resolved:
            self._set_status("未找到截图浏览器，请选择chrome.exe或msedge.exe。", "warn")
            resolved = self.choose_browser()
            if not resolved:
                return
        self.img_busy = True
        self.btn_img.configure(state="disabled", text="正在生成图片…")
        self._set_status(f"正在给 {len(posts)} 条帖子生成图片（后台截图，不会弹窗，约 {max(15, 3 * len(posts))} 秒）…", "accent_dark")
        q, G = self.q, self.G
        browser = resolved

        def work() -> None:
            try:
                r = G.make_snapshots(posts, APP_DIR, day, G.load_brand(APP_DIR), log=lambda s: q.put(("log", s)), browser=browser)
            except Exception as exc:  # noqa: BLE001
                q.put(("log", traceback.format_exc()))
                r = {"files": [], "html": None, "dir": "", "error": f"做图时出错：{exc}"}
            q.put(("images", r, len(posts), True))
        threading.Thread(target=work, daemon=True).start()

    def _on_images(self, r: Dict[str, Any], n: int, manual: bool) -> None:
        self.img_busy = False
        self.btn_img.configure(state="normal", text="生成图片快照")
        files, err, folder = r.get("files") or [], r.get("error") or "", r.get("dir") or ""
        if files:
            tot = r.get("total") or n
            self._append_log(f"✔ 图片快照 {len(files)}/{tot} 张已存到 {folder}（{n} 条帖子，太长的拆成了「图1、图2」）")
            self._set_status(f"图片快照 {len(files)}/{tot} 张已生成，文件夹已打开（一条帖子一张，太长的拆成图1、图2，发推时按顺序选图上传）。", "ok" if not err else "warn")
            if folder:
                self._safe(open_in_explorer, Path(folder))
        if err:
            self._append_log("⚠ 图片快照：" + err)
            if not files:
                self._set_status("图片没生成出来：" + err, "bad")
            if manual:
                messagebox.showwarning("图片快照", err, parent=self)
                if not files and r.get("html"):
                    self._safe(open_in_explorer, Path(r["html"]).parent)

    # ════════════════════════════════════════════════════════════════════
    # 显示结果
    # ════════════════════════════════════════════════════════════════════
    def _load_last(self) -> None:
        try:
            res = json.loads(LAST.read_text(encoding="utf-8"))
            if not isinstance(res, dict) or "blocks" not in res:
                return
        except (OSError, ValueError):
            return
        self.result, self.blocks = res, res.get("blocks", [])
        self._render_result(res)
        self._set_status(f"显示的是上次更新（{res.get('saved_at', '?')}）的结果。点「一键更新」获取最新数据。", "muted")

    def _render_result(self, res: Dict[str, Any]) -> None:
        self.cards["day"].configure(text=res.get("day") or "—")
        n_groups = len({b["name"] for b in res.get("blocks", [])})
        self.cards["picks"].configure(text=f"{res.get('picks', 0)} 条 · {n_groups} 组帖子" if res.get("blocks") else "—")
        self._update_fetched_card(res.get("fetched_at", ""))
        self.yest_lbl.configure(text=res.get("yesterday") or "—")
        self._show_link(res)
        self._fill_posts()
        self._show_kw(res.get("keywords"))
        self._show_cm(res.get("comments"))

    def _update_fetched_card(self, fetched: str) -> None:
        if not fetched:
            self.cards["fetched"].configure(text="—", fg=C["head"])
            return
        text, color = fetched[:16], C["head"]
        try:
            age = datetime.now(BJT) - datetime.strptime(fetched, "%Y-%m-%d %H:%M:%S").replace(tzinfo=BJT)
            hours = age.total_seconds() / 3600
            if hours >= STALE_HOURS:
                text += f"（已过{int(hours)}小时，赔率可能变了）"
                color = C["warn"]
        except ValueError:
            pass
        self.cards["fetched"].configure(text=text, fg=color)

    def _show_empty_posts(self) -> None:
        self.lb.delete(0, "end")
        self.blk_info.configure(text="")
        self._set_text(self.txt, "还没有推单。\n\n"
                                 "① 点上面蓝色的「一键更新」按钮；\n"
                                 "② 等几十秒，这里会出现今日各玩法的推单；\n"
                                 "③ 左边选一条帖子，点「复制这条」，去 X 粘贴发布。\n\n"
                                 "明天再点一次，昨天的推单会自动复盘（命中 / 未中）。")
        self.btn_copy.configure(state="disabled", bg=C["accent_off"])

    def _paint_list(self) -> None:
        """左边的帖子列表：名字 + 建议发帖时间（过了的标红）。只重画列表，不动右边的正文。"""
        sel = self.lb.curselection()
        keep = sel[0] if sel else 0
        yview = self.lb.yview()
        self.lb.delete(0, "end")
        lim = int(self.result.get("limit", 280)) if self.result else 280
        dl = self._deadline_map()
        for i, b in enumerate(self.blocks):
            name = b["name"] + (f"（{b['k']}/{b['n']}）" if b["n"] > 1 else "")
            over = "  ⚠" if lim < self.G.DEFAULT_LIMIT and b["weight"] > lim else ""
            d = dl.get(b["name"]) if b.get("k", 1) == 1 else None
            badge = ""
            if d and d.get("status") in ("ok", "late") and d.get("suggest"):
                badge = f"  ⏰{d['suggest'][11:16]}" if d["status"] == "ok" else "  ⏰已过"
            elif d and d.get("status") in ("started", "done"):
                badge = "  ⏰已开赛"
            self.lb.insert("end", f" {name}{over}{badge}")
            if d and d.get("status") in ("late", "started", "done"):
                self.lb.itemconfig(i, fg=C["bad"])
        if self.blocks:
            self.lb.selection_set(min(keep, len(self.blocks) - 1))
            self.lb.yview_moveto(yview[0])

    def _fill_posts(self) -> None:
        if not self.blocks:
            self.lb.delete(0, "end")
            self._show_empty_posts()
            return
        self._paint_list()
        self.btn_copy.configure(state="normal", bg=C["accent"])
        self._show_block()

    def _refresh_deadline_ui(self) -> None:
        """每隔一会儿：重新算「建议发帖时间」有没有过，只刷新列表和检查栏，不动正文。"""
        if not self.blocks:
            return
        self._paint_list()
        b = self._cur_block()
        if b:
            self._show_checks(b["name"])

    # ——— 发帖前检查 / 建议发帖时间 ———
    def _now_bjt(self) -> datetime:
        return datetime.now(BJT).replace(tzinfo=None)

    def _deadline_rows(self) -> List[Dict[str, Any]]:
        rows = (self.result or {}).get("deadlines") or []
        GD = getattr(self.G, "GD", None)
        if not rows or GD is None:
            return list(rows)
        try:
            return GD.refresh_deadlines(rows, self._now_bjt(), int(self.G.POST_LEAD_MIN))
        except Exception:  # noqa: BLE001
            return list(rows)

    def _deadline_map(self) -> Dict[str, Dict[str, Any]]:
        return {r["post"]: r for r in self._deadline_rows()}

    def _show_checks(self, name: str) -> None:
        """这条帖子下面一小块：建议发帖时间 + 和它有关的发帖前检查。"""
        res = self.result or {}
        d = self._deadline_map().get(name)
        issues = [i for i in (res.get("preflight") or []) if i.get("post") in (name, "")]
        lines: List[str] = []
        color = C["muted"]
        if d and d.get("text"):
            lines.append("⏰ " + d["text"])
            if d.get("status") in ("late", "started", "done"):
                color = C["bad"]
            elif d.get("status") == "ok":
                color = C["ok"]
        icon = {"error": "⛔", "warn": "⚠", "info": "ℹ"}
        for i in issues[:4]:
            lines.append(f"{icon.get(i['level'], '·')} {i['text']}")
        if any(i["level"] == "error" for i in issues):
            color = C["bad"]
        elif any(i["level"] == "warn" for i in issues) and color != C["bad"]:
            color = C["warn"]
        if res.get("preflight") is not None and res.get("blocks") and not issues and d is not None and not any("⛔" in l for l in lines):
            lines.append("✔ 发帖前检查：这条没发现问题")
        self.pf_lbl.configure(text="\n".join(lines), fg=color)

    def show_all_checks(self) -> None:
        res = self.result or {}
        if not res.get("blocks"):
            messagebox.showinfo("还没有推单", "先点「一键更新」生成今日推单。", parent=self)
            return
        lines: List[str] = ["【发帖前检查】"]
        pf = res.get("preflight_lines") or []
        lines += pf if pf else ["✔ 没发现问题（已开赛的场次、夸大用词、数据太旧、重复、空帖都查过了）"]
        lines += ["", "【建议发帖时间】（比该帖里最早一场开赛提前 %d 分钟，可在 rules.json 里改）" % int(self.G.POST_LEAD_MIN)]
        rows = [r for r in self._deadline_rows() if r.get("text")]
        lines += [f"· {r['post']}：{r['text']}" for r in rows] or ["（没有）"]
        lines += ["", "【临场变动】（和同一天上一次生成相比）"]
        dr = res.get("drift") or []
        lines += [f"· {d['text']}" for d in dr] or ["（没有变化，或这是今天第一次生成）"]
        if res.get("rules_changed") or res.get("rules_warns"):
            lines += ["", "【规则文件 rules.json】"]
            if res.get("rules_changed"):
                lines.append("· 和默认不同的项：" + "；".join(res["rules_changed"]))
            lines += ["⚠ " + w for w in res.get("rules_warns") or []]
        if res.get("timing"):
            lines += ["", "【这次更新各步骤用时】", "· " + ("｜".join(f"{n} {d}秒" for n, d in res["timing"] if d >= 0.5) or "每一步都很快")]
        win = tk.Toplevel(self)
        win.title("发帖前检查 · 建议发帖时间 · 临场变动")
        win.configure(bg=C["card"])
        win.geometry("760x520")
        win.transient(self)
        tf = tk.Frame(win, bg=C["card"])
        tf.pack(fill="both", expand=True, padx=12, pady=(12, 6))
        txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"], padx=12, pady=10, bg="#fbfbfc")
        sb = ttk.Scrollbar(tf, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        txt.insert("1.0", "\n".join(lines))
        txt.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(pady=(0, 10))

    def _cur_block(self) -> Optional[Dict[str, Any]]:
        sel = self.lb.curselection()
        return self.blocks[sel[0]] if sel and sel[0] < len(self.blocks) else None

    def _show_block(self) -> None:
        b = self._cur_block()
        if not b:
            return
        lim = int(self.result.get("limit", 280)) if self.result else 280
        limit_txt = "不限字数" if lim >= self.G.DEFAULT_LIMIT else f"字数 {b['weight']}/{lim}"
        over = lim < self.G.DEFAULT_LIMIT and b["weight"] > lim
        self.blk_info.configure(text=f"{b['name']}" + (f"  第 {b['k']}/{b['n']} 条" if b["n"] > 1 else "") + f"  ·  {limit_txt}"
                                + ("  ⚠ 超出上限，发不出去" if over else ""), fg=C["bad"] if over else C["muted"])
        self._set_text(self.txt, b["text"])
        self._show_checks(b["name"])

    def _show_link(self, res: Dict[str, Any]) -> None:
        """面板底部一行「衔接情况」：昨天的推单有没有接上、有没有断档。"""
        G = self.G
        lines: List[str] = []
        warn = False
        sd = res.get("settled_day")
        if sd:
            t = G.tally(G.load_history(HISTORY), [sd])
            h, n, w = sum(v[0] for v in t.values()), sum(v[1] for v in t.values()), sum(v[2] for v in t.values())
            lines.append(f"✔ 已接上昨天：{G.md(sd)}发出的推单已逐条复盘，命中 {h}/{n}" + (f"（另有 {w} 条结果未出）" if w else "")
                         + f"；今天的 {res.get('picks', 0)} 条推单已记入历史，明天更新会自动接着复盘。")
        for note in res.get("notes") or []:
            warn = warn or note.startswith("⚠")
            lines.append(note if note.startswith("⚠") else "· " + note)
        self.link.configure(text="\n".join(lines), fg=C["warn"] if warn else (C["ok"] if sd else C["muted"]))

    def show_day_posts(self) -> None:
        """弹出窗口：看所选日期当天发出的推文原文（每次生成时存进历史的）。"""
        date = self.cmb_date.get()
        if not date:
            messagebox.showinfo("还没有历史", "还没有任何一天的推单记录。先点「一键更新」。", parent=self)
            return
        run = self.G.load_history(HISTORY).get("runs", {}).get(date) or {}
        posts = run.get("posts") or []
        if not posts:
            messagebox.showinfo("没有保存推文原文", f"{date} 没有保存推文原文（可能是更早的版本生成的，或者已超过 {self.G.KEEP_POST_DAYS} 天）。\n"
                                                    "这天的推单明细还在「推单明细」表里。", parent=self)
            return
        win = tk.Toplevel(self)
        win.title(f"{date} 发出的推文原文")
        win.configure(bg=C["card"])
        win.geometry("760x520")
        win.transient(self)
        left = tk.Frame(win, bg=C["card"])
        left.pack(side="left", fill="y", padx=(12, 6), pady=12)
        lb = tk.Listbox(left, exportselection=False, activestyle="none", font=self.f_ui, width=16, bd=0, highlightthickness=1,
                        highlightbackground=C["line"], selectbackground=C["accent"], selectforeground="white")
        lb.pack(fill="y", expand=True)
        for p in posts:
            lb.insert("end", " " + p["name"])
        right = tk.Frame(win, bg=C["card"])
        right.pack(side="left", fill="both", expand=True, padx=(6, 12), pady=12)
        info = tk.Label(right, text=f"生成于 {run.get('generated_at', '?')}　·　" + ("发帖字数上限 " + str(run.get("limit")) if run.get("limit") else ""),
                        bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        info.pack(fill="x")
        tf = tk.Frame(right, bg=C["card"])
        tf.pack(fill="both", expand=True, pady=6)
        txt = tk.Text(tf, wrap="word", font=self.f_post, bd=0, highlightthickness=1, highlightbackground=C["line"], padx=12, pady=10,
                      bg="#fbfbfc", state="disabled")
        sb = ttk.Scrollbar(tf, command=txt.yview)
        txt.configure(yscrollcommand=sb.set)
        txt.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

        def show() -> None:
            sel = lb.curselection()
            if sel:
                self._set_text(txt, posts[sel[0]]["text"])

        def copy() -> None:
            sel = lb.curselection()
            if sel:
                self._to_clipboard(posts[sel[0]]["text"])
                self._set_status(f"已复制 {date} 的「{posts[sel[0]]['name']}」。", "ok")

        lb.bind("<<ListboxSelect>>", lambda e: show())
        ttk.Button(right, text="复制这条", command=copy).pack(anchor="e")
        lb.selection_set(0)
        show()

    # ——— 规则设置 / 诊断包 ———
    def open_rules(self) -> None:
        """打开 rules.json（没有就先按默认值建一个），用系统默认的编辑器（记事本）打开。"""
        try:
            self.G.ensure_rules_file(APP_DIR)
            path = L.p(APP_DIR, self.G.RULE_FILE)
            if not path.exists():
                raise OSError("rules.json 建不出来（文件夹不能写？）")
            open_in_explorer(path)
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("打不开规则文件", str(exc), parent=self)
            return
        self._set_status("已打开 rules.json：改冒号后面的数字，存盘，再点「一键更新」就按新规则出推单（看不懂的项会自动用默认值，并在日志里告诉你）。", "ok")

    def make_diag(self) -> None:
        """一键诊断包：写 诊断报告.txt（版本、设置、文件清单、历史概况、错误日志、运行日志尾巴；密钥已打码）。"""
        try:
            tail = self.log.get("1.0", "end").splitlines()[-80:]
            out = self.G.write_diagnostics(APP_DIR, log_tail=tail, browser=str(self.settings.get("browser", "")).strip())
        except Exception as exc:  # noqa: BLE001
            messagebox.showerror("诊断包没生成", str(exc), parent=self)
            return
        if not out:
            messagebox.showerror("诊断包没生成", "缺 guard.py，或这个文件夹不能写。", parent=self)
            return
        self._append_log(f"✔ 已生成 {out.name}（密钥已隐藏）")
        self._set_status(f"已生成 {out.name}：遇到问题把这个文件发给我就行（里面没有你的密钥和账号）。", "ok")
        messagebox.showinfo("诊断包已生成", f"已生成「{out.name}」，放在{'「报告」文件夹' if L.REP else '脚本文件夹'}里（已帮你打开）。\n\n遇到问题时把它发给我就行：里面有版本、设置、文件清单、"
                                           "最近的运行日志，密钥已经隐藏。", parent=self)
        self._safe(open_in_explorer, L.d(APP_DIR, L.REP))

    # —— 复制 / 保存 ——
    def _to_clipboard(self, text: str) -> None:
        self.clipboard_clear()
        self.clipboard_append(text)
        self.update_idletasks()

    def copy_current(self) -> None:
        b = self._cur_block()
        if not b:
            return
        self._to_clipboard(b["text"])
        self._set_status(f"已复制「{b['name']}」，直接去 X 粘贴发布。", "ok")
        self.btn_copy.configure(text="已复制 ✔")
        if self._flash_job:
            self.after_cancel(self._flash_job)
        self._flash_job = self.after(1300, lambda: self.btn_copy.configure(text="复制这条"))

    def copy_all(self) -> None:
        if not self.blocks:
            return
        sep = "\n\n" + "-" * 24 + "\n\n"
        self._to_clipboard(sep.join(b["text"] for b in self.blocks))
        self._set_status(f"已复制全部 {len(self.blocks)} 条（中间有分隔线，发之前要分开）。", "ok")

    def save_txt(self) -> None:
        if not self.result or not self.blocks:
            return
        path = filedialog.asksaveasfilename(parent=self, defaultextension=".txt", initialfile=f"推单文案_{self.result.get('day', '')}.txt",
                                            filetypes=[("文本文件", "*.txt")])
        if path:
            self._safe(lambda: Path(path).write_text(self.G.format_txt(self.result), encoding="utf-8"))
            self._set_status(f"已保存：{path}", "ok")

    # —— 昨日复盘页 ——
    def _refresh_review(self) -> None:
        G = self.G
        hist = G.load_history(HISTORY)
        picks = hist["picks"]
        dates = sorted({p["date"] for p in picks.values()}, reverse=True)
        today = (self.result or {}).get("day") or (dates[0] if dates else None)
        settled = sorted({p["date"] for p in picks.values() if p["status"] in ("hit", "miss") and (not today or p["date"] < today)})
        sd = settled[-1] if settled else None
        recent = []
        if today:
            base = datetime.strptime(today, "%Y-%m-%d")
            recent = [(base - timedelta(days=i)).strftime("%Y-%m-%d") for i in range(1, G.RECENT_DAYS + 1)]
        t_y, t_r, t_a = G.tally(hist, [sd] if sd else []), G.tally(hist, recent), G.tally(hist, dates)

        def cell(t: dict, play: str) -> str:
            h, n, pend = t.get(play, (0, 0, 0))
            if n == 0:
                return f"待开奖 {pend}" if pend else "—"
            return f"{h}/{n}（{h / n:.0%}）" + (f" +待{pend}" if pend else "")

        self.stats.heading("yest", text=f"{G.md(sd)}推单" if sd else "昨日推单")
        for row in self.stats.get_children():
            self.stats.delete(row)
        for play in G.PLAY_ORDER:
            if any(t.get(play, (0, 0, 0))[1] or t.get(play, (0, 0, 0))[2] for t in (t_y, t_r, t_a)):
                self.stats.insert("", "end", values=(play, cell(t_y, play), cell(t_r, play), cell(t_a, play)))
        if self.stats.get_children():
            note = ("只统计已经出结果的推单；4场进球、6场半全场、任选九本来就是低把握玩法。\n"
                    "每天点一次「一键更新」就能接上；哪天漏点了，下次更新会自动补抓那天的赛果、把它的推单结算掉（最多往前补 3 天）。")
        elif picks:
            note = "推单已记录，等比赛结束、赛果出来后（第二天更新）这里会出现命中率。"
        else:
            note = "还没有历史推单。今天生成的推单，明天点「一键更新」时会自动结算，这里就有战绩了。"
        try:
            ftxt = G.filter_stats(hist)[1]
        except Exception:
            ftxt = ""
        if ftxt:
            note += "\n" + ftxt
        self.stats_note.configure(text=note)
        cur = self.cmb_date.get()
        self.cmb_date.configure(values=dates)
        self.cmb_date.set(cur if cur in dates else (sd or (dates[0] if dates else "")))
        self.yest_cards()
        self._fill_details()

    def yest_cards(self) -> None:
        """顶部「昨日战绩」卡片：昨日（最近一个已结算日）竞足+北单+竞篮单场推荐的命中数。"""
        hist = self.G.load_history(HISTORY)
        today = (self.result or {}).get("day")
        settled = sorted({p["date"] for p in hist["picks"].values() if p["status"] in ("hit", "miss") and (not today or p["date"] < today)})
        if not settled:
            self.cards["yest"].configure(text="—")
            return
        sd = settled[-1]
        h = n = 0
        for p in hist["picks"].values():
            if p["date"] == sd and p["play"] in ("竞足", "北单", "竞篮") and p["status"] in ("hit", "miss"):
                n += 1
                h += p["status"] == "hit"
        self.cards["yest"].configure(text=f"{self.G.md(sd)} 命中 {h}/{n}（{h / n:.0%}）" if n else "—")

    def _fill_details(self) -> None:
        G = self.G
        for row in self.tree.get_children():
            self.tree.delete(row)
        date, filt = self.cmb_date.get(), self.filter_var.get()
        if not date:
            self.detail_count.configure(text="")
            return
        picks = G.load_history(HISTORY)["picks"]
        order = {n: i for i, n in enumerate(G.PLAY_ORDER)}
        rows = [p for p in picks.values() if p["date"] == date]
        rows.sort(key=lambda p: (order.get(p["play"], 99), natural_key(G.describe_pick(p, picks)[1]), p["market"]))
        label = {"hit": "命中 ✔", "miss": "未中 ✘", "pending": "待开奖", "void": "作废"}
        cnt = {"hit": 0, "miss": 0, "pending": 0, "void": 0}
        for p in rows:
            cnt[p["status"]] = cnt.get(p["status"], 0) + 1
            if filt != "all" and p["status"] != filt:
                continue
            typ, no, match, pick = G.describe_pick(p, picks)
            play = p["play"] if typ in (p["play"], "串关", "任九") or p["play"] in ("胜负彩", "4场进球", "6场半全场") else f"{p['play']}·{typ}"
            cp_txt = f"{p['cp']:.0%}" if ("模" in str(p.get("cp_src") or "") and isinstance(p.get("cp"), (int, float))) else ""    # 综合概率（赔率+模型+两队数据，真掺了模型才显示）
            self.tree.insert("", "end", values=(play, no, match, pick, cp_txt, p.get("result", ""), label.get(p["status"], p["status"])), tags=(p["status"],))
        self.detail_count.configure(text=f"共 {len(rows)} 条：命中 {cnt['hit']} · 未中 {cnt['miss']} · 待开奖 {cnt['pending']}"
                                         + (f" · 作废 {cnt['void']}" if cnt["void"] else ""))

    # —— 人工修正页 ——
    def _load_manual_text(self) -> None:
        try:
            text = MANUAL.read_text(encoding="utf-8")
        except OSError:
            text = ""
        self.man_txt.delete("1.0", "end")
        self.man_txt.insert("1.0", text)
        self.man_msg.configure(text="（现在没有人工修正）" if not text.strip() else "", fg=C["muted"])

    def _validate_manual(self, text: str) -> Optional[Dict[str, Any]]:
        try:
            data = json.loads(text)
            self.G.Manual(data)
            if not isinstance(data, dict):
                raise TypeError
            if not isinstance(data.get("exclude_teams", []), list) or not isinstance(data.get("sfc_overrides", {}), dict) \
                    or not isinstance(data.get("extra_picks", []), list):
                raise TypeError
            return data
        except json.JSONDecodeError as exc:
            self.man_msg.configure(text=f"格式不对：第 {exc.lineno} 行第 {exc.colno} 列附近（多半是少了引号/逗号，或用了中文标点）", fg=C["bad"])
        except (TypeError, ValueError, AttributeError):
            self.man_msg.configure(text="结构不对：最外层要是 { }；exclude_teams 是 [ ]，sfc_overrides 是 { }，extra_picks 是 [ ]。点「放入示例」对照。", fg=C["bad"])
        return None

    def save_manual(self, quiet: bool = False) -> bool:
        text = self.man_txt.get("1.0", "end").strip()
        if not text:
            return self.clear_manual()
        if self._validate_manual(text) is None:
            return False
        try:
            self.G.atomic_write(MANUAL, text + "\n")
        except OSError as exc:
            self.man_msg.configure(text=f"保存失败：{exc}", fg=C["bad"])
            return False
        if not quiet:
            self.man_msg.configure(text="已保存。点上面「只用现有数据重新生成」让它生效。", fg=C["ok"])
        return True

    def add_exclude(self) -> None:
        team = self.ent_team.get().strip()
        if not team:
            return
        text = self.man_txt.get("1.0", "end").strip()
        data: Dict[str, Any] = {}
        if text:
            data = self._validate_manual(text)  # type: ignore[assignment]
            if data is None:
                return
        teams = data.setdefault("exclude_teams", [])
        if team not in teams:
            teams.append(team)
        self.man_txt.delete("1.0", "end")
        self.man_txt.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
        if self.save_manual(quiet=True):
            self.man_msg.configure(text=f"已排除「{team}」并保存。点上面「只用现有数据重新生成」让它生效。", fg=C["ok"])
            self.ent_team.delete(0, "end")

    def fill_example(self) -> None:
        self.man_txt.delete("1.0", "end")
        self.man_txt.insert("1.0", json.dumps(EXAMPLE_MANUAL, ensure_ascii=False, indent=2))
        self.man_msg.configure(text="这是示例，按需修改后点「保存」。", fg=C["muted"])

    def clear_manual(self) -> bool:
        try:
            if MANUAL.exists():
                MANUAL.unlink()
        except OSError as exc:
            self.man_msg.configure(text=f"删除失败：{exc}", fg=C["bad"])
            return False
        self.man_txt.delete("1.0", "end")
        self.man_msg.configure(text="已清空（没有人工修正了）。", fg=C["ok"])
        return True

    # ════════════════════════════════════════════════════════════════════
    # 定时 / 退出
    # ════════════════════════════════════════════════════════════════════
    def _tick(self) -> None:
        try:
            now = beijing_now()
            s = self.settings
            touch_lock()
            if RUN_FLAG.exists():                      # 任务计划又启动了一个窗口，它发现这个窗口开着，就留了张条子让这里更新
                try:
                    RUN_FLAG.unlink()
                except OSError:
                    pass
                if not self.busy:
                    self._append_log("—— 每天自动运行的时间到了，自动开始 ——")
                    self.start_update(True, manual=False)
            if s.get("daily") and not self.busy and s.get("last_ok") != now.strftime("%Y-%m-%d") and now.strftime("%H:%M") >= s.get("daily_time", "15:00"):
                self._append_log("—— 到了每天定时更新的时间，自动开始 ——")
                self.start_update(True, manual=False)
            elif self.result:
                self._update_fetched_card(self.result.get("fetched_at", ""))
                if self.blocks and not self.busy:
                    self._refresh_deadline_ui()              # 建议发帖时间过了的，每隔一会儿刷新成红色
        finally:
            self.after(30000, self._tick)

    def on_close(self) -> None:
        if self.busy and not messagebox.askyesno("还在更新", "正在更新数据，现在退出会中断。确定退出吗？", parent=self):
            return
        self.cancel.set()
        proc = self.proc
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except OSError:
                pass
        try:
            LOCK.unlink()
        except OSError:
            pass
        self.destroy()


def main() -> int:
    if tk is None:
        print("这台电脑的 Python 没带 tkinter。请到 python.org 重新安装 Python，安装时保持勾选 tcl/tk。")
        return 1
    if sys.platform.startswith("win"):                # 高分屏下文字不发虚
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(1)
        except Exception:  # noqa: BLE001
            pass
    force_run = "--run" in sys.argv[1:]
    if force_run and lock_fresh():                    # 已经有一个窗口开着：留张条子让它去更新，自己不再开第二个窗口
        try:
            RUN_FLAG.write_text(str(time.time()), encoding="utf-8")
        except OSError:
            pass
        return 0
    try:
        App(force_run).mainloop()
    except Exception:  # noqa: BLE001
        err = traceback.format_exc()
        try:
            ERRLOG.write_text(err, encoding="utf-8")
        except OSError:
            pass
        try:
            root = tk.Tk()
            root.withdraw()
            probs = file_problems()
            why = file_problem_text(probs) if probs else err.strip().splitlines()[-1]
            messagebox.showerror("操作台启动失败", why + f"\n\n详细信息已写入 {ERRLOG.name}")
        except Exception:  # noqa: BLE001
            pass
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
