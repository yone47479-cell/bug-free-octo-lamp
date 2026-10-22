# 推单脚本：操作台重构与 UI 优化版

基于用户提供的 v3.1.4 完整版，拆分界面与配置逻辑，优化桌面操作布局与配置容错。

## 下载与启动

[点击下载完整优化版 ZIP](https://github.com/yone47479-cell/bug-free-octo-lamp/raw/refs/heads/main/downloads/tips-console-ui.zip)

下载后解压，双击「启动操作台.bat」。需要安装包含 tkinter 的 Python 3。
已有用户升级前请备份设置和数据库；新增的 console_ui.py、console_config.py 需要与操作台一起更新。

也可以点击仓库页面绿色的 Code → Download ZIP 下载项目源码。

## 改动与验证

- 将字体、主题、主窗口布局拆到 console_ui.py。
- 配置读取拆到 console_config.py，增加损坏配置和错误字段的容错。
- 优化顶部工具栏、按钮分组与中文字体匹配，增加 Alt+1～7 页面切换。
- 原有测试和新增回归共 140 项通过，包含 Linux 虚拟显示器中的真实 Tk 窗口检查。
- 外部站点实时采集、Windows 计划任务与浏览器出图尚未端到端验证。

详情见 [重构与界面优化说明](说明/重构与界面优化说明.md)。

测试命令：`python -m unittest discover -s 验证 -v`。无图形桌面时窗口测试会明确跳过。
