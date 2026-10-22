# -*- coding: utf-8 -*-
"""雷速「完场」页面小测试（只读 1 个页面，不改任何文件，不碰你的推单数据）

用途：看看雷速的「完场」页面里，比分能不能被脚本直接读到。
用法：双击运行；或者在文件夹里打开命令行：  python leisu_probe.py
      想测别的日期：  python leisu_probe.py 20261010

它会做的事（一共只访问 2 次网站：robots.txt 和 1 个完场页）：
  1. 先读网站的 robots.txt，看这个页面允不允许脚本读；不允许就停下，不硬抓。
  2. 如果网站要求两次访问之间隔一段时间，就老老实实等（最多等 3 分钟，屏幕上有倒计时）。
  3. 读 1 个完场页，判断比分在不在页面里。
  4. 把结果写进 leisu_probe_结果.txt，把原页面存成 leisu_probe_页面.html。
     跑完后把这两个文件发给我就行。

只用 Python 自带的库，Python 3.9 以上都能跑。
"""
import gzip
import json
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import urllib.robotparser
from datetime import datetime
from pathlib import Path

__version__ = "1.0"

DEFAULT_DATE = "20261003"
BASE = "https://live.leisu.com/"
# 老实报家门：这是个人小脚本，不假装成浏览器
UA = "personal-results-probe/1.0 (single page, polite; contact: owner)"
MAX_WAIT = 180          # 最多等多少秒（网站要求的间隔再长也只等这么久）
HERE = Path(__file__).resolve().parent
OUT_TXT = HERE / "leisu_probe_结果.txt"
OUT_HTML = HERE / "leisu_probe_页面.html"

# 比分：两边不能紧挨着汉字/字母/数字（免得把「沙尔克04 - 美因茨05」里的数字当成比分）
SCORE_RE = re.compile(r"(?<![\w\u4e00-\u9fff.:])(\d{1,2})\s*[-:：]\s*(\d{1,2})(?![\w\u4e00-\u9fff.:])")
SCORE_ONLY = re.compile(r"^\s*\d{1,2}\s*[-:：]\s*\d{1,2}\s*$")
PLACEHOLDER = ("-", "--", "- -", "—", "－")
DETAIL_RE = re.compile(r"""<a\b[^>]*?href\s*=\s*["']([^"']*?detail-(\d+))["'][^>]*>(.*?)</a>""", re.I | re.S)
# 常见的「数据写在页面脚本里」的标记
EMBED_MARKS = ("__NUXT__", "__INITIAL_STATE__", "__NEXT_DATA__", "window.__", "homeScore",
               "home_score", "\"score\"", "\"hs\"", "homeTeam", "home_team")
BLOCK_WORDS = ("captcha", "验证码", "安全验证", "访问过于频繁", "access denied", "forbidden", "请开启javascript")

LINES = []


def say(msg=""):
    LINES.append(msg)
    try:
        print(msg)
    except UnicodeEncodeError:  # 个别 Windows 命令行不认某些字
        print(msg.encode("gbk", "replace").decode("gbk", "replace"))


