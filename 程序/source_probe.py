# -*- coding: utf-8 -*-
"""赔率/排名类网页小测试（只读 3 个页面，不改任何文件，不碰你的推单数据）

用途：500 网的竞足表里没有赔率，现在只能借北单的 SP 当参考。下面两个网站的公开页面上有「竞彩 SP / 多家公司赔率」，
这是比近况更硬的参考数据：
  · 澳客 okooo.cn 的竞彩赛程页（赛事编号、竞彩指数）和凯利方差页（各公司初始/最新指数、凯利、离散度）
  · 足彩网 zgzcw.com 的竞彩足球页（联赛排名[8]、竞彩 SP、一列“平均值”）——上一次在你这边读超时了，这次多等一会儿并自动重试
我没法在我这边拿到这些页面的原始网页，盲写解析器容易写错，所以先用这个小程序把页面存下来，我照着真实结构写。

用法：双击运行；或者在文件夹里打开命令行：  python source_probe.py
它会做的事：
  1. 先读每个网站的 robots.txt，只读它允许的页面、也只在它规定的访问时间段里读（不允许的跳过并写明）；
  2. 一共读 3 个页面，页面之间隔 5 秒；读超时会自动重试，被拒绝（403 等）就不再试、也不绕；
  3. 数一数页面里有多少场比赛、认不认得出排名/赔率，把结果写进 source_probe_结果.txt，原页面存成 source_probe_*.html。
跑完后把这几个文件发给我就行。只用 Python 自带的库，Python 3.9 以上都能跑。
"""
import gzip
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

__version__ = "1.2"

GAP = 5.0                                   # 两次读页面之间隔几秒
PAGE_TIMEOUT = 60                           # 读一个页面最多等几秒（上一版 25 秒，在你的网络上读超时了）
TRIES = 3                                   # 读超时（没回应）时最多试几次
TRY_WAIT = 10.0                             # 两次重试之间隔几秒
HERE = Path(__file__).resolve().parent
OUT_TXT = HERE / "source_probe_结果.txt"
PAGES = [
    ("澳客竞彩赛程页", "https://www.okooo.cn/jingcai/", "source_probe_澳客竞彩页.html"),
    ("澳客凯利方差页", "https://www.okooo.cn/jingcai/shuju/peilv/", "source_probe_澳客凯利页.html"),
    ("足彩网竞彩足球页", "https://cp.zgzcw.com/lottery/jchtplayvsForJsp.action?lotteryId=47&type=jcmini", "source_probe_足彩网竞彩页.html"),
]

try:                                         # 和你的抓取脚本用同一个浏览器标识
    sys.path.insert(0, str(HERE))
    from export_500_all import USER_AGENT as UA   # type: ignore
except Exception:
    UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
          "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

LINES = []


def say(msg=""):
    LINES.append(msg)
    try:
        print(msg)
    except UnicodeEncodeError:
        print(msg.encode("gbk", "replace").decode("gbk", "replace"))


# ---------------------------------------------------------------- 读网页
def fetch(url, timeout=25):
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
    except Exception as e:
        return None, "", f"{type(e).__name__}: {e}"
    if "gzip" in enc:
        try:
            raw = gzip.decompress(raw)
        except Exception:
            pass
    m = re.search(r"charset=([\w-]+)", ctype, re.I)
    head = raw[:3000].decode("ascii", "ignore")
    m2 = re.search(r"charset\s*=\s*[\"']?([\w-]+)", head, re.I)
    for cs in ([m.group(1)] if m else []) + ([m2.group(1)] if m2 else []) + ["utf-8", "gb18030"]:
        try:
            return code, raw.decode(cs), None
        except Exception:
            continue
    return code, raw.decode("utf-8", "replace"), None


