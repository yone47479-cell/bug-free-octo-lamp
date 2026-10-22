# -*- coding: utf-8 -*-
"""新增公开来源：CyberScore赛程/系列赛，GOL系列赛近况，OpenDota逐局近况。"""
from __future__ import annotations
import json
import math
import re
from datetime import datetime, timedelta, timezone
from html.parser import HTMLParser
from functools import lru_cache
from urllib.parse import quote, urlencode
import esports_data as E
import layout as L
from reliability import atomic_write_text

__version__ = "1.0"
NAMES = ('CyberScore', 'GamesOfLegends', 'OpenDota')
ALIASES = {'csgo': (('Rare Atom', 'RA'), ('Alter Ego', 'AE')), 'lol': (
    ('Gen.G', 'GEN', 'Gen.G Esports'), ('Bilibili Gaming', 'BLG'),
    ('Top Esports', 'TES'), ('JD Gaming', 'JDG'), ('Weibo Gaming', 'WBG'),
    ('Karmine Corp', 'KC'), ('G2 Esports', 'G2'), ('Hanwha Life Esports', 'HLE'),
    ('Dplus KIA', 'DK'), ('KT Rolster', 'KT'), ('Fnatic', 'FNC'),
    ('Team Liquid', 'TL')), 'dota2': (('Team Spirit', 'Spirit'), ('Team Liquid', 'Liquid'),
                                   ('Resp Gaming', 'RG'), ('Yangon Galacticos', 'YG'))}


@lru_cache(maxsize=4096)
def identity(game, name):
    key = E.team_key(name)
    for names in ALIASES.get(game, ()):
        if key in {E.team_key(x) for x in names}:
            return E.team_key(names[0])
    return key


def stamp(text):
    d = datetime.fromisoformat(str(text).replace('Z', '+00:00'))
    if d.tzinfo is None:
        raise ValueError('时间缺少时区')
    return d.timestamp()


def flight_objects(html):
    """只解码Next.js公开JSON文本，不执行脚本或解析函数表达式。"""
    parts = [json.loads(m.group(1)) for m in re.finditer(
        r'self\.__next_f\.push\(\[1,("(?:\\.|[^"\\])*")\]\)', html)]
    if not parts:
        raise ValueError('CyberScore公开数据结构变化')
    for line in ''.join(parts).splitlines():
        m = re.match(r'^[0-9a-f]+:([\[{].*)$', line)
        if m:
            try:
                yield json.loads(m.group(1))
            except ValueError:
                continue


def cyber_items(html):
    for root in flight_objects(html):
        for node in E.walk_dicts(root):
            data = node.get('matches')
            if isinstance(data, dict) and isinstance(data.get('rows'), list):
                return data['rows']
    raise ValueError('CyberScore没有可核验的比赛列表')


def extract_cyber(html, url, fetched, max_tier=3):
    rows = []
    for r in cyber_items(html):
        try:
            tournament = r['tournament']
            if not 1 <= E._int(tournament['tier']) <= max_tier or r.get('is_tech_loss'):
                continue
            bo = E._int(r['best_of'])
            if bo not in (1, 3, 5, 7):  # BO2不能套用先胜制比分模型
                continue
            h, a = r['team_radiant'], r['team_dire']
            hid, aid = str(h['id']), str(a['id'])
            if not E.known_team(h['name']) or not E.known_team(a['name']) or hid == aid:
                continue
            related = r.get('related_matches') or []
            if not related or len({str(x['id']) for x in related}) != len(related):
                continue
            if any(x.get('is_tech_loss') or {str(x['team_radiant_id']), str(x['team_dire_id'])} != {hid, aid} for x in related):
                continue
            start = min(stamp(x['date_start']) for x in related)
            if not 946684800 <= start <= 4102444800:
                continue
            status = 'live'
            score = None
            if r['status'] == 'waiting' and all(x['status'] == 'waiting' for x in related) and r['best_of_score'] == [0, 0]:
                status = 'upcoming'
            elif r['status'] == 'ended_series':
                # 通过逐局胜方与队伍ID重算，DOTA换边不改变胜负方向。
                wins = {hid: 0, aid: 0}
                if any(x['status'] != 'ended_series' or x.get('winner') not in ('radiant', 'dire') for x in related):
                    continue
                for x in related:
                    wins[str(x['team_'+x['winner']+'_id'])] += 1
                score = E.final_series_score('dota2', bo, wins[hid], wins[aid])
                if score is None or list(score) != r['best_of_score']:
                    continue
                if any(stamp(x['date_start']) > fetched for x in related) or stamp(r['date_end']) > fetched:
                    continue
                status = 'finished'
            row = dict(id=str(r['id_series']), game='dota2', home=h['name'], away=a['name'],
                       start=start, bo=bo, status=status, score=list(score) if score else None,
                       event=str(tournament['name']), source='CyberScore', fetched=fetched, page=url,
                       tier=E._int(tournament['tier']),
                       url='https://cyberscore.live/en/matches/'+quote(str(r['slug']), safe='-')+'/',
                       team_ids={'CyberScore': {E.team_key(h['name']): hid, E.team_key(a['name']): aid}})
            if status == 'finished':
                # date_end可能只对应首图，整场完赛以本次公开状态确认时间为界。
                row['finished_at'] = fetched
            rows.append(row)
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return rows


