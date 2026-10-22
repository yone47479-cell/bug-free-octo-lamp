# -*- coding: utf-8 -*-
"""500 网「篮球完场页」＋「今天的足球完场页」小测试（只读 3～5 个页面，不改任何文件，不碰你的推单数据）

用途：
  ① 看 500 网自己的篮球「完场比分」页（live.500.com/lq.php?c=wc）里，脚本能不能直接读到每场比赛的球队和比分，
     以及怎么切换到更早的日期——这样才能像足球那样把篮球赛果攒下来，给竞篮做两队近况对比；
  ② 顺便存一份「今天」的足球完场页：今天还没踢的场次在页面里长什么样（我用它查为什么有些队名没自动对上）。
用法：双击运行；或者在文件夹里打开命令行：  python lq_probe.py

它会做的事：
  1. 读 live.500.com 的 robots.txt，只读它允许的页面（不允许的会跳过并写明）；
  2. 依次读：篮球完场页、今天的足球完场页、（篮球）更早日期的页面（最多试 2 种写法），页面之间隔几秒；
  3. 数每个页面里有多少行比赛、能不能认出球队和比分，列出和日期、数据加载有关的链接/脚本（只列出，不会去读它们）；
  4. 把结果写进 lq_probe_结果.txt，原页面存成 lq_probe_篮球页1.html、lq_probe_足球今日.html（有的话还有 lq_probe_篮球页2.html）。
     跑完后把这些文件发给我就行。

只用 Python 自带的库，Python 3.9 以上都能跑。
"""
import gzip
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta
from pathlib import Path

__version__ = "1.0"

HOST = "https://live.500.com"
GAP = 4.0                                   # 两次读页面之间隔几秒
HERE = Path(__file__).resolve().parent
OUT_TXT = HERE / "lq_probe_结果.txt"

try:                                         # 和你的抓取脚本用同一个浏览器标识（它在 500 网上一直能用）
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


DATE_RE = re.compile(r"(\d{4})\s*[-年]\s*(\d{1,2})\s*[-月]\s*(\d{1,2})")
SCORE_RE = re.compile(r"^\s*(\d{1,3})\s*[-－:：]\s*(\d{1,3})\s*$")


def page_dates(html):
    seen = []
    for m in DATE_RE.finditer(clean(html)):
        d = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
        if d not in seen:
            seen.append(d)
    return seen[:4]


def table_rows(html):
    out = []
    for m in re.finditer(r"<tr\b([^>]*)>(.*?)</tr\s*>", html, flags=re.S | re.I):
        out.append((m.group(1), m.group(2)))
    return out