def fetch_retry(url, timeout=None, tries=None, wait=None):
    """读页面：只有「超时没回应」才重试（网站慢/网络慢），最多 tries 次，每次间隔 wait 秒；
    被拒绝（403/429 等）不重试、也不绕——那就是网站不让读，算了。返回 (状态码, 文本, 错误说明)。"""
    timeout = timeout or PAGE_TIMEOUT
    tries = tries or TRIES
    wait = TRY_WAIT if wait is None else wait
    code, text, err = None, "", "没试"
    for k in range(1, tries + 1):
        t0 = time.time()
        code, text, err = fetch(url, timeout)
        used = time.time() - t0
        if not err and code == 200:
            say(f"  第 {k} 次读到了（用了 {used:.1f} 秒）")
            return code, text, None
        say(f"  第 {k} 次没读成：{err or code}（等了 {used:.1f} 秒）")
        is_timeout = bool(err) and ("timed out" in err.lower() or "timeout" in err.lower())
        if not is_timeout:
            break                                           # 不是超时（比如被拒绝）→ 不重试
        if k < tries:
            say(f"  隔 {wait:g} 秒再试一次……")
            time.sleep(wait)
    return code, text, err


# ---------------------------------------------------------------- robots（支持 * 和 $ 通配，最长匹配优先）
def parse_robots(text):
    """返回 * 这一组的规则 [(allow?, 规则文字)]。没有单独写 User-agent 的后续行并入上一组。"""
    groups, cur, started = {}, [], False
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        if ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if started:
                cur, started = [], False
            cur.append(v.lower())
            for a in cur:
                groups.setdefault(a, [])
        elif k in ("disallow", "allow"):
            started = True
            for a in cur or ["*"]:
                groups.setdefault(a, []).append((k == "allow", v))
        else:
            started = True
    return groups.get("*", [])


def _rule_re(rule):
    pat = re.escape(rule).replace(r"\*", ".*")
    if pat.endswith(r"\$"):
        pat = pat[:-2] + "$"
    return re.compile("^" + pat)


def robots_allows(rules, path_and_query):
    best_len, allowed = -1, True
    for allow, rule in rules:
        if rule == "":
            continue
        if _rule_re(rule).match(path_and_query):
            if len(rule) > best_len or (len(rule) == best_len and allow):
                best_len, allowed = len(rule), allow
    return allowed


# ---------------------------------------------------------------- 分析页面
def clean(h):
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", " ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", h).strip()


VISIT = {}                                  # 网站 → robots.txt 里的 Visit-time 段（UTC，如 "0130-1830"）


def robots_for(host_url):
    """读某个站的 robots.txt → 规则。读不到(网络问题)返回 None；404 当作没有限制。"""
    u = urllib.parse.urlsplit(host_url)
    code, text, err = fetch(f"{u.scheme}://{u.netloc}/robots.txt")
    if err:
        return None
    if code == 404:
        return []
    if code != 200:
        return None
    m = re.search(r"(?im)^\s*visit-time\s*:\s*(\d{4})\s*-\s*(\d{4})", text)
    if m:
        VISIT[u.netloc] = (m.group(1), m.group(2))
    return parse_robots(text)


def in_visit_time(win, now=None):
    """Visit-time（UTC，HHMM-HHMM）：现在在不在允许的时间段里。段跨午夜也支持。"""
    now = now or time.gmtime()
    cur = now.tm_hour * 100 + now.tm_min
    a, b = int(win[0]), int(win[1])
    return (a <= cur <= b) if a <= b else (cur >= a or cur <= b)


def allowed(url, cache):
    u = urllib.parse.urlsplit(url)
    key = u.netloc
    if key not in cache:
        cache[key] = robots_for(url)
        time.sleep(1.5)
    rules = cache[key]
    if rules is None:
        return False, "读不到 robots.txt，保守起见不读"
    pq = u.path + (("?" + u.query) if u.query else "")
    if not robots_allows(rules, pq):
        return False, "robots 不允许"
    win = VISIT.get(key)
    if win and not in_visit_time(win):
        return False, f"robots 的 Visit-time 只让在 UTC {win[0]}-{win[1]} 访问，现在不在这个时间段，先不读（换个时间再运行）"
    return True, "robots 允许" + (f"（访问时间段 UTC {win[0]}-{win[1]}，现在在段内）" if win else "")


