"""新增电竞来源：数据子集解析、比分方向、缓存、预算、日期精度与跨站重复。"""
import copy
import json
import sys
import tempfile
import unittest
from datetime import timedelta, timezone
from pathlib import Path
from unittest.mock import patch
from urllib.error import HTTPError
sys.path.insert(0, str(Path(__file__).parents[1]/'程序'))
import esports_data as E
import esports_sources as S
from test_esports import NOW, fixture, maps


def cyber_row(finished=False):
    start = (NOW-timedelta(days=2) if finished else NOW+timedelta(hours=3)).isoformat()
    r = {'id': 1, 'id_series':'series-a', 'slug':'test-a', 'status':'ended_series' if finished else 'waiting',
         'best_of':3, 'best_of_score':[2,0] if finished else [0,0], 'date_start':start,
         'date_end':(NOW-timedelta(days=2)+timedelta(hours=1)).isoformat() if finished else None,
         'tournament':{'tier':2,'name':'离线样例'},'is_tech_loss':False,
         'team_radiant':{'id':11,'name':'甲队'},'team_dire':{'id':22,'name':'乙队'},
         'score_team_radiant':1,'score_team_dire':99}
    r['related_matches']=[{'id':1,'date_start':start,'team_radiant_id':11,'team_dire_id':22,
                           'status':r['status'],'winner':'radiant' if finished else '', 'is_tech_loss':False}]
    if finished:
        r['related_matches'].append(dict(r['related_matches'][0],id=2,team_radiant_id=22,team_dire_id=11,winner='dire'))
    return r


def flight(rows):
    text='4b:'+json.dumps([{'matches':{'rows':rows}}])+'\n'
    # 模拟跨两个脚本块的Flight文本，不运行JS。
    n=len(text)//2
    return ''.join('<script>self.__next_f.push([1,'+json.dumps(x)+'])</script>' for x in (text[:n],text[n:]))


def gol_table(score='3 - 1', day='2026-10-15', home='Karmine Corp', away='FURIA'):
    return f'''<table class="table_list"><caption>Sample results</caption><tr>
      <td><a href="../game/stats/123/page-summary/">KC vs FURIA</a></td>
      <td class="text_victory">{home}</td><td>{score}</td><td class="text_defeat">{away}</td>
      <td>FINAL</td><td>16.20</td><td>{day}</td></tr></table>'''


def od_record(i=1, series=101):
    return dict(match_id=i, duration=1800, start_time=int(NOW.timestamp()-86400-i),
                radiant_team_id=11,dire_team_id=22,radiant_name='甲队',dire_name='乙队',
                radiant_win=True,series_id=series,series_type=1,radiant_score=5,dire_score=99)


