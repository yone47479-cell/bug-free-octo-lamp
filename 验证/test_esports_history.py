"""历史补抓、比分视角、预算、缓存及候选完整记账；全部使用离线样例。"""
import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit
sys.path.insert(0, str(Path(__file__).parents[1]/'程序'))
import esports_data as E
import esports_history as H
from test_esports import NOW, fixture


def history_item(ident='team-a', i=1, win=True):
    return {'mc_info': {'id': 'past-'+ident+'-'+str(i), 'format': '3',
            'status': 'past', 'match_status': '2', 'ts': str(int(NOW.timestamp()-i*86400)),
            'home_info': {'id':ident, 'disp_name':ident},
            'opponent_info': {'id':'op-'+str(i), 'disp_name':'opponent-'+str(i)},
            'home_score': '2' if win else '0', 'opponent_score':'0' if win else '2',
            # 这两个字段刻意相反：战队接口不能使用它们作为home/opponent分数。
            't1_score':'0' if win else '2', 't2_score':'2' if win else '0',
            'result':'home_win' if win else 'opponent_win'}}


def payload(items):
    return {'success':True, 'data':{'items':{'matches':items}}}


def candidate(i=0):
    f=fixture();f.update(id='next-'+str(i),home='team-a',away='team-b',source='5EPlay',
                        start=fixture()['start']+i*1800,
                        url='https://event.5eplay.com/csgo/matches/next-'+str(i),
                        team_ids={'5EPlay':{'team-a':'team-a','team-b':'team-b'}})
    return f