def summarize(name, html):
    say(f"  页面大小 {len(html)} 字符")
    codes = re.findall(r"周[一二三四五六日]\d{3}", html)
    say(f"  比赛编号（周五001 这种）：{len(set(codes))} 个，例：{', '.join(sorted(set(codes))[:5])}")
    ranks = re.findall(r"[\[【(]\s*\d{1,2}\s*[\]】)]", html)
    say(f"  形如 [8] 的联赛排名标记：{len(ranks)} 处")
    nums = re.findall(r"\b\d\.\d{2}\b", clean(html))
    say(f"  形如 2.06 的赔率数字：{len(nums)} 个")
    links = sorted(set(re.findall(r"https?://saishi\.zgzcw\.com/soccer/(?:league|team)/[\d/]+", html)))
    say(f"  联赛/球队页链接：{len(links)} 个，例：{', '.join(links[:3])}")
    m = re.search(r"周[一二三四五六日]\d{3}", html)
    if m:
        s = max(0, m.start() - 200)
        say("  第一场比赛附近的网页源码（前 1800 字符）：")
        say("    " + html[s:s + 1800].replace("\n", " ")[:1800])
    else:
        say(f"  表格 {len(re.findall(r'<table', html, re.I))} 个，表格行 {len(re.findall(r'<tr', html, re.I))} 行")
        say("  页面文字前 500 字：" + clean(html)[:500])
        m2 = re.search(r">\s*\d{1,2}\.\d{2}\s*<", html)
        if m2:
            s = max(0, m2.start() - 600)
            say("  第一个赔率数字附近的网页源码（前 1800 字符）：")
            say("    " + html[s:s + 1800].replace("\n", " ")[:1800])
    return links


def main():
    say(f"足彩网小测试 v{__version__}")
    cache = {}
    first_links = []
    for name, url, fn in PAGES:
        say("")
        say(f"== {name}：{url}")
        ok, why = allowed(url, cache)
        say(f"  {why}")
        if not ok:
            continue
        code, html, err = fetch_retry(url)
        if err or code != 200:
            say(f"  没读成：{err or code}")
            if err and ("timed out" in err.lower() or "timeout" in err.lower()):
                say("  结论：robots.txt 读得到、但页面一直没回应——多半是这个网站从你的网络访问很慢或不通（我这边能读到这个页面）。")
                say("  这个来源先不用了，不影响现在的推单；换个时间或网络再运行一次也行。")
            continue
        (HERE / fn).write_text(html, encoding="utf-8")
        say(f"  已存成 {fn}")
        first_links = summarize(name, html)
        time.sleep(GAP)
    lg = [x for x in first_links if "/league/" in x]
    if lg:
        url = lg[0]
        say("")
        say(f"== 第一个联赛页：{url}")
        ok, why = allowed(url, cache)
        say(f"  {why}")
        if ok:
            code, html, err = fetch_retry(url)
            if err or code != 200:
                say(f"  没读成：{err or code}")
            else:
                (HERE / "source_probe_联赛页.html").write_text(html, encoding="utf-8")
                say(f"  已存成 source_probe_联赛页.html（{len(html)} 字符）")
                t = clean(html)
                say("  页面文字前 600 字：" + t[:600])
    OUT_TXT.write_text("\n".join(LINES), encoding="utf-8")
    say("")
    say(f"完成。结果在 {OUT_TXT.name}；请把它和 source_probe_*.html 一起发给我。")


if __name__ == "__main__":
    try:
        main()
    finally:
        if sys.platform == "win32" and sys.stdin and sys.stdin.isatty():
            input("按回车键关闭……")