class SourceTests(unittest.TestCase):
    def test_flight_split_chunks_and_cyber_future_fixture(self):
        rows=S.extract_cyber(flight([cyber_row()]),'url',NOW.timestamp())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['status'],'upcoming')
        self.assertEqual(rows[0]['team_ids']['CyberScore']['甲队'],'11')

    def test_flight_does_not_execute_javascript_or_accept_missing_list(self):
        for text in ('<script>self.__next_f.push([1,eval("x")])</script>', '<html>Challenge</html>'):
            with self.assertRaises(ValueError):S.cyber_items(text)
        self.assertEqual(S.cyber_items(flight([])),[])

    def test_cyber_switching_sides_reconstructed_not_kills(self):
        rows=S.extract_cyber(flight([cyber_row(True)]),'url',NOW.timestamp())
        self.assertEqual(rows[0]['score'],[2,0])
        self.assertEqual(rows[0]['finished_at'],NOW.timestamp())
        self.assertNotEqual(rows[0]['score'],[1,99])

    def test_cyber_missing_map_conflict_technical_and_future_rejected(self):
        for case in ('missing','winner','technical','future','tier','bo2'):
            r=cyber_row(True)
            if case=='missing':r['related_matches'].pop()
            if case=='winner':r['related_matches'][1]['winner']='radiant'
            if case=='technical':r['related_matches'][0]['is_tech_loss']=True
            if case=='future':r['date_end']=(NOW+timedelta(seconds=1)).isoformat()
            if case=='tier':r['tournament']['tier']=4
            if case=='bo2':r['best_of']=2
            self.assertEqual(S.extract_cyber(flight([r]),'url',NOW.timestamp()),[],case)

    def test_cyber_already_started_series_not_upcoming(self):
        r=cyber_row();r['related_matches'][0]['status']='draft'
        self.assertEqual(S.extract_cyber(flight([r]),'url',NOW.timestamp())[0]['status'],'live')

    def test_gol_parses_series_and_retains_day_precision(self):
        rows=S.gol_series(gol_table(),'url',NOW.timestamp(),'赛事')
        self.assertEqual(rows[0]['score'],[3,1]);self.assertEqual(rows[0]['kind'],'series')
        self.assertNotIn('bo',rows[0]);self.assertEqual(rows[0]['time_precision'],'day')
        self.assertEqual(rows[0]['finished_at']-rows[0]['start'],36*3600)

    def test_gol_today_missing_date_unknown_or_wrong_winner_rejected(self):
        for text in (gol_table(day=NOW.strftime('%Y-%m-%d')),gol_table(day='未知'),
                     gol_table(score='1 - 3'),gol_table(home='TBD'),gol_table(score='1 - 1')):
            self.assertEqual(S.gol_series(text,'url',NOW.timestamp(),'赛事'),[])
        with self.assertRaises(ValueError):S.gol_series('<html>error</html>','url',NOW.timestamp(),'赛事')

    def test_gol_catalog_date_window_and_shape(self):
        rows=S.gol_tournaments([{'trname':'近赛','lastgame':'2026-10-18'}, {'trname':'旧赛','lastgame':'2025-01-01'}],NOW)
        self.assertEqual(rows,[{'name':'近赛','last':'2026-10-18'}])
        with self.assertRaises(ValueError):S.gol_tournaments({'error':1},NOW)

    def test_opendota_uses_boolean_winner_not_kills_or_series_score(self):
        rows=S.opendota_maps([od_record()],'url',NOW.timestamp())
        self.assertEqual(rows[0]['win'],1);self.assertEqual(rows[0]['kind'],'map')
        self.assertNotIn('score',rows[0]);self.assertEqual(rows[0]['series'],'od-series:101')

    def test_opendota_future_live_unknown_team_or_series_group_rejected(self):
        for changes in ({'start_time':int(NOW.timestamp())},{'radiant_win':'true'},{'duration':0},
                        {'radiant_team_id':0},{'radiant_name':None},{'series_id':0}, {'series_type':99}):
            self.assertEqual(S.opendota_maps([dict(od_record(),**changes)],'url',NOW.timestamp()),[],changes)
        self.assertEqual(S.opendota_maps([dict(od_record(),series_id=0,series_type=0)],'url',NOW.timestamp())[0]['series'],'od-bo1:1')

    def test_explicit_aliases_do_not_collapse_academy_or_other_games(self):
        self.assertEqual(S.identity('lol','KC'),S.identity('lol','Karmine Corp'))
        self.assertNotEqual(S.identity('lol','KC Academy'),S.identity('lol','Karmine Corp'))
        self.assertNotEqual(S.identity('csgo','KC'),S.identity('csgo','Karmine Corp'))

    def test_supplement_does_not_stack_same_series_from_different_sources(self):
        f=dict(fixture(),game='lol',home='KC',away='FURIA')
        records=S.gol_series(gol_table(),'url',NOW.timestamp(),'赛事')
        out,used=S.supplement_maps({'home':[],'away':[]},records*3,f,NOW,E.DEFAULTS)
        self.assertEqual(len(out['home']),4)
        # 一场系列赛不能复制成三场来绕过样本门槛。
        self.assertEqual(len({x['series'] for x in out['home']}),1)
        self.assertIsNone(E.predict(f,out,E.DEFAULTS))

    def test_opendota_series_count_and_reversed_sides(self):
        forms=S.opendota_maps([od_record(i,series=100+i//2) for i in range(1,9)],'url',NOW.timestamp())
        f=dict(fixture(),game='dota2',home='乙队',away='甲队')
        out,used=S.supplement_maps({'home':[],'away':[]},forms,f,NOW,E.DEFAULTS)
        self.assertEqual(len(out['home']),8);self.assertEqual(sum(x['win'] for x in out['home']),0)
        self.assertEqual(sum(x['win'] for x in out['away']),8)
        self.assertEqual(E.predict(f,out,E.DEFAULTS)['direction'],'甲队')

    def test_local_complete_histories_choose_single_source(self):
        f=fixture();rows=[]
        for i in range(4):
            for src,offset in [('Esports8',0),('CyberScore',1800)]:
                rows.append(dict(f,id=src+str(i),source=src,status='finished',score=[2,0],start=NOW.timestamp()-86400-i*86400+offset))
        out=E.history_maps(rows,f,NOW)
        self.assertEqual(len(out['home']),8)  # 不是跨站相加后的16图

    def test_disabled_or_filtered_source_is_not_used_from_existing_database(self):
        f=dict(fixture(),game='dota2')
        r=dict(f,status='finished',score=[2,0],source='CyberScore',tier=4,start=NOW.timestamp()-86400)
        self.assertEqual(E.history_maps([r],f,NOW)['home'],[])
        r['tier']=2
        self.assertEqual(E.history_maps([r],f,NOW,dict(E.DEFAULTS,扩展来源=[]))['home'],[])

    def test_same_match_dota_abbreviations_merge_with_source_ids(self):
        a=dict(fixture(),game='dota2',home='RG',away='YG')
        b=dict(a,home='Resp Gaming',away='Yangon Galacticos',source='CyberScore',team_ids={'CyberScore':{'resp gaming':'11','yangon galacticos':'22'}})
        rows=E.merge_matches([a,b])
        self.assertEqual(len(rows),1);self.assertEqual(len(rows[0]['sources']),2)
        self.assertEqual(rows[0]['team_ids']['CyberScore']['resp gaming'],'11')

    def test_cross_source_time_conflict_is_not_two_recommendations(self):
        with tempfile.TemporaryDirectory() as d:
            a=dict(fixture(),home='Rare Atom',away='Alter Ego')
            b=dict(a,home='RA',away='AE',start=a['start']+1200,source='5EPlay')
            cfg=dict(E.DEFAULTS,项目=['csgo'],扩展来源=[])
            client=type('C',(),{'get':lambda self,u:'{}'})()
            with patch.object(E,'load_settings',return_value=cfg),patch.object(E,'extract_esports8',return_value=[a,b]),patch.object(E,'extract_5e',return_value=[]),patch.object(E,'parse_nuxt',return_value={}),patch('esports_refs.collect',return_value={'enabled':False,'notes':[]}):
                r=E.build(Path(d),'2026-10-19',now=NOW,client=client,write=False)
            self.assertEqual(r['counts']['schedule_conflict'],2)
            self.assertEqual(len(r['picks']),0)
            self.assertEqual(len(r['diagnostics']),2)

    def test_future_completion_is_not_used(self):
        f=fixture();r=dict(f,status='finished',score=[2,0],start=NOW.timestamp()-86400,finished_at=NOW.timestamp()+1)
        self.assertEqual(E.history_maps([r],f,NOW)['home'],[])

    def test_config_migration_allows_disable_and_rejects_unknown(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d,'电竞设置.json');p.write_text(json.dumps({'扩展来源':[]}))
            self.assertEqual(E.load_settings(Path(d),False)['扩展来源'],[])
            p.write_text(json.dumps({'扩展来源':['HLTV']}))
            with self.assertRaises(ValueError):E.load_settings(Path(d),False)

    def test_post_form_allowlist_rejects_other_mutations(self):
        with tempfile.TemporaryDirectory() as d:
            c=E.PublicClient(Path(d))
            with patch.object(c,'_request',return_value='[]') as request:
                self.assertEqual(c.post_form('https://gol.gg/tournament/ajax.trlist.php',{'season':'S16'}),'[]')
                for url,fields in [('https://gol.gg/write',{'season':'S16'}),('https://gol.gg/tournament/ajax.trlist.php',{'password':'x'})]:
                    with self.assertRaises(ValueError):c.post_form(url,fields)
                self.assertEqual(request.call_count,1)

    def test_cache_reuse_force_failure_and_http_circuit_break(self):
        class Client:
            def get(self,url):return '[{"match_id":1}]'
        with tempfile.TemporaryDirectory() as d:
            c=S.SourceCollector(Path(d),E.DEFAULTS,NOW,Client(),lambda:False)
            parser=lambda text:[dict(id='x',source='OpenDota',game='dota2',kind='map',start=NOW.timestamp()-100)]
            c.read('OpenDota','x','https://api.opendota.com/test',parser);c.save()
            c2=S.SourceCollector(Path(d),E.DEFAULTS,NOW,Client(),lambda:False)
            c2.read('OpenDota','x','url',parser);self.assertEqual(c2.requests,0)
            c3=S.SourceCollector(Path(d),E.DEFAULTS,NOW,Client(),lambda:False,force=True)
            error=HTTPError('url',429,'limited',{},None)
            with patch.object(c3.client,'get',side_effect=error) as get:
                self.assertEqual(c3.read('OpenDota','x','url',parser)[0]['id'],'x')
                c3.read('OpenDota','y','url2',parser)
                self.assertEqual(get.call_count,1)
                self.assertEqual(c3.status[0]['state'],'rate_limited')
                self.assertEqual(c3.entries['x']['checked'],0)

    def test_transient_error_retries_once_within_budget(self):
        with tempfile.TemporaryDirectory() as d:
            client=type('C',(),{'get':lambda self,u:'[]'})()
            c=S.SourceCollector(Path(d),E.DEFAULTS,NOW,client,lambda:False,write=False)
            with patch.object(client,'get',side_effect=[TimeoutError('once'),'[]']):
                self.assertEqual(c.read('OpenDota','x','url',lambda b:json.loads(b)),[])
            self.assertEqual(c.requests,2);self.assertEqual(c.status[0]['state'],'read')
            self.assertEqual(c.failed_hosts,set())

    def test_budget_and_future_cache_timestamp(self):
        with tempfile.TemporaryDirectory() as d:
            Path(d,'esports_source_cache.json').write_text(json.dumps({'entries':{'future':{'checked':NOW.timestamp()+10,'rows':[]}}}))
            c=S.SourceCollector(Path(d),dict(E.DEFAULTS,扩展历史请求上限=3),NOW,type('C',(),{'get':lambda self,u:'[]'})(),lambda:False,write=False)
            self.assertEqual(c.entries,{})
            for i in range(7):c.read('OpenDota',str(i),'url',lambda b:[])
            self.assertEqual(c.requests,3);self.assertEqual(c.status[-1]['state'],'budget')

    def test_opendota_archive_survives_moving_head(self):
        class Client:
            def __init__(self):self.offset=0
            def get(self,url):return json.dumps([od_record(i+self.offset,series=100+i) for i in range(1,4)])
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,项目=['dota2'],扩展来源=['OpenDota'],OpenDota历史页数=1)
            client=Client();c=S.SourceCollector(Path(d),cfg,NOW,client,lambda:False)
            self.assertEqual(len(c.collect([])[1]),3);c.save()
            client.offset=10;c2=S.SourceCollector(Path(d),cfg,NOW,client,lambda:False,force=True)
            self.assertEqual(len(c2.collect([])[1]),6);c2.save()
            c3=S.SourceCollector(Path(d),cfg,NOW,client,lambda:False)
            self.assertEqual(len(c3.collect([])[1]),6);self.assertEqual(c3.requests,0)

    def test_opendota_cursor_cache_is_bound_to_actual_cursor(self):
        calls=[]
        class Client:
            def get(self,url):
                calls.append(url)
                if '?' not in url:return json.dumps([od_record(100)])
                return json.dumps([od_record(90)])
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,项目=['dota2'],扩展来源=['OpenDota'],OpenDota历史页数=2)
            c=S.SourceCollector(Path(d),cfg,NOW,Client(),lambda:False,write=False)
            c.collect([])
            self.assertIn('od-cursor:100',c.entries)
            self.assertIn('less_than_match_id=100',calls[1])

    def test_cyber_only_replaces_failed_primary_and_reuses_team_cache(self):
        class Client:
            def __init__(self):self.hist_calls=0
            def get(self,url):
                if '/en/matches/?' in url:return flight([cyber_row()])
                if '/en/matches/past/' in url:
                    self.hist_calls+=1
                    from urllib.parse import parse_qs,urlsplit
                    ident=int(parse_qs(urlsplit(url).query)['team_id'][0]);rows=[]
                    for i in range(3):
                        r=cyber_row(True);op=100+ident+i
                        r['id_series']=str(ident)+'-past-'+str(i)
                        r['team_radiant']={'id':ident,'name':'甲队' if ident==11 else '乙队'}
                        r['team_dire']={'id':op,'name':'对手'+str(op)}
                        r['best_of_score']=[2,0] if ident==11 else [0,2]
                        for j,x in enumerate(r['related_matches']):
                            x['id']=ident*100+i*2+j
                            x['team_radiant_id']=ident;x['team_dire_id']=op
                            x['winner']='radiant' if ident==11 else 'dire'
                        rows.append(r)
                    return flight(rows)
                raise TimeoutError('模拟原来源超时')
        with tempfile.TemporaryDirectory() as d:
            cfg=dict(E.DEFAULTS,项目=['dota2'],扩展来源=['CyberScore'],扩展赛程页数=1)
            client=Client()
            with patch.object(E,'load_settings',return_value=cfg),patch('esports_refs.collect',return_value={'enabled':False,'notes':[]}):
                result=E.build(Path(d),'2026-10-19',now=NOW,client=client)
                again=E.build(Path(d),'2026-10-19',now=NOW,client=client)
            self.assertEqual(len(result['picks']),1)
            self.assertEqual(result['picks'][0]['direction'],'甲队')
            self.assertEqual(again['picks'][0]['form']['home']['maps'],6)
            self.assertEqual(client.hist_calls,2)
            self.assertTrue(any(s['state']=='failed' and s['source']=='Esports8' for s in result['source_status']))

    def test_cancel_before_network(self):
        with tempfile.TemporaryDirectory() as d:
            c=S.SourceCollector(Path(d),E.DEFAULTS,NOW,None,lambda:True,write=False)
            with self.assertRaisesRegex(RuntimeError,'已停止'):c.read('OpenDota','x','url',lambda b:[])


if __name__=='__main__':unittest.main()
