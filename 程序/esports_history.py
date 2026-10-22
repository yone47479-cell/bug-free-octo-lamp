# -*- coding: utf-8 -*-
"""公开电竞历史补抓：按战队分页、明确比分方向、只缓存规范化终场。"""
from __future__ import annotations
import json
import math
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import urlencode
import esports_data as E
import layout as L
from reliability import atomic_write_text

__version__ = "1.1"


def team_history(data, url, fetched, team_id):
    """战队接口是home/opponent视角，t1/t2分数并不总与此视角一致。"""
    if not isinstance(data, dict) or data.get('success') is not True:
        raise ValueError('5E战队历史接口未返回成功')
    items = (data.get('data') or {}).get('items') or {}
    rows = items.get('matches')
    if not isinstance(rows, list):
        raise ValueError('5E战队历史结构变化')
    out = []
    for item in rows:
        try:
            r = item['mc_info']
            if str(r['home_info']['id']) != str(team_id):
                continue
            if r.get('status') != 'past' or E._int(r['match_status']) != 2:
                continue
            bo = E._int(r['format'])
            score = E.final_series_score('csgo', bo, r['home_score'], r['opponent_score'])
            if score is None:
                continue
            # 有明确胜方时必须与比分一致，防止取消/弃赛等异常记录。
            expected = 'home_win' if score[0] > score[1] else 'opponent_win'
            if r.get('result') and r['result'] != expected:
                continue
            start = E._int(r['ts'])
            if not 946684800 <= start <= fetched:
                continue
            home, away = r['home_info']['disp_name'], r['opponent_info']['disp_name']
            if not E.known_team(home) or not E.known_team(away):
                continue
            out.append(dict(id=str(r['id']), game='csgo', home=home, away=away,
                            start=start, bo=bo, status='finished', score=list(score),
                            event=str((item.get('tt_info') or {}).get('disp_name') or ''),
                            source='5EPlay', url='https://event.5eplay.com/csgo/matches/'+str(r['id']),
                            page=url, fetched=fetched,
                            team_ids={'5EPlay': {E.team_key(home): str(team_id),
                                                E.team_key(away): str(r['opponent_info'].get('id') or '')}}))
        except (KeyError, ValueError, TypeError, OverflowError):
            continue
    return out, len(rows)


def analysis_series(state, fixture, now, url):
    """所有项目只接收match_recent中的完整BO比分；不把LOL击杀数当局分。"""
    a = (state.get('state') or {}).get('matchAnalysis') or {}
    recent = a.get('recentData') or a.get('analysisBaseInfo') or {}
    rows = []
    for side in ('home', 'away'):
        team = recent.get(side+'_team') or {}
        if E.match_key(fixture['game'],team.get('name', '')) != E.match_key(fixture['game'],fixture[side]):
            continue
        for r in (team.get('match_recent') or {}).get('list', []):
            try:
                game = E.GAMES.get(E._int(r['game_id']))
                if game != fixture['game']:
                    continue
                start, bo = E._int(r['match_time']), E._int(r['box'])
                if not now.timestamp()-90*86400 <= start < min(now.timestamp(), fixture['start']):
                    continue
                if str(r['match_id']) == str(fixture['id']):
                    continue
                score = E.final_series_score(game, bo, r['stats'][0], r['stats'][1])
                if score is None or not E.known_team(r['opponent']['name']):
                    continue
                rows.append(dict(id=str(r['match_id']), game=game, home=fixture[side],
                                 away=r['opponent']['name'], start=start, bo=bo,
                                 status='finished', score=list(score), event=str(r.get('title') or ''),
                                 source='Esports8', page=url,
                                 url=f'https://www.esports8.com/en/{game}/match/{r["match_id"]}',
                                 fetched=now.timestamp()))
            except (KeyError, ValueError, TypeError, IndexError, OverflowError):
                continue
    return rows