def fetch(url, timeout=30):
    """读一个网址，返回 (状态码, 文本, 出错原因)。出错不抛异常。"""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,*/*;q=0.8",
                                               "Accept-Language": "zh-CN,zh;q=0.9"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            raw = r.read()
            code = r.getcode()
            enc = (r.headers.get("Content-Encoding") or "").lower()
            ctype = r.headers.get("Content-Type") or ""
    except urllib.error.HTTPError as e:
        try:
            raw = e.read()
        except Exception:
            raw = b""
        return e.code, raw.decode("utf-8", "replace"), None
    except Exception as e:  # 网络不通、超时等
        return None, "", f"{type(e).__name__}: {e}"
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    for cs in ([m.group(1)] if m else []) + ["utf-8", "gb18030"]:
        try:
            return code, raw.decode(cs), None
        except Exception:
            continue
    return code, raw.decode("utf-8", "replace"), None


def strip_tags(h):
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = h.replace("&nbsp;", " ").replace("&amp;", "&")
    return re.sub(r"\s+", " ", h).strip()


def split_rows(html):
    """按「详情链接」把页面切成一场一场，返回 [(比赛编号, 这一行的 HTML, 链接上的文字列表)]。"""
    rows, seen, texts = [], {}, {}
    for m in DETAIL_RE.finditer(html):
        mid = m.group(2)
        texts.setdefault(mid, []).append(strip_tags(m.group(3)))
        if mid in seen:
            continue
        s = html.rfind("<tr", 0, m.start())
        e = html.find("</tr>", m.end())
        if s != -1 and e != -1 and e - s < 4000:
            seg = html[s:e]
        else:  # 不是表格：取链接前后一小段
            seg = html[max(0, m.start() - 500): m.end() + 300]
        seen[mid] = len(rows)
        rows.append([mid, seg])
    return [(mid, seg, texts[mid]) for mid, seg in rows]


def row_has_score(seg):
    """没有可靠的「比分链接」时的备用办法：在整行文字里找比分（先去掉半场、时间、90分钟备注）。"""
    txt = strip_tags(seg)
    txt = re.sub(r"\d+分钟\[\d+-\d+\][，,]?", " ", txt)
    txt = re.sub(r"半场\s*\d+\s*[-:：]\s*\d+", " ", txt)
    txt = re.sub(r"(?<!\d)\d{1,2}:\d{2}(?!\d)", " ", txt)
    return bool(SCORE_RE.search(txt))


def judge(html):
    """分析页面，返回 (结论代号, 结论文字, 细节列表)。"""
    detail = []
    low = html.lower()
    if len(html) < 3000:
        detail.append(f"页面只有 {len(html)} 个字符，太短，可能不是完整页面。")
    hit_block = [w for w in BLOCK_WORDS if w in low]
    rows = split_rows(html)
    detail.append(f"页面里找到 {len(rows)} 场比赛的详情链接。")
    with_score = 0
    placeholder = 0
    samples = []
    for mid, seg, link_texts in rows:
        if any(SCORE_ONLY.match(t) for t in link_texts):      # 链接本身就是比分，如「2-1」
            with_score += 1
        elif any(t.strip() in PLACEHOLDER for t in link_texts):  # 链接上只有「-」：比分还没出现在页面里
            placeholder += 1
        elif row_has_score(seg):                               # 结构不明：退回整行找
            with_score += 1
        if len(samples) < 3:
            samples.append(strip_tags(seg)[:110])
    detail.append(f"其中有比分数字的：{with_score} 场；比分栏只有「-」的：{placeholder} 场；其余：{len(rows) - with_score - placeholder} 场。")
    marks = [m for m in EMBED_MARKS if m in html]
    scripts_with_data = 0
    for sm in re.finditer(r"<script\b[^>]*>(.*?)</script>", html, flags=re.S | re.I):
        body = sm.group(1)
        if len(body) > 2000 and (SCORE_RE.search(body) or "score" in body.lower()):
            scripts_with_data += 1
    if marks:
        detail.append("页面脚本里出现的数据标记：" + "、".join(marks[:6]))
    detail.append(f"带大段数据的脚本块：{scripts_with_data} 个。")
    for i, s in enumerate(samples, 1):
        detail.append(f"样例行 {i}：{s}")

    if hit_block and not rows:
        return "D", "页面像是验证页/拦截页（出现：" + "、".join(hit_block[:3]) + "），不要硬抓。", detail
    if not rows:
        return "C", "页面里一场比赛都没找到，可能整页是后加载的，脚本直接读不到。", detail
    if with_score >= max(3, int(len(rows) * 0.6)):
        return "A", "比分直接写在页面里，脚本可以读到。", detail
    if with_score == 0 and scripts_with_data:
        return "B", "页面表格里没有比分，但页面脚本里带着大段数据，比分可能藏在里面（要再研究一步）。", detail
    if with_score == 0:
        return "C", "比赛名单能读到，但比分是后加载的（页面里没有），脚本直接读不到。", detail
    return "E", f"只有部分比赛有比分（{with_score}/{len(rows)}），需要看原页面才能判断。", detail


def main(argv):
    url = None
    wait_override = None
    date = DEFAULT_DATE
    args = list(argv)
    while args:
        a = args.pop(0)
        if a == "--url" and args:           # 测试用：换成别的网址
            url = args.pop(0)
        elif a == "--wait" and args:        # 测试用：覆盖等待秒数
            wait_override = float(args.pop(0))
        elif re.fullmatch(r"\d{8}", a):
            date = a
    if url is None:
        url = f"{BASE}wanchang-{date}"
    pu = urllib.parse.urlparse(url)
    robots_url = f"{pu.scheme}://{pu.netloc}/robots.txt"

    say(f"雷速完场页面小测试 v{__version__}  {datetime.now():%Y-%m-%d %H:%M:%S}")
    say(f"要读的页面：{url}")
    say("")

    # 1) robots.txt
    say("① 先看网站的 robots.txt（网站对脚本的规矩）……")
    code, text, err = fetch(robots_url)
    rp = urllib.robotparser.RobotFileParser()
    delay = None
    if err or code is None:
        say(f"   读不到 robots.txt（{err}）。网络不通的话，下面也读不到。")
        rp = None
    elif code != 200:
        say(f"   robots.txt 返回状态 {code}（没有这个文件通常表示没有限制）。")
        rp = None
    else:
        rp.parse(text.splitlines())
        delay = rp.crawl_delay(UA)
        if delay is None:
            delay = rp.crawl_delay("*")
        say(f"   读到了。网站要求的访问间隔：{delay if delay else '没写'} 秒。")
        banned = [ln.split(":", 1)[1].strip() for ln in text.splitlines()
                  if ln.lower().startswith("user-agent:")]
        if banned:
            say(f"   里面点名的爬虫共 {len(banned)} 个（这个脚本不在其中也要守规矩）。")
    if rp is not None and not rp.can_fetch(UA, url):
        say("   ✖ robots.txt 不允许读这个页面。按规矩到此为止，不继续。")
        finish("R", "网站的 robots.txt 不允许脚本读这个页面，所以不要抓它。", [])
        return

    # 2) 等待
    wait = wait_override if wait_override is not None else min(float(delay or 0), MAX_WAIT)
    if wait > 0:
        say(f"② 按网站的要求，先等 {int(wait)} 秒再读页面（别关窗口，屏幕上会倒计时）……")
        left = int(wait)
        while left > 0:
            try:
                print(f"\r   还剩 {left:>3} 秒   ", end="", flush=True)
            except Exception:
                pass
            time.sleep(1)
            left -= 1
        print("\r" + " " * 30 + "\r", end="")
    else:
        say("② 网站没要求等待，直接读页面。")

    # 3) 读页面
    say("③ 读页面……")
    code, html, err = fetch(url)
    if err or code is None:
        say(f"   ✖ 读不到：{err}")
        finish("N", "网络没通或超时，没读到页面。检查网络后再运行一次。", [])
        return
    say(f"   状态码 {code}，共 {len(html)} 个字符。")
    try:
        OUT_HTML.write_text(html, "utf-8")
        say(f"   原页面已存：{OUT_HTML.name}")
    except Exception as e:
        say(f"   （原页面没存下来：{e}）")
    if code != 200:
        finish("D", f"网站返回了状态 {code}，不是正常页面（多半是拒绝脚本访问）。不要硬抓，也不要换花样绕过。", [])
        return
    verdict, text_v, detail = judge(html)
    finish(verdict, text_v, detail)


def finish(code, text, detail):
    say("")
    say("—— 结论 ——")
    say(f"[{code}] {text}")
    for d in detail:
        say("  · " + d)
    advice = {
        "A": "下一步：我可以把它写进脚本，每天只读 1 页，并守网站的间隔。",
        "B": "下一步：把 leisu_probe_页面.html 发给我，我看看数据藏在哪、怎么读。",
        "C": "下一步：比分读不到，这条路暂时不通。我建议改走 500 网自己的完场页（队名和现在的一致）。",
        "D": "下一步：网站不让脚本读，就不用它了，改走 500 网的完场页。",
        "R": "下一步：网站不让脚本读，就不用它了，改走 500 网的完场页。",
        "N": "下一步：检查网络（能不能用浏览器打开雷速），再运行一次。",
        "E": "下一步：把 leisu_probe_页面.html 发给我看看。",
    }.get(code, "")
    if advice:
        say(advice)
    say("")
    say("把 leisu_probe_结果.txt 和 leisu_probe_页面.html 两个文件发给我就行。")
    try:
        OUT_TXT.write_text("\n".join(LINES) + "\n", "utf-8")
    except Exception as e:
        print("（结果文件没存下来：%s）" % e)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n已手动停止。")
    except Exception as e:  # 不让窗口一闪而过
        import traceback
        traceback.print_exc()
        print("\n出错了：", e)
    if sys.stdin is not None and sys.stdin.isatty() and "--url" not in sys.argv:
        try:
            input("\n按回车键关闭窗口……")
        except Exception:
            pass