def row_cells(body):
    return [clean(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", body, flags=re.S | re.I)]


def analyse(html, title):
    say(f"   ［{title}］{len(html)} 个字符")
    ds = page_dates(html)
    say(f"   页面里出现的日期：{', '.join(ds) if ds else '没找到'}")
    rows = table_rows(html)
    with_id = [r for r in rows if re.search(r'\bid\s*=\s*"a\d+"', r[0])]
    say(f"   表格行 {len(rows)} 行，其中带比赛编号（id=\"a数字\"）的 {len(with_id)} 行")
    for key in ("mainName", "clientName", "clt1", "clt3", "完场", "未开", "NBA", "CBA", "第一节", "加时"):
        n = html.count(key)
        if n:
            say(f"   页面里「{key}」出现 {n} 次")
    scored = []
    for attrs, body in rows:
        cells = row_cells(body)
        if len(cells) >= 5 and any(SCORE_RE.match(c) for c in cells):
            scored.append(cells)
    say(f"   含「数字-数字」比分格的行 {len(scored)} 行")
    for cells in scored[:4]:
        say("   样例行（单元格）：" + " | ".join(c[:18] for c in cells[:12]))
    shown = 0
    for attrs, body in with_id[:2]:
        say("   样例行原始 HTML：" + re.sub(r"\s+", " ", f"<tr {attrs}>{body}")[:1400])
        shown += 1
    if not with_id and scored:
        attrs, body = next(((a, b) for a, b in rows if any(SCORE_RE.match(c) for c in row_cells(b)) and len(row_cells(b)) >= 5), ("", ""))
        if body:
            say("   样例行原始 HTML：" + re.sub(r"\s+", " ", f"<tr {attrs}>{body}")[:1400])
    scripts = re.findall(r"<script\b([^>]*)>(.*?)</script>", html, flags=re.S | re.I)
    srcs = [re.search(r"src\s*=\s*[\"']([^\"']+)", a).group(1) for a, _ in scripts if re.search(r"src\s*=", a)]
    inl = [re.sub(r"\s+", " ", b)[:160] for a, b in scripts if b.strip() and re.search(r"lq|ajax|json|data|url|\.php", b, re.I)]
    say(f"   脚本：外部 {len(srcs)} 个，内联 {len(scripts) - len(srcs)} 个（只列出，不会去读）")
    for s in srcs[:10]:
        say("     外部脚本：" + s)
    for s in inl[:6]:
        say("     内联脚本片段：" + s)
    return ds, with_id, scored


def date_links(html):
    found, seen = [], set()
    for m in re.finditer(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", html, flags=re.S | re.I):
        href, txt = m.group(1), clean(m.group(2))
        if href in seen:
            continue
        if re.search(r"[?&](e|date|d)=|\d{4}-\d{2}-\d{2}|\d{8}", href, re.I):
            seen.add(href)
            found.append((href, txt[:20]))
    for m in re.finditer(r"""<(?:option|input|select)\b[^>]*?(?:value|name|id)\s*=\s*["']([^"']*(?:\d{4}-\d{2}-\d{2}|date)[^"']*)["']""", html, flags=re.I):
        if m.group(1) not in seen:
            seen.add(m.group(1))
            found.append((m.group(1), "（表单/下拉）"))
    return found


def football_today(html):
    """今天的足球完场页里没完场的行长什么样。"""
    rows = [r for r in table_rows(html) if re.search(r'\bid\s*=\s*"a\d+"', r[0])]
    stat = {}
    for attrs, body in rows:
        m = re.search(r'<span class="red">\s*([^<]*?)\s*</span>', body)
        k = m.group(1) if m else "（没有红色状态字）"
        stat[k] = stat.get(k, 0) + 1
    say(f"   带比赛编号的行 {len(rows)} 行；状态分布：{stat}")
    n_main = sum(1 for _, b in rows if 'class="mainName"' in b)
    say(f"   其中有 mainName（主队名）的 {n_main} 行")
    shown = 0
    for attrs, body in rows:
        m = re.search(r'<span class="red">\s*([^<]*?)\s*</span>', body)
        st = m.group(1) if m else ""
        if st in ("完", "改期", "中断", "取消"):
            continue
        say("   没完场的样例行：" + re.sub(r"\s+", " ", f"<tr {attrs}>{body}")[:1400])
        shown += 1
        if shown >= 2:
            break
    if not shown:
        say("   没找到「没完场」的行（可能今天的比赛还没出现在这个页面里）。")
    return len(rows), shown


def main(argv=()):
    global HOST, GAP
    args = list(argv)
    while args:                              # 仅供我自己测试用的开关
        a = args.pop(0)
        if a == "--host" and args:
            HOST = args.pop(0).rstrip("/")
        elif a == "--gap" and args:
            GAP = float(args.pop(0))
    say(f"500 网篮球完场页 + 今天足球完场页 小测试 v{__version__}  {datetime.now():%Y-%m-%d %H:%M:%S}")
    say("")
    say("① 读 robots.txt……")
    code, text, err = fetch(HOST + "/robots.txt")
    if err or code != 200:
        say(f"   读不到 robots.txt（{err or code}）。为稳妥起见到此为止。")
        return finish("N", "没读到 robots.txt，不继续。检查网络后再试。")
    rules = parse_robots(text)
    say(f"   读到了，对所有爬虫的限制共 {len(rules)} 条。")

    verdict = {}
    # ② 篮球完场页
    P_BB = "/lq.php?c=wc"
    html1 = ""
    if robots_allows(rules, P_BB):
        say(f"② 读篮球完场页：{P_BB}")
        code, html1, err = fetch(HOST + P_BB)
        if err or code != 200:
            say(f"   ✖ 读不到：{err or '状态码 %s' % code}")
            verdict["bb"] = "读不到"
        else:
            (HERE / "lq_probe_篮球页1.html").write_text(html1, "utf-8")
            ds, with_id, scored = analyse(html1, "篮球完场页")
            verdict["bb_rows"] = max(len(with_id), len(scored))
            links = date_links(html1)
            say(f"   和日期有关的链接/表单：{len(links)} 个")
            for href, txt in links[:14]:
                say(f"     {href}   「{txt}」")
            verdict["bb_dates"] = ds
            verdict["bb_links"] = links
    else:
        say(f"② robots.txt 不允许读 {P_BB}，跳过。")
        verdict["bb"] = "robots 不允许"

    # ③ 今天的足球完场页
    time.sleep(GAP)
    P_FB = "/wanchang.php"
    if robots_allows(rules, P_FB):
        say(f"③ 读今天的足球完场页：{P_FB}")
        code, html2, err = fetch(HOST + P_FB)
        if err or code != 200:
            say(f"   ✖ 读不到：{err or '状态码 %s' % code}")
        else:
            (HERE / "lq_probe_足球今日.html").write_text(html2, "utf-8")
            say(f"   页面日期：{', '.join(page_dates(html2)) or '没找到'}，{len(html2)} 个字符")
            football_today(html2)
    else:
        say(f"③ robots.txt 不允许读 {P_FB}，跳过。")

    # ④ 篮球更早日期（最多试 2 种写法，第一种成功就停）
    if html1 and verdict.get("bb_dates"):
        older = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
        cands = []
        for href, _ in verdict.get("bb_links", []):
            if "lq.php" in href and re.search(r"[?&](e|date|d)=", href):
                p = href.split("500.com", 1)[-1] if "500.com" in href else href
                p = re.sub(r"([?&](?:e|date|d)=)(\d{4}-\d{2}-\d{2}|\d{8})", lambda m: m.group(1) + older, p)
                cands.append(p if p.startswith("/") else "/" + p.lstrip("./"))
        cands += [f"/lq.php?c=wc&e={older}", f"/lq.php?e={older}&c=wc"]
        tried = []
        base_date = verdict["bb_dates"][0]
        for path in cands:
            if path in tried or len(tried) >= 2:
                continue
            tried.append(path)
            if not robots_allows(rules, path):
                say(f"④ robots.txt 不允许读 {path}，跳过这种写法。")
                continue
            say(f"④ 等 {int(GAP)} 秒，试读更早日期：{path}")
            time.sleep(GAP)
            code, h3, err = fetch(HOST + path)
            if err or code != 200:
                say(f"   读不到：{err or '状态码 %s' % code}")
                continue
            (HERE / "lq_probe_篮球页2.html").write_text(h3, "utf-8")
            ds3, wid3, sc3 = analyse(h3, "篮球更早日期")
            verdict["bb_switch"] = bool(ds3 and ds3[0] != base_date)
            say(f"   日期{'变了' if verdict['bb_switch'] else '没变（这种写法不起作用）'}：{ds3[:1]} （原来是 {base_date}）")
            if verdict["bb_switch"]:
                verdict["bb_switch_path"] = path
                break

    n = verdict.get("bb_rows", 0)
    if n >= 3:
        sw = "；更早日期可以这样切：" + verdict["bb_switch_path"] if verdict.get("bb_switch") else "；更早日期的写法还没找到（把结果发我）"
        finish("A", f"篮球完场页直接读到了 {n} 行比赛{sw}。")
    elif html1:
        finish("C", "篮球完场页读到了，但页面源码里几乎没有比赛行——比赛多半是页面打开后再用脚本加载的。"
                    "这种我不会去绕（不读被 robots 禁止的脚本/接口），先把结果文件发我，看有没有页面本身提供的、允许读的地址。")
    else:
        finish("N", "篮球完场页没读到（网络问题，或 robots 不允许、网站拒绝）。不要绕，把结果发我。")


def finish(code, text):
    say("")
    say("—— 结论 ——")
    say(f"[{code}] {text}")
    say("把 lq_probe_结果.txt 和 lq_probe_篮球页1.html、lq_probe_足球今日.html（有的话还有 lq_probe_篮球页2.html）发给我就行。")
    try:
        OUT_TXT.write_text("\n".join(LINES) + "\n", "utf-8")
    except Exception as e:
        print("（结果文件没存下来：%s）" % e)


if __name__ == "__main__":
    try:
        main(sys.argv[1:])
    except KeyboardInterrupt:
        print("\n已手动停止。")
    except Exception as e:
        import traceback
        traceback.print_exc()
        print("\n出错了：", e)
    if sys.stdin is not None and sys.stdin.isatty() and "--host" not in sys.argv:
        try:
            input("\n按回车键关闭窗口……")
        except Exception:
            pass