class HistoryCollector:
    def __init__(self, folder, cfg, now, client, cancel, write=True, force=False):
        self.path = L.p(folder, 'esports_history_cache.json')
        self.cfg, self.now, self.client, self.cancel = cfg, now, client, cancel
        self.write, self.force = write, force
        self.cache = {}
        self.notes = []
        self.requests = self.cache_hits = 0
        try:
            data = json.loads(self.path.read_text(encoding='utf-8-sig'))
            for key, stamp in data.get('checked', {}).items():
                if isinstance(stamp, (int, float)) and not isinstance(stamp, bool) and math.isfinite(stamp) and 0 <= now.timestamp()-stamp < 86400:
                    self.cache[key] = stamp
        except (OSError, ValueError, TypeError, AttributeError):
            pass

    def collect_teams(self, candidates):
        teams = {}
        for f in candidates:
            if f['game'] != 'csgo':
                continue
            for name, ident in f.get('team_ids', {}).get('5EPlay', {}).items():
                if ident and E.match_key(f['game'],name) in (E.match_key(f['game'],f['home']), E.match_key(f['game'],f['away'])):
                    teams[str(ident)] = name
        jobs = []
        for ident, name in teams.items():
            key = '5e|'+ident
            if not self.force and self.now.timestamp()-self.cache.get(key, 0) < self.cfg['历史缓存小时']*3600:
                self.cache_hits += 1
                continue
            jobs.append((ident, name))
        # 每个任务预留整组分页预算；失败不算成功、不更新缓存时间。
        # 先保证尽可能多的候选队都能读到一页，再分配深入翻页预算。
        limit = max(1, min(self.cfg['历史每队页数'], self.cfg['历史请求上限']//max(1, len(jobs))))
        slots = self.cfg['历史请求上限']//limit
        if jobs and not slots:
            limit = self.cfg['历史请求上限']
            slots = 1
        pending = jobs[slots:]
        jobs = jobs[:slots]
        for ident, name in jobs:
            self.cache.pop('5e|'+ident, None)
        if pending:
            self.notes.append(f'电竞历史：请求预算内补抓{len(jobs)}队，另有{len(pending)}队本轮未补抓（可提高历史请求上限）。')

        def worker(job):
            ident, name = job
            out, seen, count, complete = [], set(), 0, True
            for page in range(1, limit+1):
                if self.cancel():
                    raise RuntimeError('已停止')
                url = 'https://app.5eplay.com/api/tournament/team_session_list?'+urlencode(dict(
                    status='upcoming,live,past', page=page, game_type=1, tt_ids='', team_id=ident, limit=20))
                count += 1
                try:
                    raw = json.loads(self.client.get(url))
                    rows, total = team_history(raw, url, self.now.timestamp(), ident)
                except Exception as exc:
                    if self.cancel():
                        raise RuntimeError('已停止')
                    return out, count, None, f'电竞历史：{name} 第{page}页读取失败（{type(exc).__name__}），保留已存战绩，下次重试。'
                ids = {r['id'] for r in rows}
                if ids and ids <= seen:
                    complete = False
                    break
                seen.update(ids)
                out.extend(r for r in rows if self.now.timestamp()-90*86400 <= r['start'])
                if total < 20 or (rows and max(r['start'] for r in rows) < self.now.timestamp()-90*86400):
                    break
            stamp = ('5e|'+ident, self.now.timestamp()) if complete else None
            return out, count, stamp, ('' if complete else f'电竞历史：{name} 翻页重复，已停止，未标记补抓成功。')

        out = []
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix='esports-history') as pool:
            for rows, count, stamp, note in pool.map(worker, jobs):
                self.requests += count
                out.extend(rows)
                if stamp:
                    self.cache[stamp[0]] = stamp[1]
                if note:
                    self.notes.append(note)
        return out

    def save(self):
        if self.write:
            try:
                atomic_write_text(self.path, json.dumps({'checked': self.cache}, ensure_ascii=False))
            except OSError:
                self.notes.append('电竞历史检查时间未保存，下次将重新补抓。')


def map_shortage(maps, cfg):
    reasons = []
    for side, label in (('home', '主队'), ('away', '客队')):
        values = maps.get(side, [])
        series = len({v['series'] for v in values})
        if len(values) < cfg['最少地图'] or series < cfg['最少系列赛']:
            reasons.append(f'{label}{len(values)}图/{series}场系列赛，需至少{cfg["最少地图"]}图/{cfg["最少系列赛"]}场')
    return '；'.join(reasons)
