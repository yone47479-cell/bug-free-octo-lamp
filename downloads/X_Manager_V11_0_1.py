#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""X 浏览器任务管理器 V11.0（独立执行池与8小时工作台）。

保留上传的V10界面及原流程，新增可选V11.1逐帖评分、连续阅读与同帖支线。
账号与任务 → 养号流程：V10原流程 / V11.1逐帖评分。默认保留V10，下一批生效。
设置 → 阅读评分与节奏：独立调整V11.1的80/17/3机会权重、预算与讨论深度。
TXT发推、立即同步不使用阅读流程；切换流程不会开启评论、点赞或消息阅读。

依赖：python -m pip install requests playwright
"""

from __future__ import annotations

# Embedded modules generated from the modular sources.
import sys as _embed_sys
import types as _embed_types

_embed_mod = _embed_types.ModuleType('xmanager_planning')
_embed_mod.__file__ = __file__
_embed_sys.modules['xmanager_planning'] = _embed_mod
exec(compile('"""Independent validation and identity ownership for recent-performance tasks."""\nfrom dataclasses import dataclass\nimport math\nimport re\nimport sqlite3\n\nACTIONS = (\'like\', \'repost\', \'comment\')\n\n@dataclass(frozen=True)\nclass TaskPlan:\n    actors: tuple[str, ...]\n    targets: tuple\n    limits: tuple\n    interval: float\n    comment_interval: float\n\n    @property\n    def total(self):\n        return len(self.targets) * sum(value for _, value in self.limits)\n\n    def summary(self):\n        values = dict(self.limits)\n        return (f\'执行环境 {len(self.actors)} 个 · 目标帖子 {len(self.targets)} 条\\n\'\n                f\'每帖：赞 {values["like"]} / 转 {values["repost"]} / 评 {values["comment"]}\\n\'\n                f\'最多 {self.total} 项；本人内容跳过；实际身份重复的环境停止执行。\\n\'\n                \'已完成操作不重复，结果不明的项目须人工核对。\')\n\n\ndef build_plan(actors, targets, limits, interval, comment_interval):\n    actors = tuple(dict.fromkeys(actors))\n    targets = tuple(targets)\n    if not actors or any(not isinstance(a, str) or not a or a.startswith(\'demo:\') for a in actors):\n        raise ValueError(\'请独立选择有效的执行账号环境\')\n    if not targets or len(targets) > 100:\n        raise ValueError(\'每批选择1～100条目标帖子\')\n    if len({t[0] for t in targets}) != len(targets):\n        raise ValueError(\'目标帖子重复\')\n    for pid, handle, url in targets:\n        if not str(pid).isdigit() or not re.fullmatch(r\'[A-Za-z0-9_]{1,15}\', handle):\n            raise ValueError(\'目标帖子身份无效\')\n        if url != f\'https://x.com/{handle}/status/{pid}\':\n            raise ValueError(\'目标链接与帖子身份不一致\')\n    if set(limits) != set(ACTIONS) or any(type(v) is not int or not 0 <= v <= 100 for v in limits.values()):\n        raise ValueError(\'各项数量必须为0～100的整数\')\n    if not any(limits.values()):\n        raise ValueError(\'至少启用一项操作\')\n    if limits[\'comment\'] > 1:\n        raise ValueError(\'保留全局评论去重，每帖最多一条评论\')\n    if max(limits.values()) > len(actors):\n        raise ValueError(\'执行环境数量不足，请增加账号或降低每帖数量\')\n    for value in (interval, comment_interval):\n        if isinstance(value, bool) or not math.isfinite(value) or not 0 <= value <= 86400:\n            raise ValueError(\'间隔必须为0～86400秒的有限数值\')\n    return TaskPlan(actors, targets, tuple((k, limits[k]) for k in ACTIONS), interval, comment_interval)\n\n\ndef bind_identity(store, batch, actor, handle):\n    handle = handle.lstrip(\'@\').casefold()\n    if not re.fullmatch(r\'[a-z0-9_]{1,15}\', handle):\n        raise ValueError(\'无法核验执行身份\')\n    with store.connection() as db:\n        db.execute(\'BEGIN IMMEDIATE\')\n        if not db.execute(\'SELECT 1 FROM recent_action_members WHERE batch=? AND actor=?\', (batch, actor)).fetchone():\n            raise ValueError(\'账号不在当前执行计划中\')\n        old = db.execute(\'SELECT handle FROM recent_actor_identities WHERE batch=? AND actor=?\', (batch, actor)).fetchone()\n        if old and old[0] != handle:\n            raise ValueError(\'执行过程中X账号发生变化\')\n        try:\n            db.execute(\'INSERT OR IGNORE INTO recent_actor_identities VALUES(?,?,?)\', (batch, actor, handle))\n            owner = db.execute(\'SELECT actor FROM recent_actor_identities WHERE batch=? AND handle=?\', (batch, handle)).fetchone()\n            if not owner or owner[0] != actor:\n                raise ValueError(\'该X账号已由本批另一个浏览器环境使用\')\n        except sqlite3.IntegrityError as exc:\n            raise ValueError(\'账号身份冲突\') from exc\n', 'xmanager_planning', "exec"), _embed_mod.__dict__)

_embed_mod = _embed_types.ModuleType('xmanager_outgoing')
_embed_mod.__file__ = __file__
_embed_sys.modules['xmanager_outgoing'] = _embed_mod
exec(compile('"""Persistent counts of confirmed outgoing actions, separate from received metrics."""\nimport re\nimport sqlite3\nimport time\nfrom pathlib import Path\n\nSCHEMA = \'\'\'\nCREATE TABLE IF NOT EXISTS outgoing_successes(\n account TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL,\n confirmed_at REAL NOT NULL, PRIMARY KEY(account,action,target));\n\'\'\'\n\n\ndef target_id(value):\n    value = str(value or \'\')\n    if value.isdigit():\n        return value\n    match = re.search(r\'/status/(\\d+)(?:[/?#]|$)\', value)\n    return match.group(1) if match else \'\'\n\n\ndef record(store, account, action, target, stamp=None):\n    target = target_id(target)\n    if not account or str(account).startswith(\'demo:\') or action not in (\'like\', \'comment\') or not target:\n        return False\n    with store.connection() as db:\n        result = db.execute(\'INSERT OR IGNORE INTO outgoing_successes VALUES(?,?,?,?)\',\n                            (str(account), action, target, time.time() if stamp is None else stamp))\n        return result.rowcount == 1\n\n\ndef sync_confirmed(store, comment_path):\n    """Import only explicit successful records; retries and refreshes are idempotent."""\n    records = []\n    comment_path = Path(comment_path)\n    if comment_path.is_file():\n        db = sqlite3.connect(comment_path.as_uri()+\'?mode=ro\', uri=True, timeout=30)\n        try:\n            exists = db.execute("SELECT 1 FROM sqlite_master WHERE type=\'table\' AND name=\'drafts\'").fetchone()\n            if exists:\n                for scope, owner, target, updated in db.execute("SELECT scope,owner,item,updated FROM drafts WHERE state=\'sent\'"):\n                    # Panel scope includes account and outbox ID. Exclude DM records entirely.\n                    account = scope[6:].rsplit(\':\', 1)[0] if scope.startswith(\'panel:\') else owner\n                    records.append((account, \'comment\', target, updated))\n        finally:\n            db.close()\n    with store.connection() as db:\n        records.extend(tuple(r) for r in db.execute("SELECT actor,action,target,updated FROM recent_actions WHERE state=\'sent\' AND action IN (\'like\',\'comment\')"))\n        records.extend(tuple(r) for r in db.execute("SELECT account,\'comment\',target,updated FROM outbox WHERE state=\'sent\' AND kind=\'reply\'"))\n        # Collect inside one transaction; never count sent/reviewed records more than once.\n        db.executemany(\'INSERT OR IGNORE INTO outgoing_successes VALUES(?,?,?,?)\',\n                       [(str(a), k, target_id(t), stamp) for a,k,t,stamp in records\n                        if a and not str(a).startswith(\'demo:\') and target_id(t)])\n\n\ndef counts(store):\n    with store.connection() as db:\n        result = {}\n        for account, action, amount, latest in db.execute(\'SELECT account,action,COUNT(*),MAX(confirmed_at) FROM outgoing_successes GROUP BY account,action\'):\n            row = result.setdefault(account, dict(comments_sent_total=0,likes_sent_total=0, outgoing_latest=0))\n            row[\'comments_sent_total\' if action==\'comment\' else \'likes_sent_total\'] = amount\n            row[\'outgoing_latest\'] = max(row[\'outgoing_latest\'], latest)\n        return result\n', 'xmanager_outgoing', "exec"), _embed_mod.__dict__)

_embed_mod = _embed_types.ModuleType('xmanager_ledger')
_embed_mod.__file__ = __file__
_embed_sys.modules['xmanager_ledger'] = _embed_mod
exec(compile('"""Transactional task ledger; browser execution and Tk UI are independent clients."""\nimport time\nfrom xmanager_planning import bind_identity\n\nRECENT_ACTION_NAMES = {\'like\':\'点赞\',\'repost\':\'转发\',\'comment\':\'评论\'}\nRECENT_ACTION_STATES = {\'reserved\':\'准备中\',\'sending\':\'提交中\',\'sent\':\'成功\',\'already\':\'原已完成\',\'unknown\':\'待核对\',\'failed\':\'提交前失败\',\'rejected\':\'平台拒绝\'}\n\nclass InteractionLedger:\n    def __init__(self, store, comment_store_factory):\n        self.store = store\n        self.comment_store_factory = comment_store_factory\n    def recover(self):\n        self.comment_store_factory().recover()\n        with self.store.connection() as db:\n            db.execute("UPDATE recent_actions SET state=\'unknown\',error=\'上次提交中断，结果待核对\' WHERE state=\'sending\'")\n            db.execute("UPDATE recent_actions SET state=\'failed\',error=\'上次任务在提交前中断，可重新安排\' WHERE state=\'reserved\'")\n    def create_batch(self,batch,actors,targets,limits):\n        # One persisted goal for each target/action; every checked account shares it.\n        with self.store.connection() as db:\n            db.execute(\'BEGIN IMMEDIATE\')\n            db.execute(\'INSERT INTO recent_action_batches VALUES(?,?)\',(batch,time.time()))\n            db.executemany(\'INSERT INTO recent_action_members VALUES(?,?,?)\',[(batch,a,i) for i,a in enumerate(dict.fromkeys(actors))])\n            db.executemany(\'INSERT INTO recent_action_goals VALUES(?,?,?,?,?)\',[(batch,t,k,int(limits[k]),u) for t,h,u in targets for k in RECENT_ACTION_NAMES])\n    def progress(self,batch=None):\n        with self.store.connection() as db:\n            if batch is None:\n                row=db.execute(\'SELECT batch FROM recent_action_batches ORDER BY created DESC,rowid DESC LIMIT 1\').fetchone()\n                if not row:return []\n                batch=row[\'batch\']\n            goals=db.execute(\'SELECT * FROM recent_action_goals WHERE batch=? ORDER BY rowid\',(batch,)).fetchall()\n            rows=db.execute("SELECT a.target,a.action,a.state,COUNT(*) n FROM recent_actions a JOIN recent_action_members m ON m.actor=a.actor AND m.batch=? GROUP BY a.target,a.action,a.state",(batch,)).fetchall()\n        states={(r[\'target\'],r[\'action\'],r[\'state\']):r[\'n\'] for r in rows};result=[]\n        for g in goals:\n            def count(*names):return sum(states.get((g[\'target\'],g[\'action\'],n),0) for n in names)\n            done=count(\'sent\',\'already\');unknown=count(\'unknown\',\'sending\');reserved=count(\'reserved\')\n            result.append(dict(g,done=done,unknown=unknown,reserved=reserved,missing=max(0,g[\'goal\']-done-unknown-reserved)))\n        return result\n    def pending(self,batch,actor,target,action):\n        with self.store.connection() as db:\n            return self._capacity(db,batch,actor,target,action)[0]\n    def _capacity(self,db,batch,actor,target,action):\n        goal=db.execute(\'SELECT goal FROM recent_action_goals WHERE batch=? AND target=? AND action=?\',(batch,target,action)).fetchone()\n        if goal is None:return False,\'没有该帖的已授权数量计划\'\n        if not db.execute(\'SELECT 1 FROM recent_action_members WHERE batch=? AND actor=?\',(batch,actor)).fetchone():return False,\'执行账号不在本批勾选范围\'\n        old=db.execute(\'SELECT state FROM recent_actions WHERE actor=? AND target=? AND action=?\',(actor,target,action)).fetchone()\n        if old and old[\'state\']!=\'failed\':return False,RECENT_ACTION_STATES.get(old[\'state\'],old[\'state\'])\n        used=db.execute("SELECT COUNT(*) FROM recent_actions a JOIN recent_action_members m ON m.actor=a.actor AND m.batch=? WHERE a.target=? AND a.action=? AND a.state IN (\'sent\',\'already\',\'reserved\',\'sending\',\'unknown\')",(batch,target,action)).fetchone()[0]\n        return (True,\'\') if used<goal[\'goal\'] else (False,\'该帖数量已满足或已预留（含待核对），不追加提交\')\n    def reserve(self,actor,target,action,batch,url,per_post=False):\n        with self.store.connection() as db:\n            db.execute(\'BEGIN IMMEDIATE\')\n            if per_post:\n                ok,reason=self._capacity(db,batch,actor,target,action)\n                if not ok:return False,reason\n            r=db.execute(\'SELECT state FROM recent_actions WHERE actor=? AND target=? AND action=?\',(actor,target,action)).fetchone()\n            if r and r[\'state\']!=\'failed\':return False,RECENT_ACTION_STATES.get(r[\'state\'],r[\'state\'])\n            db.execute(\'INSERT OR REPLACE INTO recent_actions(actor,target,action,state,batch,url,updated) VALUES(?,?,?,?,?,?,?)\',\n                       (actor,target,action,\'reserved\',batch,url,time.time()))\n        return True,\'\'\n    def bind_identity(self, batch, actor, handle):\n        bind_identity(self.store, batch, actor, handle)\n\n    def target_order(self,batch,actor,targets):\n        with self.store.connection() as db:row=db.execute(\'SELECT position FROM recent_action_members WHERE batch=? AND actor=?\',(batch,actor)).fetchone()\n        offset=(row[\'position\'] if row else 0)%len(targets) if targets else 0\n        return targets[offset:]+targets[:offset]\n    def update(self,actor,target,action,state,error=\'\',result_url=\'\'):\n        with self.store.connection() as db:\n            db.execute(\'UPDATE recent_actions SET state=?,updated=?,error=?,result_url=? WHERE actor=? AND target=? AND action=?\',\n                       (state,time.time(),str(error)[:500],result_url,actor,target,action))\n    def cooldown(self,actor,interval):\n        with self.store.connection() as db:\n            value=db.execute("SELECT MAX(updated) FROM recent_actions WHERE actor=? AND state IN (\'sent\',\'sending\',\'unknown\',\'rejected\')",(actor,)).fetchone()[0]\n        return max(0.0,min(interval,interval-(time.time()-value))) if value is not None else 0.0\n    def rows(self):\n        with self.store.connection() as db:return [dict(r) for r in db.execute(\'SELECT * FROM recent_actions ORDER BY updated DESC LIMIT 1000\')]\n    def resolve(self,actor,target,action,executed):\n        with self.store.connection() as db:\n            row=db.execute(\'SELECT state FROM recent_actions WHERE actor=? AND target=? AND action=?\',(actor,target,action)).fetchone()\n        if not row or row[\'state\'] not in (\'unknown\',\'sending\',\'rejected\'):return False\n        # 评论核对同时释放或保留原有全局目标/文本唯一键。\n        if action==\'comment\':\n            comments=self.comment_store_factory();comments.recover();comments.resolve(actor,target,executed)\n        self.update(actor,target,action,\'sent\' if executed else \'failed\',\'已人工核对\')\n        return True\n\n', 'xmanager_ledger', "exec"), _embed_mod.__dict__)

_embed_mod = _embed_types.ModuleType('xmanager_ui')
_embed_mod.__file__ = __file__
_embed_sys.modules['xmanager_ui'] = _embed_mod
exec(compile('"""8小时工作台：统计范围与执行池独立，计划校验不依赖浏览器。"""\nimport tkinter as tk\nfrom tkinter import ttk, messagebox\nfrom xmanager_planning import build_plan\n\n\ndef make_recent_page(api):\n    Page = api.Page\n    Path = api.Path\n    RECENT_ACTION_NAMES = api.RECENT_ACTION_NAMES\n    RECENT_ACTION_STATES = api.RECENT_ACTION_STATES\n    RECENT_METRICS = api.RECENT_METRICS\n    RECENT_SORT_LABELS = api.RECENT_SORT_LABELS\n    RecentInteractionStore = api.RecentInteractionStore\n    UI = api.UI\n    ago = api.ago\n    browser_id = api.browser_id\n    browser_name = api.browser_name\n    check = api.check\n    csv = api.csv\n    datetime = api.datetime\n    filedialog = api.filedialog\n    hint = api.hint\n    json = api.json\n    make_tree = api.make_tree\n    px = api.px\n    recent_metric_text = api.recent_metric_text\n    recent_rank = api.recent_rank\n    time = api.time\n    ui_button = api.ui_button\n\n    class LegacyRecentPerformancePage(Page):\n        key,icon,title=\'recent8\',\'🏆\',\'8小时表现\'\n        subtitle=\'仅统计账号页勾选账号的最近8小时表现；随机启动开关用于同步和转赞评，运行中修改从下一批生效\'\n        auto_refresh=True\n        def build(self):\n            p=self.frame;p.columnconfigure(0,weight=1);p.rowconfigure(3,weight=1);p.rowconfigure(5,weight=2)\n            self.metric=tk.StringVar(value=\'浏览量\');self.top_n=tk.StringVar(value=\'5\');self.kind=tk.StringVar(value=\'全部内容\');self._sig=None\n            bar=self.toolbar()\n            tk.Label(bar,text=\'排序\',bg=UI[\'bg\'],fg=UI[\'mute\']).pack(side=\'left\')\n            box=ttk.Combobox(bar,textvariable=self.metric,values=tuple(RECENT_SORT_LABELS),state=\'readonly\',width=9);box.pack(side=\'left\',padx=px(5));box.bind(\'<<ComboboxSelected>>\',lambda _e:self.refresh(True))\n            tk.Label(bar,text=\'前N账号\',bg=UI[\'bg\'],fg=UI[\'mute\']).pack(side=\'left\')\n            ttk.Combobox(bar,textvariable=self.top_n,values=(\'3\',\'5\',\'10\',\'20\'),state=\'readonly\',width=4).pack(side=\'left\',padx=px(5))\n            check(bar,\'随机顺序启动窗口\',self.app.run_flags[\'random_order\'],\'blue\',\n                  command=lambda:self.app.try_save(\'随机启动设置\')).pack(side=\'left\',padx=px(10))\n            ui_button(bar,\'同步勾选账号\',self.sync,\'primary\').pack(side=\'right\')\n            ui_button(bar,\'导出CSV\',self.export).pack(side=\'right\',padx=px(5))\n            ui_button(bar,\'刷新\',lambda:self.refresh(True)).pack(side=\'right\')\n            self.hint=tk.StringVar();tk.Label(p,textvariable=self.hint,bg=UI[\'bg\'],fg=UI[\'mute\'],anchor=\'w\',justify=\'left\',wraplength=px(1200)).grid(row=1,column=0,sticky=\'ew\',padx=px(18))\n            action=tk.Frame(p,bg=UI[\'bg\']);action.grid(row=2,column=0,sticky=\'ew\',padx=px(18),pady=px(5))\n            ui_button(action,\'复制前N账号最佳内容链接\',self.copy_top).pack(side=\'left\')\n            ui_button(action,\'复制勾选帖子链接\',self.copy_posts).pack(side=\'left\',padx=px(6))\n            tk.Label(action,text=\'上表选择账号后，下表仅显示该账号；Ctrl 可多选\',bg=UI[\'bg\'],fg=UI[\'faint\']).pack(side=\'left\')\n            cols=(\'name\',\'handle\',\'post_count\',\'reply_count\',\'unknown_count\',\'views\',\'likes\',\'replies\',\'reposts\',\'finished\',\'coverage\')\n            f,self.accounts=make_tree(p,cols,(\'账号\',\'用户名\',\'本人发帖\',\'本人回复\',\'类型未确认\',\'浏览量\',\'获赞\',\'收到回复\',\'转发\',\'最近更新\',\'采集覆盖\'),(115,110,65,65,80,90,75,75,70,90,290),height=7,stretch=(\'name\',\'coverage\'))\n            f.grid(row=3,column=0,sticky=\'nsew\',padx=px(18),pady=px(5));self.accounts.bind(\'<<TreeviewSelect>>\',lambda _e:self.render_posts())\n            filters=tk.Frame(p,bg=UI[\'bg\']);filters.grid(row=4,column=0,sticky=\'ew\',padx=px(18))\n            box=ttk.Combobox(filters,textvariable=self.kind,values=(\'全部内容\',\'本人发帖\',\'本人回复\',\'类型未确认\'),state=\'readonly\',width=14);box.pack(side=\'left\');box.bind(\'<<ComboboxSelected>>\',lambda _e:self.render_posts())\n            ui_button(filters,\'取消账号筛选\',lambda:(self.accounts.selection_remove(*self.accounts.selection()),self.render_posts())).pack(side=\'left\',padx=px(6))\n            ui_button(filters,\'全选当前筛选\',self.check_all_posts).pack(side=\'left\',padx=px(4))\n            ui_button(filters,\'清空帖子勾选\',self.clear_checked_posts).pack(side=\'left\',padx=px(4))\n            self.post_hint=tk.StringVar();tk.Label(filters,textvariable=self.post_hint,bg=UI[\'bg\'],fg=UI[\'mute\']).pack(side=\'left\')\n            f,self.posts=make_tree(p,(\'checked\',\'name\',\'kind\',\'published\',\'text\',\'views\',\'likes\',\'replies\',\'reposts\',\'rate\',\'observed\'),(\'勾选\',\'账号\',\'类型\',\'发布时间（本机）\',\'内容\',\'浏览量\',\'获赞\',\'收到回复\',\'转发\',\'互动率\',\'指标更新\'),(48,115,75,135,330,85,65,70,65,70,90),height=10,stretch=(\'text\',))\n            f.grid(row=5,column=0,sticky=\'nsew\',padx=px(18),pady=(px(5),px(14)));self.posts.bind(\'<Double-1>\',self.post_double_click)\n            self.posts.bind(\'<Button-1>\',self.post_checkbox_click)\n            self.posts.bind(\'<space>\',self.post_checkbox_space)\n            self.posts.column(\'checked\',width=px(48),minwidth=px(48),stretch=False,anchor=\'center\')\n            self.account_rows=[];self.post_rows=[];self.visible_posts={};self.checked_posts=set()\n            self.build_action_controls()\n\n        def refresh(self,force=False):\n            self.update_actors()\n            account_rows,posts=self.app.store.recent_performance()\n            selected=set(self.app.selected_ids)\n            allowed={browser_id(item) for item in self.app.raw_browsers} & selected\n            account_rows=[r for r in account_rows if r[\'account\'] in allowed]\n            posts=[r for r in posts if r[\'account\'] in allowed]\n            known={r[\'account\'] for r in account_rows}\n            for item in self.app.raw_browsers:\n                aid=browser_id(item)\n                if aid in allowed and aid not in known:\n                    account_rows.append(dict(account=aid,name=browser_name(item),handle=\'\',post_count=0,reply_count=0,unknown_count=0,total_count=0,finished=None,partial=True,posts_state=\'未采集\',replies_state=\'未采集\',views=None,likes=None,replies=None,reposts=None))\n            metric=RECENT_SORT_LABELS[self.metric.get()]\n            sig=(repr(account_rows),repr(posts),metric,int(time.time()//60))\n            if not force and sig==self._sig:return\n            self._sig=sig;keep=self.accounts.selection();self.account_rows=recent_rank(account_rows,metric);self.post_rows=posts\n            self.accounts.delete(*self.accounts.get_children())\n            for r in self.account_rows:\n                counts=[(\'≥\' if r[\'partial\'] and r[\'finished\'] else \'\')+str(r[k]) if r[\'finished\'] else \'未采集\' for k in (\'post_count\',\'reply_count\',\'unknown_count\')]\n                self.accounts.insert(\'\',\'end\',iid=r[\'account\'],values=(r[\'name\'],\'@\'+r[\'handle\'] if r[\'handle\'] else \'—\',*counts,*(recent_metric_text(r,k) for k in RECENT_METRICS),ago(r[\'finished\']) if r[\'finished\'] else \'未采集\',r[\'posts_state\']+\' / \'+r[\'replies_state\']+(\'｜超过15分钟未同步\' if r.get(\'stale\') else \'\')))\n            ids=[k for k in keep if self.accounts.exists(k)]\n            if ids:self.accounts.selection_set(ids)\n            self.hint.set(f\'仅统计账号页勾选账号（未勾选请先到账号与任务页勾选）。最近8小时内发布的内容：{len(posts)}条｜{len(account_rows)}个账号；按{self.metric.get()}降序。≥ 表示已采到的下限，未知不按0处理。\\n本人回复=账号发出的评论；收到回复=该内容获得的评论。指标为采集时累计值，不是8小时内新增；互动率=(赞+回复+转发)/浏览量。看不到的内容无法统计。\')\n            self.render_posts()\n\n        def filtered_posts(self):\n            selected=set(self.accounts.selection());kind={\'本人发帖\':\'post\',\'本人回复\':\'reply\',\'类型未确认\':\'unknown\'}.get(self.kind.get())\n            return recent_rank([r for r in self.post_rows if (not selected or r[\'account\'] in selected) and (not kind or r[\'kind\']==kind)],RECENT_SORT_LABELS[self.metric.get()])\n\n        def render_posts(self):\n            keep=self.posts.selection()\n            self.checked_posts.intersection_update(self.post_key(r) for r in self.post_rows)\n            rows=self.filtered_posts();self.posts.delete(*self.posts.get_children());self.visible_posts={}\n            for i,r in enumerate(self.page_slice(rows)):\n                iid=r[\'account\']+\':\'+r[\'status_id\'];self.visible_posts[iid]=r\n                interactions=[r[k] for k in (\'likes\',\'replies\',\'reposts\')]\n                rate=f\'{sum(interactions)/r["views"]:.2%}\' if r[\'views\'] and all(v is not None for v in interactions) else \'未知\'\n                self.posts.insert(\'\',\'end\',iid=iid,values=(\'☑\' if iid in self.checked_posts else \'☐\',r[\'name\'],{\'post\':\'发帖\',\'reply\':\'回复\',\'unknown\':\'未确认\'}[r[\'kind\']],time.strftime(\'%m-%d %H:%M:%S\',time.localtime(r[\'published_ts\'])),r[\'text\'].replace(\'\\n\',\' \')[:160],*(recent_metric_text(r,k) for k in RECENT_METRICS),rate,ago(r[\'observed_at\'])))\n            self.update_post_check_hint()\n            ids=[i for i in keep if i in self.visible_posts]\n            if ids:self.posts.selection_set(ids)\n\n        @staticmethod\n        def post_key(row):return row[\'account\']+\':\'+row[\'status_id\']\n\n        def checked_post_rows(self):\n            return [r for r in self.post_rows if self.post_key(r) in self.checked_posts]\n\n        def update_post_check_hint(self):\n            visible=set(self.visible_posts)\n            hidden=len(self.checked_posts-visible)\n            self.post_hint.set(f\'已勾选 {len(self.checked_posts)} 条\'+(f\'（当前未显示{hidden}条，仍参与）\' if hidden else \'\')+f\'｜符合筛选 {len(self.filtered_posts())} 条，每页200条；点方框勾选，空格切换高亮行。\')\n\n        def set_post_checks(self,ids,checked):\n            ids=set(ids)&{self.post_key(r) for r in self.post_rows}\n            updated=self.checked_posts|ids if checked else self.checked_posts-ids\n            if len(updated)>100:\n                messagebox.showinfo(\'勾选数量超过上限\',\'每批最多勾选100条帖子，请缩小筛选范围或取消部分勾选。\');return\n            self.checked_posts=updated\n            if ids:self.action_scope.set(\'下表勾选帖子\')\n            for iid in self.visible_posts:self.posts.set(iid,\'checked\',\'☑\' if iid in updated else \'☐\')\n            self.update_post_check_hint()\n\n        def post_checkbox_click(self,event):\n            if self.posts.identify_region(event.x,event.y)!=\'cell\' or self.posts.identify_column(event.x)!=\'#1\':return\n            iid=self.posts.identify_row(event.y)\n            if iid in self.visible_posts:\n                self.posts.focus_set();self.posts.focus(iid)\n                self.set_post_checks((iid,),iid not in self.checked_posts)\n            return \'break\'\n\n        def post_checkbox_space(self,_event=None):\n            ids=[i for i in self.posts.selection() if i in self.visible_posts]\n            if not ids:\n                focus=self.posts.focus()\n                if focus in self.visible_posts:ids=[focus]\n            if ids:self.set_post_checks(ids,not all(i in self.checked_posts for i in ids))\n            return \'break\'\n\n        def post_double_click(self,event):\n            if self.posts.identify_column(event.x)!=\'#1\':self.copy_posts()\n            return \'break\'\n\n        def check_all_posts(self):\n            self.set_post_checks((self.post_key(r) for r in self.filtered_posts()),True)\n\n        def clear_checked_posts(self):self.set_post_checks(tuple(self.checked_posts),False)\n\n        def copy_text(self,text):\n            if not text:messagebox.showinfo(\'暂无目标\',\'先同步最近8小时数据，或选择内容。\');return\n            self.app.root.clipboard_clear();self.app.root.clipboard_append(text)\n            self.app.log(f\'已复制8小时表现目标 {len(text.splitlines())} 条链接，供手动查看和互动。\')\n\n        def copy_posts(self):\n            self.refresh(True)\n            self.copy_text(\'\\n\'.join(r[\'url\'] for r in self.checked_post_rows()))\n\n        def copy_top(self):\n            self.refresh(True)\n            metric=RECENT_SORT_LABELS[self.metric.get()];n=int(self.top_n.get());links=[]\n            for acc in self.account_rows:\n                if acc.get(metric) is None:continue\n                candidates=recent_rank([p for p in self.post_rows if p[\'account\']==acc[\'account\'] and p.get(metric) is not None],metric)\n                if candidates:links.append(candidates[0][\'url\'])\n                if len(links)>=n:break\n            self.copy_text(\'\\n\'.join(links))\n\n        def sync(self):\n            ids=sorted(self.app.selected_ids)\n            self.app.start_recent_sync(ids)\n\n        def export(self):\n            self.refresh(True)\n            path=filedialog.asksaveasfilename(defaultextension=\'.csv\',initialfile=\'最近8小时帖子与回复.csv\',filetypes=[(\'CSV 文件\',\'*.csv\')])\n            if not path:return\n            try:\n                rows=self.filtered_posts();selected=set(self.accounts.selection());accounts=[a for a in self.account_rows if not selected or a[\'account\'] in selected]\n                fields=[\'账号\',\'用户名\',\'8小时发帖数\',\'8小时本人回复数\',\'类型未确认数\',\'账号浏览量合计\',\'账号获赞合计\',\'账号收到回复合计\',\'账号转发合计\',\'帖子覆盖\',\'回复覆盖\',\'类型\',\'发布时间_UTC\',\'内容\',\'浏览量\',\'获赞\',\'收到回复\',\'转发\',\'指标更新时间_UTC\',\'链接\']\n                by_account={}\n                for p in rows:by_account.setdefault(p[\'account\'],[]).append(p)\n                count=0\n                with Path(path).open(\'w\',newline=\'\',encoding=\'utf-8-sig\') as out:\n                    writer=csv.writer(out);writer.writerow(fields)\n                    for a in accounts:\n                        prefix=[a[\'name\'],a[\'handle\'],a[\'post_count\'] if a[\'finished\'] else \'\',a[\'reply_count\'] if a[\'finished\'] else \'\',a[\'unknown_count\'] if a[\'finished\'] else \'\',*(a.get(k) if a.get(k) is not None else \'\' for k in RECENT_METRICS),a[\'posts_state\'],a[\'replies_state\']]\n                        for p in by_account.get(a[\'account\'],[None]):\n                            detail=[p[\'kind\'],datetime.fromtimestamp(p[\'published_ts\'],__import__(\'datetime\').timezone.utc).isoformat(),p[\'text\'],*(p[k] if p[k] is not None else \'\' for k in RECENT_METRICS),datetime.fromtimestamp(p[\'observed_at\'],__import__(\'datetime\').timezone.utc).isoformat(),p[\'url\']] if p else [\'\']*9\n                            # 防止CSV中的帖子正文被Excel当作公式执行。\n                            writer.writerow(["\'"+v if isinstance(v,str) and v.startswith((\'=\',\'+\',\'-\',\'@\',\'\\t\',\'\\r\')) else v for v in prefix+detail]);count+=1\n                messagebox.showinfo(\'导出完成\',f\'已导出 {count} 行；包含采集覆盖状态，未知指标留空。\')\n            except Exception as exc:messagebox.showerror(\'导出失败\',str(exc))\n\n\n\n\n\n\n        def action_report(self):\n            win=tk.Toplevel(self.app.root);win.title(\'榜单互动结果与待核对\');win.geometry(f\'{px(1150)}x{px(720)}\')\n            win.configure(bg=UI[\'bg\']);hint(win,\'先在网页核对实际状态，再使用底部核对按钮；待核对项目不会自动重试。\').pack(fill=\'x\',padx=px(12),pady=px(8))\n            hint(win,\'逐帖目标：已确认包含原已完成；处理中及待核对占名额。缺额不等于失败，任务结束后仍有缺额则未完成目标。\').pack(fill=\'x\',padx=px(12))\n            f,progress_tree=make_tree(win,(\'target\',\'like\',\'repost\',\'comment\',\'pending\',\'missing\'),(\'帖子ID\',\'点赞 已确认/目标\',\'转发 已确认/目标\',\'评论 已确认/目标\',\'处理中／待核对\',\'缺额\'),(180,170,170,170,160,100),height=7,stretch=(\'target\',));f.pack(fill=\'x\',padx=px(12),pady=px(6))\n            f,tree=make_tree(win,(\'actor\',\'action\',\'target\',\'state\',\'reason\',\'time\'),(\'执行账号\',\'操作\',\'帖子ID\',\'结果\',\'说明\',\'更新时间\'),(150,70,160,85,390,130),stretch=(\'reason\',));f.pack(fill=\'both\',expand=True,padx=px(12))\n            names={browser_id(i):browser_name(i) for i in self.app.raw_browsers};records={};ledger=RecentInteractionStore(self.app.store)\n            def refresh():\n                keep=tree.selection()\n                records.clear();tree.delete(*tree.get_children());progress_tree.delete(*progress_tree.get_children())\n                grouped={}\n                for row in ledger.progress():grouped.setdefault(row[\'target\'],{})[row[\'action\']]=row\n                for target,items in grouped.items():\n                    cells=[f"{items[k][\'done\']}/{items[k][\'goal\']}" if k in items and items[k][\'goal\'] else \'关闭\' for k in RECENT_ACTION_NAMES]\n                    active=[r for r in items.values() if r[\'goal\']]\n                    progress_tree.insert(\'\',\'end\',iid=target,values=(target,*cells,f"{sum(r[\'reserved\'] for r in active)} / {sum(r[\'unknown\'] for r in active)}",sum(r[\'missing\'] for r in active)))\n                for row in ledger.rows():\n                    iid=json.dumps((row[\'actor\'],row[\'target\'],row[\'action\']));records[iid]=row;tree.insert(\'\',\'end\',iid=iid,values=(names.get(row[\'actor\'],row[\'actor\'][:8]),RECENT_ACTION_NAMES[row[\'action\']],row[\'target\'],RECENT_ACTION_STATES.get(row[\'state\'],row[\'state\']),row[\'error\'],time.strftime(\'%m-%d %H:%M:%S\',time.localtime(row[\'updated\']))))\n                keep=[i for i in keep if tree.exists(i)]\n                if keep:tree.selection_set(keep)\n            def resolve(executed):\n                if self.app.running:messagebox.showinfo(\'任务执行中\',\'请在任务结束或停止后核对，避免改动正在提交的项目。\');return\n                for iid in tree.selection():\n                    row=records[iid];ledger.resolve(row[\'actor\'],row[\'target\'],row[\'action\'],executed)\n                refresh()\n            def copy():\n                urls=[records[i][\'url\'] for i in tree.selection()]\n                if urls:self.app.root.clipboard_clear();self.app.root.clipboard_append(\'\\n\'.join(urls))\n            foot=tk.Frame(win,bg=UI[\'bg\']);foot.pack(fill=\'x\',padx=px(12),pady=px(10))\n            for label,fn in ((\'刷新\',refresh),(\'复制目标链接\',copy),(\'已核对：执行成功\',lambda:resolve(True)),(\'已核对：未执行，可重试\',lambda:resolve(False))):ui_button(foot,label,fn).pack(side=\'left\',padx=px(4))\n            refresh()\n            def tick():\n                if not win.winfo_exists():return\n                refresh()\n                win.after(1500,tick)\n            win.after(1500,tick)\n\n    base = LegacyRecentPerformancePage\n\n    class RecentPerformancePage(base):\n        subtitle = \'统计范围与执行账号池独立；先筛选内容，再选择执行账号并预览计划\'\n\n        def build_action_controls(self):\n            saved = self.app.settings.recent_actions\n            stored = saved.get(\'execution_ids\', ())\n            self.execution_ids = set(stored) if isinstance(stored, (list, tuple)) and all(isinstance(i, str) for i in stored) else set()\n            self.action_scope = tk.StringVar(value=saved.get(\'scope\', \'下表勾选帖子\'))\n            self.action_limits = {k: tk.StringVar(value=str(saved.get(k, 1))) for k in api.RECENT_ACTION_NAMES}\n            self.action_interval = tk.StringVar(value=str(saved.get(\'interval\', 60)))\n            self.action_comment_interval = tk.StringVar(value=str(saved.get(\'comment_interval\', 300)))\n            self.action_comment_file = tk.StringVar(value=saved.get(\'comment_file\', self.app.settings.comment[\'comment_file\']))\n            self.actor_note = tk.StringVar()\n            self.progress_note = tk.StringVar(value=\'选择目标与执行池后，可预览任务；待核对项目不会自动重发。\')\n            panel = ttk.LabelFrame(self.frame, text=\'独立执行计划\', padding=8)\n            panel.grid(row=6, column=0, sticky=\'ew\', padx=api.px(18), pady=6)\n            panel.columnconfigure(1, weight=1)\n            top = ttk.Frame(panel); top.grid(row=0, column=0, columnspan=2, sticky=\'ew\')\n            ttk.Label(top, textvariable=self.actor_note).pack(side=\'left\')\n            ttk.Button(top, text=\'选择执行账号池\', command=self.choose_actors).pack(side=\'right\', padx=5)\n            ttk.Combobox(top, textvariable=self.action_scope, values=(\'下表勾选帖子\', \'前N账号最佳内容\'), state=\'readonly\', width=18).pack(side=\'right\')\n            limits = ttk.Frame(panel); limits.grid(row=1, column=0, columnspan=2, sticky=\'ew\', pady=6)\n            for k, title in api.RECENT_ACTION_NAMES.items():\n                ttk.Label(limits, text=\'每帖\'+title).pack(side=\'left\')\n                ttk.Spinbox(limits, from_=0, to=1 if k==\'comment\' else 100, textvariable=self.action_limits[k], width=4).pack(side=\'left\', padx=(3,12))\n            for title, var in ((\'动作间隔/秒\', self.action_interval), (\'评论间隔/秒\', self.action_comment_interval)):\n                ttk.Label(limits, text=title).pack(side=\'left\')\n                ttk.Entry(limits, textvariable=var, width=6).pack(side=\'left\', padx=4)\n            ttk.Label(panel, text=\'评论TXT\').grid(row=2, column=0)\n            picker_host = tk.Frame(panel, bg=api.UI[\'bg\'])\n            picker_host.grid(row=2, column=1, sticky=\'ew\')\n            api.FilePicker(picker_host, self.action_comment_file, \'选择评论TXT\').pack(fill=\'x\')\n            buttons = ttk.Frame(panel); buttons.grid(row=3, column=0, columnspan=2, sticky=\'ew\', pady=6)\n            for k, title in ((\'like\',\'点赞\'), (\'repost\',\'转发\'), (\'comment\',\'评论\'), (\'all\',\'执行组合\')):\n                ttk.Button(buttons, text=title, command=lambda kind=k: self.start_actions(kind)).pack(side=\'left\', padx=3)\n            ttk.Button(buttons, text=\'预览计划\', command=lambda: self.preview(\'all\')).pack(side=\'left\', padx=3)\n            ttk.Button(buttons, text=\'结果与待核对\', command=self.action_report).pack(side=\'left\', padx=3)\n            ttk.Label(panel, textvariable=self.progress_note, wraplength=950).grid(row=4, column=0, columnspan=2, sticky=\'ew\')\n            self.page_index = 0\n            self.page_label = tk.StringVar()\n            self.search = tk.StringVar()\n            filters = ttk.Frame(self.frame)\n            filters.grid(row=7, column=0, sticky=\'ew\', padx=api.px(18), pady=4)\n            ttk.Label(filters, text=\'内容搜索\').pack(side=\'left\')\n            ttk.Entry(filters, textvariable=self.search, width=32).pack(side=\'left\', padx=6)\n            self.search.trace_add(\'write\', lambda *_: self.change_page(0, reset=True))\n            ttk.Button(filters, text=\'上一页\', width=6, command=lambda: self.change_page(-1)).pack(side=\'left\')\n            ttk.Label(filters, textvariable=self.page_label).pack(side=\'left\', padx=4)\n            ttk.Button(filters, text=\'下一页\', width=6, command=lambda: self.change_page(1)).pack(side=\'left\')\n\n        def page_slice(self, rows):\n            pages = max(1, (len(rows)+199)//200)\n            self.page_index = min(max(0, self.page_index), pages-1)\n            self.page_label.set(f\'{self.page_index+1}/{pages}\')\n            return rows[self.page_index*200:(self.page_index+1)*200]\n\n        def change_page(self, delta, reset=False):\n            self.page_index = 0 if reset else self.page_index + delta\n            self.render_posts()\n\n        def filtered_posts(self):\n            rows = super().filtered_posts()\n            query = self.search.get().strip().casefold() if hasattr(self, \'search\') else \'\'\n            return [r for r in rows if not query or query in \' \'.join(str(r.get(k, \'\')) for k in (\'text\',\'handle\',\'name\',\'status_id\')).casefold()]\n\n        def choose_actors(self):\n            win = tk.Toplevel(self.app.root)\n            win.title(\'执行账号池 · 与统计账号独立\')\n            win.geometry(\'620x520\')\n            api.hint(win, \'选择你管理的账号环境。运行时读取实际X身份；重复身份停止，本人帖子跳过。\').pack(fill=\'x\', padx=12, pady=10)\n            container = api.ScrollFrame(win)\n            container.pack(fill=\'both\', expand=True, padx=12)\n            body = getattr(container, \'inner\', None)\n            if body is None: body = getattr(container, \'body\', container)\n            choices = {}\n            for item in self.app.raw_browsers:\n                aid = api.browser_id(item)\n                if not aid or aid.startswith(\'demo:\') or aid in choices: continue\n                var = tk.BooleanVar(value=aid in self.execution_ids)\n                choices[aid] = var\n                ttk.Checkbutton(body, text=f\'{api.browser_name(item)}  [{aid[:12]}]\', variable=var).pack(anchor=\'w\', pady=3)\n            def save():\n                self.execution_ids = {aid for aid, var in choices.items() if var.get()}\n                self.app.settings.recent_actions[\'execution_ids\'] = sorted(self.execution_ids)\n                self.app.try_save(\'独立执行账号池\')\n                self.update_actors()\n                win.destroy()\n            ttk.Button(win, text=\'保存执行账号池\', command=save).pack(pady=12)\n\n        def update_actors(self):\n            progress = [r for r in api.RecentInteractionStore(self.app.store).progress() if r[\'goal\']]\n            if progress:\n                done = sum(r[\'done\'] for r in progress)\n                goal = sum(r[\'goal\'] for r in progress)\n                unknown = sum(r[\'unknown\'] for r in progress)\n                missing = sum(r[\'missing\'] for r in progress)\n                self.progress_note.set(f\'最近任务：已确认 {done}/{goal} · 待核对 {unknown} · 未分配缺额 {missing}；待核对不计为成功\')\n            valid = {api.browser_id(i) for i in self.app.raw_browsers}\n            self.actor_note.set(f\'独立执行池：{len(self.execution_ids & valid)}个环境（统计勾选不改变执行池）\')\n\n        def prepare_plan(self, kind):\n            self.refresh(True)\n            execution = api.recent_execution_accounts(self.app.raw_browsers, \'仅账号页勾选\', self.execution_ids)\n            limits = {k: int(v.get()) if kind in (\'all\', k) else 0 for k, v in self.action_limits.items()}\n            rows = self.checked_post_rows() if self.action_scope.get() == \'下表勾选帖子\' else api.recent_best_targets(self.account_rows, self.post_rows, api.RECENT_SORT_LABELS[self.metric.get()], int(self.top_n.get()))\n            plan = build_plan([api.browser_id(i) for i in execution], api.freeze_recent_targets(rows), limits, float(self.action_interval.get()), float(self.action_comment_interval.get()))\n            if limits[\'comment\']:\n                api.load_draft_lines(self.action_comment_file.get().strip())\n            return plan\n\n        def preview(self, kind):\n            try:\n                plan = self.prepare_plan(kind)\n                messagebox.showinfo(\'本次任务计划\', plan.summary(), parent=self.app.root)\n            except (ValueError, TypeError, OSError) as exc:\n                messagebox.showwarning(\'计划未就绪\', str(exc), parent=self.app.root)\n\n        def start_actions(self, kind):\n            try:\n                plan = self.prepare_plan(kind)\n                settings = dict(self.app.settings.recent_actions)\n                settings.update(execution_ids=list(plan.actors), scope=self.action_scope.get(), interval=plan.interval,\n                                comment_interval=plan.comment_interval, comment_file=self.action_comment_file.get().strip(), **dict(plan.limits))\n                self.app.start_recent_actions(plan.actors, plan.targets, dict(plan.limits), plan.interval, plan.comment_interval, settings[\'comment_file\'], settings)\n            except (ValueError, TypeError, OSError) as exc:\n                messagebox.showwarning(\'无法启动\', str(exc), parent=self.app.root)\n    return RecentPerformancePage\n', 'xmanager_ui', "exec"), _embed_mod.__dict__)

import sys as _sys


# ======================================================================
# 模块：xmanager/config.py
# ======================================================================
"""全局常量、数据目录、日志与结果枚举。

所有可由环境变量调整的参数都集中在这里；导入本模块没有副作用，
目录创建与日志初始化由 `setup_runtime()` 在程序入口调用一次。
"""


import faulthandler
import logging
import math
import os
import sys
import threading
from enum import Enum
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Dict

APP_NAME = "X 浏览器任务管理器"
APP_VERSION = "11.0.1"


def env_number(name: str, default: float, low: float, high: float) -> float:
    try:
        value = float(os.environ.get(name, str(default)))
        return min(high, max(low, value)) if math.isfinite(value) else default
    except (TypeError, ValueError):
        return default


# ============================================================
# 网络与并发
# ============================================================
BIT_API = os.environ.get("BIT_API", "http://127.0.0.1:54345")
TWITTER_HOME_URL = "https://x.com/home"

MAX_ACTIVE_BROWSERS = 5  # 最高 5 并发；按固定槽位有序排列
DEFAULT_DURATION_MIN = 20.0  # 仅首次启动时的输入框默认值；每批使用用户填写的时长
DEFAULT_CONCURRENCY = int(env_number("DEFAULT_CONCURRENCY", 2, 1, MAX_ACTIVE_BROWSERS))
NET_SCALE = env_number("NET_SCALE", 2, 0.5, 5)
LAUNCH_STAGGER = env_number("LAUNCH_STAGGER", 6, 0, 60)
STOP_GRACE_SEC = env_number("STOP_GRACE_SEC", 4, 0, 30)
EXIT_JOIN_SEC = 30
MAX_RECONNECTS = 3
RECONNECT_RESET_SEC = 300
SLEEP_SLICE = 0.25
CONTEXT_WAIT_SEC = 8.0
CLOSE_WAIT_SEC = int(8 * NET_SCALE) + 5
MAX_LOG_LINES = 2000
SEEN_LIMIT = 2000
MAX_RELOADS = 3
BOUNDS_DIVIDE_BY_DPI = os.environ.get("BOUNDS_DIVIDE_BY_DPI", "0") == "1"


def T(ms: int) -> int:
    """按网络倍率放大超时（毫秒）。"""
    return int(ms * NET_SCALE)


# ============================================================
# 路径（程序目录旁的 x_warmup_data，与旧版本保持一致）
# ============================================================
def _base_dir() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    here = Path(__file__).resolve().parent
    return here.parent if here.name == "xmanager" else here


BASE_DIR = _base_dir()
DATA_DIR = Path(os.environ.get("X_WARMUP_DATA_DIR", str(BASE_DIR / "x_warmup_data"))).expanduser().resolve()
LOG_DIR = DATA_DIR / "logs"
CONFIG_PATH = DATA_DIR / "config.json"
HISTORY_PATH = DATA_DIR / "history.jsonl"
BATCH_PATH = DATA_DIR / "last_batch.json"
REPORT_DIR = DATA_DIR / "workflow_reports"

logger = logging.getLogger("warmup")
PLAYWRIGHT_START_LOCK = threading.Lock()
_runtime_ready = False


def setup_runtime() -> None:
    """创建数据目录、滚动日志、崩溃转储与未捕获异常记录（幂等）。"""
    global _runtime_ready
    if _runtime_ready:
        return
    _runtime_ready = True
    for folder in (DATA_DIR, LOG_DIR):
        folder.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        str(LOG_DIR / "warmup.log"), maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(logging.Formatter("%(asctime)s [%(levelname)s] %(message)s"))
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    try:
        fatal = open(LOG_DIR / "fatal.log", "a", encoding="utf-8")
        faulthandler.enable(file=fatal, all_threads=True)
    except Exception:
        logger.warning("启用 faulthandler 失败", exc_info=True)

    def log_uncaught(exc_type, exc, tb) -> None:
        logger.critical("未捕获异常", exc_info=(exc_type, exc, tb))

    def log_thread_uncaught(args) -> None:
        name = args.thread.name if args.thread else "?"
        logger.critical(
            "线程 %s 未捕获异常", name, exc_info=(args.exc_type, args.exc_value, args.exc_traceback)
        )

    sys.excepthook = log_uncaught
    threading.excepthook = log_thread_uncaught


# ============================================================
# 页面选择器
# ============================================================
SELECTORS: Dict[str, str] = {
    "tweet": 'article[data-testid="tweet"]',
    "tweet_text": '[data-testid="tweetText"]',
    "user_avatar": '[data-testid="Tweet-User-Avatar"]',
    "user_name": '[data-testid="User-Name"]',
    "photo": '[data-testid="tweetPhoto"]',
    "video": '[data-testid="videoPlayer"], [data-testid="videoComponent"]',
    "video_mute": '[aria-label*="mute" i], [aria-label*="静音" i]',
    "show_more_text": 'button:has-text("Show more"), button:has-text("展开")',
    "show_replies": 'button:has-text("Show replies"), button:has-text("显示回复"), button:has-text("Show probable spam")',
    "for_you_tab": 'div[role="tablist"] a[href="/home"], [role="tab"]:has-text("For you"), [role="tab"]:has-text("为你推荐")',
    "like": '[data-testid="like"]',
    "close_viewer": '[aria-label="Close"], [aria-label="关闭"], [data-testid="app-bar-close"]',
    "next_slide": '[aria-label="Next slide"], [aria-label="下一张"]',
    "status_link": 'a[href*="/status/"]:has(time)',
    "error_text": '[data-testid="error-detail"]:visible, [data-testid="error-state"]:visible',
}


# ============================================================
# 单账号运行结果
# ============================================================
class Result(str, Enum):
    OK = "OK"
    PLAN_DONE = "PLAN_DONE"
    NO_CONTENT = "NO_CONTENT"
    PARTIAL = "PARTIAL"
    STOPPED = "STOPPED"
    CANCELLED = "CANCELLED"
    LOGIN_LOST = "LOGIN_LOST"
    NEEDS_ACTION = "NEEDS_ACTION"
    LAUNCH_FAILED = "LAUNCH_FAILED"
    PAGE_CLOSED = "PAGE_CLOSED"
    CDP_LOST = "CDP_LOST"
    ERROR = "ERROR"


# 结果 -> (界面文字, 色调)
_RESULT_META = {
    Result.OK: ("✔ 时长预算结束", "ok"),
    Result.PLAN_DONE: ("✔ 工作流计划结束", "ok"),
    Result.NO_CONTENT: ("○ 无匹配内容", "warn"),
    Result.PARTIAL: ("△ 部分工作流失败", "warn"),
    Result.STOPPED: ("■ 已停止", "warn"),
    Result.CANCELLED: ("○ 已取消排队", "warn"),
    Result.LOGIN_LOST: ("✖ 登录失效", "bad"),
    Result.NEEDS_ACTION: ("✖ 需人工处理", "bad"),
    Result.LAUNCH_FAILED: ("✖ 启动失败", "bad"),
    Result.PAGE_CLOSED: ("✖ 页面被关闭", "warn"),
    Result.CDP_LOST: ("✖ CDP 断连", "bad"),
    Result.ERROR: ("✖ 异常退出", "bad"),
}
RESULT_LABEL = {result: meta[0] for result, meta in _RESULT_META.items()}
RESULT_TONE = {result: meta[1] for result, meta in _RESULT_META.items()}
SUCCESS_RESULTS = (Result.OK, Result.PLAN_DONE)


# ======================================================================
# 模块：xmanager/deps.py
# ======================================================================
"""第三方依赖统一入口：缺包时给出一条可执行的安装提示。"""

try:
    import requests
    from playwright.sync_api import Page, sync_playwright
    from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
    from requests.adapters import HTTPAdapter
except ImportError as exc:  # pragma: no cover - 取决于运行环境
    raise SystemExit("缺少依赖，请执行：python -m pip install requests playwright\n" + str(exc)) from exc

__all__ = ["requests", "HTTPAdapter", "Page", "sync_playwright", "PlaywrightTimeoutError"]


# ======================================================================
# 模块：xmanager/errors.py
# ======================================================================
"""执行流程中使用的异常类型。"""




class StopRequested(Exception):
    """用户点击停止，或程序正在退出。"""


class DurationReached(Exception):
    """单号有效时长已用完。"""


class CdpStateError(Exception):
    """CDP 连接断开或浏览器状态异常。"""


class SceneBudgetExceeded(Exception):
    """单个场景的时间预算已用完。"""


class ContentUnavailable(Exception):
    """当前页面没有可执行的内容。"""


class PageNotReady(ContentUnavailable):
    """页面加载/重绘延迟；可有限暂缓，不视作执行故障。"""


class FeatureUnavailable(ContentUnavailable):
    def __init__(self, family, reason):
        self.family = family
        super().__init__(reason)


class GlobalCommentConflict(ContentUnavailable):
    """目标或文本已被其他账号占用（全局去重）。"""


class AccountStateError(Exception):
    def __init__(self, result: Result):
        self.result = result
        super().__init__(result.value)


class CommentRejected(Exception):
    """服务端明确拒绝；与已提交但无法确认的结果分开记录。"""

    def __init__(self, status, errors):
        self.status, self.errors = status, errors
        super().__init__(f"HTTP {status}：{errors}")


# 这些异常必须逐层上抛，不能被普通故障处理吞掉。
FATAL_ERRORS = (StopRequested, DurationReached, CdpStateError, AccountStateError)


# ======================================================================
# 模块：xmanager/layout.py
# ======================================================================
"""屏幕几何、DPI 与浏览器窗口排列。"""


import ctypes
import math
import sys
import threading
from functools import lru_cache
from typing import Tuple



def enable_dpi_awareness() -> None:
    if sys.platform != "win32":
        return
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:
        try:
            ctypes.windll.user32.SetProcessDPIAware()
        except Exception:
            pass


def get_dpi_scale() -> float:
    if sys.platform == "win32":
        try:
            return max(1.0, ctypes.windll.user32.GetDpiForSystem() / 96.0)
        except Exception:
            pass
    return 1.0


@lru_cache(maxsize=1)
def get_work_area() -> Tuple[int, int, int, int]:
    if sys.platform == "win32":
        try:
            from ctypes import wintypes

            rect = wintypes.RECT()
            if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                w, h = rect.right - rect.left, rect.bottom - rect.top
                if w > 0 and h > 0:
                    return rect.left, rect.top, w, h
        except Exception:
            pass
    try:
        import tkinter as tk

        root = tk.Tk()
        root.withdraw()
        w, h = root.winfo_screenwidth(), root.winfo_screenheight()
        root.destroy()
        return 0, 0, max(1, w), max(1, h - 45)
    except Exception:
        return 0, 0, 1920, 1035


class ScreenLayoutManager:
    @staticmethod
    def plan(count, mode="cascade", work_area=None):
        if type(count) is not int or not 1 <= count <= MAX_ACTIVE_BROWSERS:
            raise ValueError("窗口数量必须为1～5")
        if mode not in ("cascade", "tile"):
            raise ValueError("窗口排列方式无效")
        left, top, width, height = work_area if work_area is not None else get_work_area()
        if width < 100 or height < 100:
            raise ValueError("屏幕可用区域过小")
        margin = min(12, max(0, min(width, height) // 20))
        x, y, w, h = left + margin, top + margin, width - margin * 2, height - margin * 2
        gap = 8
        if mode == "tile":
            scale = get_dpi_scale() if sys.platform == "win32" else 1.0
            # 按行排序，统一尺寸；不强行挤出小于浏览器最小尺寸的格子。
            candidates = []
            for cols in range(1, count + 1):
                rows = math.ceil(count / cols)
                cw, ch = (w - gap * (cols - 1)) // cols, (h - gap * (rows - 1)) // rows
                if cw >= 560 * scale and ch >= 320 * scale:
                    candidates.append((cols, rows, cw, ch))
            if candidates:
                cols, rows, cw, ch = min(
                    candidates, key=lambda v: (v[0] * v[1] - count, abs(v[2] / v[3] - 1.5))
                )
                group_w, group_h = cols * cw + (cols - 1) * gap, rows * ch + (rows - 1) * gap
                ox, oy = x + (w - group_w) // 2, y + (h - group_h) // 2
                rects = [
                    {
                        "left": ox + (i % cols) * (cw + gap),
                        "top": oy + (i // cols) * (ch + gap),
                        "width": cw,
                        "height": ch,
                    }
                    for i in range(count)
                ]
                return "tile", rects
        # 堆叠时保留标题栏，统一大小；整个窗口组在工作区居中。
        step = min(32, max(8, min(w, h) // 20)) if count > 1 else 0
        offset = step * (count - 1)
        ww, hh = min(1100, w - offset), min(780, h - offset)
        ox, oy = x + (w - ww - offset) // 2, y + (h - hh - offset) // 2
        return "cascade", [
            {"left": ox + i * step, "top": oy + i * step, "width": ww, "height": hh} for i in range(count)
        ]

    @staticmethod
    def calculate_bounds(slot_idx, count, work_area=None, mode="cascade"):
        if type(slot_idx) is not int or not 0 <= slot_idx < count:
            raise ValueError("窗口槽位超出范围")
        return ScreenLayoutManager.plan(count, mode, work_area)[1][slot_idx]

    @staticmethod
    def position_name(slot_idx, count, mode="cascade"):
        effective, _ = ScreenLayoutManager.plan(count, mode)
        return f"堆叠第{slot_idx + 1}层" if effective == "cascade" else f"平铺第{slot_idx + 1}格"

    @staticmethod
    def to_cdp_bounds(bounds):
        # CDP 的窗口坐标为逻辑单位；工作区与 Win32 位置统一使用物理像素。
        scale = get_dpi_scale() if sys.platform == "win32" or BOUNDS_DIVIDE_BY_DPI else 1.0
        return {k: round(v / scale) for k, v in bounds.items()}

    @staticmethod
    def from_cdp_bounds(bounds):
        scale = get_dpi_scale() if sys.platform == "win32" or BOUNDS_DIVIDE_BY_DPI else 1.0
        return {
            k: round(v * scale)
            if k in ("left", "top", "width", "height") and isinstance(v, (int, float))
            else v
            for k, v in bounds.items()
        }


class NativeBrowserWindows:
    """仅匹配已登记浏览器PID；不按标题模糊匹配其他应用。"""

    def __init__(self):
        self.api = None
        if sys.platform != "win32":
            return
        try:
            from ctypes import wintypes

            self.wt = wintypes
            self.api = ctypes.WinDLL("user32", use_last_error=True)
            self.callback_type = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
            signatures = {
                "EnumWindows": ([self.callback_type, wintypes.LPARAM], wintypes.BOOL),
                "GetWindowThreadProcessId": ([wintypes.HWND, ctypes.POINTER(wintypes.DWORD)], wintypes.DWORD),
                "IsWindowVisible": ([wintypes.HWND], wintypes.BOOL),
                "IsWindow": ([wintypes.HWND], wintypes.BOOL),
                "GetClassNameW": ([wintypes.HWND, wintypes.LPWSTR, ctypes.c_int], ctypes.c_int),
                "GetWindow": ([wintypes.HWND, wintypes.UINT], wintypes.HWND),
                "SetWindowPos": (
                    [
                        wintypes.HWND,
                        wintypes.HWND,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        ctypes.c_int,
                        wintypes.UINT,
                    ],
                    wintypes.BOOL,
                ),
            }
            for name, (args, result) in signatures.items():
                method = getattr(self.api, name)
                method.argtypes = args
                method.restype = result
        except Exception:
            self.api = None
            logger.warning("Windows 窗口整理不可用，将使用CDP定位", exc_info=True)

    def find(self, pid):
        if self.api is None or not pid:
            return None
        found = []

        def callback(hwnd, _):
            process = self.wt.DWORD()
            self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
            if process.value == pid and self.api.IsWindowVisible(hwnd) and not self.api.GetWindow(hwnd, 4):
                name = ctypes.create_unicode_buffer(256)
                self.api.GetClassNameW(hwnd, name, 256)
                if name.value.startswith("Chrome_WidgetWin_"):
                    found.append(int(hwnd))
            return True

        wrapped = self.callback_type(callback)
        self.api.EnumWindows(wrapped, 0)
        # 同进程存在多个独立窗口时交给CDP精确定位，避免移动错窗口。
        return found[0] if len(found) == 1 else None

    def valid(self, hwnd):
        return bool(self.api and hwnd and self.api.IsWindow(hwnd))

    def owns(self, hwnd, pid):
        if not self.valid(hwnd):
            return False
        process = self.wt.DWORD()
        self.api.GetWindowThreadProcessId(hwnd, ctypes.byref(process))
        return process.value == pid

    def move(self, hwnd, bounds):
        if not self.valid(hwnd):
            return False
        return bool(
            self.api.SetWindowPos(
                hwnd,
                None,
                bounds["left"],
                bounds["top"],
                bounds["width"],
                bounds["height"],
                0x0010 | 0x0004 | 0x4000,
            )
        )

    def below(self, hwnd, above):
        if not self.valid(hwnd) or not self.valid(above) or hwnd == above:
            return False
        # 只调整本轮浏览器的相对层次，不置顶、不激活，也不改变其他应用的前台状态。
        return bool(self.api.SetWindowPos(hwnd, above, 0, 0, 0, 0, 0x0010 | 0x0001 | 0x0002 | 0x4000))


class WindowOrderManager:
    def __init__(self, native=None):
        self.native = native if native is not None else NativeBrowserWindows()
        self.lock = threading.RLock()
        self.records = {}
        self.count = MAX_ACTIVE_BROWSERS
        self.mode = "cascade"
        self.area = get_work_area()
        self.version = 0

    def reset(self, count, mode):
        with self.lock:
            self.count, self.mode, self.area = (
                count,
                mode,
                getattr(get_work_area, "__wrapped__", get_work_area)(),
            )
            self.records.clear()
            self.version += 1

    def snapshot(self, slot):
        with self.lock:
            effective, rects = ScreenLayoutManager.plan(self.count, self.mode, self.area)
            return self.version, effective, dict(rects[slot])

    def register(self, bid, slot, pid=None):
        hwnd = self.native.find(pid)
        with self.lock:
            self.records[bid] = {"slot": slot, "pid": pid, "hwnd": hwnd}
            self._apply_native(True)
        return bool(hwnd)

    def unregister(self, bid):
        with self.lock:
            self.records.pop(bid, None)
            self._apply_native(False)

    def request(self, mode, area=None):
        with self.lock:
            self.mode = mode
            if area is not None:
                self.area = area
            self.version += 1
            self._apply_native(True)
            effective, _ = ScreenLayoutManager.plan(self.count, self.mode, self.area)
            return len(self.records), effective

    def restack(self):
        with self.lock:
            self._apply_native(False)

    def relayout_native(self):
        with self.lock:
            self._apply_native(True)

    def _apply_native(self, geometry):
        _, rects = ScreenLayoutManager.plan(self.count, self.mode, self.area)
        ordered = sorted(self.records.values(), key=lambda r: r["slot"], reverse=True)
        above = None
        for record in ordered:
            hwnd = record["hwnd"]
            if not self.native.valid(hwnd):
                continue
            if record["pid"] and not self.native.owns(hwnd, record["pid"]):
                continue
            if geometry:
                self.native.move(hwnd, rects[record["slot"]])
            if above is not None:
                self.native.below(hwnd, above)
            above = hwnd


# ======================================================================
# 模块：xmanager/bitclient.py
# ======================================================================
"""比特浏览器本地接口客户端。"""


import threading
import time
from typing import TYPE_CHECKING, Any, Callable, Dict, List, Optional, Set
from urllib.parse import urlparse


if TYPE_CHECKING:  # pragma: no cover
    pass


class BitClient:
    def __init__(self, base: str):
        parsed = urlparse(base)
        if parsed.scheme not in ("http", "https") or not parsed.hostname:
            raise ValueError("BIT_API 必须是 http(s) 地址")
        self.base = base.rstrip("/")
        self._local = threading.local()
        self.launch_lock = threading.Lock()
        self._next_launch = 0.0

    @property
    def session(self):
        if not hasattr(self._local, "session"):
            session = requests.Session()
            session.trust_env = False
            # 启动/关闭接口绝不自动重发，超时由外层重新探测状态。
            adapter = HTTPAdapter(max_retries=0, pool_connections=4, pool_maxsize=4)
            session.mount("http://", adapter)
            session.mount("https://", adapter)
            self._local.session = session
        return self._local.session

    def close_thread_session(self) -> None:
        session = getattr(self._local, "session", None)
        if session is not None:
            session.close()
            del self._local.session

    def _post(self, path: str, payload: Dict[str, Any], timeout: float = 15) -> Dict[str, Any]:
        try:
            resp = self.session.post(f"{self.base}{path}", json=payload, timeout=(3.0, timeout))
            if resp.status_code != 200:
                return {"success": False, "msg": f"HTTP {resp.status_code}"}
            data = resp.json()
            return data if isinstance(data, dict) else {"success": False, "msg": "接口返回格式错误"}
        except Exception as ex:
            return {"success": False, "msg": f"{type(ex).__name__}: {ex}"}

    def list_browsers(self, page_size: int = 100, max_pages: int = 100) -> List[Dict[str, Any]]:
        result: List[Dict[str, Any]] = []
        seen_ids: Set[str] = set()
        for page in range(max_pages):
            res = self._post(
                "/browser/list",
                {"page": page, "pageSize": page_size},
                timeout=int(10 * NET_SCALE),
            )
            if not res.get("success"):
                raise RuntimeError(res.get("msg") or "获取列表失败")
            data = res.get("data", {})
            items = data.get("list", []) if isinstance(data, dict) else data
            if not isinstance(items, list) or not items:
                break
            new = 0
            for it in items:
                if not isinstance(it, dict):
                    continue
                bid = str(it.get("id") or it.get("browserId") or "")
                if bid and bid not in seen_ids:
                    seen_ids.add(bid)
                    result.append(it)
                    new += 1
            if new == 0 or len(items) < page_size:
                break
        return result

    def probe_running(self, browser_id: str) -> Optional[bool]:
        res = self._post("/browser/pids", {"ids": [browser_id]}, timeout=5)
        if not res.get("success"):
            return None
        data = res.get("data")
        if isinstance(data, dict):
            return bool(data.get(browser_id))
        return None

    def browser_pid(self, browser_id):
        res = self._post("/browser/pids", {"ids": [browser_id]}, timeout=5)
        data = res.get("data")
        value = data.get(browser_id) if res.get("success") and isinstance(data, dict) else None
        return (
            int(value)
            if type(value) is int
            and value > 0
            or isinstance(value, str)
            and value.isdigit()
            and int(value) > 0
            else None
        )

    def close(self, browser_id: str) -> bool:
        res = self._post("/browser/close", {"id": browser_id}, timeout=int(8 * NET_SCALE))
        return bool(res.get("success"))

    @staticmethod
    def _extract_endpoint(res: Dict[str, Any]) -> Optional[str]:
        data = res.get("data")
        if not (res.get("success") and isinstance(data, dict)):
            return None
        http_val = data.get("http")
        if http_val:
            value = str(http_val).strip()
            if value.isdigit():
                value = f"127.0.0.1:{value}"
            if ":" in value:
                return value if value.startswith(("http://", "https://")) else f"http://{value}"
        ws = data.get("ws") or data.get("wsUrl") or data.get("webSocketDebuggerUrl")
        return str(ws) if ws else None

    def ensure_browser_running(
        self,
        browser_id: str,
        bounds: Dict[str, int],
        ctl: RunControl,
        rec: LaunchRecord,
        log_cb: Callable[[str], None],
        max_wait: float = 75 * NET_SCALE,
    ) -> str:
        launch_bounds = ScreenLayoutManager.to_cdp_bounds(bounds)
        payload = {
            "id": browser_id,
            "headless": False,
            "loadExtensions": True,
            "args": [
                "--mute-audio",
                f"--window-size={launch_bounds['width']},{launch_bounds['height']}",
                f"--window-position={launch_bounds['left']},{launch_bounds['top']}",
            ],
        }
        start = time.monotonic()
        last_msg = ""
        while time.monotonic() - start < max_wait:
            if ctl.is_stopped():
                raise StopRequested()
            # 可中断锁获取，暂停时不再开启下一个环境。
            while not self.launch_lock.acquire(timeout=SLEEP_SLICE):
                if ctl.is_stopped():
                    raise StopRequested()
            try:
                while not ctl.pause_event.wait(SLEEP_SLICE):
                    if ctl.is_stopped():
                        raise StopRequested()
                if ctl.is_stopped():
                    raise StopRequested()
                wait = max(0.0, self._next_launch - time.monotonic())
                if ctl.stop_event.wait(wait):
                    raise StopRequested()
                # 错峰等待结束可能已经暂停，再次通过门禁。
                while not ctl.pause_event.wait(SLEEP_SLICE):
                    if ctl.is_stopped():
                        raise StopRequested()
                if ctl.is_stopped():
                    raise StopRequested()
                running = self.probe_running(browser_id)
                if running is None:
                    # 状态不明时不盲目 open，也不声称窗口属于本程序。
                    raise RuntimeError("无法确认窗口运行状态，请检查 /browser/pids 接口")
                if running:
                    if rec.mark_reused():
                        log_cb("检测到环境已在运行，复用现有窗口。")
                res = self._post("/browser/open", payload, timeout=int(20 * NET_SCALE))
                if not running and (res.get("success") or self.probe_running(browser_id) is True):
                    rec.mark_launched()
                endpoint = self._extract_endpoint(res)
                self._next_launch = time.monotonic() + (LAUNCH_STAGGER if not running else 0)
            finally:
                self.launch_lock.release()
            if ctl.is_stopped():
                raise StopRequested()
            if endpoint:
                return endpoint
            msg = str(res.get("msg") or "接口未返回 CDP 地址")
            if msg != last_msg:
                log_cb(f"启动未就绪 ({int(time.monotonic() - start)}s): {msg}")
                last_msg = msg
            if ctl.stop_event.wait(3.0):
                raise StopRequested()
        ctl.close_browser(browser_id, allow_reused=False)
        raise RuntimeError(f"比特浏览器启动超时: {browser_id} ({last_msg})")


# ======================================================================
# 模块：xmanager/control.py
# ======================================================================
"""运行控制：并发槽位、启动记录、暂停 / 停止 / 取消排队。"""


import queue
import threading
import time
from enum import Enum
from typing import Callable, Dict, List, Optional, Set, Tuple



class BrowserSlotPool:
    def __init__(self, size: int = MAX_ACTIVE_BROWSERS):
        self.q: queue.Queue = queue.Queue(maxsize=size)
        self._leased: Set[int] = set()
        self._lock = threading.Lock()
        for i in range(size):
            self.q.put(i)

    def acquire(self, should_abort: Callable[[], bool]) -> Optional[int]:
        while not should_abort():
            try:
                slot = self.q.get(timeout=SLEEP_SLICE)
            except queue.Empty:
                continue
            if should_abort():
                self.q.put_nowait(slot)
                return None
            with self._lock:
                self._leased.add(slot)
            return slot
        return None

    def release(self, slot_idx: int) -> None:
        with self._lock:
            if slot_idx not in self._leased:
                return
            self._leased.remove(slot_idx)
            self.q.put_nowait(slot_idx)


# ============================================================
# 运行控制与浏览器状态机
# ============================================================


class BrowserCloseState(Enum):
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


class LaunchRecord:
    def __init__(self) -> None:
        self.cond = threading.Condition()
        self.state = BrowserCloseState.OPEN
        self._launched_by_us = False
        self._reused = False
        self.worker_done = False
        self.needs_cleanup = False

    @property
    def launched_by_us(self) -> bool:
        with self.cond:
            return self._launched_by_us

    @launched_by_us.setter
    def launched_by_us(self, v: bool) -> None:
        with self.cond:
            self._launched_by_us = v

    @property
    def reused(self) -> bool:
        with self.cond:
            return self._reused

    @reused.setter
    def reused(self, v: bool) -> None:
        with self.cond:
            self._reused = v

    def mark_launched(self) -> None:
        with self.cond:
            self._launched_by_us = True
            if self.state == BrowserCloseState.CLOSED:
                self.state = BrowserCloseState.OPEN

    def mark_reused(self) -> bool:
        with self.cond:
            if self._launched_by_us or self._reused:
                return False
            self._reused = True
            return True

    def closable(self, allow_reused: bool) -> bool:
        with self.cond:
            return self._launched_by_us or (self._reused and allow_reused)


class RunControl:
    def __init__(self, log_cb: Callable[[str], None], status_cb: Callable[[str, str, str], None]):
        self.stop_event = threading.Event()
        self.pause_event = threading.Event()
        self.pause_event.set()
        self.cancel_all_event = threading.Event()
        self._cancelled: Set[str] = set()
        self._pending: Set[str] = set()
        self._launch_order: List[str] = []
        self.log = log_cb
        self.set_status = status_cb
        self.layout_count = MAX_ACTIVE_BROWSERS
        self.slots = BrowserSlotPool(self.layout_count)
        self.window_order = WindowOrderManager()
        self.bit = BitClient(BIT_API)
        # 每批启动前由界面载入的 TXT 快照：((指纹, 文本), ...)
        self.draft_rows: Tuple[Tuple[str, str], ...] = ()
        self.comment_rows: Tuple[Tuple[str, str], ...] = ()
        self._records: Dict[str, LaunchRecord] = {}
        self._lock = threading.Lock()
        self._reaper: Optional[threading.Thread] = None
        self._generation = 0
        self._pause_started: Optional[float] = None
        self._paused_seconds = 0.0

    def reset(self, concurrency: int = MAX_ACTIVE_BROWSERS, window_layout="cascade") -> None:
        with self._lock:
            if self._records:
                raise RuntimeError("上一批浏览器尚未清理完成")
            self._generation += 1
            self._pause_started = None
            self._paused_seconds = 0.0
            self.stop_event.clear()
            self.pause_event.set()
            self.cancel_all_event.clear()
            self._cancelled.clear()
            self._pending.clear()
            self._launch_order.clear()
            self._records.clear()
            self._reaper = None
            self.layout_count = max(1, min(MAX_ACTIVE_BROWSERS, concurrency))
            self.slots = BrowserSlotPool(self.layout_count)
            self.window_order.reset(self.layout_count, window_layout)

    def is_stopped(self) -> bool:
        return self.stop_event.is_set()

    def request_stop(self) -> None:
        self.stop_event.set()
        self.set_paused(False)
        with self._lock:
            if self._reaper is not None and self._reaper.is_alive():
                return
            self._reaper = threading.Thread(
                target=self._reap,
                args=(self._generation,),
                name="stop-reaper",
                daemon=True,
            )
            self._reaper.start()

    def _force_close(self, bid: str, rec: LaunchRecord) -> None:
        try:
            if self.close_browser(bid, allow_reused=False, expected=rec):
                self.log(f"[{bid[:6]}] 停止宽限期已过, 已强制关闭浏览器以中断阻塞操作。")
        finally:
            self.bit.close_thread_session()

    def _reap(self, generation: int) -> None:
        # 不因启动记录暂时为空而提前退出；旧批次 reaper 不操作新批次。
        end = time.monotonic() + STOP_GRACE_SEC
        while time.monotonic() < end:
            time.sleep(min(0.1, max(0.0, end - time.monotonic())))
        # 未确认关闭的记录继续保留；有界重试后仍失败可由下一次停止/启动前复查重试。
        for attempt in range(3):
            with self._lock:
                if generation != self._generation:
                    return
                records = list(self._records.items())
            if not records:
                break
            threads = []
            for bid, rec in records:
                thread = threading.Thread(
                    target=self._force_close, args=(bid, rec), name=f"force-close-{bid[:6]}", daemon=True
                )
                thread.start()
                threads.append(thread)
            for thread in threads:
                thread.join()
            if attempt < 2:
                time.sleep(0.25)
        self.bit.close_thread_session()

    def wait_reaper(self) -> None:
        reaper = self._reaper
        if reaper and reaper is not threading.current_thread():
            reaper.join()

    def set_paused(self, paused: bool) -> None:
        with self._lock:
            if paused and self._pause_started is None:
                self._pause_started = time.monotonic()
                self.pause_event.clear()
            elif not paused:
                if self._pause_started is not None:
                    self._paused_seconds += time.monotonic() - self._pause_started
                    self._pause_started = None
                self.pause_event.set()

    def paused_seconds(self) -> float:
        with self._lock:
            extra = time.monotonic() - self._pause_started if self._pause_started is not None else 0.0
            return self._paused_seconds + extra

    def wait_queue_ready(self, browser_id: str) -> bool:
        while not self.should_abort_queue(browser_id):
            if self.pause_event.wait(SLEEP_SLICE):
                return not self.should_abort_queue(browser_id)
        return False

    def claim_pending(self, browser_id: str) -> bool:
        with self._lock:
            if (
                self.stop_event.is_set()
                or self.cancel_all_event.is_set()
                or browser_id in self._cancelled
                or not self.pause_event.is_set()
            ):
                return False
            self._pending.discard(browser_id)
            return True

    def set_pending(self, ids: List[str]) -> None:
        with self._lock:
            self._pending = set(ids)
            self._launch_order = list(dict.fromkeys(ids))


    def take_pending(self, browser_id: str) -> None:
        with self._lock:
            self._pending.discard(browser_id)
            if browser_id in self._launch_order:
                self._launch_order.remove(browser_id)


    def cancel_queued(self, ids: Optional[List[str]] = None) -> List[str]:
        with self._lock:
            if ids is None:
                self.cancel_all_event.set()
                return list(self._pending)
            targets = [i for i in ids if i in self._pending]
            self._cancelled.update(targets)
            return targets

    def should_abort_queue(self, browser_id: str) -> bool:
        with self._lock:
            return self.stop_event.is_set() or self.cancel_all_event.is_set() or browser_id in self._cancelled

    def begin_launch(self, browser_id: str) -> LaunchRecord:
        rec = LaunchRecord()
        with self._lock:
            self._records[browser_id] = rec
        return rec

    def _retire_finished(self, browser_id: str, rec: LaunchRecord) -> bool:
        with self._lock:
            if self._records.get(browser_id) is not rec:
                return False
            with rec.cond:
                removable = rec.worker_done and (
                    not rec.needs_cleanup or rec.state == BrowserCloseState.CLOSED
                )
            if removable:
                self._records.pop(browser_id, None)
            return removable

    def end_launch(
        self, browser_id: str, expected: Optional[LaunchRecord] = None, require_close: bool = False
    ) -> None:
        with self._lock:
            rec = self._records.get(browser_id)
            if rec is None or (expected is not None and rec is not expected):
                return
            with rec.cond:
                rec.worker_done = True
                rec.needs_cleanup = (require_close or self.stop_event.is_set()) and rec.launched_by_us
        self._retire_finished(browser_id, rec)
        self.window_order.unregister(browser_id)

    def active_ids(self) -> List[str]:
        with self._lock:
            return list(self._records.keys())

    def close_browser(
        self,
        browser_id: str,
        allow_reused: bool,
        expected: Optional[LaunchRecord] = None,
    ) -> bool:
        with self._lock:
            rec = self._records.get(browser_id)
        if rec is None or (expected is not None and rec is not expected):
            return False

        wait_end = time.monotonic() + CLOSE_WAIT_SEC
        with rec.cond:
            while True:
                if not rec.closable(allow_reused):
                    return False
                if rec.state == BrowserCloseState.CLOSED:
                    return False
                if rec.state == BrowserCloseState.OPEN:
                    rec.state = BrowserCloseState.CLOSING
                    break
                remain = wait_end - time.monotonic()
                if remain <= 0:
                    return False
                rec.cond.wait(timeout=min(0.5, remain))

        ok = False
        try:
            ok = self.bit.close(browser_id)
            if not ok and self.bit.probe_running(browser_id) is False:
                ok = True
        except Exception:
            logger.debug("关闭浏览器异常", exc_info=True)
        finally:
            with rec.cond:
                rec.state = BrowserCloseState.CLOSED if ok else BrowserCloseState.OPEN
                rec.cond.notify_all()
            self._retire_finished(browser_id, rec)
        return ok

    def wait_launch_turn(self, browser_id: str) -> bool:
        while not self.should_abort_queue(browser_id):
            with self._lock:
                self._launch_order[:]=[bid for bid in self._launch_order if bid not in self._cancelled]
                ready=not self._launch_order or self._launch_order[0]==browser_id
            if ready and self.pause_event.is_set():
                return not self.should_abort_queue(browser_id)
            self.stop_event.wait(SLEEP_SLICE)
        return False

    def finish_launch_turn(self, browser_id: str) -> None:
        with self._lock:
            if browser_id in self._launch_order:
                self._launch_order.remove(browser_id)






# ======================================================================
# 模块：xmanager/metrics.py
# ======================================================================
"""计数文本解析与 X 字数计算。"""


import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

_COUNT_SUFFIX = {
    "k": 1_000,
    "mil": 1_000,
    "tsd": 1_000,
    "千": 1_000,
    "m": 1_000_000,
    "mi": 1_000_000,
    "mio": 1_000_000,
    "b": 1_000_000_000,
    "mrd": 1_000_000_000,
    "万": 10_000,
    "萬": 10_000,
    "亿": 100_000_000,
    "億": 100_000_000,
}
# 数字 + 可选单位。拉丁字母单位后面不能再接字母，避免把 "5 Mentions" 读成 5M。
_COUNT_RE = re.compile(
    r"(\d{1,3}(?: \d{3})+(?!\d)|\d[\d.,\u00a0\u202f]*)\s*(?:(mio|tsd|mrd|mil|mi|[kmb])(?![A-Za-z])|([万萬千亿億]))?",
    re.I,
)
_UNREAD_WORDS = re.compile(
    r"unread|未读|未讀|não lid|nao lid|no leíd|no leid|sin leer|non lu|ungelesen|непрочит|未読|읽지|okunmam|belum dibaca|chưa đọc",
    re.I,
)


def _number_value(raw: str, has_suffix: bool) -> Optional[float]:
    s = re.sub(r"[\s\u00a0\u202f]", "", raw).rstrip(".,")
    if not s:
        return None
    try:
        if has_suffix:
            if s.count(",") + s.count(".") > 1:
                last = max(s.rfind(","), s.rfind("."))
                s = re.sub(r"[.,]", "", s[:last]) + "." + s[last + 1 :]
            else:
                s = s.replace(",", ".")
            return float(s)
        if re.fullmatch(r"\d{1,3}(?:[.,]\d{3})+", s):  # 1,234 / 1.234.567
            return float(re.sub(r"[.,]", "", s))
        return float(s.replace(",", "."))
    except ValueError:
        return None


def parse_count(text: Any) -> Optional[int]:
    """从 "1,234 Followers" / "1.2K" / "12.3万 位关注者" 里取出第一个数字。"""
    if text is None:
        return None
    found = _COUNT_RE.search(str(text))
    if not found:
        return None
    suffix = (found.group(2) or found.group(3) or "").lower()
    value = _number_value(found.group(1), bool(suffix))
    if value is None:
        return None
    return int(round(value * _COUNT_SUFFIX.get(suffix, 1)))


def count_from_label(label: Any) -> Optional[int]:
    """互动按钮的 aria-label：元素不存在 -> None；没有数字（0 次）-> 0。"""
    if label is None:
        return None
    number = parse_count(label)
    return 0 if number is None else number


def unread_total(labels: Any) -> int:
    """从红点徽标的 aria-label 里取未读数；只有"未读"字样没有数字时按 1 计。"""
    best = 0
    for label in labels or ():
        if label and _UNREAD_WORDS.search(label):
            number = parse_count(label)
            best = max(best, 1 if number is None else number)
    return best


def build_post_metrics(rows: Any) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        pid = str(row.get("id") or "")
        if not pid.isdigit() or pid in seen:
            continue
        seen.add(pid)
        views = parse_count(row.get("views_label")) if row.get("views_label") else None
        if not views and row.get("views_text"):
            views = parse_count(row.get("views_text"))
        out.append(
            {
                "id": pid,
                "text": re.sub(r"\s+", " ", str(row.get("text") or "")).strip()[:120],
                "likes": count_from_label(row.get("like")) or 0,
                "replies": count_from_label(row.get("reply")) or 0,
                "reposts": count_from_label(row.get("retweet")) or 0,
                "views": views or 0,
            }
        )
    return out


def x_weighted_length(text: str) -> int:
    """X 的计数规则（近似）：中日韩与大多数符号每个算 2，拉丁字母算 1；上限 280。"""
    total = 0
    for ch in text:
        code = ord(ch)
        total += (
            1
            if (
                code <= 0x10FF
                or 0x2000 <= code <= 0x200D
                or 0x2010 <= code <= 0x201F
                or 0x2032 <= code <= 0x2037
            )
            else 2
        )
    return total


def local_midnight(now: Optional[float] = None) -> float:
    return (
        datetime.fromtimestamp(now or time.time())
        .replace(hour=0, minute=0, second=0, microsecond=0)
        .timestamp()
    )


# ======================================================================
# 模块：xmanager/session.py
# ======================================================================
"""Playwright 会话、单标签守卫、CDP 连接与页面健康检查。"""


import re
import threading
import time
from typing import Any, Dict, Optional
from urllib.parse import parse_qsl, urlparse



class SinglePageGuard:
    """每个受控浏览器环境仅保留一个标签；控制器创建首个空页后才安装。"""

    SCRIPT = r'''(() => {
        if(window.__xSinglePageMode)return;
        window.__xSinglePageMode=true;
        const allowed = value => {try {const u=new URL(value,location.href);return /^https?:$/.test(u.protocol)?u.href:null;}catch{return null;}};
        window.open=function(url){const target=url && allowed(String(url));if(target)location.assign(target);return null;};
        const normalize=el=>{if(el && el.target && !['_self','_top','_parent'].includes(el.target.toLowerCase()))el.target='_self';};
        document.addEventListener('click',event=>normalize(event.target.closest && event.target.closest('a[target]')),true);
        document.addEventListener('submit',event=>normalize(event.target),true);
        const install=()=>{
            document.querySelectorAll('a[target],form[target]').forEach(normalize);
            if(!document.documentElement)return;
            new MutationObserver(records=>{
                for(const record of records){
                    if(record.type==='attributes')normalize(record.target);
                    for(const node of record.addedNodes){if(node.nodeType!==1)continue;normalize(node);node.querySelectorAll('a[target],form[target]').forEach(normalize);}
                }
            }).observe(document.documentElement,{subtree:true,childList:true,attributes:true,attributeFilter:['target']});
        };
        if(document.documentElement)install();else document.addEventListener('DOMContentLoaded',install,{once:true});
    })();'''

    def __init__(self, context, page):
        self.context, self.page = context, page
        self.installed = False

    def close_extra(self, page):
        if page is not self.page and not page.is_closed():
            page.close(run_before_unload=False)

    def install(self):
        self.context.add_init_script(self.SCRIPT)
        self.context.on('page', self.close_extra)
        self.installed = True
        for page in list(self.context.pages):
            self.close_extra(page)
        if not self.page.is_closed():
            self.page.evaluate(self.SCRIPT)

    def close(self):
        if self.installed:
            self.context.remove_listener('page', self.close_extra)
            self.installed = False


def is_x_url(url: str) -> bool:
    try:
        parsed = urlparse(url)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return False
    except (ValueError, TypeError):
        return False
    return any(host == domain or host.endswith("." + domain) for domain in ("x.com", "twitter.com"))


def lite_route(route) -> None:
    try:
        request = route.request
        url = request.url.lower()
        if any(word in url for word in ("captcha", "challenge", "verify", "verification")):
            route.continue_()
        elif request.resource_type in ("image", "media", "font"):
            route.abort()
        else:
            route.continue_()
    except Exception:
        logger.debug("处理资源路由失败", exc_info=True)


class ActiveClock:
    """只累加已连接执行段；从段时长扣除暂停，不计重连/清理。"""

    def __init__(self, ctl: RunControl):
        self.ctl = ctl
        self.total = 0.0
        self.started: Optional[float] = None
        self.pause_base = 0.0

    def resume(self) -> None:
        if self.started is None:
            self.pause_base = self.ctl.paused_seconds()
            self.started = time.monotonic()

    def elapsed(self) -> float:
        if self.started is None:
            return self.total
        return self.total + max(
            0.0,
            time.monotonic() - self.started - (self.ctl.paused_seconds() - self.pause_base),
        )

    def suspend(self) -> None:
        self.total = self.elapsed()
        self.started = None


class PlaywrightSession:
    def __init__(self) -> None:
        self.pw: Any = None
        self.browser: Any = None
        self.context: Any = None
        self.page: Any = None
        self.cdp: Any = None
        self._stopped = False
        self._owner = threading.get_ident()
        self._route_installed = False
        self.layout_applied = False
        self.actual_bounds: Dict[str, Any] = {}
        self.single_page_guard = None

    def start(self) -> None:
        with PLAYWRIGHT_START_LOCK:
            self.pw = sync_playwright().start()

    def invalidate(self) -> None:
        self.browser = self.context = self.page = self.cdp = None

    def close(self) -> None:
        if threading.get_ident() != self._owner:
            return
        if self._stopped:
            return
        self._stopped = True
        cdp, pw = self.cdp, self.pw
        if self.single_page_guard is not None:
            try:
                self.single_page_guard.close()
            except Exception:
                logger.debug("移除单页监听失败", exc_info=True)
            self.single_page_guard = None
        if self._route_installed and self.page is not None:
            try:
                self.page.unroute("**/*", lite_route)
            except Exception:
                logger.debug("移除省流量路由失败", exc_info=True)
        self.invalidate()
        self.pw = None
        if cdp is not None:
            try:
                cdp.detach()
            except Exception:
                pass
        if pw is not None:
            try:
                pw.stop()
            except Exception:
                pass


class BitBrowserController:
    @staticmethod
    def apply_window_bounds(cdp, bounds: Dict[str, int]) -> Dict[str, Any]:
        info = cdp.send("Browser.getWindowForTarget")
        if not info or "windowId" not in info:
            raise RuntimeError("未获得浏览器窗口ID")
        window_id = info["windowId"]
        state = (info.get("bounds") or {}).get("windowState", "normal")
        if state != "normal":
            cdp.send(
                "Browser.setWindowBounds",
                {"windowId": window_id, "bounds": {"windowState": "normal"}},
            )
        cdp.send(
            "Browser.setWindowBounds",
            {"windowId": window_id, "bounds": ScreenLayoutManager.to_cdp_bounds(bounds)},
        )
        try:
            actual = cdp.send("Browser.getWindowBounds", {"windowId": window_id})
            return (
                ScreenLayoutManager.from_cdp_bounds(actual.get("bounds", {}))
                if isinstance(actual, dict)
                else {}
            )
        except Exception:
            logger.debug("无法读取实际窗口尺寸，布局指令已发送", exc_info=True)
            return {}

    @staticmethod
    def connect_and_arrange(
        sess: PlaywrightSession,
        endpoint: str,
        bounds: Dict[str, int],
        lite: bool,
        stop_event: threading.Event,
    ):
        playwright = sess.pw
        last_err: Optional[Exception] = None
        browser = None
        for _ in range(3):
            if stop_event.is_set():
                raise StopRequested()
            try:
                browser = playwright.chromium.connect_over_cdp(endpoint, timeout=T(25000))
                break
            except Exception as e:
                last_err = e
                if stop_event.wait(2.0):
                    raise StopRequested()
        if browser is None:
            raise RuntimeError(f"CDP 连接失败: {last_err}")
        sess.browser = browser

        t_end = time.monotonic() + CONTEXT_WAIT_SEC
        while not browser.contexts:
            if stop_event.is_set():
                raise StopRequested()
            if time.monotonic() >= t_end:
                raise CdpStateError("browser.contexts 为空, 浏览器状态异常")
            if stop_event.wait(0.5):
                raise StopRequested()
        context = browser.contexts[0]
        sess.context = context

        page = None
        for cand in context.pages:
            if is_x_url(cand.url or ""):
                page = cand
                break
        if page is None:
            page = next((p for p in context.pages if not p.is_closed()), None)
        if page is None:
            page = context.new_page()  # 环境没有页面时，仅创建唯一的初始标签。
        sess.page = page
        sess.single_page_guard = SinglePageGuard(context, page)
        sess.single_page_guard.install()

        page.set_default_timeout(T(4000))
        page.set_default_navigation_timeout(T(35000))

        try:
            cdp = context.new_cdp_session(page)
            sess.cdp = cdp
            sess.actual_bounds = BitBrowserController.apply_window_bounds(cdp, bounds)
            sess.layout_applied = True
        except Exception:
            logger.warning("窗口布局未设置成功，目标范围=%s", bounds, exc_info=True)

        try:
            if lite:
                page.route("**/*", lite_route)
                sess._route_installed = True
        except Exception:
            pass

        return browser, context, page, sess.cdp


def check_page_health(page: Page) -> str:
    """只识别明确的账号/全页故障；不匹配推文正文里的错误词。"""
    try:
        url = page.url or ""
    except Exception:
        return "ok"
    if url.startswith("chrome-error://"):
        return "error_page"
    if not is_x_url(url):
        return "ok"
    path = urlparse(url).path.rstrip("/")
    if path in ("/login", "/i/flow/login"):
        return "logged_out"
    if (
        path.startswith("/account/access")
        or path == "/account/suspended"
        or (path.startswith("/i/flow/") and "login" not in path)
    ):
        return "needs_action"
    try:
        # 有可见帖子时，局部回复加载失败不能把整页判为坏页。
        articles = page.locator(SELECTORS["tweet"])
        if any(articles.nth(i).is_visible() for i in range(min(articles.count(), 3))):
            return "ok"
        panels = page.locator(SELECTORS["error_text"])
        for i in range(min(panels.count(), 4)):
            panel = panels.nth(i)
            if panel.is_visible() and not panel.locator("xpath=ancestor::article").count():
                return "error_page"
    except Exception:
        logger.debug("页面健康探测未完成", exc_info=True)
    return "ok"


def same_x_route(left: str, right: str) -> bool:
    if not is_x_url(left) or not is_x_url(right):
        return False
    a, b = urlparse(left), urlparse(right)
    pa, pb = a.path.rstrip("/"), b.path.rstrip("/")
    if pa != pb:
        sa, sb = canonical_status_url(left), canonical_status_url(right)
        return bool(
            sa
            and sb
            and sa.rsplit("/", 1)[-1] == sb.rsplit("/", 1)[-1]
            and pa.endswith("/status/" + sa.rsplit("/", 1)[-1])
            and pb.endswith("/status/" + sb.rsplit("/", 1)[-1])
        )
    if pa in ("/home", "/notifications"):
        return True
    ignored = {"s", "t", "src", "ref_src", "lang"}

    def query(parsed):
        return sorted(
            (key, value)
            for key, value in parse_qsl(parsed.query)
            if key not in ignored and not key.startswith("utm_")
        )

    return query(a) == query(b)


def short_error(exc: Exception) -> str:
    return f"{type(exc).__name__}: {str(exc).splitlines()[0] if str(exc) else '未提供原因'}"[:260]


FOLLOWING_LABELS = (
    "Following",
    "关注",
    "正在关注",
    "关注中",
    "已关注",
    "正在關注",
    "跟隨中",
    "正在跟隨",
    "フォロー中",
    "팔로잉",
    "Seguindo",
    "Siguiendo",
    "Abonnements",
    "Folge ich",
    "Mengikuti",
    "Takip edilenler",
    "Подписки",
    "Đang theo dõi",
    "กำลังติดตาม",
    "المتابَعون",
    "متابَعون",
)


def following_name_pattern():
    return re.compile(
        r"^\s*(?:" + "|".join(re.escape(label) for label in FOLLOWING_LABELS) + r")(?:\s*\d+)?\s*$",
        re.I,
    )


def canonical_status_url(value: str) -> Optional[str]:
    if not isinstance(value, str):
        return None
    if value.startswith("/"):
        value = "https://x.com" + value
    if not is_x_url(value):
        return None
    parts = urlparse(value).path.split("/")
    try:
        index = parts.index("status")
        if index < 2 or index + 1 >= len(parts) or not parts[index + 1].isdigit():
            return None
        return "https://x.com" + "/".join(parts[: index + 2])
    except ValueError:
        return None


# ======================================================================
# 模块：xmanager/storage.py
# ======================================================================
"""配置、批次检查点与运行历史。"""


import csv
import hashlib
import json
import os
import tempfile
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Set



def report_token(browser_id: str) -> str:
    """工作流报告文件名前缀：不把环境 ID 明文写进文件名。"""
    return hashlib.sha256(browser_id.encode()).hexdigest()[:16]


def latest_report(browser_id: str) -> Optional[Dict[str, Any]]:
    """读取该账号最近一次会话的工作流报告；没有或损坏时返回 None。"""
    try:
        paths = sorted(
            REPORT_DIR.glob(f"{report_token(browser_id)}_*.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
        return json.loads(paths[0].read_text(encoding="utf-8")) if paths else None
    except (OSError, ValueError):
        return None


def atomic_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2, allow_nan=False)
            f.flush()
            os.fsync(f.fileno())
        os.replace(name, path)
    finally:
        if os.path.exists(name):
            os.unlink(name)


class ConfigStore:
    @staticmethod
    def load() -> Dict[str, Any]:
        try:
            if CONFIG_PATH.exists():
                data = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    return data
                raise ValueError("配置根节点必须是对象")
        except Exception:
            logger.warning("配置读取失败，将使用默认值；原文件保留", exc_info=True)
        return {}

    @staticmethod
    def save(data: Dict[str, Any]) -> None:
        atomic_json(CONFIG_PATH, data)


class BatchStore:
    _lock = threading.RLock()
    _data: Dict[str, Any] = {}

    @classmethod
    def begin(cls, targets: List[Dict[str, Any]]) -> None:
        with cls._lock:
            cls._data = {
                "version": 1,
                "batch_id": uuid.uuid4().hex,
                "created_at": time.time(),
                "tasks": {
                    str(it.get("id") or it.get("browserId")): {
                        "name": it.get("siteName") or it.get("name") or "未命名",
                        "state": "PENDING",
                    }
                    for it in targets
                },
            }
            atomic_json(BATCH_PATH, cls._data)

    @classmethod
    def update(cls, bid: str, state: str) -> None:
        try:
            with cls._lock:
                if bid in cls._data.get("tasks", {}):
                    cls._data["tasks"][bid]["state"] = state
                    atomic_json(BATCH_PATH, cls._data)
        except Exception:
            logger.exception("保存任务检查点失败")

    @classmethod
    def unfinished(cls) -> Set[str]:
        if not BATCH_PATH.exists():
            return set()
        data = json.loads(BATCH_PATH.read_text(encoding="utf-8"))
        tasks = data.get("tasks", {})
        return {bid for bid, info in tasks.items() if info.get("state") in ("PENDING", "RUNNING", "STOPPED")}


class HistoryStore:
    _lock = threading.Lock()

    @classmethod
    def append(
        cls,
        browser_id: str,
        name: str,
        started_at: float,
        active_sec: float,
        result: Result,
        stats: Optional[Dict[str, Any]] = None,
    ) -> None:
        rec = {
            "id": browser_id,
            "name": name,
            "start": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(started_at)),
            "date": time.strftime("%Y-%m-%d"),
            "active_sec": round(active_sec, 1),
            "result": result.value,
            "end": time.strftime("%Y-%m-%d %H:%M:%S"),
            "stats": dict(stats or {}),
            "version": APP_VERSION,
        }
        try:
            with cls._lock, HISTORY_PATH.open("a", encoding="utf-8") as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            logger.exception("写入历史记录失败")

    @classmethod
    def done_today(cls) -> Set[str]:
        today = time.strftime("%Y-%m-%d")
        ids: Set[str] = set()
        try:
            if HISTORY_PATH.exists():
                with cls._lock, HISTORY_PATH.open("r", encoding="utf-8") as f:
                    for line in f:
                        try:
                            r = json.loads(line)
                            if (
                                r.get("date") == today
                                and (r.get("stats") or {}).get("mode") != "service"
                                and r.get("result") in {result.value for result in SUCCESS_RESULTS}
                            ):
                                ids.add(str(r.get("id")))
                        except Exception:
                            continue
        except Exception:
            pass
        return ids

    @classmethod
    def export_csv(cls, path: Path) -> int:
        fields = [
            "环境ID",
            "名称",
            "开始时间",
            "结束时间",
            "有效分钟",
            "结果",
            "阅读",
            "点赞确认",
            "重连",
            "工作流完成",
            "工作流跳过",
            "工作流失败",
            "工作流中断",
            "工作流计划JSON",
        ]
        if (
            path.resolve()
            in {
                HISTORY_PATH.resolve(),
                CONFIG_PATH.resolve(),
                BATCH_PATH.resolve(),
            }
            or path.resolve().parent == Path(__file__).resolve().parent
        ):
            raise ValueError("导出路径不能覆盖程序或运行数据文件")
        count = 0
        # 先截取快照，避免导出长时间阻塞任务写历史。
        with cls._lock:
            size = HISTORY_PATH.stat().st_size if HISTORY_PATH.exists() else 0

        def safe(value):
            value = str(value or "")
            return "'" + value if value.lstrip().startswith(("=", "+", "-", "@")) else value

        with path.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(fields)
            if not size:
                return 0
            with HISTORY_PATH.open("rb") as source:
                while source.tell() < size:
                    line = source.readline()
                    if source.tell() > size:
                        break
                    try:
                        item = json.loads(line)
                        stat = item.get("stats") or {}
                        workflow = stat.get("workflow_plan") or {}
                        summary = workflow.get("summary") or {}
                        writer.writerow(
                            [
                                safe(item.get("id")),
                                safe(item.get("name")),
                                item.get("start"),
                                item.get("end", ""),
                                round(float(item.get("active_sec", 0)) / 60, 2),
                                item.get("result"),
                                stat.get("reads", 0),
                                stat.get("likes", 0),
                                stat.get("reconnects", 0),
                                summary.get("completed", 0),
                                summary.get("skipped", 0),
                                summary.get("failed", 0),
                                summary.get("interrupted", 0),
                                json.dumps(workflow, ensure_ascii=False),
                            ]
                        )
                        count += 1
                    except (ValueError, TypeError, AttributeError):
                        continue
        return count


# ======================================================================
# 模块：xmanager/publishing.py
# ======================================================================
"""TXT 发推与自动评论：持久化占用、只点一次、结果不明隔离。"""


import hashlib
import json
import random
import sqlite3
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Tuple
from urllib.parse import urlparse



def load_draft_lines(path: str) -> Tuple[Tuple[str, str], ...]:
    raw = Path(path).expanduser().read_bytes()
    for encoding in ("utf-8-sig", "utf-16", "gb18030"):
        try:
            # UTF-16 无 BOM 时不猜测，防止把其他编码误识别。
            if encoding == "utf-16" and not raw.startswith((b"\xff\xfe", b"\xfe\xff")):
                continue
            text = raw.decode(encoding)
            break
        except UnicodeError:
            continue
    else:
        raise ValueError("无法识别 TXT 编码，请另存为 UTF-8")
    if "\x00" in text:
        raise ValueError("TXT 包含空字符，请另存为 UTF-8 文本")
    rows, occurrences = [], {}
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        fingerprint = hashlib.sha256(line.encode("utf-8")).hexdigest()
        occurrences[fingerprint] = occurrences.get(fingerprint, 0) + 1
        rows.append((f"{fingerprint}:{occurrences[fingerprint]}", line))
    if not rows:
        raise ValueError("TXT 中没有可发布的非空行")
    return tuple(rows)


class DraftStore:
    """每次事务独立连接；BEGIN IMMEDIATE 防止并发取到同一条。"""

    def __init__(self, path=None):
        self.path = Path(path) if path is not None else DATA_DIR / "draft_queue.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS drafts (
                scope TEXT NOT NULL, item TEXT NOT NULL, text TEXT NOT NULL,
                state TEXT NOT NULL, owner TEXT NOT NULL, updated REAL NOT NULL,
                url TEXT NOT NULL DEFAULT '', error TEXT NOT NULL DEFAULT '',
                PRIMARY KEY(scope, item))""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 30000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def recover(self):
        # 仅在无任务运行、启动新批次前调用。已进入点击阶段的条目绝不自动重试。
        with self.connection() as db:
            db.execute(
                "UPDATE drafts SET state='unknown', error='上次发布中断，需核对' WHERE state='sending'"
            )
            db.execute("UPDATE drafts SET state='pending' WHERE state IN ('reserved', 'failed')")

    def blocked(self, owner):
        with self.connection() as db:
            return (
                db.execute(
                    "SELECT 1 FROM drafts WHERE owner=? AND state IN ('sending','unknown') LIMIT 1", (owner,)
                ).fetchone()
                is not None
            )

    def reserve(self, rows, owner, scope, order):
        if order == "random":
            rows = list(rows)
            random.shuffle(rows)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for key, text in rows:
                db.execute(
                    "INSERT OR IGNORE INTO drafts(scope,item,text,state,owner,updated) VALUES(?,?,?,'pending','',?)",
                    (scope, key, text, time.time()),
                )
                cursor = db.execute(
                    "UPDATE drafts SET state='reserved', owner=?, updated=?, error='' WHERE scope=? AND item=? AND state='pending'",
                    (owner, time.time(), scope, key),
                )
                if cursor.rowcount:
                    return key, text
        return None

    def update(self, scope, item, owner, state, error='', url=''):
        with self.connection() as db:
            cursor = db.execute(
                "UPDATE drafts SET state=?, error=?, url=?, updated=? WHERE scope=? AND item=? AND owner=?",
                (state, error, url, time.time(), scope, item, owner),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("草稿占用记录丢失，停止发布")

    def cooldown(self, owner, interval):
        with self.connection() as db:
            row = db.execute(
                "SELECT MAX(updated) FROM drafts WHERE owner=? AND state='sent'", (owner,)
            ).fetchone()
        return max(0.0, min(interval, interval - (time.time() - row[0]))) if row[0] is not None else 0.0

    def unresolved(self):
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM drafts WHERE state IN ('unknown','sending','failed') ORDER BY updated"
                )
            ]

    def resolve(self, scope, item, sent):
        with self.connection() as db:
            db.execute(
                "UPDATE drafts SET state=?, updated=?, error=? WHERE scope=? AND item=? AND state IN ('unknown','failed')",
                ("sent" if sent else "pending", time.time(), "已人工核对", scope, item),
            )


def confirmed_tweet_id(payload):
    if not isinstance(payload, dict) or payload.get("errors"):
        return None
    try:
        tweet = payload["data"]["create_tweet"]["tweet_results"]["result"]
        tweet = tweet.get("tweet", tweet)
        tid = tweet.get("rest_id")
        return str(tid) if tid and str(tid).isdigit() else None
    except (KeyError, TypeError, AttributeError):
        return None


class DraftPublisher:
    def __init__(self, machine, page):
        self.m, self.page = machine, page
        self.store = DraftStore()
        self.scope = "*" if machine.cfg.draft_scope == "shared" else machine.browser_id

    def request_matches(self, response, text):
        try:
            parsed = urlparse(response.url)
            host = (parsed.hostname or "").lower()
            if host not in ("x.com", "twitter.com", "api.x.com", "api.twitter.com"):
                return False
            if not parsed.path.endswith("/CreateTweet") or response.request.method != "POST":
                return False
            body = response.request.post_data_json
            return isinstance(body, dict) and body.get("variables", {}).get("tweet_text") == text
        except Exception:
            return False

    def publish(self, key, text):
        m, page, armed = self.m, self.page, False
        try:
            m.checkpoint()
            m.workflow_name, m.workflow_phase = "TXT 发推", "准备正文"
            m.status(f"准备发推 {m.draft_sent + 1}/{m.cfg.draft_count}", "run")
            page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=T(15000))
            m.checkpoint()
            health = check_page_health(page)
            if health in ("logged_out", "needs_action", "error_page"):
                raise RuntimeError("账号需要登录或人工处理")
            editor = page.locator('[data-testid="tweetTextarea_0"][contenteditable="true"]:visible').first
            editor.wait_for(state="visible", timeout=T(8000))
            if editor.inner_text(timeout=T(2000)).strip():
                raise RuntimeError("发帖框已有内容，请先处理现有草稿，避免覆盖")
            editor.fill(text, timeout=T(8000))
            if editor.inner_text(timeout=T(2000)).strip() != text:
                raise RuntimeError("填入文本与草稿不一致，未点击发布")
            button = page.locator(
                '[data-testid="tweetButton"]:visible, [data-testid="tweetButtonInline"]:visible'
            ).first
            button.wait_for(state="visible", timeout=T(5000))
            if not button.is_enabled():
                raise RuntimeError("发布按钮不可用，请检查平台字数或账号状态")
            m.checkpoint()
            with page.expect_response(
                lambda r: self.request_matches(r, text), timeout=T(12000)
            ) as response_info:
                # 先落盘再点击：进程在两者之间终止时，也保守归入待核对。
                self.store.update(self.scope, key, m.browser_id, "sending")
                armed = True
                m.checkpoint()
                m.behavior.click(self.page, button, timeout=T(5000))
            response = response_info.value
            tid = confirmed_tweet_id(response.json()) if response.ok else None
            if not tid:
                raise RuntimeError(f"未收到可确认的成功响应（HTTP {response.status}）")
            url = f"https://x.com/i/status/{tid}"
            self.store.update(self.scope, key, m.browser_id, "sent", url=url)
            m.draft_sent += 1
            m.stats["tweets_sent"] = m.draft_sent
            m.log(f"推文发布已确认 {m.draft_sent}/{m.cfg.draft_count}：{url}")
            return True
        except BaseException as exc:
            # 点击前失败可在下批重试；点击后超时/断线/停止均不重发。
            self.store.update(
                self.scope, key, m.browser_id, "unknown" if armed else "failed", error=short_error(exc)
            )
            if isinstance(exc, (StopRequested, DurationReached, KeyboardInterrupt, SystemExit)):
                raise
            m.log(f"{'发布结果待核对，暂不重发' if armed else '发布前失败，下批可重试'}：{short_error(exc)}")
            return False

    def run(self):
        m = self.m
        if self.store.blocked(m.browser_id):
            m.log("该账号存在结果不明的推文，请在 TXT 发推设置中核对后继续。")
            return Result.PARTIAL
        rows = m.ctl.draft_rows
        while m.draft_sent < m.cfg.draft_count:
            m.checkpoint()
            delay = self.store.cooldown(m.browser_id, m.cfg.draft_interval)
            if delay:
                m.workflow_name, m.workflow_phase = "TXT 发推", f"等待间隔 {delay:.0f}秒"
                m.status(f"等待发推间隔 {delay:.0f}秒", "run")
                m.sleep(delay)
            m.checkpoint()
            item = self.store.reserve(rows, m.browser_id, self.scope, m.cfg.draft_order)
            if item is None:
                m.log("当前没有可领取草稿；已发布、正在发布及待核对条目均会跳过。")
                return Result.PLAN_DONE
            if not self.publish(*item):
                return Result.PARTIAL
        return Result.PLAN_DONE


def normalize_comment_text(value):
    return str(value or "").replace("\r\n", "\n").replace("\u00a0", " ").strip()


def reply_request_variables(request, text, target):
    try:
        parsed = urlparse(request.url)
        host = (parsed.hostname or "").lower()
        operation = parsed.path.rstrip("/").rsplit("/", 1)[-1]
        if host not in ("x.com", "twitter.com", "api.x.com", "api.twitter.com"):
            return None
        if request.method != "POST" or operation not in ("CreateTweet", "CreateNoteTweet"):
            return None
        body = request.post_data_json
        if isinstance(body, str):
            body = json.loads(body)
        variables = body.get("variables", {})
        if isinstance(variables, str):
            variables = json.loads(variables)
        parent = str(variables.get("reply", {}).get("in_reply_to_tweet_id", ""))
        if parent != str(target) or normalize_comment_text(
            variables.get("tweet_text")
        ) != normalize_comment_text(text):
            return None
        return variables
    except Exception:
        return None


def created_reply_id(payload, target):
    if not isinstance(payload, dict) or payload.get("errors"):
        return None
    data = payload.get("data", {})
    if not isinstance(data, dict):
        return None
    for key in ("create_tweet", "create_note_tweet"):
        node = data.get(key)
        for _ in range(8):
            if not isinstance(node, dict):
                break
            if "rest_id" in node or "legacy" in node:
                legacy = node.get("legacy", {})
                if not isinstance(legacy, dict):
                    return None
                tid = node.get("rest_id") or legacy.get("id_str")
                parent = legacy.get("in_reply_to_status_id_str")
                kind = node.get("__typename", "Tweet")
                if kind != "Tweet" or (parent is not None and str(parent) != str(target)):
                    return None
                return str(tid) if tid and str(tid).isdigit() else None
            # 只沿创建结果的包装层向下，不遍历作者/引用推文，避免把其他ID当作成功。
            if isinstance(node.get("tweet_results"), dict):
                node = node["tweet_results"].get("result")
            elif isinstance(node.get("tweet"), dict):
                node = node["tweet"]
            elif isinstance(node.get("result"), dict):
                node = node["result"]
            elif isinstance(node.get("node"), dict):
                node = node["node"]
            else:
                break
    return None


class CommentStore(DraftStore):
    """整个数据目录共用目标/文本唯一键；SQLite 事务保证多账号并发互斥。"""

    def __init__(self, path=None):
        super().__init__(path if path is not None else DATA_DIR / "comment_queue.sqlite3")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("""CREATE TABLE IF NOT EXISTS assignments (
                scope TEXT NOT NULL, source TEXT NOT NULL, target TEXT NOT NULL,
                PRIMARY KEY(scope,source), UNIQUE(scope,target))""")
            db.execute(
                "CREATE TABLE IF NOT EXISTS comment_global_keys (kind TEXT NOT NULL,value TEXT NOT NULL,PRIMARY KEY(kind,value))"
            )
            db.execute(
                "CREATE TABLE IF NOT EXISTS comment_schema (name TEXT PRIMARY KEY,value TEXT NOT NULL)"
            )
            if not db.execute("SELECT 1 FROM comment_schema WHERE name='global_dedupe_v1'").fetchone():
                self._rebuild_global_keys(db)
                db.execute("INSERT INTO comment_schema(name,value) VALUES('global_dedupe_v1','1')")

    @staticmethod
    def panel_scope(account, outbox_id):
        return f"panel:{account}:{int(outbox_id)}"

    def import_panel_history(self, dashboard):
        with dashboard.connection() as db:
            rows = [
                dict(row)
                for row in db.execute(
                    "SELECT id,account,target,text,state,result_url FROM outbox WHERE kind='reply' AND account NOT LIKE 'demo:%' AND state IN ('sent','unknown','sending')"
                )
            ]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for row in rows:
                target = str(row['target'])
                if not target.isdigit():
                    continue
                scope = self.panel_scope(row['account'], row['id'])
                state = 'sent' if row['state'] == 'sent' else 'unknown'
                db.execute(
                    "INSERT OR IGNORE INTO drafts(scope,item,text,state,owner,updated,url,error) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        scope,
                        target,
                        row['text'],
                        state,
                        scope,
                        time.time(),
                        row['result_url'],
                        '面板历史记录迁入全局去重',
                    ),
                )
                if state == 'sent':
                    db.execute(
                        "UPDATE drafts SET state='sent',url=? WHERE scope=? AND item=?",
                        (row['result_url'], scope, target),
                    )
                db.execute(
                    "INSERT OR IGNORE INTO comment_global_keys(kind,value) VALUES('target',?)", (target,)
                )
                db.execute(
                    "INSERT OR IGNORE INTO comment_global_keys(kind,value) VALUES('text',?)",
                    (self.text_key(row['text']),),
                )
        return len(rows)

    @staticmethod
    def text_key(text):
        # TXT 中重复行、不同文件中的相同内容均使用同一把全局唯一键。
        return hashlib.sha256(normalize_comment_text(text).encode("utf-8")).hexdigest()

    @classmethod
    def _rebuild_global_keys(cls, db):
        db.execute("DELETE FROM comment_global_keys")
        rows = db.execute(
            "SELECT item,text FROM drafts WHERE state IN ('reserved','sending','sent','unknown','rejected')"
        ).fetchall()
        for row in rows:
            db.execute(
                "INSERT OR IGNORE INTO comment_global_keys(kind,value) VALUES('target',?)", (row["item"],)
            )
            db.execute(
                "INSERT OR IGNORE INTO comment_global_keys(kind,value) VALUES('text',?)",
                (cls.text_key(row["text"]),),
            )

    @classmethod
    def _refresh_released_keys(cls, db, target, text):
        if not db.execute(
            "SELECT 1 FROM drafts WHERE item=? AND state IN ('reserved','sending','sent','unknown','rejected') LIMIT 1",
            (target,),
        ).fetchone():
            db.execute("DELETE FROM comment_global_keys WHERE kind='target' AND value=?", (target,))
        fingerprint = cls.text_key(text)
        rows = db.execute(
            "SELECT text FROM drafts WHERE state IN ('reserved','sending','sent','unknown','rejected')"
        )
        if not any(cls.text_key(row[0]) == fingerprint for row in rows):
            db.execute("DELETE FROM comment_global_keys WHERE kind='text' AND value=?", (fingerprint,))

    def recover(self):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute(
                "UPDATE drafts SET state='unknown',error='上次提交中断，结果待核对' WHERE state='sending'"
            )
            # 兼容旧版：没有进入提交阶段的记录归还文本；绝不释放 unknown/sent。
            db.execute(
                "DELETE FROM assignments WHERE EXISTS (SELECT 1 FROM drafts d WHERE d.scope=assignments.scope AND d.item=assignments.target AND d.state IN ('pending','reserved','failed'))"
            )
            db.execute("DELETE FROM drafts WHERE state IN ('pending','reserved','failed')")
            self._rebuild_global_keys(db)

    def reserve_comment(self, rows, owner, target, order):
        target = str(target)
        if order == "random":
            rows = list(rows)
            random.shuffle(rows)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute(
                "SELECT 1 FROM comment_global_keys WHERE kind='target' AND value=?", (target,)
            ).fetchone():
                return None, "该推文已被其他账号领取、评论或待核对，已全局跳过"
            for source, text in rows:
                fingerprint = self.text_key(text)
                if db.execute(
                    "SELECT 1 FROM comment_global_keys WHERE kind='text' AND value=?", (fingerprint,)
                ).fetchone():
                    continue
                db.execute("INSERT INTO comment_global_keys(kind,value) VALUES('target',?)", (target,))
                db.execute("INSERT INTO comment_global_keys(kind,value) VALUES('text',?)", (fingerprint,))
                db.execute(
                    "INSERT INTO assignments(scope,source,target) VALUES(?,?,?)", (owner, source, target)
                )
                db.execute(
                    "INSERT INTO drafts(scope,item,text,state,owner,updated) VALUES(?,?,?,'reserved',?,?)",
                    (owner, target, text, owner, time.time()),
                )
                return (target, text), "已全局领取"
        return None, "评论文本已全局用完"

    def release_before_submit(self, owner, target):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,text FROM drafts WHERE scope=? AND item=?", (owner, target)
            ).fetchone()
            if row is None or row["state"] not in ("pending", "reserved", "failed"):
                return False
            db.execute("DELETE FROM assignments WHERE scope=? AND target=?", (owner, target))
            db.execute("DELETE FROM drafts WHERE scope=? AND item=?", (owner, target))
            self._refresh_released_keys(db, target, row["text"])
            return True

    def cooldown(self, owner, interval):
        with self.connection() as db:
            row = db.execute(
                "SELECT MAX(updated) FROM drafts WHERE owner=? AND state IN ('sent','sending','unknown','rejected')",
                (owner,),
            ).fetchone()
        return max(0.0, min(interval, interval - (time.time() - row[0]))) if row[0] is not None else 0.0

    def unresolved(self):
        with self.connection() as db:
            return [
                dict(row)
                for row in db.execute(
                    "SELECT * FROM drafts WHERE state IN ('unknown','sending','failed','rejected') ORDER BY updated DESC"
                )
            ]

    def resolve(self, scope, item, sent):
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT state,text FROM drafts WHERE scope=? AND item=?", (scope, item)
            ).fetchone()
            if row is None or row["state"] not in ("unknown", "failed", "rejected"):
                return
            if sent:
                db.execute(
                    "UPDATE drafts SET state='sent',updated=?,error='已人工核对成功' WHERE scope=? AND item=?",
                    (time.time(), scope, item),
                )
            else:
                db.execute("DELETE FROM assignments WHERE scope=? AND target=?", (scope, item))
                db.execute("DELETE FROM drafts WHERE scope=? AND item=?", (scope, item))
                self._refresh_released_keys(db, item, row["text"])


class CommentPublisher:
    EDITOR = '[contenteditable="true"][data-testid^="tweetTextarea_"]:visible, [data-testid^="tweetTextarea_"] [contenteditable="true"]:visible'
    SEND = '[data-testid="tweetButton"]:visible, [data-testid="tweetButtonInline"]:visible'

    def __init__(self, executor):
        self.e, self.m, self.source = executor, executor.m, executor.page
        self.page = None
        self.store = CommentStore()
        self.stage, self.surface = "等待", ""
        self.deadline = None

    def state(self, name, reason=""):
        m = self.m
        previous = m.stats.get("comment_status")
        m.stats["comment_status"] = {"state": name, "reason": reason}
        if previous != m.stats["comment_status"]:
            m.log(f"评论状态：{name}" + (f"｜{reason}" if reason else ""))

    def gate(self):
        self.e.gate()
        if self.deadline is not None and self.m.clock.elapsed() >= self.deadline:
            raise SceneBudgetExceeded("评论操作预算用尽")
        if self.page is not None and self.page.is_closed():
            raise ContentUnavailable("当前评论页面已关闭")

    def timeout(self, ms):
        self.gate()
        left = self.m.remaining()
        if self.deadline is not None:
            left = min(left, self.deadline - self.m.clock.elapsed())
        return max(1, int(min(T(ms), left * 1000)))

    def pump(self):
        self.gate()
        # 必须驱动 Playwright 事件循环，否则 threading.sleep 期间响应监听不会派发。
        self.page.wait_for_timeout(min(100, self.timeout(100)))
        self.gate()

    def poll(self, fn, seconds):
        end = self.m.clock.elapsed() + seconds
        while self.m.clock.elapsed() < end:
            self.gate()
            result = fn()
            if result is not None:
                return result
            self.pump()
        return None

    def health(self):
        status = check_page_health(self.page)
        if status == "logged_out":
            raise AccountStateError(Result.LOGIN_LOST)
        if status == "needs_action":
            raise AccountStateError(Result.NEEDS_ACTION)
        if status == "error_page":
            raise ContentUnavailable("目标推文页面加载失败")

    def root_article(self, target):
        link = self.page.locator(
            f'a[href$="/status/{target}"]:has(time), a[href*="/status/{target}?"]:has(time)'
        )
        return self.page.locator('article[data-testid="tweet"]').filter(has=link).first

    def find_composer(self):
        # 先找弹窗，再找详情页内嵌输入框；不假设必须有 role=dialog。
        dialogs = self.page.locator('[role="dialog"]:visible')
        for index in range(dialogs.count() - 1, -1, -1):
            dialog = dialogs.nth(index)
            editors = dialog.locator(self.EDITOR)
            if editors.count():
                return editors.first, "弹窗"
        editors = self.page.locator(self.EDITOR)
        for index in range(editors.count()):
            editor = editors.nth(index)
            if not editor.locator('xpath=ancestor::article').count():
                return editor, "详情页内嵌"
        return None

    def open_composer(self, target):
        self.health()
        article = self.root_article(target)
        article.wait_for(state="visible", timeout=self.timeout(10000))
        composer = self.poll(self.find_composer, 2)
        if composer is not None:
            return composer
        self.stage = "打开回复输入框"
        button = article.locator('[data-testid="reply"]:visible').first
        button.wait_for(state="visible", timeout=self.timeout(6000))
        if not button.is_enabled():
            raise ContentUnavailable("本推文不允许当前账号回复")
        button.scroll_into_view_if_needed(timeout=self.timeout(4000))
        # 打开入口可有限重试；实际提交仅在 submit_once 中进行一次。
        for attempt in range(2):
            self.gate()
            try:
                self.m.behavior.click(self.page, button, timeout=self.timeout(6000))
            except (StopRequested, DurationReached, SceneBudgetExceeded, CdpStateError, AccountStateError):
                raise
            except Exception:
                logger.debug("回复入口点击未确认", exc_info=True)
            composer = self.poll(self.find_composer, 4)
            if composer is not None:
                return composer
            self.health()
            article = self.root_article(target)
            button = article.locator('[data-testid="reply"]:visible').first
        raise ContentUnavailable("回复入口未出现输入框，可能被遮挡或没有回复权限")

    def send_button(self, editor):
        # 绑定到此输入框最近的提交容器，避免点到普通发帖或其他推文的按钮。
        container = editor.locator(
            'xpath=ancestor::*[.//*[@data-testid="tweetButton"] or .//*[@data-testid="tweetButtonInline"]][1]'
        )
        buttons = (
            container.locator(self.SEND)
            if container.count()
            else self.page.locator('[data-testid="tweetButtonInline"]:visible')
        )
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.is_visible() and button.is_enabled():
                return button
        return None

    def fill_composer(self, editor, text):
        self.stage = "填写评论"
        previous = normalize_comment_text(editor.inner_text(timeout=self.timeout(2000)))
        wanted = normalize_comment_text(text)
        if previous and previous != wanted:
            raise ValueError("回复框已有不同内容，保留已有草稿，未覆盖")
        if previous != wanted:
            editor.fill(text, timeout=self.timeout(6000))
        if normalize_comment_text(editor.inner_text(timeout=self.timeout(2000))) != wanted:
            raise ValueError("评论输入校验失败，未点击发送")
        button = self.poll(lambda: self.send_button(editor), 3)
        if button is None:
            # 受控输入框有时需键盘输入事件才能刷新提交状态；只操作本次相同内容。
            self.stage = "等待输入框同步"
            self.m.behavior.click(self.page, editor, timeout=self.timeout(2000))
            editor.press("Meta+A" if sys.platform == "darwin" else "Control+A", timeout=self.timeout(2000))
            editor.press("Backspace", timeout=self.timeout(2000))
            self.page.keyboard.insert_text(text)
            editor.press("ArrowRight", timeout=self.timeout(2000))
            if normalize_comment_text(editor.inner_text(timeout=self.timeout(2000))) != wanted:
                raise ValueError("键盘输入校验失败，未点击发送")
            button = self.poll(lambda: self.send_button(editor), 4)
        if button is None:
            raise ValueError("评论按钮持续不可用，请检查文本长度、账号状态或回复权限")
        return button

    def mark_sending(self, target):
        self.store.update(self.m.browser_id, target, self.m.browser_id, "sending")

    def count_attempt(self):
        self.m.comment_attempts += 1
        self.m.stats["comment_attempts"] = self.m.comment_attempts

    def submit_once(self, button, text, target):
        m, responses, requests = self.m, [], []

        def on_request(request):
            if reply_request_variables(request, text, target) is not None:
                requests.append(request)

        def on_response(response):
            if reply_request_variables(response.request, text, target) is not None:
                responses.append(response)

        self.page.on("request", on_request)
        self.page.on("response", on_response)
        attempted = False
        try:
            self.stage = "提交前检查"
            button.scroll_into_view_if_needed(timeout=self.timeout(3000))
            button.click(trial=True, timeout=self.timeout(4000))
            self.gate()
            self.mark_sending(target)
            # 落盘后即算一次提交尝试；超时也不会再次点击发送。
            attempted = True
            self.count_attempt()
            self.stage = "等待评论结果"
            try:
                self.gate()
                self.m.behavior.click(self.page, button, timeout=self.timeout(6000))
            except (StopRequested, DurationReached, SceneBudgetExceeded, CdpStateError, AccountStateError):
                raise
            except Exception:
                logger.warning("评论发送点击异常，继续检查已发出的响应，不重复点击", exc_info=True)
            end = m.clock.elapsed() + 15
            while m.clock.elapsed() < end:
                self.gate()
                while responses:
                    response = responses.pop(0)
                    try:
                        payload = response.json()
                    except Exception:
                        if response.status >= 400:
                            raise CommentRejected(response.status, "接口拒绝请求，响应不是JSON")
                        continue
                    errors = payload.get("errors") if isinstance(payload, dict) else None
                    if response.status >= 400 or errors:
                        raise CommentRejected(response.status, errors or "接口拒绝请求")
                    tid = created_reply_id(payload, target)
                    if tid:
                        return tid
                self.pump()
            self.state(
                "结果待核对", "已捕获回复请求但未收到成功确认" if requests else "点击后未捕获匹配回复请求"
            )
            return None
        except BaseException:
            if attempted:
                # 由调用层读取此状态，不能把已尝试提交归为可重试的准备失败。
                m.stats["comment_last_armed"] = True
            raise
        finally:
            m.stats["comment_last_armed"] = attempted
            for event, callback in (("request", on_request), ("response", on_response)):
                try:
                    self.page.remove_listener(event, callback)
                except Exception:
                    logger.debug("清理评论监听未完成", exc_info=True)

    def diagnostic(self, target_url, exc):
        path = (
            DATA_DIR
            / "comment_diagnostics"
            / f"{hashlib.sha256(self.m.browser_id.encode()).hexdigest()[:12]}_{time.time_ns()}.json"
        )
        data = {
            "version": APP_VERSION,
            "stage": self.stage,
            "surface": self.surface,
            "target": target_url,
            "error": str(exc),
            "account": self.m.browser_id,
        }
        try:
            if self.page is not None and not self.page.is_closed():
                data.update(
                    {
                        "url": self.page.url,
                        "visible_editors": self.page.locator(self.EDITOR).count(),
                        "visible_send_buttons": self.page.locator(self.SEND).count(),
                    }
                )
            atomic_json(path, data)
            self.m.log(f"评论诊断已保存：{path}")
        except Exception:
            logger.warning("保存评论诊断失败", exc_info=True)

    def maybe_comment(self):
        m = self.m
        if not m.cfg.comment_enabled or m.cfg.draft_enabled:
            return
        if m.comment_halted:
            return
        if m.comment_attempts >= m.cfg.comment_count:
            self.state(
                "本轮次数已完成",
                f"已确认{m.stats.get('comments_sent', 0)}，待核对{m.stats.get('comments_unknown', 0)}",
            )
            return
        if m.clock.elapsed() < m.comment_retry_at:
            return
        delay = self.store.cooldown(m.browser_id, m.cfg.comment_interval)
        if delay > 0:
            self.state("等待间隔", f"成功或提交后间隔 {m.cfg.comment_interval:g} 秒")
            return
        if m.remaining() < 15:
            self.state("时长不足", "剩余时间不足15秒，继续当前阅读")
            return
        if not m.comment_candidates:
            self.state("等待已读推文")
            return
        self.e.gate()
        item, target_url = None, None
        while m.comment_candidates:
            target, url = m.comment_candidates.popitem(last=False)
            if target in m.comment_skipped_targets:
                continue
            item, reason = self.store.reserve_comment(
                m.ctl.comment_rows, m.browser_id, target, m.cfg.comment_order
            )
            if item is not None:
                target_url = url
                break
            self.state(reason)
            if reason == "评论文本已全局用完":
                return
        if item is None:
            return
        target, text = item
        original_deadline = m.scene_deadline
        started = m.clock.elapsed()
        m.scene_deadline = None
        self.deadline = started + min(70, m.remaining())
        m.stats["comment_last_armed"] = False
        self.stage, self.surface = "准备当前页面评论", ""
        snapshot = None
        original_dialogs = 0
        self.state("正在评论", target_url)
        try:
            self.gate()
            self.page = self.source
            same_target = canonical_status_url(self.page.url or '') == canonical_status_url(target_url)
            if not same_target:
                # 不导航离开用户已有的未提交输入。
                draft = self.page.locator('[contenteditable="true"]:visible').evaluate_all(
                    "els=>els.some(e=>(e.innerText||'').trim())"
                )
                if draft:
                    raise ContentUnavailable("当前页有未提交内容，保留原页并跳过此次评论")
            else:
                texts = self.page.locator(self.EDITOR).evaluate_all(
                    "els=>els.map(e=>(e.innerText||'').trim()).filter(Boolean)"
                )
                if any(normalize_comment_text(value) != normalize_comment_text(text) for value in texts):
                    raise ContentUnavailable("目标页已有其他评论草稿，保留原内容")
            original_dialogs = self.page.locator('[role="dialog"]:visible').count()
            snapshot = self.e.navigator.capture()
            self.stage = "在当前页加载目标推文"
            if not same_target:
                self.page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout(15000))
            self.gate()
            editor, self.surface = self.open_composer(target)
            button = self.fill_composer(editor, text)
            tid = self.submit_once(button, text, target)
            if tid:
                reply_url = f"https://x.com/i/status/{tid}"
                self.store.update(m.browser_id, target, m.browser_id, "sent", url=reply_url)
                m.stats["comments_sent"] = m.stats.get("comments_sent", 0) + 1
                m.comment_prepare_failures = 0
                self.state("评论成功", f"{target_url} → {reply_url}")
            else:
                self.store.update(
                    m.browser_id,
                    target,
                    m.browser_id,
                    "unknown",
                    error="提交后没有获得成功确认；不重复评论本目标",
                )
                m.stats["comments_unknown"] = m.stats.get("comments_unknown", 0) + 1
                self.diagnostic(target_url, RuntimeError("等待回复响应超时"))
        except BaseException as exc:
            armed = m.stats.get("comment_last_armed", False)
            logger.warning(
                "评论失败 stage=%s target=%s armed=%s", self.stage, target_url, armed, exc_info=True
            )
            if isinstance(exc, CommentRejected):
                self.store.update(m.browser_id, target, m.browser_id, "rejected", error=str(exc))
                self.state("服务端拒绝", str(exc))
                # 账号/频率/文本问题不盲目重试，阅读仍继续。
                m.comment_halted = True
            elif armed:
                self.store.update(
                    m.browser_id, target, m.browser_id, "unknown", error=f"{self.stage}：{short_error(exc)}"
                )
                m.stats["comments_unknown"] = m.stats.get("comments_unknown", 0) + 1
                self.state("结果待核对", "保留本目标和文本，后续其他目标仍按间隔执行")
            else:
                self.store.release_before_submit(m.browser_id, target)
                m.comment_prepare_failures += 1
                m.comment_retry_at = m.clock.elapsed() + min(60, 5 * m.comment_prepare_failures)
                m.comment_skipped_targets.add(target)
                self.state("准备失败，继续养号", f"{self.stage}：{short_error(exc)}；评论文本未消耗")
                if isinstance(exc, ValueError):
                    m.comment_halted = True
            if not isinstance(exc, (StopRequested, DurationReached, KeyboardInterrupt, SystemExit)):
                self.diagnostic(target_url, exc)
            if isinstance(
                exc,
                (
                    StopRequested,
                    DurationReached,
                    CdpStateError,
                    AccountStateError,
                    KeyboardInterrupt,
                    SystemExit,
                ),
            ):
                raise
        finally:
            active_error = sys.exc_info()[1]
            restore_error = None
            self.deadline = None
            try:
                if (
                    snapshot is not None
                    and not isinstance(
                        active_error,
                        (
                            StopRequested,
                            DurationReached,
                            CdpStateError,
                            AccountStateError,
                            KeyboardInterrupt,
                            SystemExit,
                        ),
                    )
                    and m.remaining() > 1
                ):
                    m.scene_deadline = m.clock.elapsed() + min(15, m.remaining())
                    try:
                        self.stage = "返回评论前的来源页面"
                        if self.source.locator('[role="dialog"]:visible').count() > original_dialogs:
                            self.source.keyboard.press('Escape')
                            if self.source.locator('[role="dialog"]:visible').count() > original_dialogs:
                                self.e.navigator.goto(snapshot.url)
                        self.e.navigator.restore(snapshot)
                    except (StopRequested, DurationReached, CdpStateError, AccountStateError):
                        raise
                    except Exception as exc:
                        restore_error = exc
                        m.log("评论结果已记录，来源页恢复未完成；交由阅读流程恢复页面。")
            finally:
                self.page = None  # 主标签属于浏览会话，评论器绝不关闭它。
                # 评论与返回用时不占阅读场景预算，总时长正常累计。
                m.scene_deadline = (
                    original_deadline + (m.clock.elapsed() - started)
                    if original_deadline is not None
                    else None
                )
            if restore_error is not None and active_error is None:
                raise PageNotReady("评论结束后来源页未恢复：" + short_error(restore_error)) from restore_error


# ======================================================================
# 模块：xmanager/dashboard.py
# ======================================================================
"""账号数据看板数据库（SQLite）。"""


import bisect
import csv
import random
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


_DASH_SCHEMA = """
CREATE TABLE IF NOT EXISTS snapshots(
    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, name TEXT NOT NULL DEFAULT '',
    handle TEXT NOT NULL DEFAULT '', ts REAL NOT NULL, followers INTEGER, following INTEGER,
    likes INTEGER NOT NULL DEFAULT 0, replies INTEGER NOT NULL DEFAULT 0,
    reposts INTEGER NOT NULL DEFAULT 0, views INTEGER NOT NULL DEFAULT 0,
    posts INTEGER NOT NULL DEFAULT 0, dm_unread INTEGER, dm_convs INTEGER, notif_unread INTEGER,
    source TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_snap_acc_ts ON snapshots(account, ts);
CREATE TABLE IF NOT EXISTS post_metrics(
    account TEXT NOT NULL, status_id TEXT NOT NULL, ts REAL NOT NULL, text TEXT NOT NULL DEFAULT '',
    likes INTEGER NOT NULL DEFAULT 0, replies INTEGER NOT NULL DEFAULT 0,
    reposts INTEGER NOT NULL DEFAULT 0, views INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY(account, status_id));
CREATE TABLE IF NOT EXISTS inbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT, account TEXT NOT NULL, kind TEXT NOT NULL,
    ext_id TEXT NOT NULL, author TEXT NOT NULL DEFAULT '', text TEXT NOT NULL DEFAULT '',
    url TEXT NOT NULL DEFAULT '', first_seen REAL NOT NULL, last_seen REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'new', UNIQUE(account, kind, ext_id));
CREATE TABLE IF NOT EXISTS outbox(
    id INTEGER PRIMARY KEY AUTOINCREMENT, inbox_id INTEGER, account TEXT NOT NULL,
    kind TEXT NOT NULL, target TEXT NOT NULL DEFAULT '', author TEXT NOT NULL DEFAULT '',
    text TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'pending', created REAL NOT NULL,
    updated REAL NOT NULL, error TEXT NOT NULL DEFAULT '', result_url TEXT NOT NULL DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_outbox_acc_state ON outbox(account, state);
CREATE TABLE IF NOT EXISTS events(
    id INTEGER PRIMARY KEY AUTOINCREMENT, ts REAL NOT NULL, account TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '', kind TEXT NOT NULL, summary TEXT NOT NULL DEFAULT '');
"""


class AccountDataStore:
    """看板数据库（SQLite + WAL）。每次操作单独开连接，多账号线程和界面线程可同时读写。"""

    DEMO_PREFIX = "demo:"

    def __init__(self, path: Optional[Path] = None):
        self.path = Path(path) if path is not None else DATA_DIR / "dashboard.sqlite3"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connection() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.executescript(_DASH_SCHEMA)
            db.executescript(RECENT_SCHEMA)
            from xmanager_outgoing import SCHEMA as OUTGOING_SCHEMA
            db.executescript(OUTGOING_SCHEMA)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(str(self.path), timeout=30)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA busy_timeout = 30000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def record_recent_scan(self,account,name,handle,posts,started,cutoff,states,notes=()):
        finished=time.time()
        with self.connection() as db:
            db.execute('BEGIN IMMEDIATE')
            for p in posts:
                db.execute('''INSERT INTO recent_activity(account,status_id,handle,name,published_ts,observed_at,kind,url,text,views,likes,replies,reposts)
                 VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(account,status_id) DO UPDATE SET
                 handle=excluded.handle,name=excluded.name,published_ts=excluded.published_ts,observed_at=excluded.observed_at,
                 kind=CASE WHEN recent_activity.kind='post' AND excluded.kind='unknown' THEN 'post' ELSE excluded.kind END,
                 url=excluded.url,text=excluded.text,views=excluded.views,likes=excluded.likes,replies=excluded.replies,reposts=excluded.reposts''',
                 (account,p['id'],handle,name,p['published_ts'],p.get('observed_at',finished),p['kind'],p['url'],p['text'],p.get('views'),p.get('likes'),p.get('replies'),p.get('reposts')))
            db.execute('''INSERT INTO recent_scans VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(account) DO UPDATE SET
             name=excluded.name,handle=excluded.handle,started=excluded.started,finished=excluded.finished,cutoff=excluded.cutoff,
             posts_state=excluded.posts_state,replies_state=excluded.replies_state,notes=excluded.notes''',
             (account,name,handle,started,finished,cutoff,states['posts'],states['replies'],json.dumps(list(dict.fromkeys(notes)),ensure_ascii=False)))
            # 保留7天便于核对；旧累计表和旧看板不改动。
            db.execute('DELETE FROM recent_activity WHERE published_ts<?',(finished-7*86400,))

    def recent_performance(self,now=None):
        now=time.time() if now is None else float(now)
        with self.connection() as db:
            posts=[dict(r) for r in db.execute('SELECT * FROM recent_activity WHERE published_ts>=? AND published_ts<=?',(now-8*3600,now))]
            scans={r['account']:dict(r) for r in db.execute('SELECT * FROM recent_scans')}
        grouped={}
        for p in posts:grouped.setdefault(p['account'],[]).append(p)
        accounts=[]
        for aid in sorted(set(scans)|set(grouped)):
            meta=scans.get(aid,{})
            rows=grouped.get(aid,[])
            stale=not meta.get('finished') or now-meta['finished']>900
            complete=not stale and meta.get('notes','[]')=='[]' and all(meta.get(k) in ('已读到8小时之前','页面显示无内容') for k in ('posts_state','replies_state'))
            row={'account':aid,'name':meta.get('name',aid),'handle':meta.get('handle',''),
                 'post_count':sum(p['kind']=='post' for p in rows),'reply_count':sum(p['kind']=='reply' for p in rows),
                 'unknown_count':sum(p['kind']=='unknown' for p in rows),'total_count':len(rows),
                 'partial':not complete,'stale':stale,'finished':meta.get('finished'),'posts_state':meta.get('posts_state','未采集'),
                 'replies_state':meta.get('replies_state','未采集'),'notes':meta.get('notes','[]')}
            for key in RECENT_METRICS:
                known=[p[key] for p in rows if p[key] is not None]
                row[key]=sum(known) if known else 0 if not rows and complete else None
                row[key+'_missing']=sum(p[key] is None for p in rows)
            accounts.append(row)
        return accounts,posts

    # ---------- 采集结果 ----------
    def record_collection(self, account, name, handle, posts, info, source=""):
        """保存一次采集：帖子指标按帖更新，账号快照 = 全部已追踪帖子的合计。
        info 里没采到的字段（None）沿用上一次的值。"""
        now = time.time()
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for p in posts or []:
                db.execute(
                    """INSERT INTO post_metrics(account,status_id,ts,text,likes,replies,reposts,views)
                       VALUES(?,?,?,?,?,?,?,?)
                       ON CONFLICT(account,status_id) DO UPDATE SET ts=excluded.ts,text=excluded.text,
                       likes=excluded.likes,replies=excluded.replies,reposts=excluded.reposts,views=excluded.views""",
                    (account, p["id"], now, p["text"], p["likes"], p["replies"], p["reposts"], p["views"]),
                )
            total = db.execute(
                "SELECT COALESCE(SUM(likes),0),COALESCE(SUM(replies),0),COALESCE(SUM(reposts),0),"
                "COALESCE(SUM(views),0),COUNT(*) FROM post_metrics WHERE account=?",
                (account,),
            ).fetchone()
            prev = db.execute(
                "SELECT * FROM snapshots WHERE account=? ORDER BY id DESC LIMIT 1", (account,)
            ).fetchone()

            def pick(key):
                value = info.get(key)
                if value is not None:
                    return value
                return prev[key] if prev is not None else None

            db.execute(
                """INSERT INTO snapshots(account,name,handle,ts,followers,following,likes,replies,reposts,
                   views,posts,dm_unread,dm_convs,notif_unread,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    account,
                    name,
                    handle or (prev["handle"] if prev is not None else ""),
                    now,
                    pick("followers"),
                    pick("following"),
                    total[0],
                    total[1],
                    total[2],
                    total[3],
                    total[4],
                    pick("dm_unread"),
                    pick("dm_convs"),
                    pick("notif_unread"),
                    source,
                ),
            )

    def record_outgoing_success(self, account, action, target):
        from xmanager_outgoing import record
        return record(self, account, action, target)

    def outgoing_counts(self):
        from xmanager_outgoing import counts, sync_confirmed
        sync_confirmed(self, DATA_DIR / 'comment_queue.sqlite3')
        return counts(self)

    def overview(self, day_start: float) -> List[Dict[str, Any]]:
        """每账号最新快照 + 今日新增（对比今天零点前最后一次快照，没有就对比最早一次）。"""
        with self.connection() as db:
            latest = db.execute(
                "SELECT s.* FROM snapshots s JOIN (SELECT MAX(id) mid FROM snapshots GROUP BY account) m ON s.id=m.mid"
            ).fetchall()
            before = {
                r["account"]: r
                for r in db.execute(
                    "SELECT s.* FROM snapshots s JOIN (SELECT MAX(id) mid FROM snapshots WHERE ts<? GROUP BY account) m ON s.id=m.mid",
                    (day_start,),
                )
            }
            first = {
                r["account"]: r
                for r in db.execute(
                    "SELECT s.* FROM snapshots s JOIN (SELECT MIN(id) mid FROM snapshots GROUP BY account) m ON s.id=m.mid"
                )
            }
            fresh: Dict[str, Dict[str, int]] = {}
            for r in db.execute(
                "SELECT account,kind,COUNT(*) c FROM inbox WHERE state='new' GROUP BY account,kind"
            ):
                fresh.setdefault(r["account"], {})[r["kind"]] = r["c"]
        rows = []
        for r in latest:
            row = dict(r)
            base = before.get(row["account"]) or first.get(row["account"])
            row["likes_today"] = max(0, row["likes"] - base["likes"]) if base is not None else 0
            row["replies_today"] = max(0, row["replies"] - base["replies"]) if base is not None else 0
            row["followers_today"] = (
                row["followers"] - base["followers"]
                if base is not None and row["followers"] is not None and base["followers"] is not None
                else 0
            )
            row["inbox_new"] = fresh.get(row["account"], {})
            rows.append(row)
        outgoing = self.outgoing_counts()
        seen = {r['account'] for r in rows}
        for account, values in outgoing.items():
            if account not in seen:
                rows.append(dict(account=account,name=account,handle='',outgoing_only=True,ts=values['outgoing_latest'],
                    followers=None,following=None,likes=0,replies=0,reposts=0,views=0,posts=0,
                    dm_unread=None,dm_convs=None,notif_unread=None,likes_today=0,replies_today=0,followers_today=0))
        for row in rows:
            values = outgoing.get(row['account'], {})
            row['comments_sent_total'] = values.get('comments_sent_total', 0)
            row['likes_sent_total'] = values.get('likes_sent_total', 0)
        return rows

    def trend(self, days: int = 7, now: Optional[float] = None) -> Tuple[List[str], List[int], List[int]]:
        """近 N 天每天新增获赞 / 新增评论（所有账号合计）。"""
        now = now or time.time()
        base = datetime.fromtimestamp(now).replace(hour=0, minute=0, second=0, microsecond=0)
        starts = [(base - timedelta(days=i)).timestamp() for i in range(days - 1, -1, -1)]
        labels = [datetime.fromtimestamp(s).strftime("%m-%d") for s in starts]
        likes, replies = [0] * days, [0] * days
        with self.connection() as db:
            rows = db.execute(
                "SELECT account,ts,likes,replies FROM snapshots WHERE ts>=? ORDER BY account,ts", (starts[0],)
            ).fetchall()
            before = db.execute(
                "SELECT s.account,s.likes,s.replies FROM snapshots s JOIN "
                "(SELECT MAX(id) mid FROM snapshots WHERE ts<? GROUP BY account) m ON s.id=m.mid",
                (starts[0],),
            ).fetchall()
        prev = {r["account"]: (r["likes"], r["replies"]) for r in before}
        for r in rows:
            idx = bisect.bisect_right(starts, r["ts"]) - 1
            last = prev.get(r["account"])
            if last is not None and 0 <= idx < days:
                likes[idx] += max(0, r["likes"] - last[0])
                replies[idx] += max(0, r["replies"] - last[1])
            prev[r["account"]] = (r["likes"], r["replies"])
        return labels, likes, replies

    def history(self, account: str, limit: int = 60) -> List[Dict[str, Any]]:
        with self.connection() as db:
            rows = db.execute(
                "SELECT ts,followers,likes,replies,dm_unread FROM snapshots WHERE account=? ORDER BY id DESC LIMIT ?",
                (account, limit),
            ).fetchall()
        return [dict(r) for r in reversed(rows)]

    def inbox_new_count(self) -> int:
        with self.connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM inbox i WHERE i.state='new' AND i.account NOT LIKE ? AND NOT EXISTS "
                "(SELECT 1 FROM outbox o WHERE o.inbox_id=i.id AND o.state IN ('pending','sending','unknown'))",
                (self.DEMO_PREFIX + "%",),
            ).fetchone()[0]

    def posts_for(self, account: str, limit: int = 60) -> List[Dict[str, Any]]:
        with self.connection() as db:
            return [
                dict(r)
                for r in db.execute(
                    "SELECT * FROM post_metrics WHERE account=? ORDER BY CAST(status_id AS INTEGER) DESC LIMIT ?",
                    (account, limit),
                )
            ]

    # ---------- 收件箱 ----------
    def upsert_inbox(self, account: str, items: List[Dict[str, Any]]) -> int:
        now, new = time.time(), 0
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for it in items:
                row = db.execute(
                    "SELECT id,text,state FROM inbox WHERE account=? AND kind=? AND ext_id=?",
                    (account, it["kind"], it["ext_id"]),
                ).fetchone()
                wanted = it.get("state", "new")
                if row is None:
                    db.execute(
                        "INSERT INTO inbox(account,kind,ext_id,author,text,url,first_seen,last_seen,state) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            account,
                            it["kind"],
                            it["ext_id"],
                            it.get("author", ""),
                            it.get("text", ""),
                            it.get("url", ""),
                            now,
                            now,
                            wanted,
                        ),
                    )
                    new += 1 if wanted == "new" else 0
                else:
                    state = row["state"]
                    if it["kind"] == "dm" and row["text"] != it.get("text", "") and wanted == "new":
                        state = "new"  # 对方又发来新消息
                        new += 1
                    db.execute(
                        "UPDATE inbox SET author=?,text=?,url=CASE WHEN ?<>'' THEN ? ELSE url END,last_seen=?,state=? WHERE id=?",
                        (
                            it.get("author", ""),
                            it.get("text", ""),
                            it.get("url", ""),
                            it.get("url", ""),
                            now,
                            state,
                            row["id"],
                        ),
                    )
        return new

    def list_inbox(self, account=None, kind=None, state=None, query="", limit=500):
        sql = (
            "SELECT i.*, (SELECT o.state FROM outbox o WHERE o.inbox_id=i.id ORDER BY o.id DESC LIMIT 1) AS out_state "
            "FROM inbox i WHERE 1=1"
        )
        args: List[Any] = []
        if account:
            sql += " AND i.account=?"
            args.append(account)
        if kind:
            sql += " AND i.kind=?"
            args.append(kind)
        if state:
            sql += " AND i.state=?"
            args.append(state)
        if query:
            sql += " AND (i.text LIKE ? OR i.author LIKE ?)"
            args += [f"%{query}%", f"%{query}%"]
        sql += " ORDER BY i.last_seen DESC, i.id DESC LIMIT ?"
        args.append(limit)
        with self.connection() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def set_inbox_state(self, ids, state: str) -> None:
        ids = list(ids)
        if not ids:
            return
        with self.connection() as db:
            db.executemany("UPDATE inbox SET state=? WHERE id=?", [(state, i) for i in ids])

    def set_inbox_url(self, inbox_id, url: str) -> None:
        if inbox_id and url:
            with self.connection() as db:
                db.execute("UPDATE inbox SET url=? WHERE id=?", (url, inbox_id))

    # ---------- 待发回复（人工逐条写） ----------
    def queue_reply(self, inbox_id: int, text: str) -> int:
        text = normalize_comment_text(text)
        if not text:
            raise ValueError("回复内容不能为空")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT * FROM inbox WHERE id=?", (inbox_id,)).fetchone()
            if row is None:
                raise ValueError("这条消息已不存在")
            if row["kind"] == "dm":
                if len(text) > 1000:
                    raise ValueError(f"私信最多 1000 字，当前 {len(text)}")
            elif x_weighted_length(text) > 280:
                raise ValueError(
                    f"回复超出 X 的 280 计数上限（中文每字算 2），当前 {x_weighted_length(text)}"
                )
            if db.execute(
                "SELECT 1 FROM outbox WHERE inbox_id=? AND state IN ('pending','sending','unknown')",
                (inbox_id,),
            ).fetchone():
                raise ValueError("这条消息已有待发或待核对的回复，请先处理")
            kind = "dm" if row["kind"] == "dm" else "reply"
            target = row["url"] if kind == "dm" else row["ext_id"]
            now = time.time()
            cur = db.execute(
                "INSERT INTO outbox(inbox_id,account,kind,target,author,text,state,created,updated) VALUES(?,?,?,?,?,?,'pending',?,?)",
                (inbox_id, row["account"], kind, target, row["author"], text, now, now),
            )
            return int(cur.lastrowid)

    def list_outbox(self, account=None, states=None, limit=200):
        sql, args = "SELECT * FROM outbox WHERE 1=1", []
        if account:
            sql += " AND account=?"
            args.append(account)
        if states:
            sql += " AND state IN (%s)" % ",".join("?" * len(states))
            args += list(states)
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        with self.connection() as db:
            return [dict(r) for r in db.execute(sql, args)]

    def pending_count(self, account: str) -> int:
        with self.connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM outbox WHERE account=? AND state='pending'", (account,)
            ).fetchone()[0]

    def pending_counts(self) -> Dict[str, int]:
        with self.connection() as db:
            return {
                r["account"]: r["c"]
                for r in db.execute(
                    "SELECT account,COUNT(*) c FROM outbox WHERE state='pending' GROUP BY account"
                )
            }

    def claim_outbox(self, account: str) -> Optional[Dict[str, Any]]:
        """原子领取最早的一条待发；领取后立刻标记 sending，任何情况下都不会被领第二次。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM outbox WHERE account=? AND state='pending' ORDER BY id LIMIT 1", (account,)
            ).fetchone()
            if row is None:
                return None
            db.execute("UPDATE outbox SET state='sending',updated=? WHERE id=?", (time.time(), row["id"]))
            item = dict(row)
            item["state"] = "sending"
            source = db.execute("SELECT url,text FROM inbox WHERE id=?", (row["inbox_id"],)).fetchone()
            item["url"] = source["url"] if source else ""
            item["source_text"] = source["text"] if source else ""
            return item

    def finish_outbox(self, oid: int, state: str, error: str = "", url: str = "") -> None:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT inbox_id FROM outbox WHERE id=?", (oid,)).fetchone()
            db.execute(
                "UPDATE outbox SET state=?,error=?,result_url=?,updated=? WHERE id=?",
                (state, error[:300], url, time.time(), oid),
            )
            if state == "sent" and row is not None and row["inbox_id"]:
                db.execute("UPDATE inbox SET state='handled' WHERE id=?", (row["inbox_id"],))

    def cancel_outbox(self, oid: int) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE outbox SET state='cancelled',updated=? WHERE id=? AND state='pending'",
                    (time.time(), oid),
                ).rowcount
                == 1
            )

    def retry_outbox(self, oid: int) -> bool:
        with self.connection() as db:
            return (
                db.execute(
                    "UPDATE outbox SET state='pending',error='',updated=? WHERE id=? AND state='failed'",
                    (time.time(), oid),
                ).rowcount
                == 1
            )

    def resolve_outbox(self, oid: int, sent: bool) -> None:
        """结果不明的条目：人工核对后标记为已发 / 重新入队。"""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT inbox_id,state,account,kind,target FROM outbox WHERE id=?", (oid,)
            ).fetchone()
            if row is None or row["state"] not in ("unknown", "failed"):
                return
            if row['kind'] == 'reply':
                global_store = CommentStore()
                global_store.resolve(global_store.panel_scope(row['account'], oid), str(row['target']), sent)
            db.execute(
                "UPDATE outbox SET state=?,error='已人工核对',updated=? WHERE id=?",
                ("sent" if sent else "pending", time.time(), oid),
            )
            if sent and row["inbox_id"]:
                db.execute("UPDATE inbox SET state='handled' WHERE id=?", (row["inbox_id"],))

    def sent_today(self, account: str) -> int:
        with self.connection() as db:
            return db.execute(
                "SELECT COUNT(*) FROM outbox WHERE account=? AND state IN ('sent','unknown','sending') AND updated>=?",
                (account, local_midnight()),
            ).fetchone()[0]

    def last_send_ts(self, account: str) -> Optional[float]:
        with self.connection() as db:
            return db.execute(
                "SELECT MAX(updated) FROM outbox WHERE account=? AND state IN ('sent','unknown','sending')",
                (account,),
            ).fetchone()[0]

    def recover(self) -> int:
        """启动时调用：上次异常退出时停在 sending 的条目不自动重发，标记为待核对。"""
        with self.connection() as db:
            return db.execute(
                "UPDATE outbox SET state='unknown',error='上次发送被中断，请到账号里核对',updated=? WHERE state='sending'",
                (time.time(),),
            ).rowcount

    # ---------- 动态 / 维护 ----------
    def log_event(self, account: str, name: str, kind: str, summary: str) -> None:
        with self.connection() as db:
            db.execute(
                "INSERT INTO events(ts,account,name,kind,summary) VALUES(?,?,?,?,?)",
                (time.time(), account, name, kind, summary[:300]),
            )

    def recent_events(self, limit: int = 40) -> List[Dict[str, Any]]:
        with self.connection() as db:
            return [dict(r) for r in db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,))]

    def known_accounts(self) -> Dict[str, str]:
        with self.connection() as db:
            return {
                r["account"]: r["name"]
                for r in db.execute(
                    "SELECT s.account,s.name FROM snapshots s JOIN (SELECT MAX(id) mid FROM snapshots GROUP BY account) m ON s.id=m.mid"
                )
            }

    def prune(self, keep_days: int) -> int:
        cutoff = time.time() - keep_days * 86400
        removed = 0
        with self.connection() as db:
            removed += db.execute(
                "DELETE FROM snapshots WHERE ts<? AND id NOT IN "
                "(SELECT MAX(id) FROM snapshots GROUP BY account)",
                (cutoff,),
            ).rowcount
            removed += db.execute("DELETE FROM events WHERE ts<?", (cutoff,)).rowcount
            removed += db.execute("DELETE FROM inbox WHERE last_seen<? AND state<>'new'", (cutoff,)).rowcount
            removed += db.execute(
                "DELETE FROM outbox WHERE updated<? AND state IN ('sent','cancelled','failed')", (cutoff,)
            ).rowcount
        return removed

    def clear_demo(self) -> None:
        pattern = self.DEMO_PREFIX + "%"
        with self.connection() as db:
            for table in ("snapshots", "post_metrics", "inbox", "outbox", "events", "recent_activity", "recent_scans"):
                db.execute(f"DELETE FROM {table} WHERE account LIKE ?", (pattern,))

    def seed_demo(self) -> None:
        """写入一批明显标注为“演示”的假数据，方便没登录账号时先看看界面。"""
        self.clear_demo()
        rng = random.Random(42)
        now = time.time()
        names = ["演示·美妆号", "演示·数码号", "演示·美食号", "演示·旅行号", "演示·游戏号", "演示·财经号"]
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            for i, name in enumerate(names, 1):
                acc, handle = f"{self.DEMO_PREFIX}{i}", f"demo_user_{i}"
                followers, likes, replies = rng.randint(300, 4000), rng.randint(80, 400), rng.randint(10, 80)
                reposts, views = rng.randint(5, 40), rng.randint(2000, 20000)
                for d in range(8, -1, -1):
                    if d < 8:
                        followers += rng.randint(0, 40)
                        likes += rng.randint(5, 60)
                        replies += rng.randint(0, 9)
                        reposts += rng.randint(0, 6)
                        views += rng.randint(200, 2500)
                    ts = now - d * 86400 - rng.randint(60, 3000)
                    db.execute(
                        """INSERT INTO snapshots(account,name,handle,ts,followers,following,likes,replies,reposts,views,
                           posts,dm_unread,dm_convs,notif_unread,source) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                        (
                            acc,
                            name,
                            handle,
                            ts,
                            followers,
                            rng.randint(80, 600),
                            likes,
                            replies,
                            reposts,
                            views,
                            20,
                            rng.randint(0, 4) if d == 0 else 0,
                            rng.randint(2, 12),
                            rng.randint(0, 25) if d == 0 else 0,
                            "demo",
                        ),
                    )
                for p in range(12):
                    db.execute(
                        "INSERT INTO post_metrics(account,status_id,ts,text,likes,replies,reposts,views) VALUES(?,?,?,?,?,?,?,?)",
                        (
                            acc,
                            str(1800000000000000000 + i * 1000 + p),
                            now,
                            f"演示帖子 {p + 1}：这是一条用来预览界面的示例内容",
                            rng.randint(0, 60),
                            rng.randint(0, 9),
                            rng.randint(0, 6),
                            rng.randint(100, 3000),
                        ),
                    )
                for j in range(3):
                    db.execute(
                        "INSERT INTO inbox(account,kind,ext_id,author,text,url,first_seen,last_seen,state) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            acc,
                            "mention",
                            str(1800000000000900000 + i * 10 + j),
                            f"@fan_{j + 1}",
                            ["这个太实用了，谢谢分享！", "请问可以详细讲讲吗？", "哈哈同感，我也是这么用的"][
                                j
                            ],
                            f"https://x.com/fan_{j + 1}/status/{1800000000000900000 + i * 10 + j}",
                            now - j * 3600,
                            now - j * 3600,
                            "new" if j < 2 else "handled",
                        ),
                    )
                db.execute(
                    "INSERT INTO inbox(account,kind,ext_id,author,text,url,first_seen,last_seen,state) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        acc,
                        "dm",
                        f"conv:demo{i}",
                        "演示用户",
                        "你好，想问一下合作的事情",
                        "",
                        now - 1800,
                        now - 1800,
                        "new",
                    ),
                )
                db.execute(
                    "INSERT INTO events(ts,account,name,kind,summary) VALUES(?,?,?,?,?)",
                    (
                        now - i * 600,
                        acc,
                        name,
                        "collect",
                        f"粉丝 {followers} · 获赞 {likes} · 评论 {replies}（演示数据）",
                    ),
                )

    def export_csv(self, path: Path) -> int:
        def safe(value):
            text = "" if value is None else str(value)
            return "'" + text if text.lstrip().startswith(("=", "+", "-", "@")) else text

        rows = self.overview(local_midnight())
        with path.open("w", encoding="utf-8-sig", newline="") as out:
            writer = csv.writer(out)
            writer.writerow(
                [
                    "环境ID",
                    "名称",
                    "用户名",
                    "粉丝",
                    "关注",
                    "累计获赞",
                    "今日新增获赞",
                    "累计评论回复",
                    "累计成功发出评论数",
                    "累计成功点赞数",
                    "今日新增评论",
                    "转发",
                    "浏览",
                    "已追踪帖子",
                    "私信未读",
                    "私信会话数",
                    "通知未读",
                    "最近采集",
                ]
            )
            for r in rows:
                writer.writerow(
                    [
                        safe(r["account"]),
                        safe(r["name"]),
                        safe(r["handle"]),
                        r["followers"],
                        r["following"],
                        r["likes"],
                        r["likes_today"],
                        r["replies"],
                        r["comments_sent_total"],
                        r["likes_sent_total"],
                        r["replies_today"],
                        r["reposts"],
                        r["views"],
                        r["posts"],
                        r["dm_unread"],
                        r["dm_convs"],
                        r["notif_unread"],
                        datetime.fromtimestamp(r["ts"]).strftime("%Y-%m-%d %H:%M:%S"),
                    ]
                )
        return len(rows)

    def latest_collection_times(self) -> Dict[str, float]:
        """只使用成功保存的采集快照；失败尝试不改变账号优先级。"""
        with self.connection() as db:
            return {r['account']:r['ts'] for r in db.execute(
                "SELECT account, MAX(ts) AS ts FROM snapshots WHERE source NOT LIKE '%/partial' GROUP BY account")}




_STORE: Optional[AccountDataStore] = None
_STORE_LOCK = threading.Lock()


def get_store() -> AccountDataStore:
    global _STORE
    with _STORE_LOCK:
        if _STORE is None:
            _STORE = AccountDataStore()
        return _STORE


# ======================================================================
# 模块：xmanager/collector.py
# ======================================================================
"""只读采集器与面板回复 / 私信发送。"""


import hashlib
import re
import time
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import urlparse



# 最近8小时内容表现：与旧累计快照分表，发布时间和采集时间分开保存。
RECENT_HOURS = 8
RECENT_METRICS = ('views','likes','replies','reposts')
RECENT_SORT_LABELS = {'浏览量':'views','获赞':'likes','收到回复':'replies','转发':'reposts'}
RECENT_SCHEMA = '''
CREATE TABLE IF NOT EXISTS recent_activity(
 account TEXT NOT NULL,status_id TEXT NOT NULL,handle TEXT NOT NULL,name TEXT NOT NULL,
 published_ts REAL NOT NULL,observed_at REAL NOT NULL,kind TEXT NOT NULL,url TEXT NOT NULL,text TEXT NOT NULL,
 views INTEGER,likes INTEGER,replies INTEGER,reposts INTEGER,PRIMARY KEY(account,status_id));
CREATE INDEX IF NOT EXISTS idx_recent_pub ON recent_activity(published_ts,account);
CREATE TABLE IF NOT EXISTS recent_scans(
 account TEXT PRIMARY KEY,name TEXT NOT NULL,handle TEXT NOT NULL,started REAL NOT NULL,finished REAL NOT NULL,
 cutoff REAL NOT NULL,posts_state TEXT NOT NULL,replies_state TEXT NOT NULL,notes TEXT NOT NULL);
'''


def recent_post(row,handle,channel):
    if not isinstance(row,dict) or str(row.get('author','')).casefold()!=handle.casefold():return None
    pid=str(row.get('id',''))
    if not pid.isdigit():return None
    try:
        stamp=str(row.get('published',''))
        dt=__import__('datetime').datetime.fromisoformat(stamp.replace('Z','+00:00'))
        if dt.tzinfo is None:return None
        published=dt.timestamp()
        if not math.isfinite(published):return None
    except (ValueError,TypeError,OverflowError):return None
    kind='reply' if row.get('is_reply') else 'post' if channel=='posts' else 'unknown'
    result={'id':pid,'handle':handle,'published_ts':published,'kind':kind,
            'url':f'https://x.com/{handle}/status/{pid}','text':str(row.get('text') or '')[:2000],
            'pinned':bool(row.get('pinned')),'observed_at':time.time()}
    for key,label in (('views','views'),('likes','like'),('replies','reply'),('reposts','retweet')):
        value=row.get(label)
        result[key]=(parse_count(value) if key=='views' else count_from_label(value)) if value is not None else None
    return result


def merge_recent_post(previous,current):
    # 帖子页提供明确的原创/引用帖归属；回复页缺少上下文时不能把它降级成未知。
    if previous and previous['kind']=='post' and current['kind']=='unknown':current=dict(current,kind='post')
    return current


def recent_rank(rows,metric):
    if metric not in RECENT_METRICS:raise ValueError('未知排序指标')
    return sorted(rows,key=lambda r:(r.get(metric) is not None,r.get(metric) or 0,r.get('published_ts',0),str(r.get('account',''))),reverse=True)


def recent_metric_text(row,key):
    value=row.get(key)
    if value is None:return '未知'
    return ('≥' if row.get(key+'_missing',0) or row.get('partial',False) else '')+fmt_num(value)


RECENT_PROFILE_JS = r'''handle=>{
 const out=[],seen=new Set();
 const root=document.querySelector('[data-testid="primaryColumn"]')||document;
 for(const art of root.querySelectorAll('article[data-testid="tweet"]')){
  if(!art.getClientRects().length)continue;
  const link=[...art.querySelectorAll('a[href*="/status/"]')].find(a=>a.querySelector('time')&&a.closest('article')===art);
  if(!link)continue;
  const match=(link.getAttribute('href')||'').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)(?:[/?#]|$)/);
  if(!match||match[1].toLowerCase()!==handle.toLowerCase()||seen.has(match[2]))continue;
  seen.add(match[2]);
  const text=art.querySelector('[data-testid="tweetText"]');
  const read=selector=>{const e=[...art.querySelectorAll(selector)].find(n=>n.closest('article')===art);return e?(e.getAttribute('aria-label')||e.innerText||''):null;};
  const a=[...art.querySelectorAll('a[href*="/analytics"],a[data-testid="analytics"]')].find(n=>n.closest('article')===art);
  const header=text?(art.innerText||'').split(text.innerText)[0]:(art.innerText||'');
  const context=art.querySelector('[data-testid="replyingTo"]');
  const replying=!!context||/(?:^|\n)\s*(?:Replying to|回复|回覆|En respuesta a|Em resposta a|En réponse à|Antwort an)(?:\s|@|$)/i.test(header);
  out.push({id:match[2],author:match[1],published:link.querySelector('time').getAttribute('datetime'),text:text?text.innerText:'',
   like:read('[data-testid="like"],[data-testid="unlike"]'),reply:read('[data-testid="reply"]'),retweet:read('[data-testid="retweet"],[data-testid="unretweet"]'),
   views:a?((a.getAttribute('aria-label')&&/\d/.test(a.getAttribute('aria-label'))?a.getAttribute('aria-label'):a.innerText)||null):null,
   is_reply:replying,pinned:!!art.querySelector('[data-testid="socialContext"]')&&/Pinned|置顶|置頂|Fixado|Fijado/i.test(art.querySelector('[data-testid="socialContext"]').innerText||'')});
 }
 return out;
}'''


def collect_recent_activity(collector,handle=None):
    e,m,page=collector.e,collector.m,collector.e.page
    # 每次重新核对侧栏归属，不使用可能已切换身份的缓存用户名。
    handle=collector.own_handle()
    started=time.time();cutoff=started-RECENT_HOURS*3600
    records={};states={'posts':'未开始','replies':'未开始'};notes=[]
    previous=m.scene_deadline
    total_end=min(previous if previous is not None else math.inf,m.clock.elapsed()+95)
    m.scene_deadline=total_end
    def path():return urlparse(page.url).path.rstrip('/').casefold()
    def open_tab(channel):
        wanted='/'+handle+('/with_replies' if channel=='replies' else '')
        if channel=='posts':
            node=page.locator('[data-testid="AppTabBar_Profile_Link"]:visible').first
        else:
            # 只能点击已出现的个人主页“回复”原生入口；不存在时记录缺项。
            nodes=page.locator('a[href]:visible')
            raw=nodes.evaluate_all('(els)=>els.map(e=>e.getAttribute("href"))')
            href=next((h for h in raw if h and urlparse(h).path.rstrip('/').casefold()==wanted.casefold()),None)
            if href is None:
                node=page.get_by_role('tab',name=re.compile(r'^(Replies|回复|回覆|Respostas|Respuestas|Réponses|Antworten)$',re.I)).first
                if not node.count() or not node.is_visible():raise ContentUnavailable('个人主页没有可见的回复标签入口')
            else:node=page.locator('a[href='+json.dumps(href)+']:visible').first
        e.click(node)
        if not e.poll(lambda:path()==wanted.casefold(),6000):raise PageNotReady('个人主页分类点击后未确认')
        e.poll(lambda:page.locator(SELECTORS['tweet']).count() or page.locator('[data-testid="emptyState"]:visible').count(),6500)
    try:
        for channel in ('posts','replies'):
            try:
                e.phase('8小时统计：本人帖子' if channel=='posts' else '8小时统计：本人发出的回复')
                open_tab(channel)
                stop_at=min(total_end,m.clock.elapsed()+40)
                seen=set();older=set();stale=0;state='达到滚动上限，未确认边界'
                for _ in range(30):
                    e.gate()
                    if m.clock.elapsed()>=stop_at:state='达到时间上限，未确认边界';break
                    fresh=[]
                    for raw in page.evaluate(RECENT_PROFILE_JS,handle) or []:
                        row=recent_post(raw,handle,channel)
                        if row is None:
                            if isinstance(raw,dict) and str(raw.get('author','')).casefold()==handle.casefold():notes.append(channel+'有发布时间缺失的内容，未计入')
                            continue
                        if row['id'] not in seen:
                            if len(seen)>=300:break
                            fresh.append(row);seen.add(row['id'])
                        if row['published_ts']>=cutoff:
                            records[row['id']]=merge_recent_post(records.get(row['id']),row)
                    for row in fresh:
                        if row['published_ts']<cutoff and not row['pinned']:older.add(row['id'])
                    if len(older)>=2 and fresh and all(r['published_ts']<cutoff or r['pinned'] for r in fresh[-2:]):
                        state='已读到8小时之前';break
                    if page.locator('[data-testid="emptyState"]:visible').count() and not seen:
                        state='页面显示无内容';break
                    if len(seen)>=300:state='达到300条上限，未确认边界';break
                    stale=stale+1 if not fresh else 0
                    if stale>=3:state='连续无新增，未确认边界';break
                    e.scroll(650)
                states[channel]=state
            except (StopRequested,DurationReached,AccountStateError,CdpStateError):
                states[channel]='运行中断，未确认边界';raise
            except (ContentUnavailable,SceneBudgetExceeded,PlaywrightTimeoutError) as exc:
                states[channel]='未完成：'+short_error(exc)
                if isinstance(exc,SceneBudgetExceeded):break
            except Exception as exc:
                states[channel]='未完成：'+short_error(exc)
                logger.warning('8小时内容采集失败：%s',channel,exc_info=True)
    finally:
        m.scene_deadline=previous
        collector.store.record_recent_scan(m.browser_id,m.browser_name,handle,list(records.values()),started,cutoff,states,notes)
        m.stats['recent_8h']={'observed':len(records),'posts':states['posts'],'replies':states['replies']}
        m.log(f"8小时统计：读取{len(records)}条本人内容｜帖子：{states['posts']}｜回复：{states['replies']}；缺失指标保留未知")


# 明确点击按钮才创建定向互动任务；与普通阅读和只读统计分开。
RECENT_ACTION_NAMES={'like':'点赞','repost':'转发','comment':'评论'}
RECENT_ACTION_STATES={'reserved':'准备中','sending':'提交中','sent':'成功','already':'原已完成','unknown':'待核对','failed':'提交前失败','rejected':'平台拒绝'}
RECENT_SCHEMA += '''
CREATE TABLE IF NOT EXISTS recent_actions(
 actor TEXT NOT NULL,target TEXT NOT NULL,action TEXT NOT NULL,state TEXT NOT NULL,
 batch TEXT NOT NULL,url TEXT NOT NULL,updated REAL NOT NULL,error TEXT NOT NULL DEFAULT '',result_url TEXT NOT NULL DEFAULT '',
 PRIMARY KEY(actor,target,action));
CREATE TABLE IF NOT EXISTS recent_actor_identities(
 batch TEXT NOT NULL, actor TEXT NOT NULL, handle TEXT NOT NULL,
 PRIMARY KEY(batch,actor), UNIQUE(batch,handle));
CREATE TABLE IF NOT EXISTS recent_action_batches(batch TEXT PRIMARY KEY,created REAL NOT NULL);
CREATE TABLE IF NOT EXISTS recent_action_members(batch TEXT NOT NULL,actor TEXT NOT NULL,position INTEGER NOT NULL,PRIMARY KEY(batch,actor));
CREATE TABLE IF NOT EXISTS recent_action_goals(batch TEXT NOT NULL,target TEXT NOT NULL,action TEXT NOT NULL,goal INTEGER NOT NULL,url TEXT NOT NULL,PRIMARY KEY(batch,target,action));
'''


from xmanager_ledger import InteractionLedger


class RecentInteractionStore(InteractionLedger):
    def __init__(self, store=None):
        super().__init__(store or get_store(), CommentStore)

    def bind_identity(self, batch, actor, handle):
        try:
            super().bind_identity(batch, actor, handle)
        except ValueError as exc:
            self.store.log_event(actor, '', 'identity_conflict', str(exc))
            raise AccountStateError(Result.NEEDS_ACTION) from exc



def recent_best_targets(accounts,posts,metric,n):
    if not 1<=n<=100:raise ValueError('前N账号须在1～100之间')
    result=[];seen=set()
    for acc in recent_rank(accounts,metric):
        if acc.get(metric) is None:continue
        candidates=recent_rank([p for p in posts if p['account']==acc['account'] and p.get(metric) is not None],metric)
        if candidates:
            row=candidates[0];target=str(row.get('status_id') or row.get('id') or '')
            if target not in seen:result.append(row);seen.add(target)
        if len(result)>=n:break
    return result


def freeze_recent_targets(rows,now=None):
    now=time.time() if now is None else now
    result=[];seen=set()
    for row in rows:
        pid=str(row.get('status_id') or row.get('id') or '')
        handle=str(row.get('handle') or '')
        if not pid.isdigit() or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle):raise ValueError('目标缺少可核验的帖子ID或作者')
        if not now-8*3600<=float(row['published_ts'])<=now:continue
        if pid in seen:continue
        seen.add(pid);result.append((pid,handle,f'https://x.com/{handle}/status/{pid}'))
    if len(result)>100:raise ValueError('每批最多选择100条内容')
    return tuple(result)


def recent_execution_accounts(raw,mode,selected=(),actor=''):
    if mode not in ('全部环境参加','仅账号页勾选','单个执行账号'):raise ValueError('未知的执行范围')
    wanted=None if mode=='全部环境参加' else set(selected) if mode=='仅账号页勾选' else {actor} if actor else set()
    result=[];seen=set()
    for item in raw:
        aid=browser_id(item)
        if not aid or aid.startswith(AccountDataStore.DEMO_PREFIX) or aid in seen:continue
        if wanted is not None and aid not in wanted:continue
        seen.add(aid);result.append(item)
    if not result:raise ValueError('执行范围内没有账号，请刷新比特环境或勾选账号')
    if wanted is not None and wanted-seen:raise ValueError('部分执行账号已不在环境列表，请刷新后重新选择')
    return result


class RecentInteractionRunner:
    """按帖子共享目标数量；兼容旧配额任务，逐目标原生UI操作，提交只点击一次。"""
    def __init__(self,e,store=None):
        self.e,self.m,self.page=e,e.m,e.page;self.ledger=RecentInteractionStore(store)
        self.batch=self.m.cfg.recent_action_batch
        self.counts=self.m.stats.setdefault('recent_action_attempts',dict(like=0,repost=0,comment=0))
        self.results=self.m.stats.setdefault('recent_action_summary',dict(sent=0,already=0,skipped=0,unknown=0,failed=0))
    def wait(self,fn,ms=5000):return self.e.poll(fn,ms)
    def health(self):self.e.gate();self.e.check_health()
    def has_draft(self):
        return self.page.locator('[contenteditable="true"]:visible, textarea:visible').evaluate_all("els=>els.some(e=>(e.innerText||e.value||'').trim())")
    def _trace_ui(self,label,exc):
        row=dict(step=label,url=self.page.url,error=short_error(exc))
        trace=self.m.stats.setdefault('recent_ui_failures',[]);trace.append(row);del trace[:-30]
        self.m.log(f'榜单原生UI｜{label}｜{short_error(exc)}｜{self.page.url}')
    def clear_transient(self):
        self.e.gate()
        if self.has_draft():raise ContentUnavailable('当前页有未提交内容，保留草稿，不关闭弹窗或离页')
        menus=self.page.locator('[role="menu"]:visible, [data-testid="Dropdown"]:visible')
        if menus.count():
            self.page.keyboard.press('Escape')
            if not self.wait(lambda:not menus.count(),3000):raise PageNotReady('原生菜单未关闭，暂停下一步导航')
    def native_click(self,resolve,label,ready=None,ms=10000):
        # Navigation/focus/menu entry only. Final submissions use submit_click exactly once.
        for attempt in range(2):
            self.e.gate();self.m.workflow_phase=label
            if ready and ready():return
            try:
                def visible():
                    node=resolve()
                    return node if node is not None and node.count() and node.is_visible() else None
                node=visible() or self.wait(visible,ms)
                if node is None:raise PageNotReady(label+'：入口未就绪')
                node.click(trial=True,timeout=self.e.timeout(ms))
                self.e.gate()
                node=resolve()
                node.click(timeout=self.e.timeout(ms))
                self.e.gate()
                if ready and not self.wait(ready,ms):raise PageNotReady(label+'：点击后未确认页面状态')
                return
            except (StopRequested,DurationReached,SceneBudgetExceeded,AccountStateError,CdpStateError):raise
            except (PlaywrightTimeoutError,ContentUnavailable) as exc:
                if ready and ready():return
                self._trace_ui(label,exc)
                if attempt:raise
                self.m.log(f'榜单原生UI｜{label}｜重新读取当前页面入口，最后重试一次')
        raise PageNotReady(label+'：未完成')
    def recover_source(self):
        if self.m.stats.get('recent_native_recovery_used'):return False
        self.m.stats['recent_native_recovery_used']=True
        self.clear_transient()
        home=lambda:self.page.locator('[data-testid="AppTabBar_Home_Link"]:visible, a[href="/home"][role="link"]:visible').first
        if not home().count():return False
        def readable():
            return urlparse(self.page.url).path.rstrip('/')=='/home' and self.page.locator('article[data-testid="tweet"]:visible').count()>0
        self.m.log('连续目标入口异常，在原窗口点击首页入口恢复一次；不关窗重开')
        self.native_click(home,'原窗口恢复信息流',ready=readable,ms=12000)
        return True
    def submit_click(self,button):
        # Persisted sending state is set by the caller. No retries or simulated mouse path.
        self.e.gate();button.click(timeout=self.e.timeout(10000));self.e.gate()
    def identity_probe(self):
        self.e.gate();self.e.check_health(ignore_page_error=True)
        links=self.page.locator('[data-testid="AppTabBar_Profile_Link"]:visible, nav a[aria-label="Profile"]:visible, nav a[aria-label="个人资料"]:visible, nav a[aria-label="個人資料"]:visible, nav a[aria-label="Perfil"]:visible')
        for i in range(min(links.count(),5)):
            href=links.nth(i).get_attribute('href',timeout=self.e.timeout(1500)) or ''
            if urlparse(href).scheme and not is_x_url(href):continue
            found=re.fullmatch(r'/([A-Za-z0-9_]{1,15})/?',urlparse(href).path)
            if found and found.group(1).lower() not in ('home','explore','search','settings','messages','notifications','i'):return found.group(1)
        # Only the current-account switcher button is trusted; never infer identity from tweet authors or saved metrics.
        current=self.page.locator('[data-testid="SideNav_AccountSwitcher_Button"]:visible').first
        if current.count():
            handles=set(re.findall(r'(?<![A-Za-z0-9_])@([A-Za-z0-9_]{1,15})(?![A-Za-z0-9_])',current.inner_text(timeout=self.e.timeout(1500))))
            if len(handles)==1:return handles.pop()
        return None
    def resolve_identity(self):
        self.m.workflow_phase='等待当前账号身份入口'
        handle=self.identity_probe() or self.wait(self.identity_probe,18000)
        if not handle:
            self.clear_transient()
            drawer=lambda:self.page.locator('button[aria-label="Account menu"]:visible, button[aria-label="账号菜单"]:visible, button[aria-label="帳戶選單"]:visible').first
            if drawer().count():self.native_click(drawer,'展开当前账号侧栏',ready=self.identity_probe,ms=6000)
            handle=self.identity_probe() or self.wait(self.identity_probe,12000)
        if not handle:raise ContentUnavailable('有限等待后仍无法读取当前账号身份入口；没有使用缓存用户名代替核验')
        expected=dict(self.m.cfg.recent_actor_handles).get(self.m.browser_id,self.m.cfg.recent_actor_handle)
        if expected and handle.casefold()!=expected.casefold():
            self.m.log(f'执行身份不一致：当前@{handle}，记录@{expected}，仅暂停当前账号')
            raise AccountStateError(Result.NEEDS_ACTION)
        self.ledger.bind_identity(self.batch, self.m.browser_id, handle)
        self.m.handle=handle
        return handle
    def root(self,target,handle):
        # Narrow by the actual timestamp permalink before indexing: unrelated feed inserts cannot shift the locator.
        if not target.isdigit():return None
        articles=self.page.locator('xpath=//article[@data-testid="tweet"][(.//a[.//time])[1][contains(@href,"/status/'+target+'")]]')
        for i in range(min(articles.count(),20)):
            art=articles.nth(i)
            if not art.is_visible():continue
            key=art.evaluate("el=>{const a=[...el.querySelectorAll('a[href*=\"/status/\"]')].find(a=>a.querySelector('time'));return a?a.getAttribute('href'):'';}")
            if key and urlparse(key).scheme and not is_x_url(key):continue
            if re.fullmatch('/'+re.escape(handle)+r'/status/'+re.escape(target)+r'/?',urlparse(key or '').path,re.I):
                # Bind the first timestamp permalink itself, so an inserted quote cannot retarget an indexed article.
                literal=("'"+key+"'") if "'" not in key else ('"'+key+'"') if '"' not in key else None
                if literal is not None:return self.page.locator('xpath=//article[@data-testid="tweet"][(.//a[.//time])[1][@href='+literal+']]').first
        return None
    def target_link(self,target):
        # Timestamp links open the post; image/video/quote links must not take precedence.
        selectors=('a[href]:has(time):visible','a[href]:visible')
        for selector in selectors:
            rows=self.page.locator(selector).evaluate_all('(els)=>els.map(e=>e.getAttribute("href"))')
            for raw in rows:
                if not raw or (urlparse(raw).scheme and not is_x_url(raw)):continue
                if re.fullmatch(r'/[A-Za-z0-9_]+/status/'+re.escape(target)+r'/?',urlparse(raw).path):
                    return self.page.locator('a[href='+json.dumps(raw)+']:visible').first
        return None
    def open_target(self,target,handle):
        self.health();self.clear_transient()
        def arrived():
            u=canonical_status_url(self.page.url or '')
            return u and u.rsplit('/',1)[-1]==target and self.root(target,handle) is not None
        if arrived():return
        if self.target_link(target) is not None:
            self.native_click(lambda:self.target_link(target),'打开目标帖子 '+target,ready=arrived,ms=10000)
            return
        box=lambda:self.page.locator('[data-testid="SearchBox_Search_Input"]:visible').first
        if not box().count():
            explore=lambda:self.page.locator('[data-testid="AppTabBar_Explore_Link"]:visible, a[href="/explore"]:visible').first
            self.native_click(explore,'进入原生探索搜索',ready=lambda:box().count() and box().is_visible(),ms=12000)
        term='from:'+handle
        def search_ready():return urlparse(self.page.url).path=='/search' and dict(parse_qsl(urlparse(self.page.url).query)).get('q')==term
        if not search_ready():
            self.native_click(box,'聚焦原生搜索框',ms=8000)
            box().fill(term,timeout=self.e.timeout(8000))
            if box().input_value(timeout=self.e.timeout(2000))!=term:raise ContentUnavailable('搜索词未确认，不提交')
            box().press('Enter',timeout=self.e.timeout(8000))
            if not self.wait(search_ready,12000):raise PageNotReady('未确认作者搜索结果，等待结束')
        self.clear_transient()
        tab=lambda:self.page.get_by_role('tab',name=re.compile(r'^(Latest|最新|Recentes|Más reciente|Mais recentes)$',re.I)).first
        def latest():return dict(parse_qsl(urlparse(self.page.url).query)).get('f')=='live' or (tab().count() and tab().get_attribute('aria-selected')=='true')
        if not latest():self.native_click(tab,'切换最新搜索结果',ready=latest,ms=10000)
        # Scroll only the current native results; wait for the target after each movement.
        for _ in range(16):
            self.health()
            if self.target_link(target) is not None:
                self.native_click(lambda:self.target_link(target),'打开搜索中的目标 '+target,ready=arrived,ms=10000)
                return
            self.page.mouse.wheel(0,600)
            self.wait(lambda:self.target_link(target),1200)
        raise ContentUnavailable('当前原生搜索结果中未找到该帖；不跳转地址、不刷新寻找')
    def verify_identity(self):
        current = self.identity_probe()
        if not current or current.casefold() != self.m.handle.casefold():
            self.m.log('提交前身份复核失败，停止当前执行账号')
            raise AccountStateError(Result.NEEDS_ACTION)

    def arm(self,target,action):
        self.health()
        self.verify_identity()
        self.ledger.update(self.m.browser_id,target,action,'sending')
        self.counts[action]+=1
        if action=='like':
            self.m.like_attempts=getattr(self.m,'like_attempts',0)+1
            self.m.stats['like_attempts']=self.m.like_attempts
        elif action=='repost':self.m.stats['repost_attempts']=self.counts[action]
        self.m.stats['recent_action_last_armed']=self.m.clock.elapsed()
    def do_toggle(self,target,handle,action):
        positive='unlike' if action=='like' else 'unretweet'
        def confirmed():
            art=self.root(target,handle)
            return art is not None and art.locator('[data-testid="'+positive+'"]:visible').count()>0
        def entry():
            art=self.root(target,handle)
            return art.locator('[data-testid="like"]:visible' if action=='like' else '[data-testid="retweet"]:visible').first if art is not None else None
        if confirmed():return 'already',''
        if self.root(target,handle) is None:raise ContentUnavailable('目标正文已离开页面，未执行互动')
        if action=='repost':
            menu=lambda:self.page.locator('[data-testid="retweetConfirm"]:visible').first
            self.native_click(entry,'打开转发菜单 '+target,ready=lambda:menu().count() and menu().is_visible(),ms=8000)
            resolve=menu
        else:resolve=entry
        # Retry only actionability checks; the actual final click is never retried.
        for attempt in range(2):
            if confirmed():return 'already',''
            button=resolve()
            if button is None:raise ContentUnavailable('目标正文或互动按钮已消失')
            try:
                button.wait_for(state='visible',timeout=self.e.timeout(10000))
                button.click(trial=True,timeout=self.e.timeout(10000))
                break
            except PlaywrightTimeoutError as exc:
                self._trace_ui('提交前检查 '+RECENT_ACTION_NAMES[action],exc)
                if attempt:raise
        self.arm(target,action)
        try:self.submit_click(resolve())
        except (StopRequested,DurationReached,AccountStateError,CdpStateError):raise
        except Exception as exc:self._trace_ui('提交结果核对 '+RECENT_ACTION_NAMES[action],exc)
        return ('sent','') if self.wait(confirmed,12000) else ('unknown','提交后未确认原生按钮状态，保留名额等待核对，禁止自动重试')
    def do_comment(self,target):
        m=self.m;p=CommentPublisher(self.e);p.page=self.page;p.deadline=m.scene_deadline;p.stage='8小时榜单定向评论'
        item,reason=p.store.reserve_comment(m.ctl.comment_rows,m.browser_id,target,m.cfg.comment_order)
        if item is None:return 'skip',reason
        _,text=item;m.stats['comment_last_armed']=False;before_attempts=m.comment_attempts
        try:
            editor,p.surface=p.open_composer(target)
            button=p.fill_composer(editor,text)
            # 发布器落盘/计数/监听匹配目标的创建回复响应；不调用随机候选分派。
            self.verify_identity()
            self.ledger.update(m.browser_id,target,'comment','sending')
            tid=p.submit_once(button,text,target)
            if tid:
                url=f'https://x.com/i/status/{tid}'
                p.store.update(m.browser_id,target,m.browser_id,'sent',url=url)
                m.stats['comments_sent']=m.stats.get('comments_sent',0)+1
                return 'sent',url
            p.store.update(m.browser_id,target,m.browser_id,'unknown',error='定向评论提交后未确认')
            m.stats['comments_unknown']=m.stats.get('comments_unknown',0)+1
            return 'unknown','评论提交后未确认成功，保留全局去重'
        except BaseException as exc:
            armed=m.stats.get('comment_last_armed',False)
            if armed:
                state='rejected' if isinstance(exc,CommentRejected) else 'unknown'
                p.store.update(m.browser_id,target,m.browser_id,state,error=short_error(exc))
                self.ledger.update(m.browser_id,target,'comment',state,short_error(exc))
                if state=='rejected':m.comment_halted=True
            else:
                p.store.release_before_submit(m.browser_id,target)
                self.ledger.update(m.browser_id,target,'comment','failed',short_error(exc))
            raise
        finally:
            attempts=max(0,m.comment_attempts-before_attempts)
            if attempts:
                self.counts['comment']+=attempts;m.stats['recent_action_last_armed']=m.clock.elapsed()
    def perform(self,target,handle,url,action):
        m=self.m
        if action=='comment' and m.comment_halted:return
        # The account may have been switched manually after the initial probe.
        self.verify_identity()
        limits=dict(m.cfg.recent_action_limits)
        per_post=m.cfg.recent_action_per_post
        if not limits.get(action,0):return
        if per_post:
            if not self.ledger.pending(self.batch,m.browser_id,target,action):return
        elif self.counts[action]>=limits[action]:return
        # 全局间隔跨批次保留；本批动作间隔使用不含暂停的执行计时。
        wait=self.ledger.cooldown(m.browser_id,m.cfg.recent_action_interval)
        if m.stats.get('recent_action_last_armed') is not None:
            wait=max(wait,m.cfg.recent_action_interval-(m.clock.elapsed()-m.stats['recent_action_last_armed']))
        if action=='comment':wait=max(wait,CommentStore().cooldown(m.browser_id,m.cfg.comment_interval))
        if wait:m.workflow_phase=f'等待{RECENT_ACTION_NAMES[action]}间隔 {wait:.0f}秒';m.sleep(wait)
        m.scene_deadline=m.clock.elapsed()+75
        ok,reason=self.ledger.reserve(m.browser_id,target,action,self.batch,url,per_post=per_post)
        if not ok:
            self.results['skipped']+=1;m.scene_deadline=None;m.log(f'榜单{RECENT_ACTION_NAMES[action]}跳过 {target}：{reason}');return
        armed_before=self.counts[action]
        try:
            self.health()
            state,reason=self.do_comment(target) if action=='comment' else self.do_toggle(target,handle,action)
            if state=='skip':
                self.ledger.update(m.browser_id,target,action,'failed',reason);self.results['skipped']+=1
            else:
                self.ledger.update(m.browser_id,target,action,state,'' if state=='sent' else reason,reason if action=='comment' and state=='sent' else '')
                self.results[state if state in self.results else 'failed']+=1
                if state=='sent' and action in ('like','repost'):
                    key='likes' if action=='like' else 'reposts_sent'
                    m.stats[key]=m.stats.get(key,0)+1
            m.log(f'榜单{RECENT_ACTION_NAMES[action]} {target}：{RECENT_ACTION_STATES.get(state,state)} {reason}')
        except BaseException as exc:
            armed=self.counts[action]>armed_before
            state='rejected' if isinstance(exc,CommentRejected) and armed else 'unknown' if armed else 'failed'
            self.ledger.update(m.browser_id,target,action,state,short_error(exc))
            self.results['unknown' if state=='unknown' else 'failed']+=1
            if isinstance(exc,(StopRequested,DurationReached,AccountStateError,CdpStateError,KeyboardInterrupt,SystemExit)):raise
            m.log(f'榜单{RECENT_ACTION_NAMES[action]} {target}：{RECENT_ACTION_STATES[state]} {short_error(exc)}')
        finally:
            m.scene_deadline=None
            try:
                if action=='repost':self.clear_transient()
            except (StopRequested,DurationReached,AccountStateError,CdpStateError):raise
            except Exception as exc:m.log('转发菜单恢复未完成：'+short_error(exc))
            if hasattr(m,'persist_workflow_plan'):m.persist_workflow_plan(force=True)
    def run(self):
        m=self.m;m.workflow_name='8小时榜单定向互动'
        if hasattr(m,'set_stage'):m.set_stage('workflows')
        try:handle=self.resolve_identity()
        except ContentUnavailable as exc:
            m.stats['recent_identity_failure']=short_error(exc)
            m.log('当前账号身份入口未就绪，结束本账号定向互动，其他账号继续：'+short_error(exc))
            return Result.PARTIAL
        m.log(f'榜单互动执行账号：{m.browser_name} / @{handle}；不会切换为目标作者账号。')
        targets=m.cfg.recent_action_targets
        if m.cfg.recent_action_per_post:targets=self.ledger.target_order(self.batch,m.browser_id,targets)
        for target,author,url in targets:
            m.checkpoint()
            if handle.casefold() == author.casefold():
                m.log('跳过本人内容：'+target)
                continue
            if m.cfg.recent_action_per_post:
                if not any(n and not (k=='comment' and m.comment_halted) and self.ledger.pending(self.batch,m.browser_id,target,k) for k,n in m.cfg.recent_action_limits):continue
            elif all(self.counts[k]>=n or (k=='comment' and m.comment_halted) for k,n in m.cfg.recent_action_limits):break
            if target in m.stats.setdefault('recent_action_visited',[]):continue
            m.scene_deadline=m.clock.elapsed()+95
            try:self.open_target(target,author)
            except (StopRequested,DurationReached,AccountStateError,CdpStateError):raise
            except Exception as exc:
                reason='目标未打开：'+short_error(exc)
                m.log(f'榜单目标未打开 {target}：{short_error(exc)}');self.results['failed']+=1
                m.stats['recent_navigation_failures']=m.stats.get('recent_navigation_failures',0)+1
                for action,limit in m.cfg.recent_action_limits:
                    if not limit or (not m.cfg.recent_action_per_post and self.counts[action]>=limit):continue
                    ok,_=self.ledger.reserve(m.browser_id,target,action,self.batch,url,per_post=m.cfg.recent_action_per_post)
                    if ok:self.ledger.update(m.browser_id,target,action,'failed',reason)
                if m.cfg.recent_action_per_post and m.stats['recent_navigation_failures']>=2:
                    try:
                        m.scene_deadline=m.clock.elapsed()+35
                        self.recover_source()
                    except (StopRequested,DurationReached,AccountStateError,CdpStateError):raise
                    except Exception as recovery_exc:m.log('原窗口恢复未完成：'+short_error(recovery_exc))
                if m.cfg.recent_action_per_post and m.stats['recent_navigation_failures']>=3:
                    m.log('当前账号连续3条目标无法打开，仅结束本账号；其他账号继续领取缺额')
                    break
                continue
            finally:m.scene_deadline=None
            m.stats['recent_navigation_failures']=0
            for action in ('like','repost','comment'):
                m.workflow_phase=f'{RECENT_ACTION_NAMES[action]} / {target}'
                self.perform(target,author,url,action)
            m.stats['recent_action_visited'].append(target)
        m.log('榜单互动汇总：'+json.dumps(self.results,ensure_ascii=False))
        if m.cfg.recent_action_per_post:
            for row in self.ledger.progress(self.batch):
                if row['goal']:
                    m.log(f"逐帖进度 {row['target']} {RECENT_ACTION_NAMES[row['action']]}：已确认{row['done']}/{row['goal']}，待核对{row['unknown']}，处理中{row['reserved']}，缺额{row['missing']}")
        return Result.PARTIAL if self.results['unknown'] or self.results['failed'] else Result.PLAN_DONE



class AccountCollector:
    """只读采集：红点徽标、粉丝、近期帖子的获赞/评论、评论与提及、私信列表。
    不点赞、不关注、不发送；不打开私信会话，所以不会把私信标成已读。
    注意：X 打开“通知”页后红点会清零（本程序先读红点再进通知页）。"""

    BADGE_JS = (
        "els=>els.flatMap(e=>[e.getAttribute('aria-label')||'',"
        "...[...e.querySelectorAll('[aria-label]')].map(x=>x.getAttribute('aria-label')||'')])"
    )
    COUNTS_JS = (
        "els=>els.filter(e=>e.getClientRects().length>0)"
        ".map(e=>[e.getAttribute('href')||'',(e.innerText||'').trim()])"
    )
    PROFILE_JS = r'''(handle) => {
        const want = ('/' + handle + '/status/').toLowerCase();
        const seen = new Set(), out = [];
        for (const art of document.querySelectorAll('article[data-testid="tweet"]')) {
            if (!art.getClientRects().length) continue;
            let id = null;
            for (const a of art.querySelectorAll('a[href*="/status/"]')) {
                const href = a.getAttribute('href') || '';
                if (!a.querySelector('time') || !href.toLowerCase().startsWith(want)) continue;
                const m = href.match(/\/status\/(\d+)/);
                if (m) { id = m[1]; break; }
            }
            if (!id || seen.has(id)) continue;
            seen.add(id);
            const label = sel => { const e = art.querySelector(sel); return e ? (e.getAttribute('aria-label') || '') : null; };
            const pick = (a, b) => { const x = label(a); return x !== null ? x : label(b); };
            const analytics = art.querySelector('a[href$="/analytics"]');
            const txt = art.querySelector('[data-testid="tweetText"]');
            out.push({
                id: id, text: txt ? txt.innerText : '',
                reply: label('[data-testid="reply"]'),
                like: pick('[data-testid="like"]', '[data-testid="unlike"]'),
                retweet: pick('[data-testid="retweet"]', '[data-testid="unretweet"]'),
                views_label: analytics ? (analytics.getAttribute('aria-label') || '') : '',
                views_text: analytics ? (analytics.innerText || '') : ''
            });
        }
        return out;
    }'''
    MENTIONS_JS = r'''(handle) => {
        const me = (handle || '').toLowerCase(), seen = new Set(), out = [];
        for (const art of document.querySelectorAll('article[data-testid="tweet"]')) {
            if (!art.getClientRects().length) continue;
            let id = null, author = '';
            for (const a of art.querySelectorAll('a[href*="/status/"]')) {
                if (!a.querySelector('time')) continue;
                const m = (a.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
                if (m) { author = m[1]; id = m[2]; break; }
            }
            if (!id || seen.has(id) || author.toLowerCase() === me) continue;
            seen.add(id);
            const txt = art.querySelector('[data-testid="tweetText"]');
            out.push({id: id, author: author, text: txt ? txt.innerText : ''});
        }
        return out;
    }'''
    DM_JS = r'''() => {
        const unreadRe = /unread|未读|未讀|não lid|sin leer|non lu|ungelesen|непрочит|未読|읽지/i;
        const rows = [...document.querySelectorAll('[data-testid="conversation"], [data-testid="conversationEntry"]')]
            .filter(e => e.getClientRects().length > 0);
        return rows.slice(0, 30).map(r => {
            const labels = [r.getAttribute('aria-label') || '', ...[...r.querySelectorAll('[aria-label]')].map(x => x.getAttribute('aria-label') || '')];
            const a = r.closest('a') || r.querySelector('a[href^="/messages/"]');
            return {
                lines: (r.innerText || '').split('\n').map(s => s.trim()).filter(Boolean).slice(0, 6),
                unread: labels.some(l => unreadRe.test(l)) || !!r.querySelector('[data-testid*="nread"]'),
                href: a ? (a.getAttribute('href') || '') : ''
            };
        });
    }'''

    def __init__(self, executor):
        self.e, self.m = executor, executor.m
        self.store = get_store()
        self.posts: List[Dict[str, Any]] = []

    # ---- 总入口 ----
    def run(self, stage: str = "start") -> None:
        e, m, cfg = self.e, self.m, self.m.cfg
        original = m.scene_deadline
        m.scene_deadline = m.clock.elapsed() + 110
        m.workflow_name = "数据采集"
        e.current_key = None
        info: Dict[str, Any] = {
            k: None for k in ("followers", "following", "dm_unread", "dm_convs", "notif_unread")
        }
        inbox: List[Dict[str, Any]] = []
        errors: List[str] = []
        try:
            e.phase("采集：检查首页")
            e.ensure_home()
            e.primary()
            self.step(errors, "红点", lambda: self.read_badges(info))
            self.step(errors, "主页数据", lambda: self.read_profile(info))
            if cfg.stats_mentions:
                self.step(errors, "评论与提及", lambda: inbox.extend(self.read_mentions()))
            if cfg.stats_dm:
                self.step(errors, "私信列表", lambda: self.read_dm_list(info, inbox))
        finally:
            m.scene_deadline = original
            self.save(info, inbox, errors, stage)

    def step(self, errors: List[str], label: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except FATAL_ERRORS:
            raise
        except SceneBudgetExceeded:
            errors.append(f"{label}：时间用尽")
        except ContentUnavailable as exc:
            errors.append(f"{label}：{exc}")
        except PlaywrightTimeoutError as exc:
            errors.append(f"{label}：超时 {short_error(exc)}")
        except Exception as exc:
            logger.warning("采集步骤失败：%s", label, exc_info=True)
            errors.append(f"{label}：{short_error(exc)}")

    def save(self, info, inbox, errors, stage) -> None:
        m = self.m
        try:
            got = any(v is not None for v in info.values()) or bool(self.posts)
            if got:
                self.store.record_collection(
                    m.browser_id, m.browser_name, m.handle, self.posts, info, source=stage
                )
            new = self.store.upsert_inbox(m.browser_id, inbox) if inbox else 0
            m.stats["collections"] = m.stats.get("collections", 0) + 1
            parts = []
            if info["followers"] is not None:
                parts.append(f"粉丝 {info['followers']}")
            if self.posts:
                parts.append(
                    f"读取 {len(self.posts)} 帖 获赞 {sum(p['likes'] for p in self.posts)} 评论 {sum(p['replies'] for p in self.posts)}"
                )
            if info["dm_unread"] is not None:
                parts.append(f"私信未读 {info['dm_unread']}")
            if info["notif_unread"] is not None:
                parts.append(f"通知未读 {info['notif_unread']}")
            if inbox:
                parts.append(f"收件箱 {len(inbox)} 条（新增 {new}）")
            summary = " · ".join(parts) or "没有读到有效数据"
            if errors:
                summary += "｜未完成：" + "；".join(errors)
            m.log("数据采集完成：" + summary)
            self.store.log_event(m.browser_id, m.browser_name, "collect", summary)
        except Exception:
            logger.warning("保存采集结果失败", exc_info=True)

    # ---- 具体读取 ----
    def read_badges(self, info: Dict[str, Any]) -> None:
        page = self.e.page
        for key, selector in (
            ("dm_unread", '[data-testid="AppTabBar_DirectMessage_Link"]'),
            ("notif_unread", '[data-testid="AppTabBar_Notifications_Link"]'),
        ):
            link = page.locator(selector)
            if link.count():
                info[key] = unread_total(link.evaluate_all(self.BADGE_JS))

    def own_handle(self) -> str:
        e = self.e
        link = e.page.locator('[data-testid="AppTabBar_Profile_Link"]').first
        href = e.poll(
            lambda: link.get_attribute("href", timeout=e.timeout(1500)) if link.count() else None, 6000
        )
        found = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/?", href or "")
        if not found:
            raise ContentUnavailable("无法确认当前账号用户名（侧栏的个人主页入口没有出现）")
        self.m.handle = found.group(1)
        return self.m.handle

    def profile_counts(self) -> Optional[Dict[str, int]]:
        rows = self.e.page.locator(
            'a[href$="/followers"], a[href$="/verified_followers"], a[href$="/following"]'
        ).evaluate_all(self.COUNTS_JS)
        found: Dict[str, int] = {}
        for href, text in rows:
            number = parse_count(text)
            if number is None:
                continue
            found.setdefault("following" if href.endswith("/following") else "followers", number)
        return found or None

    def read_profile(self, info: Dict[str, Any]) -> None:
        e, m, page = self.e, self.m, self.e.page
        handle = m.handle or self.own_handle()
        e.phase("采集：打开自己的主页")
        e.navigator.goto("https://x.com/" + handle)
        if not e.poll(lambda: page.locator('[data-testid="primaryColumn"]').count(), 8000):
            raise PageNotReady("自己的主页尚未加载")
        counts = e.poll(self.profile_counts, 5000)
        if counts:
            info["followers"] = counts.get("followers", info.get("followers"))
            info["following"] = counts.get("following", info.get("following"))
        e.phase("采集：读取近期帖子的获赞与评论")
        self.posts = self.collect_posts(handle, m.cfg.stats_posts)
        if m.cfg.stats_recent_enabled:collect_recent_activity(self,handle)

    def collect_posts(self, handle: str, limit: int) -> List[Dict[str, Any]]:
        e, page = self.e, self.e.page
        e.poll(
            lambda: (
                page.locator(SELECTORS["tweet"]).count() or page.locator('[data-testid="emptyState"]').count()
            ),
            8000,
        )
        posts: Dict[str, Dict[str, Any]] = {}
        stale = 0
        for _ in range(8):
            e.gate()
            fresh = 0
            for row in build_post_metrics(page.evaluate(self.PROFILE_JS, handle)):
                fresh += 0 if row["id"] in posts else 1
                posts[row["id"]] = row
            if len(posts) >= limit:
                break
            stale = 0 if fresh else stale + 1
            if stale >= 2:
                break
            e.scroll(e.plan.rng.randint(520, 900))
        return list(posts.values())[:limit]

    def read_mentions(self) -> List[Dict[str, Any]]:
        e, page = self.e, self.e.page
        handle = self.m.handle or self.own_handle()
        e.phase("采集：评论与提及")
        e.navigator.goto("https://x.com/notifications/mentions")
        if not e.poll(lambda: page.locator(SELECTORS["tweet"] + ":visible").count(), 7000):
            return []  # 没有提及也是合法结果
        found: Dict[str, Dict[str, Any]] = {}
        for _ in range(3):
            for row in page.evaluate(self.MENTIONS_JS, handle) or []:
                pid, author = str(row.get("id") or ""), str(row.get("author") or "")
                if pid.isdigit() and author and pid not in found:
                    found[pid] = {
                        "kind": "mention",
                        "ext_id": pid,
                        "author": "@" + author,
                        "text": re.sub(r"\s+", " ", str(row.get("text") or "")).strip()[:500],
                        "url": f"https://x.com/{author}/status/{pid}",
                    }
            if len(found) >= 30:
                break
            e.scroll(e.plan.rng.randint(450, 800))
        return list(found.values())

    def read_dm_list(self, info: Dict[str, Any], inbox: List[Dict[str, Any]]) -> None:
        e, page = self.e, self.e.page
        e.phase("采集：私信列表（只读，不打开会话）")
        e.navigator.goto("https://x.com/messages")
        e.primary()
        if page.locator('input[type="password"]:visible').count():
            raise ContentUnavailable("私信要求输入 PIN / 验证，已跳过（请手动处理）")
        rows = e.poll(lambda: page.evaluate(self.DM_JS) or None, 7000)
        if not rows:
            raise ContentUnavailable("没有识别到私信会话列表（可能没有会话，或页面结构有变化）")
        flagged = 0
        for row in rows:
            lines = [str(x) for x in row.get("lines") or []]
            if not lines:
                continue
            unread = bool(row.get("unread"))
            flagged += 1 if unread else 0
            href = row.get("href") or ""
            inbox.append(
                {
                    "kind": "dm",
                    "ext_id": "conv:" + hashlib.sha1(lines[0].casefold().encode("utf-8")).hexdigest()[:14],
                    "author": lines[0][:60],
                    "text": (lines[-1] if len(lines) > 1 else "")[:200],
                    "url": ("https://x.com" + href) if re.fullmatch(r"/messages/[\w-]+", href) else "",
                    "state": "new" if unread else "handled",
                }
            )
        info["dm_convs"] = len(rows)
        info["dm_unread"] = max(info.get("dm_unread") or 0, flagged)


class PanelReplyPublisher(CommentPublisher):
    """人工写好的面板回复与自动评论共用目标、文本唯一键；提交只点击一次。"""

    def mark_sending(self, target):
        self.store.update(self._panel_scope, target, self._panel_scope, 'sending')

    def count_attempt(self):
        self.m.stats["panel_attempts"] = self.m.stats.get("panel_attempts", 0) + 1

    def send(self, target: str, target_url: str, text: str, outbox_id: int) -> Optional[str]:
        m = self.m
        scope = self.store.panel_scope(m.browser_id, outbox_id)
        item, reason = self.store.reserve_comment([(f"outbox:{outbox_id}", text)], scope, target, "ordered")
        if item is None:
            raise GlobalCommentConflict("全局去重阻止此回复，未提交：" + reason)
        self._panel_scope = scope
        original, started = m.scene_deadline, m.clock.elapsed()
        m.scene_deadline = None
        self.deadline = started + min(70, max(25, m.remaining()))
        m.stats["comment_last_armed"] = False
        self.page = self.source
        try:
            self.stage = "打开目标推文"
            self.page.goto(target_url, wait_until="domcontentloaded", timeout=self.timeout(15000))
            self.gate()
            editor, self.surface = self.open_composer(target)
            button = self.fill_composer(editor, text)
            tid = self.submit_once(button, text, target)
            self.store.update(
                scope,
                target,
                scope,
                'sent' if tid else 'unknown',
                url=f"https://x.com/i/status/{tid}" if tid else '',
                error='' if tid else '面板提交后未得到成功确认',
            )
            return tid
        except BaseException as exc:
            try:
                if isinstance(exc, CommentRejected):
                    self.store.update(scope, target, scope, 'rejected', error=str(exc))
                elif m.stats.get('comment_last_armed', False):
                    self.store.update(scope, target, scope, 'unknown', error=short_error(exc))
                else:
                    self.store.release_before_submit(scope, target)
            except Exception:
                logger.exception("面板回复全局状态保存失败，保留占用记录防止重复")
            if not isinstance(exc, FATAL_ERRORS + (CommentRejected, KeyboardInterrupt, SystemExit)):
                self.diagnostic(target_url, exc)
            raise
        finally:
            self.deadline = None
            self.page = None
            m.scene_deadline = original + (m.clock.elapsed() - started) if original is not None else None


class PanelDMSender:
    """给已有私信会话回一条人工写好的消息：找到会话、核对对象、发送一次、在会话里确认。"""

    ROWS = '[data-testid="conversation"]:visible, [data-testid="conversationEntry"]:visible'
    COMPOSER = '[data-testid="dmComposerTextInput"]:visible'
    SEND = '[data-testid="dmComposerSendButton"]:visible'
    ENTRY = '[data-testid="messageEntry"]:visible'

    def __init__(self, executor):
        self.e, self.m, self.page = executor, executor.m, executor.page

    def _entries(self) -> List[str]:
        return [
            normalize_comment_text(t)
            for t in self.page.locator(self.ENTRY).evaluate_all("els=>els.map(e=>(e.innerText||'').trim())")
        ]

    def _enabled_send(self):
        buttons = self.page.locator(self.SEND)
        for i in range(buttons.count()):
            if buttons.nth(i).is_enabled():
                return buttons.nth(i)
        return None

    def send(self, item: Dict[str, Any]) -> Tuple[str, str, str]:
        e, m, page = self.e, self.m, self.page
        text = normalize_comment_text(item["text"])
        name = (item.get("author") or "").strip()
        original, started = m.scene_deadline, m.clock.elapsed()
        m.scene_deadline = started + min(70, max(25, m.remaining()))
        m.stats["comment_last_armed"] = False
        try:
            url = item.get("target") or ""
            if re.fullmatch(r"https://x\.com/messages/[\w-]+", url):
                e.navigator.goto(url)
            else:
                e.navigator.goto("https://x.com/messages")
                e.primary()
                rows = page.locator(self.ROWS)
                if name:
                    rows = rows.filter(has_text=name)
                if not e.poll(lambda: rows.count(), 7000):
                    raise ContentUnavailable("会话列表里找不到该对象，可能已删除或列表未加载")
                e.click(rows.first)
                if not e.poll(lambda: re.search(r"/messages/[\w-]+", urlparse(page.url).path), 6000):
                    raise PageNotReady("会话没有打开")
            if page.locator('input[type="password"]:visible').count():
                raise ContentUnavailable("需要输入聊天 PIN / 验证，已保留给人工处理")
            editor = e.poll(
                lambda: page.locator(self.COMPOSER).first if page.locator(self.COMPOSER).count() else None,
                7000,
            )
            if editor is None:
                raise ContentUnavailable("没有找到私信输入框（页面结构变化，或该会话不能回复）")
            body = e.primary().inner_text(timeout=e.timeout(3000))
            if name and name.casefold() not in body.casefold():
                raise ContentUnavailable("无法在会话中确认对象名称，为避免发错人已取消")
            conv_url = page.url
            e.click(editor)
            editor.fill(text, timeout=e.timeout(6000))
            typed = normalize_comment_text(editor.evaluate("el=>('value' in el)?el.value:(el.innerText||'')"))
            if typed != text:
                raise ValueError("私信输入校验失败，未发送")
            button = e.poll(self._enabled_send, 4000)
            if button is None:
                raise ContentUnavailable("发送按钮不可用")
            before = sum(text in t for t in self._entries())
            m.checkpoint()
            m.stats["comment_last_armed"] = True  # 从这一刻起结果不明时只能人工核对，绝不重发
            e.click(button)
            confirmed = e.poll(lambda: sum(text in t for t in self._entries()) > before, 12000)
            if confirmed:
                return "sent", conv_url, ""
            return "unknown", conv_url, "已点击发送，但没有在会话里看到这条消息，请人工核对"
        finally:
            m.scene_deadline = original + (m.clock.elapsed() - started) if original is not None else None


class OutboxDispatcher:
    """把面板里人工写好的回复发出去：一条一条、点击一次、等服务端确认；不生成内容、不群发。
    受“同账号最小间隔”和“每日上限”约束。"""

    def __init__(self, executor):
        self.e, self.m = executor, executor.m
        self.store = get_store()

    def pending(self) -> int:
        return self.store.pending_count(self.m.browser_id)

    def wait_needed(self) -> float:
        last = self.store.last_send_ts(self.m.browser_id)
        if last is None:
            return 0.0
        return max(0.0, self.m.cfg.reply_min_interval - (time.time() - last))

    def capped(self) -> bool:
        cap = self.m.cfg.reply_daily_cap
        return bool(cap) and self.store.sent_today(self.m.browser_id) >= cap

    def run(self, blocking: bool = True, max_items: int = 5) -> int:
        m, done = self.m, 0
        while done < max_items:
            m.checkpoint()
            if not self.pending():
                break
            if self.capped():
                if not m.stats.get("reply_cap_logged"):
                    m.stats["reply_cap_logged"] = True
                    m.log(f"今日面板回复已达上限 {m.cfg.reply_daily_cap} 条，剩余待发保留到明天。")
                break
            wait = self.wait_needed()
            if wait > 0:
                if not blocking or wait > 120:
                    break
                m.workflow_name, m.workflow_phase = "面板回复", f"等待发送间隔 {wait:.0f} 秒"
                m.sleep(wait)
                continue
            item = self.store.claim_outbox(m.browser_id)
            if item is None:
                break
            self.send_item(item)
            done += 1
        return done

    def send_reply(self, item: Dict[str, Any]) -> Tuple[str, str, str]:
        target = str(item["target"])
        if not target.isdigit():
            raise ContentUnavailable("回复目标 ID 无效")
        url = item.get("url") or f"https://x.com/i/status/{target}"
        tid = PanelReplyPublisher(self.e).send(target, url, item["text"], item["id"])
        if tid:
            return "sent", f"https://x.com/i/status/{tid}", ""
        return "unknown", "", "提交后没有收到成功确认，请到该账号的回复列表核对"

    def send_item(self, item: Dict[str, Any]) -> None:
        e, m, store = self.e, self.m, self.store
        oid, kind = item["id"], item["kind"]
        label = "私信" if kind == "dm" else "评论回复"
        m.workflow_name = "面板回复"
        m.stats["comment_last_armed"] = False
        snapshot = None
        try:
            snapshot = e.navigator.capture()
        except FATAL_ERRORS:
            store.finish_outbox(oid, "pending", "任务中断，未发送，已放回待发")
            raise
        except Exception:
            snapshot = None
        state, url, error, fatal = "failed", "", "", None
        try:
            e.phase(f"发送{label} #{oid} → {item.get('author') or item['target']}")
            if kind == "dm":
                state, url, error = PanelDMSender(e).send(item)
                if state == "sent":
                    store.set_inbox_url(item.get("inbox_id"), url)
            else:
                state, url, error = self.send_reply(item)
        except BaseException as exc:
            armed = bool(m.stats.get("comment_last_armed"))
            is_fatal = isinstance(exc, FATAL_ERRORS + (KeyboardInterrupt, SystemExit))
            if isinstance(exc, CommentRejected):
                state, error = "failed", "服务端拒绝：" + str(exc)
            elif armed:
                state, error = "unknown", "点击发送后中断或超时，请到该账号核对：" + short_error(exc)
            elif is_fatal:
                state, error = "pending", "任务中断，未发送，已放回待发"
            else:
                state, error = "failed", short_error(exc)
            fatal = exc if is_fatal else None
            if not is_fatal:
                logger.warning("面板回复失败 #%s", oid, exc_info=True)
        store.finish_outbox(oid, state, error, url)
        who = item.get("author") or item["target"]
        zh = {"sent": "已发送", "unknown": "结果待核对", "failed": "发送失败", "pending": "已放回待发"}[state]
        m.log(f"面板{label} #{oid} → {who}：{zh}" + (f"｜{error}" if error else ""))
        store.log_event(
            m.browser_id, m.browser_name, "reply_" + state, f"{label} → {who}：{item['text'][:40]}（{zh}）"
        )
        if state == "sent":
            m.stats["panel_replies"] = m.stats.get("panel_replies", 0) + 1
        if fatal is not None:
            raise fatal
        if snapshot is not None and m.remaining() > 1:
            original = m.scene_deadline
            m.scene_deadline = m.clock.elapsed() + min(15, m.remaining())
            try:
                e.navigator.restore(snapshot)
            except FATAL_ERRORS:
                raise
            except Exception:
                try:
                    e.navigator.goto(TWITTER_HOME_URL)
                except FATAL_ERRORS:
                    raise
                except Exception:
                    logger.debug("回复后返回首页失败", exc_info=True)
            finally:
                m.scene_deadline = original


# ======================================================================
# 模块：xmanager/workflows.py
# ======================================================================
"""工作流目录、触发档位、发推定时与关键词 TXT。"""


import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Tuple



@dataclass(frozen=True)
class WorkflowSpec:
    key: str
    label: str
    base: int
    minimum_sec: int
    budget_sec: int
    tier: str = "normal"
    group: str = "基础阅读"
    handler: str = ""
    arg: str = ""
    manual_only: bool = False


WORKFLOW_SPECS = (
    WorkflowSpec("short_browse", "短时间查看动态", 3, 12, 55),
    WorkflowSpec("interest", "围绕兴趣阅读", 3, 15, 70),
    WorkflowSpec("long_read", "长文深读", 2, 12, 65),
    WorkflowSpec("comments", "评论区讨论阅读", 2, 20, 85),
    WorkflowSpec("gallery", "图片内容浏览", 2, 12, 55),
    WorkflowSpec("video", "视频内容浏览", 2, 15, 65),
    WorkflowSpec("profile", "作者主页了解", 2, 20, 80),
    WorkflowSpec("following", "关注列表巡看", 2, 15, 65),
    WorkflowSpec("search", "主题搜索", 2, 18, 75),
    WorkflowSpec("notifications", "通知查看", 1, 12, 60),
    WorkflowSpec("revisit", "回访未读完的内容", 2, 15, 65),
    WorkflowSpec("casual_exit", "随便看看后退出", 1, 8, 40),
)


# V8 工作流目录：每条自动项绑定真实处理器；手动项不进入调度。
TIER_RULES = {
    "high": ("高频阅读", 8.0, (18.0, 75.0), (0.0, 8.0)),
    "normal": ("常规探索", 4.0, (55.0, 180.0), (5.0, 35.0)),
    "low": ("低频回访", 1.0, (180.0, 480.0), (35.0, 140.0)),
    "conditional": ("条件触发", 2.5, (90.0, 300.0), (12.0, 65.0)),
    "manual": ("手动处理", 0.0, (0.0, 0.0), (0.0, 0.0)),
}
TIER_BY_LABEL = {value[0]: key for key, value in TIER_RULES.items()}
LEGACY_TIER = {
    "short_browse": "high",
    "interest": "high",
    "long_read": "normal",
    "comments": "normal",
    "gallery": "normal",
    "video": "normal",
    "profile": "normal",
    "following": "high",
    "search": "normal",
    "notifications": "low",
    "revisit": "low",
    "casual_exit": "low",
}

# key, label, group, tier, handler, argument, budget
_EXTRA_READING = (
    ("session_resume", "继续最近阅读", "进入与恢复", "low", "recent", "", 65),
    ("source_restore", "进入详情并返回来源", "进入与恢复", "normal", "detail", "", 65),
    ("feed_backtrack", "信息流上滑回看", "首页信息流", "high", "backtrack", "", 45),
    ("feed_refresh", "首页刷新与新内容", "首页信息流", "low", "refresh", "", 60),
    ("detail_read", "单帖正文与详情", "单帖阅读", "high", "detail", "", 65),
    ("translate_read", "展开可用译文", "单帖阅读", "conditional", "translate", "", 60),
    ("post_menu", "查看帖子菜单后关闭", "单帖阅读", "low", "post_menu", "", 45),
    ("thread_read", "线程上下文阅读", "线程与上下文", "normal", "thread", "", 85),
    ("reply_branch", "回复分支与父级阅读", "评论区阅读", "conditional", "reply_branch", "", 90),
    ("quote_context", "引用帖与原帖阅读", "线程与上下文", "conditional", "quote", "", 75),
    ("hashtag_read", "正文话题延伸阅读", "搜索与话题", "conditional", "post_link", "hashtag", 70),
    ("mention_read", "正文提及账号了解", "用户主页", "conditional", "post_link", "mention", 70),
    ("external_read", "外部链接阅读并返回", "分享与站外", "conditional", "external", "", 65),
    ("image_alt", "图片说明与ALT阅读", "图片与GIF", "conditional", "image_alt", "", 55),
    ("gif_read", "GIF内容浏览", "图片与GIF", "conditional", "gif", "", 55),
    ("video_review", "视频暂停与片段回看", "视频", "conditional", "video_review", "", 65),
    ("search_top", "主题热门结果阅读", "搜索", "normal", "search_mode", "top", 75),
    ("search_people", "搜索用户与简介", "搜索", "normal", "search_mode", "user", 70),
    ("search_photos", "搜索图片结果", "搜索", "conditional", "search_mode", "image", 70),
    ("search_videos", "搜索视频结果", "搜索", "conditional", "search_mode", "video", 70),
    ("search_refine", "精确短语与条件搜索", "搜索", "low", "search_mode", "exact", 75),
    ("search_history", "搜索记录与保存入口查看", "搜索", "low", "search_history", "", 50),
    ("explore_read", "探索与趋势浏览", "探索与趋势", "normal", "surface", "explore", 65),
    ("trend_read", "进入趋势讨论", "探索与趋势", "conditional", "trend", "", 75),
    ("custom_timeline", "自定义信息流阅读", "探索与趋势", "conditional", "custom_timeline", "", 65),
    ("profile_media", "作者媒体标签阅读", "用户主页", "conditional", "profile_tab", "media", 75),
    ("profile_replies", "作者回复标签阅读", "用户主页", "normal", "profile_tab", "with_replies", 75),
    ("profile_articles", "作者文章标签阅读", "用户主页", "conditional", "profile_tab", "articles", 80),
    ("profile_followers", "作者粉丝列表查看", "关注关系", "low", "profile_tab", "followers", 65),
    ("profile_following", "作者关注列表查看", "关注关系", "low", "profile_tab", "following", 65),
    ("bookmarks_read", "书签内容重访", "书签与历史", "low", "surface", "bookmarks", 70),
    ("history_read", "History历史内容重访", "书签与历史", "conditional", "surface", "history", 70),
    ("lists_read", "列表内容浏览", "Lists列表", "conditional", "collection", "lists", 80),
    ("notifications_mentions", "提及通知与关联内容", "通知", "low", "mentions", "", 65),
    ("own_profile", "自己的主页与内容核查", "自己的内容", "low", "own_profile", "", 70),
    ("messages_read", "消息会话阅读（改变已读状态）", "私信与Chat", "conditional", "messages", "", 65),
    (
        "communities_read",
        "社群发现与内容阅读",
        "Communities社群",
        "conditional",
        "collection",
        "communities",
        85,
    ),
    ("community_rules", "社群规则与简介", "Communities社群", "conditional", "community_rules", "", 70),
    ("spaces_read", "音频空间卡片与详情", "Spaces空间", "conditional", "linked_surface", "spaces", 65),
    ("live_read", "直播与回放观看", "直播", "conditional", "live", "", 75),
    ("articles_read", "Articles文章阅读", "Articles文章", "conditional", "linked_surface", "articles", 90),
    ("grok_history", "Grok入口与已有内容查看", "Grok", "conditional", "surface", "grok", 60),
    ("notes_read", "社区附注与来源说明", "社区附注", "conditional", "notes", "", 65),
    ("poll_read", "投票选项与公开结果阅读", "投票", "conditional", "poll", "", 60),
    ("share_menu", "查看分享选项后关闭", "分享与站外", "low", "share_menu", "", 45),
    ("settings_read", "设置目录只读巡览", "设置与辅助功能", "low", "surface", "settings", 55),
    ("premium_read", "会员权益页只读查看", "会员与订阅", "conditional", "surface", "premium", 55),
    ("creator_read", "创作者工具入口查看", "专业工具", "conditional", "surface", "creator", 55),
    ("security_read", "安全设置目录只读查看", "安全与授权", "low", "surface", "security", 55),
    ("account_read", "账号设置目录只读查看", "账号生命周期", "low", "surface", "account", 55),
    ("accessibility_read", "显示语言与辅助功能目录", "设置与辅助功能", "low", "surface", "accessibility", 55),
    ("preference_read", "隐私与内容偏好目录查看", "内容偏好", "low", "surface", "privacy", 55),
    ("like_read_post", "已读帖子点赞与结果核实", "点赞转发引用", "conditional", "like", "", 55),
    ("comment_dispatch", "已读推文TXT评论", "发表评论", "conditional", "comment", "", 90),
)

# 涉及发送、关系修改、付费、隐私和删除的操作单列，绝不以浏览完成冒充已执行。
_MANUAL_ACTIONS = (
    ("account_switch", "切换身份、登录与退出", "进入与恢复", "/home"),
    ("like_remove", "取消已有点赞", "点赞转发引用", "/home"),
    ("repost_manage", "转发与撤销转发", "点赞转发引用", "/home"),
    ("quote_publish", "编辑并发布引用", "点赞转发引用", "/compose/post"),
    ("bookmark_manage", "添加删除书签与文件夹管理", "书签与历史", "/i/bookmarks"),
    ("follow_manage", "关注、取消、请求及移除粉丝", "关注关系", "/home"),
    ("follow_notify", "修改作者通知与转发显示", "关注关系", "/home"),
    ("list_manage", "创建编辑删除列表、管理成员", "Lists列表", "/i/lists"),
    ("notification_manage", "修改推送与通知过滤", "通知", "/settings/notifications"),
    ("compose_publish", "自由撰写、媒体、线程与发布", "发帖与草稿", "/compose/post"),
    ("txt_publish", "TXT自动发推及定时（使用发推设置）", "发帖与草稿", "/compose/post"),
    ("draft_manage", "草稿与平台定时计划管理", "发帖与草稿", "/compose/post"),
    ("post_manage", "编辑删除置顶、回复权限管理", "自己的内容", "/home"),
    ("reply_manage", "隐藏回复、编辑或删除自己的回复", "发表评论", "/home"),
    ("poll_vote", "投票或创建投票", "投票", "/compose/post"),
    ("media_download", "媒体下载、上传与发布设置", "图片与GIF", "/home"),
    ("video_settings", "字幕、音量与播放偏好管理", "视频", "/settings/data"),
    ("message_send", "发送、回应、删除消息及群管理", "私信与Chat", "/messages"),
    ("chat_security", "Chat PIN、安全号码与恢复", "私信与Chat", "/messages"),
    ("calls_manage", "发起接听音视频及群通话", "音视频通话", "/messages"),
    ("community_join", "加入申请、邀请及退出社群", "Communities社群", "/i/communities"),
    ("community_manage", "社群发帖、成员与版主管理", "Communities社群", "/i/communities"),
    ("space_participate", "加入收听、申请发言及回应", "Spaces空间", "/home"),
    ("space_host", "创建预约主持及结束空间", "Spaces空间", "/home"),
    ("live_host", "创建管理直播与回放", "直播", "/home"),
    ("article_publish", "撰写编辑发布删除文章", "Articles文章", "/i/articles"),
    ("grok_send", "Grok提问反馈及对话管理", "Grok", "/i/grok"),
    ("notes_contribute", "申请贡献者、撰写与评分附注", "社区附注", "/i/communitynotes"),
    ("share_send", "复制链接、私信分享与站外分享", "分享与站外", "/home"),
    ("mute_block_report", "静音屏蔽举报及离开对话", "内容偏好", "/settings/privacy_and_safety"),
    ("profile_edit", "修改头像封面简介用户名", "个人资料", "/settings/profile"),
    ("privacy_edit", "修改保护、联系人与数据共享", "设置与辅助功能", "/settings/privacy_and_safety"),
    ("credentials_edit", "修改密码邮箱手机与双重验证", "安全与授权", "/settings/security_and_account_access"),
    ("sessions_edit", "结束会话与撤销应用授权", "安全与授权", "/settings/apps_and_sessions"),
    ("archive_download", "请求和下载账号存档", "安全与授权", "/settings/download_your_data"),
    ("account_lifecycle", "停用恢复账号与申诉", "账号生命周期", "/settings/account"),
    ("subscription_pay", "会员、赠送、创作者订阅与付款", "会员与订阅", "/settings/premium"),
    ("creator_payout", "收益资格、收款与税务设置", "专业工具", "/home"),
    ("pro_ads", "X Pro、广告与Media Studio操作", "专业工具", "/home"),
)

WORKFLOW_SPECS = (
    WORKFLOW_SPECS
    + tuple(
        WorkflowSpec(key, label, 1, 10, budget, tier, group, handler, arg)
        for key, label, group, tier, handler, arg, budget in _EXTRA_READING
    )
    + tuple(
        WorkflowSpec(key, label, 0, 0, 0, "manual", group, "manual", route, True)
        for key, label, group, route in _MANUAL_ACTIONS
    )
)
WORKFLOW_BY_KEY = {spec.key: spec for spec in WORKFLOW_SPECS}
DEFAULT_WORKFLOW_SETTINGS = tuple(
    (spec.key, not spec.manual_only and spec.key != "messages_read", spec.base) for spec in WORKFLOW_SPECS
)


def migrate_workflow_settings(rows):
    """旧12项精确保留，新项补默认；重复、未知或坏行报错，避免吞配置。"""
    if rows is None:
        return DEFAULT_WORKFLOW_SETTINGS
    saved = {}
    for row in rows:
        if not isinstance(row, (tuple, list)) or len(row) != 3:
            raise ValueError("工作流设置格式错误")
        key, enabled, base = row
        if key not in WORKFLOW_BY_KEY or key in saved:
            raise ValueError("工作流名称未知或重复")
        if type(enabled) is not bool or type(base) is not int or not 0 <= base <= 500:
            raise ValueError("工作流启用状态或基础次数无效")
        spec = WORKFLOW_BY_KEY[key]
        saved[key] = (key, False if spec.manual_only else enabled, 0 if spec.manual_only else base)
    return tuple(saved.get(key, (key, enabled, base)) for key, enabled, base in DEFAULT_WORKFLOW_SETTINGS)


def workflow_tier(spec, overrides=()):
    return (
        "manual" if spec.manual_only else dict(overrides).get(spec.key, LEGACY_TIER.get(spec.key, spec.tier))
    )


def validate_post_schedule(mode: str, day: str, clock: str) -> None:
    if mode not in ("immediate", "once", "daily"):
        raise ValueError("定时方式无效")
    if mode == "immediate":
        return
    try:
        datetime.strptime(clock.strip(), "%H:%M:%S" if clock.strip().count(":") == 2 else "%H:%M")
        if mode == "once":
            datetime.strptime(day.strip(), "%Y-%m-%d")
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError("日期请填 YYYY-MM-DD，时间请填 HH:MM 或 HH:MM:SS（本机时间）") from exc


def next_post_schedule(mode, day, clock, now=None, last_date=None):
    """使用运行电脑的本地墙钟；日程至多每天一次，不重叠或补发多轮。"""
    validate_post_schedule(mode, day, clock)
    now = now if now is not None else datetime.now()
    if mode == "immediate":
        return now
    parsed = datetime.strptime(clock.strip(), "%H:%M:%S" if clock.strip().count(":") == 2 else "%H:%M").time()
    if mode == "once":
        target = datetime.combine(datetime.strptime(day.strip(), "%Y-%m-%d").date(), parsed)
        if target <= now:
            raise ValueError("指定发推时间已经过去，请设置未来时间")
        return target
    target = datetime.combine(now.date(), parsed)
    if target <= now:
        target += timedelta(days=1)
    if last_date is not None and target.date() <= last_date:
        target = datetime.combine(last_date + timedelta(days=1), parsed)
    return target


def load_keyword_lines(path: str) -> Tuple[str, ...]:
    """TXT一行一个关键词；支持UTF-8/BOM、UTF-16 BOM及Windows中文编码。"""
    file = Path(path).expanduser()
    if not file.is_file():
        raise ValueError(f"关键词TXT不存在：{file}")
    data = file.read_bytes()
    try:
        if data.startswith((b'\xff\xfe', b'\xfe\xff')):
            text = data.decode('utf-16')
        else:
            try:
                text = data.decode('utf-8-sig')
            except UnicodeDecodeError:
                text = data.decode('gb18030')
    except UnicodeDecodeError as exc:
        raise ValueError("关键词TXT编码无法识别，请保存为UTF-8") from exc
    if '\x00' in text:
        raise ValueError("关键词TXT含无效字符，请保存为UTF-8或带BOM的UTF-16")
    rows = tuple(line.strip() for line in text.splitlines() if line.strip())
    if not rows:
        raise ValueError("关键词TXT没有有效内容，请每行填写一个关键词")
    return rows


def migrate_keyword_file(terms):
    """旧手填关键词转为用户电脑上的TXT，不覆盖已有文件。"""
    rows = tuple(str(term).strip() for term in terms if str(term).strip())
    if not rows:
        return ''
    path = DATA_DIR / '关键词_旧配置.txt'
    if path.exists():
        try:
            if load_keyword_lines(str(path)) == rows:
                return str(path)
        except (ValueError, OSError):
            pass
        path = DATA_DIR / f'关键词_旧配置_{time.time_ns()}.txt'
    with path.open('x', encoding='utf-8', newline='\n') as stream:
        stream.write('\n'.join(rows) + '\n')
    return str(path)


# ======================================================================
# 模块：xmanager/models.py
# ======================================================================
"""一批任务的不可变运行配置。"""


import math
from dataclasses import dataclass
from enum import Enum
from typing import Tuple



READING_FIELDS = (
    ('main_weight',80,'继续主线权重',1,1000),
    ('content_weight',17,'当前内容支线权重',0,1000),
    ('explore_weight',3,'低频探索权重',0,1000),
    ('min_segment_seconds',12.0,'支线前最少主线秒数',0,600),
    ('min_segment_reads',2,'支线前最少阅读条数',1,100),
    ('side_cooldown',30.0,'阅读链之间冷却秒数',0,3600),
    ('comment_age_boost_cap',3.0,'到期评论等待加权上限倍数',1,10),
    ('comment_age_ramp',180.0,'到期评论达到加权上限的等待秒数',1,3600),
    ('max_secondary_ratio',0.30,'辅助耗时目标上限比例',0.01,0.8),
    ('chain_budget',70.0,'同帖阅读链总预算秒数',10,600),
    ('step_budget',25.0,'单步预算秒数',5,180),
    ('restore_budget',12.0,'返回来源预留秒数',3,60),
    ('max_chain_steps',3,'同帖最多支线步骤',1,8),
    ('max_crosspage_steps',2,'同帖最多跨页步骤',1,5),
    ('max_images',3,'单帖最多查看图片数',1,10),
    ('discussion_budget',35.0,'单帖讨论预算秒数',5,180),
    ('max_discussion_depth',2,'讨论最大上下文深度',1,5),
    ('max_reply_expands',3,'讨论最多展开次数',0,20),
    ('max_discussion_reads',6,'单帖最多阅读回复数',1,50),
    ('explore_interval',180.0,'独立探索间隔秒数',0,7200),
    ('post_capacity',1000,'会话帖子档案容量',50,10000),
    ('score_ttl',60.0,'相同内容评分缓存秒数',5,3600),
    ('heat_min_samples',5,'热度置信度所需样本数',2,100),
    ('author_window',12,'作者连续性参考帖子窗口',2,100),
    ('body_threshold',50.0,'正文支线最低分',0,100),
    ('image_threshold',50.0,'图片支线最低分',0,100),
    ('video_threshold',50.0,'视频支线最低分',0,100),
    ('discussion_threshold',55.0,'讨论支线最低分',0,100),
    ('author_threshold',60.0,'作者支线最低分',0,100),
    ('score_relevance_weight',0.25,'综合分：相关性权重',0,1),
    ('score_heat_weight',0.20,'综合分：热度权重',0,1),
    ('score_body_weight',0.20,'综合分：正文权重',0,1),
    ('score_image_weight',0.10,'综合分：图片权重',0,1),
    ('score_video_weight',0.10,'综合分：视频权重',0,1),
    ('score_discussion_weight',0.10,'综合分：讨论权重',0,1),
    ('score_author_weight',0.05,'综合分：作者权重',0,1),
)


READING_PHASE_LABELS={'primary_reading':'主线阅读','post_analysis':'帖子分析','content_branch':'内容支线','exploration':'低频探索','discussion':'评论阅读','subcomments':'子评论阅读','restore':'返回恢复','images':'图片查看','video_reading':'视频浏览'}


DEFAULT_READING_POLICY=tuple((key,value) for key,value,*_ in READING_FIELDS)


def reading_policy(cfg):
    return dict(cfg.reading_policy)


def score_clip(value):
    return round(max(0.0,min(100.0,value)),1)


def observed_count(value):
    """缺失/没有数字的标签为未知，明确的0保留0。"""
    if value is None:return None
    if isinstance(value,(int,float)):
        return int(value) if math.isfinite(value) and value>=0 else None
    return parse_count(value)


def feature_metrics(features, now):
    metrics={key:observed_count(features.get(key)) for key in ('likes','replies','reposts','views')}
    known=[metrics[k]*w for k,w in (('likes',1),('replies',3),('reposts',2)) if metrics[k] is not None]
    total=sum(known) if known else None
    result={'volume':math.log1p(total) if total is not None else None,'rate':None,'velocity':None}
    if total is not None and metrics['views'] and all(metrics[k] is not None for k in ('likes','replies','reposts')):
        result['rate']=total/metrics['views']
    published=None
    try:
        published=datetime.fromisoformat(str(features.get('published','')).replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,OverflowError):pass
    if total is not None and published is not None and 0<=now-published:
        result['velocity']=math.log1p(total/max(1.0,(now-published)/3600))
    return metrics,result


class PostReadingBook:
    def __init__(self, policy):
        self.policy=policy
        self.entries=OrderedDict()
        self.authors=OrderedDict()
        self.current=None
        self.total_posts=0

    def observe(self, features, terms=(), now=None):
        now=time.time() if now is None else now
        url=canonical_status_url(features.get('url') or '')
        if not url:raise ContentUnavailable('当前帖子没有稳定ID')
        pid=url.rsplit('/',1)[-1]
        data=dict(features,url=url,id=pid)
        data['text']=str(data.get('text') or '')[:8000]
        data['types']=[label for label,on in (('长文',len(data['text'])>=140 or data.get('expand')),('单图',data.get('images')==1),('多图',(data.get('images') or 0)>1),('视频',data.get('video')),('GIF',data.get('gif')),('引用帖',data.get('quote_url')),('线程',data.get('thread')),('投票',data.get('poll'))) if on] or ['普通文字']
        fingerprint=hashlib.sha256(json.dumps(data,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
        entry=self.entries.get(pid)
        new=entry is None
        if new:
            self.total_posts+=1
            author=str(data.get('author') or '').casefold()
            if author:
                self.authors[author]=self.authors.get(author,0)+1
                self.authors.move_to_end(author)
                while len(self.authors)>512:self.authors.popitem(last=False)
            entry={'id':pid,'url':url,'first_seen':now,'actions':{},'read':False,
                   'source':{},'discussion':{'seen':[],'edges':[],'expanded':[]},'score_revision':0}
            self.entries[pid]=entry
        entry['last_seen']=now
        self.entries.move_to_end(pid)
        self.current=pid
        if new or entry.get('fingerprint')!=fingerprint or now-entry.get('scored_at',0)>=self.policy['score_ttl']:
            entry['features']=data
            entry['fingerprint']=fingerprint
            entry['scores']=self.score(data,terms,now,pid)
            entry['scored_at']=now
            entry['score_revision']+=1
        while len(self.entries)>self.policy['post_capacity']:
            self.entries.popitem(last=False)
        return entry

    def score(self, f, terms, now, pid):
        text=str(f.get('text') or '')
        matched=[term for term in terms if term.casefold() in text.casefold()]
        relevance=score_clip(100*min(1,len(matched)/max(1,min(3,len(terms))))) if terms else None
        rel=relevance or 0
        metrics,signals=feature_metrics(f,now)
        others=[feature_metrics(e['features'],now)[1] for key,e in self.entries.items() if key!=pid and e.get('features')]
        components=[]
        for key,value in signals.items():
            samples=[s[key] for s in others if s.get(key) is not None]
            if value is not None and samples:
                percentile=100*(sum(v<value for v in samples)+.5*sum(v==value for v in samples))/len(samples)
                components.append(percentile)
        known=sum(v is not None for v in metrics.values())
        confidence=round((known/4)*min(1,(len(others)+1)/self.policy['heat_min_samples']),2)
        heat=score_clip(50+((sum(components)/len(components) if components else 50)-50)*confidence) if known else None
        body=score_clip(min(60,len(text)/8)+25*bool(f.get('expand'))+10*bool(f.get('quote_url'))+10*bool(f.get('thread'))+.15*rel)
        image=score_clip(45+10*min(2,max(0,int(f.get('images',0))-1))+10*bool(f.get('image_alt'))+.15*rel+.10*(heat or 0)) if f.get('images') else None
        video=score_clip(45+10*bool(f.get('video_ready'))+.20*rel+.10*(heat or 0)) if f.get('video') else None
        replies=metrics['replies']
        discussion=(score_clip(20+min(50,20*math.log10(1+replies))+.20*rel+.10*(heat or 0)) if replies else 0.0) if replies is not None else None
        author_name=str(f.get('author') or '').casefold()
        count=sum(str(e.get('features',{}).get('author') or '').casefold()==author_name for e in list(self.entries.values())[-self.policy['author_window']:]) if author_name else 0
        author=score_clip(min(60,count*20)+.25*rel+.1*(heat or 0)) if count>=2 else 0.0
        values={'relevance':relevance,'heat':heat,'body':body,'image':image,'video':video,'discussion':discussion,'author':author}
        weighted=[(v,self.policy['score_'+key+'_weight']) for key,v in values.items() if v is not None]
        denominator=sum(w for _,w in weighted)
        overall=score_clip(sum(v*w for v,w in weighted)/denominator) if denominator else 0.0
        return dict(values,overall=overall,confidence=confidence,matched_terms=matched,
                    missing=[k for k,v in metrics.items() if v is None],metrics=metrics,
                    evidence={'relative_samples':len(others),'signals':signals,'text_length':len(text),'author_posts':count})

    def snapshot(self):
        return list(self.entries.values())


POST_FEATURE_JS=r'''el => {
    const own=n=>n && n.closest('article[data-testid="tweet"]')===el && !n.closest('[data-testid="quoteTweet"]');
    const all=s=>[...el.querySelectorAll(s)].filter(own);
    const times=all('a[href*="/status/"] time');
    const link=times.length?times[0].closest('a'):null;
    const path=link?link.getAttribute('href'):'';
    const m=path.match(/^\/([A-Za-z0-9_]+)\/status\/(\d+)/);
    const metric=s=>{const n=all(s)[0];return n?((n.innerText||'').trim()||n.getAttribute('aria-label')||null):null;};
    const videos=all('video');const v=videos[0];
    const links=all('a[href]').map(a=>a.getAttribute('href')||'');
    const other=links.find(h=>/\/status\/\d+/.test(h)&&!h.includes('/status/'+(m?m[2]:'')));
    return {url:m?'https://x.com/'+m[1]+'/status/'+m[2]:null,author:m?m[1]:'',
      text:all('[data-testid="tweetText"]').map(n=>n.innerText||'').join('\n'),
      published:times.length?times[0].getAttribute('datetime'):null,
      likes:metric('[data-testid="like"], [data-testid="unlike"]'),replies:metric('[data-testid="reply"]'),
      reposts:metric('[data-testid="retweet"], [data-testid="unretweet"]'),views:metric('a[href$="/analytics"]'),
      expand:all('[data-testid="tweet-text-show-more-link"]').length>0||all('button').some(n=>/^(Show more|展开)$/.test((n.innerText||'').trim())),
      images:all('[data-testid="tweetPhoto"] img').filter(n=>!n.closest('[data-testid="videoPlayer"], [data-testid="videoComponent"]')).length,image_alt:all('[data-testid="tweetPhoto"] img[alt]').some(n=>!!n.getAttribute('alt')),
      video:!!v,video_ready:!!v&&v.readyState>=1&&!v.error,video_duration:v&&Number.isFinite(v.duration)?v.duration:null,
      gif:!!v&&v.loop,quote_url:other||null,
      external_links:links.filter(h=>/^https?:/.test(h)&&!/^https?:\/\/(?:www\.)?(?:x|twitter)\.com\//.test(h)),
      hashtags:links.filter(h=>h.startsWith('/hashtag/')),mentions:links.filter(h=>/^\/[A-Za-z0-9_]+$/.test(h)&&(!m||h!=='/'+m[1])),
      thread:el.getAttribute('data-thread')==='true'||all('a').some(n=>/^(Show this thread|Show this conversation|查看此线程|显示此线程|查看此对话)/i.test((n.innerText||'').trim())),
      poll:all('[data-testid="cardPoll"], [data-testid="poll"]').length>0,
      notes:all('[data-testid="birdwatch-pivot"], [data-testid="communityNote"]').length>0,
      translate:all('[data-testid="translate"]').length>0,
      specials:links.filter(h=>/\/i\/(spaces|broadcasts|articles?)\//.test(h)),
      promoted:all('[data-testid="promotedIndicator"]').length>0};
}'''


DISCUSSION_ROWS_JS=r'''({root,allowMissingRoot}) => {
    const primary=document.querySelector('[data-testid="primaryColumn"]') || document.querySelector('main');
    if(!primary)return [];
    const visible=e=>e.getClientRects().length>0;
    const articles=[...primary.querySelectorAll('article[data-testid="tweet"]')];
    const id=el=>{const t=[...el.querySelectorAll('a[href*="/status/"] time')].find(n=>n.closest('article')===el&&!n.closest('[data-testid="quoteTweet"]'));const a=t&&t.closest('a');const m=a&&(a.getAttribute('href')||'').match(/\/([A-Za-z0-9_]+)\/status\/(\d+)/);return m?{id:m[2],url:'https://x.com/'+m[1]+'/status/'+m[2],author:m[1]}:null;};
    const rootIndex=articles.findIndex(a=>{const p=id(a);return p&&p.id===root;});
    if(rootIndex<0&&!allowMissingRoot)return [];
    const headings=[...primary.querySelectorAll('[role="heading"],h1,h2,h3')];
    const end=headings.find(e=>/^(Discover more|More posts|You might like|Recommended|发现更多|更多帖子|为你推荐|你可能喜欢|相关帖子|Explorar mais|Descubre más)/i.test((e.innerText||'').trim()));
    const rows=[];
    for(let i=Math.max(0,rootIndex+1);i<articles.length;i++){
      const el=articles[i],p=id(el);if(!p||p.id===root||!visible(el))continue;
      if(end&&(end.compareDocumentPosition(el)&Node.DOCUMENT_POSITION_FOLLOWING))break;
      if(el.querySelector('[data-testid="promotedIndicator"]'))continue;
      const timeline=el.closest('[data-testid="conversation"], [aria-label*="Conversation" i], [aria-label*="对话"], [aria-label*="会话"], [aria-label*="Thread" i], [aria-label*="Conversación" i], [aria-label*="Conversa" i]');
      const parent=el.getAttribute('data-parent-id')||el.getAttribute('data-in-reply-to-id');
      if(!timeline&&parent!==root)continue; // 未确认会话边界时宁可不读，不把推荐流当回复。
      const reply=el.querySelector('[data-testid="reply"]');
      const cell=el.closest('[data-testid="cellInnerDiv"]')||el;
      const expand=[...cell.querySelectorAll('button,[role="button"],a')].find(n=>visible(n)&&/^(Show (more )?replies|View (more )?replies|显示(更多)?回复|查看(更多)?回复|更多回复|顯示(更多)?回覆|Ver (mais )?respostas|Mostrar (más )?respuestas)(\s|$)/i.test((n.innerText||n.getAttribute('aria-label')||'').trim()));
      rows.push({...p,text:(el.querySelector('[data-testid="tweetText"]')?.innerText||'').slice(0,4000),
        replies:reply?((reply.innerText||'').trim()||reply.getAttribute('aria-label')||null):null,
        parent:parent||null,relation:parent?'explicit_parent':'conversation_context',expand:!!expand});
    }
    return rows;
}'''


READING_MODEL_LABELS = {'v10':'V10 原工作流', 'v11_1':'V11.1 逐帖评分与连续阅读'}

@dataclass(frozen=True)
class WarmupConfig:
    duration_min: float
    enable_like: bool
    enable_deep_visit: bool
    close_after: bool
    random_order: bool = True  # 是否打乱队列随机启动
    enable_jitter: bool = True  # 行为概率动态浮动
    p_like: float = 0.04
    p_deep: float = 0.05
    p_photo: float = 0.03
    p_video: float = 0.06
    p_profile: float = 0.03
    p_refresh_feed: float = 0.02
    lite_mode: bool = False
    concurrency: int = 2
    max_likes: int = 10
    min_like_interval: float = 60.0
    workflow_settings: Tuple[Tuple[str, bool, int], ...] = DEFAULT_WORKFLOW_SETTINGS
    interest_terms: Tuple[str, ...] = ()
    keyword_file: str = ""
    workflow_tiers: Tuple[Tuple[str, str], ...] = ()
    draft_enabled: bool = False
    draft_file: str = ""
    draft_order: str = "sequential"
    draft_scope: str = "shared"
    draft_count: int = 1
    draft_interval: float = 300.0
    draft_schedule_mode: str = "immediate"
    draft_schedule_date: str = ""
    draft_schedule_time: str = "09:00:00"
    comment_enabled: bool = False
    comment_file: str = ""
    comment_order: str = "sequential"
    comment_count: int = 1
    comment_interval: float = 300.0
    window_layout: str = "cascade"
    # V9：数据采集与面板回复
    stats_enabled: bool = True
    stats_mentions: bool = True
    stats_dm: bool = True
    stats_posts: int = 20
    stats_interval_min: float = 0.0
    reply_min_interval: float = 45.0
    reply_daily_cap: int = 30
    service_mode: bool = False  # 只做“采集 + 发送面板回复”，不跑阅读工作流

    reading_model: str = "v10"
    reading_policy: Tuple[Tuple[str, Any], ...] = DEFAULT_READING_POLICY
    stats_recent_enabled: bool = True
    performance_only: bool = False
    recent_action_batch: str = ''
    recent_action_targets: Tuple[Tuple[str,str,str], ...] = ()
    recent_action_limits: Tuple[Tuple[str,int], ...] = (('like',0),('repost',0),('comment',0))
    recent_action_interval: float = 60.0
    recent_action_per_post: bool = False
    recent_actor_handle: str = ''
    recent_actor_handles: Tuple[Tuple[str,str], ...] = ()

    def __post_init__(self) -> None:
        if not math.isfinite(self.recent_action_interval) or not 0<=self.recent_action_interval<=86400:raise ValueError('榜单动作间隔无效')
        if type(self.recent_action_per_post) is not bool:raise ValueError('逐帖数量开关无效')
        if self.recent_action_batch:
            if not self.service_mode or self.performance_only or self.draft_enabled:raise ValueError('榜单互动只能使用独立任务模式')
            handles=dict(self.recent_actor_handles)
            if len(handles)!=len(self.recent_actor_handles) or any(not isinstance(a,str) or not a or not isinstance(h,str) or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',h) for a,h in handles.items()):raise ValueError('执行账号用户名映射无效')
            limits=dict(self.recent_action_limits)
            if set(limits)!=set(RECENT_ACTION_NAMES) or len(self.recent_action_limits)!=3 or any(type(v) is not int or not 0<=v<=100 for v in limits.values()) or not any(limits.values()):raise ValueError('榜单互动数量须为0～100')
            if self.recent_action_per_post and limits['comment']>1:raise ValueError('评论保留全局目标唯一，每帖评论只能设置0或1')
            if not 1<=len(self.recent_action_targets)<=100:raise ValueError('榜单目标数量无效')
            ids=set()
            for target,handle,url in self.recent_action_targets:
                if not target.isdigit() or not re.fullmatch(r'[A-Za-z0-9_]{1,15}',handle) or url!=f'https://x.com/{handle}/status/{target}' or target in ids:raise ValueError('榜单目标格式错误或重复')
                ids.add(target)
            if limits['comment'] and not self.comment_enabled:raise ValueError('榜单评论没有授权')
            if limits['like'] and not self.enable_like:raise ValueError('榜单点赞没有授权')
        if type(self.stats_recent_enabled) is not bool or type(self.performance_only) is not bool:raise ValueError("8小时统计开关必须是布尔值")
        if self.reading_model not in READING_MODEL_LABELS:raise ValueError("未知的养号流程")
        defaults=dict(DEFAULT_READING_POLICY)
        try:
            incoming=dict(self.reading_policy)
        except (ValueError,TypeError):
            raise ValueError('阅读策略应为键值配置') from None
        if set(incoming)-set(defaults):raise ValueError('阅读策略包含未知参数')
        defaults.update(incoming)
        for key,default,label,low,high in READING_FIELDS:
            value=defaults[key]
            if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not low<=value<=high:
                raise ValueError(f'{label}须在 {low}～{high} 之间')
            if type(default) is int and not isinstance(value,int):raise ValueError(f'{label}须为整数')
        if not sum(v for k,v in defaults.items() if k.startswith('score_')):raise ValueError('评分维度权重不能全为0')
        object.__setattr__(self,'reading_policy',tuple(defaults.items()))
        if self.reading_model=='v11_1':object.__setattr__(self,'lite_mode',False)  # 旧配置不能重新启用资源过滤。
        if not isinstance(self.keyword_file, str):
            raise ValueError("关键词TXT路径须为文本")
        if not isinstance(self.workflow_tiers, tuple):
            raise ValueError("工作流档位须为不可变配置")
        tier_keys = set()
        for row in self.workflow_tiers:
            if not isinstance(row, tuple) or len(row) != 2:
                raise ValueError("工作流档位格式错误")
            key, tier = row
            if key not in WORKFLOW_BY_KEY or key in tier_keys or tier not in TIER_RULES:
                raise ValueError("工作流档位未知或重复")
            if WORKFLOW_BY_KEY[key].manual_only and tier != "manual":
                raise ValueError("手动操作不能提升为自动触发")
            tier_keys.add(key)
        if self.window_layout not in ("cascade", "tile"):
            raise ValueError("窗口排列方式无效")
        if type(self.stats_posts) is not int or not 3 <= self.stats_posts <= 100:
            raise ValueError("每次读取的帖子数应是 3～100 的整数")
        if not math.isfinite(self.stats_interval_min) or not 0 <= self.stats_interval_min <= 1440:
            raise ValueError("中途采集间隔应在 0～1440 分钟之间（0 表示只在开局和收尾采集）")
        if not math.isfinite(self.reply_min_interval) or not 0 <= self.reply_min_interval <= 86400:
            raise ValueError("面板回复最小间隔应在 0～86400 秒之间")
        if type(self.reply_daily_cap) is not int or not 0 <= self.reply_daily_cap <= 500:
            raise ValueError("每日回复上限应是 0～500 的整数（0 表示不限制）")
        validate_post_schedule(self.draft_schedule_mode, self.draft_schedule_date, self.draft_schedule_time)
        if self.comment_order not in ("sequential", "random"):
            raise ValueError("评论读取顺序无效")
        if type(self.comment_count) is not int or self.comment_count < 1:
            raise ValueError("单号评论数量须为正整数")
        if not math.isfinite(self.comment_interval) or self.comment_interval < 0:
            raise ValueError("评论间隔须为非负秒数")
        if self.comment_enabled and not self.comment_file.strip():
            raise ValueError("请先选择评论 TXT 文件")
        if self.draft_order not in ("sequential", "random"):
            raise ValueError("草稿顺序应为顺序或随机")
        if self.draft_scope not in ("shared", "per_account"):
            raise ValueError("草稿分配方式无效")
        if type(self.draft_count) is not int or self.draft_count < 1:
            raise ValueError("单号发布数量须为正整数")
        if not math.isfinite(self.draft_interval) or self.draft_interval < 0:
            raise ValueError("发布间隔须为非负秒数")
        if self.draft_enabled and not self.draft_file.strip():
            raise ValueError("请先选择推文 TXT 文件")
        if (
            not math.isfinite(self.duration_min)
            or self.duration_min < 0
            or not math.isfinite(self.duration_min * 60)
        ):
            raise ValueError("单号时长请填非负分钟数，支持小数；0表示不按时长停止")
        if not 1 <= self.concurrency <= MAX_ACTIVE_BROWSERS:
            raise ValueError("并发数应在 1～5 之间")
        if not isinstance(self.max_likes, int) or not 0 <= self.max_likes <= 100:
            raise ValueError("单号点赞上限应是 0～100 的整数，0 表示禁用")
        if not math.isfinite(self.min_like_interval) or not 0 <= self.min_like_interval <= 86400:
            raise ValueError("点赞最小间隔应在 0～86400 秒之间")
        if not isinstance(self.workflow_settings, tuple) or len(self.workflow_settings) != len(
            WORKFLOW_SPECS
        ):
            raise ValueError(f"必须完整配置{len(WORKFLOW_SPECS)}项工作流")
        keys = set()
        for item in self.workflow_settings:
            if not isinstance(item, tuple) or len(item) != 3:
                raise ValueError("工作流设置格式错误")
            key, enabled, base = item
            if key not in WORKFLOW_BY_KEY or key in keys or not isinstance(enabled, bool):
                raise ValueError("工作流名称重复或启用状态无效")
            if type(base) is not int or not 0 <= base <= 500:
                raise ValueError("每项工作流基础次数应是0～500的整数")
            keys.add(key)
        if not isinstance(self.interest_terms, tuple) or any(
            not isinstance(term, str) or not term.strip() for term in self.interest_terms
        ):
            raise ValueError("兴趣关键词必须为文本，空行请留空或删除")
        for name in (
            "p_like",
            "p_deep",
            "p_photo",
            "p_video",
            "p_profile",
            "p_refresh_feed",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or not 0 <= value <= 1:
                raise ValueError(f"{name} 应在 0～1 之间")

    @property
    def duration_budget_sec(self) -> float:
        return math.inf if self.duration_min == 0 else self.duration_min * 60

    @property
    def duration_text(self) -> str:
        return "不限时" if self.duration_min == 0 else f"{self.duration_min:g} 分钟"


class ConnState(Enum):
    CONNECTED = "connected"
    CDP_LOST = "cdp_lost"
    RECONNECTING = "reconnecting"
    FAILED = "failed"


def compute_worker_count(total_tasks: int, concurrency: int) -> int:
    return max(1, min(total_tasks, max(1, concurrency), MAX_ACTIVE_BROWSERS))


# ======================================================================
# 模块：xmanager/planner.py
# ======================================================================
"""工作流抽样计划、阅读记录与场景导航。"""


import hashlib
import json
import math
import random
import re
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse



class WorkflowPlanner:
    """每账号每会话只抽样一次；重连沿用配额和执行记录。"""

    def __init__(self, cfg: WarmupConfig, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.session_id = uuid.uuid4().hex
        self.items: Dict[str, Dict[str, Any]] = {}
        self.last_elapsed = 0.0
        for key, enabled, base in cfg.workflow_settings:
            spec = WORKFLOW_BY_KEY[key]
            tier = workflow_tier(spec, cfg.workflow_tiers)
            amplitude = self.rng.randint(10, 60)
            offset = amplitude * self.rng.choice((-1, 1))
            raw_target = base * (1 + offset / 100.0)
            target = max(1, int(math.floor(raw_target + 0.5))) if enabled and base > 0 else 0
            reason = ""
            if spec.manual_only or tier == "manual":
                reason = "手动处理，不进入自动计划"
            elif not enabled or base == 0:
                reason = "用户禁用"
            elif key == "like_read_post" and not cfg.enable_like:
                reason = "未启用点赞"
            elif key == "comment_dispatch" and not cfg.comment_enabled:
                reason = "未启用TXT评论"
            elif cfg.lite_mode and key in (
                "gallery",
                "video",
                "image_alt",
                "gif_read",
                "video_review",
                "search_photos",
                "search_videos",
                "live_read",
                "profile_media",
            ):
                reason = "省流量模式禁用媒体"
            elif not cfg.enable_deep_visit and key in ("comments", "thread_read", "reply_branch"):
                reason = "未允许深读评论"
            elif (key in ("interest", "search") or spec.handler == "search_mode") and not cfg.interest_terms:
                reason = "未配置兴趣关键词"
            if reason:
                target = 0
            self.items[key] = {
                "label": spec.label,
                "tier": tier,
                "tier_label": TIER_RULES[tier][0],
                "group": spec.group,
                "weight": TIER_RULES[tier][1],
                "defer_until": self.rng.uniform(*TIER_RULES[tier][3]) if target else 0.0,
                "unavailable_streak": 0,
                "base": base,
                "offset_pct": offset,
                "raw_target": round(raw_target, 3),
                "target": target,
                "attempts": 0,
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": 0,
                "deferred": 0,
                "launches": 0,
                "state": "DISABLED" if reason else "PENDING",
                "disabled_reason": reason,
                "last_reason": "",
                "phase": "等待执行",
            }
        self.last_key: Optional[str] = None

    def pending(self, remaining):
        return [
            key
            for key, item in self.items.items()
            if item["attempts"] < item["target"] and WORKFLOW_BY_KEY[key].minimum_sec <= remaining
        ]

    def available(self, remaining, elapsed=0):
        pending = self.pending(remaining)
        if any(k != "casual_exit" for k in pending):
            pending = [k for k in pending if k != "casual_exit"]
        return [k for k in pending if self.items[k].get("defer_until", 0) <= elapsed]

    def next_ready_delay(self, remaining, elapsed):
        pending = self.pending(remaining)
        if any(k != "casual_exit" for k in pending):
            pending = [k for k in pending if k != "casual_exit"]
        if not pending:
            return None
        return max(0.0, min(self.items[k].get("defer_until", 0) for k in pending) - elapsed)

    def choose(self, remaining, elapsed=0):
        self.last_elapsed = elapsed
        keys = self.available(remaining, elapsed)
        if not keys:
            return None
        weights = []
        previous = self.items.get(self.last_key, {})
        for key in keys:
            item = self.items[key]
            weight = item["weight"] * math.sqrt(max(1, item["target"] - item["attempts"]))
            if item.get("context_url"):
                weight *= 2.0
            if key == self.last_key:
                weight *= 0.12
            elif previous.get("group") == item.get("group"):
                weight *= 0.65
            weights.append(max(0.001, weight))
        return self.rng.choices(keys, weights=weights, k=1)[0]

    def suggest(self, key: str, url: str) -> None:
        url = canonical_status_url(url)
        item = self.items.get(key)
        if url and item and item["attempts"] < item["target"]:
            item["context_url"] = url

    def defer(self, key: str, reason: str, until: float) -> None:
        item = self.items[key]
        if item["attempts"] < item["target"]:
            item["defer_until"] = until
            item["state"] = "DEFERRED"
            item["last_reason"] = reason
            item["phase"] = "等待内容条件"

    def begin(self, key: str) -> None:
        item = self.items[key]
        if item["state"] == "RUNNING" or item["attempts"] >= item["target"]:
            raise RuntimeError("工作流配额已用尽或正在运行")
        item["attempts"] += 1
        item["launches"] += 1
        item["state"] = "RUNNING"
        item["phase"] = "进入场景"
        self.last_key = key

    def finish(self, key: str, outcome: str, reason: str, elapsed=None) -> None:
        item = self.items[key]
        if item["state"] != "RUNNING":
            raise RuntimeError("工作流未处于执行状态")
        if outcome == "deferred":
            item["deferred"] += 1
            item["last_reason"] = str(reason)[:500]
            elapsed = self.last_elapsed if elapsed is None else elapsed
            if item["deferred"] <= 2:
                item["attempts"] -= 1
                item["state"] = "DEFERRED"
                item["phase"] = "页面未就绪，等待恢复"
                item["defer_until"] = elapsed + self.rng.uniform(12, 35)
            else:
                item["skipped"] += 1
                self.retire(key, str(reason) + "；已到本会话暂缓重试上限", "UNAVAILABLE")
            return
        if outcome not in ("completed", "skipped", "failed", "interrupted"):
            raise ValueError("未知工作流结果")
        item[outcome] += 1
        item["state"] = "DONE" if item["attempts"] >= item["target"] else "PENDING"
        item["last_reason"] = str(reason)[:500]
        item["phase"] = "已结束"
        elapsed = self.last_elapsed if elapsed is None else elapsed
        low, high = TIER_RULES[item["tier"]][2]
        item["defer_until"] = elapsed + self.rng.uniform(low, high)
        item["unavailable_streak"] = item["unavailable_streak"] + 1 if outcome == "skipped" else 0
        if item["unavailable_streak"] >= 2 and item["attempts"] < item["target"]:
            item["unspent_target"] = item["target"] - item["attempts"]
            item["target"] = item["attempts"]
            item["state"] = "UNAVAILABLE"
            item["last_reason"] += "；连续两次缺少内容，本会话不再探测"

    def retire(self, key, reason, state="UNAVAILABLE"):
        item = self.items[key]
        item["unspent_target"] = item.get("unspent_target", 0) + max(0, item["target"] - item["attempts"])
        item["target"] = item["attempts"]
        item["state"] = state
        item["phase"] = "无需继续触发" if state == "SATISFIED" else "本会话不再探测"
        item["last_reason"] = str(reason)[:500]

    def summary(self) -> Dict[str, int]:
        return {
            field: sum(item[field] for item in self.items.values())
            for field in (
                "target",
                "attempts",
                "completed",
                "skipped",
                "failed",
                "interrupted",
                "deferred",
            )
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "summary": self.summary(),
            "workflows": json.loads(json.dumps(self.items, ensure_ascii=False)),
        }


class ReadingJournal:
    """每账号隔离，只记录 URL、阅读进度和时间，不存正文或通知内容。"""

    def __init__(self, browser_id: str):
        token = hashlib.sha256(browser_id.encode("utf-8")).hexdigest()[:24]
        self.path = DATA_DIR / "reading" / f"{token}.json"
        self.entries: Dict[str, Dict[str, Any]] = {}
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.entries = {
                        url: item
                        for url, item in data.items()
                        if canonical_status_url(url) == url and isinstance(item, dict)
                    }
        except (OSError, ValueError):
            logger.warning("读取阅读记录失败，保留原文件", exc_info=True)

    def remember(self, url: Optional[str], complete: bool, scroll: float = 0, reason: str = "") -> None:
        url = canonical_status_url(url) if url else None
        if not url:
            return
        previous = self.entries.get(url, {})
        # 已完成阅读不因后续“候选发现”被降级为未读。
        complete = bool(complete or previous.get("complete"))
        self.entries[url] = {
            "complete": complete,
            "scroll": max(0.0, float(scroll)),
            "updated_at": time.time(),
            "reason": reason[:120],
            "revisit_attempts": int(previous.get("revisit_attempts", 0)),
            "thread_pending": bool(previous.get("thread_pending", False)),
            "thread_scroll": previous.get("thread_scroll", 0),
        }
        if len(self.entries) > 300:
            ordered = sorted(
                self.entries,
                key=lambda item: self.entries[item].get("updated_at", 0),
                reverse=True,
            )
            self.entries = {item: self.entries[item] for item in ordered[:300]}
        self.flush()

    def pending(self) -> List[Tuple[str, Dict[str, Any]]]:
        return sorted(
            (
                (url, item)
                for url, item in self.entries.items()
                if (not item.get("complete") or item.get("thread_pending"))
                and item.get("revisit_attempts", 0) < 3
            ),
            key=lambda row: row[1].get("updated_at", 0),
            reverse=True,
        )

    def mark_revisit(self, url: str) -> None:
        if url in self.entries:
            self.entries[url]["revisit_attempts"] = int(self.entries[url].get("revisit_attempts", 0)) + 1
            self.flush()

    def discussion(self, url: str, pending: bool, scroll: float = 0) -> None:
        url = canonical_status_url(url)
        if not url:
            return
        if url not in self.entries:
            self.remember(url, False)
        self.entries[url]["thread_pending"] = pending
        self.entries[url]["thread_scroll"] = max(0.0, float(scroll))
        self.entries[url]["updated_at"] = time.time()
        self.flush()

    def flush(self) -> None:
        try:
            atomic_json(self.path, self.entries)
        except OSError:
            logger.warning("写入阅读记录失败", exc_info=True)


@dataclass(frozen=True)
class NavigationSnapshot:
    url: str
    scroll: float
    anchor: Optional[str] = None
    feed_tab: Optional[str] = None


class SceneNavigator:
    def __init__(self, executor):
        self.e = executor
        self.page = executor.page

    def capture(self) -> NavigationSnapshot:
        try:
            scroll = float(self.page.evaluate("window.scrollY"))
        except Exception:
            scroll = 0.0
        anchor = None
        try:
            art = self.e.pick_article(lambda _art, _text: True, include_seen=True, rounds=1)
            if art is not None:
                anchor = self.e.status_url(art)
        except (StopRequested, DurationReached, SceneBudgetExceeded, AccountStateError):
            raise
        except Exception:
            logger.debug("读取返回锚点失败", exc_info=True)
        feed_tab = None
        if urlparse(self.page.url or "").path.rstrip("/") == "/home":
            selected = self.page.locator('[role="tab"][aria-selected="true"]').first
            try:
                if selected.count():
                    feed_tab = selected.inner_text(timeout=self.e.timeout(1000)).strip() or None
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("读取原信息流标签失败", exc_info=True)
        return NavigationSnapshot(self.page.url or TWITTER_HOME_URL, scroll, anchor, feed_tab)

    def goto(self, url: str) -> None:
        self.e.gate()
        if not is_x_url(url):
            raise ValueError("场景导航仅允许 X/Twitter 地址")
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=self.e.timeout(15000))
        except PlaywrightTimeoutError as exc:
            self.e.gate()
            # DOMContentLoaded超时但目标地址已到达时，继续由具体内容条件验证。
            if not same_x_route(self.page.url or '', url):
                raise PageNotReady("页面导航超时，稍后重试；未重复点击或提交") from exc
        self.e.gate()
        self.e.check_health()

    def restore(self, snapshot: NavigationSnapshot) -> None:
        self.e.gate()
        self.e.check_health(ignore_page_error=True)
        target = snapshot.url if is_x_url(snapshot.url) else TWITTER_HOME_URL
        if not same_x_route(self.page.url or "", target):
            try:
                self.page.go_back(wait_until="domcontentloaded", timeout=self.e.timeout(3500))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("历史返回未成功，将直接打开来源页", exc_info=True)
            self.e.gate()
            self.e.check_health(ignore_page_error=True)
        if not same_x_route(self.page.url or "", target) or check_page_health(self.page) == "error_page":
            self.goto(target)
        else:
            self.e.check_health()
        if not same_x_route(self.page.url or "", target):
            raise ContentUnavailable(f"来源页未恢复：{self.page.url}")
        if snapshot.feed_tab:
            tab = self.page.get_by_role(
                "tab",
                name=re.compile(r"^\s*" + re.escape(snapshot.feed_tab.strip()) + r"\s*$", re.I),
            ).first
            if tab.count() and tab.is_visible() and not self.e.tab_selected(tab):
                self.e.click(tab)
                self.e.wait_tab_selected(tab)
        self.page.evaluate("y => window.scrollTo(0, y)", max(0.0, snapshot.scroll))
        # 锚点消失只丢弃精确滚动位置，不把来源页成功恢复误记为场景失败。
        if snapshot.anchor:
            try:
                anchor = self.e.article_by_url(snapshot.anchor, wait=False)
                if anchor.count() and anchor.is_visible():
                    anchor.scroll_into_view_if_needed(timeout=self.e.timeout(1800))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("来源内容已被虚拟列表回收，保留大致位置", exc_info=True)
        self.e.gate()


# ======================================================================
# 模块：xmanager/executor_base.py
# ======================================================================
"""执行器基础能力：门禁、超时、帖子定位、阅读与点赞。"""


import random
import time
from collections import OrderedDict
from typing import TYPE_CHECKING, Optional
from urllib.parse import urlparse


if TYPE_CHECKING:  # pragma: no cover
    pass


class ExecutorBase:
    def __init__(self, machine: "TwitterWarmupMachine", page: Page):
        self.m = machine
        self.page = page
        self.plan = machine.workflow_plan
        self.navigator = SceneNavigator(self)
        self.current_key: Optional[str] = None
        self._article_urls: OrderedDict = OrderedDict()
        self.commenter = None
        self.capabilities = getattr(machine, "capabilities", {})
        machine.capabilities = self.capabilities

    def maybe_comment(self):
        if self.m.cfg.comment_enabled:
            if self.commenter is None:
                self.commenter = CommentPublisher(self)
            self.commenter.maybe_comment()

    def gate(self) -> None:
        self.m.checkpoint()
        if not self.m.cdp_alive():
            raise CdpStateError("CDP 已断开")
        if self.page.is_closed():
            raise AccountStateError(Result.PAGE_CLOSED)

    def timeout(self, requested_ms: int = 4000) -> int:
        self.gate()
        scene_left = (
            self.m.scene_deadline - self.m.clock.elapsed()
            if self.m.scene_deadline is not None
            else self.m.remaining()
        )
        return max(1, int(min(requested_ms, self.m.remaining() * 1000, scene_left * 1000)))

    def phase(self, text: str) -> None:
        self.gate()
        self.m.workflow_phase = text
        if self.current_key:
            item = self.plan.items[self.current_key]
            item["phase"] = text
            trace = item.setdefault("phase_trace", [])
            trace.append({"phase": text, "elapsed": round(self.m.clock.elapsed(), 2), "url": self.page.url})
            del trace[:-20]
        self.m.last_progress = 0
        self.m.progress()
        self.persist()

    def check_health(self, ignore_page_error: bool = False) -> None:
        health = check_page_health(self.page)
        if health == "logged_out":
            raise AccountStateError(Result.LOGIN_LOST)
        if health == "needs_action":
            raise AccountStateError(Result.NEEDS_ACTION)
        if health == "error_page" and not ignore_page_error:
            raise ContentUnavailable("当前页面有明确的全页加载异常")

    def click(self, locator) -> None:
        self.gate()
        self.m.behavior.click(self.page, locator, timeout=self.timeout())
        self.gate()

    def text(self, art) -> str:
        locator = art.locator(SELECTORS["tweet_text"]).first
        return locator.inner_text(timeout=self.timeout(1800)) if locator.count() else ""

    def status_url(self, art) -> Optional[str]:
        bound = self._article_urls.get(id(art))
        if bound is not None and bound[0] is art:
            return bound[1]
        return canonical_status_url(self.m.tweet_key(art) or "")

    def article_by_url(self, url: str, wait: bool = True, navigate_if_missing: bool = False):
        url = canonical_status_url(url)
        if not url:
            raise ContentUnavailable("帖子没有稳定ID，跳过操作")
        status_id = url.rsplit("/", 1)[-1]
        links = self.page.locator(
            f'a[href$="/status/{status_id}"]:has(time), a[href*="/status/{status_id}?"]:has(time)'
        )
        article = self.page.locator(SELECTORS["tweet"]).filter(has=links).first
        if not article.count() and navigate_if_missing:
            self.navigator.goto(url)
        if wait:
            try:
                article.wait_for(state="visible", timeout=self.timeout(4000))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception as exc:
                raise ContentUnavailable(
                    f"目标帖子 {status_id} 已离开页面或不可用：{short_error(exc)}"
                ) from exc
        self._article_urls[id(article)] = (article, url)
        if len(self._article_urls) > 256:
            self._article_urls.popitem(last=False)
        return article

    def tab_selected(self, tab) -> bool:
        return bool(
            tab.evaluate(
                "el => el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-current') === 'page' || el.getAttribute('data-state') === 'active'"
            )
        )

    def wait_tab_selected(self, tab) -> None:
        for _ in range(16):
            self.gate()
            if self.tab_selected(tab):
                return
            self.m.sleep(0.25)
        raise ContentUnavailable("已点击关注页签，但选中状态未确认")

    def scroll(self, distance: int = 450) -> None:
        self.gate()
        self.m.behavior.scroll(self.page, distance)
        self.m.sleep(self.plan.rng.uniform(0.4, 1.15))

    def ensure_home(self) -> None:
        if not is_x_url(self.page.url or "") or urlparse(self.page.url).path.rstrip("/") != "/home":
            self.navigator.goto(TWITTER_HOME_URL)
        self.check_health()

    def pick_article(self, predicate, include_seen: bool = False, rounds: int = 3):
        for turn in range(rounds):
            self.gate()
            articles = self.page.locator(SELECTORS["tweet"])
            try:
                articles.first.wait_for(state="visible", timeout=self.timeout(2500))
            except Exception:
                self.gate()
                self.check_health()
            count = min(articles.count(), 15)
            for index in range(count):
                self.gate()
                art = articles.nth(index)
                try:
                    if not art.is_visible():
                        continue
                    url = self.status_url(art)
                    if not include_seen and url and url in self.m.seen:
                        continue
                    if not url:
                        continue
                    pinned = self.article_by_url(url, wait=False)
                    if not pinned.count():
                        continue
                    if predicate(pinned, self.text(pinned)):
                        return pinned
                except (
                    StopRequested,
                    DurationReached,
                    SceneBudgetExceeded,
                    AccountStateError,
                    CdpStateError,
                ):
                    raise
                except Exception:
                    logger.debug("候选帖子已变化", exc_info=True)
            if turn + 1 < rounds:
                self.scroll()
        return None

    def require_article(self, predicate=lambda _art, _text: True, include_seen: bool = False):
        art = self.pick_article(predicate, include_seen=include_seen)
        if art is None:
            raise ContentUnavailable("没有符合条件且可见的帖子")
        return art

    def read(self, art, deep: bool = False, allow_like: bool = True) -> Optional[str]:
        self.phase("阅读正文")
        self.gate()
        url = self.status_url(art)
        art = self.article_by_url(url)
        self.m.journal.remember(url, False, reason="开始阅读")
        try:
            art.scroll_into_view_if_needed(timeout=self.timeout(2500))
            expand = art.locator(SELECTORS["show_more_text"]).first
            if deep and expand.count() and expand.is_visible():
                self.click(expand)
            text = self.text(art)
            self.m.sleep(
                self.plan.rng.uniform(0.75, 1.35)
                * min(16.0 if deep else 7.0, max(2.0, len(text) / (22 if deep else 40)))
            )
            self.m.stats["reads"] += 1
            if url:
                self.m.mark_seen(url)
            self.m.journal.remember(url, True, reason="正文阅读完成")
            if self.m.cfg.comment_enabled and url:
                target_id = url.rsplit("/", 1)[-1]
                if target_id not in self.m.comment_skipped_targets:
                    self.m.comment_candidates[target_id] = url
                while len(self.m.comment_candidates) > SEEN_LIMIT:
                    self.m.comment_candidates.popitem(last=False)
            if allow_like and self.m.can_like() and random.random() < self.m.cfg.p_like:
                self.confirmed_like(art)
            if self.m.cfg.comment_enabled:
                self.maybe_comment()
            return url
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            CdpStateError,
            AccountStateError,
        ):
            try:
                scroll = (
                    float(self.page.evaluate("window.scrollY"))
                    if canonical_status_url(self.page.url or "") == url
                    else 0.0
                )
            except Exception:
                scroll = 0.0
            self.m.journal.remember(url, False, scroll, "阅读被中断")
            raise

    def confirmed_like(self, art) -> None:
        button = art.locator(SELECTORS["like"]).first
        if not button.count() or not button.is_visible() or not self.m.can_like():
            return
        self.phase("确认点赞状态")
        # 发出点击前占用次数，超时不重发，不让不确定结果绕过上限。
        self.m.like_attempts += 1
        self.m.last_like_at = time.monotonic()
        self.m.stats["like_attempts"] = self.m.like_attempts
        try:
            self.click(button)
            art.locator('[data-testid="unlike"]').first.wait_for(state="visible", timeout=self.timeout(2000))
            self.m.stats["likes"] += 1
            try:
                get_store().record_outgoing_success(self.m.browser_id, 'like', self.status_url(art))
            except Exception:
                logger.exception('点赞已确认，但独立累计记录保存失败')
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            self.m.stats["like_unconfirmed"] += 1
            self.m.log("点赞结果未确认，本次不重试，已计入尝试上限。")

    def open_detail(self, art) -> str:
        url = self.status_url(art)
        if not url:
            raise ContentUnavailable("帖子没有可验证的详情链接")
        self.phase("进入帖子详情")
        self.navigator.goto(url)
        expected_id = urlparse(url).path.split("/status/")[-1]
        current = canonical_status_url(self.page.url or "")
        if not current or urlparse(current).path.split("/status/")[-1] != expected_id:
            raise ContentUnavailable("详情页没有到达目标帖子")
        return url

    def read_feed(self, count: int = 2, predicate=lambda _art, _text: True) -> int:
        completed = 0
        for _ in range(count):
            try:
                art = self.require_article(predicate)
            except ContentUnavailable:
                break
            self.read(art)
            completed += 1
            self.scroll(380)
        if completed == 0:
            raise ContentUnavailable("当前信息流没有新的匹配内容")
        return completed

    def poll(self, probe, requested_ms=6500):
        """等待真实页面条件；每次轮询都处理暂停/停止并驱动浏览器事件。"""
        deadline = time.monotonic() + self.timeout(requested_ms) / 1000
        while True:
            self.gate()
            try:
                value = probe()
                if value:
                    return value
            except (StopRequested, DurationReached, SceneBudgetExceeded, CdpStateError, AccountStateError):
                raise
            except Exception:
                self.gate()
                logger.debug("页面重绘，等待下一次快照", exc_info=True)
            left = deadline - time.monotonic()
            if left <= 0:
                self.check_health()
                return None
            self.page.wait_for_timeout(min(150, left * 1000))

    def persist(self) -> None:
        self.m.persist_workflow_plan()


# ======================================================================
# 模块：xmanager/scenes_core.py
# ======================================================================
"""原版 12 个阅读场景。"""


from typing import Any, Dict, Optional
from urllib.parse import urlencode, urlparse



class CoreScenesMixin:
    def short_browse(self) -> str:
        self.ensure_home()
        count = self.read_feed(self.plan.rng.randint(1, 3))
        return f"短浏览完成，阅读 {count} 条"

    def interest(self) -> str:
        terms = tuple(term.casefold() for term in self.m.cfg.interest_terms)
        if not terms:
            raise ContentUnavailable("请先配置兴趣关键词")
        self.ensure_home()
        art = self.require_article(lambda _art, text: any(term in text.casefold() for term in terms))
        url = self.read(art, deep=True)
        continuations = [
            key
            for key in ("comments", "profile")
            if self.plan.items[key]["attempts"] < self.plan.items[key]["target"]
        ]
        if url and continuations:
            key = self.plan.rng.choice(continuations)
            self.plan.suggest(key, url)
            return f"兴趣正文已读，后续优先衔接{WORKFLOW_BY_KEY[key].label}"
        return "已阅读关键词匹配内容"

    def long_read(self) -> str:
        self.ensure_home()
        art = self.require_article(
            lambda art, text: len(text) >= 140 or art.locator(SELECTORS["show_more_text"]).count() > 0
        )
        self.read(art, deep=True)
        return "长文展开与阅读完成"

    def context_article(self, key: str):
        url = self.plan.items[key].pop("context_url", None)
        if url:
            self.phase("打开上一个场景关联帖子")
            self.navigator.goto(url)
            art = self.require_article(lambda art, _text: self.status_url(art) == url, include_seen=True)
        else:
            self.ensure_home()
            art = self.require_article()
        if (self.status_url(art) or "") not in self.m.seen:
            self.read(art, allow_like=False)
        return art

    def read_discussion(self, root_url: str, count: int = 2) -> int:
        self.phase("阅读回复与讨论")
        self.m.journal.discussion(root_url, True, float(self.page.evaluate("window.scrollY")))
        read_count = 0
        seen_replies = set()
        for _ in range(3):
            self.gate()
            replies = self.page.locator(SELECTORS["tweet"])
            for index in range(min(replies.count(), 8)):
                reply = replies.nth(index)
                url = self.status_url(reply)
                if (
                    not url
                    or url == root_url
                    or url in seen_replies
                    or url in self.m.seen
                    or not reply.is_visible()
                ):
                    continue
                reply = self.article_by_url(url)
                self.read(reply, allow_like=False)
                seen_replies.add(url)
                read_count += 1
                break
            if read_count >= count:
                break
            expand = self.page.locator(SELECTORS["show_replies"]).first
            if expand.count() and expand.is_visible():
                self.click(expand)
            self.scroll(400)
            self.m.journal.discussion(root_url, True, float(self.page.evaluate("window.scrollY")))
        self.m.journal.discussion(root_url, False)
        return read_count

    def comments(self) -> str:
        art = self.context_article("comments")
        root_url = self.open_detail(art)
        read_count = self.read_discussion(root_url, self.plan.rng.randint(1, 4))
        if not read_count:
            raise ContentUnavailable("原帖已读，但没有可见的新回复")
        return f"阅读 {read_count} 条回复"

    def photo_state(self) -> Dict[str, Any]:
        return self.page.evaluate(r"""() => {
            // x_media_viewer_state_v71
            const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
            const route = new RegExp('/status/[0-9]+/photo/[0-9]+').test(location.pathname);
            const overlay = [...document.querySelectorAll('[data-testid="swipe-to-dismiss"], [role="dialog"], [aria-modal="true"]')].find(el => visible(el) && el.querySelector('[data-testid="tweetPhoto"] img, img[src*="/media/"]'));
            const images = [...(overlay || document).querySelectorAll('img')].filter(el => visible(el) && (el.closest('[data-testid="tweetPhoto"]') || (el.currentSrc || el.src).includes('/media/')));
            const image = images.find(el => el.complete && el.naturalWidth > 0 && (route || overlay));
            return {open: !!(route || overlay), loaded: !!image, identity: location.pathname + '|' + (image ? (image.currentSrc || image.src) : ''), route};
        }""")

    def wait_photo(self, rounds: int = 16) -> Optional[Dict[str, Any]]:
        for _ in range(rounds):
            self.gate()
            state = self.photo_state()
            if state.get("open") and state.get("loaded"):
                return state
            self.m.sleep(0.25)
        return None

    def gallery(self) -> str:
        self.ensure_home()
        art = self.require_article(lambda art, _text: art.locator(SELECTORS["photo"]).count() > 0)
        url = self.read(art, allow_like=False)
        art = self.article_by_url(url, navigate_if_missing=True)
        self.phase("打开图片或在信息流查看")
        photo = art.locator(SELECTORS["photo"]).first
        links = art.locator('a[href*="/photo/"]')
        own_link = None
        href = None
        for index in range(min(links.count(), 6)):
            candidate = links.nth(index)
            value = candidate.get_attribute("href", timeout=self.timeout(1200)) or ""
            if canonical_status_url(value) == url:
                own_link, href = candidate, value
                break
        if links.count() and own_link is None:
            raise ContentUnavailable("图片链接属于引用帖，未把其他帖图片当作当前帖操作")
        self.click(own_link if own_link is not None else photo)
        state = self.wait_photo()
        if state is None and href:
            target = href if is_x_url(href) else "https://x.com" + href
            self.navigator.goto(target)
            state = self.wait_photo()
        if state is None:
            # 有些页面只支持内联图片；真实看到图片可以完成浏览，但不声称打开了查看器。
            art = self.article_by_url(url, navigate_if_missing=True)
            image = art.locator(SELECTORS["photo"] + " img").first
            if (
                image.count()
                and image.is_visible()
                and image.evaluate(
                    "el => el.complete && el.naturalWidth > 0",
                    timeout=self.timeout(1500),
                )
            ):
                image.scroll_into_view_if_needed(timeout=self.timeout(2500))
                self.m.sleep(3)
                return "已在信息流查看加载完成的图片；当前页面未打开独立查看器"
            raise ContentUnavailable("图片未加载或没有可识别的查看器，跳过本次图片流程")
        self.m.sleep(3)
        viewed = 1
        for _ in range(self.plan.rng.randint(1, 3)):
            next_button = self.page.locator(
                SELECTORS["next_slide"]
                + ', [data-testid="Carousel-NavRight"], [aria-label="Próximo slide"], [aria-label="Siguiente diapositiva"]'
            ).first
            if not next_button.count() or not next_button.is_visible():
                break
            before = state.get("identity")
            self.click(next_button)
            self.m.sleep(1)
            state = self.wait_photo(8)
            if state is None or state.get("identity") == before:
                break
            viewed += 1
            self.m.sleep(1)
        self.page.keyboard.press("Escape")
        self.m.sleep(0.3)
        if self.photo_state().get("open"):
            close = self.page.locator(
                SELECTORS["close_viewer"] + ', [aria-label="Fechar"], [aria-label="Cerrar"]'
            ).first
            if close.count() and close.is_visible():
                self.click(close)
                self.m.sleep(0.3)
        if self.photo_state().get("open"):
            self.navigator.goto(url)
        return f"查看 {viewed} 张已加载图片，并离开图片查看器"

    def video_state(self, video) -> Dict[str, Any]:
        return video.evaluate(
            """v => ({time:v.currentTime || 0, duration:Number.isFinite(v.duration)?v.duration:0,
            paused:v.paused, ended:v.ended, ready:v.readyState, network:v.networkState,
            error:v.error ? v.error.code : 0})""",
            timeout=self.timeout(2000),
        )

    def video(self) -> str:
        self.ensure_home()
        art = self.require_article(lambda art, _text: art.locator("video").count() > 0)
        url = self.read(art, allow_like=False)
        try:
            art = self.article_by_url(url, navigate_if_missing=True)
            video = art.locator("video").first
            video.scroll_into_view_if_needed(timeout=self.timeout(3000))
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            # 不再复用原来的 nth(index)；详情页重新获取同一帖子的视频。
            self.navigator.goto(url)
            art = self.article_by_url(url)
            video = art.locator("video").first
            try:
                video.wait_for(state="visible", timeout=self.timeout(4500))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception as exc:
                raise ContentUnavailable(f"同一帖子的视频节点未就绪：{short_error(exc)}") from exc
        self.phase("检查视频加载与播放状态")
        before = self.video_state(video)
        if before.get("error"):
            raise ContentUnavailable(f"视频媒体错误 code={before['error']}，未尝试反复播放")
        play_result = {
            "ok": not before.get("paused", True),
            "reason": "already_playing",
        }
        if not play_result["ok"]:
            play_result = video.evaluate(
                """v => {
                v.muted=true;
                return Promise.race([
                    v.play().then(()=>({ok:true,reason:'started'})).catch(e=>({ok:false,reason:e.name || 'play_failed'})),
                    new Promise(resolve=>setTimeout(()=>resolve({ok:false,reason:'buffering_timeout'}),2000))]);
            }""",
                timeout=self.timeout(3000),
            )
        if not play_result.get("ok"):
            play = art.locator(
                '[data-testid="playButton"], [aria-label="Play"], [aria-label="Play video"], [aria-label="播放"], [aria-label="播放视频"], [aria-label="Reproduzir"], [aria-label="Reproducir"]'
            ).first
            if play.count() and play.is_visible():
                self.click(play)  # 只尝试一次可见播放按钮，不改浏览器播放策略。
            self.m.sleep(1.5)
        current = self.video_state(video)
        if current.get("error"):
            raise ContentUnavailable(f"视频媒体错误 code={current['error']}")
        if current.get("paused", True) and not play_result.get("ok"):
            raise ContentUnavailable(
                f"视频未进入播放：{play_result.get('reason', 'unknown')}，readyState={current.get('ready', 0)}，networkState={current.get('network', 0)}"
            )
        self.phase("静音观看并验证播放进度")
        watch_sec = min(
            self.plan.rng.uniform(7, 18),
            max(4.0, float(current.get("duration", 0)) - float(current.get("time", 0))),
        )
        previous = float(current.get("time", 0))
        moved = abs(previous - float(before.get("time", 0))) > 0.1
        spent = 0.0
        while spent < watch_sec:
            interval = min(2.0, watch_sec - spent)
            self.m.sleep(interval)
            spent += interval
            current = self.video_state(video)
            value = float(current.get("time", 0))
            moved = moved or abs(value - previous) > 0.1
            previous = value
            if current.get("ended") and moved:
                break
            if current.get("error"):
                raise ContentUnavailable(f"观看中媒体加载失败 code={current['error']}")
        if not moved:
            raise ContentUnavailable(
                f"视频没有实际播放进度，readyState={current.get('ready', 0)}，networkState={current.get('network', 0)}"
            )
        return f"视频播放进度已确认，观看约 {spent:.0f} 秒"

    def profile(self) -> str:
        art = self.context_article("profile")
        art = self.article_by_url(self.status_url(art), navigate_if_missing=True)
        self.phase("进入作者主页")
        link = art.locator('[data-testid="User-Name"] a[role="link"]').first
        href = link.get_attribute("href", timeout=self.timeout(2000)) if link.count() else None
        if not href or not href.startswith("/") or len(href.strip("/").split("/")) != 1:
            raise ContentUnavailable("没有可验证的作者主页链接")
        self.navigator.goto("https://x.com" + href)
        if urlparse(self.page.url).path.rstrip("/").casefold() != href.rstrip("/").casefold():
            raise ContentUnavailable("未进入预期作者主页")
        bio = self.page.locator('[data-testid="UserDescription"]').first
        if bio.count() and bio.is_visible():
            self.phase("阅读作者简介")
            bio.inner_text(timeout=self.timeout(1500))
            self.m.sleep(2)
        self.read_feed(2)
        return "作者简介与近期动态阅读完成"

    def following(self) -> str:
        self.ensure_home()
        self.phase("定位并切换关注信息流")
        tab = self.page.get_by_role("tab", name=following_name_pattern()).first
        try:
            tab.wait_for(state="visible", timeout=self.timeout(5000))
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            raise ContentUnavailable("当前页面未提供可识别的关注页签（支持中英、葡语、西语等）")
        if not self.tab_selected(tab):
            self.click(tab)
            self.wait_tab_selected(tab)
        self.read_feed(2)
        return "关注信息流阅读完成"

    def search(self) -> str:
        if not self.m.cfg.interest_terms:
            raise ContentUnavailable("没有预设搜索关键词")
        term = self.plan.rng.choice(self.m.cfg.interest_terms)
        self.phase(f"搜索预设主题：{term}")
        self.navigator.goto(
            "https://x.com/search?" + urlencode({"q": term, "src": "typed_query", "f": "live"})
        )
        self.read_feed(2)
        return f"主题搜索阅读完成：{term}"

    def notifications(self) -> str:
        self.phase("查看已有通知")
        self.navigator.goto("https://x.com/notifications")
        cells = self.page.locator('[data-testid="notification"], [data-testid="cellInnerDiv"]')
        try:
            cells.first.wait_for(state="visible", timeout=self.timeout(3500))
        except Exception:
            self.gate()
            self.check_health()
            raise ContentUnavailable("没有可见通知或通知尚未加载")
        read_count = 0
        target_url = None
        for index in range(min(cells.count(), 6)):
            self.gate()
            cell = cells.nth(index)
            if not cell.is_visible():
                continue
            text = cell.inner_text(timeout=self.timeout(1500))
            if not text.strip():
                continue
            # 阅读不等于回复；不保存通知正文，不点击关注/回复按钮。
            self.m.sleep(min(5.0, max(1.0, len(text) / 40)))
            read_count += 1
            links = cell.locator('a[href*="/status/"]')
            if target_url is None and links.count():
                target_url = canonical_status_url(
                    links.first.get_attribute("href", timeout=self.timeout(1500)) or ""
                )
            if read_count >= 3:
                break
        if target_url:
            self.phase("查看通知关联帖子")
            self.navigator.goto(target_url)
            art = self.require_article(include_seen=True)
            self.read(art, allow_like=False)
        if read_count == 0:
            raise ContentUnavailable("没有可读通知")
        self.m.stats["notifications_read"] += read_count
        return f"阅读 {read_count} 条已有通知"

    def revisit(self) -> str:
        entries = self.m.journal.pending()
        if not entries:
            raise ContentUnavailable("没有未读完的历史帖子")
        url, entry = entries[0]
        self.m.journal.mark_revisit(url)
        self.phase("继续未完成阅读")
        self.navigator.goto(url)
        position = entry.get("thread_scroll", 0) if entry.get("thread_pending") else entry.get("scroll", 0)
        self.page.evaluate("y => window.scrollTo(0, y)", max(0.0, float(position)))
        if entry.get("thread_pending"):
            if not self.m.cfg.enable_deep_visit:
                raise ContentUnavailable("评论阅读已关闭，保留未完成讨论")
            count = self.read_discussion(url)
            if count == 0:
                raise ContentUnavailable("历史讨论没有可见的新回复")
            return f"已继续阅读历史讨论的 {count} 条回复"
        expected_id = urlparse(url).path.split("/status/")[-1]
        art = self.require_article(
            lambda art, _text: (self.status_url(art) or "").endswith("/status/" + expected_id),
            include_seen=True,
        )
        self.read(art, deep=True, allow_like=False)
        return "已继续并完成历史阅读"

    def casual_exit(self) -> str:
        self.ensure_home()
        # 空信息流也会结束会话，但不能把“没有阅读”记成完成浏览。
        self.read_feed(1)
        return "短暂浏览后结束"


# ======================================================================
# 模块：xmanager/scenes_extra.py
# ======================================================================
"""V8 扩展目录：分派、条件探测与扩展阅读处理器。"""


import json
import re
from urllib.parse import urlencode, urlparse



class ExtraScenesMixin:
    # ---------- V8：目录分派、能力检查与可核实的阅读路径 ----------
    def execute_workflow(self, key):
        spec = WORKFLOW_BY_KEY[key]
        if spec.manual_only:
            raise ContentUnavailable("手动项不允许进入自动执行器")
        if not spec.handler:
            return getattr(self, key)()
        handler = getattr(self, "extra_" + spec.handler, None)
        if handler is None:
            raise RuntimeError("工作流缺少处理器：" + key)
        self.phase(spec.label)
        return handler(spec.arg)

    def trigger_condition(self, key):
        """只检查已呈现的DOM，不为探测功能点击、导航或修改账号状态。"""
        if self.plan.items[key]['tier'] != 'conditional':
            return None
        selectors = {
            'gif_read': 'video[loop]:visible, [data-testid="gifPlayer"]:visible',
            'video_review': 'video:visible',
            'image_alt': '[data-testid="tweetPhoto"] img[alt]:visible',
            'notes_read': '[data-testid="birdwatch-pivot"]:visible, [data-testid="communityNote"]:visible, [data-testid="birdwatch-note"]:visible',
            'poll_read': '[data-testid="cardPoll"]:visible, [data-testid="poll"]:visible, [data-testid^="pollOption"]:visible',
            'live_read': 'a[href*="/i/broadcasts/"]:visible, [data-testid="liveVideoPlayer"]:visible',
            'spaces_read': 'a[href*="/i/spaces/"]:visible',
            'articles_read': 'a[href*="/i/article/"]:visible, a[href*="/i/articles/"]:visible',
        }
        selector = selectors.get(key)
        if selector and not self.page.locator(selector).count():
            return '当前可见内容未提供对应媒体或功能入口'
        return None

    def candidate_link(self, scope, predicate, requested_ms=4000):
        """一轮DOM快照读取链接，不对重绘中的nth索引逐个等待。"""

        def collect():
            rows = scope.locator('a[href]').evaluate_all('''els => els.filter(e => {
                const s=getComputedStyle(e);return e.getClientRects().length && s.visibility!=='hidden' && s.display!=='none';
            }).map(e => ({href:e.getAttribute('href')||'',url:e.href||''}))''')
            found = {}
            for row in rows:
                url = row['url']
                href = row['href']
                if urlparse(url).scheme in ('http', 'https') and predicate(url):
                    found.setdefault(url, href)
            if not found:
                return None
            url = self.plan.rng.choice(list(found))
            node = scope.locator('a[href=' + json.dumps(found[url], ensure_ascii=False) + ']:visible').first
            return (node, url) if node.count() else None

        result = self.poll(collect, requested_ms)
        if result is None:
            raise ContentUnavailable("页面已等待，但没有此功能的可见入口")
        return result

    def open_observed(self, pattern, scope=None):
        rx = re.compile(pattern, re.I)
        node, url = self.candidate_link(
            scope if scope is not None else self.page,
            lambda u: is_x_url(u) and bool(rx.search(urlparse(u).path)),
        )
        # 按href重新定位后只点击一次，导航慢时等待URL，不重复点击。
        self.click(node)
        arrived = self.poll(
            lambda: is_x_url(self.page.url) and bool(rx.search(urlparse(self.page.url).path)), 6500
        )
        if not arrived:
            raise PageNotReady("入口已点击，目标功能页尚未完成跳转")
        self.check_health()
        return url

    def primary(self):
        selectors = (
            '[data-testid="sheetDialog"]:visible',
            '[role="dialog"][aria-modal="true"]:visible',
            '[data-testid="settingsDetail"]:visible',
            '[data-testid="primaryColumn"]:visible',
            'main:visible',
            '[role="main"]:visible',
            '[role="dialog"]:visible',
        )

        def find():
            for selector in selectors:
                node = self.page.locator(selector).first
                if node.count():
                    return node
            return None

        node = self.poll(find, 7000)
        if node is None:
            raise PageNotReady("页面主内容尚未就绪，稍后重新尝试")
        return node

    def read_blocks(self, scope, selector=None, limit=3):
        blocks = scope.locator(selector) if selector else scope

        # 文本和可见状态在同一次浏览器求值中读取，不保存消息/通知正文。
        def snapshot():
            return blocks.evaluate_all('''els=>els.filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')
                .map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,20)''')

        texts = self.poll(snapshot, 6500)
        if not texts:
            if self.page.locator('[role="progressbar"]:visible, [aria-busy="true"]:visible').count():
                raise PageNotReady("主内容仍在加载，稍后重新尝试")
            raise ContentUnavailable("功能页已等待，但没有可读内容")
        count = 0
        fingerprints = set()
        handles = blocks.element_handles()
        try:
            for current in handles[:20]:
                self.gate()
                try:
                    # 临时绑定同一DOM节点，只用于阅读；不把动态nth重新解释成其他内容。
                    if (
                        not current.evaluate('e=>e.isConnected && e.getClientRects().length>0')
                        or not current.is_visible()
                    ):
                        continue
                    text = current.inner_text().strip()
                    if not text or text in fingerprints:
                        continue
                    current.scroll_into_view_if_needed(timeout=self.timeout(1500))
                except (
                    StopRequested,
                    DurationReached,
                    SceneBudgetExceeded,
                    CdpStateError,
                    AccountStateError,
                ):
                    raise
                except Exception:
                    self.gate()
                    continue
                fingerprints.add(text)
                self.m.sleep(self.plan.rng.uniform(0.7, 1.3) * min(6, max(1, len(text) / 45)))
                count += 1
                if count >= limit:
                    break
        finally:
            for handle in handles:
                try:
                    handle.dispose()
                except Exception:
                    logger.debug("阅读节点释放失败", exc_info=True)
        if not count:
            raise PageNotReady("阅读内容在重绘中消失，稍后重新尝试")
        return count

    def read_any_posts(self, count=2):
        ready = self.poll(lambda: self.page.locator(SELECTORS['tweet'] + ':visible').count(), 8000)
        if not ready:
            if self.page.locator('[role="progressbar"]:visible, [aria-busy="true"]:visible').count():
                raise PageNotReady("帖子列表仍在加载")
            raise ContentUnavailable("等待后仍没有可见帖子")
        completed = 0
        local_seen = set()
        for _ in range(count):
            art = self.pick_article(
                lambda a, t: self.status_url(a) not in local_seen, include_seen=True, rounds=2
            )
            if art is None:
                break
            url = self.status_url(art)
            try:
                self.read(art, allow_like=False)
            except ContentUnavailable:
                # 某条被虚拟列表回收只跳过该候选，不把整个列表立即判为空。
                local_seen.add(url)
                continue
            local_seen.add(url)
            completed += 1
            self.scroll(self.plan.rng.randint(180, 430))
        if not completed:
            raise ContentUnavailable("可见帖子已变化，当前没有可读候选")
        return completed

    def detail_source(self):
        self.ensure_home()
        art = self.require_article(include_seen=True)
        url = self.open_detail(art)
        return url, self.article_by_url(url)

    def extra_detail(self, arg):
        url, art = self.detail_source()
        self.read(art, deep=True, allow_like=False)
        return "已核实目标ID并完成详情阅读，结束后恢复来源"

    def extra_recent(self, arg):
        entries = list(self.m.journal.entries.items())
        if not entries:
            raise ContentUnavailable("没有可重访的阅读记录")
        url, _ = self.plan.rng.choice(entries[-25:])
        if not canonical_status_url(url):
            raise ContentUnavailable("历史内容没有稳定帖子ID")
        self.navigator.goto(url)
        self.read(self.article_by_url(url), deep=True, allow_like=False)
        return "已重访阅读记录中的同一帖子"

    def extra_backtrack(self, arg):
        self.ensure_home()
        self.scroll(self.plan.rng.randint(380, 900))
        self.m.behavior.scroll(self.page, self.plan.rng.randint(180, 450), -1)
        self.m.sleep(self.plan.rng.uniform(0.6, 1.8))
        self.read_any_posts(1)
        return "下滚后向上回看并阅读可见内容"

    def extra_refresh(self, arg):
        self.ensure_home()
        self.page.reload(wait_until="domcontentloaded", timeout=self.timeout(12000))
        self.check_health()
        self.read_any_posts(1)
        return "首页刷新后已核实可读内容"

    def extra_translate(self, arg):
        self.ensure_home()
        art = self.require_article(
            lambda a, t: (
                a.locator('[data-testid="translate"]:visible').count() > 0
                or a.get_by_role(
                    "button",
                    name=re.compile(
                        r"^(Translate post|Translate|翻译推文|翻译帖子|翻译|Traduzir post|Traduzir|Traducir post)$",
                        re.I,
                    ),
                ).count()
                > 0
            ),
            include_seen=True,
        )
        before = art.inner_text(timeout=self.timeout(1500))
        button = art.locator('[data-testid="translate"]:visible').first
        if not button.count():
            button = art.get_by_role(
                "button",
                name=re.compile(
                    r"^(Translate post|Translate|翻译推文|翻译帖子|翻译|Traduzir post|Traduzir|Traducir post)$",
                    re.I,
                ),
            ).first
        self.click(button)
        for _ in range(10):
            self.m.sleep(0.25)
            if art.inner_text(timeout=self.timeout(1000)) != before:
                self.read(art, deep=True, allow_like=False)
                return "翻译入口已点击并确认内容发生变化"
        raise ContentUnavailable("译文未确认出现，未记为完成")

    def extra_thread(self, arg):
        url, art = self.detail_source()
        self.read(art, deep=True, allow_like=False)
        count = self.read_discussion(url, self.plan.rng.randint(2, 4))
        if not count:
            raise ContentUnavailable("主帖可读，但没有可见上下文或回复")
        return f"主帖及{count}条上下文阅读完成（不推断均属作者线程）"

    def extra_reply_branch(self, arg):
        root, art = self.detail_source()
        self.read(art, allow_like=False)
        reply = self.pick_article(lambda a, t: self.status_url(a) != root, include_seen=True, rounds=2)
        if reply is None:
            raise ContentUnavailable("没有可展开的其他回复")
        target = self.open_detail(reply)
        self.read(self.article_by_url(target), deep=True, allow_like=False)
        count = self.read_discussion(target, 2)
        self.navigator.goto(root)
        self.article_by_url(root)
        return f"已进入回复分支并返回原帖，新增阅读{count}条；未把目标回复当原帖"

    def extra_quote(self, arg):
        self.ensure_home()

        def quoted(a, t):
            own = self.status_url(a)
            return any(
                canonical_status_url(v.get_attribute("href", timeout=self.timeout(800)) or "")
                not in (None, own)
                for v in [
                    a.locator('a[href*="/status/"]').nth(i)
                    for i in range(min(a.locator('a[href*="/status/"]').count(), 10))
                ]
            )

        art = self.require_article(quoted, include_seen=True)
        own = self.status_url(art)
        self.read(art, allow_like=False)
        _, url = self.candidate_link(
            art, lambda u: is_x_url(u) and canonical_status_url(u) not in (None, own)
        )
        url = canonical_status_url(url)
        self.navigator.goto(url)
        self.read(self.article_by_url(url), deep=True, allow_like=False)
        return "已阅读不同ID的关联原帖；仅按可验证链接识别关联关系"

    def extra_post_link(self, arg):
        self.ensure_home()
        selector = '[data-testid="tweetText"] a[href]:visible'

        def matches(u):
            path = urlparse(u).path
            return is_x_url(u) and (
                path.startswith('/hashtag/')
                if arg == 'hashtag'
                else bool(re.fullmatch(r'/[A-Za-z0-9_]{1,15}', path))
            )

        art = self.require_article(
            lambda a, t: any(
                matches(("https://x.com" + h) if h.startswith('/') else h)
                for h in a.locator(selector).evaluate_all('(els)=>els.map(e=>e.getAttribute("href")||"")')
            ),
            include_seen=True,
        )
        _, url = self.candidate_link(art.locator('[data-testid="tweetText"]'), matches)
        self.navigator.goto(url)
        if arg == 'hashtag':
            self.read_any_posts(2)
        else:
            self.read_blocks(self.primary(), '[data-testid="UserDescription"]:visible', 1)
        return "正文链接延伸阅读完成：" + arg

    def extra_external(self, arg):
        self.ensure_home()
        art = self.require_article(
            lambda a, t: (
                a.locator(
                    '[data-testid="card.wrapper"] a[href], [data-testid="tweetText"] a[href^="http"]'
                ).count()
                > 0
            ),
            include_seen=True,
        )
        _, url = self.candidate_link(
            art, lambda u: urlparse(u).scheme in ('http', 'https') and not is_x_url(u)
        )
        # 工作流结束时由统一导航器恢复来源；全程不创建新标签。
        self.page.goto(url, wait_until="domcontentloaded", timeout=self.timeout(12000))
        self.gate()
        if urlparse(self.page.url).scheme not in ('http', 'https'):
            raise ContentUnavailable("站外链接没有到达网页")
        text = self.page.locator('body').inner_text(timeout=self.timeout(2500)).strip()
        if len(text) < 40:
            raise ContentUnavailable("站外网页没有足够可读内容")
        self.m.sleep(self.plan.rng.uniform(3, 8))
        return "已在当前标签阅读站外网页，结束后返回来源"

    def extra_image_alt(self, arg):
        self.ensure_home()
        art = self.require_article(
            lambda a, t: a.locator('[data-testid="tweetPhoto"] img[alt]').count() > 0, include_seen=True
        )
        descriptions = art.locator('[data-testid="tweetPhoto"] img').evaluate_all(
            '(els)=>els.map(e=>e.alt||"").filter(t=>t.trim()&&!/^(image|photo|图像|图片)$/i.test(t.trim()))'
        )
        if not descriptions:
            raise ContentUnavailable("图片存在，但没有可读的自定义ALT说明")
        self.m.sleep(min(8, max(2, sum(map(len, descriptions)) / 35)))
        return f"阅读{len(descriptions)}条图片说明"

    def extra_gif(self, arg):
        self.ensure_home()
        art = self.require_article(
            lambda a, t: a.locator('video[loop], [data-testid="gifPlayer"]').count() > 0, include_seen=True
        )
        self.read(art, allow_like=False)
        media = art.locator('video').first
        if media.count():
            before = self.video_state(media)
            media.evaluate('v=>{v.muted=true; return v.play().then(()=>true).catch(()=>false)}')
            self.m.sleep(self.plan.rng.uniform(2, 5))
            after = self.video_state(media)
            if before['time'] == after['time']:
                raise ContentUnavailable("GIF媒体没有实际播放进度")
        else:
            self.read_blocks(art, limit=1)
        return "GIF可见内容阅读完成"

    def extra_video_review(self, arg):
        self.ensure_home()
        art = self.require_article(lambda a, t: a.locator('video').count() > 0, include_seen=True)
        video = art.locator('video').first
        before = self.video_state(video)
        if before.get('error'):
            raise ContentUnavailable("视频加载错误")
        started = video.evaluate('v=>{v.muted=true;return v.play().then(()=>true).catch(()=>false)}')
        if not started:
            raise ContentUnavailable("视频没有获准播放")
        try:
            self.m.sleep(self.plan.rng.uniform(2, 4))
            state = self.video_state(video)
            if state['time'] == before['time']:
                raise ContentUnavailable("视频播放进度未变化")
            video.evaluate('v=>v.pause()')
            self.m.sleep(self.plan.rng.uniform(0.4, 1.1))
            if state['duration'] > 5:
                video.evaluate(
                    '(v,delta)=>{v.currentTime=Math.max(0,v.currentTime-delta)}', self.plan.rng.uniform(1, 3)
                )
            resumed = video.evaluate('v=>v.play().then(()=>true).catch(()=>false)')
            if not resumed:
                raise ContentUnavailable("暂停后恢复播放失败")
            self.m.sleep(self.plan.rng.uniform(1, 3))
            return "视频实际播放、暂停与恢复已核实"
        finally:
            # 离开时恢复原有暂停状态，不留下新开启的后台播放。
            if before.get('paused'):
                try:
                    video.evaluate('v=>v.pause()')
                except Exception:
                    logger.debug("恢复视频暂停状态失败", exc_info=True)

    def extra_search_mode(self, arg):
        if not self.m.cfg.interest_terms:
            raise ContentUnavailable("没有搜索关键词")
        term = self.plan.rng.choice(self.m.cfg.interest_terms)
        params = {'q': ('"' + term.replace('"', '') + '"') if arg == 'exact' else term, 'src': 'typed_query'}
        if arg not in ('top', 'exact'):
            params['f'] = arg
        self.navigator.goto('https://x.com/search?' + urlencode(params))
        if arg == 'user':
            count = self.read_blocks(
                self.primary(), '[data-testid="UserCell"]:visible', self.plan.rng.randint(1, 3)
            )
        else:
            if arg == 'image':
                self.require_article(
                    lambda a, t: a.locator(SELECTORS['photo']).count() > 0, include_seen=True
                )
            if arg == 'video':
                self.require_article(
                    lambda a, t: a.locator('video, [data-testid="videoPlayer"]').count() > 0,
                    include_seen=True,
                )
            count = self.read_any_posts(self.plan.rng.randint(1, 2))
        return f"{arg}搜索已读{count}项，关键词：{term}"

    def extra_search_history(self, arg):
        self.ensure_home()
        box = self.page.locator('[data-testid="SearchBox_Search_Input"]:visible').first
        if not box.count():
            raise ContentUnavailable("没有搜索框入口")
        self.click(box)
        try:
            count = self.read_blocks(
                self.page, '[role="listbox"]:visible, [data-testid="typeaheadDropdown"]:visible', 1
            )
            return f"已查看{count}个搜索建议或历史面板；未修改记录"
        finally:
            self.page.keyboard.press('Escape')

    SURFACES = {
        'explore': ('/explore', r'^/explore(?:/|$)'),
        'bookmarks': ('/i/bookmarks', r'^/i/bookmarks(?:/|$)'),
        'lists': (None, r'^/(?:i/lists|[A-Za-z0-9_]+/lists)(?:/|$)'),
        'history': (None, r'^/(?:i/)?history(?:/|$)'),
        'communities': (None, r'^/(?:i/)?communities(?:/|$)'),
        'grok': (None, r'^/i/grok(?:/|$)'),
        'settings': ('/settings', r'^/settings(?:/|$)'),
        'security': (
            '/settings/security_and_account_access',
            r'^/settings/security_and_account_access(?:/|$)',
        ),
        'account': ('/settings/account', r'^/settings/account(?:/|$)'),
        'accessibility': (
            '/settings/accessibility_display_and_languages',
            r'^/settings/accessibility_display_and_languages(?:/|$)',
        ),
        'privacy': ('/settings/privacy_and_safety', r'^/settings/privacy_and_safety(?:/|$)'),
        'premium': (None, r'^/(?:i/)?(?:premium|premium_sign_up|verified-choose)(?:/|$)'),
        'creator': (None, r'^/(?:i/)?(?:monetization|creator|creator-studio)(?:/|$)'),
    }

    def goto_surface(self, arg):
        previous = self.capabilities.get(arg, {})
        if previous.get('state') == 'unavailable':
            raise FeatureUnavailable(arg, previous['reason'])
        direct, pattern = self.SURFACES[arg]
        if direct:
            self.navigator.goto('https://x.com' + direct)
            if not self.poll(lambda: bool(re.search(pattern, urlparse(self.page.url).path, re.I)), 4500):
                raise PageNotReady("功能页跳转尚未完成")
        else:
            # 先等当前界面完成挂载；侧栏收起时尝试可见的导航“更多”菜单。
            self.primary()
            try:
                self.open_observed(pattern)
            except ContentUnavailable as exc:
                if isinstance(exc, PageNotReady):
                    raise
                more = self.page.locator(
                    'nav [data-testid="AppTabBar_More_Menu"]:visible, nav [aria-label="More menu items"]:visible, nav [aria-label="更多菜单项"]:visible'
                ).first
                if not more.count():
                    raise FeatureUnavailable(arg, "当前账号已加载的导航未提供此功能入口") from exc
                self.click(more)
                try:
                    self.open_observed(pattern)
                except ContentUnavailable as second:
                    if isinstance(second, PageNotReady):
                        raise
                    raise FeatureUnavailable(arg, "侧栏及更多菜单均未提供此功能入口") from second
                finally:
                    self.page.keyboard.press('Escape')
        scope = self.primary()
        if self.page.locator('input[type="password"]:visible').count():
            raise FeatureUnavailable(arg, "此入口要求重新验证身份，保留给用户手动处理")
        self.capabilities[arg] = {'state': 'available', 'elapsed': round(self.m.clock.elapsed(), 2)}
        return scope

    def extra_surface(self, arg):
        scope = self.goto_surface(arg)
        if arg == 'bookmarks':
            count = self.read_any_posts(2)
        elif arg == 'history':
            try:
                count = self.read_any_posts(2)
            except PageNotReady:
                raise
            except ContentUnavailable:
                count = self.read_blocks(
                    scope,
                    'a[href*="/status/"]:visible, a[href*="/i/article/"]:visible, a[href*="/i/articles/"]:visible',
                    2,
                )
        else:
            count = self.read_blocks(scope, limit=1)
        return f"{arg}已读{count}项；未修改设置或提交内容"

    def extra_trend(self, arg):
        scope = self.goto_surface('explore')
        self.open_observed(r'^/search$', scope)
        count = self.read_any_posts(2)
        return f"从探索页进入实际趋势链接，阅读{count}条"

    def extra_custom_timeline(self, arg):
        self.ensure_home()
        tabs = self.page.locator('[role="tab"]:visible')
        choices = []
        standard = re.compile(
            r'^(For you|Following|为你推荐|推荐|正在关注|关注|Para você|Seguindo|Para ti|Siguiendo)$', re.I
        )
        for i in range(tabs.count()):
            node = tabs.nth(i)
            text = node.inner_text(timeout=self.timeout(1000)).strip()
            if text and not standard.fullmatch(text):
                choices.append(node)
        if not choices:
            raise ContentUnavailable("没有额外固定的信息流标签")
        tab = self.plan.rng.choice(choices)
        self.click(tab)
        self.wait_tab_selected(tab)
        count = self.read_any_posts(2)
        return f"自定义信息流已读{count}条"

    def author_page(self):
        self.ensure_home()
        art = self.require_article(include_seen=True)
        _, url = self.candidate_link(
            art.locator('[data-testid="User-Name"]'),
            lambda u: is_x_url(u) and bool(re.fullmatch(r'/[A-Za-z0-9_]{1,15}', urlparse(u).path)),
        )
        self.navigator.goto(url)
        self.primary()
        return urlparse(url).path.rstrip('/')

    def extra_profile_tab(self, arg):
        author = self.author_page()
        suffix = r'(?:followers|verified_followers)' if arg == 'followers' else re.escape(arg)
        self.open_observed('^' + re.escape(author) + '/' + suffix + r'/?$')
        if arg in ('following', 'followers'):
            count = self.read_blocks(
                self.primary(), '[data-testid="UserCell"]:visible', self.plan.rng.randint(1, 3)
            )
        elif arg == 'articles':
            count = self.read_blocks(
                self.primary(), '[data-testid="cellInnerDiv"]:visible, article:visible', 2
            )
        else:
            count = self.read_any_posts(2)
        return f"作者{arg}标签已读{count}项"

    def extra_collection(self, arg):
        scope = self.goto_surface(arg)
        pattern = r'^/i/lists/[0-9]+/?$' if arg == 'lists' else r'^/i/communities/[0-9]+/?$'
        self.open_observed(pattern, scope)
        count = self.read_any_posts(self.plan.rng.randint(1, 3))
        return f"已进入实际{arg}并阅读{count}条；未修改成员关系"

    def extra_community_rules(self, arg):
        scope = self.goto_surface('communities')
        self.open_observed(r'^/i/communities/[0-9]+/?$', scope)
        rules = self.page.locator(
            '[data-testid="communityRules"]:visible, [data-testid="communityDescription"]:visible'
        ).first
        if rules.count():
            self.read_blocks(rules, limit=1)
            return "已读取社群规则或简介"
        about = self.page.get_by_role(
            'tab', name=re.compile(r'^(About|关于|简介|Sobre|Información)$', re.I)
        ).first
        if not about.count():
            raise ContentUnavailable("社群没有可识别的规则或简介入口")
        self.click(about)
        self.read_blocks(self.primary(), limit=1)
        return "已打开社群简介标签，未加入或申请"

    def extra_mentions(self, arg):
        self.navigator.goto('https://x.com/notifications/mentions')
        count = self.read_any_posts(2)
        self.m.stats['notifications_read'] += count
        return f"已阅读{count}条提及内容"

    def extra_own_profile(self, arg):
        link = self.page.locator('[data-testid="AppTabBar_Profile_Link"]:visible').first
        if not link.count():
            raise ContentUnavailable("没有当前账号的主页入口")
        href = link.get_attribute('href', timeout=self.timeout(1200)) or ''
        if not re.fullmatch(r'/[A-Za-z0-9_]{1,15}', href):
            raise ContentUnavailable("自己的主页链接未确认")
        self.navigator.goto('https://x.com' + href)
        count = self.read_any_posts(2)
        return f"当前账号主页已读{count}条，未编辑或删除"

    def extra_messages(self, arg):
        self.navigator.goto('https://x.com/messages')
        scope = self.primary()
        rows = scope.locator(
            '[data-testid="conversation"]:visible, [data-testid="conversationEntry"]:visible'
        )
        if not rows.count():
            raise ContentUnavailable("没有可识别的已有会话；不自动注册Chat或输入PIN")
        row = rows.nth(self.plan.rng.randrange(min(rows.count(), 8)))
        self.click(row)
        count = self.read_blocks(
            self.primary(), '[data-testid="messageEntry"]:visible, [data-testid="message"]:visible', 3
        )
        return f"已有会话已读{count}项（可能改变已读回执），未发送消息"

    def extra_linked_surface(self, arg):
        pattern = r'^/i/spaces/[A-Za-z0-9]+' if arg == 'spaces' else r'^/(?:i/)?articles?(?:/|$)'
        self.ensure_home()
        self.open_observed(pattern)
        # Space只读卡片和详情，不点击加入、申请发言或麦克风。
        count = self.read_blocks(self.primary(), limit=1)
        return f"{arg}实际入口与内容已读{count}项；未提交或加入"

    def extra_live(self, arg):
        self.ensure_home()
        art = self.require_article(
            lambda a, t: a.locator('a[href*="/i/broadcasts/"], [data-testid="liveVideoPlayer"]').count() > 0,
            include_seen=True,
        )
        if art.locator('a[href*="/i/broadcasts/"]').count():
            self.open_observed(r'^/i/broadcasts/', art)
        video = self.page.locator('video:visible').first
        if not video.count():
            raise ContentUnavailable("直播入口存在，但没有可见播放器")
        before = self.video_state(video)
        self.m.sleep(self.plan.rng.uniform(3, 6))
        after = self.video_state(video)
        if before['time'] == after['time']:
            raise ContentUnavailable("直播或回放没有实际播放进度")
        return "直播或回放的可见播放进度已核实"

    def extra_notes(self, arg):
        self.ensure_home()
        selector = '[data-testid="birdwatch-pivot"]:visible, [data-testid="communityNote"]:visible, [data-testid="birdwatch-note"]:visible'
        art = self.require_article(lambda a, t: a.locator(selector).count() > 0, include_seen=True)
        count = self.read_blocks(art, selector, 1)
        return f"已读{count}个可见社区附注；未撰写或评分"

    def extra_poll(self, arg):
        self.ensure_home()
        selector = '[data-testid="cardPoll"]:visible, [data-testid="poll"]:visible, [data-testid^="pollOption"]:visible'
        art = self.require_article(lambda a, t: a.locator(selector).count() > 0, include_seen=True)
        self.read_blocks(art, selector, 1)
        return "已阅读投票选项或公开结果，未投票"

    def inspect_menu(self, kind):
        self.ensure_home()
        art = self.require_article(include_seen=True)
        if kind == 'post':
            button = art.locator('[data-testid="caret"]:visible').first
        else:
            button = art.get_by_role(
                'button',
                name=re.compile(
                    r'^(Share post|Share|分享帖子|分享推文|分享|Compartilhar post|Compartilhar|Compartir post|Compartir)$',
                    re.I,
                ),
            ).first
        if not button.count():
            raise ContentUnavailable("没有可识别的菜单按钮")
        self.click(button)
        try:
            self.read_blocks(self.page, '[role="menu"]:visible', 1)
            return "菜单选项已读，未点击任何修改或发送项"
        finally:
            self.page.keyboard.press('Escape')

    def extra_post_menu(self, arg):
        return self.inspect_menu('post')

    def extra_share_menu(self, arg):
        return self.inspect_menu('share')

    def extra_like(self, arg):
        if not self.m.can_like():
            raise ContentUnavailable("点赞开关、次数上限或间隔条件不满足")
        self.ensure_home()
        art = self.require_article()
        self.read(art, allow_like=False)
        before = self.m.stats['likes']
        self.confirmed_like(art)
        if self.m.stats['likes'] <= before:
            raise ContentUnavailable("点赞未确认成功，不重复点击")
        return "已读帖子点赞成功并核实按钮状态"

    def extra_comment(self, arg):
        if not self.m.cfg.comment_enabled:
            raise ContentUnavailable("未启用TXT评论")
        before = self.m.stats.get('comments_sent', 0)
        self.ensure_home()
        art = self.require_article()
        self.read(art, allow_like=False)
        self.maybe_comment()
        if self.m.stats.get('comments_sent', 0) <= before:
            reason = self.m.stats.get('comment_status', {})
            raise ContentUnavailable("评论未确认新增：" + str(reason.get('state', '等待配额或间隔')))
        return "TXT评论已确认发布，沿用跨账号目标和文本全局去重"


# ======================================================================
# 模块：xmanager/executor.py
# ======================================================================
"""工作流执行器：调度主循环、开局 / 收尾采集与场景间隙服务。"""




class WorkflowExecutor(ExecutorBase, CoreScenesMixin, ExtraScenesMixin):
    """把基础能力、原版场景与扩展场景组合成完整执行器。"""

    def feature_family(self, spec):
        if spec.handler in ('surface', 'collection'):
            return spec.arg
        if spec.handler == 'community_rules':
            return 'communities'
        return None

    def retire_feature(self, family, reason):
        self.capabilities[family] = {
            'state': 'unavailable',
            'reason': reason,
            'elapsed': round(self.m.clock.elapsed(), 2),
        }
        for spec in WORKFLOW_SPECS:
            item = self.plan.items[spec.key]
            if (
                self.feature_family(spec) == family
                and item['state'] != 'RUNNING'
                and item['attempts'] < item['target']
            ):
                self.plan.retire(spec.key, reason, 'UNAVAILABLE')

    def prune_completed_actions(self):
        item = self.plan.items.get('comment_dispatch')
        if item and item['attempts'] < item['target']:
            if self.m.comment_attempts >= self.m.cfg.comment_count:
                self.plan.retire('comment_dispatch', '评论配额已完成；无需再次触发', 'SATISFIED')
            elif self.m.comment_halted:
                self.plan.retire('comment_dispatch', '评论已暂停，阅读继续', 'SATISFIED')
        item = self.plan.items.get('like_read_post')
        if item and item['attempts'] < item['target'] and self.m.like_attempts >= self.m.cfg.max_likes:
            self.plan.retire('like_read_post', '点赞尝试上限已达到', 'SATISFIED')

    def diagnose_wait(self):
        """只记录布局计数，不采集正文、消息、表单或凭据。"""
        try:
            state = self.page.evaluate('''()=>{
                const count=s=>[...document.querySelectorAll(s)].filter(e=>e.getClientRects().length>0).length;
                return {path:location.pathname,ready:document.readyState,
                    primary:count('[data-testid="primaryColumn"]'),main:count('main,[role="main"]'),
                    dialog:count('[role="dialog"],[data-testid="sheetDialog"]'),
                    loading:count('[role="progressbar"],[aria-busy="true"]'),posts:count('[data-testid="tweet"]')};
            }''')
            records = self.m.stats.setdefault('page_wait_diagnostics', [])
            records.append(state)
            del records[:-12]
            self.m.log(f"页面等待诊断：{state}")
        except Exception:
            logger.debug("页面等待诊断不可用", exc_info=True)

    # ---------- V9：开局/收尾采集、场景间隙发送面板回复 ----------
    COLLECT_GRACE = 90.0  # 采集临时多给的秒数；采集用掉的时间不占单号阅读时长

    def service_step(self, label, fn):
        """执行一个采集/回复步骤：普通故障只记日志，停止/断连/登录失效照常向上抛。"""
        try:
            return fn()
        except FATAL_ERRORS:
            raise
        except SceneBudgetExceeded:
            self.m.log(f"{label}：时间预算用尽，已保存读到的部分。")
        except ContentUnavailable as exc:
            self.m.log(f"{label}：{exc}")
        except PlaywrightTimeoutError as exc:
            self.m.log(f"{label}超时：{short_error(exc)}")
        except Exception as exc:
            logger.warning("%s失败", label, exc_info=True)
            self.m.log(f"{label}失败：{short_error(exc)}")

    def _service(self, stage, collect, dispatch, blocking):
        m = self.m
        grace_before = m.grace_sec
        m.grace_sec = grace_before + self.COLLECT_GRACE
        started = m.clock.elapsed()
        try:
            if getattr(m.cfg,'recent_action_batch',''):
                result=RecentInteractionRunner(self).run()
                m.stats['recent_action_result']=result.value
                return
            if m.cfg.performance_only:
                m.set_stage("collect_end" if stage=="end" else "collect_start")
                self.service_step("8小时帖子与回复统计",lambda:collect_recent_activity(AccountCollector(self)))
                return
            dispatcher = OutboxDispatcher(self)
            if dispatch and dispatcher.pending():
                m.set_stage("outbox")
                self.service_step("发送面板回复", lambda: dispatcher.run(blocking=blocking))
            if collect:
                m.set_stage("collect_end" if stage == "end" else "collect_start")
                self.service_step("采集账号数据", lambda: AccountCollector(self).run(stage))
        finally:
            m.grace_sec = grace_before + max(0.0, m.clock.elapsed() - started)
            m.last_service_at = m.clock.elapsed()

    def guarded_service(self, stage):
        try:
            self._service(stage, self.m.cfg.stats_enabled, True, stage != "end")
            return None
        except StopRequested:
            return Result.STOPPED
        except (DurationReached, SceneBudgetExceeded):
            return None
        except CdpStateError:
            return Result.CDP_LOST
        except AccountStateError as exc:
            return exc.result

    def between_scenes(self):
        m, cfg = self.m, self.m.cfg
        now = m.clock.elapsed()
        if now - m.last_service_check < 20:
            return
        m.last_service_check = now
        dispatcher = OutboxDispatcher(self)
        dispatch = dispatcher.pending() > 0 and dispatcher.wait_needed() <= 0 and not dispatcher.capped()
        collect = bool(
            cfg.stats_enabled
            and cfg.stats_interval_min > 0
            and now - m.last_service_at >= cfg.stats_interval_min * 60
            and m.remaining() > 150
        )
        if not (dispatch or collect):
            return
        self._service("periodic", collect, dispatch, False)
        m.set_stage("workflows")
        self.service_step("返回首页", lambda: self.navigator.goto(TWITTER_HOME_URL))

    def run_service(self) -> Result:
        """“立即同步”模式：只采集数据并发送面板里排队的回复，然后结束。"""
        m, cfg = self.m, self.m.cfg
        self.persist()
        m.set_stage("login")
        try:
            self.check_health()
            self._service("service", cfg.stats_enabled, True, True)
        except StopRequested:
            return Result.STOPPED
        except DurationReached:
            return Result.OK
        except SceneBudgetExceeded:
            return Result.PARTIAL
        except CdpStateError:
            return Result.CDP_LOST
        except AccountStateError as exc:
            return exc.result
        except ContentUnavailable as exc:
            m.log(f"页面异常，同步中止：{exc}")
            return Result.ERROR
        m.set_stage("close")
        return Result(m.stats.get('recent_action_result',Result.PLAN_DONE.value))

    def run(self) -> Result:
        m, cfg = self.m, self.m.cfg
        self.persist()
        m.set_stage("login")
        if not m.stats.get("start_service_done"):  # 重连后不重复做开局采集
            m.stats["start_service_done"] = True
            early = self.guarded_service("start")
            if early is not None:
                return early
        m.set_stage("workflows")
        result = self._run_core()
        if (
            cfg.stats_enabled
            and not m.stats.get("end_service_done")
            and result in (Result.OK, Result.PLAN_DONE, Result.NO_CONTENT, Result.PARTIAL)
        ):
            m.stats["end_service_done"] = True
            final = self.guarded_service("end")
            if final is not None:
                return final
        return result

    def _run_core(self) -> Result:
        self.persist()
        while self.m.remaining() > 0:
            try:
                self.gate()
                self.check_health()
                self.prune_completed_actions()
                self.between_scenes()
                key = self.plan.choose(self.m.remaining(), self.m.clock.elapsed())
                if key is None:
                    delay = self.plan.next_ready_delay(self.m.remaining(), self.m.clock.elapsed())
                    if delay is not None and delay + 2 < self.m.remaining():
                        self.m.workflow_name = "等待触发条件"
                        self.m.workflow_phase = f"最近冷却剩余 {delay:.1f}秒"
                        self.m.sleep(min(max(0.15, delay), 1.5))
                        continue
                    self.m.stats["end_reason"] = "配额已结束或剩余预算不足启动下一场景"
                    break
                condition = self.trigger_condition(key)
                if condition:
                    item = self.plan.items[key]
                    item['condition_misses'] = item.get('condition_misses', 0) + 1
                    if item['condition_misses'] >= 2:
                        item['unspent_target'] = item['target'] - item['attempts']
                        item['target'] = item['attempts']
                        item['state'] = 'NO_TRIGGER'
                        item['last_reason'] = condition + '；两轮探测未满足，本会话保留为未触发'
                    else:
                        self.plan.defer(
                            key, condition, self.m.clock.elapsed() + self.plan.rng.uniform(25, 80)
                        )
                    self.m.log(f"工作流 {WORKFLOW_BY_KEY[key].label} 未触发：{condition}")
                    self.persist()
                    continue
                self.current_key = key
                spec = WORKFLOW_BY_KEY[key]
                self.plan.begin(key)
                self.m.scene_deadline = self.m.clock.elapsed() + min(spec.budget_sec, self.m.remaining())
                self.m.workflow_name = spec.label
                self.plan.items[key]["source_url"] = self.page.url
                self.plan.items[key]["started_at"] = round(self.m.clock.elapsed(), 2)
                self.m.log(
                    f"工作流 [{self.plan.items[key]['tier_label']}] {spec.label} 开始：第 {self.plan.items[key]['attempts']}/{self.plan.items[key]['target']} 次"
                )
                self.persist()
                outcome, reason = "failed", "未完成"
                snapshot = None
                fatal = None
                unavailable_family = None
                try:
                    snapshot = self.navigator.capture()
                    reason = self.execute_workflow(key)
                    outcome = "completed"
                except FeatureUnavailable as exc:
                    outcome, reason = "skipped", str(exc)
                    unavailable_family = exc.family
                except PageNotReady as exc:
                    outcome, reason = "deferred", str(exc)
                    self.diagnose_wait()
                except ContentUnavailable as exc:
                    outcome, reason = "skipped", str(exc)
                except SceneBudgetExceeded:
                    outcome, reason = "interrupted", "单场景预算已用尽"
                except (
                    StopRequested,
                    DurationReached,
                    AccountStateError,
                    CdpStateError,
                ) as exc:
                    outcome, reason, fatal = "interrupted", type(exc).__name__, exc
                except Exception as exc:
                    if not self.m.cdp_alive():
                        outcome, reason, fatal = (
                            "interrupted",
                            "CDP 断开",
                            CdpStateError("CDP 断开"),
                        )
                    elif isinstance(exc, PlaywrightTimeoutError) and key not in (
                        "comment_dispatch",
                        "like_read_post",
                    ):
                        outcome, reason = "deferred", "页面加载或控件重绘超时，有限暂缓：" + short_error(exc)
                        self.diagnose_wait()
                    else:
                        reason = short_error(exc)
                        logger.warning("场景执行失败: %s", key, exc_info=True)
                finally:
                    self.m.scene_deadline = None
                    primary_outcome, primary_reason = outcome, reason
                    item = self.plan.items[key]
                    item["primary_outcome"], item["primary_reason"] = outcome, reason
                    item["restore_error"] = ""
                    # 当前页普通故障不阻止返回；验证/登录/停止/断连仍立即退出。
                    if fatal is None and snapshot is not None and self.m.remaining() > 1:
                        self.m.scene_deadline = self.m.clock.elapsed() + min(15, self.m.remaining())
                        try:
                            self.phase("返回来源页面")
                            self.navigator.restore(snapshot)
                            self.m.stats["consecutive_return_failures"] = 0
                        except (
                            StopRequested,
                            DurationReached,
                            AccountStateError,
                            CdpStateError,
                        ) as exc:
                            fatal = exc
                            outcome, reason = (
                                "interrupted",
                                f"返回中断：{type(exc).__name__}",
                            )
                        except SceneBudgetExceeded:
                            outcome, reason = (
                                "interrupted",
                                f"原始{primary_outcome}：{primary_reason}；返回来源页的预算已用尽",
                            )
                        except Exception as exc:
                            error = short_error(exc)
                            item["restore_error"] = error
                            logger.warning(
                                "场景%s返回失败；原始结果=%s；原始原因=%s；当前URL=%s",
                                key,
                                primary_outcome,
                                primary_reason,
                                self.page.url,
                                exc_info=True,
                            )
                            recovered = False
                            try:
                                self.navigator.goto(TWITTER_HOME_URL)
                                recovered = True
                                self.m.log(
                                    f"来源页恢复未完成，已回到首页。原始结果：{primary_outcome}，{primary_reason}"
                                )
                            except (
                                StopRequested,
                                DurationReached,
                                AccountStateError,
                                CdpStateError,
                            ) as recovery_error:
                                fatal = recovery_error
                            except Exception:
                                logger.debug("返回首页兜底失败", exc_info=True)
                            if recovered:
                                outcome, reason = (
                                    primary_outcome,
                                    primary_reason + f"；来源页恢复异常，已回首页（{error}）",
                                )
                                self.m.stats["consecutive_return_failures"] = 0
                            else:
                                outcome, reason = (
                                    "failed",
                                    f"原始{primary_outcome}：{primary_reason}；返回失败：{error}",
                                )
                                failures = self.m.stats.get("consecutive_return_failures", 0) + 1
                                self.m.stats["consecutive_return_failures"] = failures
                                if failures >= 2 and fatal is None:
                                    self.m.log("连续两次无法恢复页面，结束该账号，避免反复消耗场景配额。")
                                    fatal = AccountStateError(Result.ERROR)
                        finally:
                            self.m.scene_deadline = None
                    self.plan.items[key]["ended_at"] = round(self.m.clock.elapsed(), 2)
                    self.plan.items[key]["restored_url"] = self.page.url
                    self.plan.finish(key, outcome, reason, self.m.clock.elapsed())
                    if unavailable_family:
                        self.retire_feature(unavailable_family, reason)
                    self.m.log(f"工作流 {spec.label}：{outcome}，{reason}")
                    self.persist()
                if fatal is not None:
                    raise fatal
                if self.m.cfg.comment_enabled:
                    self.maybe_comment()
                if (
                    key == "casual_exit"
                    and self.plan.items[key]["attempts"] >= self.plan.items[key]["target"]
                ):
                    self.m.stats["end_reason"] = reason
                    break
                self.m.sleep(self.plan.rng.uniform(0.3, 1.4))
            except ContentUnavailable as exc:
                recoveries = self.m.stats.get("page_recoveries", 0) + 1
                self.m.stats["page_recoveries"] = recoveries
                if recoveries > MAX_RELOADS:
                    self.m.log(f"页面多次恢复失败：{exc}")
                    return Result.ERROR
                self.m.log(f"页面异常，第 {recoveries}/{MAX_RELOADS} 次返回首页并等待。")
                try:
                    self.page.goto(
                        TWITTER_HOME_URL,
                        wait_until="domcontentloaded",
                        timeout=self.timeout(10000),
                    )
                    self.m.sleep(min(15, 2**recoveries))
                except DurationReached:
                    return Result.OK
                except StopRequested:
                    return Result.STOPPED
                except CdpStateError:
                    return Result.CDP_LOST
                except AccountStateError as state_error:
                    return state_error.result
                except Exception:
                    logger.debug("恢复首页未完成", exc_info=True)
            except DurationReached:
                self.m.stats["end_reason"] = "总时长预算已用尽"
                return Result.OK
            except StopRequested:
                return Result.STOPPED
            except CdpStateError:
                return Result.CDP_LOST
            except AccountStateError as exc:
                return exc.result
            finally:
                self.m.scene_deadline = None
        summary = self.plan.summary()
        if not summary["completed"]:
            return Result.NO_CONTENT if not summary["failed"] else Result.ERROR
        if summary["failed"]:
            return Result.PARTIAL
        return Result.PLAN_DONE


# ======================================================================
# 模块：xmanager/human.py
# ======================================================================
"""可中断的分段指针轨迹与滚动。"""


import math
import random
from collections import OrderedDict



class HumanBehaviorEngine:
    """可中断的分段指针轨迹。仅用于交互体验，不推断平台风控或账号权重。"""

    def __init__(self, checkpoint=None, rng=None):
        self.checkpoint = checkpoint or (lambda: None)
        self.rng = rng if rng is not None else random.Random()
        self.last = (0, 0)
        self.positions = OrderedDict()

    @staticmethod
    def cubic_bezier(p0, p1, p2, p3, t):
        return tuple(
            (1 - t) ** 3 * p0[k] + 3 * (1 - t) ** 2 * t * p1[k] + 3 * (1 - t) * t * t * p2[k] + t**3 * p3[k]
            for k in (0, 1)
        )

    @staticmethod
    def bounds(page):
        value = page.evaluate("() => ({width:innerWidth,height:innerHeight})")
        return max(1, int(value["width"])), max(1, int(value["height"]))

    def trajectory(self, start, target, width, height, steps=None):
        """返回(x,y,秒)；随机分段、双向曲率、不同加减速，终点精确且不出视口。"""
        r = self.rng
        clamp = lambda x, y: (max(0.0, min(width - 1.0, x)), max(0.0, min(height - 1.0, y)))
        sx, sy = clamp(*start)
        tx, ty = clamp(*target)
        dx, dy = tx - sx, ty - sy
        distance = math.hypot(dx, dy)
        if distance < 0.5:
            return [(tx, ty, 0.0)]
        count = max(5, min(42, int(steps) if steps else int(distance / r.uniform(14, 27)) + r.randint(5, 11)))
        bend = min(distance * 0.22, 100) * r.uniform(-1, 1)
        nx, ny = -dy / distance, dx / distance
        p1 = (sx + dx * r.uniform(0.18, 0.42) + nx * bend, sy + dy * r.uniform(0.18, 0.42) + ny * bend)
        p2 = (
            sx + dx * r.uniform(0.58, 0.88) - nx * bend * r.uniform(0.2, 1.0),
            sy + dy * r.uniform(0.58, 0.88) - ny * bend * r.uniform(0.2, 1.0),
        )
        knots = sorted(r.uniform(0.01, 0.99) for _ in range(count - 1)) + [1.0]
        shape = r.choice(("ease", "accelerate", "decelerate", "linear"))
        total = max(0.09, min(0.85, distance / r.uniform(800, 1700) + r.uniform(0.04, 0.16)))
        weights = [r.uniform(0.35, 1.8) for _ in knots]
        if count > 8 and r.random() < 0.32:
            weights[r.randrange(2, count - 2)] *= r.uniform(2, 4)
        scale = total / sum(weights)
        path = []
        for t, w in zip(knots, weights):
            u = (
                t * t * (3 - 2 * t)
                if shape == "ease"
                else t**1.35
                if shape == "accelerate"
                else 1 - (1 - t) ** 1.35
                if shape == "decelerate"
                else t
            )
            x, y = self.cubic_bezier((sx, sy), p1, p2, (tx, ty), u)
            # 偏移随接近目标消退；不是每次都插入抖动或停顿。
            if shape != "linear":
                x += r.uniform(-0.6, 0.6) * (1 - u)
                y += r.uniform(-0.6, 0.6) * (1 - u)
            x, y = clamp(x, y)
            path.append((x, y, w * scale))
        path[-1] = (tx, ty, path[-1][2])
        return path

    def wait(self, page, seconds):
        left = max(0.0, seconds)
        while left > 0:
            self.checkpoint()
            part = min(0.025, left)
            page.wait_for_timeout(part * 1000)
            left -= part

    def move(self, page, tx, ty, steps=None):
        self.checkpoint()
        width, height = self.bounds(page)
        previous = self.positions.get(id(page))
        start = previous[1] if previous and previous[0] is page else (0, 0)
        for x, y, delay in self.trajectory(start, (tx, ty), width, height, steps):
            self.checkpoint()
            page.mouse.move(x, y)
            self.last = (x, y)
            self.positions[id(page)] = (page, self.last)
            self.wait(page, delay)
        if len(self.positions) > 12:
            self.positions.popitem(last=False)

    def click(self, page, locator, timeout=4000):
        self.checkpoint()
        locator.scroll_into_view_if_needed(timeout=timeout)
        box = locator.bounding_box(timeout=timeout)
        if not box or box["width"] <= 0 or box["height"] <= 0:
            raise ContentUnavailable("点击对象没有有效边界")
        width, height = self.bounds(page)
        left = max(box["x"] + 1, 0)
        right = min(box["x"] + box["width"] - 1, width - 1)
        top = max(box["y"] + 1, 0)
        bottom = min(box["y"] + box["height"] - 1, height - 1)
        if right < left or bottom < top:
            raise ContentUnavailable("点击对象不在可用视口内")
        x = left + (right - left) * self.rng.uniform(0.25, 0.75)
        y = top + (bottom - top) * self.rng.uniform(0.25, 0.75)
        self.move(page, x, y)
        self.checkpoint()
        # 由Locator最后复核遮挡、稳定性与目标身份，不使用force或裸坐标点击。
        locator.click(position={"x": x - box["x"], "y": y - box["y"]}, timeout=timeout)
        self.checkpoint()

    def scroll(self, page, distance, direction=1):
        self.checkpoint()
        distance = max(0, int(distance))
        sign = 1 if direction >= 0 else -1
        if not distance:
            return
        count = min(distance, self.rng.randint(3, 9))
        weights = [self.rng.uniform(0.3, 2.3) for _ in range(count)]
        total = sum(weights)
        used = 0
        for i, w in enumerate(weights):
            self.checkpoint()
            part = (
                distance - used
                if i == count - 1
                else min(distance - used, max(0, round(distance * w / total)))
            )
            if part:
                page.mouse.wheel(0, part * sign)
                used += part
                self.wait(page, self.rng.uniform(0.025, 0.13))


# ======================================================================
# 模块：xmanager/machine.py
# ======================================================================
"""单账号状态机：排队、启动、连接、重连与收尾。"""


import random
import sys
import time
from collections import OrderedDict
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import urlparse



class TwitterWarmupMachine:
    def __init__(self, browser_id: str, browser_name: str, cfg: WarmupConfig, ctl: RunControl):
        self.browser_id = browser_id
        self.browser_name = browser_name
        self.cfg = cfg
        self.ctl = ctl
        self.workflow_plan = WorkflowPlanner(cfg)
        self.journal = ReadingJournal(browser_id)
        self.scene_deadline: Optional[float] = None
        self.workflow_name = "等待工作流"
        self.workflow_phase = "准备"
        self.like_attempts = 0
        self.draft_sent = 0
        self.comment_candidates = OrderedDict()
        self.comment_attempts = 0
        self.comment_halted = False
        self.comment_prepare_failures = 0
        self.comment_retry_at = 0.0
        self.comment_skipped_targets = set()
        self.report_path = REPORT_DIR / f"{report_token(browser_id)}_{self.workflow_plan.session_id}.json"
        self.slot: Optional[int] = None
        self.run_started = 0.0
        self.clock = ActiveClock(ctl)
        self.behavior = HumanBehaviorEngine(self.checkpoint)
        self.stats: Dict[str, Any] = {
            "reads": 0,
            "likes": 0,
            "reconnects": 0,
            "like_attempts": 0,
            "like_unconfirmed": 0,
            "notifications_read": 0,
        }
        self.last_progress = 0.0
        self.last_like_at: Optional[float] = None
        self.seen: "OrderedDict[str, None]" = OrderedDict()
        self.selector_miss: Dict[str, int] = {}
        self._browser: Any = None
        self._layout_cdp = None
        self._layout_seen = -1
        self.conn_state = ConnState.CONNECTED
        # V9
        self.handle = ""
        self.grace_sec = 0.0
        self.stage = ""
        self.stage_log: List[Dict[str, Any]] = []
        self._persist_at = 0.0
        self.last_service_at = 0.0
        self.last_service_check = -999.0
        if cfg.service_mode:
            self.stats["mode"] = "service"

    def set_stage(self, name: str) -> None:
        """记录当前处在哪个流程阶段（界面“执行流程”页读取）。"""
        if self.stage == name:
            return
        self.stage = name
        self.stage_log.append({"stage": name, "at": round(self.clock.elapsed(), 1), "ts": time.time()})
        del self.stage_log[:-60]
        self.persist_workflow_plan(force=True)

    def log(self, text: str) -> None:
        slot = f"|S{self.slot + 1}" if self.slot is not None else ""
        self.ctl.log(f"[{self.browser_name}|{self.browser_id[:6]}{slot}] {text}")

    def status(self, text: str, tone: str = "info") -> None:
        self.ctl.set_status(self.browser_id, text, tone)

    def cdp_alive(self) -> bool:
        b = self._browser
        if b is None:
            return True
        try:
            return bool(b.is_connected())
        except (StopRequested, DurationReached, SceneBudgetExceeded):
            raise
        except Exception:
            return False

    def sync_window_layout(self, force=False):
        if self._layout_cdp is None or self.slot is None:
            return
        version, mode, bounds = self.ctl.window_order.snapshot(self.slot)
        if not force and version == self._layout_seen:
            return
        self._layout_seen = version
        try:
            BitBrowserController.apply_window_bounds(self._layout_cdp, bounds)
            self.ctl.window_order.relayout_native()
        except Exception:
            logger.warning("窗口重排未完成，保留当前任务", exc_info=True)

    def checkpoint(self) -> None:
        self._pause_gate()
        self.sync_window_layout()
        if self.clock.started is not None and self.remaining() <= 0:
            raise DurationReached()
        self.check_scene_budget()

    def check_scene_budget(self) -> None:
        if self.scene_deadline is not None and self.clock.elapsed() >= self.scene_deadline:
            raise SceneBudgetExceeded()

    def persist_workflow_plan(self, force: bool = False) -> None:
        # 每个阶段都会调用；平时最多 1.5 秒写一次，避免 fsync 拖慢浏览器线程
        now = time.monotonic()
        if not force and now - self._persist_at < 1.5:
            return
        self._persist_at = now
        try:
            snapshot = self.workflow_plan.snapshot()
            self.stats["workflow_plan"] = snapshot
            atomic_json(
                self.report_path,
                {
                    "version": APP_VERSION,
                    "browser_id": self.browser_id,
                    "name": self.browser_name,
                    "handle": self.handle,
                    "mode": "service"
                    if self.cfg.service_mode
                    else ("post" if self.cfg.draft_enabled else "read"),
                    "stage": self.stage,
                    "stage_log": self.stage_log,
                    "updated_at": time.time(),
                    "active_sec": round(self.clock.elapsed(), 2),
                    "plan": snapshot,
                },
            )
        except OSError:
            logger.warning("写入工作流报告失败", exc_info=True)

    def _pause_gate(self) -> Tuple[bool, float]:
        was_paused = not self.ctl.pause_event.is_set()
        if was_paused:
            self.status("已暂停", "warn")
        before = self.ctl.paused_seconds()
        while not self.ctl.pause_event.wait(SLEEP_SLICE):
            if self.ctl.is_stopped():
                raise StopRequested()
        if self.ctl.is_stopped():
            raise StopRequested()
        if was_paused and self.clock.started is not None:
            self.last_progress = 0
            self.progress()
        return True, max(0.0, self.ctl.paused_seconds() - before)

    def wait_if_paused(self) -> bool:
        return self._pause_gate()[0]

    def remaining(self) -> float:
        # grace_sec：采集/回复用掉的时间不占单号阅读时长
        return max(0.0, self.cfg.duration_budget_sec + self.grace_sec - self.clock.elapsed())

    def sleep(self, seconds: float) -> bool:
        # 即使旧动作忘记检查返回值，停止仍能通过异常逐层退出。
        end = time.monotonic() + max(0.0, seconds)
        while True:
            _, paused = self._pause_gate()
            self.sync_window_layout()
            end += paused
            if self.clock.started is not None and self.remaining() <= 0:
                raise DurationReached()
            self.check_scene_budget()
            if self.clock.started is not None:
                self.progress()
            remain = end - time.monotonic()
            if remain <= 0:
                return True
            if self.ctl.stop_event.wait(min(SLEEP_SLICE, remain)):
                raise StopRequested()

    def progress(self) -> None:
        now = time.monotonic()
        if now - self.last_progress >= 1:
            self.last_progress = now
            self.status(
                (
                    f"TXT 发推 {self.draft_sent}/{self.cfg.draft_count}·{self.workflow_phase}"
                    if self.cfg.draft_enabled
                    else f"{self.workflow_name}·{self.workflow_phase}"
                )
                + (" | 不限时" if self.cfg.duration_min == 0 else f" | 剩余 {self.remaining() / 60:.1f}分"),
                "run",
            )

    def miss(self, key: str) -> int:
        self.selector_miss[key] = self.selector_miss.get(key, 0) + 1
        return self.selector_miss[key]

    def tweet_key(self, art) -> Optional[str]:
        try:
            return art.locator(SELECTORS["status_link"]).first.get_attribute("href", timeout=800)
        except (StopRequested, DurationReached, SceneBudgetExceeded):
            raise
        except Exception:
            return None

    def mark_seen(self, key: str) -> bool:
        if key in self.seen:
            return True
        self.seen[key] = None
        if len(self.seen) > SEEN_LIMIT:
            for _ in range(SEEN_LIMIT // 2):
                self.seen.popitem(last=False)
        return False

    def can_like(self) -> bool:
        return (
            self.cfg.enable_like
            and max(self.like_attempts, self.stats["likes"]) < self.cfg.max_likes
            and (
                self.last_like_at is None
                or time.monotonic() - self.last_like_at >= self.cfg.min_like_interval
            )
        )

    def warmup_loop(self, page: Page) -> Result:
        if self.cfg.service_mode:
            return WorkflowExecutor(self, page).run_service()
        if self.cfg.draft_enabled:
            return DraftPublisher(self, page).run()
        result = WorkflowExecutor(self, page).run()
        if (self.comment_halted or self.stats.get("comments_unknown", 0)) and result in SUCCESS_RESULTS:
            return Result.PARTIAL
        return result

    def attach_and_run(self, endpoint: str, bounds: Dict[str, int]) -> Result:
        sess = PlaywrightSession()
        try:
            sess.start()
            try:
                browser, _ctx, page, _cdp = BitBrowserController.connect_and_arrange(
                    sess, endpoint, bounds, self.cfg.lite_mode, self.ctl.stop_event
                )
            except StopRequested:
                return Result.STOPPED
            except DurationReached:
                raise
            except Exception as e:
                if self.ctl.is_stopped():
                    return Result.STOPPED
                self.log(f"CDP 连接失败: {e}")
                return Result.CDP_LOST

            self._browser = browser
            self._layout_cdp = sess.cdp
            self._layout_seen = -1
            pid = None
            if sys.platform == "win32":
                try:
                    pid = self.ctl.bit.browser_pid(self.browser_id)
                except Exception:
                    logger.debug("查询窗口PID失败", exc_info=True)
            self.ctl.window_order.register(self.browser_id, self.slot, pid)
            self.sync_window_layout(force=True)
            if sess.layout_applied:
                self.log("窗口布局指令已应用，CDP 控制链路就绪。")
                actual = sess.actual_bounds
                if actual and any(abs(actual.get(key, value) - value) > 4 for key, value in bounds.items()):
                    self.log(f"实际窗口范围 {actual} 与目标 {bounds} 有差异，请检查桌面缩放或窗口限制。")
            else:
                self.log("CDP 已连接，但窗口布局未确认，请查看日志中的布局错误。")

            self.status("加载首页", "run")

            if not is_x_url(page.url or "") or urlparse(page.url).path.rstrip("/") != "/home":
                try:
                    page.goto(TWITTER_HOME_URL, wait_until="commit", timeout=T(35000))
                except (StopRequested, DurationReached, SceneBudgetExceeded):
                    raise
                except Exception:
                    pass
            if not self.run_started:
                self.run_started = time.monotonic()
            self.clock.resume()
            if (
                not self.cfg.draft_enabled
                and not self.cfg.service_mode
                and self.stats.get("plan_logged") is not True
            ):
                self.stats["plan_logged"] = True
                self.log(
                    "本次工作流偏移："
                    + "; ".join(
                        f"{item['label']} {item['base']}次 {item['offset_pct']:+d}% → {item['target']}次"
                        + (f"（{item['disabled_reason']}）" if item["disabled_reason"] else "")
                        for item in self.workflow_plan.items.values()
                    )
                )
            self.status("运行中", "run")
            if not self.sleep(random.uniform(2.0, 3.5)):
                return Result.STOPPED

            result = self.warmup_loop(page)
            if result in SUCCESS_RESULTS:
                self.log(f"会话结束：{RESULT_LABEL[result]}，有效执行 {self.clock.elapsed() / 60:.1f} 分钟。")
            return result
        except DurationReached:
            if self.cfg.draft_enabled and self.draft_sent < self.cfg.draft_count:
                self.log("达到单号总时长，发推数量未完成；下批继续未发送条目。")
                return Result.PARTIAL
            return Result.OK
        except StopRequested:
            return Result.STOPPED
        finally:
            self.clock.suspend()
            self._layout_cdp = None
            self._browser = None
            sess.close()

    def session(self, endpoint: str, bounds: Dict[str, int], rec: LaunchRecord) -> Result:
        reconnects = 0
        while True:
            if self.run_started and self.remaining() <= 0:
                return Result.OK
            attached_at = time.monotonic()
            result = self.attach_and_run(endpoint, bounds)
            if result != Result.CDP_LOST:
                return result
            if self.ctl.is_stopped():
                return Result.STOPPED
            if time.monotonic() - attached_at > RECONNECT_RESET_SEC:
                reconnects = 0

            self.stats["reconnects"] += 1
            endpoint = None
            while endpoint is None:
                reconnects += 1
                if reconnects > MAX_RECONNECTS:
                    self.log(f"CDP 连续 {MAX_RECONNECTS} 次重连失败, 终止该账号。")
                    return Result.CDP_LOST
                wait = min(30, 5 * reconnects)
                self.status(f"重连中({reconnects}/{MAX_RECONNECTS})", "warn")
                self.log(f"CDP 断连, {wait}s 后第 {reconnects}/{MAX_RECONNECTS} 次重连...")
                if not self.sleep(wait):
                    return Result.STOPPED
                try:
                    endpoint = self.ctl.bit.ensure_browser_running(
                        self.browser_id, bounds, self.ctl, rec, self.log
                    )
                except StopRequested:
                    return Result.STOPPED
                except DurationReached:
                    raise
                except Exception as e:
                    self.log(f"重连获取端口失败: {e}")
                    endpoint = None

    def run(self) -> Tuple[Result, float]:
        self.status("排队中", "info")
        slot = (
            self.ctl.slots.acquire(lambda: self.ctl.should_abort_queue(self.browser_id))
            if self.ctl.wait_queue_ready(self.browser_id)
            else None
        )
        if slot is None:
            self.ctl.take_pending(self.browser_id)
            result = Result.STOPPED if self.ctl.is_stopped() else Result.CANCELLED
            self.status(RESULT_LABEL[result], RESULT_TONE[result])
            return result, 0.0
        result, rec, require_close = Result.ERROR, None, False
        self.slot = slot
        try:
            while not self.ctl.claim_pending(self.browser_id):
                if not self.ctl.wait_queue_ready(self.browser_id):
                    result = Result.STOPPED if self.ctl.is_stopped() else Result.CANCELLED
                    return result, 0.0
            self.set_stage("launch")
            rec = self.ctl.begin_launch(self.browser_id)
            BatchStore.update(self.browser_id, "RUNNING")
            self.log(
                f"获得槽位 [{slot + 1}/{self.ctl.layout_count}: {ScreenLayoutManager.position_name(slot, self.ctl.layout_count, self.ctl.window_order.mode)}]"
            )
            self.status("启动中", "info")
            _, _, bounds = self.ctl.window_order.snapshot(slot)
            self.log(
                f"窗口位置 ({bounds['left']},{bounds['top']})，尺寸 {bounds['width']}×{bounds['height']}"
            )
            try:
                endpoint = self.ctl.bit.ensure_browser_running(
                    self.browser_id, bounds, self.ctl, rec, self.log
                )
            except (StopRequested, DurationReached, SceneBudgetExceeded):
                raise
            except Exception as exc:
                self.log(f"浏览器启动失败: {exc}")
                result = Result.LAUNCH_FAILED
            else:
                result = self.session(endpoint, bounds, rec)
        except StopRequested:
            result = Result.STOPPED
        except DurationReached:
            result = (
                Result.PARTIAL
                if self.cfg.draft_enabled and self.draft_sent < self.cfg.draft_count
                else Result.OK
            )
        except Exception as exc:
            result = Result.STOPPED if self.ctl.is_stopped() else Result.ERROR
            logger.exception("账号执行异常")
            try:
                self.log(f"账号执行异常: {exc}")
            except Exception:
                pass
        finally:
            # 资源释放不依赖日志、持久化、窗口管理器是否成功。
            try:
                if rec is not None:
                    require_close = (
                        self.cfg.close_after or result not in SUCCESS_RESULTS or self.ctl.is_stopped()
                    )
                    if require_close:
                        try:
                            closed = self.ctl.close_browser(self.browser_id, allow_reused=False, expected=rec)
                        except Exception:
                            closed = False
                            logger.exception("关窗操作异常")
                        with rec.cond:
                            unresolved = rec.launched_by_us and rec.state != BrowserCloseState.CLOSED
                        if unresolved:
                            require_close = True
                            if result in SUCCESS_RESULTS:
                                result = Result.ERROR
                            self.ctl.request_stop()
                            self.log("窗口关闭未确认，已保留记录并停止后续账号，后台将重试关窗。")
                        elif closed:
                            self.log("已自动关闭浏览器窗口。")
            finally:
                try:
                    try:
                        self.ctl.take_pending(self.browser_id)
                    finally:
                        if rec is not None:
                            self.ctl.end_launch(self.browser_id, expected=rec, require_close=require_close)
                finally:
                    self.ctl.slots.release(slot)
                    self.slot = None
            try:
                self.stats["workflow_plan"] = self.workflow_plan.snapshot()
                self.stats["end_result"] = result.value
                if self.cfg.comment_enabled and not self.cfg.draft_enabled:
                    self.log(
                        f"评论汇总：尝试 {self.comment_attempts}，成功 {self.stats.get('comments_sent', 0)}，待核对 {self.stats.get('comments_unknown', 0)}"
                    )
                self.set_stage("close")
                self.persist_workflow_plan(force=True)
                self.log(f"释放槽位 [{slot + 1}/{self.ctl.layout_count}], 状态: {RESULT_LABEL[result]}")
                self.status(RESULT_LABEL[result], RESULT_TONE[result])
            except Exception:
                logger.exception("账号结束信息写入失败，槽位已释放")
        active = min(self.cfg.duration_budget_sec + self.grace_sec, self.clock.elapsed())
        try:
            get_store().log_event(
                self.browser_id,
                self.browser_name,
                "run",
                f"{RESULT_LABEL[result]} · 有效 {active / 60:.1f} 分钟"
                + (" · 数据同步" if self.cfg.service_mode else ""),
            )
        except Exception:
            logger.debug("写入动态失败", exc_info=True)
        return result, active


# ======================================================================
# 模块：xmanager/batch.py
# ======================================================================
"""一批账号的线程池调度：与界面解耦，只通过回调汇报。"""


import concurrent.futures
import threading
import time
from typing import Any, Callable, Dict, List



def browser_id(item: Dict[str, Any]) -> str:
    return str(item.get("id") or item.get("browserId") or "")


def browser_name(item: Dict[str, Any]) -> str:
    return item.get("siteName") or item.get("name") or "未命名"


def mode_description(cfg: WarmupConfig) -> str:
    if cfg.recent_action_batch:return '8小时榜单转赞评'
    if cfg.performance_only:return '8小时只读统计'
    if cfg.service_mode:
        return "数据同步"
    if cfg.draft_enabled:
        return "TXT 发布"
    return "阅读及评论" if cfg.comment_enabled else "养号"


def has_reading_workflow(cfg):
    if cfg.service_mode or cfg.draft_enabled:
        return True
    for key,on,base in cfg.workflow_settings:
        spec=WORKFLOW_BY_KEY[key]
        if not on or base<=0 or spec.manual_only or workflow_tier(spec,cfg.workflow_tiers)=='manual':continue
        if key=='comment_dispatch' and not cfg.comment_enabled:continue
        if key=='like_read_post' and not cfg.enable_like:continue
        if (key in ('interest','search') or spec.handler=='search_mode') and not cfg.interest_terms:continue
        if not cfg.enable_deep_visit and key in ('comments','thread_read','reply_branch'):continue
        return True
    return False


def reading_start_failed(cfg,result,stats):
    return (not cfg.service_mode and not cfg.draft_enabled
            and int(stats.get('reads',0))==0
            and result not in (Result.STOPPED,Result.CANCELLED))


def order_by_collection_age(targets, collection_times, random_ties=False, rng=None):
    """未采集优先，其余按最后成功快照时间升序；同时间才允许打乱。"""
    items=list(targets)
    if random_ties:
        (rng or random).shuffle(items)
    def timestamp(item):
        bid=str(item.get('id') or item.get('browserId') or '')
        value=collection_times.get(bid)
        return float(value) if isinstance(value,(int,float)) and math.isfinite(value) and value>0 else 0.0
    return sorted(items,key=timestamp)


@dataclass
class ReadingCadence:
    primary_seconds: float = 0.0
    secondary_seconds: float = 0.0
    segment_seconds: float = 0.0
    segment_reads: int = 0
    extras: int = 0
    last_extra_at: float = -1000000000.0

    def record_reading(self, seconds, reads):
        self.primary_seconds+=max(0.0,seconds)
        self.segment_seconds+=max(0.0,seconds)
        self.segment_reads+=max(0,reads)

    def ready(self, remaining, cfg=None, now=None):
        p=reading_policy(cfg) if cfg is not None else dict(DEFAULT_READING_POLICY)
        now=self.primary_seconds+self.secondary_seconds if now is None else now
        return (remaining>=p['step_budget']+p['restore_budget'] and self.segment_seconds>=p['min_segment_seconds']
                and self.segment_reads>=p['min_segment_reads'] and now-self.last_extra_at>=p['side_cooldown']
                and self.secondary_seconds<=self.primary_seconds*p['max_secondary_ratio']/(1-p['max_secondary_ratio']))

    def finish_extra(self, seconds, now=None):
        self.secondary_seconds+=max(0.0,seconds)
        self.segment_seconds=0.0
        self.segment_reads=0
        self.extras+=1
        self.last_extra_at=self.primary_seconds+self.secondary_seconds if now is None else now


class ScoredWorkflowPlanner:
    """每账号每会话只抽样一次；重连沿用配额和执行记录。"""

    def __init__(self, cfg: WarmupConfig, rng=None):
        self.rng = rng if rng is not None else random.Random()
        self.session_id = uuid.uuid4().hex
        self.items: Dict[str, Dict[str, Any]] = {}
        self.last_elapsed = 0.0
        for key, enabled, base in cfg.workflow_settings:
            spec=WORKFLOW_BY_KEY[key]
            tier=workflow_tier(spec,cfg.workflow_tiers)
            amplitude = self.rng.randint(10, 60)
            offset = amplitude * self.rng.choice((-1, 1))
            raw_target = base * (1 + offset / 100.0)
            target = (
                max(1, int(math.floor(raw_target + 0.5))) if enabled and base > 0 else 0
            )
            reason = ""
            if spec.manual_only or tier=="manual":
                reason = "手动处理，不进入自动计划"
            elif not enabled or base == 0:
                reason = "用户禁用"
            elif key=="like_read_post" and not cfg.enable_like:
                reason = "未启用点赞"
            elif key=="comment_dispatch" and not cfg.comment_enabled:
                reason = "未启用TXT评论"
            elif not cfg.enable_deep_visit and key in ("comments", "thread_read", "reply_branch"):
                reason = "未允许深读评论"
            elif (key in ("interest", "search") or spec.handler=="search_mode") and not cfg.interest_terms:
                reason = "未配置兴趣关键词"
            if reason:
                target = 0
            self.items[key] = {
                "label": spec.label,
                "tier": tier,
                "tier_label": TIER_RULES[tier][0],
                "group": spec.group,
                "weight": TIER_RULES[tier][1],
                "defer_until": self.rng.uniform(*TIER_RULES[tier][3]) if target else 0.0,
                "unavailable_streak": 0,
                "base": base,
                "offset_pct": offset,
                "raw_target": round(raw_target, 3),
                "target": target,
                "attempts": 0,
                "completed": 0,
                "skipped": 0,
                "failed": 0,
                "interrupted": 0,
                "deferred": 0,
                "launches": 0,
                "state": "DISABLED" if reason else "PENDING",
                "disabled_reason": reason,
                "last_reason": "",
                "phase": "等待执行",
            }
        self.last_key: Optional[str] = None

    def pending(self, remaining):
        return [key for key,item in self.items.items()
                if item["attempts"]<item["target"] and WORKFLOW_BY_KEY[key].minimum_sec<=remaining]

    def available(self, remaining, elapsed=0):
        pending=self.pending(remaining)
        if any(k!="casual_exit" for k in pending):
            pending=[k for k in pending if k!="casual_exit"]
        return [k for k in pending if self.items[k].get("defer_until",0)<=elapsed]

    def next_ready_delay(self, remaining, elapsed):
        pending=self.pending(remaining)
        if any(k!="casual_exit" for k in pending):pending=[k for k in pending if k!="casual_exit"]
        if not pending:return None
        return max(0.0,min(self.items[k].get("defer_until",0) for k in pending)-elapsed)

    def choose(self, remaining, elapsed=0):
        self.last_elapsed=elapsed
        keys=self.available(remaining,elapsed)
        if not keys:return None
        weights=[]
        previous=self.items.get(self.last_key,{})
        for key in keys:
            item=self.items[key]
            weight=item["weight"]*math.sqrt(max(1,item["target"]-item["attempts"]))
            if item.get("context_url"):weight*=2.0
            if key==self.last_key:weight*=.12
            elif previous.get("group")==item.get("group"):weight*=.65
            weights.append(max(.001,weight))
        return self.rng.choices(keys,weights=weights,k=1)[0]

    def suggest(self, key: str, url: str) -> None:
        url = canonical_status_url(url)
        item = self.items.get(key)
        if url and item and item["attempts"] < item["target"]:
            item["context_url"] = url

    def defer(self, key: str, reason: str, until: float) -> None:
        item = self.items[key]
        if item["attempts"] < item["target"]:
            item["defer_until"] = until
            item["state"] = "DEFERRED"
            item["last_reason"] = reason
            item["phase"] = "等待内容条件"

    def begin(self, key: str) -> None:
        item = self.items[key]
        if item["state"] == "RUNNING" or item["attempts"] >= item["target"]:
            raise RuntimeError("工作流配额已用尽或正在运行")
        item["attempts"] += 1
        item["launches"] += 1
        item["state"] = "RUNNING"
        item["phase"] = "进入场景"
        self.last_key = key

    def finish(self, key: str, outcome: str, reason: str, elapsed=None) -> None:
        item = self.items[key]
        if item["state"] != "RUNNING":
            raise RuntimeError("工作流未处于执行状态")
        if outcome=="deferred":
            item["deferred"]+=1
            item["last_reason"]=str(reason)[:500]
            elapsed=self.last_elapsed if elapsed is None else elapsed
            if item["deferred"]<=2:
                item["attempts"]-=1
                item["state"]="DEFERRED"
                item["phase"]="页面未就绪，等待恢复"
                item["defer_until"]=elapsed+self.rng.uniform(12,35)
            else:
                item["skipped"]+=1
                self.retire(key,str(reason)+"；已到本会话暂缓重试上限","UNAVAILABLE")
            return
        if outcome not in ("completed", "skipped", "failed", "interrupted"):
            raise ValueError("未知工作流结果")
        item[outcome] += 1
        item["state"] = "DONE" if item["attempts"] >= item["target"] else "PENDING"
        item["last_reason"] = str(reason)[:500]
        item["phase"] = "已结束"
        elapsed=self.last_elapsed if elapsed is None else elapsed
        low,high=TIER_RULES[item["tier"]][2]
        item["defer_until"]=elapsed+self.rng.uniform(low,high)
        item["unavailable_streak"] = item["unavailable_streak"]+1 if outcome=="skipped" else 0
        if item["unavailable_streak"]>=2 and item["attempts"]<item["target"]:
            item["unspent_target"]=item["target"]-item["attempts"]
            item["target"]=item["attempts"]
            item["state"]="UNAVAILABLE"
            item["last_reason"]+="；连续两次缺少内容，本会话不再探测"

    def retire(self,key,reason,state="UNAVAILABLE"):
        item=self.items[key]
        item["unspent_target"]=item.get("unspent_target",0)+max(0,item["target"]-item["attempts"])
        item["target"]=item["attempts"]
        item["state"]=state
        item["phase"]="无需继续触发" if state=="SATISFIED" else "本会话不再探测"
        item["last_reason"]=str(reason)[:500]

    def summary(self) -> Dict[str, int]:
        return {
            field: sum(item[field] for item in self.items.values())
            for field in (
                "target",
                "attempts",
                "completed",
                "skipped",
                "failed",
                "interrupted",
                "deferred",
            )
        }

    def snapshot(self) -> Dict[str, Any]:
        return {
            "session_id": self.session_id,
            "summary": self.summary(),
            "workflows": json.loads(json.dumps(self.items, ensure_ascii=False)),
        }


class ScoredReadingJournal:
    """每账号隔离，只记录 URL、阅读进度和时间，不存正文或通知内容。"""

    def __init__(self, browser_id: str):
        token = hashlib.sha256(browser_id.encode("utf-8")).hexdigest()[:24]
        self.path = DATA_DIR / "reading" / f"{token}.json"
        self.entries: Dict[str, Dict[str, Any]] = {}
        try:
            if self.path.exists():
                data = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(data, dict):
                    self.entries = {
                        url: item
                        for url, item in data.items()
                        if canonical_status_url(url) == url and isinstance(item, dict)
                    }
        except (OSError, ValueError):
            logger.warning("读取阅读记录失败，保留原文件", exc_info=True)

    def remember(
        self, url: Optional[str], complete: bool, scroll: float = 0, reason: str = ""
    ) -> None:
        url = canonical_status_url(url) if url else None
        if not url:
            return
        previous = self.entries.get(url, {})
        # 已完成阅读不因后续“候选发现”被降级为未读。
        complete = bool(complete or previous.get("complete"))
        self.entries[url] = {
            "complete": complete,
            "scroll": max(0.0, float(scroll)),
            "updated_at": time.time(),
            "reason": reason[:120],
            "revisit_attempts": int(previous.get("revisit_attempts", 0)),
            "thread_pending": bool(previous.get("thread_pending", False)),
            "thread_scroll": previous.get("thread_scroll", 0),
        }
        if len(self.entries) > 300:
            ordered = sorted(
                self.entries,
                key=lambda item: self.entries[item].get("updated_at", 0),
                reverse=True,
            )
            self.entries = {item: self.entries[item] for item in ordered[:300]}
        self.flush()

    def pending(self) -> List[Tuple[str, Dict[str, Any]]]:
        return sorted(
            (
                (url, item)
                for url, item in self.entries.items()
                if (not item.get("complete") or item.get("thread_pending"))
                and item.get("revisit_attempts", 0) < 3
            ),
            key=lambda row: row[1].get("updated_at", 0),
            reverse=True,
        )

    def mark_revisit(self, url: str) -> None:
        if url in self.entries:
            self.entries[url]["revisit_attempts"] = (
                int(self.entries[url].get("revisit_attempts", 0)) + 1
            )
            self.flush()

    def discussion(self, url: str, pending: bool, scroll: float = 0) -> None:
        url = canonical_status_url(url)
        if not url:
            return
        if url not in self.entries:
            self.remember(url, False)
        self.entries[url]["thread_pending"] = pending
        self.entries[url]["thread_scroll"] = max(0.0, float(scroll))
        self.entries[url]["updated_at"] = time.time()
        self.flush()

    def flush(self) -> None:
        try:
            atomic_json(self.path, self.entries)
        except OSError:
            logger.warning("写入阅读记录失败", exc_info=True)


class ScoredSceneNavigator:
    def __init__(self, executor):
        self.e = executor
        self.page = executor.page

    def capture(self) -> NavigationSnapshot:
        try:
            scroll = float(self.page.evaluate("window.scrollY"))
        except Exception:
            scroll = 0.0
        anchor = None
        try:
            art = self.e.peek_article()
            if art is not None:
                anchor = self.e.status_url(art)
        except (StopRequested, DurationReached, SceneBudgetExceeded, AccountStateError):
            raise
        except Exception:
            logger.debug("读取返回锚点失败", exc_info=True)
        feed_tab = None
        if urlparse(self.page.url or "").path.rstrip("/") == "/home":
            selected = self.page.locator('[role="tab"][aria-selected="true"]').first
            try:
                if selected.count():
                    feed_tab = (
                        selected.inner_text(timeout=self.e.timeout(1000)).strip()
                        or None
                    )
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("读取原信息流标签失败", exc_info=True)
        return NavigationSnapshot(
            self.page.url or TWITTER_HOME_URL, scroll, anchor, feed_tab
        )

    def goto(self, url: str) -> None:
        self.e.gate()
        if self.e._chain_navigation_count is not None and not getattr(self.e,'_restoring',False) and not same_x_route(self.page.url or '',url):
            if self.e._chain_navigation_count>=reading_policy(self.e.m.cfg)['max_crosspage_steps']:
                raise SceneBudgetExceeded()
            self.e._chain_navigation_count+=1
        if not is_x_url(url):
            raise ValueError("场景导航仅允许 X/Twitter 地址")
        try:
            self.page.goto(url,wait_until="domcontentloaded",timeout=self.e.timeout(15000))
        except PlaywrightTimeoutError as exc:
            self.e.gate()
            # DOMContentLoaded超时但目标地址已到达时，继续由具体内容条件验证。
            if not same_x_route(self.page.url or '',url):
                raise PageNotReady("页面导航超时，稍后重试；未重复点击或提交") from exc
        self.e.gate()
        self.e.check_health()

    def restore(self, snapshot: NavigationSnapshot) -> None:
        self.e.gate()
        self.e.check_health(ignore_page_error=True)
        target = snapshot.url if is_x_url(snapshot.url) else TWITTER_HOME_URL
        if not same_x_route(self.page.url or "", target):
            try:
                self.page.go_back(
                    wait_until="domcontentloaded", timeout=self.e.timeout(3500)
                )
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("历史返回未成功，将直接打开来源页", exc_info=True)
            self.e.gate()
            self.e.check_health(ignore_page_error=True)
        if (
            not same_x_route(self.page.url or "", target)
            or check_page_health(self.page) == "error_page"
        ):
            self.goto(target)
        else:
            self.e.check_health()
        if not same_x_route(self.page.url or "", target):
            raise ContentUnavailable(f"来源页未恢复：{self.page.url}")
        if snapshot.feed_tab:
            tab = self.page.get_by_role(
                "tab",
                name=re.compile(
                    r"^\s*" + re.escape(snapshot.feed_tab.strip()) + r"\s*$", re.I
                ),
            ).first
            if tab.count() and tab.is_visible() and not self.e.tab_selected(tab):
                self.e.click(tab)
                self.e.wait_tab_selected(tab)
        self.page.evaluate("y => window.scrollTo(0, y)", max(0.0, snapshot.scroll))
        # 锚点消失只丢弃精确滚动位置，不把来源页成功恢复误记为场景失败。
        if snapshot.anchor:
            try:
                anchor = self.e.article_by_url(snapshot.anchor, wait=False)
                if anchor.count() and anchor.is_visible():
                    anchor.scroll_into_view_if_needed(timeout=self.e.timeout(1800))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception:
                logger.debug("来源内容已被虚拟列表回收，保留大致位置", exc_info=True)
        self.e.gate()


class ScoredWorkflowExecutor:
    def __init__(self, machine: "TwitterWarmupMachine", page: Page):
        self.m = machine
        self.page = page
        self.plan = machine.workflow_plan
        self.navigator = ScoredSceneNavigator(self)
        self.current_key: Optional[str] = None
        self._article_urls: OrderedDict = OrderedDict()
        self.commenter = None
        self._bound_entry=None
        self._chain_navigation_count=None
        self.capabilities=getattr(machine,"capabilities",{})
        machine.capabilities=self.capabilities

    def maybe_comment(self):
        if self.m.cfg.comment_enabled:
            if self.commenter is None:
                self.commenter = ScoredCommentPublisher(self)
            self.commenter.maybe_comment()

    def gate(self) -> None:
        self.m.checkpoint()
        if not self.m.cdp_alive():
            raise CdpStateError("CDP 已断开")
        if self.page.is_closed():
            raise AccountStateError(Result.PAGE_CLOSED)

    def timeout(self, requested_ms: int = 4000) -> int:
        self.gate()
        scene_left = (
            self.m.scene_deadline - self.m.clock.elapsed()
            if self.m.scene_deadline is not None
            else self.m.remaining()
        )
        return max(
            1, int(min(requested_ms, self.m.remaining() * 1000, scene_left * 1000))
        )

    def phase(self, text: str) -> None:
        self.gate()
        self.m.workflow_phase = text
        if self.current_key:
            item=self.plan.items[self.current_key]
            item["phase"] = text
            trace=item.setdefault("phase_trace",[])
            trace.append({"phase":text,"elapsed":round(self.m.clock.elapsed(),2),"url":self.page.url})
            del trace[:-20]
        self.m.last_progress = 0
        self.m.progress()
        self.persist()

    def check_health(self, ignore_page_error: bool = False) -> None:
        health = check_page_health(self.page)
        if health == "logged_out":
            raise AccountStateError(Result.LOGIN_LOST)
        if health == "needs_action":
            raise AccountStateError(Result.NEEDS_ACTION)
        if health == "error_page" and not ignore_page_error:
            raise ContentUnavailable("当前页面有明确的全页加载异常")

    def click(self, locator) -> None:
        self.gate()
        self.m.behavior.click(self.page,locator,timeout=self.timeout())
        self.gate()

    def text(self, art) -> str:
        locator = art.locator(SELECTORS["tweet_text"]).first
        return locator.inner_text(timeout=self.timeout(1800)) if locator.count() else ""

    def status_url(self, art) -> Optional[str]:
        bound = self._article_urls.get(id(art))
        if bound is not None and bound[0] is art:
            return bound[1]
        return canonical_status_url(self.m.tweet_key(art) or "")

    def article_by_url(
        self, url: str, wait: bool = True, navigate_if_missing: bool = False
    ):
        url = canonical_status_url(url)
        if not url:
            raise ContentUnavailable("帖子没有稳定ID，跳过操作")
        status_id = url.rsplit("/", 1)[-1]
        links = self.page.locator(
            f'a[href$="/status/{status_id}"]:has(time), a[href*="/status/{status_id}?"]:has(time)'
        )
        article = self.page.locator(SELECTORS["tweet"]).filter(has=links).first
        if not article.count() and navigate_if_missing:
            self.navigator.goto(url)
        if wait:
            try:
                article.wait_for(state="visible", timeout=self.timeout(4000))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception as exc:
                raise ContentUnavailable(
                    f"目标帖子 {status_id} 已离开页面或不可用：{short_error(exc)}"
                ) from exc
        self._article_urls[id(article)] = (article, url)
        if len(self._article_urls) > 256:
            self._article_urls.popitem(last=False)
        return article

    def tab_selected(self, tab) -> bool:
        return bool(
            tab.evaluate(
                "el => el.getAttribute('aria-selected') === 'true' || el.getAttribute('aria-current') === 'page' || el.getAttribute('data-state') === 'active'"
            )
        )

    def wait_tab_selected(self, tab) -> None:
        for _ in range(16):
            self.gate()
            if self.tab_selected(tab):
                return
            self.m.sleep(0.25)
        raise ContentUnavailable("已点击关注页签，但选中状态未确认")

    def scroll(self, distance: int = 450) -> None:
        self.gate()
        self.m.behavior.scroll(self.page, distance)
        self.m.sleep(self.plan.rng.uniform(.4,1.15))

    def ensure_home(self) -> None:
        if self._bound_entry is not None:
            self.check_health()
            return
        if (
            not is_x_url(self.page.url or "")
            or urlparse(self.page.url).path.rstrip("/") != "/home"
        ):
            self.navigator.goto(TWITTER_HOME_URL)
        self.check_health()

    def viewport_article(self):
        articles=self.page.locator(SELECTORS['tweet'])
        height=self.page.evaluate('window.innerHeight')
        selected=None
        for index in range(min(articles.count(),30)):
            art=articles.nth(index)
            box=art.bounding_box(timeout=self.timeout(500))
            if not box or box['y']>=height or box['y']+box['height']<=0:continue
            url=self.status_url(art)
            if not url:continue
            self.analyze_post(art)
            if selected is None and url not in self.m.seen:selected=art
        return selected

    def peek_article(self):
        """只查看视口内已经呈现的帖子，不滚动、不等待、不为保存位置导航。"""
        articles=self.page.locator(SELECTORS['tweet'])
        for index in range(min(articles.count(),15)):
            art=articles.nth(index)
            box=art.bounding_box(timeout=self.timeout(500))
            if box and box['y']>=0 and box['y']<self.page.evaluate('window.innerHeight'):
                return art
        return None

    def pick_article(self, predicate, include_seen: bool = False, rounds: int = 3):
        for turn in range(rounds):
            self.gate()
            articles = self.page.locator(SELECTORS["tweet"])
            try:
                articles.first.wait_for(state="visible", timeout=self.timeout(2500))
            except Exception:
                self.gate()
                self.check_health()
            count = min(articles.count(), 15)
            for index in range(count):
                self.gate()
                art = articles.nth(index)
                try:
                    if not art.is_visible():
                        continue
                    url = self.status_url(art)
                    if not include_seen and url and url in self.m.seen:
                        continue
                    if not url:
                        continue
                    pinned = self.article_by_url(url, wait=False)
                    if not pinned.count():
                        continue
                    if predicate(pinned, self.text(pinned)):
                        return pinned
                except (
                    StopRequested,
                    DurationReached,
                    SceneBudgetExceeded,
                    AccountStateError,
                    CdpStateError,
                ):
                    raise
                except Exception:
                    logger.debug("候选帖子已变化", exc_info=True)
            if turn + 1 < rounds:
                self.scroll()
        return None

    def require_article(
        self, predicate=lambda _art, _text: True, include_seen: bool = False
    ):
        if self._bound_entry is not None and (urlparse(self.page.url).path.rstrip('/')=='/home' or canonical_status_url(self.page.url or '')==self._bound_entry['url']):
            art=self.article_by_url(self._bound_entry['url'],navigate_if_missing=True)
            if predicate(art,self.text(art)):return art
            raise ContentUnavailable('当前绑定帖子不再满足内容条件，不改选其他帖子')
        art = self.pick_article(predicate, include_seen=include_seen)
        if art is None:
            raise ContentUnavailable("没有符合条件且可见的帖子")
        return art

    def read(self, art, deep: bool = False, allow_like: bool = False) -> Optional[str]:
        self.phase("阅读正文")
        self.gate()
        url = self.status_url(art)
        art = self.article_by_url(url)
        if self._bound_entry and url==self._bound_entry['url'] and self._bound_entry.get('read') and not deep:
            return url
        self.m.journal.remember(url, False, reason="开始阅读")
        try:
            art.scroll_into_view_if_needed(timeout=self.timeout(2500))
            pid=url.rsplit('/',1)[-1] if url else None
            if pid and pid not in self.m.post_book.entries:
                try:
                    observed=art.evaluate(POST_FEATURE_JS,timeout=self.timeout(1500))
                    if not observed.get('url'):observed['url']=url
                    record=self.m.post_book.observe(observed,self.m.cfg.interest_terms)
                    record['source']={'url':self.page.url,'scroll':self.page.evaluate('window.scrollY'),'anchor':url}
                    self.m.stats['posts_scored']=self.m.post_book.total_posts
                except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):raise
                except Exception:logger.debug('支线帖评分不可用，继续正文阅读',exc_info=True)
            expand = art.locator(SELECTORS["show_more_text"]).first
            if deep and expand.count() and expand.is_visible():
                before_text=self.text(art)
                self.click(expand)
                art=self.article_by_url(url)
                after_text=self.text(art)
                remaining_expand=art.locator(SELECTORS['show_more_text']).first
                if after_text==before_text and remaining_expand.count() and remaining_expand.is_visible():
                    raise ContentUnavailable('正文展开尚未确认，未重复点击')
            text = self.text(art)
            self.m.sleep(
                self.plan.rng.uniform(.75,1.35)*min(16.0 if deep else 7.0, max(2.0, len(text) / (22 if deep else 40)))
            )
            self.m.stats["reads"] += 1
            if url:
                record=self.m.post_book.entries.get(url.rsplit('/',1)[-1])
                if record:
                    record['read']=True
                    self.m.current_post=record['id'];self.m.post_book.current=record['id']
            if url:
                self.m.mark_seen(url)
            self.m.journal.remember(url, True, reason="正文阅读完成")
            if self.m.cfg.comment_enabled and url:
                target_id = url.rsplit("/", 1)[-1]
                if target_id not in self.m.comment_skipped_targets:
                    self.m.comment_candidates[target_id] = url
                while len(self.m.comment_candidates) > SEEN_LIMIT:
                    self.m.comment_candidates.popitem(last=False)
            if allow_like and self.m.can_like() and random.random() < self.m.cfg.p_like:
                self.confirmed_like(art)
            # 阅读时只积累候选；评论交给独立辅助片段，避免逐条阅读被弹窗打断。
            return url
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            CdpStateError,
            AccountStateError,
        ):
            try:
                scroll = (
                    float(self.page.evaluate("window.scrollY"))
                    if canonical_status_url(self.page.url or "") == url
                    else 0.0
                )
            except Exception:
                scroll = 0.0
            self.m.journal.remember(url, False, scroll, "阅读被中断")
            raise

    def confirmed_like(self, art) -> None:
        button = art.locator(SELECTORS["like"]).first
        if not button.count() or not button.is_visible() or not self.m.can_like():
            return
        self.phase("确认点赞状态")
        # 发出点击前占用次数，超时不重发，不让不确定结果绕过上限。
        self.m.like_attempts += 1
        self.m.last_like_at = time.monotonic()
        self.m.stats["like_attempts"] = self.m.like_attempts
        try:
            self.click(button)
            art.locator('[data-testid="unlike"]').first.wait_for(
                state="visible", timeout=self.timeout(2000)
            )
            self.m.stats["likes"] += 1
            try:
                get_store().record_outgoing_success(self.m.browser_id, 'like', self.status_url(art))
            except Exception:
                logger.exception('点赞已确认，但独立累计记录保存失败')
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            self.m.stats["like_unconfirmed"] += 1
            self.m.log("点赞结果未确认，本次不重试，已计入尝试上限。")

    def open_detail(self, art) -> str:
        url = self.status_url(art)
        if not url:
            raise ContentUnavailable("帖子没有可验证的详情链接")
        self.phase("进入帖子详情")
        if not same_x_route(self.page.url or '',url):self.navigator.goto(url)
        expected_id = urlparse(url).path.split("/status/")[-1]
        current = canonical_status_url(self.page.url or "")
        if not current or urlparse(current).path.split("/status/")[-1] != expected_id:
            raise ContentUnavailable("详情页没有到达目标帖子")
        return url

    def read_feed(self, count: int = 2, predicate=lambda _art, _text: True) -> int:
        completed = 0
        for _ in range(count):
            try:
                art = self.require_article(predicate)
            except ContentUnavailable:
                break
            self.read(art)
            completed += 1
            self.scroll(380)
        if completed == 0:
            raise ContentUnavailable("当前信息流没有新的匹配内容")
        return completed

    def short_browse(self) -> str:
        self.ensure_home()
        count = self.read_feed(self.plan.rng.randint(1,3))
        return f"短浏览完成，阅读 {count} 条"

    def interest(self) -> str:
        terms = tuple(term.casefold() for term in self.m.cfg.interest_terms)
        if not terms:
            raise ContentUnavailable("请先配置兴趣关键词")
        self.ensure_home()
        art = self.require_article(
            lambda _art, text: any(term in text.casefold() for term in terms)
        )
        url = self.read(art, deep=True)
        continuations = [
            key
            for key in ("comments", "profile")
            if self.plan.items[key]["attempts"] < self.plan.items[key]["target"]
        ]
        if url and continuations:
            key = self.plan.rng.choice(continuations)
            self.plan.suggest(key, url)
            return f"兴趣正文已读，后续优先衔接{WORKFLOW_BY_KEY[key].label}"
        return "已阅读关键词匹配内容"

    def long_read(self) -> str:
        self.ensure_home()
        art = self.require_article(
            lambda art, text: (
                len(text) >= 140 or art.locator(SELECTORS["show_more_text"]).count() > 0
            )
        )
        self.read(art, deep=True)
        return "长文展开与阅读完成"

    def context_article(self, key: str):
        if self._bound_entry is not None:
            return self.article_by_url(self._bound_entry['url'],navigate_if_missing=True)
        url = self.plan.items[key].pop("context_url", None)
        if url:
            self.phase("打开上一个场景关联帖子")
            self.navigator.goto(url)
            art = self.require_article(
                lambda art, _text: self.status_url(art) == url, include_seen=True
            )
        else:
            self.ensure_home()
            art = self.require_article()
        if (self.status_url(art) or "") not in self.m.seen:
            self.read(art, allow_like=False)
        return art

    def read_discussion(self, root_url: str, count: int = 2) -> int:
        entry=self.m.post_book.entries.get(root_url.rsplit('/',1)[-1])
        if entry is None:entry=self.analyze_post(self.article_by_url(root_url))
        before=self.m.stats.get('comments_read',0)+self.m.stats.get('subcomments_read',0)
        self.read_scored_discussion(root_url,entry)
        return self.m.stats.get('comments_read',0)+self.m.stats.get('subcomments_read',0)-before

    def comments(self) -> str:
        art = self.context_article("comments")
        root_url = self.open_detail(art)
        read_count = self.read_discussion(root_url,self.plan.rng.randint(1,4))
        if not read_count:
            raise ContentUnavailable("原帖已读，但没有可见的新回复")
        return f"阅读 {read_count} 条回复"

    def photo_state(self) -> Dict[str, Any]:
        return self.page.evaluate(r"""() => {
            // x_media_viewer_state_v71
            const visible = el => !!el && el.getClientRects().length > 0 && getComputedStyle(el).visibility !== 'hidden';
            const route = new RegExp('/status/[0-9]+/photo/[0-9]+').test(location.pathname);
            const overlay = [...document.querySelectorAll('[data-testid="swipe-to-dismiss"], [role="dialog"], [aria-modal="true"]')].find(el => visible(el) && el.querySelector('[data-testid="tweetPhoto"] img, img[src*="/media/"]'));
            const images = [...(overlay || document).querySelectorAll('img')].filter(el => visible(el) && (el.closest('[data-testid="tweetPhoto"]') || (el.currentSrc || el.src).includes('/media/')));
            const image = images.find(el => el.complete && el.naturalWidth > 0 && (route || overlay));
            return {open: !!(route || overlay), loaded: !!image, identity: location.pathname + '|' + (image ? (image.currentSrc || image.src) : ''), route};
        }""")

    def wait_photo(self, rounds: int = 16) -> Optional[Dict[str, Any]]:
        for _ in range(rounds):
            self.gate()
            state = self.photo_state()
            if state.get("open") and state.get("loaded"):
                return state
            self.m.sleep(0.25)
        return None

    def gallery(self) -> str:
        self.ensure_home()
        art = self.require_article(lambda art, _text: art.locator(SELECTORS['photo']).count()>0,include_seen=bool(self._bound_entry))
        url = self.read(art, allow_like=False)
        art = self.article_by_url(url, navigate_if_missing=True)
        self.phase("打开图片或在信息流查看")
        photo = art.locator(SELECTORS["photo"]).first
        links = art.locator('a[href*="/photo/"]')
        own_link = None
        href = None
        for index in range(min(links.count(), 6)):
            candidate = links.nth(index)
            value = candidate.get_attribute("href", timeout=self.timeout(1200)) or ""
            if canonical_status_url(value) == url:
                own_link, href = candidate, value
                break
        if links.count() and own_link is None:
            raise ContentUnavailable("图片链接属于引用帖，未把其他帖图片当作当前帖操作")
        self.click(own_link if own_link is not None else photo)
        state = self.wait_photo()
        if state is None and href:
            target = href if is_x_url(href) else "https://x.com" + href
            self.navigator.goto(target)
            state = self.wait_photo()
        if state is None:
            # 有些页面只支持内联图片；真实看到图片可以完成浏览，但不声称打开了查看器。
            art = self.article_by_url(url, navigate_if_missing=True)
            image = art.locator(SELECTORS["photo"] + " img").first
            if (
                image.count()
                and image.is_visible()
                and image.evaluate(
                    "el => el.complete && el.naturalWidth > 0",
                    timeout=self.timeout(1500),
                )
            ):
                image.scroll_into_view_if_needed(timeout=self.timeout(2500))
                self.m.sleep(3)
                self.m.stats['images_viewed']=self.m.stats.get('images_viewed',0)+1
                return "已在信息流查看加载完成的图片；当前页面未打开独立查看器"
            raise ContentUnavailable("图片未加载或没有可识别的查看器，跳过本次图片流程")
        self.m.sleep(3)
        viewed = 1
        self.m.stats['images_viewed']=self.m.stats.get('images_viewed',0)+1
        for _ in range(max(0,reading_policy(self.m.cfg)['max_images']-1)):
            next_button = self.page.locator(
                SELECTORS["next_slide"]
                + ', [data-testid="Carousel-NavRight"], [aria-label="Próximo slide"], [aria-label="Siguiente diapositiva"]'
            ).first
            if not next_button.count() or not next_button.is_visible():
                break
            before = state.get("identity")
            self.click(next_button)
            self.m.sleep(1)
            state = self.wait_photo(8)
            if state is None or state.get("identity") == before:
                break
            viewed += 1
            self.m.stats['images_viewed']=self.m.stats.get('images_viewed',0)+1
            self.m.sleep(1)
        self.page.keyboard.press("Escape")
        self.m.sleep(0.3)
        if self.photo_state().get("open"):
            close = self.page.locator(
                SELECTORS["close_viewer"]
                + ', [aria-label="Fechar"], [aria-label="Cerrar"]'
            ).first
            if close.count() and close.is_visible():
                self.click(close)
                self.m.sleep(0.3)
        if self.photo_state().get("open"):
            self.navigator.goto(url)
        return f"查看 {viewed} 张已加载图片，并离开图片查看器"

    def video_state(self, video) -> Dict[str, Any]:
        return video.evaluate(
            """v => ({time:v.currentTime || 0, duration:Number.isFinite(v.duration)?v.duration:0,
            paused:v.paused, ended:v.ended, ready:v.readyState, network:v.networkState,
            error:v.error ? v.error.code : 0})""",
            timeout=self.timeout(2000),
        )

    def video(self) -> str:
        self.ensure_home()
        art = self.require_article(lambda art, _text: art.locator("video").count() > 0)
        url = self.read(art, allow_like=False)
        try:
            art = self.article_by_url(url, navigate_if_missing=True)
            video = art.locator("video").first
            video.scroll_into_view_if_needed(timeout=self.timeout(3000))
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            # 不再复用原来的 nth(index)；详情页重新获取同一帖子的视频。
            self.navigator.goto(url)
            art = self.article_by_url(url)
            video = art.locator("video").first
            try:
                video.wait_for(state="visible", timeout=self.timeout(4500))
            except (
                StopRequested,
                DurationReached,
                SceneBudgetExceeded,
                AccountStateError,
                CdpStateError,
            ):
                raise
            except Exception as exc:
                raise ContentUnavailable(
                    f"同一帖子的视频节点未就绪：{short_error(exc)}"
                ) from exc
        self.phase("检查视频加载与播放状态")
        before = self.video_state(video)
        if before.get("error"):
            raise ContentUnavailable(
                f"视频媒体错误 code={before['error']}，未尝试反复播放"
            )
        play_result = {
            "ok": not before.get("paused", True),
            "reason": "already_playing",
        }
        if not play_result["ok"]:
            play_result = video.evaluate(
                """v => {
                v.muted=true;
                return Promise.race([
                    v.play().then(()=>({ok:true,reason:'started'})).catch(e=>({ok:false,reason:e.name || 'play_failed'})),
                    new Promise(resolve=>setTimeout(()=>resolve({ok:false,reason:'buffering_timeout'}),2000))]);
            }""",
                timeout=self.timeout(3000),
            )
        if not play_result.get("ok"):
            play = art.locator(
                '[data-testid="playButton"], [aria-label="Play"], [aria-label="Play video"], [aria-label="播放"], [aria-label="播放视频"], [aria-label="Reproduzir"], [aria-label="Reproducir"]'
            ).first
            if play.count() and play.is_visible():
                self.click(play)  # 只尝试一次可见播放按钮，不改浏览器播放策略。
            self.m.sleep(1.5)
        current = self.video_state(video)
        if current.get("error"):
            raise ContentUnavailable(f"视频媒体错误 code={current['error']}")
        if current.get("paused", True) and not play_result.get("ok"):
            raise ContentUnavailable(
                f"视频未进入播放：{play_result.get('reason', 'unknown')}，readyState={current.get('ready', 0)}，networkState={current.get('network', 0)}"
            )
        self.phase("静音观看并验证播放进度")
        watch_sec = min(
            self.plan.rng.uniform(7,18),
            max(4.0, float(current.get("duration", 0)) - float(current.get("time", 0))),
        )
        previous = float(current.get("time", 0))
        moved = abs(previous - float(before.get("time", 0))) > 0.1
        spent = 0.0
        while spent < watch_sec:
            interval = min(2.0, watch_sec - spent)
            self.m.sleep(interval)
            spent += interval
            current = self.video_state(video)
            value = float(current.get("time", 0))
            moved = moved or abs(value - previous) > 0.1
            previous = value
            if current.get("ended") and moved:
                break
            if current.get("error"):
                raise ContentUnavailable(f"观看中媒体加载失败 code={current['error']}")
        if not moved:
            raise ContentUnavailable(
                f"视频没有实际播放进度，readyState={current.get('ready', 0)}，networkState={current.get('network', 0)}"
            )
        self.m.stats['videos_viewed']=self.m.stats.get('videos_viewed',0)+1
        return f"视频播放进度已确认，观看约 {spent:.0f} 秒"

    def profile(self) -> str:
        art = self.context_article("profile")
        art = self.article_by_url(self.status_url(art), navigate_if_missing=True)
        self.phase("进入作者主页")
        link = art.locator('[data-testid="User-Name"] a[role="link"]').first
        href = (
            link.get_attribute("href", timeout=self.timeout(2000))
            if link.count()
            else None
        )
        if not href or not href.startswith("/") or len(href.strip("/").split("/")) != 1:
            raise ContentUnavailable("没有可验证的作者主页链接")
        self.navigator.goto("https://x.com" + href)
        if (
            urlparse(self.page.url).path.rstrip("/").casefold()
            != href.rstrip("/").casefold()
        ):
            raise ContentUnavailable("未进入预期作者主页")
        bio = self.page.locator('[data-testid="UserDescription"]').first
        if bio.count() and bio.is_visible():
            self.phase("阅读作者简介")
            bio.inner_text(timeout=self.timeout(1500))
            self.m.sleep(2)
        self.read_feed(2)
        return "作者简介与近期动态阅读完成"

    def following(self) -> str:
        self.ensure_home()
        self.phase("定位并切换关注信息流")
        tab = self.page.get_by_role("tab", name=following_name_pattern()).first
        try:
            tab.wait_for(state="visible", timeout=self.timeout(5000))
        except (
            StopRequested,
            DurationReached,
            SceneBudgetExceeded,
            AccountStateError,
            CdpStateError,
        ):
            raise
        except Exception:
            raise ContentUnavailable(
                "当前页面未提供可识别的关注页签（支持中英、葡语、西语等）"
            )
        if not self.tab_selected(tab):
            self.click(tab)
            self.wait_tab_selected(tab)
        self.read_feed(2)
        return "关注信息流阅读完成"

    def search(self) -> str:
        if not self.m.cfg.interest_terms:
            raise ContentUnavailable("没有预设搜索关键词")
        term = self.plan.rng.choice(self.m.cfg.interest_terms)
        self.phase(f"搜索预设主题：{term}")
        self.navigator.goto(
            "https://x.com/search?"
            + urlencode({"q": term, "src": "typed_query", "f": "live"})
        )
        self.read_feed(2)
        return f"主题搜索阅读完成：{term}"

    def notifications(self) -> str:
        self.phase("查看已有通知")
        self.navigator.goto("https://x.com/notifications")
        cells = self.page.locator(
            '[data-testid="notification"], [data-testid="cellInnerDiv"]'
        )
        try:
            cells.first.wait_for(state="visible", timeout=self.timeout(3500))
        except Exception:
            self.gate()
            self.check_health()
            raise ContentUnavailable("没有可见通知或通知尚未加载")
        read_count = 0
        target_url = None
        for index in range(min(cells.count(), 6)):
            self.gate()
            cell = cells.nth(index)
            if not cell.is_visible():
                continue
            text = cell.inner_text(timeout=self.timeout(1500))
            if not text.strip():
                continue
            # 阅读不等于回复；不保存通知正文，不点击关注/回复按钮。
            self.m.sleep(min(5.0, max(1.0, len(text) / 40)))
            read_count += 1
            links = cell.locator('a[href*="/status/"]')
            if target_url is None and links.count():
                target_url = canonical_status_url(
                    links.first.get_attribute("href", timeout=self.timeout(1500)) or ""
                )
            if read_count >= 3:
                break
        if target_url:
            self.phase("查看通知关联帖子")
            self.navigator.goto(target_url)
            art = self.require_article(include_seen=True)
            self.read(art, allow_like=False)
        if read_count == 0:
            raise ContentUnavailable("没有可读通知")
        self.m.stats["notifications_read"] += read_count
        return f"阅读 {read_count} 条已有通知"

    def revisit(self) -> str:
        entries = self.m.journal.pending()
        if not entries:
            raise ContentUnavailable("没有未读完的历史帖子")
        url, entry = entries[0]
        self.m.journal.mark_revisit(url)
        self.phase("继续未完成阅读")
        self.navigator.goto(url)
        position = (
            entry.get("thread_scroll", 0)
            if entry.get("thread_pending")
            else entry.get("scroll", 0)
        )
        self.page.evaluate("y => window.scrollTo(0, y)", max(0.0, float(position)))
        if entry.get("thread_pending"):
            if not self.m.cfg.enable_deep_visit:
                raise ContentUnavailable("评论阅读已关闭，保留未完成讨论")
            count = self.read_discussion(url)
            if count == 0:
                raise ContentUnavailable("历史讨论没有可见的新回复")
            return f"已继续阅读历史讨论的 {count} 条回复"
        expected_id = urlparse(url).path.split("/status/")[-1]
        art = self.require_article(
            lambda art, _text: (self.status_url(art) or "").endswith(
                "/status/" + expected_id
            ),
            include_seen=True,
        )
        self.read(art, deep=True, allow_like=False)
        return "已继续并完成历史阅读"

    def casual_exit(self) -> str:
        self.ensure_home()
        # 空信息流也会结束会话，但不能把“没有阅读”记成完成浏览。
        self.read_feed(1)
        return "短暂浏览后结束"

    # ---------- V8：目录分派、能力检查与可核实的阅读路径 ----------
    def execute_workflow(self, key):
        spec=WORKFLOW_BY_KEY[key]
        if spec.manual_only:
            raise ContentUnavailable("手动项不允许进入自动执行器")
        if not spec.handler:
            return getattr(self,key)()
        handler=getattr(self,"extra_"+spec.handler,None)
        if handler is None:
            raise RuntimeError("工作流缺少处理器："+key)
        self.phase(spec.label)
        return handler(spec.arg)

    def trigger_condition(self,key):
        """只检查已呈现的DOM，不为探测功能点击、导航或修改账号状态。"""
        if self.plan.items[key]['tier']!='conditional':
            return None
        selectors={
            'gif_read':'video[loop]:visible, [data-testid="gifPlayer"]:visible',
            'video_review':'video:visible',
            'image_alt':'[data-testid="tweetPhoto"] img[alt]:visible',
            'notes_read':'[data-testid="birdwatch-pivot"]:visible, [data-testid="communityNote"]:visible, [data-testid="birdwatch-note"]:visible',
            'poll_read':'[data-testid="cardPoll"]:visible, [data-testid="poll"]:visible, [data-testid^="pollOption"]:visible',
            'live_read':'a[href*="/i/broadcasts/"]:visible, [data-testid="liveVideoPlayer"]:visible',
            'spaces_read':'a[href*="/i/spaces/"]:visible',
            'articles_read':'a[href*="/i/article/"]:visible, a[href*="/i/articles/"]:visible',
        }
        selector=selectors.get(key)
        if selector and not self.page.locator(selector).count():
            return '当前可见内容未提供对应媒体或功能入口'
        return None

    def candidate_link(self, scope, predicate, requested_ms=4000):
        """一轮DOM快照读取链接，不对重绘中的nth索引逐个等待。"""
        def collect():
            rows=scope.locator('a[href]').evaluate_all('''els => els.filter(e => {
                const s=getComputedStyle(e);return e.getClientRects().length && s.visibility!=='hidden' && s.display!=='none';
            }).map(e => ({href:e.getAttribute('href')||'',url:e.href||''}))''')
            found={}
            for row in rows:
                url=row['url'];href=row['href']
                if urlparse(url).scheme in ('http','https') and predicate(url):
                    found.setdefault(url,href)
            if not found:
                return None
            url=self.plan.rng.choice(list(found))
            node=scope.locator('a[href='+json.dumps(found[url],ensure_ascii=False)+']:visible').first
            return (node,url) if node.count() else None
        result=self.poll(collect,requested_ms)
        if result is None:
            raise ContentUnavailable("页面已等待，但没有此功能的可见入口")
        return result

    def open_observed(self, pattern, scope=None):
        rx=re.compile(pattern,re.I)
        node,url=self.candidate_link(scope if scope is not None else self.page,
                                     lambda u:is_x_url(u) and bool(rx.search(urlparse(u).path)))
        # 按href重新定位后只点击一次，导航慢时等待URL，不重复点击。
        self.click(node)
        arrived=self.poll(lambda:is_x_url(self.page.url) and bool(rx.search(urlparse(self.page.url).path)),6500)
        if not arrived:
            raise PageNotReady("入口已点击，目标功能页尚未完成跳转")
        self.check_health()
        return url

    def primary(self):
        selectors=('[data-testid="sheetDialog"]:visible','[role="dialog"][aria-modal="true"]:visible',
                   '[data-testid="settingsDetail"]:visible','[data-testid="primaryColumn"]:visible',
                   'main:visible','[role="main"]:visible','[role="dialog"]:visible')
        def find():
            for selector in selectors:
                node=self.page.locator(selector).first
                if node.count():
                    return node
            return None
        node=self.poll(find,7000)
        if node is None:
            raise PageNotReady("页面主内容尚未就绪，稍后重新尝试")
        return node

    def read_blocks(self, scope, selector=None, limit=3):
        blocks=scope.locator(selector) if selector else scope
        # 文本和可见状态在同一次浏览器求值中读取，不保存消息/通知正文。
        def snapshot():
            return blocks.evaluate_all('''els=>els.filter(e=>e.getClientRects().length && getComputedStyle(e).visibility!=='hidden')
                .map(e=>(e.innerText||'').trim()).filter(Boolean).slice(0,20)''')
        texts=self.poll(snapshot,6500)
        if not texts:
            if self.page.locator('[role="progressbar"]:visible, [aria-busy="true"]:visible').count():
                raise PageNotReady("主内容仍在加载，稍后重新尝试")
            raise ContentUnavailable("功能页已等待，但没有可读内容")
        count=0;fingerprints=set()
        handles=blocks.element_handles()
        try:
            for current in handles[:20]:
                self.gate()
                try:
                    # 临时绑定同一DOM节点，只用于阅读；不把动态nth重新解释成其他内容。
                    if not current.evaluate('e=>e.isConnected && e.getClientRects().length>0') or not current.is_visible():
                        continue
                    text=current.inner_text().strip()
                    if not text or text in fingerprints:
                        continue
                    current.scroll_into_view_if_needed(timeout=self.timeout(1500))
                except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):
                    raise
                except Exception:
                    self.gate()
                    continue
                fingerprints.add(text)
                self.m.sleep(self.plan.rng.uniform(.7,1.3)*min(6,max(1,len(text)/45)))
                count+=1
                if count>=limit:
                    break
        finally:
            for handle in handles:
                try:handle.dispose()
                except Exception:logger.debug("阅读节点释放失败",exc_info=True)
        if not count:
            raise PageNotReady("阅读内容在重绘中消失，稍后重新尝试")
        return count

    def read_any_posts(self,count=2):
        ready=self.poll(lambda:self.page.locator(SELECTORS['tweet']+':visible').count(),8000)
        if not ready:
            if self.page.locator('[role="progressbar"]:visible, [aria-busy="true"]:visible').count():
                raise PageNotReady("帖子列表仍在加载")
            raise ContentUnavailable("等待后仍没有可见帖子")
        completed=0;local_seen=set()
        for _ in range(count):
            art=self.pick_article(lambda a,t:self.status_url(a) not in local_seen,include_seen=True,rounds=2)
            if art is None:
                break
            url=self.status_url(art)
            try:
                self.read(art,allow_like=False)
            except ContentUnavailable:
                # 某条被虚拟列表回收只跳过该候选，不把整个列表立即判为空。
                local_seen.add(url)
                continue
            local_seen.add(url);completed+=1
            self.scroll(self.plan.rng.randint(180,430))
        if not completed:
            raise ContentUnavailable("可见帖子已变化，当前没有可读候选")
        return completed

    def detail_source(self):
        self.ensure_home()
        art=self.require_article(include_seen=True)
        url=self.open_detail(art)
        return url,self.article_by_url(url)

    def extra_detail(self,arg):
        url,art=self.detail_source()
        self.read(art,deep=True,allow_like=False)
        return "已核实目标ID并完成详情阅读，结束后恢复来源"

    def extra_recent(self,arg):
        return self.revisit()  # 历史支线只恢复确实未读完的正文或讨论。

    def extra_backtrack(self,arg):
        self.ensure_home()
        self.scroll(self.plan.rng.randint(380,900))
        self.m.behavior.scroll(self.page,self.plan.rng.randint(180,450),-1)
        self.m.sleep(self.plan.rng.uniform(.6,1.8))
        self.read_any_posts(1)
        return "下滚后向上回看并阅读可见内容"

    def extra_refresh(self,arg):
        self.ensure_home()
        self.page.reload(wait_until="domcontentloaded",timeout=self.timeout(12000))
        self.check_health(); self.read_any_posts(1)
        return "首页刷新后已核实可读内容"

    def extra_translate(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('[data-testid="translate"]:visible').count()>0 or a.get_by_role("button",name=re.compile(r"^(Translate post|Translate|翻译推文|翻译帖子|翻译|Traduzir post|Traduzir|Traducir post)$",re.I)).count()>0,include_seen=True)
        before=art.inner_text(timeout=self.timeout(1500))
        button=art.locator('[data-testid="translate"]:visible').first
        if not button.count():
            button=art.get_by_role("button",name=re.compile(r"^(Translate post|Translate|翻译推文|翻译帖子|翻译|Traduzir post|Traduzir|Traducir post)$",re.I)).first
        self.click(button)
        for _ in range(10):
            self.m.sleep(.25)
            if art.inner_text(timeout=self.timeout(1000))!=before:
                self.read(art,deep=True,allow_like=False)
                return "翻译入口已点击并确认内容发生变化"
        raise ContentUnavailable("译文未确认出现，未记为完成")

    def extra_thread(self,arg):
        url,art=self.detail_source()
        self.read(art,deep=True,allow_like=False)
        count=self.read_discussion(url,self.plan.rng.randint(2,4))
        if not count:
            raise ContentUnavailable("主帖可读，但没有可见上下文或回复")
        return f"主帖及{count}条上下文阅读完成（不推断均属作者线程）"

    def extra_reply_branch(self,arg):
        root,art=self.detail_source()
        self.read(art,allow_like=False)
        reply=self.pick_article(lambda a,t:self.status_url(a)!=root,include_seen=True,rounds=2)
        if reply is None:
            raise ContentUnavailable("没有可展开的其他回复")
        target=self.open_detail(reply)
        self.read(self.article_by_url(target),deep=True,allow_like=False)
        count=self.read_discussion(target,2)
        self.navigator.goto(root)
        self.article_by_url(root)
        return f"已进入回复分支并返回原帖，新增阅读{count}条；未把目标回复当原帖"

    def extra_quote(self,arg):
        self.ensure_home()
        def quoted(a,t):
            own=self.status_url(a)
            return any(canonical_status_url(v.get_attribute("href",timeout=self.timeout(800)) or "") not in (None,own) for v in [a.locator('a[href*="/status/"]').nth(i) for i in range(min(a.locator('a[href*="/status/"]').count(),10))])
        art=self.require_article(quoted,include_seen=True)
        own=self.status_url(art); self.read(art,allow_like=False)
        _,url=self.candidate_link(art,lambda u:is_x_url(u) and canonical_status_url(u) not in (None,own))
        url=canonical_status_url(url); self.navigator.goto(url)
        self.read(self.article_by_url(url),deep=True,allow_like=False)
        return "已阅读不同ID的关联原帖；仅按可验证链接识别关联关系"

    def extra_post_link(self,arg):
        self.ensure_home()
        selector='[data-testid="tweetText"] a[href]:visible'
        def matches(u):
            path=urlparse(u).path
            return is_x_url(u) and (path.startswith('/hashtag/') if arg=='hashtag' else bool(re.fullmatch(r'/[A-Za-z0-9_]{1,15}',path)))
        art=self.require_article(lambda a,t:any(matches(("https://x.com"+h) if h.startswith('/') else h) for h in a.locator(selector).evaluate_all('(els)=>els.map(e=>e.getAttribute("href")||"")')),include_seen=True)
        _,url=self.candidate_link(art.locator('[data-testid="tweetText"]'),matches)
        self.navigator.goto(url)
        if arg=='hashtag':
            self.read_any_posts(2)
        else:
            self.read_blocks(self.primary(),'[data-testid="UserDescription"]:visible',1)
        return "正文链接延伸阅读完成："+arg

    def extra_external(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('[data-testid="card.wrapper"] a[href], [data-testid="tweetText"] a[href^="http"]').count()>0,include_seen=True)
        _,url=self.candidate_link(art,lambda u:urlparse(u).scheme in ('http','https') and not is_x_url(u))
        # 工作流结束时由统一导航器恢复来源；全程不创建新标签。
        self.page.goto(url,wait_until="domcontentloaded",timeout=self.timeout(12000))
        self.gate()
        if urlparse(self.page.url).scheme not in ('http','https'):
            raise ContentUnavailable("站外链接没有到达网页")
        text=self.page.locator('body').inner_text(timeout=self.timeout(2500)).strip()
        if len(text)<40:
            raise ContentUnavailable("站外网页没有足够可读内容")
        self.m.sleep(self.plan.rng.uniform(3,8))
        return "已在当前标签阅读站外网页，结束后返回来源"

    def extra_image_alt(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('[data-testid="tweetPhoto"] img[alt]').count()>0,include_seen=True)
        descriptions=art.locator('[data-testid="tweetPhoto"] img').evaluate_all('(els)=>els.map(e=>e.alt||"").filter(t=>t.trim()&&!/^(image|photo|图像|图片)$/i.test(t.trim()))')
        if not descriptions:
            raise ContentUnavailable("图片存在，但没有可读的自定义ALT说明")
        self.m.sleep(min(8,max(2,sum(map(len,descriptions))/35)))
        return f"阅读{len(descriptions)}条图片说明"

    def extra_gif(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('video[loop], [data-testid="gifPlayer"]').count()>0,include_seen=True)
        self.read(art,allow_like=False)
        media=art.locator('video').first
        if media.count():
            before=self.video_state(media)
            media.evaluate('v=>{v.muted=true; return v.play().then(()=>true).catch(()=>false)}')
            self.m.sleep(self.plan.rng.uniform(2,5))
            after=self.video_state(media)
            if before['time']==after['time']:
                raise ContentUnavailable("GIF媒体没有实际播放进度")
        else:
            self.read_blocks(art,limit=1)
        return "GIF可见内容阅读完成"

    def extra_video_review(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('video').count()>0,include_seen=True)
        video=art.locator('video').first
        before=self.video_state(video)
        if before.get('error'):
            raise ContentUnavailable("视频加载错误")
        started=video.evaluate('v=>{v.muted=true;return v.play().then(()=>true).catch(()=>false)}')
        if not started:
            raise ContentUnavailable("视频没有获准播放")
        try:
            self.m.sleep(self.plan.rng.uniform(2,4))
            state=self.video_state(video)
            if state['time']==before['time']:
                raise ContentUnavailable("视频播放进度未变化")
            video.evaluate('v=>v.pause()'); self.m.sleep(self.plan.rng.uniform(.4,1.1))
            if state['duration']>5:
                video.evaluate('(v,delta)=>{v.currentTime=Math.max(0,v.currentTime-delta)}',self.plan.rng.uniform(1,3))
            resumed=video.evaluate('v=>v.play().then(()=>true).catch(()=>false)')
            if not resumed:
                raise ContentUnavailable("暂停后恢复播放失败")
            self.m.sleep(self.plan.rng.uniform(1,3))
            return "视频实际播放、暂停与恢复已核实"
        finally:
            # 离开时恢复原有暂停状态，不留下新开启的后台播放。
            if before.get('paused'):
                try:video.evaluate('v=>v.pause()')
                except Exception:logger.debug("恢复视频暂停状态失败",exc_info=True)

    def extra_search_mode(self,arg):
        if not self.m.cfg.interest_terms:
            raise ContentUnavailable("没有搜索关键词")
        term=self.plan.rng.choice(self.m.cfg.interest_terms)
        params={'q':('"'+term.replace('"','')+'"') if arg=='exact' else term,'src':'typed_query'}
        if arg not in ('top','exact'):params['f']=arg
        self.navigator.goto('https://x.com/search?'+urlencode(params))
        if arg=='user':
            count=self.read_blocks(self.primary(),'[data-testid="UserCell"]:visible',self.plan.rng.randint(1,3))
        else:
            if arg=='image':
                self.require_article(lambda a,t:a.locator(SELECTORS['photo']).count()>0,include_seen=True)
            if arg=='video':
                self.require_article(lambda a,t:a.locator('video, [data-testid="videoPlayer"]').count()>0,include_seen=True)
            count=self.read_any_posts(self.plan.rng.randint(1,2))
        return f"{arg}搜索已读{count}项，关键词：{term}"

    def extra_search_history(self,arg):
        self.ensure_home()
        box=self.page.locator('[data-testid="SearchBox_Search_Input"]:visible').first
        if not box.count():raise ContentUnavailable("没有搜索框入口")
        self.click(box)
        try:
            count=self.read_blocks(self.page,'[role="listbox"]:visible, [data-testid="typeaheadDropdown"]:visible',1)
            return f"已查看{count}个搜索建议或历史面板；未修改记录"
        finally:self.page.keyboard.press('Escape')

    SURFACES={
        'explore':('/explore',r'^/explore(?:/|$)'),
        'bookmarks':('/i/bookmarks',r'^/i/bookmarks(?:/|$)'),
        'lists':(None,r'^/(?:i/lists|[A-Za-z0-9_]+/lists)(?:/|$)'),
        'history':(None,r'^/(?:i/)?history(?:/|$)'),
        'communities':(None,r'^/(?:i/)?communities(?:/|$)'),
        'grok':(None,r'^/i/grok(?:/|$)'),
        'settings':('/settings',r'^/settings(?:/|$)'),
        'security':('/settings/security_and_account_access',r'^/settings/security_and_account_access(?:/|$)'),
        'account':('/settings/account',r'^/settings/account(?:/|$)'),
        'accessibility':('/settings/accessibility_display_and_languages',r'^/settings/accessibility_display_and_languages(?:/|$)'),
        'privacy':('/settings/privacy_and_safety',r'^/settings/privacy_and_safety(?:/|$)'),
        'premium':(None,r'^/(?:i/)?(?:premium|premium_sign_up|verified-choose)(?:/|$)'),
        'creator':(None,r'^/(?:i/)?(?:monetization|creator|creator-studio)(?:/|$)'),
    }

    def goto_surface(self,arg):
        previous=self.capabilities.get(arg,{})
        if previous.get('state')=='unavailable':
            raise FeatureUnavailable(arg,previous['reason'])
        direct,pattern=self.SURFACES[arg]
        if direct:
            self.navigator.goto('https://x.com'+direct)
            if not self.poll(lambda:bool(re.search(pattern,urlparse(self.page.url).path,re.I)),4500):
                raise PageNotReady("功能页跳转尚未完成")
        else:
            # 先等当前界面完成挂载；侧栏收起时尝试可见的导航“更多”菜单。
            self.primary()
            try:
                self.open_observed(pattern)
            except ContentUnavailable as exc:
                if isinstance(exc,PageNotReady):
                    raise
                more=self.page.locator('nav [data-testid="AppTabBar_More_Menu"]:visible, nav [aria-label="More menu items"]:visible, nav [aria-label="更多菜单项"]:visible').first
                if not more.count():
                    raise FeatureUnavailable(arg,"当前账号已加载的导航未提供此功能入口") from exc
                self.click(more)
                try:
                    self.open_observed(pattern)
                except ContentUnavailable as second:
                    if isinstance(second,PageNotReady):
                        raise
                    raise FeatureUnavailable(arg,"侧栏及更多菜单均未提供此功能入口") from second
                finally:
                    self.page.keyboard.press('Escape')
        scope=self.primary()
        if self.page.locator('input[type="password"]:visible').count():
            raise FeatureUnavailable(arg,"此入口要求重新验证身份，保留给用户手动处理")
        self.capabilities[arg]={'state':'available','elapsed':round(self.m.clock.elapsed(),2)}
        return scope

    def extra_surface(self,arg):
        scope=self.goto_surface(arg)
        if arg=='bookmarks':
            count=self.read_any_posts(2)
        elif arg=='history':
            try:count=self.read_any_posts(2)
            except PageNotReady:
                raise
            except ContentUnavailable:
                count=self.read_blocks(scope,'a[href*="/status/"]:visible, a[href*="/i/article/"]:visible, a[href*="/i/articles/"]:visible',2)
        else:
            count=self.read_blocks(scope,limit=1)
        return f"{arg}已读{count}项；未修改设置或提交内容"

    def extra_trend(self,arg):
        scope=self.goto_surface('explore')
        self.open_observed(r'^/search$',scope)
        count=self.read_any_posts(2)
        return f"从探索页进入实际趋势链接，阅读{count}条"

    def extra_custom_timeline(self,arg):
        self.ensure_home()
        tabs=self.page.locator('[role="tab"]:visible')
        choices=[]
        standard=re.compile(r'^(For you|Following|为你推荐|推荐|正在关注|关注|Para você|Seguindo|Para ti|Siguiendo)$',re.I)
        for i in range(tabs.count()):
            node=tabs.nth(i); text=node.inner_text(timeout=self.timeout(1000)).strip()
            if text and not standard.fullmatch(text):choices.append(node)
        if not choices:raise ContentUnavailable("没有额外固定的信息流标签")
        tab=self.plan.rng.choice(choices); self.click(tab); self.wait_tab_selected(tab)
        count=self.read_any_posts(2)
        return f"自定义信息流已读{count}条"

    def author_page(self):
        self.ensure_home(); art=self.require_article(include_seen=True)
        _,url=self.candidate_link(art.locator('[data-testid="User-Name"]'),lambda u:is_x_url(u) and bool(re.fullmatch(r'/[A-Za-z0-9_]{1,15}',urlparse(u).path)))
        self.navigator.goto(url)
        self.primary()
        return urlparse(url).path.rstrip('/')

    def extra_profile_tab(self,arg):
        author=self.author_page()
        suffix=r'(?:followers|verified_followers)' if arg=='followers' else re.escape(arg)
        self.open_observed('^'+re.escape(author)+'/'+suffix+r'/?$')
        if arg in ('following','followers'):
            count=self.read_blocks(self.primary(),'[data-testid="UserCell"]:visible',self.plan.rng.randint(1,3))
        elif arg=='articles':
            count=self.read_blocks(self.primary(),'[data-testid="cellInnerDiv"]:visible, article:visible',2)
        else:
            count=self.read_any_posts(2)
        return f"作者{arg}标签已读{count}项"

    def extra_collection(self,arg):
        scope=self.goto_surface(arg)
        pattern=r'^/i/lists/[0-9]+/?$' if arg=='lists' else r'^/i/communities/[0-9]+/?$'
        self.open_observed(pattern,scope)
        count=self.read_any_posts(self.plan.rng.randint(1,3))
        return f"已进入实际{arg}并阅读{count}条；未修改成员关系"

    def extra_community_rules(self,arg):
        scope=self.goto_surface('communities')
        self.open_observed(r'^/i/communities/[0-9]+/?$',scope)
        rules=self.page.locator('[data-testid="communityRules"]:visible, [data-testid="communityDescription"]:visible').first
        if rules.count():
            self.read_blocks(rules,limit=1)
            return "已读取社群规则或简介"
        about=self.page.get_by_role('tab',name=re.compile(r'^(About|关于|简介|Sobre|Información)$',re.I)).first
        if not about.count():raise ContentUnavailable("社群没有可识别的规则或简介入口")
        self.click(about); self.read_blocks(self.primary(),limit=1)
        return "已打开社群简介标签，未加入或申请"

    def extra_mentions(self,arg):
        self.navigator.goto('https://x.com/notifications/mentions')
        count=self.read_any_posts(2)
        self.m.stats['notifications_read']+=count
        return f"已阅读{count}条提及内容"

    def extra_own_profile(self,arg):
        link=self.page.locator('[data-testid="AppTabBar_Profile_Link"]:visible').first
        if not link.count():raise ContentUnavailable("没有当前账号的主页入口")
        href=link.get_attribute('href',timeout=self.timeout(1200)) or ''
        if not re.fullmatch(r'/[A-Za-z0-9_]{1,15}',href):raise ContentUnavailable("自己的主页链接未确认")
        self.navigator.goto('https://x.com'+href); count=self.read_any_posts(2)
        return f"当前账号主页已读{count}条，未编辑或删除"

    def extra_messages(self,arg):
        self.navigator.goto('https://x.com/messages')
        scope=self.primary()
        rows=scope.locator('[data-testid="conversation"]:visible, [data-testid="conversationEntry"]:visible')
        if not rows.count():raise ContentUnavailable("没有可识别的已有会话；不自动注册Chat或输入PIN")
        row=rows.nth(self.plan.rng.randrange(min(rows.count(),8)))
        self.click(row)
        count=self.read_blocks(self.primary(),'[data-testid="messageEntry"]:visible, [data-testid="message"]:visible',3)
        return f"已有会话已读{count}项（可能改变已读回执），未发送消息"

    def extra_linked_surface(self,arg):
        pattern=r'^/i/spaces/[A-Za-z0-9]+' if arg=='spaces' else r'^/(?:i/)?articles?(?:/|$)'
        self.ensure_home()
        self.open_observed(pattern)
        # Space只读卡片和详情，不点击加入、申请发言或麦克风。
        count=self.read_blocks(self.primary(),limit=1)
        return f"{arg}实际入口与内容已读{count}项；未提交或加入"

    def extra_live(self,arg):
        self.ensure_home()
        art=self.require_article(lambda a,t:a.locator('a[href*="/i/broadcasts/"], [data-testid="liveVideoPlayer"]').count()>0,include_seen=True)
        if art.locator('a[href*="/i/broadcasts/"]').count():
            self.open_observed(r'^/i/broadcasts/',art)
        video=self.page.locator('video:visible').first
        if not video.count():raise ContentUnavailable("直播入口存在，但没有可见播放器")
        before=self.video_state(video); self.m.sleep(self.plan.rng.uniform(3,6)); after=self.video_state(video)
        if before['time']==after['time']:raise ContentUnavailable("直播或回放没有实际播放进度")
        return "直播或回放的可见播放进度已核实"

    def extra_notes(self,arg):
        self.ensure_home()
        selector='[data-testid="birdwatch-pivot"]:visible, [data-testid="communityNote"]:visible, [data-testid="birdwatch-note"]:visible'
        art=self.require_article(lambda a,t:a.locator(selector).count()>0,include_seen=True)
        count=self.read_blocks(art,selector,1)
        return f"已读{count}个可见社区附注；未撰写或评分"

    def extra_poll(self,arg):
        self.ensure_home()
        selector='[data-testid="cardPoll"]:visible, [data-testid="poll"]:visible, [data-testid^="pollOption"]:visible'
        art=self.require_article(lambda a,t:a.locator(selector).count()>0,include_seen=True)
        self.read_blocks(art,selector,1)
        return "已阅读投票选项或公开结果，未投票"

    def inspect_menu(self,kind):
        self.ensure_home(); art=self.require_article(include_seen=True)
        if kind=='post':
            button=art.locator('[data-testid="caret"]:visible').first
        else:
            button=art.get_by_role('button',name=re.compile(r'^(Share post|Share|分享帖子|分享推文|分享|Compartilhar post|Compartilhar|Compartir post|Compartir)$',re.I)).first
        if not button.count():raise ContentUnavailable("没有可识别的菜单按钮")
        self.click(button)
        try:
            self.read_blocks(self.page,'[role="menu"]:visible',1)
            return "菜单选项已读，未点击任何修改或发送项"
        finally:self.page.keyboard.press('Escape')

    def extra_post_menu(self,arg):return self.inspect_menu('post')
    def extra_share_menu(self,arg):return self.inspect_menu('share')

    def extra_like(self,arg):
        if not self.m.can_like():raise ContentUnavailable("点赞开关、次数上限或间隔条件不满足")
        self.ensure_home(); art=self.require_article()
        self.read(art,allow_like=False)
        before=self.m.stats['likes']; self.confirmed_like(art)
        if self.m.stats['likes']<=before:raise ContentUnavailable("点赞未确认成功，不重复点击")
        return "已读帖子点赞成功并核实按钮状态"

    def extra_comment(self,arg):
        if not self.m.cfg.comment_enabled:raise ContentUnavailable("未启用TXT评论")
        before=self.m.stats.get('comments_sent',0)
        self.ensure_home()
        if not self.m.comment_candidates:
            art=self.require_article()
            self.read(art,allow_like=False)
        self.maybe_comment()
        if self.m.stats.get('comments_sent',0)<=before:
            reason=self.m.stats.get('comment_status',{})
            raise ContentUnavailable("评论未确认新增："+str(reason.get('state','等待配额或间隔')))
        return "TXT评论已确认发布，沿用跨账号目标和文本全局去重"


    def poll(self, probe, requested_ms=6500):
        """等待真实页面条件；每次轮询都处理暂停/停止并驱动浏览器事件。"""
        deadline=time.monotonic()+self.timeout(requested_ms)/1000
        while True:
            self.gate()
            try:
                value=probe()
                if value:
                    return value
            except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):
                raise
            except Exception:
                self.gate()
                logger.debug("页面重绘，等待下一次快照",exc_info=True)
            left=deadline-time.monotonic()
            if left<=0:
                self.check_health()
                return None
            self.page.wait_for_timeout(min(150,left*1000))


    def feature_family(self,spec):
        if spec.handler in ('surface','collection'):
            return spec.arg
        if spec.handler=='community_rules':
            return 'communities'
        return None


    def retire_feature(self,family,reason):
        self.capabilities[family]={'state':'unavailable','reason':reason,'elapsed':round(self.m.clock.elapsed(),2)}
        for spec in WORKFLOW_SPECS:
            item=self.plan.items[spec.key]
            if self.feature_family(spec)==family and item['state']!='RUNNING' and item['attempts']<item['target']:
                self.plan.retire(spec.key,reason,'UNAVAILABLE')


    def prune_completed_actions(self):
        item=self.plan.items.get('comment_dispatch')
        if item and item['attempts']<item['target']:
            if self.m.comment_attempts>=self.m.cfg.comment_count:
                self.plan.retire('comment_dispatch','评论配额已完成；无需再次触发','SATISFIED')
            elif self.m.comment_halted:
                self.plan.retire('comment_dispatch','评论已暂停，阅读继续','SATISFIED')
        item=self.plan.items.get('like_read_post')
        if item and item['attempts']<item['target'] and self.m.like_attempts>=self.m.cfg.max_likes:
            self.plan.retire('like_read_post','点赞尝试上限已达到','SATISFIED')

    def diagnose_wait(self):
        """只记录布局计数，不采集正文、消息、表单或凭据。"""
        try:
            state=self.page.evaluate('''()=>{
                const count=s=>[...document.querySelectorAll(s)].filter(e=>e.getClientRects().length>0).length;
                return {path:location.pathname,ready:document.readyState,
                    primary:count('[data-testid="primaryColumn"]'),main:count('main,[role="main"]'),
                    dialog:count('[role="dialog"],[data-testid="sheetDialog"]'),
                    loading:count('[role="progressbar"],[aria-busy="true"]'),posts:count('[data-testid="tweet"]')};
            }''')
            records=self.m.stats.setdefault('page_wait_diagnostics',[])
            records.append(state);del records[:-12]
            self.m.log(f"页面等待诊断：{state}")
        except Exception:
            logger.debug("页面等待诊断不可用",exc_info=True)


    def persist(self) -> None:
        self.m.persist_workflow_plan()

    # ---------- V9：开局/收尾采集、场景间隙发送面板回复 ----------
    COLLECT_GRACE = 90.0  # 采集临时多给的秒数；采集用掉的时间不占单号阅读时长

    def service_step(self, label, fn):
        """执行一个采集/回复步骤：普通故障只记日志，停止/断连/登录失效照常向上抛。"""
        try:
            return fn()
        except FATAL_ERRORS:
            raise
        except SceneBudgetExceeded:
            self.m.log(f"{label}：时间预算用尽，已保存读到的部分。")
        except ContentUnavailable as exc:
            self.m.log(f"{label}：{exc}")
        except PlaywrightTimeoutError as exc:
            self.m.log(f"{label}超时：{short_error(exc)}")
        except Exception as exc:
            logger.warning("%s失败", label, exc_info=True)
            self.m.log(f"{label}失败：{short_error(exc)}")

    def _service(self, stage, collect, dispatch, blocking):
        m = self.m
        grace_before = m.grace_sec
        m.grace_sec = grace_before + self.COLLECT_GRACE
        started = m.clock.elapsed()
        before_success=m.stats.get('collections_successful',0)
        try:
            if getattr(m.cfg,'recent_action_batch',''):
                result=RecentInteractionRunner(self).run()
                m.stats['recent_action_result']=result.value
                return
            if m.cfg.performance_only:
                m.set_stage("collect_end" if stage=="end" else "collect_start")
                self.service_step("8小时帖子与回复统计",lambda:collect_recent_activity(ScoredAccountCollector(self)))
                return
            dispatcher = OutboxDispatcher(self)
            if dispatch and dispatcher.pending():
                m.set_stage("outbox")
                self.service_step("发送面板回复", lambda: dispatcher.run(blocking=blocking))
            if collect:
                m.set_stage("collect_end" if stage == "end" else "collect_start")
                self.service_step("采集账号数据", lambda: ScoredAccountCollector(self).run(stage))
        finally:
            m.grace_sec = grace_before + max(0.0, m.clock.elapsed() - started)
            m.last_service_at = m.clock.elapsed()
            if collect:
                m.last_collection_attempt_at=m.clock.elapsed()
                if m.stats.get('collections_successful',0)>before_success:m.last_collection_at=m.clock.elapsed()

    def guarded_service(self, stage):
        try:
            self._service(stage, self.m.cfg.stats_enabled, True, stage != "end")
            return None
        except StopRequested:
            return Result.STOPPED
        except (DurationReached, SceneBudgetExceeded):
            return None
        except CdpStateError:
            return Result.CDP_LOST
        except AccountStateError as exc:
            return exc.result

    def between_scenes(self):
        """仅在阅读片段结束时调用，采集和已排队回复合为一次维护。"""
        m, cfg = self.m, self.m.cfg
        now = m.clock.elapsed()
        if now - m.last_service_check < 20:
            return False
        m.last_service_check = now
        dispatcher = OutboxDispatcher(self)
        dispatch = dispatcher.pending() > 0 and dispatcher.wait_needed() <= 0 and not dispatcher.capped()
        collect = bool(cfg.stats_enabled and cfg.stats_interval_min > 0
                       and now - max(m.last_collection_at,m.last_collection_attempt_at) >= cfg.stats_interval_min * 60 and m.remaining() > 150)
        if not (dispatch or collect):
            return False
        snapshot=self.navigator.capture()
        try:
            self._service("periodic", collect, dispatch, False)
        finally:
            m.set_stage("workflows")
            m.scene_deadline=None
        self.navigator.restore(snapshot)
        return True

    def run_service(self) -> Result:
        """“立即同步”模式：只采集数据并发送面板里排队的回复，然后结束。"""
        m, cfg = self.m, self.m.cfg
        self.persist()
        m.set_stage("login")
        try:
            self.check_health()
            self._service("service", cfg.stats_enabled, True, True)
        except StopRequested:
            return Result.STOPPED
        except DurationReached:
            return Result.OK
        except SceneBudgetExceeded:
            return Result.PARTIAL
        except CdpStateError:
            return Result.CDP_LOST
        except AccountStateError as exc:
            return exc.result
        except ContentUnavailable as exc:
            m.log(f"页面异常，同步中止：{exc}")
            return Result.ERROR
        m.set_stage("close")
        return Result(m.stats.get('recent_action_result',Result.PLAN_DONE.value))

    def prime_reading(self):
        """先确认至少一条帖子可读，再做采集和可选工作流。"""
        m=self.m
        if m.stats.get('initial_read_done'):
            return
        m.set_stage('workflows')
        self.phase('等待首页帖子加载，准备首次阅读')
        self.ensure_home()
        for attempt in range(2):
            ready=self.poll(lambda:self.page.locator(SELECTORS['tweet']+':visible').count(),25000)
            if ready:
                break
            self.check_health()
            self.diagnose_wait()
            if attempt==1:
                raise ContentUnavailable('首页两轮等待仍无可读帖子，只跳过当前账号')
            m.stats['initial_load_retries']=1
            m.log('首页暂未出现帖子，原窗口刷新后再等待一次；其他账号继续运行。')
            self.page.reload(wait_until='domcontentloaded',timeout=self.timeout(15000))
            m.sleep(2)

        art=self.require_article(include_seen=True)
        entry=self.analyze_post(art)
        started=m.clock.elapsed()
        self.read(art,allow_like=False)
        entry['read']=True
        m.reading_cadence.record_reading(m.clock.elapsed()-started,1)
        self.audit_reading('first_read',entry)
        m.stats['initial_read_done']=True
        m.stats['first_read_at']=round(m.clock.elapsed(),2)
        m.log('首次帖子阅读已完成，开始正常浏览；辅助采集不会代替阅读。')

    def continue_reading(self):
        m=self.m
        self.current_key=None
        m.set_stage('primary_reading');m.workflow_name='主线阅读'
        m.scene_deadline=m.clock.elapsed()+min(30,m.remaining())
        try:
            self.ensure_home()
            art=self.viewport_article()
            if art is None:
                self.scroll(420)
                art=self.viewport_article()
            if art is not None:
                entry=self.analyze_post(art)
                m.set_stage('primary_reading')
                self.read(art,allow_like=False)
                entry['read']=True
                m.stats['continuous_reads']=m.stats.get('continuous_reads',0)+1
                m.stats['empty_feed_checks']=0
                return entry
            m.stats['empty_feed_checks']=m.stats.get('empty_feed_checks',0)+1
            self.phase('当前视口暂无未读帖子，继续等待信息流')
            if m.clock.elapsed()-m.stats.get('last_feed_reload_at',0)>=120:
                m.stats['last_feed_reload_at']=m.clock.elapsed()
                self.page.reload(wait_until='domcontentloaded',timeout=self.timeout(12000))
                m.stats['feed_refreshes']=m.stats.get('feed_refreshes',0)+1
                self.check_health()
            m.sleep(2)
            return None
        finally:m.scene_deadline=None


    def run(self) -> Result:
        m, cfg = self.m, self.m.cfg
        self.persist()
        m.set_stage("login")
        try:
            self.prime_reading()
        except StopRequested:return Result.STOPPED
        except DurationReached:
            return Result.OK if m.stats.get('reads',0)>0 else Result.NO_CONTENT
        except CdpStateError:return Result.CDP_LOST
        except AccountStateError as exc:return exc.result
        except (ContentUnavailable,SceneBudgetExceeded,PlaywrightTimeoutError) as exc:
            m.stats['end_reason']='首次阅读未完成：'+short_error(exc)
            m.log(m.stats['end_reason'])
            return Result.NO_CONTENT
        # 全量采集集中在收尾；设置了采集间隔时，仅在阅读片段边界执行。
        m.set_stage("workflows")
        result = self._run_core()
        collection_due=(not m.last_collection_attempt_at or m.clock.elapsed()-m.last_collection_attempt_at>=max(60,cfg.stats_interval_min*60))
        if (cfg.stats_enabled and collection_due and not m.stats.get("end_service_done")
                and result in (Result.OK, Result.PLAN_DONE, Result.NO_CONTENT, Result.PARTIAL)):
            m.stats["end_service_done"] = True
            final = self.guarded_service("end")
            if final is not None:
                return final
        return result

    def audit_reading(self, event, entry):
        try:
            self.m.report_path.parent.mkdir(parents=True,exist_ok=True)
            record={'event':event,'at':time.time(),'post':entry['id'],'url':entry['url'],'features':entry['features'],
                    'scores':entry['scores'],'actions':entry['actions'],'discussion':entry['discussion'],
                    'decision':entry.get('decisions',[None])[-1],
                    'chain_plan':entry.get('chain_plans',[None])[-1]}
            with self.m.report_path.with_suffix('.reading.jsonl').open('a',encoding='utf-8') as output:
                output.write(json.dumps(record,ensure_ascii=False)+'\n')
        except OSError:logger.warning('阅读审计写入失败',exc_info=True)

    def analyze_post(self, art):
        self.m.set_stage('post_analysis')
        self.phase('读取当前帖子的可见内容与互动指标')
        try:
            features=art.evaluate(POST_FEATURE_JS,timeout=self.timeout(2000))
            if not features.get('url'):features['url']=self.status_url(art)
        except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):raise
        except Exception as exc:
            features={'url':self.status_url(art),'text':self.text(art),'analysis_error':short_error(exc)}
            self.m.log('帖子结构暂未完全识别，回退到普通正文阅读。')
        entry=self.m.post_book.observe(features,self.m.cfg.interest_terms)
        entry['source']={'url':self.page.url,'scroll':self.page.evaluate('window.scrollY'),'anchor':entry['url']}
        self.m.current_post=entry['id']
        self.m.stats['posts_scored']=self.m.post_book.total_posts
        self.m.stats['current_post']={k:entry[k] for k in ('id','url','scores')}
        return entry

    def workflow_available(self, key, remaining):
        item=self.plan.items.get(key)
        if not item:return '工作流不存在'
        if not item['target'] or item['attempts']>=item['target']:return '已禁用或配额已用尽'
        if item.get('defer_until',0)>self.m.clock.elapsed():return '工作流冷却中'
        if WORKFLOW_BY_KEY[key].manual_only:return '手动操作'
        if WORKFLOW_BY_KEY[key].minimum_sec>remaining:return '剩余预算不足'
        return None

    def comment_wait_multiplier(self, eligible):
        m=self.m;p=reading_policy(m.cfg)
        if not eligible:
            m.comment_eligible_since=None
            m.stats['comment_priority']={'eligible':False,'waiting_seconds':0,'multiplier':1.0}
            return 1.0
        now=m.clock.elapsed()
        if m.comment_eligible_since is None:m.comment_eligible_since=now
        waited=max(0.0,now-m.comment_eligible_since)
        cap=p['comment_age_boost_cap']
        boost=1+(cap-1)*min(1.0,waited/p['comment_age_ramp'])
        m.stats['comment_priority']={'eligible_since':m.comment_eligible_since,'waiting_seconds':round(waited,2),'multiplier':round(boost,3)}
        return boost

    def content_candidates(self, entry):
        f,s=entry['features'],entry['scores']
        p=reading_policy(self.m.cfg)
        rows=[]
        def add(keys,family,score,condition=True,crosspage=False):
            for key in keys:
                rows.append({'key':key,'family':family,'score':score or 0,'condition':bool(condition),'crosspage':crosspage})
        add(('long_read','detail_read','source_restore'),'body',s['body'],s['body']>=p['body_threshold'] or f.get('expand'))
        add(('interest',),'body',s['relevance'],bool(s['matched_terms']))
        add(('translate_read',),'body',s['body'],f.get('translate'))
        add(('gallery','image_alt'),'image',s['image'],f.get('images') and s['image']>=p['image_threshold'],True)
        add(('gif_read',),'video',s['video'],f.get('gif'),False)
        add(('video','video_review'),'video',s['video'],f.get('video') and s['video']>=p['video_threshold'])
        add(('comments','reply_branch'),'discussion',s['discussion'],self.m.cfg.enable_deep_visit and s['discussion'] is not None and s['discussion']>=p['discussion_threshold'],True)
        add(('thread_read',),'discussion',s['body'],self.m.cfg.enable_deep_visit and f.get('thread'),True)
        add(('profile','profile_media','profile_replies','profile_articles','profile_followers','profile_following'),'author',s['author'],s['author']>=p['author_threshold'],True)
        add(('quote_context',),'quote',s['body'],bool(f.get('quote_url')),True)
        add(('hashtag_read',),'topic',s['relevance'] or s['body'],bool(f.get('hashtags')),True)
        add(('mention_read',),'mention',s['author'],bool(f.get('mentions')) and s['author']>=p['author_threshold'],True)
        add(('external_read',),'external',s['relevance'],bool(s['matched_terms']) and bool(f.get('external_links')),True)
        add(('poll_read',),'poll',s['body'],f.get('poll'))
        add(('notes_read',),'notes',s['body'],f.get('notes'))
        for key,pattern in (('spaces_read','/i/spaces/'),('live_read','/i/broadcasts/'),('articles_read','/i/article')):
            add((key,),key,s['body'],any(pattern in h for h in f.get('specials',[])),True)
        add(('like_read_post',),'like',s['overall'],self.m.cfg.enable_like and self.m.cfg.p_like>0 and self.m.can_like())
        comment_ready=(self.m.cfg.comment_enabled and not self.m.comment_halted and self.m.comment_attempts<self.m.cfg.comment_count
                       and self.m.clock.elapsed()>=self.m.comment_retry_at and entry['id'] not in self.m.comment_skipped_targets)
        if comment_ready:
            if self.commenter is None:self.commenter=ScoredCommentPublisher(self)
            comment_ready=self.commenter.store.cooldown(self.m.browser_id,self.m.cfg.comment_interval)<=0
        comment_ready=comment_ready and self.workflow_available('comment_dispatch',min(p['step_budget'],p['chain_budget'],self.m.remaining()-p['restore_budget'])) is None
        comment_boost=self.comment_wait_multiplier(comment_ready)
        add(('comment_dispatch',),'comment',s['overall'],comment_ready,True)
        candidates=[]; filtered=[]; used=set()
        for row in rows:
            key=row['key']; family=row['family']
            reason=self.workflow_available(key,min(p['step_budget'],p['chain_budget'],self.m.remaining()-p['restore_budget']))
            if not row['condition']:reason=reason or '当前内容、评分或用户权限不满足'
            if key in entry['actions'] or family in {a.get('family') for a in entry['actions'].values()}:reason=reason or '本帖该阅读步骤已尝试'
            if reason:filtered.append({'key':key,'reason':reason});continue
            if family in used:continue  # 同类入口合并，避免同一功能因别名多而增加概率。
            used.add(family)
            item=self.plan.items[key]
            row['weight']=round(item['weight']*math.sqrt(max(1,item['target']-item['attempts']))*(.25+row['score']/100),4)
            if key=='like_read_post':row['weight']*=self.m.cfg.p_like
            if key=='comment_dispatch':
                row['age_multiplier']=comment_boost
                row['weight']*=comment_boost
            candidates.append(row)
        return candidates,filtered

    def exploration_candidates(self, entry):
        p=reading_policy(self.m.cfg)
        keys=('search','search_top','search_people','search_photos','search_videos','search_refine','search_history',
              'following','explore_read','trend_read','custom_timeline','revisit','session_resume','bookmarks_read','history_read','lists_read',
              'notifications','notifications_mentions','own_profile','messages_read','communities_read','community_rules','grok_history',
              'settings_read','premium_read','creator_read','security_read','account_read','accessibility_read','preference_read')
        candidates=[];filtered=[]
        if self.m.clock.elapsed()-self.m.last_explore_at<p['explore_interval']:
            return [],[{'key':'exploration','reason':'独立探索间隔未到'}]
        for key in keys:
            reason=self.workflow_available(key,min(p['step_budget'],p['chain_budget'],self.m.remaining()-p['restore_budget']))
            if key.startswith('search') and not entry['scores']['matched_terms']:reason=reason or '当前帖子未产生关键词关联'
            if key in ('revisit','session_resume') and not self.m.journal.pending():reason=reason or '没有未读完的历史'
            if not reason:
                condition=self.trigger_condition(key)
                if condition:reason=condition
            if reason:filtered.append({'key':key,'reason':reason});continue
            item=self.plan.items[key]
            candidates.append({'key':key,'family':'explore','crosspage':True,'score':0,
                'weight':item['weight']*math.sqrt(max(1,item['target']-item['attempts']))})
        return candidates,filtered

    def choose_post_path(self, entry):
        m=self.m;p=reading_policy(m.cfg)
        candidates,filtered=self.content_candidates(entry)
        exploration,rejected=self.exploration_candidates(entry)
        ready=m.reading_cadence.ready(m.remaining(),m.cfg,m.clock.elapsed())
        weights=[p['main_weight'],p['content_weight'] if candidates and ready else 0,p['explore_weight'] if exploration and ready else 0]
        group=self.plan.rng.choices(('main','content','explore'),weights=weights,k=1)[0]
        pool=candidates if group=='content' else exploration if group=='explore' else []
        selected=self.plan.rng.choices(pool,weights=[r['weight'] for r in pool],k=1)[0] if pool else None
        total=sum(weights)
        decision={'at':round(m.clock.elapsed(),2),'group':group,'selected':selected['key'] if selected else None,
                  'group_probabilities':dict(zip(('main','content','explore'),[round(w/total,6) for w in weights])),
                  'conditional_probabilities':{r['key']:round(r['weight']/sum(x['weight'] for x in pool),6) for r in pool},
                  'candidates':candidates,'exploration':exploration,'filtered':filtered+rejected,
                  'reason':'按评分和已呈现入口选择' if selected else '正常继续阅读' if ready else '阅读进度、冷却或时间预算尚不适合支线'}
        entry.setdefault('decisions',[]).append(decision)
        entry['decisions']=entry['decisions'][-5:]
        m.stats['last_decision']=decision
        self.audit_reading('decision',entry)
        m.log(f"逐帖决策 {entry['id']}：综合 {entry['scores']['overall']:g}，讨论 {entry['scores']['discussion']}，{decision['reason']} → {decision['selected'] or '主线'}")
        return group,selected

    def execute_bound_step(self, row, entry):
        key=row['key'];f=entry['features'];url=entry['url']
        art=self.article_by_url(url,navigate_if_missing=True)
        if row['family']=='body':
            if key=='translate_read':return self.extra_translate('')
            self.read(art,deep=True,allow_like=False)
            self.analyze_post(self.article_by_url(url))
            return '当前帖正文已展开或深入阅读'
        if row['family']=='image':
            self.m.set_stage('images')
            return self.extra_image_alt('') if key=='image_alt' else self.gallery()
        if row['family']=='video':
            self.m.set_stage('video_reading')
            return self.extra_gif('') if key=='gif_read' else self.extra_video_review('') if key=='video_review' else self.video()
        if row['family']=='discussion':
            root=self.open_detail(art)
            return self.read_scored_discussion(root,entry)
        if row['family']=='comment':
            pending=self.m.comment_candidates
            pending.pop(entry['id'],None)
            self.m.comment_candidates=OrderedDict([(entry['id'],url)])
            before=self.m.stats.get('comments_sent',0)
            before_attempts=self.m.comment_attempts
            try:self.maybe_comment()
            finally:
                pending.update(self.m.comment_candidates)
                self.m.comment_candidates=pending
                if self.m.comment_attempts>before_attempts or self.m.stats.get('comments_sent',0)>before:self.m.comment_eligible_since=None
            if self.m.stats.get('comments_sent',0)<=before:raise ContentUnavailable('评论未确认新增，继续阅读；沿用原提交隔离状态')
            return '评论已确认'
        if row['family']=='like':
            before=self.m.stats.get('likes',0)
            self.confirmed_like(art)
            if self.m.stats.get('likes',0)<=before:raise ContentUnavailable('点赞未确认，保留原尝试计数，不重复提交')
            return '当前已读帖点赞已核实'
        if row['family']=='author':
            self.plan.items[key]['context_url']=url
            return self.execute_workflow(key)
        if row['family']=='quote':
            target=canonical_status_url(f.get('quote_url') or '')
            if not target or target==url:raise ContentUnavailable('引用原帖链接未确认')
            self.navigator.goto(target)
            self.read(self.article_by_url(target),deep=True,allow_like=False)
            return '关联原帖已阅读'
        if row['family'] in ('topic','mention'):
            links=f['hashtags'] if row['family']=='topic' else f['mentions']
            self.navigator.goto('https://x.com'+links[0])
            self.read_any_posts(1)
            return '当前帖中的话题或提及内容已阅读'
        if row['family']=='external':return self.extra_external('')
        if row['family'] in ('poll','notes'):
            selector='[data-testid="cardPoll"], [data-testid="poll"]' if row['family']=='poll' else '[data-testid="birdwatch-pivot"], [data-testid="communityNote"]'
            text=art.locator(selector).first.inner_text(timeout=self.timeout(1500))
            if not text.strip():raise ContentUnavailable('内容入口存在，但没有可读文字')
            self.m.sleep(min(6,max(2,len(text)/40)))
            return '已阅读当前可见内容，未投票或改变状态'
        links=f.get('specials',[])
        pattern={'spaces_read':'/i/spaces/','live_read':'/i/broadcasts/','articles_read':'/i/article'}.get(key)
        target=next((h for h in links if pattern and pattern in h),None)
        if not target:raise ContentUnavailable('当前特殊内容入口已消失')
        self.navigator.goto(target if is_x_url(target) else 'https://x.com'+target)
        self.read_blocks(self.primary(),limit=1)
        return '当前关联特殊内容已查看'

    def restore_reading_source(self, snapshot):
        m=self.m;p=reading_policy(m.cfg)
        m.set_stage('restore')
        m.scene_deadline=m.clock.elapsed()+min(p['restore_budget'],m.remaining())
        self._restoring=True
        try:self.navigator.restore(snapshot)
        finally:self._restoring=False
        m.stats['source_restores']=m.stats.get('source_restores',0)+1
        m.stats['last_return']={'url':self.page.url,'scroll':self.page.evaluate('window.scrollY'),'anchor':snapshot.anchor}

    def plan_reading_chain(self, entry, group, selected, budget):
        """只对已通过条件的同帖候选规划步骤，入口抽样与链内顺序分离。"""
        p=reading_policy(self.m.cfg)
        if group!='content' or selected['family'] not in ('body','image','video','discussion','poll','notes','quote'):
            return [dict(selected)]
        current,_=self.content_candidates(entry)
        sequence={'body':0,'image':1,'video':1,'poll':2,'notes':2,'discussion':3,'quote':4}
        # 选中的候选作为锚点保留；其余步骤按各自维度价值选择，而非强制遍历目录。
        extras=[r for r in current if r['family'] in sequence and r['family']!=selected['family']]
        if selected['family']=='quote':extras=[r for r in extras if r['family'] in ('body','image','video')]
        else:extras=[r for r in extras if r['family']!='quote']
        extras.sort(key=lambda r:(-r['score'],sequence[r['family']],r['key']))
        def minimum(row):return float(WORKFLOW_BY_KEY[row['key']].minimum_sec)
        rows=[dict(selected)];estimate=minimum(selected);families={selected['family']}
        crossings=int(selected['crosspage'])
        for row in extras:
            if len(rows)>=p['max_chain_steps']:break
            cost=minimum(row)
            if row['family'] in families or estimate+cost>budget:continue
            if crossings+int(row['crosspage'])>p['max_crosspage_steps']:continue
            rows.append(dict(row));families.add(row['family']);estimate+=cost;crossings+=int(row['crosspage'])
        rows.sort(key=lambda r:(sequence[r['family']],-r['score'],r['key']))
        return rows

    def run_reading_chain(self, entry, group, first):
        m=self.m;p=reading_policy(m.cfg)
        snapshot=self.navigator.capture()
        started=m.clock.elapsed();deadline=started+min(p['chain_budget'],max(0,m.remaining()-p['restore_budget']))
        rows=self.plan_reading_chain(entry,group,first,deadline-started)
        chain={'anchor':first['key'],'group':group,'planned':[r['key'] for r in rows],
               'budget_seconds':round(deadline-started,2),'executed':[],'skipped':[],'status':'running','return_status':'not_needed','started_at':round(started,2)}
        entry.setdefault('chain_plans',[]).append(chain)
        entry['chain_plans']=entry['chain_plans'][-5:]
        m.stats['planned_reading_chain']=chain
        m.log(f"同帖计划 {entry['id']}："+' → '.join(WORKFLOW_BY_KEY[r['key']].label for r in rows))
        self.audit_reading('chain_plan',entry)
        crossings=0;fatal=None;had_error=False
        self._bound_entry=entry if group=='content' else None
        self._chain_navigation_count=0
        if group=='explore':m.last_explore_at=started
        try:
            for index,row in enumerate(rows):
                key=row['key']
                if index and group=='content':
                    available,_=self.content_candidates(entry)
                    if key not in {r['key'] for r in available}:
                        chain['skipped'].append({'key':key,'reason':'阅读后内容、冷却或配额条件已变化'})
                        continue
                if m.clock.elapsed()>=deadline or m.remaining()<=p['restore_budget']:break
                if row['crosspage'] and crossings>=p['max_crosspage_steps']:break
                if self.workflow_available(key,min(p['step_budget'],deadline-m.clock.elapsed())):break
                m.set_stage('content_branch' if group=='content' else 'exploration')
                m.workflow_name=WORKFLOW_BY_KEY[key].label
                self.current_key=key
                self.plan.begin(key)
                m.scene_deadline=min(deadline,m.clock.elapsed()+min(p['step_budget'],WORKFLOW_BY_KEY[key].budget_sec))
                step_started=m.clock.elapsed();outcome='completed';reason='';before_url=self.page.url
                try:
                    reason=self.execute_bound_step(row,entry) if group=='content' else self.execute_workflow(key)
                except (StopRequested,DurationReached,CdpStateError,AccountStateError) as exc:
                    fatal=exc;outcome='interrupted';reason=short_error(exc)
                except (ContentUnavailable,PlaywrightTimeoutError,SceneBudgetExceeded) as exc:
                    outcome='skipped';reason=short_error(exc);had_error=True
                except Exception as exc:
                    outcome='failed';reason=short_error(exc);had_error=True
                    logger.warning('同帖支线失败 %s',key,exc_info=True)
                finally:
                    action={'family':row['family'],'state':outcome,'reason':reason,'seconds':round(m.clock.elapsed()-step_started,2),
                            'source':before_url,'ended_url':self.page.url}
                    entry['actions'][key]=action
                    chain['executed'].append(key)
                    self.audit_reading('action',entry)
                    self.plan.finish(key,outcome,reason,m.clock.elapsed())
                    self.current_key=None
                    m.scene_deadline=None
                    if row['crosspage']:crossings+=1
                    m.log(f"阅读链 {entry['id']} / {key}：{outcome}，{reason}")
                    self.persist()
                if fatal is not None or had_error or group=='explore' or row['family'] in ('comment','like'):break
                if not same_x_route(self.page.url or '',entry['url']) and not same_x_route(self.page.url or '',snapshot.url):
                    # 图片查看器由图片处理器关闭；其他跨页步骤不为接下一项重复来回跳转。
                    if row['family']!='image':break
        finally:
            self._bound_entry=None
            self._chain_navigation_count=None
            self.current_key=None
            m.scene_deadline=None
            try:
                if fatal is None:
                    if any(r['family']=='image' and r['key'] in chain['executed'] for r in rows) and self.photo_state().get('open'):
                        self.page.keyboard.press('Escape')
                        if self.photo_state().get('open'):raise ContentUnavailable('图片查看器未能关闭，保留状态供检查')
                    needs_restore=not same_x_route(self.page.url or '',snapshot.url)
                    # 同路由的评论滚动也必须恢复；单纯正文展开不重置当前位置。
                    needs_restore=needs_restore or any(r['family'] in ('discussion','explore','author') and r['key'] in chain['executed'] for r in rows)
                    if needs_restore:
                        chain['return_status']='restoring'
                        self.restore_reading_source(snapshot)
                        chain['return_status']='restored'
            except (StopRequested,DurationReached,CdpStateError,AccountStateError):
                chain['return_status']='interrupted'
                raise
            except Exception as exc:
                chain['return_status']='failed'
                m.stats['return_failures']=m.stats.get('return_failures',0)+1
                m.log('阅读来源恢复失败，只结束当前账号：'+short_error(exc))
                raise AccountStateError(Result.ERROR) from exc
            finally:
                m.scene_deadline=None
                m.reading_cadence.finish_extra(m.clock.elapsed()-started,m.clock.elapsed())
                m.stats['reading_cadence']=dataclasses.asdict(m.reading_cadence)
                m.current_post=entry['id'];m.post_book.current=entry['id']
                m.set_stage('primary_reading')
                chain['seconds']=round(m.clock.elapsed()-started,2)
                chain['status']='return_failed' if chain['return_status']=='failed' else 'interrupted' if fatal or chain['return_status']=='interrupted' else 'partial' if had_error or len(chain['executed'])<len(chain['planned']) else 'completed'
                chain['remaining']=[key for key in chain['planned'] if key not in chain['executed']]
                self.audit_reading('chain_end',entry)
                self.persist()
        if fatal is not None:raise fatal

    def browse_primary(self):
        m=self.m
        started=m.clock.elapsed();reads=m.stats.get('reads',0)
        entry=None
        try:entry=self.continue_reading()
        finally:
            m.reading_cadence.record_reading(m.clock.elapsed()-started,m.stats.get('reads',0)-reads)
            m.stats['reading_cadence']=dataclasses.asdict(m.reading_cadence)
        if entry:
            if m.reading_cadence.ready(m.remaining(),m.cfg,m.clock.elapsed()):
                before=m.clock.elapsed()
                try:maintained=self.between_scenes()
                except Exception:
                    m.reading_cadence.finish_extra(m.clock.elapsed()-before,m.clock.elapsed())
                    raise
                if maintained:
                    m.reading_cadence.finish_extra(m.clock.elapsed()-before,m.clock.elapsed())
                    self.scroll(380)
                    return
            group,selected=self.choose_post_path(entry)
            if selected:self.run_reading_chain(entry,group,selected)
            m.set_stage('primary_reading')
            if self.viewport_article() is None:self.scroll(380)

    def _run_core(self) -> Result:
        self.persist()
        recoveries=0
        while self.m.remaining()>0:
            try:
                self.gate();self.check_health();self.prune_completed_actions()
                self.browse_primary()
                recoveries=0
            except SceneBudgetExceeded:
                self.m.scene_deadline=None
                self.m.log('当前阅读片段到时，继续主线。')
            except DurationReached:
                self.m.stats['end_reason']='总时长预算已用尽'
                return Result.OK if self.m.stats.get('reads',0)>0 else Result.NO_CONTENT
            except StopRequested:return Result.STOPPED
            except CdpStateError:return Result.CDP_LOST
            except AccountStateError as exc:return exc.result
            except (ContentUnavailable,PlaywrightTimeoutError) as exc:
                recoveries+=1
                self.m.scene_deadline=None
                if recoveries>MAX_RELOADS:
                    self.m.stats['end_reason']=short_error(exc)
                    return Result.ERROR
                self.m.log(f'当前账号页面恢复 {recoveries}/{MAX_RELOADS}：{short_error(exc)}')
                try:
                    self.ensure_home()
                    self.m.sleep(min(8,2**recoveries))
                except StopRequested:return Result.STOPPED
                except DurationReached:return Result.OK if self.m.stats.get('reads',0)>0 else Result.NO_CONTENT
                except CdpStateError:return Result.CDP_LOST
                except AccountStateError as state:return state.result
                except (ContentUnavailable,PlaywrightTimeoutError):pass
        return Result.OK if self.m.stats.get('reads',0)>0 else Result.NO_CONTENT


    def discussion_rows(self, root, allow_missing=False):
        if (canonical_status_url(self.page.url or '') or '').rsplit('/',1)[-1]!=root.rsplit('/',1)[-1]:
            raise ContentUnavailable('讨论详情页ID不匹配')
        return self.page.evaluate(DISCUSSION_ROWS_JS,{'root':root.rsplit('/',1)[-1],'allowMissingRoot':allow_missing})

    def read_scored_discussion(self, root_url, entry):
        m=self.m;p=reading_policy(m.cfg)
        state=entry['discussion'];seen=set(state['seen']);visited=set();expanded=set(state['expanded'])
        reads_before=len(seen);expands=0;new_count=0
        stop_at=min(m.scene_deadline or math.inf,m.clock.elapsed()+p['discussion_budget'])
        previous_deadline=m.scene_deadline
        m.scene_deadline=stop_at
        self.m.journal.discussion(root_url,True,float(self.page.evaluate('window.scrollY')))
        def edge(parent,row,depth,evidence):
            record={'context_parent':parent.rsplit('/',1)[-1],'reply':row['id'],'depth':depth,
                    'confirmed_parent':row.get('parent'),'relation':row.get('relation',evidence),'evidence':evidence}
            if not any(e.get('reply')==record['reply'] and e.get('context_parent')==record['context_parent'] for e in state['edges']):
                state['edges'].append(record)
            state['edges']=state['edges'][-200:]
        def walk(parent,depth):
            nonlocal expands,new_count
            parent_id=parent.rsplit('/',1)[-1]
            if parent_id in visited:return
            visited.add(parent_id)
            if (canonical_status_url(self.page.url or '') or '').rsplit('/',1)[-1]!=parent_id:
                raise ContentUnavailable('回复分支未到达预期详情页')
            self.article_by_url(parent)
            idle=0;allow_missing=False
            while m.clock.elapsed()<stop_at and new_count<p['max_discussion_reads']:
                self.gate()
                m.set_stage('subcomments' if depth else 'discussion')
                self.phase(f'阅读讨论上下文，第 {depth} 层；直接父级只记录页面可确认的关系')
                rows=self.discussion_rows(parent,allow_missing)
                unseen=[r for r in rows if r['id'] not in seen and r['id'] not in visited]
                if not unseen:
                    idle+=1
                    if idle>=3:return
                    self.scroll(300)
                    m.sleep(.5)
                    allow_missing=bool(rows) or allow_missing
                    continue
                idle=0
                for row in unseen:
                    if new_count>=p['max_discussion_reads']:return
                    self.gate()
                    art=self.article_by_url(row['url'],wait=False)
                    if not art.count():continue
                    art.scroll_into_view_if_needed(timeout=self.timeout(1200))
                    reply_entry=self.analyze_post(art)
                    self.read(art,allow_like=False)
                    reply_entry['read']=True
                    seen.add(row['id']);new_count+=1
                    previous_edge=next((e for e in state['edges'] if e['reply']==row['id'] and e.get('evidence')=='通过该回复所属单元的展开入口出现'),None)
                    row_depth=previous_edge['depth'] if previous_edge else depth
                    counter='subcomments_read' if row_depth else 'comments_read'
                    m.stats[counter]=m.stats.get(counter,0)+1
                    edge(parent,row,row_depth,'已确认会话容器及阅读上下文，不推断未知的直接父级')
                    text=row.get('text') or ''
                    quality=score_clip(min(70,len(text)/3)+30*bool(reply_entry['scores']['matched_terms']))
                    old=entry['scores']['discussion']
                    entry['scores']['discussion']=score_clip((old or quality)*.7+quality*.3)
                    entry['scores']['evidence']['visible_reply_quality']=quality
                    m.log(f"讨论阅读 {row['id']}：层级 {depth}，关系 {row.get('relation')}，内容价值 {quality:g}")
                    if row_depth>=p['max_discussion_depth'] or expands>=p['max_reply_expands']:continue
                    worthwhile=quality>=p['discussion_threshold'] or bool(reply_entry['scores']['matched_terms'])
                    if not worthwhile:continue
                    token=row['id']+':expand'
                    if token in expanded:continue
                    if row.get('expand'):
                        scope=art.locator("xpath=ancestor::*[@data-testid='cellInnerDiv'][1]")
                        if not scope.count():scope=art
                        button=scope.get_by_role('button',name=re.compile(r'^(Show (more )?replies|View (more )?replies|显示(更多)?回复|查看(更多)?回复|更多回复|顯示(更多)?回覆|Ver (mais )?respostas|Mostrar (más )?respuestas)(\s|$)',re.I)).first
                        if not button.count():
                            button=scope.get_by_role('link',name=re.compile(r'^(Show (more )?replies|显示(更多)?回复|更多回复)(\s|$)',re.I)).first
                        if button.count() and button.is_visible():
                            expanded.add(token);expands+=1
                            before={r['id'] for r in rows}
                            origin=self.navigator.capture()
                            self.click(button)
                            current=(canonical_status_url(self.page.url or '') or '').rsplit('/',1)[-1]
                            if current!=parent_id:
                                if current!=row['id']:raise ContentUnavailable('展开回复离开预期讨论，停止当前支线')
                                try:walk(row['url'],row_depth+1)
                                finally:
                                    self._restoring=True
                                    try:self.navigator.restore(origin)
                                    finally:self._restoring=False
                                continue
                            added=self.poll(lambda:[r for r in self.discussion_rows(parent,True) if r['id'] not in before],2200)
                            if not added:
                                m.log('展开入口未出现新回复，记录后不重复点击。')
                            else:
                                for child in added:edge(row['url'],child,row_depth+1,'通过该回复所属单元的展开入口出现')
                            # 新出现的回复在下一轮正常去重阅读，不在点击后重复导航。
                    elif (observed_count(row.get('replies')) or 0)>0:
                        expanded.add(token);expands+=1
                        snapshot=self.navigator.capture()
                        self.open_detail(self.article_by_url(row['url'],wait=False))
                        try:walk(row['url'],row_depth+1)
                        finally:
                            if not m.ctl.is_stopped() and m.remaining()>0:
                                m.scene_deadline=min(stop_at,m.clock.elapsed()+p['restore_budget'])
                                self._restoring=True
                                try:self.navigator.restore(snapshot)
                                finally:self._restoring=False
                                m.scene_deadline=stop_at
                if m.clock.elapsed()>=stop_at:return
                self.scroll(260)
                allow_missing=True
        completed=False
        try:
            walk(root_url,0)
            completed=True
        finally:
            state['seen']=list(seen)[-200:]
            state['expanded']=list(expanded)[-100:]
            state['last_result']={'new_reads':len(seen)-reads_before,'expands':expands,'finished':completed}
            m.scene_deadline=previous_deadline
            m.current_post=entry['id'];m.post_book.current=entry['id']
            m.journal.discussion(root_url,not completed)
        if not new_count:return '会话边界内暂无可确认的新回复，正常结束讨论'
        return f'已阅读 {new_count} 条会话回复，展开 {expands} 次；未知直接父级保留为上下文关系'


class ScoredCommentPublisher:
    EDITOR = '[contenteditable="true"][data-testid^="tweetTextarea_"]:visible, [data-testid^="tweetTextarea_"] [contenteditable="true"]:visible'
    SEND = '[data-testid="tweetButton"]:visible, [data-testid="tweetButtonInline"]:visible'

    def __init__(self, executor):
        self.e, self.m, self.source = executor, executor.m, executor.page
        self.page = None
        self.store = CommentStore()
        self.stage, self.surface = "等待", ""
        self.deadline = None

    def state(self, name, reason=""):
        m = self.m
        previous = m.stats.get("comment_status")
        m.stats["comment_status"] = {"state":name,"reason":reason}
        if previous != m.stats["comment_status"]:
            m.log(f"评论状态：{name}" + (f"｜{reason}" if reason else ""))

    def gate(self):
        self.e.gate()
        if self.deadline is not None and self.m.clock.elapsed() >= self.deadline:
            raise SceneBudgetExceeded("评论操作预算用尽")
        if self.page is not None and self.page.is_closed():
            raise ContentUnavailable("当前评论页面已关闭")

    def timeout(self, ms):
        self.gate()
        left = self.m.remaining()
        if self.deadline is not None:
            left = min(left,self.deadline-self.m.clock.elapsed())
        return max(1,int(min(T(ms),left*1000)))

    def pump(self):
        self.gate()
        # 必须驱动 Playwright 事件循环，否则 threading.sleep 期间响应监听不会派发。
        self.page.wait_for_timeout(min(100,self.timeout(100)))
        self.gate()

    def poll(self, fn, seconds):
        end = self.m.clock.elapsed() + seconds
        while self.m.clock.elapsed() < end:
            self.gate()
            result = fn()
            if result is not None:
                return result
            self.pump()
        return None

    def health(self):
        status = check_page_health(self.page)
        if status == "logged_out":
            raise AccountStateError(Result.LOGIN_LOST)
        if status == "needs_action":
            raise AccountStateError(Result.NEEDS_ACTION)
        if status == "error_page":
            raise ContentUnavailable("目标推文页面加载失败")

    def root_article(self, target):
        link = self.page.locator(f'a[href$="/status/{target}"]:has(time), a[href*="/status/{target}?"]:has(time)')
        return self.page.locator('article[data-testid="tweet"]').filter(has=link).first

    def find_composer(self):
        # 先找弹窗，再找详情页内嵌输入框；不假设必须有 role=dialog。
        dialogs = self.page.locator('[role="dialog"]:visible')
        for index in range(dialogs.count()-1,-1,-1):
            dialog = dialogs.nth(index)
            editors = dialog.locator(self.EDITOR)
            if editors.count():
                return editors.first, "弹窗"
        editors = self.page.locator(self.EDITOR)
        for index in range(editors.count()):
            editor = editors.nth(index)
            if not editor.locator('xpath=ancestor::article').count():
                return editor, "详情页内嵌"
        return None

    def open_composer(self, target):
        self.health()
        article = self.root_article(target)
        article.wait_for(state="visible",timeout=self.timeout(10000))
        composer = self.poll(self.find_composer,2)
        if composer is not None:
            return composer
        self.stage = "打开回复输入框"
        button = article.locator('[data-testid="reply"]:visible').first
        button.wait_for(state="visible",timeout=self.timeout(6000))
        if not button.is_enabled():
            raise ContentUnavailable("本推文不允许当前账号回复")
        button.scroll_into_view_if_needed(timeout=self.timeout(4000))
        # 打开入口可有限重试；实际提交仅在 submit_once 中进行一次。
        for attempt in range(2):
            self.gate()
            try:
                self.m.behavior.click(self.page,button,timeout=self.timeout(6000))
            except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):
                raise
            except Exception:
                logger.debug("回复入口点击未确认",exc_info=True)
            composer = self.poll(self.find_composer,4)
            if composer is not None:
                return composer
            self.health()
            article = self.root_article(target)
            button = article.locator('[data-testid="reply"]:visible').first
        raise ContentUnavailable("回复入口未出现输入框，可能被遮挡或没有回复权限")

    def send_button(self, editor):
        # 绑定到此输入框最近的提交容器，避免点到普通发帖或其他推文的按钮。
        container = editor.locator('xpath=ancestor::*[.//*[@data-testid="tweetButton"] or .//*[@data-testid="tweetButtonInline"]][1]')
        buttons = container.locator(self.SEND) if container.count() else self.page.locator('[data-testid="tweetButtonInline"]:visible')
        for index in range(buttons.count()):
            button = buttons.nth(index)
            if button.is_visible() and button.is_enabled():
                return button
        return None

    def fill_composer(self, editor, text):
        self.stage = "填写评论"
        previous = normalize_comment_text(editor.inner_text(timeout=self.timeout(2000)))
        wanted = normalize_comment_text(text)
        if previous and previous != wanted:
            raise ValueError("回复框已有不同内容，保留已有草稿，未覆盖")
        if previous != wanted:
            editor.fill(text,timeout=self.timeout(6000))
        if normalize_comment_text(editor.inner_text(timeout=self.timeout(2000))) != wanted:
            raise ValueError("评论输入校验失败，未点击发送")
        button = self.poll(lambda:self.send_button(editor),3)
        if button is None:
            # 受控输入框有时需键盘输入事件才能刷新提交状态；只操作本次相同内容。
            self.stage = "等待输入框同步"
            self.m.behavior.click(self.page,editor,timeout=self.timeout(2000))
            editor.press("Meta+A" if sys.platform == "darwin" else "Control+A",timeout=self.timeout(2000))
            editor.press("Backspace",timeout=self.timeout(2000))
            self.page.keyboard.insert_text(text)
            editor.press("ArrowRight",timeout=self.timeout(2000))
            if normalize_comment_text(editor.inner_text(timeout=self.timeout(2000))) != wanted:
                raise ValueError("键盘输入校验失败，未点击发送")
            button = self.poll(lambda:self.send_button(editor),4)
        if button is None:
            raise ValueError("评论按钮持续不可用，请检查文本长度、账号状态或回复权限")
        return button

    def mark_sending(self, target):
        self.store.update(self.m.browser_id,target,self.m.browser_id,"sending")

    def count_attempt(self):
        self.m.comment_attempts += 1
        self.m.stats["comment_attempts"] = self.m.comment_attempts

    def submit_once(self, button, text, target):
        m, responses, requests = self.m, [], []
        def on_request(request):
            if reply_request_variables(request,text,target) is not None:
                requests.append(request)
        def on_response(response):
            if reply_request_variables(response.request,text,target) is not None:
                responses.append(response)
        self.page.on("request",on_request)
        self.page.on("response",on_response)
        attempted = False
        try:
            self.stage = "提交前检查"
            button.scroll_into_view_if_needed(timeout=self.timeout(3000))
            button.click(trial=True,timeout=self.timeout(4000))
            self.gate()
            self.mark_sending(target)
            # 落盘后即算一次提交尝试；超时也不会再次点击发送。
            attempted = True
            self.count_attempt()
            self.stage = "等待评论结果"
            try:
                self.gate()
                self.m.behavior.click(self.page,button,timeout=self.timeout(6000))
            except (StopRequested,DurationReached,SceneBudgetExceeded,CdpStateError,AccountStateError):
                raise
            except Exception:
                logger.warning("评论发送点击异常，继续检查已发出的响应，不重复点击",exc_info=True)
            end = m.clock.elapsed() + 15
            while m.clock.elapsed() < end:
                self.gate()
                while responses:
                    response = responses.pop(0)
                    try:
                        payload = response.json()
                    except Exception:
                        if response.status >= 400:
                            raise CommentRejected(response.status,"接口拒绝请求，响应不是JSON")
                        continue
                    errors = payload.get("errors") if isinstance(payload,dict) else None
                    if response.status >= 400 or errors:
                        raise CommentRejected(response.status,errors or "接口拒绝请求")
                    tid = created_reply_id(payload,target)
                    if tid:
                        return tid
                self.pump()
            self.state("结果待核对", "已捕获回复请求但未收到成功确认" if requests else "点击后未捕获匹配回复请求")
            return None
        except BaseException:
            if attempted:
                # 由调用层读取此状态，不能把已尝试提交归为可重试的准备失败。
                m.stats["comment_last_armed"] = True
            raise
        finally:
            m.stats["comment_last_armed"] = attempted
            for event,callback in (("request",on_request),("response",on_response)):
                try:
                    self.page.remove_listener(event,callback)
                except Exception:
                    logger.debug("清理评论监听未完成",exc_info=True)

    def diagnostic(self, target_url, exc):
        path = DATA_DIR / "comment_diagnostics" / f"{hashlib.sha256(self.m.browser_id.encode()).hexdigest()[:12]}_{time.time_ns()}.json"
        data = {"version":APP_VERSION,"stage":self.stage,"surface":self.surface,"target":target_url,"error":str(exc),"account":self.m.browser_id}
        try:
            if self.page is not None and not self.page.is_closed():
                data.update({"url":self.page.url,"visible_editors":self.page.locator(self.EDITOR).count(),"visible_send_buttons":self.page.locator(self.SEND).count()})
            atomic_json(path,data)
            self.m.log(f"评论诊断已保存：{path}")
        except Exception:
            logger.warning("保存评论诊断失败",exc_info=True)

    def maybe_comment(self):
        m = self.m
        if not m.cfg.comment_enabled or m.cfg.draft_enabled:
            return
        if m.comment_halted:
            return
        if m.comment_attempts >= m.cfg.comment_count:
            self.state("本轮次数已完成",f"已确认{m.stats.get('comments_sent',0)}，待核对{m.stats.get('comments_unknown',0)}")
            return
        if m.clock.elapsed() < m.comment_retry_at:
            return
        delay = self.store.cooldown(m.browser_id,m.cfg.comment_interval)
        if delay > 0:
            self.state("等待间隔",f"成功或提交后间隔 {m.cfg.comment_interval:g} 秒")
            return
        if m.remaining() < 15:
            self.state("时长不足","剩余时间不足15秒，继续当前阅读")
            return
        if not m.comment_candidates:
            self.state("等待已读推文")
            return
        self.e.gate()
        item, target_url = None, None
        while m.comment_candidates:
            target,url = m.comment_candidates.popitem(last=False)
            if target in m.comment_skipped_targets:
                continue
            item, reason = self.store.reserve_comment(m.ctl.comment_rows,m.browser_id,target,m.cfg.comment_order)
            if item is not None:
                target_url = url
                break
            self.state(reason)
            if reason == "评论文本已全局用完":
                return
        if item is None:
            return
        target,text = item
        original_deadline = m.scene_deadline
        started = m.clock.elapsed()
        m.scene_deadline = None
        self.deadline = min(started+70,started+m.remaining(),original_deadline if original_deadline is not None else math.inf)
        m.stats["comment_last_armed"] = False
        self.stage,self.surface = "准备当前页面评论",""
        snapshot=None
        original_dialogs=0
        self.state("正在评论",target_url)
        try:
            self.gate()
            self.page = self.source
            same_target=canonical_status_url(self.page.url or '')==canonical_status_url(target_url)
            if not same_target:
                # 不导航离开用户已有的未提交输入。
                draft=self.page.locator('[contenteditable="true"]:visible').evaluate_all("els=>els.some(e=>(e.innerText||'').trim())")
                if draft:raise ContentUnavailable("当前页有未提交内容，保留原页并跳过此次评论")
            else:
                texts=self.page.locator(self.EDITOR).evaluate_all("els=>els.map(e=>(e.innerText||'').trim()).filter(Boolean)")
                if any(normalize_comment_text(value)!=normalize_comment_text(text) for value in texts):
                    raise ContentUnavailable("目标页已有其他评论草稿，保留原内容")
            original_dialogs=self.page.locator('[role="dialog"]:visible').count()
            snapshot=self.e.navigator.capture()
            self.stage = "在当前页加载目标推文"
            if not same_target:
                self.page.goto(target_url,wait_until="domcontentloaded",timeout=self.timeout(15000))
            self.gate()
            editor,self.surface = self.open_composer(target)
            button = self.fill_composer(editor,text)
            tid = self.submit_once(button,text,target)
            if tid:
                reply_url = f"https://x.com/i/status/{tid}"
                self.store.update(m.browser_id,target,m.browser_id,"sent",url=reply_url)
                m.stats["comments_sent"] = m.stats.get("comments_sent",0)+1
                m.comment_prepare_failures = 0
                self.state("评论成功",f"{target_url} → {reply_url}")
            else:
                self.store.update(m.browser_id,target,m.browser_id,"unknown",error="提交后没有获得成功确认；不重复评论本目标")
                m.stats["comments_unknown"] = m.stats.get("comments_unknown",0)+1
                self.diagnostic(target_url,RuntimeError("等待回复响应超时"))
        except BaseException as exc:
            armed = m.stats.get("comment_last_armed",False)
            logger.warning("评论失败 stage=%s target=%s armed=%s",self.stage,target_url,armed,exc_info=True)
            if isinstance(exc,CommentRejected):
                self.store.update(m.browser_id,target,m.browser_id,"rejected",error=str(exc))
                self.state("服务端拒绝",str(exc))
                # 账号/频率/文本问题不盲目重试，阅读仍继续。
                m.comment_halted = True
            elif armed:
                self.store.update(m.browser_id,target,m.browser_id,"unknown",error=f"{self.stage}：{short_error(exc)}")
                m.stats["comments_unknown"] = m.stats.get("comments_unknown",0)+1
                self.state("结果待核对", "保留本目标和文本，后续其他目标仍按间隔执行")
            else:
                self.store.release_before_submit(m.browser_id,target)
                m.comment_prepare_failures += 1
                m.comment_retry_at = m.clock.elapsed() + min(60,5*m.comment_prepare_failures)
                m.comment_skipped_targets.add(target)
                self.state("准备失败，继续养号",f"{self.stage}：{short_error(exc)}；评论文本未消耗")
                if isinstance(exc,ValueError):
                    m.comment_halted = True
            if not isinstance(exc,(StopRequested,DurationReached,KeyboardInterrupt,SystemExit)):
                self.diagnostic(target_url,exc)
            if isinstance(exc,(StopRequested,DurationReached,CdpStateError,AccountStateError,KeyboardInterrupt,SystemExit)):
                raise
        finally:
            active_error=sys.exc_info()[1]
            restore_error=None
            self.deadline = None
            try:
                if snapshot is not None and not isinstance(active_error,(StopRequested,DurationReached,CdpStateError,AccountStateError,KeyboardInterrupt,SystemExit)) and m.remaining()>1:
                    m.scene_deadline=m.clock.elapsed()+min(15,m.remaining())
                    try:
                        self.stage="返回评论前的来源页面"
                        if self.source.locator('[role="dialog"]:visible').count()>original_dialogs:
                            self.source.keyboard.press('Escape')
                            if self.source.locator('[role="dialog"]:visible').count()>original_dialogs:
                                self.e.navigator.goto(snapshot.url)
                        self.e.navigator.restore(snapshot)
                    except (StopRequested,DurationReached,CdpStateError,AccountStateError):
                        raise
                    except Exception as exc:
                        restore_error=exc
                        m.log("评论结果已记录，来源页恢复未完成；交由阅读流程恢复页面。")
            finally:
                self.page=None  # 主标签属于浏览会话，评论器绝不关闭它。
                # 评论与返回用时不占阅读场景预算，总时长正常累计。
                m.scene_deadline=original_deadline+(m.clock.elapsed()-started) if original_deadline is not None else None
            if restore_error is not None and active_error is None:
                raise PageNotReady("评论结束后来源页未恢复："+short_error(restore_error)) from restore_error


class ScoredAccountCollector:
    """只读采集：红点徽标、粉丝、近期帖子的获赞/评论、评论与提及、私信列表。
    不点赞、不关注、不发送；不打开私信会话，所以不会把私信标成已读。
    注意：X 打开“通知”页后红点会清零（本程序先读红点再进通知页）。"""

    BADGE_JS = ("els=>els.flatMap(e=>[e.getAttribute('aria-label')||'',"
                "...[...e.querySelectorAll('[aria-label]')].map(x=>x.getAttribute('aria-label')||'')])")
    COUNTS_JS = ("els=>els.filter(e=>e.getClientRects().length>0)"
                 ".map(e=>[e.getAttribute('href')||'',(e.innerText||'').trim()])")
    PROFILE_JS = r'''(handle) => {
        const want = ('/' + handle + '/status/').toLowerCase();
        const seen = new Set(), out = [];
        for (const art of document.querySelectorAll('article[data-testid="tweet"]')) {
            if (!art.getClientRects().length) continue;
            let id = null;
            for (const a of art.querySelectorAll('a[href*="/status/"]')) {
                const href = a.getAttribute('href') || '';
                if (!a.querySelector('time') || !href.toLowerCase().startsWith(want)) continue;
                const m = href.match(/\/status\/(\d+)/);
                if (m) { id = m[1]; break; }
            }
            if (!id || seen.has(id)) continue;
            seen.add(id);
            const label = sel => { const e = art.querySelector(sel); return e ? (e.getAttribute('aria-label') || '') : null; };
            const pick = (a, b) => { const x = label(a); return x !== null ? x : label(b); };
            const analytics = art.querySelector('a[href$="/analytics"]');
            const txt = art.querySelector('[data-testid="tweetText"]');
            out.push({
                id: id, text: txt ? txt.innerText : '',
                reply: label('[data-testid="reply"]'),
                like: pick('[data-testid="like"]', '[data-testid="unlike"]'),
                retweet: pick('[data-testid="retweet"]', '[data-testid="unretweet"]'),
                views_label: analytics ? (analytics.getAttribute('aria-label') || '') : '',
                views_text: analytics ? (analytics.innerText || '') : ''
            });
        }
        return out;
    }'''
    MENTIONS_JS = r'''(handle) => {
        const me = (handle || '').toLowerCase(), seen = new Set(), out = [];
        for (const art of document.querySelectorAll('article[data-testid="tweet"]')) {
            if (!art.getClientRects().length) continue;
            let id = null, author = '';
            for (const a of art.querySelectorAll('a[href*="/status/"]')) {
                if (!a.querySelector('time')) continue;
                const m = (a.getAttribute('href') || '').match(/^\/([A-Za-z0-9_]{1,15})\/status\/(\d+)/);
                if (m) { author = m[1]; id = m[2]; break; }
            }
            if (!id || seen.has(id) || author.toLowerCase() === me) continue;
            seen.add(id);
            const txt = art.querySelector('[data-testid="tweetText"]');
            out.push({id: id, author: author, text: txt ? txt.innerText : ''});
        }
        return out;
    }'''
    DM_JS = r'''() => {
        const unreadRe = /unread|未读|未讀|não lid|sin leer|non lu|ungelesen|непрочит|未読|읽지/i;
        const rows = [...document.querySelectorAll('[data-testid="conversation"], [data-testid="conversationEntry"]')]
            .filter(e => e.getClientRects().length > 0);
        return rows.slice(0, 30).map(r => {
            const labels = [r.getAttribute('aria-label') || '', ...[...r.querySelectorAll('[aria-label]')].map(x => x.getAttribute('aria-label') || '')];
            const a = r.closest('a') || r.querySelector('a[href^="/messages/"]');
            return {
                lines: (r.innerText || '').split('\n').map(s => s.trim()).filter(Boolean).slice(0, 6),
                unread: labels.some(l => unreadRe.test(l)) || !!r.querySelector('[data-testid*="nread"]'),
                href: a ? (a.getAttribute('href') || '') : ''
            };
        });
    }'''

    def __init__(self, executor):
        self.e, self.m = executor, executor.m
        self.store = get_store()
        self.posts: List[Dict[str, Any]] = []

    # ---- 总入口 ----
    def run(self, stage: str = "start") -> None:
        e, m, cfg = self.e, self.m, self.m.cfg
        original = m.scene_deadline
        m.scene_deadline = m.clock.elapsed() + 110
        m.workflow_name = "数据采集"
        e.current_key = None
        info: Dict[str, Any] = {k: None for k in ("followers", "following", "dm_unread", "dm_convs", "notif_unread")}
        inbox: List[Dict[str, Any]] = []
        errors: List[str] = []
        try:
            e.phase("采集：检查首页")
            e.ensure_home()
            e.primary()
            self.step(errors, "红点", lambda: self.read_badges(info))
            self.step(errors, "主页数据", lambda: self.read_profile(info))
            if cfg.stats_mentions:
                self.step(errors, "评论与提及", lambda: inbox.extend(self.read_mentions()))
            if cfg.stats_dm:
                self.step(errors, "私信列表", lambda: self.read_dm_list(info, inbox))
        finally:
            m.scene_deadline = original
            self.save(info, inbox, errors, stage)

    def step(self, errors: List[str], label: str, fn: Callable[[], Any]) -> None:
        try:
            fn()
        except FATAL_ERRORS:
            raise
        except SceneBudgetExceeded:
            errors.append(f"{label}：时间用尽")
        except ContentUnavailable as exc:
            errors.append(f"{label}：{exc}")
        except PlaywrightTimeoutError as exc:
            errors.append(f"{label}：超时 {short_error(exc)}")
        except Exception as exc:
            logger.warning("采集步骤失败：%s", label, exc_info=True)
            errors.append(f"{label}：{short_error(exc)}")

    def save(self, info, inbox, errors, stage) -> None:
        m = self.m
        try:
            got = any(v is not None for v in info.values()) or bool(self.posts)
            if got:
                self.store.record_collection(m.browser_id, m.browser_name, m.handle, self.posts, info, source=stage+('/partial' if errors else ''))
                m.stats['collections_partial' if errors else 'collections_successful']=m.stats.get('collections_partial' if errors else 'collections_successful',0)+1
                if not errors:m.stats['last_successful_collection']=time.time()
            new = self.store.upsert_inbox(m.browser_id, inbox) if inbox else 0
            m.stats["collections"] = m.stats.get("collections", 0) + 1
            parts = []
            if info["followers"] is not None:
                parts.append(f"粉丝 {info['followers']}")
            if self.posts:
                parts.append(f"读取 {len(self.posts)} 帖 获赞 {sum(p['likes'] for p in self.posts)} 评论 {sum(p['replies'] for p in self.posts)}")
            if info["dm_unread"] is not None:
                parts.append(f"私信未读 {info['dm_unread']}")
            if info["notif_unread"] is not None:
                parts.append(f"通知未读 {info['notif_unread']}")
            if inbox:
                parts.append(f"收件箱 {len(inbox)} 条（新增 {new}）")
            summary = " · ".join(parts) or "没有读到有效数据"
            if errors:
                summary += "｜未完成：" + "；".join(errors)
            m.log("数据采集完成：" + summary)
            self.store.log_event(m.browser_id, m.browser_name, "collect", summary)
        except Exception:
            logger.warning("保存采集结果失败", exc_info=True)

    # ---- 具体读取 ----
    def read_badges(self, info: Dict[str, Any]) -> None:
        page = self.e.page
        for key, selector in (("dm_unread", '[data-testid="AppTabBar_DirectMessage_Link"]'),
                              ("notif_unread", '[data-testid="AppTabBar_Notifications_Link"]')):
            link = page.locator(selector)
            if link.count():
                info[key] = unread_total(link.evaluate_all(self.BADGE_JS))

    def own_handle(self) -> str:
        e = self.e
        link = e.page.locator('[data-testid="AppTabBar_Profile_Link"]').first
        href = e.poll(lambda: link.get_attribute("href", timeout=e.timeout(1500)) if link.count() else None, 6000)
        found = re.fullmatch(r"/([A-Za-z0-9_]{1,15})/?", href or "")
        if not found:
            raise ContentUnavailable("无法确认当前账号用户名（侧栏的个人主页入口没有出现）")
        self.m.handle = found.group(1)
        return self.m.handle

    def profile_counts(self) -> Optional[Dict[str, int]]:
        rows = self.e.page.locator(
            'a[href$="/followers"], a[href$="/verified_followers"], a[href$="/following"]'
        ).evaluate_all(self.COUNTS_JS)
        found: Dict[str, int] = {}
        for href, text in rows:
            number = parse_count(text)
            if number is None:
                continue
            found.setdefault("following" if href.endswith("/following") else "followers", number)
        return found or None

    def read_profile(self, info: Dict[str, Any]) -> None:
        e, m, page = self.e, self.m, self.e.page
        handle = m.handle or self.own_handle()
        e.phase("采集：打开自己的主页")
        e.navigator.goto("https://x.com/" + handle)
        if not e.poll(lambda: page.locator('[data-testid="primaryColumn"]').count(), 8000):
            raise PageNotReady("自己的主页尚未加载")
        counts = e.poll(self.profile_counts, 5000)
        if counts:
            info["followers"] = counts.get("followers", info.get("followers"))
            info["following"] = counts.get("following", info.get("following"))
        e.phase("采集：读取近期帖子的获赞与评论")
        self.posts = self.collect_posts(handle, m.cfg.stats_posts)
        if m.cfg.stats_recent_enabled:collect_recent_activity(self,handle)

    def collect_posts(self, handle: str, limit: int) -> List[Dict[str, Any]]:
        e, page = self.e, self.e.page
        e.poll(lambda: page.locator(SELECTORS["tweet"]).count() or page.locator('[data-testid="emptyState"]').count(), 8000)
        posts: Dict[str, Dict[str, Any]] = {}
        stale = 0
        for _ in range(8):
            e.gate()
            fresh = 0
            for row in build_post_metrics(page.evaluate(self.PROFILE_JS, handle)):
                fresh += 0 if row["id"] in posts else 1
                posts[row["id"]] = row
            if len(posts) >= limit:
                break
            stale = 0 if fresh else stale + 1
            if stale >= 2:
                break
            e.scroll(e.plan.rng.randint(520, 900))
        return list(posts.values())[:limit]

    def read_mentions(self) -> List[Dict[str, Any]]:
        e, page = self.e, self.e.page
        handle = self.m.handle or self.own_handle()
        e.phase("采集：评论与提及")
        e.navigator.goto("https://x.com/notifications/mentions")
        if not e.poll(lambda: page.locator(SELECTORS["tweet"] + ":visible").count(), 7000):
            return []  # 没有提及也是合法结果
        found: Dict[str, Dict[str, Any]] = {}
        for _ in range(3):
            for row in page.evaluate(self.MENTIONS_JS, handle) or []:
                pid, author = str(row.get("id") or ""), str(row.get("author") or "")
                if pid.isdigit() and author and pid not in found:
                    found[pid] = {"kind": "mention", "ext_id": pid, "author": "@" + author,
                                  "text": re.sub(r"\s+", " ", str(row.get("text") or "")).strip()[:500],
                                  "url": f"https://x.com/{author}/status/{pid}"}
            if len(found) >= 30:
                break
            e.scroll(e.plan.rng.randint(450, 800))
        return list(found.values())

    def read_dm_list(self, info: Dict[str, Any], inbox: List[Dict[str, Any]]) -> None:
        e, page = self.e, self.e.page
        e.phase("采集：私信列表（只读，不打开会话）")
        e.navigator.goto("https://x.com/messages")
        e.primary()
        if page.locator('input[type="password"]:visible').count():
            raise ContentUnavailable("私信要求输入 PIN / 验证，已跳过（请手动处理）")
        rows = e.poll(lambda: page.evaluate(self.DM_JS) or None, 7000)
        if not rows:
            raise ContentUnavailable("没有识别到私信会话列表（可能没有会话，或页面结构有变化）")
        flagged = 0
        for row in rows:
            lines = [str(x) for x in row.get("lines") or []]
            if not lines:
                continue
            unread = bool(row.get("unread"))
            flagged += 1 if unread else 0
            href = row.get("href") or ""
            inbox.append({
                "kind": "dm", "ext_id": "conv:" + hashlib.sha1(lines[0].casefold().encode("utf-8")).hexdigest()[:14],
                "author": lines[0][:60], "text": (lines[-1] if len(lines) > 1 else "")[:200],
                "url": ("https://x.com" + href) if re.fullmatch(r"/messages/[\w-]+", href) else "",
                "state": "new" if unread else "handled",
            })
        info["dm_convs"] = len(rows)
        info["dm_unread"] = max(info.get("dm_unread") or 0, flagged)


class ScoredTwitterWarmupMachine:
    def __init__(
        self, browser_id: str, browser_name: str, cfg: WarmupConfig, ctl: RunControl
    ):
        self.browser_id = browser_id
        self.browser_name = browser_name
        self.cfg = cfg
        self.ctl = ctl
        self.workflow_plan = ScoredWorkflowPlanner(cfg)
        self.reading_cadence = ReadingCadence()
        self.post_book=PostReadingBook(reading_policy(cfg))
        self.current_post=None
        self.last_explore_at=0.0
        self.last_collection_attempt_at=0.0
        self.journal = ScoredReadingJournal(browser_id)
        self.scene_deadline: Optional[float] = None
        self.workflow_name = "等待工作流"
        self.workflow_phase = "准备"
        self.like_attempts = 0
        self.draft_sent = 0
        self.comment_candidates = OrderedDict()
        self.comment_attempts = 0
        self.comment_eligible_since=None
        self.comment_halted = False
        self.comment_prepare_failures = 0
        self.comment_retry_at = 0.0
        self.comment_skipped_targets = set()
        self.report_path = (
            DATA_DIR
            / "workflow_reports"
            / f"{hashlib.sha256(browser_id.encode()).hexdigest()[:16]}_{self.workflow_plan.session_id}.json"
        )
        self.slot: Optional[int] = None
        self.run_started = 0.0
        self.clock = ActiveClock(ctl)
        self.behavior = HumanBehaviorEngine(self.checkpoint)
        self.stats: Dict[str, Any] = {
            "reads": 0,
            "likes": 0,
            "reconnects": 0,
            "like_attempts": 0,
            "like_unconfirmed": 0,
            "notifications_read": 0,
        }
        self.last_progress = 0.0
        self.last_like_at: Optional[float] = None
        self.seen: "OrderedDict[str, None]" = OrderedDict()
        self.selector_miss: Dict[str, int] = {}
        self._browser: Any = None
        self._layout_cdp = None
        self._layout_seen = -1
        self.conn_state = ConnState.CONNECTED
        # V9
        self.handle = ""
        self.grace_sec = 0.0
        self.stage = ""
        self.stage_log: List[Dict[str, Any]] = []
        self._persist_at = 0.0
        self.last_service_at = 0.0
        self.last_collection_at = 0.0
        self.last_service_check = -999.0
        if cfg.service_mode:
            self.stats["mode"] = "service"

    def set_stage(self, name: str) -> None:
        """记录当前处在哪个流程阶段（界面“执行流程”页读取）。"""
        if self.stage == name:
            return
        self.stage = name
        self.stage_log.append({"stage": name, "at": round(self.clock.elapsed(), 1), "ts": time.time()})
        del self.stage_log[:-60]
        self.persist_workflow_plan(force=True)

    def log(self, text: str) -> None:
        slot = f"|S{self.slot + 1}" if self.slot is not None else ""
        self.ctl.log(f"[{self.browser_name}|{self.browser_id[:6]}{slot}] {text}")

    def status(self, text: str, tone: str = "info") -> None:
        self.ctl.set_status(self.browser_id, text, tone)

    def cdp_alive(self) -> bool:
        b = self._browser
        if b is None:
            return True
        try:
            return bool(b.is_connected())
        except (StopRequested, DurationReached, SceneBudgetExceeded):
            raise
        except Exception:
            return False

    def observe_navigation(self, frame):
        if frame==getattr(self,'_tracked_main_frame',None):
            self.stats['page_navigations']=self.stats.get('page_navigations',0)+1
            self.stats['navigation_tail']=(self.stats.get('navigation_tail',[])+[{'url':frame.url,'at':round(self.clock.elapsed(),2)}])[-30:]

    def sync_window_layout(self, force=False):
        if self._layout_cdp is None or self.slot is None:
            return
        version,mode,bounds=self.ctl.window_order.snapshot(self.slot)
        if not force and version==self._layout_seen:
            return
        self._layout_seen=version
        try:
            BitBrowserController.apply_window_bounds(self._layout_cdp,bounds)
            self.ctl.window_order.relayout_native()
        except Exception:
            logger.warning("窗口重排未完成，保留当前任务",exc_info=True)

    def checkpoint(self) -> None:
        self._pause_gate()
        self.sync_window_layout()
        if self.clock.started is not None and self.remaining() <= 0:
            raise DurationReached()
        self.check_scene_budget()

    def check_scene_budget(self) -> None:
        if (
            self.scene_deadline is not None
            and self.clock.elapsed() >= self.scene_deadline
        ):
            raise SceneBudgetExceeded()

    def persist_workflow_plan(self, force: bool = False) -> None:
        # 每个阶段都会调用；平时最多 1.5 秒写一次，避免 fsync 拖慢浏览器线程
        now = time.monotonic()
        if not force and now - self._persist_at < 1.5:
            return
        self._persist_at = now
        try:
            snapshot = self.workflow_plan.snapshot()
            self.stats["workflow_plan"] = snapshot
            atomic_json(
                self.report_path,
                {
                    "version": APP_VERSION,
                    "reading_model": self.cfg.reading_model,
                    "browser_id": self.browser_id,
                    "name": self.browser_name,
                    "handle": self.handle,
                    "mode": "service" if self.cfg.service_mode else ("post" if self.cfg.draft_enabled else "read"),
                    "stage": self.stage,
                    "stage_log": self.stage_log,
                    "updated_at": time.time(),
                    "active_sec": round(self.clock.elapsed(), 2),
                    "plan": snapshot,
                    "reading": {'current':self.post_book.entries.get(self.current_post),
                                'recent':list(self.post_book.entries.values())[-20:],
                                'cadence':dataclasses.asdict(self.reading_cadence),
                                'statistics':{k:v for k,v in self.stats.items() if k not in ('workflow_plan','last_decision')},
                                'policy':dict(self.cfg.reading_policy),'budget_sec':self.cfg.duration_budget_sec if math.isfinite(self.cfg.duration_budget_sec) else None,
                                'effective_sec':max(0,self.clock.elapsed()-self.grace_sec)},
                },
            )
        except OSError:
            logger.warning("写入工作流报告失败", exc_info=True)

    def _pause_gate(self) -> Tuple[bool, float]:
        was_paused = not self.ctl.pause_event.is_set()
        if was_paused:
            self.status("已暂停", "warn")
        before = self.ctl.paused_seconds()
        while not self.ctl.pause_event.wait(SLEEP_SLICE):
            if self.ctl.is_stopped():
                raise StopRequested()
        if self.ctl.is_stopped():
            raise StopRequested()
        if was_paused and self.clock.started is not None:
            self.last_progress = 0
            self.progress()
        return True, max(0.0, self.ctl.paused_seconds() - before)

    def wait_if_paused(self) -> bool:
        return self._pause_gate()[0]

    def remaining(self) -> float:
        # grace_sec：采集/回复用掉的时间不占单号阅读时长
        return max(0.0, self.cfg.duration_budget_sec + self.grace_sec - self.clock.elapsed())

    def sleep(self, seconds: float) -> bool:
        # 即使旧动作忘记检查返回值，停止仍能通过异常逐层退出。
        end = time.monotonic() + max(0.0, seconds)
        while True:
            _, paused = self._pause_gate()
            self.sync_window_layout()
            end += paused
            if self.clock.started is not None and self.remaining() <= 0:
                raise DurationReached()
            self.check_scene_budget()
            if self.clock.started is not None:
                self.progress()
            remain = end - time.monotonic()
            if remain <= 0:
                return True
            if self.ctl.stop_event.wait(min(SLEEP_SLICE, remain)):
                raise StopRequested()

    def progress(self) -> None:
        now = time.monotonic()
        if now - self.last_progress >= 1:
            self.last_progress = now
            self.status(
                (f"TXT 发推 {self.draft_sent}/{self.cfg.draft_count}·{self.workflow_phase}" if self.cfg.draft_enabled else f"{self.workflow_name}·{self.workflow_phase}")
                + (" | 不限时" if self.cfg.duration_min == 0 else f" | 剩余 {self.remaining() / 60:.1f}分"),
                "run",
            )

    def miss(self, key: str) -> int:
        self.selector_miss[key] = self.selector_miss.get(key, 0) + 1
        return self.selector_miss[key]

    def tweet_key(self, art) -> Optional[str]:
        try:
            return art.locator(SELECTORS["status_link"]).first.get_attribute(
                "href", timeout=800
            )
        except (StopRequested, DurationReached, SceneBudgetExceeded):
            raise
        except Exception:
            return None

    def mark_seen(self, key: str) -> bool:
        if key in self.seen:
            return True
        self.seen[key] = None
        if len(self.seen) > SEEN_LIMIT:
            for _ in range(SEEN_LIMIT // 2):
                self.seen.popitem(last=False)
        return False

    def can_like(self) -> bool:
        return (
            self.cfg.enable_like
            and max(self.like_attempts, self.stats["likes"]) < self.cfg.max_likes
            and (
                self.last_like_at is None
                or time.monotonic() - self.last_like_at >= self.cfg.min_like_interval
            )
        )

    def warmup_loop(self, page: Page) -> Result:
        if self.cfg.service_mode:
            return ScoredWorkflowExecutor(self, page).run_service()
        if self.cfg.draft_enabled:
            return DraftPublisher(self, page).run()
        result = ScoredWorkflowExecutor(self, page).run()
        if (self.comment_halted or self.stats.get("comments_unknown",0)) and result in SUCCESS_RESULTS:
            return Result.PARTIAL
        return result

    def attach_and_run(self, endpoint: str, bounds: Dict[str, int]) -> Result:
        sess = PlaywrightSession()
        try:
            sess.start()
            try:
                browser, _ctx, page, _cdp = BitBrowserController.connect_and_arrange(
                    sess, endpoint, bounds, False, self.ctl.stop_event
                )
            except StopRequested:
                return Result.STOPPED
            except DurationReached:
                raise
            except Exception as e:
                if self.ctl.is_stopped():
                    return Result.STOPPED
                self.log(f"CDP 连接失败: {e}")
                return Result.CDP_LOST

            self._tracked_main_frame=page.main_frame
            page.on('framenavigated',self.observe_navigation)
            self._browser = browser
            self._layout_cdp = sess.cdp
            self._layout_seen = -1
            pid=None
            if sys.platform=="win32":
                try:pid=self.ctl.bit.browser_pid(self.browser_id)
                except Exception:logger.debug("查询窗口PID失败",exc_info=True)
            self.ctl.window_order.register(self.browser_id,self.slot,pid)
            self.sync_window_layout(force=True)
            if sess.layout_applied:
                self.log("窗口布局指令已应用，CDP 控制链路就绪。")
                actual = sess.actual_bounds
                if actual and any(
                    abs(actual.get(key, value) - value) > 4
                    for key, value in bounds.items()
                ):
                    self.log(
                        f"实际窗口范围 {actual} 与目标 {bounds} 有差异，请检查桌面缩放或窗口限制。"
                    )
            else:
                self.log("CDP 已连接，但窗口布局未确认，请查看日志中的布局错误。")

            self.status("加载首页", "run")

            if (
                not is_x_url(page.url or "")
                or urlparse(page.url).path.rstrip("/") != "/home"
            ):
                try:
                    page.goto(TWITTER_HOME_URL, wait_until="commit", timeout=T(35000))
                except (StopRequested, DurationReached, SceneBudgetExceeded):
                    raise
                except Exception:
                    logger.debug("回到首页超时，继续后续流程", exc_info=True)
            if not self.run_started:
                self.run_started = time.monotonic()
            self.clock.resume()
            if not self.cfg.draft_enabled and not self.cfg.service_mode and self.stats.get("plan_logged") is not True:
                self.stats["plan_logged"] = True
                enabled=sum(1 for item in self.workflow_plan.items.values() if item['target']>0)
                self.log(f'阅读模型：逐帖七维评分；启用{enabled}项候选工作流，配额仅作上限，完整明细见报告。')
            self.status("运行中", "run")
            if not self.sleep(random.uniform(2.0, 3.5)):
                return Result.STOPPED

            result = self.warmup_loop(page)
            if result in SUCCESS_RESULTS:
                self.log(
                    f"会话结束：{RESULT_LABEL[result]}，有效执行 {self.clock.elapsed() / 60:.1f} 分钟。"
                )
            return result
        except DurationReached:
            if self.cfg.draft_enabled and self.draft_sent < self.cfg.draft_count:
                self.log("达到单号总时长，发推数量未完成；下批继续未发送条目。")
                return Result.PARTIAL
            return Result.OK
        except StopRequested:
            return Result.STOPPED
        finally:
            self.clock.suspend()
            try:
                if 'page' in locals():page.remove_listener('framenavigated',self.observe_navigation)
            except Exception:logger.debug('移除导航统计监听失败',exc_info=True)
            self._layout_cdp = None
            self._browser = None
            sess.close()

    def session(
        self, endpoint: str, bounds: Dict[str, int], rec: LaunchRecord
    ) -> Result:
        reconnects = 0
        while True:
            if self.run_started and self.remaining() <= 0:
                return Result.OK
            attached_at = time.monotonic()
            result = self.attach_and_run(endpoint, bounds)
            if result != Result.CDP_LOST:
                return result
            if self.ctl.is_stopped():
                return Result.STOPPED
            if time.monotonic() - attached_at > RECONNECT_RESET_SEC:
                reconnects = 0

            self.stats["reconnects"] += 1
            endpoint = None
            while endpoint is None:
                reconnects += 1
                if reconnects > MAX_RECONNECTS:
                    self.log(f"CDP 连续 {MAX_RECONNECTS} 次重连失败, 终止该账号。")
                    return Result.CDP_LOST
                wait = min(30, 5 * reconnects)
                self.status(f"重连中({reconnects}/{MAX_RECONNECTS})", "warn")
                self.log(
                    f"CDP 断连, {wait}s 后第 {reconnects}/{MAX_RECONNECTS} 次重连..."
                )
                if not self.sleep(wait):
                    return Result.STOPPED
                try:
                    endpoint = self.ctl.bit.ensure_browser_running(
                        self.browser_id, bounds, self.ctl, rec, self.log
                    )
                except StopRequested:
                    return Result.STOPPED
                except DurationReached:
                    raise
                except Exception as e:
                    self.log(f"重连获取端口失败: {e}")
                    endpoint = None

    def run(self) -> Tuple[Result, float]:
        self.status("排队中", "info")
        slot = self.ctl.slots.acquire(lambda: self.ctl.should_abort_queue(self.browser_id)) if self.ctl.wait_launch_turn(self.browser_id) else None
        if slot is None:
            self.ctl.take_pending(self.browser_id)
            result = Result.STOPPED if self.ctl.is_stopped() else Result.CANCELLED
            self.status(RESULT_LABEL[result], RESULT_TONE[result])
            return result, 0.0
        result, rec, require_close = Result.ERROR, None, False
        self.slot = slot
        try:
            while not self.ctl.claim_pending(self.browser_id):
                if not self.ctl.wait_queue_ready(self.browser_id):
                    result = Result.STOPPED if self.ctl.is_stopped() else Result.CANCELLED
                    return result, 0.0
            self.set_stage("launch")
            rec = self.ctl.begin_launch(self.browser_id)
            BatchStore.update(self.browser_id, "RUNNING")
            self.log(f"获得槽位 [{slot + 1}/{self.ctl.layout_count}: {ScreenLayoutManager.position_name(slot, self.ctl.layout_count,self.ctl.window_order.mode)}]")
            self.status("启动中", "info")
            _, _, bounds = self.ctl.window_order.snapshot(slot)
            self.log(f"窗口位置 ({bounds['left']},{bounds['top']})，尺寸 {bounds['width']}×{bounds['height']}")
            try:
                endpoint = self.ctl.bit.ensure_browser_running(self.browser_id, bounds, self.ctl, rec, self.log)
            except (StopRequested, DurationReached, SceneBudgetExceeded):
                raise
            except Exception as exc:
                self.log(f"浏览器启动失败: {exc}")
                result = Result.LAUNCH_FAILED
            else:
                self.ctl.finish_launch_turn(self.browser_id)
                result = self.session(endpoint, bounds, rec)
                if reading_start_failed(self.cfg,result,self.stats) and result in SUCCESS_RESULTS:
                    result=Result.NO_CONTENT
        except StopRequested:
            result = Result.STOPPED
        except DurationReached:
            result = Result.PARTIAL if self.cfg.draft_enabled and self.draft_sent < self.cfg.draft_count else Result.OK
            if reading_start_failed(self.cfg,result,self.stats):
                result=Result.NO_CONTENT
        except Exception as exc:
            result = Result.STOPPED if self.ctl.is_stopped() else Result.ERROR
            logger.exception("账号执行异常")
            try:
                self.log(f"账号执行异常: {exc}")
            except Exception:
                pass
        finally:
            # 资源释放不依赖日志、持久化、窗口管理器是否成功。
            try:
                if rec is not None:
                    early_failure=reading_start_failed(self.cfg,result,self.stats) and not self.ctl.is_stopped()
                    retain_window=(early_failure and not self.cfg.close_after and rec.launched_by_us
                                   and rec.state!=BrowserCloseState.CLOSED)
                    if early_failure:
                        self.stats['startup_failed']=True
                        self.stats['window_retained']=retain_window
                        window_note='按设置保留当前窗口' if retain_window else '按结束关窗设置清理当前窗口'
                        self.log(f'首次阅读未成功（{result.value}）；仅结束当前账号，{window_note}；其他账号继续排队，自动计划保持原设置。')
                    # 单账号读取故障不影响整批队列；仅关窗未确认等资源故障仍停止调度。
                    close_now=self.ctl.is_stopped() or self.cfg.close_after
                    require_close=close_now or retain_window
                    if close_now:
                        try:
                            closed = self.ctl.close_browser(self.browser_id, allow_reused=False, expected=rec)
                        except Exception:
                            closed = False
                            logger.exception("关窗操作异常")
                        with rec.cond:
                            unresolved = rec.launched_by_us and rec.state != BrowserCloseState.CLOSED
                        if unresolved:
                            require_close = True
                            if result in SUCCESS_RESULTS:
                                result = Result.ERROR
                            self.ctl.request_stop()
                            self.log("窗口关闭未确认，已保留记录并停止后续账号，后台将重试关窗。")
                        elif closed:
                            self.log("已自动关闭浏览器窗口。")
            finally:
                try:
                    try:
                        self.ctl.take_pending(self.browser_id)
                    finally:
                        if rec is not None:
                            self.ctl.end_launch(self.browser_id, expected=rec, require_close=require_close)
                finally:
                    self.ctl.slots.release(slot)
                    self.slot = None
            try:
                self.stats["workflow_plan"] = self.workflow_plan.snapshot()
                self.stats["end_result"] = result.value
                if self.cfg.comment_enabled and not self.cfg.draft_enabled:
                    self.log(f"评论汇总：尝试 {self.comment_attempts}，成功 {self.stats.get('comments_sent',0)}，待核对 {self.stats.get('comments_unknown',0)}")
                self.set_stage("close")
                self.persist_workflow_plan(force=True)
                self.log(f"释放槽位 [{slot + 1}/{self.ctl.layout_count}], 状态: {RESULT_LABEL[result]}")
                self.status(RESULT_LABEL[result], RESULT_TONE[result])
            except Exception:
                logger.exception("账号结束信息写入失败，槽位已释放")
        active = min(self.cfg.duration_budget_sec + self.grace_sec, self.clock.elapsed())
        try:
            get_store().log_event(self.browser_id, self.browser_name, "run",
                f"{RESULT_LABEL[result]} · 有效 {active / 60:.1f} 分钟" + (" · 数据同步" if self.cfg.service_mode else ""))
        except Exception:
            logger.debug("写入动态失败", exc_info=True)
        return result, active


def reading_machine_class(cfg):
    if cfg.reading_model == 'v11_1' and not cfg.draft_enabled and not cfg.service_mode:
        return ScoredTwitterWarmupMachine
    return TwitterWarmupMachine


class BatchRunner:
    """在后台线程中按并发上限执行一批账号。

    on_result(bid, result) 在工作线程里调用，界面需自行切回主线程；
    on_finished() 在批次（包括停止后的清理）完全结束后调用一次。
    """

    def __init__(
        self,
        ctl: RunControl,
        cfg: WarmupConfig,
        targets: List[Dict[str, Any]],
        log: Callable[[str], None],
        on_result: Callable[[str, Result], None],
        on_finished: Callable[[], None],
    ):
        self.ctl, self.cfg, self.targets = ctl, cfg, list(targets)
        self.log, self.on_result, self.on_finished = log, on_result, on_finished
        self.summary: Dict[str, int] = {}
        self._lock = threading.Lock()
        self.thread = threading.Thread(target=self._run, name="matrix", daemon=True)

    def start(self) -> threading.Thread:
        self.thread.start()
        return self.thread

    def _job(self, item: Dict[str, Any]) -> None:
        bid, name = browser_id(item), browser_name(item)
        started = time.time()
        machine = None
        try:
            machine = reading_machine_class(self.cfg)(bid, name, self.cfg, self.ctl)
            result, active = machine.run()
        except Exception as err:
            logger.exception("子任务执行异常")
            self.log(f"[{name}] 子任务执行异常: {err}")
            result, active = Result.ERROR, 0.0
            self.ctl.take_pending(bid)
            self.ctl.set_status(bid, RESULT_LABEL[result], RESULT_TONE[result])
        with self._lock:
            self.summary[result.value] = self.summary.get(result.value, 0) + 1
        BatchStore.update(bid, result.value)
        HistoryStore.append(bid, name, started, active, result, machine.stats if machine else {})
        self.on_result(bid, result)
        self.ctl.bit.close_thread_session()

    def _run(self) -> None:
        cfg = self.cfg
        desc = mode_description(cfg)
        try:
            total = len(self.targets)
            if cfg.service_mode:
                jitter = "不跑阅读工作流"
            elif cfg.draft_enabled:
                jitter = "发推模式不使用工作流偏移"
            else:
                jitter = "每工作流独立 ±10%～60%，会话内固定"
            order = "成功采集最旧优先" if cfg.reading_model=="v11_1" and not cfg.draft_enabled and not cfg.service_mode else "随机打乱" if cfg.random_order else "固定次序"
            self.log(
                f"=== {desc}任务启动: 共 {total} 个账号 | 并发上限 {cfg.concurrency}（本轮{self.ctl.layout_count}窗）"
                f" | 单号 {'按目标与数量结束' if cfg.recent_action_batch else cfg.duration_text} | 启动队列: {order} | 执行量偏移: {jitter} | 养号流程: {READING_MODEL_LABELS[cfg.reading_model]} ==="
            )
            workers = compute_worker_count(total, cfg.concurrency)
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=workers, thread_name_prefix="acct"
            ) as pool:
                futures = [pool.submit(self._job, item) for item in self.targets]
                for future in concurrent.futures.as_completed(futures):
                    try:
                        future.result()
                    except Exception as err:
                        self.log(f"子任务异常: {err}")
            self.ctl.wait_reaper()
            text = ", ".join(f"{RESULT_LABEL[Result(k)]} {v}" for k, v in self.summary.items())
            self.log(f"=== {desc}任务全部结束: {text or '无'} ===")
        except Exception as exc:
            logger.exception("批次调度异常")
            self.log(f"批次调度异常：{exc}")
            self.ctl.request_stop()
            self.ctl.wait_reaper()
        finally:
            self.on_finished()


# ======================================================================
# 模块：xmanager/settings.py
# ======================================================================
"""界面设置模型：读取 / 校验 / 保存 config.json，并生成每批的 WarmupConfig。

旧版本把同一套“合并默认值 → 校验 → 失败回退”的逻辑在界面里写了五遍，
这里统一成 `_load_section`，config.json 的字段名保持不变，旧配置可直接使用。
"""


import dataclasses
from typing import Any, Dict, List, Optional, Tuple


ADVANCED_KEYS = (
    "p_like",
    "p_deep",
    "p_photo",
    "p_video",
    "p_profile",
    "p_refresh_feed",
    "max_likes",
    "min_like_interval",
)
DRAFT_DEFAULTS: Dict[str, Any] = {
    "draft_enabled": False,
    "draft_file": "",
    "draft_order": "sequential",
    "draft_scope": "shared",
    "draft_count": 1,
    "draft_interval": 300.0,
    "draft_schedule_mode": "immediate",
    "draft_schedule_date": "",
    "draft_schedule_time": "09:00:00",
}
COMMENT_DEFAULTS: Dict[str, Any] = {
    "comment_enabled": False,
    "comment_file": "",
    "comment_order": "sequential",
    "comment_count": 1,
    "comment_interval": 300.0,
}
DASH_DEFAULTS: Dict[str, Any] = {
    "stats_enabled": True,
    "stats_recent_enabled": True,
    "stats_mentions": True,
    "stats_dm": True,
    "stats_posts": 20,
    "stats_interval_min": 0.0,
    "reply_min_interval": 45.0,
    "reply_daily_cap": 30,
}
# 主界面的运行参数（与旧版 config.json 键名一致）
RUN_DEFAULTS: Dict[str, Any] = {
    "reading_model": "v10",
    "duration": str(DEFAULT_DURATION_MIN),
    "concurrency": str(DEFAULT_CONCURRENCY),
    "like": True,
    "deep": True,
    "random_order": True,
    "jitter": True,
    "close_after": True,
    "skip_done": False,
    "lite": False,
    "window_layout": "cascade",
    "group": "全部",
    "page": "dash",
}
DEFAULT_QUICK_REPLIES = ["谢谢支持！", "感谢你的留言 🙏", "收到，稍后回复你～"]

RUN_MODES = ("read", "comment", "post")
MODE_LABEL = {"read": "阅读养号", "comment": "阅读 + 自动评论", "post": "TXT 自动发推"}
MODE_START = {"read": "▶ 开始养号", "comment": "▶ 开始阅读+评论", "post": "▶ 开始 TXT 发推"}
MODE_HINT = {
    "read": "下一批：阅读工作流",
    "comment": "下一批：阅读 + TXT 自动评论",
    "post": "下一批：独立 TXT 发推（不执行阅读和评论）",
}


def validate_partial(values: Dict[str, Any]) -> WarmupConfig:
    """用默认的必填项补齐后校验一个设置分区；无效时抛 ValueError / TypeError。"""
    return WarmupConfig(DEFAULT_DURATION_MIN, False, False, True, **values)


class AppSettings:
    def __init__(self, raw: Optional[Dict[str, Any]] = None):
        raw = raw if isinstance(raw, dict) else {}
        self.warnings: List[str] = []
        defaults = WarmupConfig(DEFAULT_DURATION_MIN, False, False, True)
        self.advanced = self._load_section(
            raw.get("advanced"), {key: getattr(defaults, key) for key in ADVANCED_KEYS}, "点赞 / 行为参数"
        )
        self.draft = self._load_section(raw.get("draft_settings"), DRAFT_DEFAULTS, "TXT 发推设置")
        self.comment = self._load_section(raw.get("comment_settings"), COMMENT_DEFAULTS, "自动评论设置")
        dash = raw.get("dashboard_settings")
        if isinstance(dash, dict):
            dash = {
                k: bool(v) if k in ("stats_enabled", "stats_recent_enabled", "stats_mentions", "stats_dm") else v
                for k, v in dash.items()
            }
        self.dash = self._load_section(dash, DASH_DEFAULTS, "数据采集设置")
        self.recent_actions=dict(raw.get("recent_actions_settings",{})) if isinstance(raw.get("recent_actions_settings"),dict) else {}
        try:
            self.reading_policy = WarmupConfig(DEFAULT_DURATION_MIN,False,False,True,
                reading_policy=raw.get('reading_policy',DEFAULT_READING_POLICY)).reading_policy
        except (TypeError,ValueError):
            self.reading_policy=DEFAULT_READING_POLICY
            self.warnings.append('阅读策略无效，已恢复默认')
        self._load_workflows(raw)
        quick = raw.get("quick_replies")
        self.quick_replies: List[str] = (
            [str(x)[:280] for x in quick if str(x).strip()][:30]
            if isinstance(quick, list)
            else list(DEFAULT_QUICK_REPLIES)
        )
        self.run = dict(RUN_DEFAULTS)
        self.run.update({k: raw[k] for k in RUN_DEFAULTS if k in raw})
        if self.run['reading_model'] not in READING_MODEL_LABELS:
            self.run['reading_model']='v10'
            self.warnings.append('养号流程未知，已恢复V10原流程')
        selected = raw.get("selected", [])
        self.selected: List[str] = [str(x) for x in selected] if isinstance(selected, list) else []

    # ---------- 读取 ----------
    def _load_section(self, saved: Any, defaults: Dict[str, Any], title: str) -> Dict[str, Any]:
        values = dict(defaults)
        if isinstance(saved, dict):
            values.update({k: saved[k] for k in defaults if k in saved})
        try:
            validate_partial(values)
            return values
        except (ValueError, TypeError, AttributeError) as exc:
            logger.warning("%s无效，已恢复默认：%s", title, exc)
            self.warnings.append(f"{title}无效，已恢复默认（{exc}）")
            return dict(defaults)

    def _load_workflows(self, raw: Dict[str, Any]) -> None:
        self.workflow_settings = DEFAULT_WORKFLOW_SETTINGS
        self.workflow_tiers: Tuple[Tuple[str, str], ...] = ()
        self.interest_terms: Tuple[str, ...] = ()
        keyword_file = raw.get("keyword_file", "")
        self.keyword_file = keyword_file if isinstance(keyword_file, str) else ""
        try:
            saved = raw.get("workflow_settings")
            if saved is not None:
                self.workflow_settings = migrate_workflow_settings(saved)
            self.workflow_tiers = tuple(tuple(row) for row in raw.get("workflow_tiers", []))
            terms = raw.get("interest_terms", [])
            if not isinstance(terms, list):
                raise ValueError("兴趣词格式错误")
            self.interest_terms = tuple(terms)
            WarmupConfig(
                DEFAULT_DURATION_MIN,
                False,
                True,
                True,
                workflow_settings=self.workflow_settings,
                workflow_tiers=self.workflow_tiers,
                interest_terms=self.interest_terms,
            )
        except (ValueError, TypeError):
            logger.warning("工作流配置无效，恢复默认设置", exc_info=True)
            self.warnings.append("工作流配置无效，已恢复默认")
            self.workflow_settings, self.workflow_tiers, self.interest_terms = (
                DEFAULT_WORKFLOW_SETTINGS,
                (),
                (),
            )
        if not self.keyword_file and self.interest_terms:
            try:
                self.keyword_file = migrate_keyword_file(self.interest_terms)
            except OSError:
                logger.warning("旧关键词迁移到TXT失败，选择TXT后再启用兴趣/搜索", exc_info=True)

    # ---------- 运行模式（阅读 / 阅读+评论 / 发推 三选一） ----------
    @property
    def mode(self) -> str:
        if self.draft["draft_enabled"]:
            return "post"
        if self.comment["comment_enabled"]:
            return "comment"
        return "read"

    def set_mode(self, mode: str) -> None:
        """切换运行模式；所需 TXT 不可用时抛 ValueError，设置保持原样。"""

        if mode not in RUN_MODES:
            raise ValueError("未知的运行模式")
        draft = {**self.draft, "draft_enabled": mode == "post"}
        comment = {**self.comment, "comment_enabled": mode == "comment"}
        if mode == "post":
            if not draft["draft_file"].strip():
                raise ValueError("还没有选择推文 TXT，请先到「设置 › 自动发推」选择文件")
            load_draft_lines(draft["draft_file"])
        if mode == "comment":
            if not comment["comment_file"].strip():
                raise ValueError("还没有选择评论 TXT，请先到「设置 › 自动评论」选择文件")
            load_draft_lines(comment["comment_file"])
        validate_partial(draft)
        validate_partial(comment)
        self.draft, self.comment = draft, comment

    # ---------- 保存 ----------
    def to_json(self) -> Dict[str, Any]:
        data: Dict[str, Any] = {
            "workflow_settings": [list(row) for row in self.workflow_settings],
            "workflow_tiers": [list(row) for row in self.workflow_tiers],
            "keyword_file": self.keyword_file,
            "interest_terms": list(self.interest_terms) if not self.keyword_file else [],
            "recent_actions_settings": dict(self.recent_actions),
            "reading_policy": list(self.reading_policy),
            "advanced": dict(self.advanced),
            "draft_settings": dict(self.draft),
            "comment_settings": dict(self.comment),
            "dashboard_settings": dict(self.dash),
            "quick_replies": list(self.quick_replies),
            "selected": sorted(set(self.selected)),
        }
        data.update(self.run)
        return data

    def save(self) -> None:
        ConfigStore.save(self.to_json())

    # ---------- 生成本批配置 ----------
    def build_config(self) -> WarmupConfig:
        run = self.run
        try:
            duration = float(str(run["duration"]).strip())
        except ValueError as exc:
            raise ValueError("单号时长请填数字（分钟），0 表示不限时") from exc
        try:
            concurrency = int(str(run["concurrency"]).strip())
        except ValueError as exc:
            raise ValueError("并发数请填 1～5 的整数") from exc
        posting = self.draft["draft_enabled"]
        return WarmupConfig(
            reading_model=run["reading_model"],
            reading_policy=self.reading_policy,
            duration_min=duration,
            window_layout="tile" if run["window_layout"] == "tile" else "cascade",
            enable_like=bool(run["like"]),
            enable_deep_visit=bool(run["deep"]),
            close_after=bool(run["close_after"]),
            random_order=bool(run["random_order"]),
            enable_jitter=bool(run["jitter"]),
            lite_mode=bool(run["lite"]),
            concurrency=concurrency,
            workflow_settings=self.workflow_settings,
            workflow_tiers=self.workflow_tiers,
            keyword_file=self.keyword_file,
            interest_terms=load_keyword_lines(self.keyword_file) if self.keyword_file and not posting else (),
            **self.draft,
            **self.comment,
            **self.advanced,
            **self.dash,
        )

    def build_service_config(self) -> WarmupConfig:
        """“立即同步”：只采集 + 发送面板回复，不跑阅读工作流。"""
        base = dataclasses.replace(
            self.build_config_lenient(),
            service_mode=True,
            duration_min=6.0,
            draft_enabled=False,
            comment_enabled=False,
            interest_terms=(),
            keyword_file="",
            stats_enabled=True,
        )
        return base

    def build_config_lenient(self) -> WarmupConfig:
        """同步任务不依赖关键词 TXT 是否可读。"""
        keyword_file = self.keyword_file
        try:
            self.keyword_file = ""
            return self.build_config()
        finally:
            self.keyword_file = keyword_file


# ======================================================================
# 模块：xmanager/ui/theme.py
# ======================================================================
"""界面主题：深色调色板、字体、DPI 缩放与 ttk 样式。"""


import math
import time
import tkinter as tk
from tkinter import font as tkfont
from tkinter import ttk
from typing import Any, Optional

UI = {
    "bg": "#0f1419",
    "side": "#0a0e13",
    "card": "#16202a",
    "card2": "#1e2b37",
    "line": "#2d3d4b",
    "text": "#e7e9ea",
    "mute": "#8b98a5",
    "faint": "#5b6b78",
    "blue": "#1d9bf0",
    "green": "#00ba7c",
    "amber": "#f5a623",
    "red": "#f4212e",
    "pink": "#f91880",
    "sel": "#1b3c57",
    "log_bg": "#070a0d",
}
TONE_COLORS = (
    ("ok", UI["green"]),
    ("warn", UI["amber"]),
    ("bad", UI["red"]),
    ("run", UI["blue"]),
    ("info", UI["mute"]),
    ("mute", UI["faint"]),
    ("alert", UI["amber"]),
)
BUTTONS = {
    "primary": ("#1d9bf0", "#4db3f5", "white"),
    "good": ("#00a06b", "#00ba7c", "white"),
    "warn": ("#b36b00", "#d98200", "white"),
    "danger": ("#b3173a", "#d21f49", "white"),
    "normal": ("#1e2b37", "#2d3d4b", "#e7e9ea"),
    "ghost": ("#16202a", "#1e2b37", "#1d9bf0"),
    "amber": ("#1e2b37", "#2d3d4b", "#f5a623"),
    "red": ("#1e2b37", "#2d3d4b", "#f4212e"),
}

UI_FONT = "TkDefaultFont"
MONO_FONT = "TkFixedFont"
_scale = 1.0


def pick_fonts(root: tk.Misc) -> None:
    """挑本机已有的中文字体与等宽字体；找不到就用系统默认。"""
    global UI_FONT, MONO_FONT
    try:
        have = set(tkfont.families(root))
    except tk.TclError:
        return
    for name in (
        "Microsoft YaHei UI",
        "Microsoft YaHei",
        "PingFang SC",
        "Noto Sans CJK SC",
        "Source Han Sans SC",
        "WenQuanYi Micro Hei",
        "WenQuanYi Zen Hei",
        "DejaVu Sans",
    ):
        if name in have:
            UI_FONT = name
            break
    for name in ("Cascadia Mono", "Consolas", "Menlo", "DejaVu Sans Mono"):
        if name in have:
            MONO_FONT = name
            break


def F(size: int = 9, bold: bool = False):
    return (UI_FONT, size, "bold") if bold else (UI_FONT, size)


def mono(size: int = 9):
    return (MONO_FONT, size)


def px(value: float) -> int:
    """把按 96 DPI 设计的像素值换算到当前屏幕。"""
    return int(round(value * _scale))


# ============================================================
# 数字与时间格式
# ============================================================
def fmt_num(value: Any) -> str:
    if value is None:
        return "—"
    try:
        return f"{int(value):,}"
    except (TypeError, ValueError):
        return str(value)


def compact_num(value: Any) -> str:
    """大卡片用的短数字：1234 -> 1,234；123456 -> 12.3万"""
    if value is None:
        return "—"
    n = int(value)
    if abs(n) >= 100_000_000:
        return f"{n / 100_000_000:.2f}亿"
    if abs(n) >= 100_000:
        return f"{n / 10_000:.1f}万"
    return f"{n:,}"


def ago(ts: Optional[float]) -> str:
    if not ts:
        return "—"
    sec = max(0, time.time() - ts)
    if sec < 60:
        return "刚刚"
    if sec < 3600:
        return f"{int(sec // 60)} 分钟前"
    if sec < 86400:
        return f"{int(sec // 3600)} 小时前"
    return f"{int(sec // 86400)} 天前"


def nice_peak(value: float) -> float:
    if value <= 4:
        return 4.0
    raw = value / 4
    mag = 10 ** math.floor(math.log10(raw))
    for m in (1, 2, 2.5, 5, 10):
        if raw <= m * mag:
            return m * mag * 4
    return 10 * mag * 4


# ============================================================
# ttk 样式与经典控件默认值
# ============================================================
def apply_theme(root: tk.Tk) -> None:
    global _scale
    try:
        _scale = max(1.0, float(root.winfo_fpixels("1i")) / 96.0)
    except tk.TclError:
        _scale = 1.0
    pick_fonts(root)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except tk.TclError:
        pass
    u = UI
    style.configure(
        ".",
        background=u["bg"],
        foreground=u["text"],
        fieldbackground=u["card2"],
        bordercolor=u["line"],
        lightcolor=u["line"],
        darkcolor=u["line"],
        troughcolor=u["card2"],
        font=F(9),
    )
    style.configure(
        "Treeview",
        background=u["card"],
        fieldbackground=u["card"],
        foreground=u["text"],
        rowheight=px(27),
        borderwidth=0,
        relief="flat",
    )
    style.configure(
        "Treeview.Heading",
        background=u["card2"],
        foreground=u["mute"],
        relief="flat",
        font=F(9, True),
        padding=(6, 5),
        borderwidth=0,
    )
    style.map("Treeview.Heading", background=[("active", u["line"])])
    style.map("Treeview", background=[("selected", u["sel"])], foreground=[("selected", u["text"])])
    for option in ("foreground", "background"):  # 修复部分 Tk 版本里标签颜色失效的问题
        fixed = [e for e in style.map("Treeview", query_opt=option) if e[:2] != ("!disabled", "!selected")]
        style.map("Treeview", **{option: fixed})
    style.configure(
        "TCombobox",
        fieldbackground=u["card2"],
        background=u["card2"],
        foreground=u["text"],
        arrowcolor=u["mute"],
        bordercolor=u["line"],
        selectbackground=u["card2"],
        selectforeground=u["text"],
        padding=3,
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", u["card2"])],
        foreground=[("readonly", u["text"])],
        selectbackground=[("readonly", u["card2"])],
        selectforeground=[("readonly", u["text"])],
    )
    style.configure(
        "TScrollbar",
        background=u["card2"],
        troughcolor=u["card"],
        bordercolor=u["card"],
        arrowcolor=u["mute"],
        relief="flat",
    )
    style.map("TScrollbar", background=[("active", u["line"])])
    style.configure(
        "Horizontal.TProgressbar",
        troughcolor=u["card2"],
        background=u["blue"],
        bordercolor=u["card2"],
        lightcolor=u["blue"],
        darkcolor=u["blue"],
        thickness=px(8),
    )
    style.configure("TNotebook", background=u["bg"], borderwidth=0, tabmargins=(0, 0, 0, 0))
    style.configure(
        "TNotebook.Tab",
        background=u["bg"],
        foreground=u["mute"],
        padding=(px(16), px(7)),
        borderwidth=0,
        font=F(10),
    )
    style.map(
        "TNotebook.Tab",
        background=[("selected", u["card"]), ("active", u["card2"])],
        foreground=[("selected", u["blue"]), ("active", u["text"])],
        expand=[("selected", (0, 0, 0, 0))],
        padding=[("selected", (px(16), px(7)))],
    )
    style.configure("TFrame", background=u["bg"])
    style.configure("TLabel", background=u["bg"], foreground=u["text"])
    defaults = {
        "*Toplevel.background": u["bg"],
        "*Frame.background": u["bg"],
        "*LabelFrame.background": u["bg"],
        "*LabelFrame.foreground": u["mute"],
        "*Label.background": u["bg"],
        "*Label.foreground": u["text"],
        "*Button.background": u["card2"],
        "*Button.foreground": u["text"],
        "*Button.activeBackground": u["line"],
        "*Button.activeForeground": u["text"],
        "*Button.relief": "flat",
        "*Button.borderWidth": 0,
        "*Button.highlightThickness": 0,
        "*Button.padX": 10,
        "*Button.padY": 3,
        "*Button.disabledForeground": u["faint"],
        "*Entry.background": u["card2"],
        "*Entry.foreground": u["text"],
        "*Entry.insertBackground": u["text"],
        "*Entry.relief": "flat",
        "*Entry.highlightThickness": 1,
        "*Entry.highlightBackground": u["line"],
        "*Entry.highlightColor": u["blue"],
        "*Entry.selectBackground": u["blue"],
        "*Entry.disabledBackground": u["card"],
        "*Entry.disabledForeground": u["faint"],
        "*Spinbox.background": u["card2"],
        "*Spinbox.foreground": u["text"],
        "*Spinbox.insertBackground": u["text"],
        "*Spinbox.relief": "flat",
        "*Spinbox.highlightThickness": 1,
        "*Spinbox.highlightBackground": u["line"],
        "*Spinbox.buttonBackground": u["card2"],
        "*Text.background": u["card2"],
        "*Text.foreground": u["text"],
        "*Text.insertBackground": u["text"],
        "*Text.relief": "flat",
        "*Text.highlightThickness": 1,
        "*Text.highlightBackground": u["line"],
        "*Text.highlightColor": u["blue"],
        "*Text.selectBackground": u["sel"],
        "*Listbox.background": u["card2"],
        "*Listbox.foreground": u["text"],
        "*Listbox.relief": "flat",
        "*Listbox.highlightThickness": 0,
        "*Listbox.selectBackground": u["sel"],
        "*Checkbutton.background": u["bg"],
        "*Checkbutton.foreground": u["text"],
        "*Checkbutton.selectColor": u["card2"],
        "*Checkbutton.activeBackground": u["bg"],
        "*Checkbutton.activeForeground": u["text"],
        "*Checkbutton.highlightThickness": 0,
        "*Checkbutton.borderWidth": 0,
        "*Radiobutton.highlightThickness": 0,
        "*Radiobutton.borderWidth": 0,
        "*Radiobutton.background": u["bg"],
        "*Radiobutton.foreground": u["text"],
        "*Radiobutton.selectColor": u["card2"],
        "*Radiobutton.activeBackground": u["bg"],
        "*Radiobutton.activeForeground": u["text"],
        "*Canvas.background": u["bg"],
        "*Menu.background": u["card2"],
        "*Menu.foreground": u["text"],
        "*Menu.activeBackground": u["sel"],
        "*Menu.activeForeground": u["text"],
        "*Menu.relief": "flat",
        "*TCombobox*Listbox.background": u["card2"],
        "*TCombobox*Listbox.foreground": u["text"],
        "*TCombobox*Listbox.selectBackground": u["sel"],
        "*TCombobox*Listbox.selectForeground": u["text"],
        "*Font": F(9),
    }
    for pattern, value in defaults.items():
        root.option_add(pattern, value)

theme = _sys.modules[__name__]  # 单文件中 `theme.X` 指向本模块全局


# ======================================================================
# 模块：xmanager/ui/base.py
# ======================================================================
"""页面基类。每个页面只负责自己的控件，数据与任务控制都经由 app。"""


import tkinter as tk
from typing import TYPE_CHECKING


if TYPE_CHECKING:  # pragma: no cover
    pass


class Page:
    key = ""
    icon = ""
    title = ""
    subtitle = ""
    auto_refresh = False  # 可见时每 3 秒刷新一次

    def __init__(self, app: "WarmupApp", host: tk.Frame):
        self.app = app
        self.frame = tk.Frame(host, bg=UI["bg"])
        self.frame.grid(row=0, column=0, sticky="nsew")
        self.build()

    # 子类实现
    def build(self) -> None:
        raise NotImplementedError

    def refresh(self, force: bool = False) -> None:
        pass

    def on_show(self) -> None:
        self.refresh(force=True)

    # 通用布局：页面顶部工具条
    def toolbar(self, row: int = 0, columnspan: int = 1) -> tk.Frame:
        bar = tk.Frame(self.frame, bg=UI["bg"])
        bar.grid(row=row, column=0, columnspan=columnspan, sticky="ew", padx=px(18), pady=(px(14), px(8)))
        return bar


# ======================================================================
# 模块：xmanager/ui/widgets.py
# ======================================================================
"""可复用的界面组件：按钮、卡片、表格、表单行、分段选择、图表。

全部基于 tkinter 自绘，无第三方依赖。
"""


import math
import tkinter as tk
from tkinter import filedialog, ttk
from tkinter import font as tkfont
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Tuple



def ui_button(parent, text, command, kind="normal", width=None, **kw) -> tk.Button:
    bg, active, fg = BUTTONS[kind]
    button = tk.Button(
        parent,
        text=text,
        command=command,
        bg=bg,
        fg=fg,
        activebackground=active,
        activeforeground=fg,
        relief="flat",
        bd=0,
        padx=px(12),
        pady=px(5),
        cursor="hand2",
        font=F(9, kind in ("primary", "good", "danger", "warn", "amber", "red")),
        highlightthickness=0,
        disabledforeground=UI["faint"],
        **kw,
    )
    if width:
        button.configure(width=width)
    return button


def label(parent, text="", tone="text", size=9, bold=False, bg=None, **kw) -> tk.Label:
    return tk.Label(parent, text=text, fg=UI[tone], bg=bg or parent.cget("bg"), font=F(size, bold), **kw)


def hint(parent, text, wrap=None, **kw) -> tk.Label:
    """浅色说明文字；wrap 为像素宽度。"""
    return tk.Label(
        parent,
        text=text,
        fg=UI["faint"],
        bg=parent.cget("bg"),
        font=F(8),
        justify="left",
        anchor="w",
        wraplength=px(wrap) if wrap else 0,
        **kw,
    )


def card(parent, title: Optional[str] = None, subtitle: str = "", pad=12) -> Tuple[tk.Frame, tk.Frame]:
    """带细边框的卡片；返回 (外框, 内容区)。"""
    outer = tk.Frame(parent, bg=UI["card"], highlightbackground=UI["line"], highlightthickness=1)
    if title:
        head = tk.Frame(outer, bg=UI["card"])
        head.pack(fill="x", padx=px(pad), pady=(px(10), 0))
        tk.Label(head, text=title, bg=UI["card"], fg=UI["text"], font=F(10, True)).pack(side="left")
        if subtitle:
            tk.Label(head, text=subtitle, bg=UI["card"], fg=UI["faint"], font=F(8)).pack(
                side="left", padx=px(8)
            )
        outer.head = head  # type: ignore[attr-defined]
    body = tk.Frame(outer, bg=UI["card"])
    body.pack(fill="both", expand=True, padx=px(pad), pady=px(10))
    return outer, body


def check(parent, text, variable, tone="text", command=None) -> tk.Checkbutton:
    bg = parent.cget("bg")
    return tk.Checkbutton(
        parent,
        text=text,
        variable=variable,
        fg=UI[tone],
        bg=bg,
        selectcolor=UI["card2"],
        activebackground=bg,
        activeforeground=UI[tone],
        anchor="w",
        command=command,
    )


def entry(parent, variable, width=8, **kw) -> tk.Entry:
    return tk.Entry(parent, textvariable=variable, width=width, **kw)


def combo(parent, variable, values, width=14) -> ttk.Combobox:
    return ttk.Combobox(parent, textvariable=variable, values=tuple(values), state="readonly", width=width)


class Form:
    """两列表单：左侧标签、中间输入控件、右侧说明。"""

    def __init__(self, parent):
        self.frame = tk.Frame(parent, bg=parent.cget("bg"))
        self.frame.columnconfigure(2, weight=1)
        self.row = 0

    def add(
        self,
        text: str,
        widget_factory: Callable[[tk.Frame], tk.Widget],
        note: str = "",
        sticky="w",
        wide=False,
    ) -> tk.Widget:
        """wide=True 时控件横跨输入列与说明列（用于文件路径等长控件）。"""
        bg = self.frame.cget("bg")
        tk.Label(self.frame, text=text, bg=bg, fg=UI["mute"], anchor="w").grid(
            row=self.row, column=0, sticky="w", pady=px(4)
        )
        widget = widget_factory(self.frame)
        widget.grid(
            row=self.row, column=1, columnspan=2 if wide else 1, sticky=sticky, padx=px(10), pady=px(4)
        )
        if note and not wide:
            tk.Label(self.frame, text=note, bg=bg, fg=UI["faint"], font=F(8), anchor="w").grid(
                row=self.row, column=2, sticky="w"
            )
        self.row += 1
        return widget

    def span(self, widget: tk.Widget, pady=4) -> tk.Widget:
        widget.grid(row=self.row, column=0, columnspan=3, sticky="ew", pady=px(pady))
        self.row += 1
        return widget


class FilePicker(tk.Frame):
    """文件路径输入框 + 选择按钮。"""

    def __init__(
        self,
        parent,
        variable: tk.StringVar,
        title: str,
        on_pick: Optional[Callable[[], None]] = None,
        filetypes=(("文本文件", "*.txt"), ("所有文件", "*.*")),
    ):
        super().__init__(parent, bg=parent.cget("bg"))
        self.variable, self.title, self.on_pick, self.filetypes = variable, title, on_pick, filetypes
        tk.Entry(self, textvariable=variable, width=64).pack(side="left", fill="x", expand=True, ipady=px(2))
        ui_button(self, "选择文件…", self.pick).pack(side="left", padx=(px(6), 0))

    def pick(self) -> None:
        name = filedialog.askopenfilename(
            parent=self.winfo_toplevel(), title=self.title, filetypes=list(self.filetypes)
        )
        if name:
            self.variable.set(name)
            if self.on_pick:
                self.on_pick()


class Segmented(tk.Frame):
    """分段选择器（单选按钮组的卡片化外观）。"""

    def __init__(
        self,
        parent,
        options: Sequence[Tuple[str, str]],
        command: Callable[[str], None],
        value: Optional[str] = None,
    ):
        super().__init__(parent, bg=UI["card2"], highlightthickness=0)
        self.command = command
        self.buttons: Dict[str, tk.Label] = {}
        self.value = value or options[0][0]
        for i, (key, text) in enumerate(options):
            self.columnconfigure(i, weight=1, uniform="seg")
            item = tk.Label(
                self,
                text=text,
                bg=UI["card2"],
                fg=UI["mute"],
                font=F(9),
                padx=px(8),
                pady=px(6),
                cursor="hand2",
            )
            item.grid(row=0, column=i, sticky="nsew", padx=1, pady=1)
            item.bind("<Button-1>", lambda _e, k=key: self.command(k))
            self.buttons[key] = item
        self.set(self.value)

    def set(self, value: str) -> None:
        self.value = value
        for key, item in self.buttons.items():
            on = key == value
            item.configure(
                bg=UI["blue"] if on else UI["card2"], fg="white" if on else UI["mute"], font=F(9, on)
            )


class ScrollFrame(tk.Frame):
    """垂直滚动容器：内容放在 self.inner 里。"""

    def __init__(self, parent, bg=None):
        bg = bg or parent.cget("bg")
        super().__init__(parent, bg=bg)
        self.canvas = tk.Canvas(self, bg=bg, highlightthickness=0, bd=0)
        bar = ttk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.inner = tk.Frame(self.canvas, bg=bg)
        self._win = self.canvas.create_window((0, 0), window=self.inner, anchor="nw")
        self.canvas.configure(yscrollcommand=bar.set)
        self.canvas.pack(side="left", fill="both", expand=True)
        bar.pack(side="right", fill="y")
        self.inner.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._win, width=e.width))
        for widget in (self.canvas, self.inner):
            widget.bind("<Enter>", lambda _e: self._wheel(True))
            widget.bind("<Leave>", lambda _e: self._wheel(False))

    def _wheel(self, on: bool) -> None:
        if on:
            self.canvas.bind_all(
                "<MouseWheel>",
                lambda e: self.canvas.yview_scroll(
                    int(-e.delta / 120) or (-1 if e.delta > 0 else 1), "units"
                ),
            )
            self.canvas.bind_all("<Button-4>", lambda _e: self.canvas.yview_scroll(-2, "units"))
            self.canvas.bind_all("<Button-5>", lambda _e: self.canvas.yview_scroll(2, "units"))
        else:
            for seq in ("<MouseWheel>", "<Button-4>", "<Button-5>"):
                self.canvas.unbind_all(seq)


def make_tree(parent, cols, heads, widths, height=10, selectmode="extended", anchors=None, stretch=()):
    frame = tk.Frame(parent, bg=UI["card"])
    tree = ttk.Treeview(frame, columns=cols, show="headings", height=height, selectmode=selectmode)
    for col, head, width in zip(cols, heads, widths):
        where = (anchors or {}).get(col, "w")
        tree.heading(col, text=head, anchor=where)
        tree.column(col, width=px(width), minwidth=px(36), anchor=where, stretch=col in stretch)
    bar = ttk.Scrollbar(frame, orient="vertical", command=tree.yview)
    tree.configure(yscrollcommand=bar.set)
    tree.pack(side="left", fill="both", expand=True)
    bar.pack(side="right", fill="y")
    for tone, color in TONE_COLORS:
        tree.tag_configure(tone, foreground=color)
    return frame, tree


def set_text(widget: tk.Text, content: str, readonly: bool = True) -> None:
    widget.configure(state="normal")
    widget.delete("1.0", "end")
    widget.insert("1.0", content)
    if readonly:
        widget.configure(state="disabled")


def text_box(parent, height=4, readonly=False, width=40, **kw) -> tk.Text:
    box = tk.Text(parent, width=width, height=height, wrap="word", font=F(10), **kw)
    if readonly:
        box.configure(state="disabled")
    return box


def popup_menu(widget: tk.Widget, items: Iterable[Optional[Tuple[str, Callable[[], None]]]], event) -> None:
    menu = tk.Menu(widget, tearoff=0)
    for item in items:
        if item is None:
            menu.add_separator()
        elif item:  # 空元组表示本次不显示该项
            menu.add_command(label=item[0], command=item[1])
    try:
        menu.tk_popup(event.x_root, event.y_root)
    finally:
        menu.grab_release()


class MiniChart(tk.Canvas):
    """极简图表：横向条形图 / 折线图。窗口大小变化时自动重绘。"""

    def __init__(self, parent, height=190):
        super().__init__(parent, height=px(height), bg=UI["card"], highlightthickness=0, bd=0)
        self._painter: Optional[Callable[[int, int], None]] = None
        self._font = tkfont.Font(family=theme.UI_FONT, size=9)
        self.bind("<Configure>", lambda _e: self.redraw())

    def redraw(self) -> None:
        self.delete("all")
        if self._painter is not None and self.winfo_width() > 60:
            self._painter(self.winfo_width(), self.winfo_height())

    def message(self, text: str) -> None:
        self._painter = lambda w, h: self.create_text(
            w / 2, h / 2, text=text, fill=UI["faint"], font=F(10), width=max(80, w - 40), justify="center"
        )
        self.redraw()

    def _clip(self, text: str, pixels: int) -> str:
        if self._font.measure(text) <= pixels:
            return text
        while text and self._font.measure(text + "…") > pixels:
            text = text[:-1]
        return text + "…"

    def bars(self, items, color=None, empty="暂无数据") -> None:
        items = [(str(a), float(b)) for a, b in items]
        if not items:
            self.message(empty)
            return
        color = color or UI["blue"]

        def paint(w: int, h: int) -> None:
            n, top = len(items), 6
            label_w, value_w = min(px(160), max(px(90), int(w * 0.3))), px(70)
            row = (h - top * 2) / n
            bar_h = max(6, min(px(16), row * 0.55))
            peak = max(v for _, v in items) or 1
            span = max(20, w - label_w - value_w - 16)
            x0 = label_w + 8
            for i, (name, value) in enumerate(items):
                cy = top + row * (i + 0.5)
                self.create_text(
                    label_w, cy, text=self._clip(name, label_w - 4), anchor="e", fill=UI["mute"], font=F(9)
                )
                self.create_rectangle(
                    x0, cy - bar_h / 2, x0 + span, cy + bar_h / 2, fill=UI["card2"], outline=""
                )
                length = max(3, span * value / peak) if value > 0 else 3
                self.create_rectangle(x0, cy - bar_h / 2, x0 + length, cy + bar_h / 2, fill=color, outline="")
                self.create_text(
                    x0 + span + 8, cy, text=fmt_num(int(value)), anchor="w", fill=UI["text"], font=F(9, True)
                )

        self._painter = paint
        self.redraw()

    def lines(self, labels, series, empty="暂无数据") -> None:
        """series: [(名称, [数值...], 颜色)]"""
        if not labels or not series:
            self.message(empty)
            return

        def paint(w: int, h: int) -> None:
            left, right, top, bottom = px(46), px(16), px(30), px(26)
            peak = nice_peak(max([max(vals) for _, vals, _ in series if vals] + [1]))
            pw, ph = w - left - right, h - top - bottom
            for g in range(5):
                y = top + ph * g / 4
                self.create_line(left, y, w - right, y, fill=UI["line"], dash=(2, 4) if 0 < g < 4 else ())
                self.create_text(
                    left - 8,
                    y,
                    text=fmt_num(int(peak * (4 - g) / 4)),
                    anchor="e",
                    fill=UI["faint"],
                    font=F(8),
                )
            n = len(labels)
            xs = [left + (pw * i / (n - 1) if n > 1 else pw / 2) for i in range(n)]
            step = max(1, math.ceil(n / 8))
            for i, text in enumerate(labels):
                if i % step == 0 or i == n - 1:
                    edge = "e" if (i == n - 1 and n > 1) else "w" if (i == 0 and n > 1) else "center"
                    self.create_text(
                        xs[i], h - bottom + 14, text=text, fill=UI["faint"], font=F(8), anchor=edge
                    )
            legend_x = left
            for name, values, color in series:
                pts = [
                    (xs[i], top + ph * (1 - min(values[i], peak) / peak)) for i in range(min(n, len(values)))
                ]
                if len(pts) > 1:
                    self.create_line(*[c for p in pts for c in p], fill=color, width=2, joinstyle="round")
                for x, y in pts:
                    self.create_oval(x - 3, y - 3, x + 3, y + 3, fill=color, outline=UI["card"])
                if pts and values:
                    self.create_text(
                        pts[-1][0],
                        pts[-1][1] - 11,
                        text=fmt_num(values[len(pts) - 1]),
                        fill=color,
                        font=F(8, True),
                    )
                self.create_rectangle(legend_x, 9, legend_x + 10, 19, fill=color, outline="")
                self.create_text(legend_x + 15, 14, text=name, anchor="w", fill=UI["mute"], font=F(9))
                legend_x += 40 + self._font.measure(name)

        self._painter = paint
        self.redraw()


class StageStrip(tk.Canvas):
    """执行流程的“箭头条”：已完成 / 进行中 / 跳过 / 待执行 四种状态。"""

    STYLE = {
        "done": ("#0e4f3c", "#00ba7c", "#b6f2dc"),
        "current": ("#1d9bf0", "#7cc8f7", "#ffffff"),
        "skipped": ("#16202a", "#2d3d4b", "#5b6b78"),
        "todo": ("#1e2b37", "#2d3d4b", "#8b98a5"),
    }
    MARK = {"done": "✔ ", "current": "▶ ", "skipped": "– ", "todo": ""}

    def __init__(self, parent, height=78):
        super().__init__(parent, height=px(height), bg=UI["bg"], highlightthickness=0, bd=0)
        self._stages: List[Tuple[str, str, str]] = []
        self.bind("<Configure>", lambda _e: self.redraw())

    def show(self, stages) -> None:
        self._stages = list(stages)
        self.redraw()

    def redraw(self) -> None:
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        n = len(self._stages)
        if n == 0 or width < 80:
            return
        pad, notch = 3, px(16)
        cell = (width - pad * 2) / n
        for i, (text, state, sub) in enumerate(self._stages):
            fill, edge, ink = self.STYLE[state]
            x0, x1 = pad + cell * i, pad + cell * (i + 1)
            y0, y1, mid = 6, height - 6, height / 2
            pts = [x0, y0, x1 - notch, y0, x1, mid, x1 - notch, y1, x0, y1]
            if i > 0:
                pts += [x0 + notch, mid]
            self.create_polygon(*pts, fill=fill, outline=edge, width=2 if state == "current" else 1)
            cx = (x0 + x1) / 2 + (notch / 4 if i > 0 else 0)
            self.create_text(
                cx,
                mid - (px(8) if sub else 0),
                text=self.MARK[state] + text,
                fill=ink,
                font=F(10, state == "current"),
                width=max(40, cell - notch * 2),
            )
            if sub:
                self.create_text(cx, mid + px(13), text=sub, fill=ink, font=F(8))


# ======================================================================
# 模块：xmanager/ui/accounts.py
# ======================================================================
"""账号与任务：比特环境列表、勾选、排队控制，以及右侧的运行模式与本批参数。"""


import os
import tkinter as tk
from tkinter import messagebox, ttk
from typing import Any, Dict, List



class AccountsPage(Page):
    key, icon, title = "accounts", "👥", "账号与任务"
    subtitle = "勾选账号 → 选择运行模式 → 点右上角开始"

    COLS = ("select", "index", "group", "id", "name", "followers", "likes", "unread", "today", "status")

    def build(self) -> None:
        app = self.app
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.search_var = tk.StringVar()
        self.count_var = tk.StringVar(value="")

        tools = self.toolbar(columnspan=2)
        ui_button(tools, "🔄 刷新比特环境", app.load_browsers, "primary").pack(side="left")
        tk.Label(tools, text="分组", fg=UI["mute"], bg=UI["bg"]).pack(side="left", padx=(px(16), px(4)))
        self.group_combo = ttk.Combobox(tools, state="readonly", width=12, values=("全部",))
        self.group_combo.set(app.settings.run.get("group") or "全部")
        self.group_combo.pack(side="left")
        self.group_combo.bind("<<ComboboxSelected>>", lambda _e: self.render_table())
        tk.Label(tools, text="搜索", fg=UI["mute"], bg=UI["bg"]).pack(side="left", padx=(px(16), px(4)))
        tk.Entry(tools, textvariable=self.search_var, width=20).pack(side="left", ipady=px(3))
        self.search_var.trace_add("write", lambda *_: self.render_table())
        for text, cmd in (
            ("全选", lambda: self.set_all_check(True)),
            ("全不选", lambda: self.set_all_check(False)),
            ("反选", self.invert_check),
            ("重选失败账号", self.select_failed),
            ("恢复待执行队列", self.restore_pending),
        ):
            ui_button(tools, text, cmd).pack(side="left", padx=(px(4) if text != "全选" else px(16), 0))
        tk.Label(tools, textvariable=self.count_var, fg=UI["blue"], bg=UI["bg"], font=F(9)).pack(side="right")

        outer, body = card(page, "账号列表", "点第一列勾选 · 空格切换所选行 · 双击看执行流程 · 右键更多")
        outer.grid(row=1, column=0, sticky="nsew", padx=(px(18), px(10)), pady=(0, px(14)))
        frame, self.tree = make_tree(
            body,
            self.COLS,
            ("选择", "#", "分组", "环境ID", "账号名称", "粉丝", "累计获赞", "未读", "今日", "当前状态"),
            (50, 40, 86, 110, 170, 66, 78, 54, 50, 210),
            height=14,
            stretch=("name", "status"),
            anchors={
                "select": "center",
                "index": "center",
                "followers": "e",
                "likes": "e",
                "unread": "e",
                "today": "center",
            },
        )
        frame.pack(fill="both", expand=True)
        self.tree.bind("<Button-1>", self.on_click)
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-3>", self.on_menu)
        self.tree.bind("<space>", lambda _e: self.toggle_rows(self.tree.selection()))
        acts = tk.Frame(body, bg=UI["card"])
        acts.pack(fill="x", pady=(px(10), 0))
        self.cancel_sel_btn = ui_button(acts, "取消选中排队", self.cancel_selected, state="disabled")
        self.cancel_sel_btn.pack(side="left")
        self.cancel_all_btn = ui_button(
            acts, "取消全部排队", lambda: app.cancel_queue(None), state="disabled"
        )
        self.cancel_all_btn.pack(side="left", padx=px(8))
        ui_button(acts, "⚡ 立即同步已勾选账号", self.sync_checked, "primary").pack(side="right")
        ui_button(acts, "🔁 查看所选流程", self.flow_of_selection).pack(side="right", padx=px(8))
        self._build_side(page)

    def _build_side(self, page) -> None:
        app = self.app
        side = ScrollFrame(page, bg=UI["bg"])
        side.configure(width=px(340))
        side.grid(row=1, column=1, sticky="ns", padx=(0, px(18)), pady=(0, px(14)))
        side.grid_propagate(False)
        side = side.inner
        side.columnconfigure(0, weight=1)

        outer, body = card(side, "运行模式", "三选一，下一批生效")
        outer.grid(row=0, column=0, sticky="ew")
        self.mode_seg = Segmented(
            body,
            [("read", "阅读养号"), ("comment", "阅读+评论"), ("post", "TXT 发推")],
            self.on_mode,
            app.settings.mode,
        )
        self.mode_seg.pack(fill="x")
        self.mode_summary = tk.Label(
            body,
            text="",
            bg=UI["card"],
            fg=UI["mute"],
            font=F(8),
            justify="left",
            anchor="w",
            wraplength=px(300),
        )
        self.mode_summary.pack(fill="x", pady=(px(8), px(4)))
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        ui_button(row, "工作流目录 ›", lambda: app.show_page("workflows"), "ghost").pack(side="left")
        ui_button(row, "调整模式设置 ›", self.open_mode_settings, "ghost").pack(side="right")

        model_row=tk.Frame(body,bg=UI['card']);model_row.pack(fill='x',pady=(px(8),px(2)))
        tk.Label(model_row,text='养号流程',bg=UI['card'],fg=UI['mute']).pack(anchor='w')
        self.reading_model_var=tk.StringVar(value=READING_MODEL_LABELS[app.settings.run['reading_model']])
        model_box=ttk.Combobox(model_row,textvariable=self.reading_model_var,
            values=list(READING_MODEL_LABELS.values()),state='readonly',width=28)
        model_box.pack(fill='x',pady=px(3))
        model_box.bind('<<ComboboxSelected>>',self.on_reading_model)
        hint(body,'流程与操作权限分别设置；下一批生效。V11.1持续阅读，配额仅作支线上限。',wrap=300).pack(fill='x')
        ui_button(body,'V11.1 阅读参数 ›',lambda:(app.show_page('settings'),app.pages['settings'].select_tab('reading')),'ghost').pack(anchor='w')

        outer, body = card(side, "本次运行参数")
        outer.grid(row=1, column=0, sticky="ew", pady=px(10))
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=px(3))
        tk.Label(row, text="单号时长（分钟，0 不限）", bg=UI["card"], fg=UI["mute"]).pack(side="left")
        tk.Entry(row, textvariable=app.duration_var, width=7, justify="center").pack(
            side="right", ipady=px(2)
        )
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=px(3))
        tk.Label(row, text="同时运行的账号数上限", bg=UI["card"], fg=UI["mute"]).pack(side="left")
        tk.Spinbox(
            row, from_=1, to=MAX_ACTIVE_BROWSERS, textvariable=app.concurrency_var, width=4, justify="center"
        ).pack(side="right", ipady=px(2))
        flags = app.run_flags
        for text, key, tone in (
            ("允许点赞", "like", "green"),
            ("允许深读评论区", "deep", "green"),
            ("🔀 随机顺序启动（打乱排队）", "random_order", "blue"),
            ("结束关窗（仅本次启动的）", "close_after", "mute"),
            ("跳过今日已跑完的账号", "skip_done", "mute"),
            ("省流量（不加载图片 / 媒体 / 字体）", "lite", "mute"),
        ):
            check(body, text, flags[key], tone).pack(fill="x", pady=1)
        hint(
            body,
            "工作流数量偏移 ±10%～60%（每号每次独立抽样）\nV10按原工作流结束；V11.1按时长连续阅读，0持续至停止",
            wrap=300,
        ).pack(fill="x", pady=(px(6), 0))

        outer, body = card(side, "浏览器窗口排列")
        outer.grid(row=2, column=0, sticky="ew")
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        layout = ttk.Combobox(
            row,
            textvariable=app.window_layout_var,
            values=("有序堆叠", "整齐平铺"),
            state="readonly",
            width=10,
        )
        layout.pack(side="left")
        layout.bind("<<ComboboxSelected>>", lambda _e: app.arrange_browser_windows())
        ui_button(row, "一键整理窗口", app.arrange_browser_windows).pack(side="right")

    # ---------- 模式 ----------
    def on_mode(self, mode: str) -> None:
        if not self.app.set_mode(mode):
            self.mode_seg.set(self.app.settings.mode)

    def open_mode_settings(self) -> None:
        mode = self.app.settings.mode
        if mode == "read":
            self.app.show_page("workflows")
            return
        self.app.pages["settings"].select_tab("post" if mode == "post" else "comment")
        self.app.show_page("settings")

    def update_mode(self, mode: str) -> None:
        s = self.app.settings
        self.mode_seg.set(mode)
        if mode == "post":
            d = s.draft
            schedule = {
                "immediate": "点开始立即执行",
                "once": f"定时 {d['draft_schedule_date']} {d['draft_schedule_time']}",
                "daily": f"每天 {d['draft_schedule_time']}",
            }[d["draft_schedule_mode"]]
            text = (
                f"推文 TXT：{os.path.basename(d['draft_file']) or '未选择'}\n"
                f"每号最多 {d['draft_count']} 条 · 间隔 {d['draft_interval']:g} 秒 · "
                f"{'各号各发一遍' if d['draft_scope'] == 'per_account' else '共用队列'} · {schedule}\n"
                "本模式只发推，不执行阅读工作流。"
            )
        elif mode == "comment":
            c = s.comment
            text = (
                f"评论 TXT：{os.path.basename(c['comment_file']) or '未选择'}\n"
                f"每号最多 {c['comment_count']} 条 · 间隔 {c['comment_interval']:g} 秒 · "
                f"{'随机' if c['comment_order'] == 'random' else '顺序'}读取\n阅读正文后按条件评论，全局去重。"
            )
        else:
            auto = sum(
                1
                for key, on, base in s.workflow_settings
                if on and base > 0 and not WORKFLOW_BY_KEY[key].manual_only
            )
            text = f"已启用自动工作流 {auto} 项\n关键词 TXT：{os.path.basename(s.keyword_file) or '未选择（兴趣 / 搜索类不执行）'}"
        self.mode_summary.configure(text=f"【{MODE_LABEL[mode]}】\n{text}")

    # ---------- 表格 ----------
    def current_group(self) -> str:
        return self.group_combo.get() or "全部"

    def set_browsers(self, items: List[Dict[str, Any]]) -> None:
        groups = {"全部"} | {(it.get("groupName") or "默认分组") for it in items}
        current = self.current_group()
        self.group_combo.configure(values=sorted(groups))
        self.group_combo.set(current if current in groups else "全部")
        self.render_table()

    def render_table(self) -> None:
        app = self.app
        tree = self.tree
        tree.delete(*tree.get_children())
        group_filter = self.current_group()
        query = self.search_var.get().strip().casefold()
        try:
            data = {r["account"]: r for r in app.store.overview(local_midnight())}
        except Exception:
            logger.debug("读取看板数据失败", exc_info=True)
            data = {}
        shown = 0
        for idx, it in enumerate(app.raw_browsers, 1):
            bid = browser_id(it)
            if not bid:
                continue
            group = it.get("groupName") or "默认分组"
            if group_filter != "全部" and group != group_filter:
                continue
            name = browser_name(it)
            if query and query not in f"{bid} {name} {group}".casefold():
                continue
            text, tone = app.status_map.get(bid, ("", "info"))
            d = data.get(bid)
            unread = ((d["dm_unread"] or 0) + (d["notif_unread"] or 0)) if d else None
            try:
                tree.insert(
                    "",
                    "end",
                    iid=bid,
                    tags=(tone,),
                    values=(
                        "☑" if bid in app.selected_ids else "☐",
                        idx,
                        group,
                        bid,
                        name,
                        fmt_num(d["followers"]) if d else "—",
                        fmt_num(d["likes"]) if d else "—",
                        fmt_num(unread) if d else "—",
                        "✔" if bid in app.done_today else "",
                        text,
                    ),
                )
                shown += 1
            except tk.TclError:
                pass
        self._update_count(shown)

    def _update_count(self, shown=None) -> None:
        if shown is None:
            shown = len(self.tree.get_children())
        total = sum(1 for it in self.app.raw_browsers if browser_id(it))
        self.count_var.set(f"已勾选 {len(self.app.selected_ids)} · 显示 {shown} / 共 {total}")

    def update_status(self, bid: str, text: str, tone: str) -> None:
        if self.tree.exists(bid):
            self.tree.set(bid, "status", text)
            self.tree.item(bid, tags=(tone,))

    def refresh(self, force: bool = False) -> None:
        self.render_table()
        self.update_mode(self.app.settings.mode)

    def set_queue_buttons(self, enabled: bool) -> None:
        state = "normal" if enabled else "disabled"
        self.cancel_sel_btn.configure(state=state)
        self.cancel_all_btn.configure(state=state)

    # ---------- 勾选 ----------
    def toggle_rows(self, rows) -> None:
        selected = self.app.selected_ids
        for row in rows:
            if row in selected:
                selected.discard(row)
            else:
                selected.add(row)
            if self.tree.exists(row):
                self.tree.set(row, "select", "☑" if row in selected else "☐")
        self._update_count()

    def on_click(self, event) -> None:
        if self.tree.identify("region", event.x, event.y) != "cell":
            return
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) == "#1":
            self.toggle_rows([row])

    def set_all_check(self, state: bool) -> None:
        for bid in self.tree.get_children():
            (self.app.selected_ids.add if state else self.app.selected_ids.discard)(bid)
        self.render_table()

    def invert_check(self) -> None:
        self.toggle_rows(self.tree.get_children())

    def select_failed(self) -> None:
        app = self.app
        app.selected_ids = {
            bid
            for bid, result in app.batch_results.items()
            if result not in (*SUCCESS_RESULTS, Result.CANCELLED, Result.STOPPED)
        }
        self.render_table()
        app.log(f"已勾选上一批失败账号 {len(app.selected_ids)} 个，点击开始执行。")

    def restore_pending(self) -> None:
        app = self.app
        if app.running:
            messagebox.showinfo("提示", "请等当前批次结束后恢复队列。")
            return
        try:
            unfinished = BatchStore.unfinished()
            existing = {browser_id(it) for it in app.raw_browsers}
            app.selected_ids = unfinished & existing
            self.render_table()
            app.log(
                f"恢复待执行账号 {len(app.selected_ids)} 个；已不存在 {len(unfinished - existing)} 个。中断账号从头执行。"
            )
        except Exception as exc:
            messagebox.showerror("队列恢复失败", str(exc))

    # ---------- 行操作 ----------
    def on_double(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row and self.tree.identify_column(event.x) != "#1":
            self.app.pages["flow"].focus_account(row)

    def on_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        if row not in self.tree.selection():
            self.tree.selection_set(row)
        rows = list(self.tree.selection())
        app = self.app

        def copy_ids():
            app.root.clipboard_clear()
            app.root.clipboard_append("\n".join(rows))

        popup_menu(
            self.tree,
            [
                (f"切换勾选（{len(rows)} 行）", lambda: self.toggle_rows(rows)),
                None,
                ("🔁 查看执行流程", lambda: app.pages["flow"].focus_account(row)),
                ("💬 查看收件箱", lambda: app.pages["inbox"].focus_account(row)),
                ("⚡ 立即同步所选行", lambda: app.start_service_run(rows)),
                ("取消所选行的排队", self.cancel_selected) if app.running else (),
                None,
                ("复制环境 ID", copy_ids),
            ],
            event,
        )

    def flow_of_selection(self) -> None:
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("提示", "先点选一个账号行，再查看它的执行流程。")
            return
        self.app.pages["flow"].focus_account(sel[0])

    def sync_checked(self) -> None:
        ids = sorted(self.app.selected_ids)
        if not ids:
            messagebox.showinfo("提示", "先勾选要同步的账号（第一列的方框）。")
            return
        self.app.start_service_run(ids, "数据同步")

    def cancel_selected(self) -> None:
        ids = list(self.tree.selection())
        if not ids:
            messagebox.showinfo("提示", "请先在表格中点击选中要取消排队的账号行。")
            return
        self.app.cancel_queue(ids)

    def on_reading_model(self, _event=None):
        previous=self.app.settings.run['reading_model']
        selected=next((k for k,v in READING_MODEL_LABELS.items() if v==self.reading_model_var.get()),None)
        if selected is None:return
        if self.app.post_schedule is not None:
            self.reading_model_var.set(READING_MODEL_LABELS[previous])
            messagebox.showinfo('定时任务已启用','请先停止定时任务，再更改养号流程。')
            return
        try:
            self.app.settings.run['reading_model']=selected
            self.app.save_config()
        except Exception as exc:
            self.app.settings.run['reading_model']=previous
            self.reading_model_var.set(READING_MODEL_LABELS[previous])
            messagebox.showerror('保存失败',str(exc));return
        self.app.log(f"养号流程已设为 {READING_MODEL_LABELS[selected]}，下一批生效；当前批次沿用原配置。")



# ======================================================================
# 模块：xmanager/ui/dashboard.py
# ======================================================================
"""数据看板：KPI、获赞排行、7 天趋势、账号数据表、最近动态，以及账号明细弹窗。"""


import time
import tkinter as tk
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any, Dict, Tuple


DEMO = AccountDataStore.DEMO_PREFIX


class DashboardPage(Page):
    key, icon, title = "dash", "📊", "数据看板"
    subtitle = "收到的互动与主动操作独立统计；主动操作仅计已确认成功，不含尝试和待核对"
    auto_refresh = True

    COLS = (
        ("name", "账号", 120, "w"),
        ("handle", "@用户名", 104, "w"),
        ("state", "运行状态", 84, "w"),
        ("followers", "粉丝", 58, "e"),
        ("likes", "累计获赞", 72, "e"),
        ("likes_today", "今日+", 50, "e"),
        ("likes_sent_total", "累计成功点赞数", 130, "e"),
        ("comments_sent_total", "累计成功发出评论数", 150, "e"),
        ("replies", "累计评论", 72, "e"),
        ("replies_today", "今日+", 50, "e"),
        ("dm", "私信未读", 70, "e"),
        ("notif", "通知未读", 70, "e"),
        ("posts", "已读帖", 54, "e"),
        ("ts", "最近采集", 76, "e"),
    )
    TEXT_COLS = ("name", "handle", "state")

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self.sort: Tuple[str, bool] = ("likes", True)
        self._sig: Any = None

        bar = self.toolbar()
        self.hint = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.hint, fg=UI["mute"], bg=UI["bg"], font=F(9)).pack(side="left")
        ui_button(bar, "📤 导出 CSV", self.export).pack(side="right")
        ui_button(bar, "⚡ 同步所选账号", self.sync_selected, "primary").pack(side="right", padx=px(8))
        ui_button(bar, "🔄 刷新", lambda: self.refresh(True)).pack(side="right")

        kpis = tk.Frame(page, bg=UI["bg"])
        kpis.grid(row=1, column=0, sticky="ew", padx=px(18))
        self.kpi: Dict[str, Tuple[tk.StringVar, tk.StringVar]] = {}
        specs = (
            ("accounts", "已记录账号", UI["blue"]),
            ("followers", "粉丝合计", UI["text"]),
            ("likes", "累计获赞", UI["pink"]),
            ("replies", "累计收到评论回复", UI["amber"]),
            ("comments_sent_total", "累计成功发出评论数", UI["green"]),
            ("likes_sent_total", "累计成功点赞数", UI["blue"]),
            ("dm", "私信未读", UI["green"]),
            ("pending", "待发回复", UI["blue"]),
        )
        for i, (key, title, color) in enumerate(specs):
            kpis.columnconfigure(i % 4, weight=1, uniform="kpi")
            outer, body = card(kpis)
            outer.grid(row=i // 4, column=i % 4, sticky="nsew", padx=(0 if i % 4 == 0 else px(10), 0), pady=(0, px(6)))
            tk.Label(body, text=title, bg=UI["card"], fg=UI["mute"], font=F(9)).pack(anchor="w")
            value, sub = tk.StringVar(value="—"), tk.StringVar(value=" ")
            tk.Label(body, textvariable=value, bg=UI["card"], fg=color, font=F(22, True)).pack(anchor="w")
            tk.Label(body, textvariable=sub, bg=UI["card"], fg=UI["faint"], font=F(8)).pack(anchor="w")
            self.kpi[key] = (value, sub)

        charts = tk.Frame(page, bg=UI["bg"])
        charts.grid(row=2, column=0, sticky="ew", padx=px(18), pady=px(10))
        charts.columnconfigure(0, weight=1, uniform="ch")
        charts.columnconfigure(1, weight=1, uniform="ch")
        outer, body = card(charts, "各账号累计获赞 TOP 10", "最近读取的帖子合计")
        outer.grid(row=0, column=0, sticky="nsew")
        self.chart_bars = MiniChart(body, 190)
        self.chart_bars.pack(fill="both", expand=True)
        outer, body = card(charts, "近 7 天新增", "全部账号合计")
        outer.grid(row=0, column=1, sticky="nsew", padx=(px(10), 0))
        self.chart_lines = MiniChart(body, 190)
        self.chart_lines.pack(fill="both", expand=True)

        low = tk.Frame(page, bg=UI["bg"])
        low.grid(row=3, column=0, sticky="nsew", padx=px(18), pady=(0, px(14)))
        low.columnconfigure(0, weight=6)
        low.columnconfigure(1, weight=2, minsize=px(240))
        low.rowconfigure(0, weight=1)
        outer, body = card(low, "账号数据", "点列标题排序 · 双击查看帖子明细 · 右键更多操作")
        outer.grid(row=0, column=0, sticky="nsew")
        cols = [c[0] for c in self.COLS]
        frame, self.tree = make_tree(
            body,
            cols,
            [c[1] for c in self.COLS],
            [c[2] for c in self.COLS],
            height=6,
            anchors={c[0]: c[3] for c in self.COLS},
            stretch=("name",),
        )
        frame.pack(fill="both", expand=True)
        for col in cols:
            self.tree.heading(col, command=lambda c=col: self.sort_by(c))
        self.tree.bind("<Double-1>", self.on_double)
        self.tree.bind("<Button-3>", self.on_menu)
        self.empty = tk.Label(
            body,
            bg=UI["card"],
            fg=UI["faint"],
            font=F(10),
            justify="center",
            text="还没有任何账号数据\n\n① 到「账号与任务」勾选账号，点「⚡ 立即同步」\n② 或到「设置 › 数据管理」载入演示数据先预览界面",
        )
        outer, body = card(low, "最近动态")
        outer.grid(row=0, column=1, sticky="nsew", padx=(px(10), 0))
        self.feed = tk.Text(
            body,
            width=30,
            height=6,
            wrap="word",
            state="disabled",
            bg=UI["card"],
            relief="flat",
            font=F(9),
            cursor="arrow",
            highlightthickness=0,
        )
        feed_bar = ttk.Scrollbar(body, orient="vertical", command=self.feed.yview)
        self.feed.configure(yscrollcommand=feed_bar.set)
        feed_bar.pack(side="right", fill="y")
        self.feed.pack(side="left", fill="both", expand=True)
        self.feed.tag_configure("time", foreground=UI["faint"], font=F(8))
        self.feed.tag_configure("name", foreground=UI["text"], font=F(9, True))
        self.feed.tag_configure("collect", foreground=UI["green"])
        self.feed.tag_configure("run", foreground=UI["blue"])
        self.feed.tag_configure("reply", foreground=UI["amber"])

    # ---------- 交互 ----------
    def sort_by(self, col: str) -> None:
        old, desc = self.sort
        self.sort = (col, not desc if old == col else col not in self.TEXT_COLS)
        self.refresh(True)

    def on_double(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if row:
            AccountDetail(self.app, row)

    def on_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        demo = row.startswith(DEMO)
        popup_menu(
            self.tree,
            [
                ("查看帖子明细", lambda: AccountDetail(self.app, row)),
                () if demo else ("⚡ 立即同步此账号", lambda: self.app.start_service_run([row])),
                ("💬 查看收件箱", lambda: self.app.pages["inbox"].focus_account(row)),
                ("🔁 查看执行流程", lambda: self.app.pages["flow"].focus_account(row)),
            ],
            event,
        )

    def sync_selected(self) -> None:
        ids = list(self.tree.selection()) or sorted(self.app.selected_ids)
        if not ids:
            messagebox.showinfo("提示", "先在表格里点选账号，或到「账号与任务」页勾选账号。")
            return
        self.app.start_service_run(ids, "数据同步")

    def export(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="账号数据看板.csv", filetypes=[("CSV 文件", "*.csv")]
        )
        if not path:
            return
        try:
            count = self.app.store.export_csv(Path(path))
            self.app.log(f"已导出看板数据 {count} 个账号：{path}")
            messagebox.showinfo("导出完成", f"已导出 {count} 个账号的数据。")
        except Exception as exc:
            messagebox.showerror("导出失败", str(exc))

    # ---------- 刷新 ----------
    def _value(self, row: Dict[str, Any], col: str, state: str) -> Any:
        if col == "name":
            return str(row["name"]).casefold()
        if col == "handle":
            return str(row["handle"] or "").casefold()
        if col == "state":
            return state
        if col == "followers":
            return row["followers"] if row["followers"] is not None else -1
        if col in ("dm", "notif"):
            return row["dm_unread" if col == "dm" else "notif_unread"] or 0
        return row[col]

    def refresh(self, force: bool = False) -> None:
        app, store = self.app, self.app.store
        rows = store.overview(local_midnight())
        names = app.account_names()
        for row in rows:
            if row.get('outgoing_only'):
                row['name'] = names.get(row['account'], row['name'])
        pending = store.pending_counts()
        labels, likes7, replies7 = store.trend(7)
        events = store.recent_events(30)
        states = {
            r["account"]: (
                "演示数据"
                if r["account"].startswith(DEMO)
                else app.status_map.get(r["account"], ("", ""))[0] or "—"
            )
            for r in rows
        }
        sig = (
            repr(rows),
            repr(sorted(pending.items())),
            likes7,
            replies7,
            tuple(e["id"] for e in events),
            tuple(sorted(states.items())),
            self.sort,
            int(time.time() // 60),
        )
        if not force and self._sig == sig:
            return
        self._sig = sig

        col, desc = self.sort
        rows.sort(key=lambda r: self._value(r, col, states[r["account"]]), reverse=desc)
        keep = list(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        for r in rows:
            acc = r["account"]
            tone = app.status_map.get(acc, ("", ""))[1]
            tag = (
                ("run",)
                if tone == "run"
                else ("bad",)
                if tone == "bad"
                else ("mute",)
                if acc.startswith(DEMO)
                else ("alert",)
                if (r["dm_unread"] or 0) > 0
                else ()
            )
            self.tree.insert(
                "",
                "end",
                iid=acc,
                tags=tag,
                values=(
                    r["name"],
                    ("@" + r["handle"]) if r["handle"] else "—",
                    states[acc],
                    fmt_num(r["followers"]),
                    fmt_num(r["likes"]),
                    f"+{r['likes_today']}" if r["likes_today"] else "·",
                    fmt_num(r["likes_sent_total"]),
                    fmt_num(r["comments_sent_total"]),
                    fmt_num(r["replies"]),
                    f"+{r['replies_today']}" if r["replies_today"] else "·",
                    fmt_num(r["dm_unread"]),
                    fmt_num(r["notif_unread"]),
                    r["posts"],
                    ago(r["ts"]),
                ),
            )
        keep = [i for i in keep if self.tree.exists(i)]
        if keep:
            self.tree.selection_set(keep)
        for key, title, _w, _a in self.COLS:
            arrow = (" ▼" if desc else " ▲") if key == col else ""
            self.tree.heading(key, text=title + arrow)
        if rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.55, anchor="center")
        self._kpis(rows, pending)
        if rows:
            ranked = sorted(rows, key=lambda r: r["likes"], reverse=True)[:10]
            self.chart_bars.bars([(r["name"], r["likes"]) for r in ranked], UI["pink"])
            self.chart_lines.lines(
                labels, [("新增获赞", likes7, UI["pink"]), ("新增评论回复", replies7, UI["amber"])]
            )
        else:
            self.chart_bars.message("同步一次账号数据后，这里显示获赞排行")
            self.chart_lines.message("同步一次账号数据后，这里显示每天新增")
        n = app.settings.dash.get("stats_posts", 20)
        demo = any(r["account"].startswith(DEMO) for r in rows)
        self.hint.set(
            f"获赞/收到评论=已追踪帖子合计；主动评论/点赞=已确认成功，同账号同帖去重"
            + ("　｜　当前包含演示数据（设置 › 数据管理 可清除）" if demo else "")
        )
        self._feed(events)

    def _kpis(self, rows, pending) -> None:
        def total(key):
            return sum((r[key] or 0) for r in rows)

        kpi = self.kpi
        followers = [r["followers"] for r in rows if r["followers"] is not None]
        for key in ('comments_sent_total', 'likes_sent_total'):
            kpi[key][0].set(fmt_num(total(key)))
            kpi[key][1].set('仅计成功；同账号同帖去重')
        kpi["accounts"][0].set(str(len(rows)))
        kpi["accounts"][1].set(f"最近记录 {ago(max(r['ts'] for r in rows))}" if rows else "尚未采集")
        kpi["followers"][0].set(compact_num(sum(followers)) if followers else "—")
        kpi["followers"][1].set(f"今日 {sum(r['followers_today'] for r in rows):+d}" if rows else " ")
        kpi["likes"][0].set(compact_num(total("likes")) if rows else "—")
        kpi["likes"][1].set(f"今日 +{total('likes_today')}" if rows else " ")
        kpi["replies"][0].set(compact_num(total("replies")) if rows else "—")
        kpi["replies"][1].set(f"今日 +{total('replies_today')}" if rows else " ")
        kpi["dm"][0].set(compact_num(total("dm_unread")) if rows else "—")
        kpi["dm"][1].set(f"{sum(1 for r in rows if (r['dm_unread'] or 0) > 0)} 个账号有未读" if rows else " ")
        kpi["pending"][0].set(str(sum(pending.values())))
        kpi["pending"][1].set("在「收件箱」写好回复后排队" if not pending else f"{len(pending)} 个账号待发送")

    def _feed(self, events) -> None:
        feed = self.feed
        feed.configure(state="normal")
        feed.delete("1.0", "end")
        for e in events:
            feed.insert("end", time.strftime("%m-%d %H:%M  ", time.localtime(e["ts"])), "time")
            feed.insert("end", f"{e['name']}\n", "name")
            kind = str(e["kind"])
            feed.insert(
                "end",
                f"{e['summary']}\n\n",
                "reply" if kind.startswith("reply") else kind if kind in ("collect", "run") else (),
            )
        if not events:
            feed.insert("end", "暂无动态。\n同步或运行账号后，这里会按时间列出每次采集和运行结果。")
        feed.configure(state="disabled")





from xmanager_ui import make_recent_page
import sys as _runtime_sys
RecentPerformancePage = make_recent_page(_runtime_sys.modules[__name__])


class AccountDetail:
    """账号明细弹窗：累计走势 + 已读取的帖子。"""

    def __init__(self, app, acc: str):
        rows = {r["account"]: r for r in app.store.overview(local_midnight())}
        r = rows.get(acc)
        if r is None:
            return
        demo = acc.startswith(DEMO)
        win = tk.Toplevel(app.root)
        win.title(f"账号明细 · {r['name']}")
        win.geometry(f"{px(1000)}x{px(680)}")
        win.transient(app.root)
        head = tk.Frame(win, bg=UI["bg"])
        head.pack(fill="x", padx=px(18), pady=(px(16), px(6)))
        tk.Label(head, text=r["name"], font=F(16, True), bg=UI["bg"]).pack(side="left")
        tk.Label(head, text=("@" + r["handle"]) if r["handle"] else "", fg=UI["mute"], bg=UI["bg"]).pack(
            side="left", padx=px(10)
        )
        tk.Label(head, text=f"最近采集 {ago(r['ts'])}", fg=UI["faint"], bg=UI["bg"], font=F(9)).pack(
            side="right"
        )
        stats = (
            f"粉丝 {fmt_num(r['followers'])}　关注 {fmt_num(r['following'])}　累计获赞 {fmt_num(r['likes'])}"
            f"（今日 +{r['likes_today']}）　累计评论 {fmt_num(r['replies'])}（今日 +{r['replies_today']}）　"
            f"转发 {fmt_num(r['reposts'])}　私信未读 {fmt_num(r['dm_unread'])}　通知未读 {fmt_num(r['notif_unread'])}"
        )
        tk.Label(
            win, text=stats, fg=UI["text"], bg=UI["bg"], anchor="w", justify="left", wraplength=px(940)
        ).pack(fill="x", padx=px(18))
        history = app.store.history(acc, 60)
        outer, body = card(win, "累计获赞 / 评论走势", "每次同步一个点")
        outer.pack(fill="x", padx=px(18), pady=px(10))
        chart = MiniChart(body, 170)
        chart.pack(fill="both", expand=True)
        if history:
            chart.lines(
                [time.strftime("%m-%d %H:%M", time.localtime(h["ts"])) for h in history],
                [
                    ("累计获赞", [h["likes"] for h in history], UI["pink"]),
                    ("累计评论", [h["replies"] for h in history], UI["amber"]),
                ],
            )
        else:
            chart.message("还没有历史数据")
        outer, body = card(win, "已读取的帖子", "双击在浏览器打开（演示数据除外）")
        outer.pack(fill="both", expand=True, padx=px(18), pady=(0, px(8)))
        frame, table = make_tree(
            body,
            ("text", "likes", "replies", "reposts", "views"),
            ("帖子内容", "获赞", "评论", "转发", "浏览"),
            (520, 80, 80, 80, 90),
            height=8,
            anchors={"likes": "e", "replies": "e", "reposts": "e", "views": "e"},
            stretch=("text",),
        )
        frame.pack(fill="both", expand=True)
        posts = app.store.posts_for(acc, 100)
        for p in posts:
            table.insert(
                "",
                "end",
                iid=p["status_id"],
                values=(
                    (p["text"] or "（无文字）").replace("\n", " ")[:120],
                    fmt_num(p["likes"]),
                    fmt_num(p["replies"]),
                    fmt_num(p["reposts"]),
                    fmt_num(p["views"]),
                ),
            )
        if not posts:
            tk.Label(
                body, text="还没有读取到帖子（账号可能还没发过帖，或还没同步）", fg=UI["faint"], bg=UI["card"]
            ).pack()

        def open_post(event):
            row = table.identify_row(event.y)
            if row and not demo:
                webbrowser.open(f"https://x.com/i/status/{row}")

        table.bind("<Double-1>", open_post)
        foot = tk.Frame(win, bg=UI["bg"])
        foot.pack(fill="x", padx=px(18), pady=(0, px(14)))
        if not demo:
            ui_button(
                foot, "⚡ 立即同步此账号", lambda: (win.destroy(), app.start_service_run([acc])), "primary"
            ).pack(side="left")
        ui_button(
            foot, "💬 查看该账号收件箱", lambda: (win.destroy(), app.pages["inbox"].focus_account(acc))
        ).pack(side="left", padx=px(8))
        ui_button(
            foot, "🔁 查看执行流程", lambda: (win.destroy(), app.pages["flow"].focus_account(acc))
        ).pack(side="left")
        ui_button(foot, "关闭", win.destroy).pack(side="right")


# ======================================================================
# 模块：xmanager/ui/flow.py
# ======================================================================
"""执行流程：阶段箭头条、当前动作、工作流明细（含基础次数 / 偏移 / 目标）与阶段轨迹。

V9 的「工作流明细」弹窗已合并到本页的表格里。
"""


import time
import tkinter as tk
from tkinter import ttk
from typing import Any, Dict, Optional


STAGES = (
    ("launch", "启动浏览器"),
    ("login", "登录检查"),
    ("outbox", "发送面板回复"),
    ("collect_start", "开局采集"),
    ("workflows", "阅读 / 互动工作流"),
    ("collect_end", "收尾采集"),
    ("close", "收尾关窗"),
)
STAGE_LABEL = dict(STAGES)
WF_STATE = {
    "RUNNING": ("▶ 进行中", "run"),
    "PENDING": ("· 待执行", "info"),
    "DONE": ("✔ 已完成", "ok"),
    "DEFERRED": ("⏳ 暂缓", "warn"),
    "UNAVAILABLE": ("○ 无内容", "warn"),
    "SATISFIED": ("✔ 已满足", "ok"),
    "NO_TRIGGER": ("○ 未触发", "warn"),
    "DISABLED": ("— 未启用", "mute"),
}
STATE_RANK = {"DEFERRED": 2, "PENDING": 3, "SATISFIED": 4, "NO_TRIGGER": 5, "UNAVAILABLE": 5, "DISABLED": 6}


class FlowPage(Page):
    key, icon, title = "flow", "🔁", "执行流程"
    subtitle = "实时查看每个账号处在哪个阶段、哪个工作流、做到第几次"
    auto_refresh = True

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(3, weight=1)
        self.account_map: Dict[str, str] = {}
        self.current_bid = ""
        self._sig: Any = None

        top = self.toolbar()
        tk.Label(top, text="查看账号", fg=UI["mute"], bg=UI["bg"]).pack(side="left")
        self.combo = ttk.Combobox(top, state="readonly", width=44)
        self.combo.pack(side="left", padx=px(8))
        self.combo.bind("<<ComboboxSelected>>", lambda _e: self.on_pick())
        self.follow = tk.BooleanVar(value=True)
        check(top, "自动跟随正在运行的账号", self.follow, command=lambda: self.refresh(True)).pack(
            side="left", padx=px(8)
        )
        ui_button(top, "🔄 刷新", lambda: self.refresh(True)).pack(side="left")
        self.info = tk.StringVar(value="")
        tk.Label(top, textvariable=self.info, fg=UI["faint"], bg=UI["bg"], font=F(9)).pack(side="right")

        self.strip = StageStrip(page, 84)
        self.strip.grid(row=1, column=0, sticky="ew", padx=px(18))

        outer, body = card(page)
        outer.grid(row=2, column=0, sticky="ew", padx=px(18), pady=px(10))
        self.now = tk.StringVar(value="")
        self.summary = tk.StringVar(value="")
        tk.Label(
            body,
            textvariable=self.now,
            bg=UI["card"],
            fg=UI["text"],
            font=F(12, True),
            anchor="w",
            justify="left",
            wraplength=px(1000),
        ).pack(fill="x")
        tk.Label(body, textvariable=self.summary, bg=UI["card"], fg=UI["mute"], font=F(9), anchor="w").pack(
            fill="x", pady=(px(4), px(6))
        )
        self.bar = ttk.Progressbar(body, mode="determinate")
        self.bar.pack(fill="x")

        low = tk.Frame(page, bg=UI["bg"])
        low.grid(row=3, column=0, sticky="nsew", padx=px(18), pady=(0, px(14)))
        low.columnconfigure(0, weight=5)
        low.columnconfigure(1, weight=2)
        low.rowconfigure(0, weight=1)
        outer, body = card(low, "工作流明细", "本次会话每个工作流的基础次数、随机偏移、目标与结果")
        outer.grid(row=0, column=0, sticky="nsew")
        self.only_active = tk.BooleanVar(value=True)
        check(
            body, "只显示已启用的工作流", self.only_active, "mute", command=lambda: self.refresh(True)
        ).pack(anchor="w")
        cols = ("label", "state", "progress", "base", "offset", "done", "skip", "fail", "intr", "reason")
        frame, self.tree = make_tree(
            body,
            cols,
            ("工作流", "状态", "进度", "基础", "偏移", "完成", "跳过", "失败", "中断", "说明 / 当前动作"),
            (200, 84, 60, 44, 54, 44, 44, 44, 44, 300),
            height=8,
            stretch=("reason",),
            anchors={c: "center" for c in cols[2:-1]},
        )
        frame.pack(fill="both", expand=True, pady=(px(6), 0))
        outer, body = card(low, "阶段轨迹", "本次会话经过的阶段与最近动态")
        outer.grid(row=0, column=1, sticky="nsew", padx=(px(10), 0))
        self.trace = tk.Text(
            body,
            width=30,
            height=8,
            wrap="word",
            state="disabled",
            bg=UI["card"],
            relief="flat",
            highlightthickness=0,
            font=F(9),
            cursor="arrow",
        )
        bar = ttk.Scrollbar(body, orient="vertical", command=self.trace.yview)
        self.trace.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.trace.pack(side="left", fill="both", expand=True)
        self.trace.tag_configure("time", foreground=UI["faint"], font=F(8))
        self.trace.tag_configure("now", foreground=UI["blue"], font=F(9, True))
        self.trace.tag_configure("done", foreground=UI["green"])
        self.trace.tag_configure("mute", foreground=UI["mute"])

    def on_pick(self) -> None:
        self.follow.set(False)
        self.current_bid = self.account_map.get(self.combo.get(), "")
        self.refresh(True)

    def focus_account(self, bid: str) -> None:
        self.follow.set(False)
        self.current_bid = bid
        self.app.show_page("flow")

    def _accounts(self, active) -> None:
        names = self.app.account_names()
        if self.current_bid and self.current_bid not in names:
            names[self.current_bid] = self.current_bid
        running = set(active)
        ordered = sorted(names.items(), key=lambda kv: (kv[0] not in running, kv[1]))
        self.account_map = {f"{'▶ ' if bid in running else ''}{name} · {bid}": bid for bid, name in ordered}
        self.combo.configure(values=list(self.account_map))

    def refresh(self, force: bool = False) -> None:
        active = list(self.app.ctl.active_ids())
        self._accounts(active)
        bid = self.current_bid
        if self.follow.get() and active and bid not in active:
            bid = active[0]
        if not bid and self.account_map:
            bid = next(iter(self.account_map.values()))
        self.current_bid = bid
        label = next((k for k, v in self.account_map.items() if v == bid), "")
        if label and self.combo.get() != label:
            self.combo.set(label)
        report = latest_report(bid) if bid else None
        running = bid in active
        sig = (
            bid,
            running,
            report.get("updated_at") if report else None,
            self.only_active.get(),
            len(active),
        )
        if not force and self._sig == sig:
            return
        self._sig = sig
        self._strip(report, running)
        self.tree.delete(*self.tree.get_children())
        if not report:
            self.now.set(
                "这个账号还没有运行记录"
                if bid
                else "还没有可查看的账号（先到「账号与任务」点“刷新比特环境”）"
            )
            self.summary.set("开始任务后，这里会实时显示：启动 → 登录 → 采集 → 各个工作流 → 收尾。")
            self.bar.configure(value=0, maximum=1)
            self.info.set("")
            self._trace(None, [])
            return
        self._details(report, running)
        events = [e for e in self.app.store.recent_events(120) if e["account"] == bid][:8]
        self._trace(report, events)

    def _strip(self, report: Optional[Dict[str, Any]], running: bool) -> None:
        mode = (report or {}).get("mode", "read")
        stages = [s for s in STAGES if not (mode == "service" and s[0] in ("workflows", "collect_end"))]
        visited = {e.get("stage"): e.get("ts") for e in (report or {}).get("stage_log") or []}
        current = (report or {}).get("stage", "")
        if current in READING_PHASE_LABELS:current="workflows"
        order = [k for k, _ in STAGES]
        cur_idx = order.index(current) if current in order else -1
        strip = []
        for key, text in stages:
            if key == "close" and current == "close" and not running:
                state = "done"
            elif key == current and (running or key != "close"):
                state = "current"
            elif key in visited:
                state = "done"
            elif cur_idx >= 0 and order.index(key) < cur_idx:
                state = "skipped"
            else:
                state = "todo"
            ts = visited.get(key)
            strip.append((text, state, time.strftime("%H:%M:%S", time.localtime(ts)) if ts else ""))
        self.strip.show(strip)

    def _details(self, report: Dict[str, Any], running: bool) -> None:
        plan = report.get("plan") or {}
        items = plan.get("workflows") or {}
        summary = plan.get("summary") or {}
        current = report.get("stage", "")
        run_item = next((v for v in items.values() if v.get("state") == "RUNNING"), None)
        stage_label = READING_PHASE_LABELS.get(current,STAGE_LABEL.get(current, ""))
        age = time.time() - float(report.get("updated_at") or 0)
        if run_item:
            self.now.set(
                f"正在执行：【{run_item.get('tier_label', '原版')}】{run_item['label']} —— {run_item.get('phase', '')}"
            )
        elif running:
            self.now.set(f"当前阶段：{stage_label or '准备中'}")
        else:
            self.now.set(
                f"这是上一次运行的记录（{ago(report.get('updated_at'))}），最后阶段：{stage_label or '—'}"
            )
        target = int(summary.get("target", 0))
        attempts = int(summary.get("attempts", 0))
        session = str(plan.get("session_id", ""))[:12]
        self.summary.set(
            f"会话 {session or '—'}　｜　有效运行 {float(report.get('active_sec', 0)) / 60:.1f} 分钟　｜　计划 {target}"
            f"　已尝试 {attempts}　完成 {summary.get('completed', 0)}　跳过 {summary.get('skipped', 0)}"
            f"　暂缓 {summary.get('deferred', 0)}　失败 {summary.get('failed', 0)}　中断 {summary.get('interrupted', 0)}"
        )
        self.bar.configure(maximum=max(1, target), value=min(attempts, max(1, target)))
        self.info.set(
            f"记录更新于 {ago(report.get('updated_at'))}" + ("（运行中）" if running and age < 30 else "")
        )

        def rank(item):  # 进行中 → 已经做过的 → 暂缓 → 待执行 → 其他
            if item.get("state") == "RUNNING":
                return 0
            if item.get("attempts", 0) > 0:
                return 1
            return STATE_RANK.get(item.get("state"), 9)

        reading=report.get('reading')
        if reading is not None:
            post=reading.get('current') or {};scores=post.get('scores') or {}
            if running:
                self.now.set(f"V11.1 · {stage_label or '准备'}｜帖子 {post.get('id','—')}｜综合 {scores.get('overall','未知')} / 讨论 {scores.get('discussion','未知')}")
            cadence=reading.get('cadence') or {};stats=reading.get('statistics') or {}
            self.summary.set(f"主线 {cadence.get('primary_seconds',0)/60:.1f} 分钟｜支线 {cadence.get('secondary_seconds',0)/60:.1f} 分钟｜阅读 {stats.get('reads',0)} 条｜图片 {stats.get('images_viewed',0)}｜评论/子评论 {stats.get('comments_read',0)}/{stats.get('subcomments_read',0)}｜支线配额仅作上限")
            budget=reading.get('budget_sec');finite=budget if isinstance(budget,(int,float)) and math.isfinite(budget) and budget>0 else 1
            self.bar.configure(maximum=finite,value=min(reading.get('effective_sec',0),finite) if budget==finite else 0)
            self.info.set(f"跨页 {stats.get('page_navigations',0)}｜刷新 {stats.get('feed_refreshes',0)}｜更新 {ago(report.get('updated_at'))}")
        for key, it in sorted(items.items(), key=lambda kv: rank(kv[1])):
            if self.only_active.get() and it.get("state") == "DISABLED":
                continue
            text, tone = WF_STATE.get(it.get("state"), (str(it.get("state")), "info"))
            reason = (
                it.get("phase")
                if it.get("state") == "RUNNING"
                else (it.get("disabled_reason") or it.get("last_reason") or "")
            )
            self.tree.insert(
                "",
                "end",
                iid=key,
                tags=(tone,),
                values=(
                    f"[{it.get('tier_label', '原版')}] {it['label']}",
                    text,
                    f"{it['attempts']}/{it['target']}",
                    it.get("base", ""),
                    f"{it.get('offset_pct', 0):+d}%",
                    it["completed"],
                    it["skipped"],
                    it["failed"],
                    it.get("interrupted", 0),
                    reason,
                ),
            )


    def _trace(self, report, events) -> None:
        text = self.trace
        text.configure(state="normal")
        text.delete("1.0", "end")
        if report:
            for e in report.get("stage_log") or []:
                tag = "now" if e.get("stage") == report.get("stage") else "done"
                text.insert("end", time.strftime("%H:%M:%S  ", time.localtime(e.get("ts", 0))), "time")
                text.insert("end", f"{STAGE_LABEL.get(e.get('stage'), e.get('stage'))}\n", tag)
        if events:
            text.insert("end", "\n最近动态\n", "mute")
            for e in events:
                text.insert("end", time.strftime("%m-%d %H:%M  ", time.localtime(e["ts"])), "time")
                text.insert("end", f"{e['summary']}\n", "mute")
        if not report and not events:
            text.insert("end", "暂无记录", "mute")
        text.see("end")
        text.configure(state="disabled")


# ======================================================================
# 模块：xmanager/ui/inbox.py
# ======================================================================
"""收件箱：评论 / 提及 / 私信列表，手写回复入队，以及待发 / 已发队列的核对。"""


import time
import tkinter as tk
import webbrowser
from tkinter import messagebox, ttk
from typing import Any, Dict, Optional


DEMO = AccountDataStore.DEMO_PREFIX
IB_STATE = {"new": "待处理", "handled": "已处理", "ignored": "已忽略"}
OUT_STATE = {
    "pending": ("待发", "info"),
    "sending": ("发送中", "run"),
    "sent": ("✔ 已发出", "ok"),
    "unknown": ("⚠ 待核对", "warn"),
    "failed": ("✖ 失败", "bad"),
    "cancelled": ("已取消", "mute"),
}
IB_KIND = {"mention": "评论/提及", "dm": "私信"}


class InboxPage(Page):
    key, icon, title = "inbox", "💬", "收件箱"
    subtitle = "选中一条消息 → 手写回复 → 加入待发队列，由对应账号的浏览器点一次发送"
    auto_refresh = True

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=3)
        page.columnconfigure(1, weight=2, minsize=px(440))
        page.rowconfigure(1, weight=1)
        self.account_map: Dict[str, str] = {}
        self.rows: Dict[str, Dict[str, Any]] = {}
        self._sig: Any = None

        bar = self.toolbar(columnspan=2)
        self.account = ttk.Combobox(bar, state="readonly", width=26)
        self.account.pack(side="left")
        self.kind = ttk.Combobox(bar, state="readonly", width=10, values=("全部类型", "评论/提及", "私信"))
        self.kind.set("全部类型")
        self.kind.pack(side="left", padx=px(6))
        self.state = ttk.Combobox(
            bar, state="readonly", width=8, values=("待处理", "已处理", "已忽略", "全部")
        )
        self.state.set("待处理")
        self.state.pack(side="left")
        for box in (self.account, self.kind, self.state):
            box.bind("<<ComboboxSelected>>", lambda _e: self.refresh(True))
        self.query = tk.StringVar()
        tk.Label(bar, text="搜索", fg=UI["mute"], bg=UI["bg"]).pack(side="left", padx=(px(10), px(4)))
        tk.Entry(bar, textvariable=self.query, width=18).pack(side="left", ipady=px(3))
        self.query.trace_add("write", lambda *_: self.refresh(True))
        ui_button(bar, "🔄 刷新", lambda: self.refresh(True)).pack(side="left", padx=px(6))
        ui_button(bar, "全部标为已处理", self.mark_all).pack(side="left")
        ui_button(bar, "⚡ 立即发送待发回复", self.send_pending_now, "primary").pack(side="right")

        outer, body = card(page, "消息", "来自各账号的评论 / 提及 / 私信（只读采集）· 右键更多")
        outer.grid(row=1, column=0, sticky="nsew", padx=(px(18), px(10)), pady=(0, px(14)))
        frame, self.tree = make_tree(
            body,
            ("st", "acct", "kind", "author", "text", "time"),
            ("状态", "账号", "类型", "来自", "内容", "时间"),
            (70, 120, 70, 110, 330, 80),
            height=14,
            selectmode="browse",
            stretch=("text",),
        )
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select())
        self.tree.bind("<Double-1>", lambda _e: self.open_selected())
        self.tree.bind("<Button-3>", self.on_menu)

        right = tk.Frame(page, bg=UI["bg"])
        right.grid(row=1, column=1, sticky="nsew", padx=(0, px(18)), pady=(0, px(14)))
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)
        self._build_reply(right)
        self._build_outbox(right)

    def _build_reply(self, right) -> None:
        outer, body = card(right, "详情与回复")
        outer.grid(row=0, column=0, sticky="ew")
        self.head = tk.StringVar(value="在左侧点选一条消息")
        tk.Label(
            body, textvariable=self.head, bg=UI["card"], fg=UI["text"], font=F(10, True), anchor="w"
        ).pack(fill="x")
        self.msg = tk.Text(body, width=40, height=3, wrap="word", state="disabled", font=F(10))
        self.msg.pack(fill="x", pady=(px(6), px(8)))
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        tk.Label(row, text="我的回复（手写，一次一条）", bg=UI["card"], fg=UI["mute"], font=F(9)).pack(
            side="left"
        )
        self.count = tk.StringVar(value="0 / 280")
        self.count_label = tk.Label(row, textvariable=self.count, bg=UI["card"], fg=UI["faint"], font=F(9))
        self.count_label.pack(side="right")
        self.reply = tk.Text(body, width=40, height=3, wrap="word", font=F(10))
        self.reply.pack(fill="x", pady=(px(4), px(6)))
        self.reply.bind("<KeyRelease>", lambda _e: self.update_count())
        self.reply.bind("<Control-Return>", lambda _e: (self.queue_reply(), "break")[1])
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        tk.Label(row, text="快捷语", bg=UI["card"], fg=UI["mute"], font=F(9)).pack(side="left")
        self.quick = ttk.Combobox(row, state="readonly", width=26, values=self.app.settings.quick_replies)
        self.quick.pack(side="left", padx=px(6))
        self.quick.bind("<<ComboboxSelected>>", self.use_quick)
        ui_button(row, "编辑快捷语", self.edit_quick).pack(side="left")
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=(px(8), 0))
        ui_button(row, "➕ 加入待发队列", self.queue_reply, "good").pack(side="left")
        ui_button(row, "标为已处理", lambda: self.mark("handled")).pack(side="left", padx=px(6))
        ui_button(row, "忽略", lambda: self.mark("ignored")).pack(side="left")
        ui_button(row, "🔗 打开", self.open_selected).pack(side="right")
        self.flash = tk.StringVar(value="")
        tk.Label(
            body,
            textvariable=self.flash,
            bg=UI["card"],
            fg=UI["amber"],
            font=F(9),
            anchor="w",
            justify="left",
            wraplength=px(400),
        ).pack(fill="x", pady=(px(6), 0))
        tk.Label(
            body, text="Ctrl+Enter 快速加入队列", bg=UI["card"], fg=UI["faint"], font=F(8), anchor="w"
        ).pack(fill="x")

    def _build_outbox(self, right) -> None:
        outer, body = card(right, "待发 / 已发队列", "每条回复由对应账号的浏览器点一次发送")
        outer.grid(row=1, column=0, sticky="nsew", pady=(px(10), 0))
        tk.Label(
            body,
            text="“待核对”：点了发送但没等到服务端确认。程序不会自动重发，请到账号里确认后再选下面的按钮。",
            bg=UI["card"],
            fg=UI["faint"],
            font=F(8),
            wraplength=px(400),
            justify="left",
            anchor="w",
        ).pack(side="bottom", fill="x", pady=(px(6), 0))
        row = tk.Frame(body, bg=UI["card"])
        row.pack(side="bottom", fill="x", pady=(px(8), 0))
        ui_button(row, "取消排队", self.outbox_cancel).pack(side="left")
        ui_button(row, "失败重试", self.outbox_retry).pack(side="left", padx=px(6))
        ui_button(row, "核对：已发出", lambda: self.outbox_resolve(True)).pack(side="left")
        ui_button(row, "核对：没发出，重新入队", lambda: self.outbox_resolve(False)).pack(
            side="left", padx=px(6)
        )
        frame, self.out_tree = make_tree(
            body,
            ("state", "acct", "to", "text"),
            ("状态", "账号", "对象", "回复内容"),
            (80, 100, 90, 200),
            height=3,
            selectmode="browse",
            stretch=("text",),
        )
        frame.pack(side="top", fill="both", expand=True)

    # ---------- 刷新 ----------
    def focus_account(self, acc: str) -> None:
        self.app.show_page("inbox")
        label = next((k for k, v in self.account_map.items() if v == acc), None)
        if label:
            self.account.set(label)
        self.refresh(True)

    def refresh(self, force: bool = False) -> None:
        store, names = self.app.store, self.app.account_names()
        self.account_map = {"全部账号": ""}
        self.account_map.update({f"{n} · {b}": b for b, n in sorted(names.items(), key=lambda kv: kv[1])})
        self.account.configure(values=list(self.account_map))
        if self.account.get() not in self.account_map:
            self.account.set("全部账号")
        account = self.account_map.get(self.account.get(), "")
        kind = {"评论/提及": "mention", "私信": "dm"}.get(self.kind.get())
        state = {"待处理": "new", "已处理": "handled", "已忽略": "ignored"}.get(self.state.get())
        rows = store.list_inbox(account or None, kind, state, self.query.get().strip(), 400)
        outbox = store.list_outbox(account or None, None, 80)
        sig = (repr(rows), repr(outbox), int(time.time() // 60))
        if not force and self._sig == sig:
            return
        self._sig = sig
        keep = self.tree.selection()
        self.tree.delete(*self.tree.get_children())
        self.rows = {}
        for r in rows:
            iid = str(r["id"])
            self.rows[iid] = r
            st = IB_STATE.get(r["state"], r["state"])
            if r.get("out_state") in ("pending", "sending"):
                st, tag = "待发", "run"
            elif r.get("out_state") == "unknown":
                st, tag = "⚠ 待核对", "warn"
            elif r["state"] == "new":
                tag = "alert"
            else:
                tag = "mute"
            self.tree.insert(
                "",
                "end",
                iid=iid,
                tags=(tag,),
                values=(
                    st,
                    names.get(r["account"], r["account"]),
                    IB_KIND.get(r["kind"], r["kind"]),
                    r["author"],
                    (r["text"] or "").replace("\n", " ")[:90],
                    ago(r["last_seen"]),
                ),
            )
        keep = [k for k in keep if self.tree.exists(k)]
        if keep:
            self.tree.selection_set(keep)
        self.out_tree.delete(*self.out_tree.get_children())
        for o in outbox:
            text, tone = OUT_STATE.get(o["state"], (o["state"], "info"))
            self.out_tree.insert(
                "",
                "end",
                iid=str(o["id"]),
                tags=(tone,),
                values=(
                    text,
                    names.get(o["account"], o["account"]),
                    o["author"] or ("私信" if o["kind"] == "dm" else ""),
                    (o["text"] or "").replace("\n", " ")[:60] + (f"  〔{o['error']}〕" if o["error"] else ""),
                ),
            )

    def _changed(self) -> None:
        self.refresh(True)
        self.app.refresh_badges()

    # ---------- 选择与回复 ----------
    def selected(self) -> Optional[Dict[str, Any]]:
        sel = self.tree.selection()
        return self.rows.get(sel[0]) if sel else None

    def on_select(self) -> None:
        item = self.selected()
        self.msg.configure(state="normal")
        self.msg.delete("1.0", "end")
        if item is None:
            self.head.set("在左侧点选一条消息")
        else:
            names = self.app.account_names()
            self.head.set(
                f"{item['author'] or '对方'} · {IB_KIND.get(item['kind'], item['kind'])}"
                f" · 发给 {names.get(item['account'], item['account'])}"
            )
            self.msg.insert("1.0", item["text"] or "（没有读到文字）")
        self.msg.configure(state="disabled")
        self.flash.set("")
        self.update_count()

    def on_menu(self, event) -> None:
        row = self.tree.identify_row(event.y)
        if not row:
            return
        self.tree.selection_set(row)
        popup_menu(
            self.tree,
            [
                ("🔗 在浏览器打开", self.open_selected),
                ("标为已处理", lambda: self.mark("handled")),
                ("忽略", lambda: self.mark("ignored")),
                None,
                ("复制内容", lambda: self._copy((self.selected() or {}).get("text") or "")),
            ],
            event,
        )

    def _copy(self, text: str) -> None:
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(text)

    def update_count(self) -> None:
        text = normalize_comment_text(self.reply.get("1.0", "end"))
        item = self.selected()
        if item is not None and item["kind"] == "dm":
            used, limit = len(text), 1000
        else:
            used, limit = x_weighted_length(text), 280
        self.count.set(f"{used} / {limit}" + ("（中文每字算 2）" if limit == 280 else ""))
        self.count_label.configure(fg=UI["red"] if used > limit else UI["faint"])

    def use_quick(self, _event=None) -> None:
        text = self.quick.get()
        if text:
            self.reply.delete("1.0", "end")
            self.reply.insert("1.0", text)
            self.update_count()

    def edit_quick(self) -> None:
        app = self.app
        win = tk.Toplevel(app.root)
        win.title("编辑快捷语")
        win.geometry(f"{px(520)}x{px(380)}")
        win.transient(app.root)
        tk.Label(
            win,
            text="每行一条快捷语（最多 30 条）。选中后会填进回复框，你仍然可以继续修改再发送。",
            fg=UI["mute"],
            wraplength=px(480),
            justify="left",
        ).pack(anchor="w", padx=px(14), pady=(px(14), px(6)))
        box = tk.Text(win, height=12, wrap="word", font=F(10))
        box.pack(fill="both", expand=True, padx=px(14))
        box.insert("1.0", "\n".join(app.settings.quick_replies))

        def save():
            lines = [ln.strip() for ln in box.get("1.0", "end").splitlines() if ln.strip()][:30]
            too_long = [ln for ln in lines if x_weighted_length(ln) > 280]
            if too_long:
                messagebox.showwarning(
                    "太长了", f"有 {len(too_long)} 条超过 280 计数上限，请缩短。", parent=win
                )
                return
            app.settings.quick_replies = lines
            self.quick.configure(values=lines)
            app.try_save("快捷语")
            win.destroy()

        row = tk.Frame(win)
        row.pack(fill="x", padx=px(14), pady=px(12))
        ui_button(row, "保存", save, "primary").pack(side="right")
        ui_button(row, "取消", win.destroy).pack(side="right", padx=px(8))

    def queue_reply(self) -> None:
        item = self.selected()
        if item is None:
            messagebox.showinfo("提示", "先在左侧点选一条消息。")
            return
        if item["account"].startswith(DEMO):
            messagebox.showinfo("演示数据", "这是演示数据，不能真的发送。同步真实账号后再试。")
            return
        text = self.reply.get("1.0", "end").strip()
        try:
            self.app.store.queue_reply(item["id"], text)
        except ValueError as exc:
            messagebox.showwarning("无法加入队列", str(exc))
            return
        self.reply.delete("1.0", "end")
        self.update_count()
        self.flash.set(
            "已加入待发队列。"
            + (
                "该账号正在运行时，会在下一个间隙自动发出。"
                if self.app.running
                else "点右上角「⚡ 立即发送待发回复」开始发送。"
            )
        )
        self._changed()

    def mark(self, state: str) -> None:
        item = self.selected()
        if item is None:
            return
        self.app.store.set_inbox_state([item["id"]], state)
        self._changed()

    def mark_all(self) -> None:
        account = self.account_map.get(self.account.get(), "")
        ids = [
            r["id"]
            for r in self.app.store.list_inbox(account or None, None, "new", "", 2000)
            if r.get("out_state") not in ("pending", "sending", "unknown")
        ]
        if not ids:
            return
        if messagebox.askyesno("确认", f"把当前筛选下的 {len(ids)} 条待处理消息全部标为已处理？"):
            self.app.store.set_inbox_state(ids, "handled")
            self._changed()

    def open_selected(self) -> None:
        item = self.selected()
        if item is None or item["account"].startswith(DEMO):
            return
        webbrowser.open(item["url"] if item["kind"] != "dm" and item["url"] else "https://x.com/messages")

    # ---------- 发送队列 ----------
    def selected_outbox(self) -> Optional[int]:
        sel = self.out_tree.selection()
        return int(sel[0]) if sel else None

    def outbox_cancel(self) -> None:
        oid = self.selected_outbox()
        if oid is None or not self.app.store.cancel_outbox(oid):
            messagebox.showinfo("提示", "只有“待发”状态的回复可以取消。")
        self._changed()

    def outbox_retry(self) -> None:
        oid = self.selected_outbox()
        if oid is None or not self.app.store.retry_outbox(oid):
            messagebox.showinfo("提示", "只有“失败”状态的回复可以重试。")
        self._changed()

    def outbox_resolve(self, sent: bool) -> None:
        oid = self.selected_outbox()
        row = next((o for o in self.app.store.list_outbox(None, ["unknown"], 200) if o["id"] == oid), None)
        if row is None:
            messagebox.showinfo("提示", "先选一条“⚠ 待核对”的回复。")
            return
        if not sent and not messagebox.askyesno(
            "确认重新入队", "确定对方没有收到这条回复吗？\n重新入队后会再发一次，如果其实已经发出就会重复。"
        ):
            return
        self.app.store.resolve_outbox(oid, sent)
        self._changed()

    def send_pending_now(self) -> None:
        ids = [a for a in self.app.store.pending_counts() if not a.startswith(DEMO)]
        if not ids:
            messagebox.showinfo("提示", "没有待发送的回复。先点选一条消息，写好回复，再点“加入待发队列”。")
            return
        if self.app.running:
            messagebox.showinfo(
                "提示",
                "现在已有任务在运行：运行中的账号会在场景间隙自动发出自己的待发回复（约 20 秒内），不用再点。",
            )
            return
        self.app.start_service_run(ids, "发送面板回复")


# ======================================================================
# 模块：xmanager/ui/settings_page.py
# ======================================================================
"""设置：把 V9 分散的「点赞设置 / TXT 自动评论 / TXT 自动发推 / 数据采集 / 数据管理」弹窗整合为分页。

运行模式（阅读 / 阅读+评论 / 发推）统一在「账号与任务」页切换；这里只配置各模式的参数。
"""


import os
import subprocess
import sys
import threading
import tkinter as tk
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Callable, Dict


SCHEDULE_LABELS = {"immediate": "点开始立即执行", "once": "指定日期时间", "daily": "每天固定时间"}
ORDER_LABELS = {"sequential": "顺序", "random": "随机"}
SCOPE_LABELS = {"shared": "所有账号共用队列", "per_account": "每个账号各发一遍"}

COMMENT_NOTES = (
    "· 阅读正文完成后立即检查评论条件；复用当前标签页评论，完成后返回来源和阅读位置。\n"
    "· 兼容详情页内嵌回复框及弹窗，发送前等待输入状态同步；每次实际提交只点击一次。\n"
    "· 全局去重：相同评论文本只分配给一个账号，同一推文只允许一个账号处理；TXT 重复行也会去重，进度跨重启保留。\n"
    "· 提交结果不明会全局保留该推文及文本的占用，其他账号也不会重复提交；在「记录核对」处理。\n"
    "· 服务端明确拒绝时暂停评论，阅读继续。"
)
POST_NOTES = (
    "· 发推模式只执行发推，不执行阅读工作流；按「账号与任务」页的单号时长执行，0 不按时长停止，数量完成即结束。\n"
    "· 定时按本机时间到点启动所选账号，实际发出受排队及浏览器加载影响；程序需保持运行且电脑唤醒。\n"
    "· 每天模式继续读取未发文本，不重复已成功条目；任务不重叠。等待中修改设置不影响已启用计划，需先停止再开始。\n"
    "· 已确认成功的条目跨重启跳过；点击后结果不明则停止该账号，在「记录核对」核对后再继续。\n"
    "· 共用队列每行只分配给一个账号；各发一遍模式按账号分别记录。编辑 TXT 或切换分配方式前请先核对进度。"
)
GUIDE = (
    "1. 「账号与任务」：点“刷新比特环境”→ 勾选账号 → 在右侧选择运行模式与参数 → 点右上角开始。\n"
    "　　右键账号行可查看流程 / 收件箱、立即同步、取消排队；空格键切换所选行的勾选。\n"
    "2. 「数据看板」：每个账号的粉丝、累计获赞、累计评论、私信 / 通知红点；双击账号看每条帖子的数据。\n"
    "3. 「执行流程」：实时显示当前阶段、正在执行的工作流、每个工作流的基础次数 / 随机偏移 / 目标与结果。\n"
    "4. 「收件箱」：选中一条评论 / 私信，自己写回复 → 加入待发队列 → 该账号运行时（或点“立即发送”）由对应浏览器发出。\n"
    "　　每条只点一次发送，结果不明的标“待核对”，不会自动重发。\n"
    "5. 「工作流目录」：调整 105 项工作流的启用、档位和次数；选择兴趣 / 搜索关键词 TXT。\n"
    "6. 「记录核对」：TXT 发推与自动评论里结果不明的条目，人工核实后标记。\n"
    "7. 快捷键：Ctrl+1～8 切换页面，F5 刷新当前页。\n"
    "8. 说明：采集网页元素依赖 X 当前的页面结构，读不到的数据会在日志里写明“未完成”的步骤；改版后需要更新选择器。\n"
    "　　鼠标轨迹只改善交互，不保证账号权重或规避平台检测。"
)


class SettingsPage(Page):
    key, icon, title = "settings", "⚙", "设置"
    subtitle = "各运行模式的参数、数据采集、数据管理；每页单独保存，下一批生效"

    TABS = (
        ("behavior", "点赞与行为"),
        ("reading", "阅读评分与节奏"),
        ("comment", "自动评论"),
        ("post", "自动发推"),
        ("collect", "数据采集与回复"),
        ("data", "数据管理"),
        ("help", "使用说明"),
    )

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(0, weight=1)
        self.book = ttk.Notebook(page)
        self.book.grid(row=0, column=0, sticky="nsew", padx=px(18), pady=px(14))
        self.tabs: Dict[str, tk.Frame] = {}
        builders: Dict[str, Callable[[tk.Frame], None]] = {
            "behavior": self._behavior,
            "reading": self._reading,
            "comment": self._comment,
            "post": self._post,
            "collect": self._collect,
            "data": self._data,
            "help": self._help,
        }
        for key, text in self.TABS:
            holder = ScrollFrame(self.book, bg=UI["bg"])
            self.book.add(holder, text=f"  {text}  ")
            self.tabs[key] = holder
            builders[key](holder.inner)

    def select_tab(self, key: str) -> None:
        if key in self.tabs:
            self.book.select(self.tabs[key])

    def on_show(self) -> None:
        self._refresh_modes()

    # ---------- 通用 ----------
    def _section(self, parent, title, subtitle=""):
        outer, body = card(parent, title, subtitle)
        outer.pack(fill="x", padx=px(4), pady=(px(10), 0))
        return body

    def _footer(self, body, save: Callable[[], None], extra=()) -> tk.StringVar:
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=(px(12), 0))
        ui_button(row, "💾 保存本页", save, "primary").pack(side="left")
        for text, cmd in extra:
            ui_button(row, text, cmd).pack(side="left", padx=(px(8), 0))
        flash = tk.StringVar(value="")
        tk.Label(row, textvariable=flash, bg=UI["card"], fg=UI["green"]).pack(side="left", padx=px(12))
        return flash

    def _flash(self, var: tk.StringVar, text="✔ 已保存，下一批生效") -> None:
        var.set(text)
        self.app.root.after(4000, lambda: var.set(""))

    def _mode_row(self, body, mode: str) -> tk.Label:
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=(0, px(8)))
        status = tk.Label(row, text="", bg=UI["card"], font=F(9, True))
        status.pack(side="left")
        ui_button(row, f"设为当前运行模式（{MODE_LABEL[mode]}）", lambda: self._use_mode(mode), "ghost").pack(
            side="right"
        )
        return status

    def _use_mode(self, mode: str) -> None:
        save = self._save_comment if mode == "comment" else self._save_post
        if save(quiet=True) and self.app.set_mode(mode):
            self._refresh_modes()

    def _refresh_modes(self) -> None:
        mode = self.app.settings.mode
        for key, label in (("comment", self.comment_mode), ("post", self.post_mode)):
            on = mode == key
            label.configure(
                text="● 当前运行模式" if on else f"○ 未启用（当前：{MODE_LABEL[mode]}）",
                fg=UI["green"] if on else UI["faint"],
            )

    # ---------- 点赞与行为 ----------
    def _behavior(self, parent) -> None:
        body = self._section(parent, "点赞", "读完正文后的随机点赞；“已读帖子点赞”工作流也受这里的上限约束")
        a = self.app.settings.advanced
        self.adv_vars = {
            "p_like": tk.StringVar(value=f"{a['p_like']:g}"),
            "max_likes": tk.StringVar(value=str(a["max_likes"])),
            "min_like_interval": tk.StringVar(value=f"{a['min_like_interval']:g}"),
        }
        form = Form(body)
        form.frame.pack(fill="x")
        form.add(
            "读完正文后的点赞概率", lambda p: entry(p, self.adv_vars["p_like"]), "0～1，填 0 关闭随机点赞"
        )
        form.add(
            "单号单次最多尝试点赞",
            lambda p: entry(p, self.adv_vars["max_likes"]),
            "0～100 次，含结果未确认的点击",
        )
        form.add("两次点赞最小间隔", lambda p: entry(p, self.adv_vars["min_like_interval"]), "秒，0～86400")
        hint(
            body,
            "尝试上限包含结果未确认的点击，重连不清零、不自动重发。是否允许点赞在「账号与任务」页勾选。",
            wrap=900,
        ).pack(fill="x", pady=(px(6), 0))
        self.adv_flash = self._footer(body, self._save_behavior)

    def _save_behavior(self) -> None:
        s = self.app.settings
        old = s.advanced
        try:
            new = dict(old)
            new.update(
                {
                    key: int(var.get()) if key == "max_likes" else float(var.get())
                    for key, var in self.adv_vars.items()
                }
            )
            validate_partial(new)
            s.advanced = new
            self.app.save_config()
        except Exception as exc:
            s.advanced = old
            messagebox.showerror("参数无效或保存失败", str(exc))
            return
        self._flash(self.adv_flash)
        self.app.log("点赞参数已保存，下一批任务使用新设置。")

    # ---------- 自动评论 ----------
    def _comment(self, parent) -> None:
        c = self.app.settings.comment
        body = self._section(parent, "阅读流程 · TXT 自动评论", "每行一条评论，空行忽略；不会修改原 TXT")
        self.comment_mode = self._mode_row(body, "comment")
        self.c_vars = {
            "file": tk.StringVar(value=c["comment_file"]),
            "count": tk.StringVar(value=str(c["comment_count"])),
            "interval": tk.StringVar(value=f"{c['comment_interval']:g}"),
            "order": tk.StringVar(value=ORDER_LABELS[c["comment_order"]]),
        }
        form = Form(body)
        form.frame.pack(fill="x")
        form.add(
            "评论 TXT",
            lambda p: FilePicker(p, self.c_vars["file"], "选择评论 TXT", self._preview_comment),
            sticky="ew",
            wide=True,
        )
        form.add("单号每批最多尝试评论", lambda p: entry(p, self.c_vars["count"]), "条")
        form.add("同账号评论间隔", lambda p: entry(p, self.c_vars["interval"]), "秒")
        form.add("读取顺序", lambda p: combo(p, self.c_vars["order"], ORDER_LABELS.values(), 10))
        self.c_preview = text_box(body, height=6, readonly=True)
        self.c_preview.pack(fill="x", pady=(px(6), 0))
        hint(body, COMMENT_NOTES, wrap=900).pack(fill="x", pady=(px(8), 0))
        self.c_flash = self._footer(
            body,
            self._save_comment,
            (
                ("预览文件", self._preview_comment),
                ("核对评论记录 ›", lambda: self.app.pages["review"].show_kind("comments")),
            ),
        )
        if c["comment_file"]:
            self._preview_comment()

    def _preview_comment(self) -> None:
        try:
            rows = load_draft_lines(self.c_vars["file"].get())
            set_text(
                self.c_preview,
                f"共 {len(rows)} 条（每行一条，空行忽略）\n\n" + "\n".join(t for _, t in rows[:10]),
            )
        except Exception as exc:
            set_text(self.c_preview, f"无法读取：{exc}")

    def _save_comment(self, quiet: bool = False) -> bool:
        s, v = self.app.settings, self.c_vars
        old = s.comment
        try:
            new = {
                "comment_enabled": old["comment_enabled"],
                "comment_file": v["file"].get().strip(),
                "comment_count": int(v["count"].get()),
                "comment_interval": float(v["interval"].get()),
                "comment_order": "random" if v["order"].get() == "随机" else "sequential",
            }
            validate_partial(new)
            if new["comment_file"]:
                load_draft_lines(new["comment_file"])
            s.comment = new
            self.app.save_config()
        except Exception as exc:
            s.comment = old
            messagebox.showerror("无法保存", str(exc))
            return False
        self.app.update_mode_ui()
        if not quiet:
            self._flash(self.c_flash)
            self.app.log("自动评论设置已保存，下一批生效。")
        return True

    # ---------- 自动发推 ----------
    def _post(self, parent) -> None:
        d = self.app.settings.draft
        body = self._section(parent, "TXT 自动发推", "一行一条推文，空行忽略；不会修改原 TXT")
        self.post_mode = self._mode_row(body, "post")
        self.d_vars = {
            "file": tk.StringVar(value=d["draft_file"]),
            "count": tk.StringVar(value=str(d["draft_count"])),
            "interval": tk.StringVar(value=f"{d['draft_interval']:g}"),
            "order": tk.StringVar(value=ORDER_LABELS[d["draft_order"]]),
            "scope": tk.StringVar(value=SCOPE_LABELS[d["draft_scope"]]),
            "schedule": tk.StringVar(value=SCHEDULE_LABELS[d["draft_schedule_mode"]]),
            "date": tk.StringVar(value=d["draft_schedule_date"] or datetime.now().strftime("%Y-%m-%d")),
            "time": tk.StringVar(value=d["draft_schedule_time"]),
        }
        v = self.d_vars
        form = Form(body)
        form.frame.pack(fill="x")
        form.add(
            "推文 TXT",
            lambda p: FilePicker(p, v["file"], "选择推文 TXT", self._preview_post),
            sticky="ew",
            wide=True,
        )
        form.add("单号每批最多发布", lambda p: entry(p, v["count"]), "条")
        form.add("同账号两条间隔", lambda p: entry(p, v["interval"]), "秒")
        form.add("读取顺序", lambda p: combo(p, v["order"], ORDER_LABELS.values(), 10))
        form.add("文本分配", lambda p: combo(p, v["scope"], SCOPE_LABELS.values(), 18))
        form.add("启动方式", lambda p: combo(p, v["schedule"], SCHEDULE_LABELS.values(), 18))
        self.date_entry = form.add(
            "指定日期", lambda p: entry(p, v["date"], 14), "YYYY-MM-DD，仅“指定日期时间”使用"
        )
        form.add("本机时间", lambda p: entry(p, v["time"], 14), "HH:MM 或 HH:MM:SS")
        v["schedule"].trace_add("write", lambda *_: self._schedule_state())
        self._schedule_state()
        self.d_info = tk.StringVar(value="")
        tk.Label(
            body,
            textvariable=self.d_info,
            bg=UI["card"],
            fg=UI["mute"],
            anchor="w",
            justify="left",
            wraplength=px(900),
        ).pack(fill="x", pady=(px(6), 0))
        hint(body, POST_NOTES, wrap=900).pack(fill="x", pady=(px(8), 0))
        self.d_flash = self._footer(
            body,
            self._save_post,
            (
                ("预览文件", self._preview_post),
                ("核对发布记录 ›", lambda: self.app.pages["review"].show_kind("drafts")),
            ),
        )
        if d["draft_file"]:
            self._preview_post()

    def _schedule_state(self) -> None:
        once = self.d_vars["schedule"].get() == SCHEDULE_LABELS["once"]
        self.date_entry.configure(state="normal" if once else "disabled")

    def _preview_post(self) -> None:
        try:
            rows = load_draft_lines(self.d_vars["file"].get())
            self.d_info.set(f"共 {len(rows)} 条。首条：{rows[0][1][:100]}")
        except Exception as exc:
            self.d_info.set(f"无法读取：{exc}")

    def _save_post(self, quiet: bool = False) -> bool:
        s, v = self.app.settings, self.d_vars
        old = s.draft
        try:
            new = {
                "draft_enabled": old["draft_enabled"],
                "draft_file": v["file"].get().strip(),
                "draft_count": int(v["count"].get()),
                "draft_interval": float(v["interval"].get()),
                "draft_order": "random" if v["order"].get() == "随机" else "sequential",
                "draft_scope": "per_account" if v["scope"].get() == SCOPE_LABELS["per_account"] else "shared",
                "draft_schedule_mode": next(
                    k for k, t in SCHEDULE_LABELS.items() if t == v["schedule"].get()
                ),
                "draft_schedule_date": v["date"].get().strip(),
                "draft_schedule_time": v["time"].get().strip(),
            }
            validate_partial(new)
            if new["draft_file"]:
                load_draft_lines(new["draft_file"])
            s.draft = new
            self.app.save_config()
        except Exception as exc:
            s.draft = old
            messagebox.showerror("无法保存", str(exc))
            return False
        self.app.update_mode_ui()
        if not quiet:
            self._flash(self.d_flash)
            self.app.log("TXT 自动发推设置已保存，下一批生效。")
        return True

    # ---------- 数据采集与回复 ----------
    def _collect(self, parent) -> None:
        d = self.app.settings.dash
        body = self._section(parent, "数据采集", "开局和收尾各采集一次，用时不占单号阅读时长")
        self.dash_vars = {
            "stats_enabled": tk.BooleanVar(value=d["stats_enabled"]),
            "stats_recent_enabled": tk.BooleanVar(value=d["stats_recent_enabled"]),
            "stats_mentions": tk.BooleanVar(value=d["stats_mentions"]),
            "stats_dm": tk.BooleanVar(value=d["stats_dm"]),
            "stats_posts": tk.StringVar(value=str(d["stats_posts"])),
            "stats_interval_min": tk.StringVar(value=f"{d['stats_interval_min']:g}"),
            "reply_min_interval": tk.StringVar(value=f"{d['reply_min_interval']:g}"),
            "reply_daily_cap": tk.StringVar(value=str(d["reply_daily_cap"])),
        }
        for key, text, note in (
            ("stats_enabled", "每次运行时采集账号数据（粉丝 / 获赞 / 评论 / 红点）", "开局和收尾各一次"),
            ("stats_recent_enabled", "统计最近8小时本人帖子与发出的回复", "另外读取个人主页与回复分类；达到预算时会标记覆盖不完整"),
            ("stats_mentions", "同时读取评论与提及（通知页）", "进入通知页后，X 上的通知红点会被清零"),
            (
                "stats_dm",
                "同时读取私信列表（只读）",
                "不打开会话，所以不会把私信标成已读；预览文字只存在本机",
            ),
        ):
            check(body, text, self.dash_vars[key]).pack(fill="x")
            hint(body, "　　" + note).pack(fill="x", pady=(0, px(4)))
        form = Form(body)
        form.frame.pack(fill="x", pady=(px(8), 0))
        form.add("每次读取最近帖子数", lambda p: entry(p, self.dash_vars["stats_posts"]), "3～100")
        form.add(
            "运行中每隔多少分钟再采集",
            lambda p: entry(p, self.dash_vars["stats_interval_min"]),
            "0 = 只在开局和收尾采集",
        )
        body2 = self._section(parent, "面板回复", "收件箱里手写的回复，由对应账号的浏览器一条一条发送")
        form2 = Form(body2)
        form2.frame.pack(fill="x")
        form2.add(
            "两条回复之间至少间隔", lambda p: entry(p, self.dash_vars["reply_min_interval"]), "秒，0～86400"
        )
        form2.add(
            "每个账号每天最多回复",
            lambda p: entry(p, self.dash_vars["reply_daily_cap"]),
            "条，0 = 不限制（建议保持较小）",
        )
        self.dash_flash = self._footer(body2, self._save_collect)

    def _save_collect(self) -> None:
        v = self.dash_vars
        try:
            new = {
                "stats_enabled": bool(v["stats_enabled"].get()),
                "stats_recent_enabled": bool(v["stats_recent_enabled"].get()),
                "stats_mentions": bool(v["stats_mentions"].get()),
                "stats_dm": bool(v["stats_dm"].get()),
                "stats_posts": int(v["stats_posts"].get().strip()),
                "stats_interval_min": float(v["stats_interval_min"].get().strip()),
                "reply_min_interval": float(v["reply_min_interval"].get().strip()),
                "reply_daily_cap": int(v["reply_daily_cap"].get().strip()),
            }
            validate_partial(new)
        except ValueError as exc:
            messagebox.showwarning("设置有误", f"请检查数字：{exc}")
            return
        self.app.settings.dash = new
        if self.app.try_save("采集设置"):
            self._flash(self.dash_flash)

    # ---------- 数据管理 ----------
    def _data(self, parent) -> None:
        body = self._section(parent, "导出与文件夹", "所有数据都保存在本机")
        hint(
            body,
            f"看板数据库：{DATA_DIR / 'dashboard.sqlite3'}\n运行历史：{DATA_DIR / 'history.jsonl'}\n"
            f"日志：{LOG_DIR}",
            wrap=900,
        ).pack(fill="x")
        grid = tk.Frame(body, bg=UI["card"])
        grid.pack(fill="x", pady=px(10))
        for i, (text, cmd) in enumerate(
            (
                ("📤 导出看板 CSV", self.app.pages["dash"].export),
                ("📤 导出运行历史 CSV", self.export_history),
                ("📂 打开数据文件夹", lambda: open_path(DATA_DIR)),
                ("📜 打开日志文件夹", lambda: open_path(LOG_DIR)),
            )
        ):
            grid.columnconfigure(i % 4, weight=1, uniform="d")
            ui_button(grid, text, cmd).grid(row=0, column=i, sticky="ew", padx=px(3))
        body = self._section(parent, "演示数据", "账号名以“演示·”开头，不影响真实账号，不能真的发送")
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        ui_button(row, "🧪 载入演示数据", self.load_demo).pack(side="left")
        ui_button(row, "🧹 清除演示数据", self.clear_demo).pack(side="left", padx=px(8))
        body = self._section(parent, "清理旧数据", "每个账号最新一次数据会保留")
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        tk.Label(row, text="清理超过", bg=UI["card"], fg=UI["mute"]).pack(side="left")
        self.prune_days = tk.StringVar(value="90")
        tk.Entry(row, textvariable=self.prune_days, width=5, justify="center").pack(
            side="left", padx=px(6), ipady=px(2)
        )
        tk.Label(row, text="天的历史快照 / 动态 / 已处理消息", bg=UI["card"], fg=UI["mute"]).pack(side="left")
        ui_button(row, "清理", self.prune_data, "warn").pack(side="left", padx=px(10))

    def export_history(self) -> None:
        path = filedialog.asksaveasfilename(
            defaultextension=".csv", initialfile="运行历史.csv", filetypes=[("CSV 文件", "*.csv")]
        )
        if not path:
            return

        def worker():
            try:
                count = HistoryStore.export_csv(Path(path))
                self.app.log(f"已导出 {count} 条历史记录：{path}")
            except Exception as exc:
                self.app.log(f"导出失败：{exc}")

        threading.Thread(target=worker, name="export-history", daemon=True).start()

    def load_demo(self) -> None:
        self.app.store.seed_demo()
        self.app.log("已载入演示数据（账号名都以“演示·”开头，不会影响真实账号）。")
        self.app.show_page("dash")

    def clear_demo(self) -> None:
        self.app.store.clear_demo()
        self.app.log("已清除演示数据。")
        self.app.refresh_all()

    def prune_data(self) -> None:
        try:
            days = int(self.prune_days.get().strip())
            if days < 1:
                raise ValueError
        except ValueError:
            messagebox.showwarning("提示", "请填写大于 0 的整数天数。")
            return
        if messagebox.askyesno(
            "确认清理", f"删除 {days} 天前的历史快照、动态和已处理消息？\n（每个账号最新一次数据会保留）"
        ):
            removed = self.app.store.prune(days)
            self.app.log(f"已清理 {removed} 条旧数据。")
            self.app.refresh_all()

    # ---------- 使用说明 ----------
    def _help(self, parent) -> None:
        body = self._section(parent, f"使用说明 · V{APP_VERSION}")
        tk.Label(
            body,
            text=GUIDE,
            bg=UI["card"],
            fg=UI["mute"],
            justify="left",
            anchor="nw",
            wraplength=px(1000),
            font=F(9),
        ).pack(fill="both", expand=True)

    def _reading(self, parent):
        body=self._section(parent,'V11.1 逐帖评分与节奏','仅V11.1养号流程使用；不修改V10原流程或互动权限。')
        hint(body,'80/17/3为机会权重，经过候选、冷却、配额和预算过滤后归一化，并非固定触发频率。',wrap=900).pack(fill='x')
        policy=dict(self.app.settings.reading_policy)
        self.reading_vars={}
        form=Form(body);form.frame.pack(fill='x')
        for key,default,label,low,high in READING_FIELDS:
            value=tk.StringVar(value=str(policy[key]));self.reading_vars[key]=value
            form.add(label,lambda p,value=value:entry(p,value),f'{low}～{high}')
        self.reading_flash=self._footer(body,self._save_reading)

    def _save_reading(self):
        settings=self.app.settings;old=settings.reading_policy
        try:
            values=tuple((key,int(self.reading_vars[key].get()) if type(default) is int else float(self.reading_vars[key].get()))
                for key,default,*_ in READING_FIELDS)
            configured=WarmupConfig(DEFAULT_DURATION_MIN,False,False,True,reading_policy=values).reading_policy
            settings.reading_policy=configured;self.app.save_config()
        except Exception as exc:
            settings.reading_policy=old
            messagebox.showerror('阅读参数无效或保存失败',str(exc));return
        self._flash(self.reading_flash);self.app.log('V11.1阅读参数已保存，下一批生效。')



def open_path(path: Path) -> None:
    try:
        path.mkdir(parents=True, exist_ok=True)
        if sys.platform == "win32":
            os.startfile(str(path))  # type: ignore[attr-defined]
        elif sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])
    except Exception as exc:
        messagebox.showinfo("文件夹位置", f"无法自动打开，请手动前往：\n{path}\n\n{exc}")


# ======================================================================
# 模块：xmanager/ui/logs.py
# ======================================================================
"""运行日志：实时追加、关键字过滤、只看异常、颜色分级。完整日志在 logs/warmup.log。"""


import re
import tkinter as tk
from tkinter import ttk
from typing import Iterable


ERROR_RE = re.compile(r"✖|失败|异常|错误|Error|Exception|超时", re.I)
WARN_RE = re.compile(r"⚠|警告|待核对|暂缓|未完成|未确认|跳过|重连", re.I)


def tone_of(line: str) -> str:
    if line.lstrip().startswith(("===", ">>")) or "] ===" in line or "] >>" in line:
        return "head"
    if ERROR_RE.search(line):
        return "error"
    if WARN_RE.search(line):
        return "warn"
    return "info"


class LogsPage(Page):
    key, icon, title = "logs", "📜", "运行日志"
    subtitle = f"界面保留最近 {MAX_LOG_LINES} 行；完整记录在日志文件夹"

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        bar = self.toolbar()
        self.query = tk.StringVar()
        self.only_issues = tk.BooleanVar(value=False)
        self.follow = tk.BooleanVar(value=True)
        tk.Label(bar, text="过滤", fg=UI["mute"], bg=UI["bg"]).pack(side="left")
        tk.Entry(bar, textvariable=self.query, width=26).pack(side="left", padx=px(6), ipady=px(3))
        self.query.trace_add("write", lambda *_: self.rerender())
        check(bar, "只看异常 / 警告", self.only_issues, command=self.rerender).pack(side="left", padx=px(8))
        check(bar, "自动滚动到底部", self.follow).pack(side="left")
        ui_button(bar, "打开日志文件夹", lambda: open_path(LOG_DIR)).pack(side="right")
        ui_button(bar, "复制显示内容", self.copy).pack(side="right", padx=px(8))
        ui_button(bar, "清空显示", self.clear).pack(side="right")

        outer, body = card(page)
        outer.grid(row=1, column=0, sticky="nsew", padx=px(18), pady=(0, px(14)))
        self.text = tk.Text(
            body,
            state="disabled",
            bg=UI["log_bg"],
            fg="#c9d1d9",
            font=mono(9),
            relief="flat",
            highlightthickness=0,
            wrap="word",
        )
        bar = ttk.Scrollbar(body, orient="vertical", command=self.text.yview)
        self.text.configure(yscrollcommand=bar.set)
        bar.pack(side="right", fill="y")
        self.text.pack(side="left", fill="both", expand=True)
        self.text.tag_configure("head", foreground=UI["blue"])
        self.text.tag_configure("error", foreground="#ff6b6b")
        self.text.tag_configure("warn", foreground=UI["amber"])
        self.text.tag_configure("info", foreground="#7ee2b8")

    def _match(self, line: str) -> bool:
        needle = self.query.get().strip().casefold()
        if needle and needle not in line.casefold():
            return False
        return not self.only_issues.get() or tone_of(line) in ("error", "warn")

    def _write(self, lines: Iterable[str], reset: bool = False) -> None:
        text = self.text
        text.configure(state="normal")
        if reset:
            text.delete("1.0", "end")
        for line in lines:
            if self._match(line):
                text.insert("end", line + "\n", tone_of(line))
        total = int(text.index("end-1c").split(".")[0])
        if total > MAX_LOG_LINES:
            text.delete("1.0", f"{total - MAX_LOG_LINES}.0")
        if self.follow.get():
            text.see("end")
        text.configure(state="disabled")

    def append(self, lines) -> None:
        self._write(lines)

    def rerender(self) -> None:
        self._write(list(self.app.log_lines), reset=True)

    def clear(self) -> None:
        self.app.log_lines.clear()
        self._write([], reset=True)

    def copy(self) -> None:
        self.app.root.clipboard_clear()
        self.app.root.clipboard_append(self.text.get("1.0", "end-1c"))

    def on_show(self) -> None:
        if self.follow.get():
            self.text.see("end")


# ======================================================================
# 模块：xmanager/ui/review.py
# ======================================================================
"""记录核对：TXT 发推 / 自动评论中“结果不明”或“失败”的条目，人工核实后标记。

V9 中分别藏在两个设置弹窗的按钮里，现在合并为一个页面。
"""


import tkinter as tk
import webbrowser
from tkinter import messagebox
from typing import Any, Dict, List



class ReviewPage(Page):
    key, icon, title = "review", "🧾", "记录核对"
    subtitle = "核实“结果不明 / 失败”的发推与评论：已发布 → 标记已发；未发布 → 重新入队"

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.kind = "drafts"
        self.rows: List[Dict[str, Any]] = []

        bar = self.toolbar()
        self.seg = Segmented(
            bar, [("drafts", "推文发布记录"), ("comments", "评论记录")], self.switch, "drafts"
        )
        self.seg.pack(side="left")
        ui_button(bar, "🔄 刷新", lambda: self.refresh(True)).pack(side="left", padx=px(10))
        self.count = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.count, fg=UI["blue"], bg=UI["bg"], font=F(9)).pack(side="right")

        body = tk.Frame(page, bg=UI["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=px(18), pady=(0, px(14)))
        body.columnconfigure(0, weight=3)
        body.columnconfigure(1, weight=2)
        body.rowconfigure(0, weight=1)
        outer, inner = card(body, "待核对条目", "任务运行时只能查看，停止后才能更改记录")
        outer.grid(row=0, column=0, sticky="nsew")
        frame, self.tree = make_tree(
            inner,
            ("owner", "state", "text"),
            ("浏览器账号 ID", "状态", "文本摘要"),
            (200, 90, 460),
            height=14,
            selectmode="browse",
            stretch=("text",),
        )
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.show())
        self.empty = tk.Label(inner, text="没有需要核对的记录 ✔", bg=UI["card"], fg=UI["faint"], font=F(10))

        outer, inner = card(body, "详情与处理")
        outer.grid(row=0, column=1, sticky="nsew", padx=(px(10), 0))
        self.details = text_box(inner, height=12, readonly=True)
        self.details.pack(fill="both", expand=True)
        row = tk.Frame(inner, bg=UI["card"])
        row.pack(fill="x", pady=(px(10), 0))
        ui_button(row, "✔ 已核实发布：标记已发", lambda: self.resolve(True), "good").pack(side="left")
        ui_button(row, "已核实未发布：重新入队", lambda: self.resolve(False)).pack(side="left", padx=px(6))
        self.open_btn = ui_button(row, "🔗 打开目标", self.open_target)
        self.open_btn.pack(side="right")
        tk.Label(
            inner,
            text="结果不明时请保持原状：程序不会自动重发，也不会把它当作已发送。",
            bg=UI["card"],
            fg=UI["faint"],
            font=F(8),
            anchor="w",
        ).pack(fill="x", pady=(px(6), 0))

    def switch(self, kind: str) -> None:
        self.kind = kind
        self.seg.set(kind)
        self.refresh(True)

    def show_kind(self, kind: str) -> None:
        self.app.show_page("review")
        self.switch(kind)

    def _store(self):
        return CommentStore() if self.kind == "comments" else DraftStore()

    def refresh(self, force: bool = False) -> None:
        try:
            store = self._store()
            if not self.app.running:
                # recover 会把“发送中”改成“待核对”，只能在没有任务运行时调用。
                store.recover()
            self.rows = store.unresolved()
        except Exception as exc:
            self.rows = []
            self.count.set(f"读取记录失败：{exc}")
            return
        self.tree.delete(*self.tree.get_children())
        for i, row in enumerate(self.rows):
            tone = "warn" if row["state"] == "unknown" else "bad"
            self.tree.insert(
                "",
                "end",
                iid=str(i),
                tags=(tone,),
                values=(row["owner"], row["state"], row["text"].replace("\n", " ")[:100]),
            )
        if self.rows:
            self.empty.place_forget()
        else:
            self.empty.place(relx=0.5, rely=0.5, anchor="center")
        self.count.set(f"{len(self.rows)} 条待核对")
        set_text(self.details, "")
        self.open_btn.configure(state="normal" if self.kind == "comments" else "disabled")

    def selected(self):
        pick = self.tree.selection()
        return self.rows[int(pick[0])] if pick else None

    def show(self) -> None:
        row = self.selected()
        if not row:
            set_text(self.details, "")
            return
        target = f"目标：https://x.com/i/status/{row['item']}\n" if self.kind == "comments" else ""
        set_text(
            self.details,
            f"账号：{row['owner']}\n{target}状态：{row['state']}\n原因：{row['error']}\n\n{row['text']}",
        )

    def open_target(self) -> None:
        row = self.selected()
        if row and self.kind == "comments":
            webbrowser.open(f"https://x.com/i/status/{row['item']}")

    def resolve(self, sent: bool) -> None:
        if self.app.running:
            messagebox.showinfo("任务执行中", "请先停止任务，再更改记录。")
            return
        row = self.selected()
        if not row:
            messagebox.showinfo("提示", "先在左侧选择一条记录。")
            return
        if not sent and not messagebox.askyesno(
            "确认重新入队", "确定这条没有发布成功吗？\n重新入队后会再发一次，如果其实已经发出就会重复。"
        ):
            return
        if self.kind == "comments" and row["scope"].startswith("panel:"):
            self.app.store.resolve_outbox(int(row["scope"].rsplit(":", 1)[1]), sent)
        else:
            self._store().resolve(row["scope"], row["item"], sent)
        self.app.log(
            f"已人工核对{'评论' if self.kind == 'comments' else '推文'}记录：{'已发' if sent else '重新入队'}。"
        )
        self.refresh(True)


# ======================================================================
# 模块：xmanager/ui/workflows_page.py
# ======================================================================
"""工作流目录：105 项工作流的启用、触发档位、基础次数，以及兴趣 / 搜索关键词 TXT。

V9 中这是一个弹窗，现在是独立页面；修改后点“保存”下一批生效。
"""


import tkinter as tk
from tkinter import messagebox, ttk
from typing import Dict, List


ALL_GROUPS, ALL_TIERS = "全部分类", "全部档位"
AUTO_TIER_LABELS = [rule[0] for key, rule in TIER_RULES.items() if key != "manual"]


class WorkflowsPage(Page):
    key, icon, title = "workflows", "🧩", "工作流目录"
    subtitle = f"{len(WORKFLOW_SPECS)} 项工作流：可搜索、多选、批量调整档位与次数；保存后下一批生效"

    def build(self) -> None:
        page = self.frame
        page.columnconfigure(0, weight=1)
        page.rowconfigure(1, weight=1)
        self.rows: Dict[str, List] = {}
        self.tiers: Dict[str, str] = {}
        self.dirty = False
        self._loading = False
        self._pending_edit = False

        bar = self.toolbar()
        self.query = tk.StringVar()
        self.group = tk.StringVar(value=ALL_GROUPS)
        self.tier_filter = tk.StringVar(value=ALL_TIERS)
        self.hide_manual = tk.BooleanVar(value=False)
        tk.Label(bar, text="搜索", fg=UI["mute"], bg=UI["bg"]).pack(side="left")
        tk.Entry(bar, textvariable=self.query, width=22).pack(side="left", padx=px(6), ipady=px(3))
        ttk.Combobox(
            bar,
            textvariable=self.group,
            values=[ALL_GROUPS] + sorted({s.group for s in WORKFLOW_SPECS}),
            state="readonly",
            width=16,
        ).pack(side="left", padx=px(4))
        ttk.Combobox(
            bar,
            textvariable=self.tier_filter,
            values=[ALL_TIERS] + [v[0] for v in TIER_RULES.values()],
            state="readonly",
            width=12,
        ).pack(side="left", padx=px(4))
        check(bar, "隐藏手动项", self.hide_manual, command=self.render).pack(side="left", padx=px(8))
        for var in (self.query, self.group, self.tier_filter):
            var.trace_add("write", lambda *_: self.render())
        self.save_btn = ui_button(bar, "💾 保存工作流与关键词", self.save, "primary")
        self.save_btn.pack(side="right")
        ui_button(bar, "放弃修改", self.reload).pack(side="right", padx=px(8))
        ui_button(bar, "恢复默认", self.restore_defaults).pack(side="right")

        body = tk.Frame(page, bg=UI["bg"])
        body.grid(row=1, column=0, sticky="nsew", padx=px(18), pady=(0, px(14)))
        body.columnconfigure(0, weight=1)
        body.columnconfigure(1, weight=0, minsize=px(350))
        body.rowconfigure(0, weight=1)

        outer, inner = card(body, "工作流", "可多选（Shift / Ctrl）后在右侧批量调整")
        outer.grid(row=0, column=0, sticky="nsew")
        self.stats = tk.StringVar(value="")
        tk.Label(outer.head, textvariable=self.stats, bg=UI["card"], fg=UI["blue"], font=F(9)).pack(
            side="right"
        )
        cols = ("group", "label", "enabled", "tier", "base", "budget")
        frame, self.tree = make_tree(
            inner,
            cols,
            ("分类", "工作流 / 操作", "启用", "触发档位", "基础次数", "场景上限"),
            (96, 220, 44, 80, 60, 60),
            height=16,
            stretch=("label",),
            anchors={"enabled": "center", "base": "center", "budget": "center"},
        )
        frame.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self.on_select())
        self.tree.bind("<Double-1>", lambda _e: self.toggle_enabled())

        side = tk.Frame(body, bg=UI["bg"])
        side.grid(row=0, column=1, sticky="nsew", padx=(px(10), 0))
        side.columnconfigure(0, weight=1)
        side.rowconfigure(2, weight=1)
        self._build_editor(side)
        self._build_keywords(side)
        self.reload()

    def _build_editor(self, side) -> None:
        outer, body = card(side, "批量调整选中项")
        outer.grid(row=0, column=0, sticky="ew")
        self.on = tk.BooleanVar(value=True)
        self.chosen_tier = tk.StringVar(value=TIER_RULES["normal"][0])
        self.base = tk.StringVar(value="1")
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x")
        check(row, "启用", self.on).pack(side="left")
        ttk.Combobox(
            row, textvariable=self.chosen_tier, values=AUTO_TIER_LABELS, state="readonly", width=11
        ).pack(side="left", padx=px(6))
        tk.Label(row, text="次数", bg=UI["card"], fg=UI["mute"]).pack(side="left")
        tk.Spinbox(row, from_=0, to=500, textvariable=self.base, width=5).pack(side="left", padx=px(4))
        row = tk.Frame(body, bg=UI["card"])
        row.pack(fill="x", pady=(px(8), 0))
        ui_button(row, "应用到选中项", self.apply_selected, "good").pack(side="left")
        ui_button(row, "复制手动入口", self.copy_entry).pack(side="left", padx=px(6))
        self.detail = tk.Label(
            body,
            text="选择一项查看条件；可多选后批量调整档位和次数。双击切换启用。",
            bg=UI["card"],
            fg=UI["mute"],
            font=F(9),
            justify="left",
            anchor="w",
            wraplength=px(320),
        )
        self.detail.pack(fill="x", pady=(px(8), 0))
        for var in (self.on, self.chosen_tier, self.base):
            var.trace_add("write", self._edited)

        outer, body = card(side, "档位说明")
        outer.grid(row=1, column=0, sticky="ew", pady=px(10))
        lines = []
        for key, (text, weight, cool, _start) in TIER_RULES.items():
            if key != "manual":
                lines.append(f"{text}：权重 {weight:g}，执行后冷却 {cool[0]:g}～{cool[1]:g} 秒")
        lines.append("手动处理：发送 / 关系 / 付费 / 删除等，不进入自动计划")
        hint(
            body,
            "\n".join(lines) + "\n\n鼠标采用每次重新生成的分段轨迹与可变速度；不用于判断平台风控。",
            wrap=320,
        ).pack(fill="x")

    def _build_keywords(self, side) -> None:
        outer, body = card(side, "兴趣 / 搜索关键词 TXT", "每行一项；每批启动重新读取")
        outer.grid(row=2, column=0, sticky="nsew")
        self.keyword_path = tk.StringVar(value=self.app.settings.keyword_file)
        FilePicker(body, self.keyword_path, "选择关键词TXT", on_pick=self.preview_keywords).pack(fill="x")
        self.keyword_status = tk.StringVar(value="")
        tk.Label(
            body,
            textvariable=self.keyword_status,
            bg=UI["card"],
            fg=UI["faint"],
            font=F(8),
            anchor="w",
            justify="left",
            wraplength=px(320),
        ).pack(fill="x", pady=px(4))
        self.terms = tk.Text(body, width=30, height=5, wrap="word", font=F(9), state="disabled")
        self.terms.pack(fill="both", expand=True)
        ui_button(body, "重新读取", self.preview_keywords).pack(anchor="e", pady=(px(6), 0))

    # ---------- 数据 ----------
    def reload(self) -> None:
        s = self.app.settings
        self.rows = {key: [enabled, base] for key, enabled, base in s.workflow_settings}
        self.tiers = {spec.key: workflow_tier(spec, s.workflow_tiers) for spec in WORKFLOW_SPECS}
        self.keyword_path.set(s.keyword_file)
        self._set_dirty(False)
        self.render()
        self.preview_keywords()

    def restore_defaults(self) -> None:
        if not messagebox.askyesno(
            "恢复默认", "把全部工作流的启用状态、档位与次数恢复为默认值？\n（点保存后才生效）"
        ):
            return
        self.rows = {key: [enabled, base] for key, enabled, base in DEFAULT_WORKFLOW_SETTINGS}
        self.tiers = {spec.key: workflow_tier(spec, ()) for spec in WORKFLOW_SPECS}
        self._set_dirty(True)
        self.render()

    def _set_dirty(self, dirty: bool) -> None:
        self.dirty = dirty
        self.save_btn.configure(text="💾 保存工作流与关键词" + (" *" if dirty else ""))

    def render(self) -> None:
        selected = set(self.tree.selection())
        self.tree.delete(*self.tree.get_children())
        needle = self.query.get().strip().casefold()
        for spec in WORKFLOW_SPECS:
            tier_label = TIER_RULES[self.tiers[spec.key]][0]
            if self.group.get() not in (ALL_GROUPS, spec.group):
                continue
            if self.tier_filter.get() not in (ALL_TIERS, tier_label):
                continue
            if self.hide_manual.get() and spec.manual_only:
                continue
            if needle and needle not in f"{spec.label} {spec.group} {spec.key}".casefold():
                continue
            enabled, count = self.rows[spec.key]
            tone = "mute" if spec.manual_only else "ok" if enabled and count > 0 else "info"
            self.tree.insert(
                "",
                "end",
                iid=spec.key,
                tags=(tone,),
                values=(
                    spec.group,
                    spec.label,
                    "手动" if spec.manual_only else "✔" if enabled else "—",
                    tier_label,
                    count,
                    "—" if spec.manual_only else f"{spec.budget_sec}秒",
                ),
            )
            if spec.key in selected:
                self.tree.selection_add(spec.key)
        auto = [k for k, (on, base) in self.rows.items() if not WORKFLOW_BY_KEY[k].manual_only]
        active = sum(1 for k in auto if self.rows[k][0] and self.rows[k][1] > 0)
        self.stats.set(
            f"自动 {len(auto)} 项（启用 {active}）· 手动 {len(self.rows) - len(auto)} 项 · "
            f"当前显示 {len(self.tree.get_children())}"
        )

    def on_select(self) -> None:
        selected = self.tree.selection()
        if not selected:
            return
        spec = WORKFLOW_BY_KEY[selected[0]]
        enabled, count = self.rows[spec.key]
        self._loading = True
        self.on.set(enabled)
        self.base.set(str(count))
        if not spec.manual_only:
            self.chosen_tier.set(TIER_RULES[self.tiers[spec.key]][0])
        self._loading = False
        self._pending_edit = False
        prefix = f"已选 {len(selected)} 项。" if len(selected) > 1 else ""
        if spec.manual_only:
            text = (
                f"手动处理：{spec.label}。不进入自动计划，不会记为执行成功。参考入口：https://x.com{spec.arg}"
                "；TXT 发布使用「设置 › 自动发推」。"
            )
        else:
            rule = TIER_RULES[self.tiers[spec.key]]
            text = (
                f"{spec.label}｜权重 {rule[1]:g}，每次执行后冷却 {rule[2][0]:g}～{rule[2][1]:g} 秒（条件不满足时跳过）。"
                "次数为尝试上限；重连不重抽。消息阅读可能改变已读状态。"
            )
        self.detail.configure(text=prefix + text)

    def _edited(self, *_):
        if not self._loading:
            self._pending_edit = True

    def apply_selected(self) -> bool:
        try:
            count = int(self.base.get())
            tier = TIER_BY_LABEL.get(self.chosen_tier.get())
            if not 0 <= count <= 500 or tier not in TIER_RULES or tier == "manual":
                raise ValueError("请选择自动触发档位，次数填 0～500")
        except ValueError as exc:
            messagebox.showerror("参数无效", str(exc))
            return False
        changed = 0
        for key in self.tree.selection():
            if not WORKFLOW_BY_KEY[key].manual_only:
                self.rows[key] = [self.on.get(), count]
                self.tiers[key] = tier
                changed += 1
        self._pending_edit = False
        if changed:
            self._set_dirty(True)
        self.render()
        return True

    def toggle_enabled(self) -> None:
        for key in self.tree.selection():
            if not WORKFLOW_BY_KEY[key].manual_only:
                self.rows[key][0] = not self.rows[key][0]
                self._set_dirty(True)
        self.render()

    def copy_entry(self) -> None:
        selected = self.tree.selection()
        if selected and WORKFLOW_BY_KEY[selected[0]].manual_only:
            url = "https://x.com" + WORKFLOW_BY_KEY[selected[0]].arg
            self.app.root.clipboard_clear()
            self.app.root.clipboard_append(url)
            self.detail.configure(text="已复制参考入口。请在所需账号窗口手动打开并核对页面。")

    def preview_keywords(self) -> None:
        path = self.keyword_path.get().strip()
        try:
            rows = load_keyword_lines(path) if path else ()
            self.keyword_status.set(
                f"共 {len(rows)} 项；预览前 100 行。启动批次时读取 TXT 最新内容。"
                if rows
                else "未选择 TXT；兴趣与搜索类工作流不执行。"
            )
            content = "\n".join(rows[:100])
        except (ValueError, OSError) as exc:
            self.keyword_status.set(str(exc))
            content = ""
        set_text(self.terms, content)
        if path != self.app.settings.keyword_file:
            self._set_dirty(True)

    def save(self) -> None:
        if self._pending_edit and self.tree.selection() and not self.apply_selected():
            return
        s = self.app.settings
        previous = s.workflow_settings, s.workflow_tiers, s.interest_terms, s.keyword_file
        try:
            settings = tuple(
                (
                    spec.key,
                    False if spec.manual_only else self.rows[spec.key][0],
                    0 if spec.manual_only else self.rows[spec.key][1],
                )
                for spec in WORKFLOW_SPECS
            )
            overrides = tuple((spec.key, self.tiers[spec.key]) for spec in WORKFLOW_SPECS)
            path = self.keyword_path.get().strip()
            terms = load_keyword_lines(path) if path else ()
            WarmupConfig(
                DEFAULT_DURATION_MIN,
                False,
                True,
                True,
                workflow_settings=settings,
                workflow_tiers=overrides,
                interest_terms=terms,
                keyword_file=path,
            )
            s.workflow_settings, s.workflow_tiers, s.interest_terms, s.keyword_file = (
                settings,
                overrides,
                terms,
                path,
            )
            self.app.save_config()
        except Exception as exc:
            s.workflow_settings, s.workflow_tiers, s.interest_terms, s.keyword_file = previous
            messagebox.showerror("保存失败", str(exc))
            return
        self._set_dirty(False)
        self.app.update_mode_ui()
        self.app.log("工作流目录与档位已保存，下一批生效。手动项不进入自动调度。")


# ======================================================================
# 模块：xmanager/ui/app.py
# ======================================================================
"""主窗口：侧边导航 + 顶部任务栏 + 页面区 + 底部状态栏，以及批次的启动 / 暂停 / 停止 / 定时。"""


import logging
import os
import queue
import random
import threading
import time
import tkinter as tk
from collections import deque
from datetime import datetime
from tkinter import messagebox, ttk
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


PAGE_CLASSES = (
    DashboardPage,
    RecentPerformancePage,
    AccountsPage,
    FlowPage,
    InboxPage,
    WorkflowsPage,
    ReviewPage,
    SettingsPage,
    LogsPage,
)


class WarmupApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.closing = False
        self.stopping = False
        self.task_thread: Optional[threading.Thread] = None
        self.post_schedule: Optional[Dict[str, Any]] = None
        self.post_schedule_after: Optional[str] = None
        self.loading_browsers = False
        self.bit_state: Tuple[str, str] = ("checking", "正在连接比特浏览器…")

        self.raw_browsers: List[Dict[str, Any]] = []
        self.status_map: Dict[str, Tuple[str, str]] = {}
        self.batch_results: Dict[str, Result] = {}
        self.batch_total = 0
        self.batch_finished = 0
        self.done_today: Set[str] = set()

        self.ui_queue: queue.Queue = queue.Queue()
        self.log_queue: queue.Queue = queue.Queue(maxsize=4000)
        self.log_lines: deque = deque(maxlen=MAX_LOG_LINES)
        self.dropped_logs = 0
        self.ctl = RunControl(self.log, self.set_status)

        self.settings = AppSettings(ConfigStore.load())
        self.selected_ids: Set[str] = set(self.settings.selected)
        self.store = get_store()
        interrupted = self.store.recover()
        global_comments = CommentStore()
        global_comments.recover()
        global_comments.import_panel_history(self.store)

        self._build()
        for warning in self.settings.warnings:
            self.log(f"配置提示：{warning}")
        if interrupted:
            self.log(
                f"提示：上次退出时有 {interrupted} 条面板回复结果不明，已标为“待核对”，"
                "请到「收件箱」核对，程序不会自动重发。"
            )
        self.root.report_callback_exception = lambda typ, err, tb: logger.error(
            "界面回调异常", exc_info=(typ, err, tb)
        )
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.root.after(80, self._poll_ui)
        self.root.after(2500, self._auto_refresh)
        self.refresh_done_today()
        self.load_browsers()

    # ============================================================
    # 框架
    # ============================================================
    def _build(self) -> None:
        apply_theme(self.root)
        root = self.root
        root.title(f"{APP_NAME} V{APP_VERSION}")
        root.geometry(f"{px(1420)}x{px(880)}")
        root.minsize(px(1180), px(720))
        root.configure(bg=UI["bg"])
        run = self.settings.run
        self.duration_var = tk.StringVar(value=str(run["duration"]))
        self.concurrency_var = tk.StringVar(value=str(run["concurrency"]))
        self.run_flags = {
            key: tk.BooleanVar(value=bool(run[key]))
            for key in ("like", "deep", "random_order", "jitter", "close_after", "skip_done", "lite")
        }
        self.window_layout_var = tk.StringVar(
            value="整齐平铺" if run["window_layout"] == "tile" else "有序堆叠"
        )
        self.progress_var = tk.StringVar(value="待开始")
        self.mode_var = tk.StringVar(value=MODE_HINT[self.settings.mode])
        self.page_name = ""
        self.pages: Dict[str, Page] = {}
        self.nav_items: Dict[str, tk.Label] = {}

        shell = tk.Frame(root, bg=UI["bg"])
        shell.pack(fill="both", expand=True)
        self._build_statusbar(root)
        self._build_sidebar(shell)
        main = tk.Frame(shell, bg=UI["bg"])
        main.pack(side="left", fill="both", expand=True)
        self._build_topbar(main)
        host = tk.Frame(main, bg=UI["bg"])
        host.pack(fill="both", expand=True)
        host.rowconfigure(0, weight=1)
        host.columnconfigure(0, weight=1)
        for cls in PAGE_CLASSES:
            self.pages[cls.key] = cls(self, host)
        for i, cls in enumerate(PAGE_CLASSES, 1):
            root.bind(f"<Control-Key-{i}>", lambda _e, k=cls.key: self.show_page(k))
        root.bind("<F5>", lambda _e: self.refresh_all())
        start = run.get("page") if run.get("page") in self.pages else "dash"
        self.show_page(start)
        self.update_mode_ui()

    def _build_sidebar(self, shell) -> None:
        side = tk.Frame(shell, bg=UI["side"], width=px(208))
        side.pack(side="left", fill="y")
        side.pack_propagate(False)
        tk.Label(side, text="X  管理器", bg=UI["side"], fg=UI["text"], font=F(16, True)).pack(
            anchor="w", padx=px(20), pady=(px(22), 0)
        )
        tk.Label(side, text="养号 · 数据 · 回复", bg=UI["side"], fg=UI["faint"], font=F(8)).pack(
            anchor="w", padx=px(20), pady=(px(2), px(18))
        )
        groups = {"dash": "概览", "workflows": "配置", "logs": "系统"}
        for cls in PAGE_CLASSES:
            if cls.key in groups:
                tk.Label(side, text=groups[cls.key], bg=UI["side"], fg=UI["faint"], font=F(8)).pack(
                    anchor="w", padx=px(22), pady=(px(10), px(2))
                )
            item = tk.Label(
                side,
                text="",
                anchor="w",
                bg=UI["side"],
                fg=UI["mute"],
                font=F(11),
                padx=px(14),
                pady=px(9),
                cursor="hand2",
            )
            item.pack(fill="x")
            item.bind("<Button-1>", lambda _e, k=cls.key: self.show_page(k))
            item.bind(
                "<Enter>",
                lambda _e, w=item, k=cls.key: w.configure(bg=UI["card"]) if k != self.page_name else None,
            )
            item.bind(
                "<Leave>",
                lambda _e, w=item, k=cls.key: w.configure(bg=UI["side"]) if k != self.page_name else None,
            )
            self.nav_items[cls.key] = item
        tk.Label(
            side,
            text=f"V{APP_VERSION}  ·  Ctrl+1~{len(PAGE_CLASSES)} 切换页面",
            bg=UI["side"],
            fg=UI["faint"],
            font=F(8),
        ).pack(side="bottom", anchor="w", padx=px(20), pady=px(14))

    def _build_topbar(self, main) -> None:
        bar = tk.Frame(main, bg=UI["card"], height=px(68))
        bar.pack(fill="x")
        bar.pack_propagate(False)
        left = tk.Frame(bar, bg=UI["card"])
        left.pack(side="left", padx=px(22))
        self.page_title = tk.Label(left, text="", bg=UI["card"], fg=UI["text"], font=F(15, True))
        self.page_title.pack(anchor="w", pady=(px(10), 0))
        self.page_sub = tk.Label(left, text="", bg=UI["card"], fg=UI["mute"], font=F(8))
        self.page_sub.pack(anchor="w")
        right = tk.Frame(bar, bg=UI["card"])
        right.pack(side="right", padx=px(16))
        self.stop_btn = ui_button(right, "■ 停止", self.stop_warmup, "red", width=8, state="disabled")
        self.stop_btn.pack(side="right", padx=(px(6), 0))
        self.pause_btn = ui_button(right, "暂停", self.toggle_pause, "amber", width=7, state="disabled")
        self.pause_btn.pack(side="right", padx=px(6))
        self.start_btn = ui_button(right, "", self.start_warmup, "good", width=16)
        self.start_btn.pack(side="right", padx=px(6))
        prog = tk.Frame(right, bg=UI["card"])
        prog.pack(side="right", padx=(0, px(18)))
        self.mode_chip = tk.Label(
            prog, textvariable=self.mode_var, bg=UI["card"], fg=UI["amber"], font=F(8), cursor="hand2"
        )
        self.mode_chip.pack(anchor="e")
        self.mode_chip.bind("<Button-1>", lambda _e: self.show_page("accounts"))
        self.progress_bar = ttk.Progressbar(prog, mode="determinate", length=px(200))
        self.progress_bar.pack(pady=(px(3), px(1)))
        tk.Label(prog, textvariable=self.progress_var, bg=UI["card"], fg=UI["blue"], font=F(8)).pack(
            anchor="e"
        )

    def _build_statusbar(self, root) -> None:
        bar = tk.Frame(root, bg=UI["side"], height=px(26))
        bar.pack(side="bottom", fill="x")
        bar.pack_propagate(False)
        self.bit_dot = tk.Label(bar, text="●", bg=UI["side"], fg=UI["amber"], font=F(9))
        self.bit_dot.pack(side="left", padx=(px(14), px(4)))
        self.bit_label = tk.Label(bar, text="", bg=UI["side"], fg=UI["mute"], font=F(8), cursor="hand2")
        self.bit_label.pack(side="left")
        self.bit_label.bind("<Button-1>", lambda _e: self.load_browsers())
        self.status_var = tk.StringVar(value="")
        tk.Label(bar, textvariable=self.status_var, bg=UI["side"], fg=UI["mute"], font=F(8)).pack(
            side="left", padx=px(24)
        )
        tk.Label(bar, text=f"数据目录：{DATA_DIR}", bg=UI["side"], fg=UI["faint"], font=F(8)).pack(
            side="right", padx=px(14)
        )

    # ============================================================
    # 页面切换与刷新
    # ============================================================
    def show_page(self, key: str) -> None:
        if key not in self.pages:
            key = "dash"
        self.page_name = key
        page = self.pages[key]
        page.frame.tkraise()
        for name, item in self.nav_items.items():
            on = name == key
            item.configure(
                bg=UI["card2"] if on else UI["side"], fg=UI["blue"] if on else UI["mute"], font=F(11, on)
            )
        self.page_title.configure(text=page.title)
        self.page_sub.configure(text=page.subtitle)
        try:
            page.on_show()
        except Exception:
            logger.warning("刷新页面失败：%s", key, exc_info=True)
        self.refresh_badges()

    def refresh_all(self) -> None:
        self.refresh_badges()
        try:
            self.pages[self.page_name].refresh(force=True)
        except Exception:
            logger.warning("刷新页面失败：%s", self.page_name, exc_info=True)

    def _auto_refresh(self) -> None:
        if self.closing:
            return
        try:
            self.refresh_badges()
            page = self.pages.get(self.page_name)
            if page is not None and page.auto_refresh:
                page.refresh()
        except Exception:
            logger.debug("定时刷新失败", exc_info=True)
        self.root.after(3000, self._auto_refresh)

    def refresh_badges(self) -> None:
        pending = sum(self.store.pending_counts().values())
        fresh = self.store.inbox_new_count()
        running = len(self.ctl.active_ids())
        badges = {"inbox": fresh, "accounts": running}
        for cls in PAGE_CLASSES:
            count = badges.get(cls.key, 0)
            extra = f"  ({count})" if count else ""
            self.nav_items[cls.key].configure(text=f"  {cls.icon}   {cls.title}{extra}")
        parts = [f"运行中账号 {running}", f"待发回复 {pending}", f"未处理消息 {fresh}"]
        if self.post_schedule is not None and self.post_schedule.get("next") is not None:
            parts.append(f"定时发推 {self.post_schedule['next']:%m-%d %H:%M:%S}")
        self.status_var.set("　｜　".join(parts))
        state, text = self.bit_state
        self.bit_dot.configure(fg={"ok": UI["green"], "bad": UI["red"]}.get(state, UI["amber"]))
        self.bit_label.configure(text=text)

    # ============================================================
    # 线程 → 界面
    # ============================================================
    def ui_dispatch(self, fn: Callable[[], None]) -> None:
        self.ui_queue.put(fn)

    def _poll_ui(self) -> None:
        for _ in range(50):
            try:
                fn = self.ui_queue.get_nowait()
                fn()
            except queue.Empty:
                break
            except Exception:
                logger.exception("处理界面更新失败")
        self._flush_logs()
        self.root.after(80, self._poll_ui)

    def log(self, text: str) -> None:
        logger.info(text)
        try:
            self.log_queue.put_nowait(f"[{time.strftime('%H:%M:%S')}] {text}")
        except queue.Full:
            self.dropped_logs += 1  # 完整日志仍在磁盘，只丢弃界面展示副本

    def _flush_logs(self) -> None:
        lines: List[str] = []
        while len(lines) < 300:
            try:
                lines.append(self.log_queue.get_nowait())
            except queue.Empty:
                break
        if not lines:
            return
        if self.dropped_logs:
            lines.append(f"[提示] 界面省略了 {self.dropped_logs} 条日志，完整内容请查看 logs/warmup.log。")
            self.dropped_logs = 0
        self.log_lines.extend(lines)
        self.pages["logs"].append(lines)

    def set_status(self, bid: str, text: str, tone: str = "info") -> None:
        def update():
            self.status_map[bid] = (text, tone)
            self.pages["accounts"].update_status(bid, text, tone)

        self.ui_dispatch(update)

    # ============================================================
    # 账号与配置
    # ============================================================
    def load_browsers(self) -> None:
        if self.loading_browsers or self.closing:
            return
        self.loading_browsers = True
        self.bit_state = ("checking", "正在读取比特浏览器环境…")
        self.refresh_badges()

        def worker():
            try:
                items = self.ctl.bit.list_browsers()

                def apply():
                    self.raw_browsers = items
                    self.bit_state = ("ok", f"比特接口已连接 · {len(items)} 个环境（点此刷新）")
                    self.pages["accounts"].set_browsers(items)
                    self.refresh_badges()

                self.ui_dispatch(apply)
                self.log(f"已同步比特浏览器: 发现 {len(items)} 个独立环境配置。")
            except Exception as exc:
                self.ui_dispatch(lambda: setattr(self, "bit_state", ("bad", "比特接口未连接（点此重试）")))
                self.log(f"获取比特列表异常: {exc}, 请检查比特后台开放接口服务。")
            finally:
                self.ctl.bit.close_thread_session()
                self.ui_dispatch(lambda: setattr(self, "loading_browsers", False))
                self.ui_dispatch(self.refresh_badges)

        threading.Thread(target=worker, name="load-browsers", daemon=True).start()

    def refresh_done_today(self) -> None:
        def worker():
            done = HistoryStore.done_today()

            def apply():
                self.done_today = done
                self.pages["accounts"].render_table()

            self.ui_dispatch(apply)

        threading.Thread(target=worker, name="done-today", daemon=True).start()

    def account_names(self) -> Dict[str, str]:
        names = {browser_id(it): browser_name(it) for it in self.raw_browsers if browser_id(it)}
        try:
            for acc, name in self.store.known_accounts().items():
                names.setdefault(acc, name)
        except Exception:
            logger.debug("读取账号名失败", exc_info=True)
        return names

    def sync_run_settings(self) -> None:
        run = self.settings.run
        run["duration"] = self.duration_var.get().strip()
        run["concurrency"] = self.concurrency_var.get().strip()
        run.update({key: var.get() for key, var in self.run_flags.items()})
        run["window_layout"] = "tile" if self.window_layout_var.get() == "整齐平铺" else "cascade"
        run["page"] = self.page_name or "dash"
        run["group"] = self.pages["accounts"].current_group()
        self.settings.selected = sorted(self.selected_ids)

    def save_config(self) -> None:
        self.sync_run_settings()
        self.settings.save()

    def try_save(self, what: str = "配置") -> bool:
        try:
            self.save_config()
            return True
        except Exception as exc:
            self.log(f"{what}保存失败：{exc}")
            return False

    def set_mode(self, mode: str) -> bool:
        """切换运行模式（阅读 / 阅读+评论 / 发推）；失败时提示原因并保持原模式。"""
        if mode == self.settings.mode:
            return True
        if self.post_schedule is not None:
            messagebox.showinfo("定时已启用", "请先点击停止，再切换运行模式。")
            return False
        old = (self.settings.draft, self.settings.comment)
        try:
            self.settings.set_mode(mode)
            self.save_config()
        except Exception as exc:
            self.settings.draft, self.settings.comment = old
            if messagebox.askyesno("无法切换模式", f"{exc}\n\n现在去设置页选择文件？"):
                self.pages["settings"].select_tab("post" if mode == "post" else "comment")
                self.show_page("settings")
            return False
        self.log(f"运行模式已切换为「{MODE_LABEL[mode]}」，下一批生效。")
        self.update_mode_ui()
        return True

    def update_mode_ui(self) -> None:
        mode = self.settings.mode
        self.mode_var.set(MODE_HINT[mode] + "  ›")
        if not (self.task_thread and self.task_thread.is_alive()) and self.post_schedule is None:
            self.start_btn.configure(text=MODE_START[mode])
        self.pages["accounts"].update_mode(mode)

    def arrange_browser_windows(self) -> None:
        mode = "tile" if self.window_layout_var.get() == "整齐平铺" else "cascade"
        # 主线程重新取工作区，避免清空缓存后让工作线程意外创建 Tk。
        area = getattr(get_work_area, "__wrapped__", get_work_area)()
        count, effective = self.ctl.window_order.request(mode, area)
        self.try_save("窗口偏好")
        text = "有序堆叠" if effective == "cascade" else "整齐平铺"
        self.log(
            f"窗口整理：{text}，已登记 {count} 个本轮窗口，固定槽位顺序。"
            + (" 屏幕空间不足，已自动改用堆叠。" if mode != effective else "")
        )

    @property
    def running(self) -> bool:
        return bool(self.task_thread and self.task_thread.is_alive())

    # ============================================================
    # 批次控制
    # ============================================================
    def _set_controls(self, state: str) -> None:
        """idle / running / stopping / scheduled"""
        self.start_btn.configure(state="normal" if state == "idle" else "disabled")
        self.pause_btn.configure(state="normal" if state == "running" else "disabled")
        if state != "running":
            self.pause_btn.configure(text="暂停")
        self.stop_btn.configure(
            state="normal" if state in ("running", "scheduled") else "disabled",
            text={"stopping": "停止中...", "scheduled": "停止定时"}.get(state, "■ 停止"),
        )
        self.pages["accounts"].set_queue_buttons(state == "running")
        if state == "idle":
            self.start_btn.configure(text=MODE_START[self.settings.mode])

    def start_warmup(self, scheduled_payload=None) -> bool:
        if self.closing:
            return False
        if scheduled_payload is None and self.post_schedule is not None:
            messagebox.showinfo("定时已启用", "请先点击停止，再修改或启动另一批任务。")
            return False
        if self.running:
            messagebox.showinfo("提示", "上一轮任务正在退出或执行中，请稍候。")
            return False
        unresolved = self.ctl.active_ids()
        if unresolved:
            self.ctl.request_stop()
            messagebox.showwarning(
                "上批窗口尚未清理",
                "已保留未确认窗口并在后台重试关闭，请稍后再开始。\n"
                + "、".join(bid[:8] for bid in unresolved),
            )
            return False
        if scheduled_payload is not None:
            targets = [dict(it) for it in scheduled_payload[1]]
        else:
            targets = [it for it in self.raw_browsers if browser_id(it) in self.selected_ids]
        if not targets:
            messagebox.showwarning("提示", "请先在「账号与任务」页勾选要执行的账号！")
            self.show_page("accounts")
            return False

        if scheduled_payload is None and self.run_flags["skip_done"].get() and self.settings.mode == "read":
            done = HistoryStore.done_today()
            skipped = [it for it in targets if browser_id(it) in done]
            targets = [it for it in targets if browser_id(it) not in done]
            if skipped:
                self.log(f"已自动跳过今日已完成的账号 {len(skipped)} 个。")
            if not targets:
                messagebox.showinfo("提示", "选中的账号今日均已完成养号。")
                return False

        try:
            if scheduled_payload is not None:
                cfg = scheduled_payload[0]
            else:
                self.sync_run_settings()
                cfg = self.settings.build_config()
            if cfg.keyword_file and not cfg.draft_enabled:
                self.log(
                    f"关键词TXT：已读取 {len(cfg.interest_terms)} 项，本批固定使用这次快照；下一批重新读取。"
                )
            if scheduled_payload is None and cfg.draft_enabled and cfg.draft_schedule_mode != "immediate":
                load_draft_lines(cfg.draft_file)
                self.save_config()
                self.arm_post_schedule(cfg, targets)
                return True
            if cfg.recent_action_batch:
                ledger=RecentInteractionStore(self.store);ledger.recover()
                if cfg.recent_action_per_post:
                    ledger.create_batch(cfg.recent_action_batch,[browser_id(it) for it in targets],cfg.recent_action_targets,dict(cfg.recent_action_limits))
                    self._recent_goal_batch=cfg.recent_action_batch
            if cfg.draft_enabled:
                self.ctl.draft_rows = load_draft_lines(cfg.draft_file)
                DraftStore().recover()
                self.log(
                    f"TXT 发布模式：载入 {len(self.ctl.draft_rows)} 条，单号最多 {cfg.draft_count} 条，"
                    f"间隔 {cfg.draft_interval:g} 秒；受单号总时长约束。"
                )
            if cfg.comment_enabled and not cfg.draft_enabled:
                self.ctl.comment_rows = load_draft_lines(cfg.comment_file)
                CommentStore().recover()
                self.log(
                    f"TXT 自动评论：载入 {len(self.ctl.comment_rows)} 条；每账号每批最多尝试 "
                    f"{cfg.comment_count} 条，间隔 {cfg.comment_interval:g} 秒。"
                )
            self.save_config()
            BatchStore.begin(targets)
        except Exception as exc:
            messagebox.showerror("无法开始", f"请检查参数或数据目录权限：{exc}")
            return False
        self._launch_batch(cfg, targets)
        return True

    def _launch_batch(self, cfg: WarmupConfig, targets: List[Dict[str, Any]]) -> None:
        self.batch_results.clear()
        self.batch_total, self.batch_finished = len(targets), 0
        self.progress_var.set(f"已结束 0/{len(targets)}")
        self.progress_bar.configure(maximum=len(targets), value=0)
        if cfg.reading_model=='v11_1' and not cfg.draft_enabled and not cfg.service_mode:
            targets=order_by_collection_age(targets,get_store().latest_collection_times(),cfg.random_order)
            self.log('V11.1启动顺序：未采集优先，其余最后成功采集时间从旧到新；仅同时间随机。')
        elif cfg.random_order:
            random.shuffle(targets)
            self.log(f"🔀 已开启「随机顺序启动」: 选中的 {len(targets)} 个账号启动顺序已打乱。")
        else:
            self.log(f"⏸ 按表格默认次序启动 {len(targets)} 个账号。")
        self.stopping = False
        self.ctl.reset(min(cfg.concurrency, len(targets)), window_layout=cfg.window_layout)
        self._set_controls("running")
        self.ctl.set_pending([browser_id(it) for it in targets])
        for it in targets:
            self.set_status(browser_id(it), "排队中", "info")
        runner = BatchRunner(
            self.ctl,
            cfg,
            targets,
            self.log,
            on_result=lambda bid, result: self.ui_dispatch(lambda: self.update_batch_progress(bid, result)),
            on_finished=lambda: self.ui_dispatch(self.reset_ui),
        )
        self.task_thread = runner.start()
        self.refresh_badges()


    def start_recent_actions(self,actors,targets,limits,interval,comment_interval,comment_file,settings):
        if self.running or self.post_schedule is not None:
            messagebox.showinfo('任务正在执行','请先等待当前任务结束或停止定时计划。');return False
        # 字符串仅兼容上一版的单账号调用；新界面传入固定的执行账号ID快照。
        actor_ids=(actors,) if isinstance(actors,str) else tuple(actors)
        execution=recent_execution_accounts(self.raw_browsers,'仅账号页勾选',actor_ids)
        from xmanager_planning import build_plan
        plan = build_plan(tuple(browser_id(it) for it in execution), targets, limits, interval, comment_interval)
        actors, targets = plan.actors, plan.targets
        self.sync_run_settings()
        actor_rows,_=self.store.recent_performance()
        wanted={browser_id(it) for it in execution}
        handles=tuple((r['account'],r['handle']) for r in actor_rows if r['account'] in wanted and r['handle'])
        base=self.settings.build_service_config()
        cfg=dataclasses.replace(base,performance_only=False,stats_enabled=False,stats_recent_enabled=False,
            stats_mentions=False,stats_dm=False,duration_min=0,concurrency=min(base.concurrency,len(execution)),enable_like=bool(limits['like']),max_likes=len(targets) if limits['like'] else 0,
            comment_enabled=bool(limits['comment']),comment_file=comment_file,comment_count=max(1,len(targets)) if limits['comment'] else 1,comment_interval=comment_interval,
            recent_action_batch=uuid.uuid4().hex,recent_action_targets=tuple(targets),recent_action_limits=tuple(limits.items()),
            recent_action_interval=interval,recent_action_per_post=True,recent_actor_handle='',recent_actor_handles=handles)
        self.settings.recent_actions=dict(settings)
        self.log(f"榜单互动：{len(targets)}条帖子，每帖目标点赞{limits['like']}、转发{limits['repost']}、评论{limits['comment']}；独立执行池{len(execution)}个，并发{cfg.concurrency}窗。")
        self.log(f"本批逐帖目标合计：点赞{len(targets)*limits['like']}，转发{len(targets)*limits['repost']}，评论{len(targets)*limits['comment']}；已确认的同账号同帖操作计入目标，不会重复。")
        if max(limits.values())>len(execution):self.log('执行账号不足以完成部分逐帖数量，报告将显示缺额；不会使用执行池外的账号补量。')
        self.log('评论继续全局去重：同一目标仅一个账号可提交；其他账号跳过该目标。点赞和转发按执行账号分别去重。')
        self.log('目标ID：'+', '.join(t[0] for t in targets))
        return self.start_warmup((cfg,execution))

    def start_recent_sync(self,ids):
        if self.running or self.post_schedule is not None:
            messagebox.showinfo('任务正在执行','请先等待当前批次结束，或停止定时计划后再同步。');return
        wanted={str(i) for i in ids if not str(i).startswith(AccountDataStore.DEMO_PREFIX)} & set(self.selected_ids)
        targets=[it for it in self.raw_browsers if browser_id(it) in wanted]
        if not targets:
            messagebox.showinfo('没有账号','请先在「账号与任务」页勾选需要统计的账号；不会同步未勾选账号。');return
        try:
            self.sync_run_settings()
            cfg=dataclasses.replace(self.settings.build_service_config(),performance_only=True,stats_recent_enabled=True,
                                    stats_mentions=False,stats_dm=False,enable_like=False,comment_enabled=False,draft_enabled=False)
        except (ValueError,TypeError) as exc:
            messagebox.showerror('参数有误',str(exc));return
        self.log(f'=== 最近8小时统计：{len(targets)}个账号；只读本人帖子与回复，不发送面板排队内容 ===')
        self.start_warmup((cfg,targets))

    def start_service_run(self, ids, label: str = "数据同步") -> None:
        """立即同步：只采集数据 + 发送面板里排队的回复，不跑阅读工作流。"""
        real = [str(i) for i in ids if not str(i).startswith(AccountDataStore.DEMO_PREFIX)]
        if not real:
            messagebox.showinfo("提示", "选中的是演示数据，不能同步。请选真实账号。")
            return
        if self.post_schedule is not None:
            messagebox.showinfo("定时发推已启用", "请先点击停止，再进行同步。")
            return
        if self.running:
            messagebox.showinfo("提示", "上一轮任务正在执行或退出中，请稍候。")
            return
        wanted = set(real)
        targets = [it for it in self.raw_browsers if browser_id(it) in wanted]
        if not targets:
            messagebox.showinfo(
                "提示", "在比特环境列表里找不到这些账号。请到「账号与任务」页点“刷新比特环境”。"
            )
            return
        try:
            self.sync_run_settings()
            cfg = self.settings.build_service_config()
        except (ValueError, TypeError) as exc:
            messagebox.showerror("参数有误", str(exc))
            return
        self.log(f"=== {label}：{len(targets)} 个账号（只读采集 + 发送面板里排队的回复，不跑阅读工作流）===")
        if self.start_warmup((cfg, targets)) and self.page_name != "dash":
            self.show_page("flow")

    def update_batch_progress(self, bid: str, result: Result) -> None:
        self.batch_results[bid] = result
        self.batch_finished += 1
        self.progress_bar.configure(maximum=max(1, self.batch_total), value=self.batch_finished)
        ok = sum(r in SUCCESS_RESULTS for r in self.batch_results.values())
        self.progress_var.set(f"已结束 {self.batch_finished}/{self.batch_total} | 完成 {ok}")
        if result in SUCCESS_RESULTS:
            self.done_today.add(bid)
        try:
            self.refresh_all()
        except Exception:
            logger.debug("批次进度后刷新界面失败", exc_info=True)

    def toggle_pause(self) -> None:
        if self.stopping:
            return
        if self.ctl.pause_event.is_set():
            self.ctl.set_paused(True)
            self.pause_btn.configure(text="继续")
            self.log(">> 任务已暂停 (暂停期间不扣减单号倒计时)。")
        else:
            self.ctl.set_paused(False)
            self.pause_btn.configure(text="暂停")
            self.log(">> 任务恢复运行。")

    def stop_warmup(self) -> None:
        if self.cancel_post_schedule():
            self.log("定时发推计划已取消，后续不会再次自动启动。")
            if not self.running:
                self.reset_ui()
                self.progress_var.set("定时已停止")
                return
        if self.stopping:
            return
        self.stopping = True
        self._set_controls("stopping")
        self.log(
            f">> 正在下发终止信号: 排队账号不再启动; 运行中账号开始退出；"
            f"{STOP_GRACE_SEC:.0f}s 后尝试强制关闭本程序启动的窗口。"
        )
        self.ctl.request_stop()

    def cancel_queue(self, ids: Optional[List[str]]) -> None:
        targets = self.ctl.cancel_queued(ids)
        for bid in targets:
            self.set_status(bid, RESULT_LABEL[Result.CANCELLED], RESULT_TONE[Result.CANCELLED])
        if ids is None:
            self.log(">> 已取消所有待运行账号的排队。")
        else:
            self.log(f">> 已取消 {len(targets)} 个仍在排队的账号。")

    def reset_ui(self) -> None:
        batch=getattr(self,'_recent_goal_batch','')
        if batch:
            self._recent_goal_batch=''
            progress=[r for r in RecentInteractionStore(self.store).progress(batch) if r['goal']]
            complete=sum(r['done']>=r['goal'] for r in progress)
            self.log(f'=== 逐帖目标结束：{complete}/{len(progress)}项达标；待核对不算成功，缺额不自动冒险补发 ===')
            for row in progress:
                self.log(f"帖子 {row['target']} {RECENT_ACTION_NAMES[row['action']]}：已确认{row['done']}/{row['goal']}，待核对{row['unknown']}，缺额{row['missing']}" )
        plan = self.post_schedule
        if plan is not None and plan["cfg"].draft_schedule_mode == "daily":
            if not self.closing and not self.stopping and not self.ctl.is_stopped():
                plan["next"] = next_post_schedule(
                    "daily", "", plan["cfg"].draft_schedule_time, last_date=plan["last_date"]
                )
                self.log(f"本轮发推结束，下次定时：{plan['next']:%Y-%m-%d %H:%M:%S}（本机时间）。")
                self.wait_post_schedule_ui()
                return
            self.cancel_post_schedule()
        self.stopping = False
        self._set_controls("idle")
        try:
            self.refresh_all()
        except Exception:
            logger.debug("任务结束后刷新界面失败", exc_info=True)

    # ---------- 定时发推（按本机时间） ----------
    def cancel_post_schedule(self) -> bool:
        had_schedule = self.post_schedule is not None
        self.post_schedule = None
        if self.post_schedule_after is not None:
            try:
                self.root.after_cancel(self.post_schedule_after)
            except Exception:
                logger.debug("取消定时回调失败", exc_info=True)
            self.post_schedule_after = None
        return had_schedule

    def arm_post_schedule(self, cfg: WarmupConfig, targets) -> None:
        due = next_post_schedule(cfg.draft_schedule_mode, cfg.draft_schedule_date, cfg.draft_schedule_time)
        self.post_schedule = {
            "cfg": cfg,
            "targets": tuple(dict(it) for it in targets),
            "next": due,
            "last_date": None,
        }
        self.stopping = False
        self.log(f"定时发推已启用：{due:%Y-%m-%d %H:%M:%S}（本机时间），账号 {len(targets)} 个。")
        self.wait_post_schedule_ui()

    def wait_post_schedule_ui(self) -> None:
        plan = self.post_schedule
        if plan is None or self.closing:
            return
        if self.post_schedule_after is not None:
            self.root.after_cancel(self.post_schedule_after)
            self.post_schedule_after = None
        self._set_controls("scheduled")
        for it in plan["targets"]:
            self.set_status(browser_id(it), f"等待定时 {plan['next']:%m-%d %H:%M:%S}", "info")
        self.post_schedule_tick()

    def post_schedule_tick(self) -> None:
        self.post_schedule_after = None
        plan = self.post_schedule
        if plan is None or self.closing or plan["next"] is None:
            return
        now = datetime.now()
        due = plan["next"]
        if now < due or self.running:
            seconds = max(0, int((due - now).total_seconds()))
            self.progress_var.set(f"定时 {due:%m-%d %H:%M:%S} | 剩余 {seconds} 秒（本机时间）")
            self.post_schedule_after = self.root.after(1000, self.post_schedule_tick)
            return
        plan["last_date"] = due.date()
        plan["next"] = None
        if plan["cfg"].draft_schedule_mode == "once":
            self.post_schedule = None
        self.log(f"定时时间已到，启动 TXT 发推：{due:%Y-%m-%d %H:%M:%S}（本机时间）。")
        if not self.start_warmup((plan["cfg"], plan["targets"])):
            self.cancel_post_schedule()
            self.reset_ui()

    # ============================================================
    # 退出
    # ============================================================
    def on_close(self) -> None:
        if self.closing:
            return
        if self.running and not messagebox.askyesno(
            "确认退出", "任务仍在运行。退出会停止全部账号并关闭本程序启动的窗口，确定退出？"
        ):
            return
        self.closing = True
        self.cancel_post_schedule()
        self.root.title("正在安全退出，请稍候...")
        self.try_save()
        self.ctl.request_stop()

        def waiter():
            thread = self.task_thread
            if thread and thread.is_alive():
                thread.join(timeout=EXIT_JOIN_SEC)
            for bid in self.ctl.active_ids():
                self.ctl.close_browser(bid, allow_reused=False)
            self.ui_dispatch(self._finalize_exit)

        threading.Thread(target=waiter, name="exit-waiter", daemon=True).start()

    def _finalize_exit(self) -> None:
        try:
            self.root.destroy()
        except Exception:
            pass
        logging.shutdown()
        os._exit(0)


# ======================================================================
# 模块：xmanager/main.py
# ======================================================================
"""程序入口：单实例锁、命令行诊断与启动界面。"""


import argparse
import sys



class SingleInstance:
    def __init__(self):
        self.file = None

    def acquire(self) -> bool:
        self.file = (DATA_DIR / "instance.lock").open("a+b")
        self.file.seek(0, 2)
        if self.file.tell() == 0:
            self.file.write(b"0")
            self.file.flush()
        self.file.seek(0)
        try:
            if sys.platform == "win32":
                import msvcrt

                msvcrt.locking(self.file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(self.file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except OSError:
            self.file.close()
            self.file = None
            return False

    def release(self) -> None:
        if self.file is not None:
            self.file.close()
            self.file = None


def diagnose() -> int:

    print(f"版本: {APP_VERSION} | Python: {sys.version.split()[0]} | 数据目录: {DATA_DIR}")
    client = BitClient(BIT_API)
    try:
        print(f"比特接口正常，环境数量: {len(client.list_browsers())}")
        return 0
    except Exception as exc:
        print(f"接口诊断失败: {exc}")
        return 1
    finally:
        client.close_thread_session()


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=f"{APP_NAME} V{APP_VERSION}")
    parser.add_argument("--diagnose", action="store_true", help="不打开界面，检查数据目录和比特接口")
    args = parser.parse_args(argv)
    setup_runtime()
    if args.diagnose:
        return diagnose()
    instance = SingleInstance()
    if not instance.acquire():
        print("程序已经运行，请切换到现有窗口。")
        return 1
    try:
        import tkinter as tk


        enable_dpi_awareness()
        get_work_area()
        root = tk.Tk()
        WarmupApp(root)
        root.mainloop()
        return 0
    finally:
        instance.release()


if __name__ == "__main__":
    raise SystemExit(main())