class _GolTable(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth = 0
        self.rows = []
        self.row = self.cell = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'table':
            if self.depth:
                self.depth += 1
            elif 'table_list' in a.get('class', '').split():
                self.depth = 1
        if not self.depth:
            return
        if tag == 'tr':
            self.row = []
        elif tag == 'td' and self.row is not None:
            self.cell = {'text': '', 'class': a.get('class', ''), 'links': []}
        elif tag == 'a' and self.cell is not None and a.get('href'):
            self.cell['links'].append(a['href'])

    def handle_endtag(self, tag):
        if tag == 'td' and self.cell is not None and self.row is not None:
            self.row.append(self.cell)
            self.cell = None
        elif tag == 'tr' and self.row is not None:
            self.rows.append(self.row)
            self.row = None
        elif tag == 'table' and self.depth:
            self.depth -= 1

    def handle_data(self, text):
        if self.cell is not None:
            self.cell['text'] += text


def gol_tournaments(data, now):
    if not isinstance(data, list) or any(not isinstance(x, dict) or 'trname' not in x for x in data):
        raise ValueError('GOL赛事目录结构变化')
    rows = []
    for r in data:
        try:
            last = datetime.strptime(r['lastgame'], '%Y-%m-%d').replace(tzinfo=timezone.utc)
            if now.timestamp()-90*86400 <= last.timestamp() <= now.timestamp():
                rows.append({'name': str(r['trname']), 'last': r['lastgame']})
        except (KeyError, ValueError, TypeError):
            continue
    return sorted(rows, key=lambda x: x['last'], reverse=True)


def gol_series(html, url, fetched, event):
    p = _GolTable()
    p.feed(html)
    if 'table_list' not in html or not re.search(r'<caption[^>]*>.*?results', html, re.I | re.S):
        raise ValueError('GOL系列赛结果表结构变化')
    out = []
    for cells in p.rows:
        try:
            if len(cells) != 7:
                continue
            a, b = (E._int(x) for x in re.fullmatch(r'\s*(\d+)\s*[-:]\s*(\d+)\s*', cells[2]['text']).groups())
            if max(a, b) > 4 or min(a, b) < 0 or a == b:
                continue
            win, lose = (1, 3) if a > b else (3, 1)
            if 'text_victory' not in cells[win]['class'] or 'text_defeat' not in cells[lose]['class']:
                continue
            home, away = cells[1]['text'].strip(), cells[3]['text'].strip()
            if not E.known_team(home) or not E.known_team(away) or identity('lol', home) == identity('lol', away):
                continue
            game_id = next(re.search(r'/game/stats/(\d+)/page-summary/', x) for x in cells[0]['links'] if re.search(r'/game/stats/(\d+)/page-summary/', x)).group(1)
            date = datetime.strptime(cells[6]['text'].strip(), '%Y-%m-%d').replace(tzinfo=timezone.utc)
            # 原站仅给日历日期，按全球最晚时区UTC-12的当天结束时间保守确认。
            finished = (date+timedelta(hours=36)).timestamp()
            if not fetched-90*86400 <= date.timestamp() or finished > fetched:
                continue
            out.append(dict(kind='series', id='gol:'+game_id, game='lol', home=home, away=away,
                            start=date.timestamp(), finished_at=finished, fetched=fetched, score=[a, b],
                            time_precision='day', source='GamesOfLegends', event=event,
                            url='https://gol.gg/game/stats/'+game_id+'/page-summary/', page=url))
        except (KeyError, ValueError, TypeError, AttributeError, StopIteration):
            continue
    return out


def opendota_maps(data, url, fetched):
    if not isinstance(data, list) or any(not isinstance(x, dict) or 'match_id' not in x for x in data):
        raise ValueError('OpenDota职业赛列表结构变化')
    out = []
    for r in data:
        try:
            start, duration = E._int(r['start_time']), E._int(r['duration'])
            if not 60 <= duration <= 21600 or not fetched-90*86400 <= start or start+duration > fetched:
                continue
            home, away = r['radiant_name'], r['dire_name']
            if not E.known_team(home) or not E.known_team(away) or type(r['radiant_win']) is not bool:
                continue
            if E._int(r['radiant_team_id']) <= 0 or E._int(r['dire_team_id']) <= 0 or r['radiant_team_id'] == r['dire_team_id']:
                continue
            sid, kind = E._int(r['series_id']), E._int(r['series_type'])
            if kind not in (0, 1, 2) or sid < 0 or (not sid and kind != 0):
                continue
            match_id = str(E._int(r['match_id']))
            out.append(dict(kind='map', id='od:'+match_id, steam_match_id=match_id, game='dota2',
                            home=home, away=away, start=start, finished_at=start+duration, fetched=fetched,
                            win=int(r['radiant_win']), series='od-series:'+str(sid) if sid else 'od-bo1:'+match_id,
                            source='OpenDota', event=str(r.get('league_name') or ''),
                            url='https://www.opendota.com/matches/'+match_id, page=url))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return out


def fixture_jobs(cfg):
    if 'CyberScore' not in cfg['扩展来源'] or 'dota2' not in cfg['项目']:
        return []
    return [('cyber', 'https://cyberscore.live/en/matches/?'+urlencode({'page': page}))
            for page in range(1, cfg['扩展赛程页数']+1)]


class SourceCollector:
    def __init__(self, folder, cfg, now, client, cancel, write=True, force=False):
        self.path = L.p(folder, 'esports_source_cache.json')
        self.cfg, self.now, self.client, self.cancel = cfg, now, client, cancel
        self.write, self.force = write, force
        self.entries, self.status, self.notes, self.failed_hosts = {}, [], [], set()
        self.archive = []
        self.requests = 0
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            self.archive = data.get('history', []) if isinstance(data.get('history'), list) else []
            for key, v in data.get('entries', {}).items():
                if not isinstance(v, dict) or not isinstance(v.get('rows'), list) or len(v['rows']) > 2000:
                    continue
                at = v.get('checked')
                if isinstance(at, (int, float)) and not isinstance(at, bool) and math.isfinite(at) and 0 <= now.timestamp()-at <= 90*86400:
                    self.entries[key] = v
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def read(self, source, key, url, parser, post=None):
        if self.cancel():
            raise RuntimeError('已停止')
        old = self.entries.get(key, {'checked': 0, 'rows': []})
        state, message = 'cached', ''
        rows = old['rows']
        if self.force or self.now.timestamp()-old['checked'] >= self.cfg['历史缓存小时']*3600:
            if source in self.failed_hosts:
                state, message = 'fallback', '该来源本轮已失败，复用已确认历史，暂不追加请求'
            elif self.requests >= self.cfg['扩展历史请求上限']:
                state, message = 'budget', '达到扩展历史请求上限，未刷新'
            else:
                for attempt in range(2):
                    if self.cancel():raise RuntimeError('已停止')
                    self.requests += 1
                    try:
                        body = self.client.post_form(url, post) if post is not None else self.client.get(url)
                        rows = parser(body)
                        self.entries[key] = {'checked': self.now.timestamp(), 'rows': rows}
                        state = 'read'
                        break
                    except Exception as exc:
                        if self.cancel():raise RuntimeError('已停止')
                        code = getattr(exc, 'code', None)
                        transient = (isinstance(exc, OSError) and not code) or code in (500,502,503,504)
                        if attempt == 0 and transient and self.requests < self.cfg['扩展历史请求上限']:
                            continue
                        self.failed_hosts.add(source)
                        # 强制刷新失败后，下次常规运行仍重试，不沿用之前的成功检查时间。
                        self.entries[key] = dict(old, checked=0)
                        state = 'blocked' if code == 403 else 'rate_limited' if code == 429 else 'fallback'
                        message = (f'HTTP {code}' if code else type(exc).__name__)+f'（已试{attempt+1}次）；保留本地已确认历史'
                        break
        self.status.append(dict(source=source, state=state, url=url, rows=len(rows), message=message))
        return rows

    def collect(self, candidates):
        games = set(self.cfg['项目'])
        series_rows, forms = [], []
        active = set(self.cfg['扩展来源'])
        if 'dota2' in games and 'CyberScore' in active:
            teams = {}
            for f in candidates:
                if f['game'] == 'dota2':
                    teams.update(f.get('team_ids', {}).get('CyberScore', {}))
            # 先每队一页，避免按全站最近15场错误判断某队没有历史。
            kinds = sum((bool('dota2' in games and 'CyberScore' in active), bool('lol' in games and 'GamesOfLegends' in active), bool('dota2' in games and 'OpenDota' in active)))
            quota = max(1, self.cfg['扩展历史请求上限']//max(1, kinds))
            before_requests, pending = self.requests, 0
            for name, ident in teams.items():
                key = 'cyber-team:'+str(ident)
                entry = self.entries.get(key, {})
                cached = not self.force and 0 <= self.now.timestamp()-entry.get('checked', 0) < self.cfg['历史缓存小时']*3600
                if not cached and self.requests-before_requests >= quota:
                    pending += 1
                    continue
                url = 'https://cyberscore.live/en/matches/past/?'+urlencode(dict(page=1, type='past', team_id=ident))
                rows = self.read('CyberScore', 'cyber-team:'+str(ident), url,
                                 lambda body: extract_cyber(body, url, self.now.timestamp(), self.cfg['CyberScore最大Tier']))
                # 服务端若忽略team_id，绝不把无关结果当战队历史。
                rows = [r for r in rows if r.get('status') == 'finished' and str(ident) in r.get('team_ids', {}).get('CyberScore', {}).values()]
                series_rows.extend(rows)
            if pending:
                self.notes.append(f'CyberScore：另有{pending}队受本轮来源预算限制未刷新，下次优先处理未缓存队。')
        if 'lol' in games and 'GamesOfLegends' in active:
            url = 'https://gol.gg/tournament/ajax.trlist.php'
            season = 'S'+str(self.now.year-2010)
            tournaments = self.read('GamesOfLegends', 'gol-list:'+season, url,
                                    lambda body: gol_tournaments(json.loads(body), self.now), post={'season': season})
            for tr in tournaments[:self.cfg['LOL赛事页数']]:
                try:
                    name = tr['name']
                    u = 'https://gol.gg/tournament/tournament-matchlist/'+quote(name, safe='')+'/'
                except (KeyError, TypeError):
                    continue
                forms.extend(self.read('GamesOfLegends', 'gol-series:'+name, u,
                                       lambda body: gol_series(body, u, self.now.timestamp(), name)))
        if 'dota2' in games and 'OpenDota' in active:
            cursor = ''
            for page in range(self.cfg['OpenDota历史页数']):
                url = 'https://api.opendota.com/api/proMatches'+('?' + urlencode({'less_than_match_id': cursor}) if cursor else '')
                rows = self.read('OpenDota', 'od-cursor:'+str(cursor or 'head'), url,
                                 lambda body: opendota_maps(json.loads(body), url, self.now.timestamp()))
                # 缓存按实际游标标识，不能将上一轮第2页当作本轮新游标第2页。
                forms.extend(rows)
                ids = [int(r['steam_match_id']) for r in rows if str(r.get('steam_match_id', '')).isdigit()]
                if not ids or self.status[-1]['state'] in ('fallback', 'blocked', 'rate_limited', 'budget'):
                    break
                cursor = str(min(ids))
        # 仍可使用旧页积累的90天历史，但禁用的来源不参与。
        archive = list(self.archive)
        for entry in self.entries.values():
            archive.extend(entry['rows'])
        for r in archive:
            if isinstance(r, dict) and r.get('source') in active and r.get('game') in games:
                if r.get('kind') in ('series', 'map'):
                    forms.append(r)
                elif r.get('status') == 'finished':
                    series_rows.append(r)
        for source in NAMES:
            rows = [x for x in self.status if x['source'] == source]
            if rows:
                states = '、'.join(dict.fromkeys(x['state'] for x in rows))
                errors = '；'.join(dict.fromkeys(x['message'] for x in rows if x['message']))
                self.notes.append(f'电竞新增来源 {source}：{states}，涉及{len(rows)}页。'+errors)
        unique = {}
        for r in forms:
            if isinstance(r, dict) and isinstance(r.get('source'),str) and isinstance(r.get('id'),str):
                unique[(r.get('source'), r.get('id'))] = r
        # 翻页游标移动后仍保留已确认的旧局，按来源ID去重并滚动保留90天。
        saved = {}
        for r in archive+forms:
            try:
                if isinstance(r, dict) and r.get('kind') in ('series', 'map') and self.now.timestamp()-90*86400 <= r['start'] <= self.now.timestamp():
                    saved[(r['source'], r['id'])] = r
            except (KeyError, TypeError):
                continue
        self.archive = list(saved.values())
        series_rows = [r for r in series_rows if r.get('source') != 'CyberScore' or
                       isinstance(r.get('tier'), (int, float)) and 1 <= r['tier'] <= self.cfg['CyberScore最大Tier']]
        series_rows = list({(r.get('source'),r.get('id'),r.get('start')):r for r in series_rows
                            if isinstance(r.get('id'),str) and isinstance(r.get('start'),(int,float))}.values())
        self.notes.append(f'电竞扩展历史：本轮请求{self.requests}次，按来源ID去重后{len(series_rows)}条系列赛记录、{len(unique)}条近况记录。')
        return series_rows, list(unique.values())

    def save(self):
        if self.write:
            try:
                # 页面游标缓存只保留最近7天；规范化近况另存90天，避免大量过期页重复占用空间。
                entries={key:v for key,v in self.entries.items() if 0<=self.now.timestamp()-v['checked']<=7*86400}
                atomic_write_text(self.path, json.dumps({'entries': entries, 'history': self.archive}, ensure_ascii=False))
            except OSError:
                self.notes.append('电竞扩展历史缓存未保存，下次重新抓取。')


def supplement_maps(base, forms, fixture, now, cfg):
    """每侧选择一个样本更充分的来源，绝不把不同站点的同场战绩叠加凑样本。"""
    out = {side: list(base.get(side, [])) for side in ('home', 'away')}
    used = {}
    before = min(now.timestamp(), fixture['start'])
    for side in out:
        pools = {}
        for r in forms:
            try:
                if r['game'] != fixture['game'] or r['source'] not in cfg['扩展来源']:
                    continue
                if not before-90*86400 <= r['start'] < before or r['finished_at'] > before or r['finished_at'] < r['start']:
                    continue
                # 数据必须来自已完成的公开记录，拒绝未来抓取时间。
                if r['fetched'] > now.timestamp() or not all(math.isfinite(r[k]) for k in ('start', 'finished_at', 'fetched')):
                    continue
                name = identity(r['game'], fixture[side])
                if name not in (identity(r['game'], r['home']), identity(r['game'], r['away'])):
                    continue
                home = name == identity(r['game'], r['home'])
                values = pools.setdefault(r['source'], {})
                if r['kind'] == 'series':
                    a, b = (E._int(x) for x in r['score'])
                    if min(a, b) < 0 or max(a, b) > 4 or a == b:
                        continue
                    if not home:
                        a, b = b, a
                    games = [dict(at=r['start'], win=int(i < a), series=r['id'], map='系列赛汇总',
                                  sources=[{'name': r['source'], 'url': r['url'], 'fetched': r['fetched']}]) for i in range(a+b)]
                    values[r['id']] = games
                elif r['kind'] == 'map' and r['win'] in (0, 1):
                    values[r['id']] = [dict(at=r['start'], win=r['win'] if home else 1-r['win'],
                                           series=r['series'], map='独立已完局',
                                           sources=[{'name': r['source'], 'url': r['url'], 'fetched': r['fetched']}])]
            except (KeyError, ValueError, TypeError, OverflowError):
                continue
        for source, groups in pools.items():
            values = []
            for group in sorted(groups.values(), key=lambda x: x[0]['at'], reverse=True):
                if len(values)+len(group) > 30:
                    break
                values.extend(group)
            n = len(values)
            series = len({v['series'] for v in values})
            sufficient = n >= cfg['最少地图'] and series >= cfg['最少系列赛']
            current = out[side]
            current_ok = len(current) >= cfg['最少地图'] and len({v['series'] for v in current}) >= cfg['最少系列赛']
            if (sufficient and not current_ok) or (sufficient == current_ok and n > len(current)):
                out[side], used[side] = values, source
    return out, used