class HistoryTests(unittest.TestCase):
    def test_team_perspective_score_not_t1_t2(self):
        rows,total=H.team_history(payload([history_item()]),'https://app.5eplay.com/test',NOW.timestamp(),'team-a')
        self.assertEqual(total,1)
        self.assertEqual(rows[0]['score'],[2,0])
        self.assertEqual(rows[0]['home'],'team-a')

    def test_live_future_invalid_wrong_team_and_inconsistent_winner_rejected(self):
        for changes in ({'status':'live'},{'match_status':'1'},{'ts':str(int(NOW.timestamp()+1))},
                        {'home_score':'13'},{'result':'opponent_win'},
                        {'home_info':{'id':'another','disp_name':'team-a'}}):
            r=history_item();r['mc_info'].update(changes)
            self.assertEqual(H.team_history(payload([r]),'url',NOW.timestamp(),'team-a')[0],[])

    def test_bo1_rounds_converted(self):
        r=history_item();r['mc_info'].update(format='1',home_score='13',opponent_score='8')
        self.assertEqual(H.team_history(payload([r]),'url',NOW.timestamp(),'team-a')[0][0]['score'],[1,0])

    def test_team_history_paginated_and_reused_after_save(self):
        calls=[]
        class Client:
            def get(self,url):
                q=parse_qs(urlsplit(url).query);calls.append(q)
                ident=q['team_id'][0];page=int(q['page'][0])
                return json.dumps(payload([history_item(ident,i) for i in (range(1,21) if page==1 else range(21,24))]))
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,历史每队页数=3,历史请求上限=12)
            h=H.HistoryCollector(Path(d),cfg,NOW,Client(),lambda:False)
            rows=h.collect_teams([candidate(),candidate(1)]);h.save()
            self.assertEqual(len(rows),46);self.assertEqual(h.requests,4)
            h2=H.HistoryCollector(Path(d),cfg,NOW,Client(),lambda:False)
            self.assertEqual(h2.collect_teams([candidate()]),[])
            self.assertEqual(h2.cache_hits,2);self.assertEqual(len(calls),4)
            h3=H.HistoryCollector(Path(d),cfg,NOW,Client(),lambda:False,force=True)
            h3.collect_teams([candidate()]);self.assertEqual(h3.requests,4)

    def test_failure_not_cached_and_budget_bounded(self):
        class Client:
            def get(self,url):raise TimeoutError('test')
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,历史请求上限=2)
            h=H.HistoryCollector(Path(d),cfg,NOW,Client(),lambda:False)
            self.assertEqual(h.collect_teams([candidate()]),[])
            self.assertEqual(h.requests,2);self.assertEqual(h.cache,{})
            self.assertTrue(h.notes)

    def test_empty_success_and_bad_structure_distinguished(self):
        self.assertEqual(H.team_history(payload([]),'url',NOW.timestamp(),'team-a'),([],0))
        with self.assertRaises(ValueError):H.team_history({'success':True,'data':{}},'url',NOW.timestamp(),'team-a')

    def test_repeated_page_stops_and_does_not_mark_complete(self):
        class Client:
            def get(self,url):
                ident=parse_qs(urlsplit(url).query)['team_id'][0]
                return json.dumps(payload([history_item(ident,i) for i in range(1,21)]))
        with tempfile.TemporaryDirectory() as d:
            h=H.HistoryCollector(Path(d),E.DEFAULTS,NOW,Client(),lambda:False,write=False)
            self.assertEqual(len(h.collect_teams([candidate()])),40)
            self.assertEqual(h.requests,4);self.assertEqual(h.cache,{})

    def test_future_cache_time_ignored(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'esports_history_cache.json').write_text(json.dumps({'checked':{'5e|team-a':NOW.timestamp()+10,'5e|team-b':float('nan')}}))
            h=H.HistoryCollector(Path(d),E.DEFAULTS,NOW,None,lambda:False)
            self.assertEqual(h.cache,{})

    def test_old_default_migration_preserves_custom_settings(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d,'电竞设置.json')
            p.write_text(json.dumps({'分析候选':6,'最多场次':2,'自定义备注':'保留'}))
            cfg=E.load_settings(Path(d))
            saved=json.loads(p.read_text())
            self.assertEqual(cfg['分析候选'],24)
            self.assertEqual(saved['最多场次'],2)
            self.assertEqual(saved['自定义备注'],'保留')
            self.assertEqual(saved['历史每队页数'],3)

    def test_analysis_complete_series_all_projects_no_future_or_kill_scores(self):
        f=dict(candidate(),game='lol')
        record={'game_id':1,'match_time':int(NOW.timestamp()-86400),'box':3,'stats':[2,1],
                'match_id':'past-lol','opponent':{'name':'opponent'}}
        state={'state':{'matchAnalysis':{'analysisBaseInfo':{'home_team':{'name':f['home'],'match_recent':{'list':[
            record,dict(record,match_time=int(NOW.timestamp()+1)),dict(record,stats=[20,15]),dict(record,game_id=2)]}}}}}}
        rows=H.analysis_series(state,f,NOW,'url')
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['score'],[2,1])

    def test_merge_preserves_conflict_and_source_team_ids_across_remerge(self):
        a=candidate();b=dict(a,bo=5,source='Esports8',team_ids={'Esports8':{'team-a':'e8a'}})
        merged=E.merge_matches([a,b])
        again=E.merge_matches(merged)
        self.assertTrue(again[0]['conflict']);self.assertEqual(len(again[0]['sources']),2)
        self.assertEqual(again[0]['team_ids']['5EPlay']['team-a'],'team-a')
        self.assertNotIn('Esports8',a['team_ids'])

    def test_history_limit_never_truncates_invented_map_order(self):
        f=candidate();rows=[]
        for i in range(7):
            rows.append(dict(f,id='past'+str(i),status='finished',bo=5,score=[3,2],start=NOW.timestamp()-1000-i*1000))
        result=E.history_maps(rows,f,NOW)
        self.assertEqual(len(result['home']),30)
        self.assertEqual(sum(v['win'] for v in result['home']),18)
        self.assertEqual(sum(v['win'] for v in result['away']),12)
        rows[0].update(bo=3,score=[2,0])
        result=E.history_maps(rows,f,NOW)
        self.assertEqual(len(result['home']),27)
        self.assertEqual(len({v['series'] for v in result['home']}),6)

    def test_build_5e_only_can_predict_and_account_every_candidate(self):
        class Client:
            def get(self,url):
                q=parse_qs(urlsplit(url).query);ident=q['team_id'][0]
                return json.dumps(payload([history_item(ident,i,win=ident=='team-a') for i in range(1,5)]))
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,分析候选=7)
            fixtures=[candidate(i) for i in range(7)]
            with patch.object(E,'load_settings',return_value=cfg),patch.object(E,'extract_esports8',return_value=fixtures),patch.object(E,'parse_nuxt',return_value={}),patch.object(E,'extract_5e',return_value=[]),patch('esports_refs.collect',return_value={'enabled':False,'notes':[]}):
                class Combined(Client):
                    def get(self,url):
                        return super().get(url) if 'team_session_list' in url else '{}'
                out=E.build(Path(d),'2026-10-19',now=NOW,client=Combined())
            self.assertEqual(len(out['picks']),3)
            self.assertEqual(out['counts']['selection_limit'],4)
            self.assertEqual(sum(out['counts'].values()),7)
            self.assertTrue(Path(d,'esports_matches.json').exists())
            self.assertIn('team-a',E.diagnostics_text(out))

    def test_analysis_limit_has_explicit_record(self):
        class Client:
            def get(self,url):return '{}'
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,项目=['lol'],分析候选=2)
            fixtures=[dict(candidate(i),game='lol') for i in range(7)]
            with patch.object(E,'load_settings',return_value=cfg),patch.object(E,'extract_esports8',return_value=fixtures),patch.object(E,'parse_nuxt',return_value={}),patch('esports_refs.collect',return_value={'enabled':False,'notes':[]}):
                out=E.build(Path(d),'2026-10-19',now=NOW,client=Client(),write=False)
            self.assertEqual(out['counts']['insufficient_history'],2)
            self.assertEqual(out['counts']['analysis_limit'],5)
            self.assertEqual(len(out['diagnostics']),7)
            self.assertEqual(list(Path(d).iterdir()),[])

    def test_cancel_stops_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            h=H.HistoryCollector(Path(d),E.DEFAULTS,NOW,None,lambda:True,write=False)
            with self.assertRaisesRegex(RuntimeError,'已停止'):h.collect_teams([candidate()])


if __name__=='__main__':unittest.main()
