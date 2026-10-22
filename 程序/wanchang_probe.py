# -*- coding: utf-8 -*-
"""500 网「完场」页小测试（只读 1～2 个页面，不改任何文件，不碰你的推单数据）

用途：看看 500 网自己的「完场比分」页（全部赛事，一天大约 90 多场），
      脚本能不能读到比分，以及怎么切换到更早的日期。
用法：双击运行；或者在文件夹里打开命令行：  python wanchang_probe.py

它会做的事：
  1. 读 live.500.com 的 robots.txt，只读它允许的页面；
  2. 读「完场」页（最多再读 1 个更早日期的页面），页面之间隔几秒；
  3. 认出每一场的 联赛 / 时间 / 主队 / 比分 / 客队 / 半场，打印统计和样例；
  4. 列出页面里和「切换日期」有关的链接（我据此决定怎么补历史）；
  5. 把结果写进 wanchang_probe_结果.txt，原页面存成 wanchang_probe_页面1.html（和 页面2.html）。
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
OUT_TXT = HERE / "wanchang_probe_结果.txt"

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


# ---------------------------------------------------------------- 解析完场页
def clean(h):
    h = re.sub(r"<(script|style)\b.*?</\1>", " ", h, flags=re.S | re.I)
    h = re.sub(r"<br\s*/?>", " ", h, flags=re.I)
    h = re.sub(r"<[^>]+>", " ", h)
    h = (h.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">"))
    return re.sub(r"\s+", " ", h).strip()


def team_name(t):
    t = re.sub(r"[\[［【][^\]］】]*[\]］】]", "", t)       # 去掉 [英超1] 这类排名标记
    t = re.sub(r"\s+", "", t)
    return t


SCORE_CELL = re.compile(r"^\s*(\d{1,3})\s*[-－:：]\s*(\d{1,3})\s*$")
TIME_CELL = re.compile(r"(\d{1,2})-(\d{1,2})\s+(\d{1,2}):(\d{2})")


def parse_wanchang(html):
    """返回 (页面日期 'YYYY-MM-DD' 或 None, 比赛列表, 备注说明)。
    比赛：{lg, kick(如 '10-14 10:00'), status, home, away, hs, as, h1, a1}"""
    m = re.search(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日", clean(html))
    page_date = f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}" if m else None
    out, note = [], ""
    trs = re.findall(r"<tr\b[^>]*>(.*?)</tr>", html, flags=re.S | re.I)
    if not trs:
        return page_date, out, "页面里没有 <tr> 表格行（结构和预想的不同）。"
    for tr in trs:
        cells = [clean(c) for c in re.findall(r"<t[dh]\b[^>]*>(.*?)</t[dh]>", tr, flags=re.S | re.I)]
        if len(cells) < 5:
            continue
        st_i = next((i for i, c in enumerate(cells) if c in ("完", "完场", "已完")), None)
        lo = (st_i + 1) if st_i is not None else 3      # 比分在「状态」之后；没有状态列就跳过前几列（日期/轮次）
        si = next((i for i, c in enumerate(cells) if i >= lo and SCORE_CELL.match(c) and i < len(cells) - 1), None)
        if si is None:
            continue
        home, away = team_name(cells[si - 1]), team_name(cells[si + 1])
        if not home or not away:
            continue
        sc = SCORE_CELL.match(cells[si])
        half = next((SCORE_CELL.match(c) for c in cells[si + 2:] if SCORE_CELL.match(c)), None)
        kick = ""
        for c in cells[:si]:
            tm = TIME_CELL.search(c)
            if tm:
                kick = f"{int(tm.group(1)):02d}-{int(tm.group(2)):02d} {int(tm.group(3)):02d}:{tm.group(4)}"
                break
        status = next((c for c in cells[:si] if c in ("完", "完场", "已完")), "")
        out.append({"lg": cells[0], "kick": kick, "status": status, "home": home, "away": away,
                    "hs": int(sc.group(1)), "as": int(sc.group(2)),
                    "h1": int(half.group(1)) if half else None, "a1": int(half.group(2)) if half else None})
    return page_date, out, note


def date_links(html):
    """页面里所有和「日期切换」可能有关的链接（含 wanchang、e= 或 日期样式）。"""
    found, seen = [], set()
    for m in re.finditer(r"""<a\b[^>]*?href\s*=\s*["']([^"']+)["'][^>]*>(.*?)</a>""", html, flags=re.S | re.I):
        href, txt = m.group(1), clean(m.group(2))
        if href in seen:
            continue
        if re.search(r"wanchang|[?&](e|date|d)=|\d{4}-\d{2}-\d{2}|\d{8}", href, re.I):
            seen.add(href)
            found.append((href, txt[:20]))
    return found


def main(argv=()):
    global HOST, GAP
    args = list(argv)
    while args:                              # 仅供我自己测试用的开关
        a = args.pop(0)
        if a == "--host" and args:
            HOST = args.pop(0).rstrip("/")
        elif a == "--gap" and args:
            GAP = float(args.pop(0))
    PAGE = HOST + "/wanchang.php"
    say(f"500 网完场页小测试 v{__version__}  {datetime.now():%Y-%m-%d %H:%M:%S}")
    say("")
    say("① 读 robots.txt……")
    code, text, err = fetch(HOST + "/robots.txt")
    if err or code != 200:
        say(f"   读不到 robots.txt（{err or code}）。为稳妥起见到此为止。")
        return finish("N", "没读到 robots.txt，不继续。检查网络后再试。")
    rules = parse_robots(text)
    say(f"   读到了，对所有爬虫的限制共 {len(rules)} 条。")
    if not robots_allows(rules, "/wanchang.php"):
        say("   ✖ robots 不允许读完场页，到此为止。")
        return finish("R", "robots.txt 不允许读完场页，不要抓。")

    say("② 读完场页……")
    code, html, err = fetch(PAGE)
    if err or code != 200:
        say(f"   ✖ 读不到：{err or '状态码 %s' % code}")
        return finish("N", "完场页没读到（网络问题，或网站拒绝）。不要绕，告诉我这个结果。")
    say(f"   状态码 {code}，{len(html)} 个字符。")
    (HERE / "wanchang_probe_页面1.html").write_text(html, "utf-8")
    d1, rows, note = parse_wanchang(html)
    say(f"   页面日期：{d1 or '没找到'}")
    if note:
        say("   " + note)
    done = [r for r in rows if r["status"] in ("完", "完场", "已完")]
    say(f"   认出 {len(rows)} 场有比分的比赛（状态为「完」的 {len(done)} 场）。")
    lgs = {}
    for r in rows:
        lgs[r["lg"]] = lgs.get(r["lg"], 0) + 1
    say(f"   涉及 {len(lgs)} 个联赛/赛事。")
    for r in rows[:5]:
        h = f"（半场 {r['h1']}-{r['a1']}）" if r["h1"] is not None else ""
        say(f"   样例：{r['lg']} {r['kick']} {r['home']} {r['hs']}-{r['as']} {r['away']} {h}")

    links = date_links(html)
    say(f"③ 页面里和日期有关的链接：{len(links)} 个")
    for href, txt in links[:12]:
        say(f"   {href}   「{txt}」")

    # 试读一个更早日期的页面（robots 通配规则允许才读；失败也没关系）
    older = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
    path2 = f"/wanchang.php?e={older}"
    verdict_hist = "没试"
    if robots_allows(rules, path2):
        say(f"④ 等 {int(GAP)} 秒，再试读更早日期：{path2}")
        time.sleep(GAP)
        code2, html2, err2 = fetch(HOST + path2)
        if err2 or code2 != 200:
            say(f"   读不到：{err2 or '状态码 %s' % code2}")
            verdict_hist = "读不到"
        else:
            (HERE / "wanchang_probe_页面2.html").write_text(html2, "utf-8")
            d2, rows2, _ = parse_wanchang(html2)
            say(f"   页面日期：{d2 or '没找到'}，认出 {len(rows2)} 场。")
            verdict_hist = "可以切日期" if d2 and d1 and d2 != d1 and rows2 else "日期没变（这样的写法不起作用）"
    else:
        say(f"④ robots.txt 不允许读 {path2}，跳过。")
        verdict_hist = "robots 不允许"
    say(f"   更早日期：{verdict_hist}")

    if len(rows) >= 20:
        finish("A", f"完场页能读到，认出 {len(rows)} 场（比竞彩赛果每天十几场多得多）。更早日期：{verdict_hist}。")
    elif rows:
        finish("E", f"只认出 {len(rows)} 场，可能结构有出入。请把页面文件发给我看看。")
    else:
        finish("C", "页面读到了，但一场也没认出来。请把页面文件发给我，我按真实结构改。")


def finish(code, text):
    say("")
    say("—— 结论 ——")
    say(f"[{code}] {text}")
    say("把 wanchang_probe_结果.txt 和 wanchang_probe_页面1.html（有的话还有 页面2.html）发给我就行。")
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
