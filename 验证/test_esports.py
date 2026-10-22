"""电竞比分扩展：不联网，不把示例数据当真实推荐。"""
import ast,copy,json,math,sys,tempfile,unittest
from pathlib import Path
from datetime import datetime,timedelta,timezone
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'程序'))
import esports_data as E
import gen_tips as G
import guard as GD
import export_500_all as W
from test_reliability import fixture as football_fixture,NOW as FOOT_NOW
NOW=datetime(2026,10,19,18,tzinfo=E.BJT)

def fixture():
    return {'id':'sample','game':'csgo','home':'示例甲','away':'示例乙','start':int((NOW+timedelta(hours=3)).timestamp()),'bo':3,'status':'upcoming','score':None,'event':'离线测试赛事','source':'Esports8','url':'https://www.esports8.com/en/csgo/match/sample','fetched':NOW.timestamp()}
def maps(wins=9):
    return {'home':[{'at':NOW.timestamp()-10000-i,'win':int(i<wins),'series':'A'+str(i//2)} for i in range(10)],
            'away':[{'at':NOW.timestamp()-20000-i,'win':int(i<2),'series':'B'+str(i//2)} for i in range(10)]}

def page():
    return '<script>window.__NUXT__=(function(a,b,c){c.home={name:"示例甲",score:a};c.away={name:"示例乙",score:a};c.box=3;c.id="sample";c.game_id=2;c.status_id=1;c.start_time=b;return {state:{home:{unfinished:[c]}}};}(0,'+str(fixture()['start'])+',{}));</script>'

class EsportsTests(unittest.TestCase):
    def test_data_only_nuxt_assignments_refs_and_date(self):
        st=E.parse_nuxt(page());rows=E.extract_esports8(st,'https://www.esports8.com/en/csgo',NOW.timestamp())
        self.assertEqual(len(rows),1);self.assertEqual(rows[0]['bo'],3);self.assertEqual(rows[0]['status'],'upcoming')
        st=E.parse_nuxt('<script>window.__NUXT__=(function(a){return {x:a,n:.9,d:new Date(12)}}(null));</script>')
        self.assertAlmostEqual(st['n'],.9);self.assertEqual(st['d'],{'$date':12})
    def test_script_not_executed_and_prototype_rejected(self):
        for text in ('(function(a){return alert(1)}(null));','(function(a){a.__proto__={};return a}({}));','(function(a){return eval("1")}({}));'):
            with self.assertRaises(E.DataScriptError):E.parse_nuxt('<script>window.__NUXT__='+text+'</script>')
    def test_bo1_rounds_and_bo3_series_never_mixed(self):
        self.assertEqual(E.final_series_score('csgo',1,13,8),(1,0))
        self.assertEqual(E.final_series_score('csgo',1,11,13),(0,1))
        self.assertIsNone(E.final_series_score('csgo',1,13,12))
        self.assertIsNone(E.final_series_score('csgo',3,13,8))
        self.assertEqual(E.final_series_score('csgo',3,2,1),(2,1))
        self.assertIsNone(E.final_series_score('lol',1,20,15))
    def test_5e_schema_and_status(self):
        r={'mc_info':{'id':'x','format':'1','game_type':'csgo','plan_ts':str(fixture()['start']),'t1_info':{'disp_name':'甲队'},'t2_info':{'disp_name':'乙队'}},'state':{'status':'2','t1_score':'13','t2_score':'8'}}
        got=E.extract_5e({'success':True,'data':{'matches':[r]}},'https://app.5eplay.com/test',NOW.timestamp())
        self.assertEqual(got[0]['score'],[1,0]);self.assertEqual(got[0]['status'],'finished')
    def test_merge_reversed_sides_conflicts_and_academy(self):
        a=fixture();a.update(status='finished',score=[2,1])
        b=dict(a,home=a['away'],away=a['home'],source='5EPlay',score=[1,2]);merged=E.merge_matches([a,b])
        self.assertEqual(len(merged),1);self.assertFalse(merged[0]['conflict']);self.assertEqual(len(merged[0]['sources']),2)
        b['score']=[2,0];self.assertTrue(E.merge_matches([a,b])[0]['conflict'])
        self.assertNotEqual(E.team_key('Team Academy'),E.team_key('Team'))
        self.assertFalse(E.known_team('A/B winner'));self.assertFalse(E.known_team('TBD'))
    def test_live_status_prevents_prediction_candidate(self):
        rows=E.merge_matches([fixture(),dict(fixture(),status='live',source='5EPlay')]);self.assertEqual(rows[0]['status'],'live')
    def test_distribution_sums_and_scores_legal(self):
        for bo in (1,3,5,7):
            for p in (.25,.5,.75):
                dist=E.score_distribution(p,bo);self.assertAlmostEqual(sum(v[2] for v in dist),1)
                self.assertTrue(all(max(a,b)==bo//2+1 and a!=b for a,b,_ in dist))
        with self.assertRaises(ValueError):E.score_distribution(.5,2)
    def test_sample_gate_and_series_count(self):
        self.assertIsNotNone(E.predict(fixture(),maps(),E.DEFAULTS))
        small=maps();small['home']=small['home'][:3];self.assertIsNone(E.predict(fixture(),small,E.DEFAULTS))
        single=maps()
        for r in single['home']:r['series']='single'
        self.assertIsNone(E.predict(fixture(),single,E.DEFAULTS))
        same=maps();same['away']=copy.deepcopy(same['home']);self.assertIsNone(E.predict(fixture(),same,E.DEFAULTS))
    def test_future_form_excluded_and_map_count_not_series(self):
        f=fixture();recent=[]
        for i in range(10):
            recent.append({'game_id':2,'match_time':int(NOW.timestamp()-1000-i),'stats':[13,8],'match_id':str(i//2),'box_num':i%2+1,'map_name':'测试图'})
        future=dict(recent[0],match_time=int(NOW.timestamp()+400),match_id='future')
        state={'state':{'matchAnalysis':{'recentData':{'home_team':{'name':f['home'],'recent':recent+[future]},'away_team':{'name':f['away'],'recent':recent}}}}}
        got=E.recent_cs_maps(state,f,NOW);self.assertEqual(len(got['home']),10);self.assertEqual(len({r['series'] for r in got['home']}),5)
    def test_finished_history_excludes_future_other_game(self):
        f=fixture();r=dict(f,status='finished',start=NOW.timestamp()-86400,score=[2,0])
        got=E.history_maps([r,dict(r,game='lol'),dict(r,start=NOW.timestamp()+100)],f,NOW)
        self.assertEqual(len(got['home']),2);self.assertEqual(len(got['away']),2)
    def test_post_has_prediction_and_no_calibrated_probability_claim(self):
        f=fixture();f['sources']=[];p=E.predict(f,maps(),E.DEFAULTS);text=E.article([p],'2026-10-19')
        self.assertIn('电竞预测1场',text);self.assertIn('比分参考',text);self.assertIn('近10图',text);self.assertNotIn('近10场',text);self.assertNotIn('%',text)
    def test_disabled_no_network_or_fake_pick(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);(folder/'电竞设置.json').write_text(json.dumps({'启用':False}))
            with patch.object(E.PublicClient,'get',side_effect=AssertionError('network')):out=E.build(folder,'2026-10-19',now=NOW)
            self.assertFalse(out['enabled'])
    def test_network_failures_do_not_invent_matches(self):
        with tempfile.TemporaryDirectory() as d:
            client=type('Client',(),{'get':lambda self,url:(_ for _ in ()).throw(OSError('offline'))})()
            out=E.build(Path(d),'2026-10-19',now=NOW,client=client,write=False)
            self.assertFalse(out['picks']);self.assertIn('暂不推荐',out['text']);self.assertFalse(list(Path(d).iterdir()))
    def test_config_rejects_nan_and_invalid_project(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);p=folder/'电竞设置.json'
            p.write_text(json.dumps({'最小单图倾向差':float('nan')}))
            with self.assertRaises(ValueError):E.load_settings(folder)
            p.write_text(json.dumps({'项目':['fake']}))
            with self.assertRaises(ValueError):E.load_settings(folder)
    def test_esports_preflight_flags_started_and_deadline(self):
        posts=[('电竞预测','电竞测试')]
        picks=[{'play':'电竞','market':'系列赛','key':'sample','home':'甲队','away':'乙队','kick':'2026-10-19 17:00'}]
        checks=GD.preflight(posts,picks,NOW.replace(tzinfo=None))
        self.assertTrue(any(x['code']=='started' and x['post']=='电竞预测' for x in checks))
        rows=GD.deadlines(posts,picks,{},NOW.replace(tzinfo=None))
        self.assertIn(rows[0]['status'],('done','started'))

    def test_integration_appends_single_article_without_soccer_settlement_mix(self):
        # 在既有足球流程样例上注入独立电竞结果，不联网。
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);xlsx=folder/'500网数据_2026-10-17.xlsx'
            W.write_workbook(xlsx,[(W.UPCOMING_SPEC,[football_fixture()])],created=FOOT_NOW)
            report={'enabled':True,'text':'2026-10-17 周六｜电竞预测1场\n测试甲 VS 测试乙\n🎯 方向：测试甲胜\n🥅 比分参考：2:0 / 2:1','picks':[{'game':'csgo'}],'notes':[]}
            with patch.object(G.ES,'build',return_value=report):
                res=G.run(xlsx,folder/'tips_history.json',output=folder,day='2026-10-17',save=False,include_esports=True,now=FOOT_NOW.replace(tzinfo=None))
            self.assertEqual(sum(p['name']=='电竞预测' for p in res['posts']),1)
            self.assertTrue((folder/'电竞推单_2026-10-17.txt').exists())
            self.assertEqual(res['esports']['picks'],report['picks'])

if __name__=='__main__':unittest.main()
