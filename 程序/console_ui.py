"""操作台界面外壳：字体、主题、布局。业务与后台任务仍由 App 控制。"""
from __future__ import annotations
from typing import Dict, List
try:
    import tkinter as tk
    from tkinter import ttk
    import tkinter.font as tkfont
except ImportError:
    tk = ttk = tkfont = None
import layout as L

C = dict(bg="#f4f7fb", card="#ffffff", head="#12233f", head2="#263c5c", accent="#2563eb", accent_dark="#1d4ed8",
         accent_off="#93c5fd", ok="#15803d", bad="#b91c1c", warn="#b45309", muted="#6b7280", line="#dce4ef",
         hit_bg="#e6f4ea", miss_bg="#fce8e6")


class ConsoleShellMixin:
    def _init_fonts(self) -> None:
        fams = {name.casefold(): name for name in tkfont.families(self)}

        def pick(cands: List[str], fallback: str) -> str:
            return next((fams[c.casefold()] for c in cands if c.casefold() in fams), fallback)

        base = tkfont.nametofont("TkDefaultFont").actual("family")
        ui = pick(["Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", "Noto Sans CJK SC", "WenQuanYi Micro Hei", "SimHei", "WenQuanYi Bitmap Song"], base)
        mono = pick(["Consolas", "Cascadia Mono", "Noto Sans Mono CJK SC", "DejaVu Sans Mono", "Courier New"], "TkFixedFont")
        for name in ("TkDefaultFont", "TkTextFont", "TkMenuFont", "TkHeadingFont"):
            tkfont.nametofont(name).configure(family=ui, size=10)
        self.f_ui = (ui, 10)
        self.f_small = (ui, 9)
        self.f_bold = (ui, 10, "bold")
        self.f_title = (ui, 17, "bold")
        self.f_card = (ui, 13, "bold")
        self.f_big = (ui, 13, "bold")
        self.f_post = (ui, 11)
        self.f_mono = (mono, 10)

    def _init_style(self) -> None:
        st = ttk.Style(self)
        try:
            st.theme_use("clam")                   # 各系统外观一致，也能正常改颜色
        except tk.TclError:
            pass
        scale = float(self.tk.call("tk", "scaling"))
        rh = max(22, int(10 * scale * 1.95))
        card, line = C["card"], C["line"]
        for name in ("TFrame", "TLabelframe", "TRadiobutton", "TCheckbutton", "TPanedwindow"):
            st.configure(name, background=card)
        st.configure("TLabelframe", bordercolor=line)
        st.configure("TLabelframe.Label", background=card, foreground=C["head"], font=self.f_bold)
        st.configure("TRadiobutton", font=self.f_ui)
        st.configure("TCheckbutton", font=self.f_ui)
        st.map("TRadiobutton", background=[("active", card)])
        st.map("TCheckbutton", background=[("active", card)])
        st.configure("TButton", padding=(12, 7), background="#e5e7eb", bordercolor=line, font=self.f_ui)
        st.map("TButton", background=[("active", "#d1d5db"), ("disabled", "#f3f4f6")])
        st.configure("TNotebook", background=C["bg"], bordercolor=line)
        st.configure("TNotebook.Tab", padding=(18, 10), font=self.f_bold, background=C["bg"], foreground=C["head2"])
        st.map("TNotebook.Tab", background=[("selected", card)], foreground=[("selected", C["accent"])])
        st.configure("Treeview", rowheight=rh, font=self.f_ui, background="white", fieldbackground="white", bordercolor=line)
        st.configure("Treeview.Heading", font=self.f_bold, background="#f3f4f6", relief="flat")
        st.map("Treeview", background=[("selected", C["accent"])], foreground=[("selected", "white")])
        st.configure("Horizontal.TProgressbar", background=C["accent"], troughcolor="#e5e7eb", bordercolor=line)

    # ════════════════════════════════════════════════════════════════════
    # 搭界面
    # ════════════════════════════════════════════════════════════════════
    def _build(self) -> None:
        head = tk.Frame(self, bg=C["head"])
        head.pack(fill="x")
        title = tk.Frame(head, bg=C["head"])
        title.pack(fill="x")
        tk.Label(title, text="竞彩推单操作台", bg=C["head"], fg="white", font=self.f_title).pack(side="left", padx=(18, 10), pady=8)
        tools = tk.Frame(title, bg=C["head"])
        tools.pack(side="right", padx=14)
        for text, cmd in (("设置", self.open_settings), ("规则设置", self.open_rules), ("诊断包", self.make_diag),
                          (("打开推单文件夹" if L.OUT else "打开文件夹"), self.open_output_folder)):
            tk.Button(tools, text=text, command=cmd, bg=C["head2"], fg="white", activebackground="#4b5563", activeforeground="white",
                      relief="flat", bd=0, padx=14, pady=5, cursor="hand2", font=self.f_ui).pack(side="left", padx=(0, 8))

        panel = tk.Frame(self, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
        panel.pack(fill="x", padx=14, pady=(12, 8))
        row0 = tk.Frame(panel, bg=C["card"])
        row0.pack(fill="x", padx=14, pady=(8, 4))
        self.btn_go = tk.Button(row0, text="▶  一键更新", command=lambda: self.start_update(True),
                                bg=C["accent"], fg="white", activebackground=C["accent_dark"], activeforeground="white",
                                disabledforeground="#dbeafe", relief="flat", bd=0, padx=22, pady=7, cursor="hand2", font=self.f_big)
        self.btn_go.pack(side="left")
        secondary = tk.Frame(panel, bg=C["card"])
        secondary.pack(fill="x", padx=14, pady=(0, 4))
        self.btn_regen = ttk.Button(secondary, text="只用现有数据重新生成", command=lambda: self.start_update(False))
        self.btn_regen.pack(side="left")
        self.btn_retry = ttk.Button(secondary, text="重试失败项", command=self.retry_failed)
        self.btn_retry.pack(side="left", padx=(8, 0))
        self.btn_stop = ttk.Button(secondary, text="停止", command=self.stop, state="disabled")
        self.btn_stop.pack(side="left", padx=(8, 0))
        self.btn_hist = ttk.Button(secondary, text="补历史赛果", command=self.start_history)
        self.btn_hist.pack(side="left", padx=(8, 0))
        tk.Label(row0, text="更新数据、复盘昨日，再生成今日内容", bg=C["card"],
                 fg=C["muted"], font=self.f_ui).pack(side="left", padx=16)
        self.bar = ttk.Progressbar(row0, mode="determinate", length=200, value=0)
        self.bar.pack(side="right")

        row1 = tk.Frame(panel, bg=C["card"])
        row1.pack(fill="x", padx=14, pady=(2, 4))
        self.step_lbls: List[tk.Label] = []
        for i, name in enumerate(self.STEPS):
            if i:
                tk.Label(row1, text="›", bg=C["card"], fg=C["line"], font=self.f_big).pack(side="left", padx=8)
            lb = tk.Label(row1, text=name, bg=C["card"], fg=C["muted"], font=self.f_ui)
            lb.pack(side="left")
            self.step_lbls.append(lb)
        mode = tk.Frame(panel, bg=C["card"])
        mode.pack(fill="x", padx=14, pady=(2, 4))
        tk.Label(mode, text="发帖账号：", bg=C["card"], fg=C["muted"], font=self.f_ui).pack(side="left")
        self.mode_var = tk.StringVar(value="280" if int(self.settings.get("limit", 280)) < self.G.DEFAULT_LIMIT else "pro")
        for text, val in (("普通账号（超过280字拆成串）", "280"), ("Premium（长帖不拆）", "pro")):
            ttk.Radiobutton(mode, text=text, value=val, variable=self.mode_var, command=self._on_mode).pack(side="left", padx=(8, 0))

        self.status = tk.Label(panel, text="", height=1, width=1, bg=C["card"], fg=C["muted"], font=self.f_ui, anchor="w")
        self.status.pack(fill="x", padx=14, pady=(0, 2))
        summary = tk.Frame(panel, bg=C["card"])
        summary.pack(fill="x", padx=14, pady=(0, 8))
        self.btn_details = ttk.Button(summary, text="查看运行详情", command=self.show_run_details)
        self.btn_details.pack(side="right", padx=(10, 0))
        self.link = tk.Label(summary, text="尚未更新", height=1, width=1, bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w")
        self.link.pack(side="left", fill="x", expand=True)

        cards = tk.Frame(self, bg=C["bg"])
        cards.pack(fill="x", padx=14, pady=(0, 8))
        self.cards: Dict[str, tk.Label] = {}
        for i, (key, title) in enumerate((("day", "今日销售日"), ("fetched", "数据抓取时间（北京时间）"),
                                          ("picks", "今日推单"), ("yest", "昨日战绩（竞足+北单+竞篮单场）"))):
            f = tk.Frame(cards, bg=C["card"], highlightbackground=C["line"], highlightthickness=1)
            f.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 8, 0))
            cards.columnconfigure(i, weight=1, uniform="card")
            tk.Label(f, text=title, width=1, height=1, bg=C["card"], fg=C["muted"], font=self.f_small, anchor="w").pack(fill="x", padx=12, pady=(8, 0))
            v = tk.Label(f, text="—", width=1, height=1, bg=C["card"], fg=C["head"], font=self.f_card, anchor="w")
            v.pack(fill="x", padx=12, pady=(0, 8))
            self.cards[key] = v

        self.nb = ttk.Notebook(self)
        self.cards["yest"].configure(font=self.f_bold)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(0, 14))
        self._build_posts_tab()
        self._build_kw_tab()
        self._build_cm_tab()
        self._build_review_tab()
        self._build_stats_tab()
        self._build_manual_tab()
        self._build_log_tab()
        self.nb.enable_traversal()
        for index in range(self.nb.index("end")):
            self.bind(f"<Alt-Key-{index + 1}>", lambda event, i=index: self._select_tab(i))

    def _select_tab(self, index: int) -> str:
        self.nb.select(index)
        return "break"

