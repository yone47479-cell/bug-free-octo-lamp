"""外部电竞参考：价格口径、时间/项目/队名隔离、来源状态，不联网。"""
import copy,json,sys,tempfile,unittest
from datetime import datetime,timedelta,timezone
from pathlib import Path
from urllib.parse import urlsplit,parse_qs
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).parents[1]/'程序'))
import esports_refs as R
import esports_data as E
NOW=datetime(2026,10,19,12,tzinfo=timezone.utc)

def pick(game='csgo'):
    return {'game':game,'home':'NAVI','away':'G2','bo':3,'direction':'NAVI', 'fixture':{'start':(NOW+timedelta(hours=2)).timestamp(),'event':'Worlds'}}
def event(game='csgo'):
    return {'slug':'sample-event','tags':[{'slug':next(iter(R.GAME_TAGS[game]))}],'markets':[]}
def market():
    return {'id':'sample','active':True,'closed':False,'sportsMarketType':'moneyline','line':None,
            'question':'Counter-Strike: Natus Vincere vs G2 Esports (BO3)','outcomes':json.dumps(['G2 Esports','Natus Vincere']),
            'outcomePrices':json.dumps(['0.35','0.65']),'gameStartTime':(NOW+timedelta(hours=2)).isoformat(),
            'bestBid':.34,'bestAsk':.36,'liquidityNum':5000,'updatedAt':NOW.isoformat()}
def script(page):return '<script id="__NEXT_DATA__" type="application/json">'+json.dumps({'props':{'pageProps':page}})+'</script>'
def opgg():return script({'leagues':[{'shortName':'Worlds','latestSerie':{'year':2026,'beginAt':(NOW-timedelta(days=5)).isoformat(),'endAt':(NOW+timedelta(days=10)).isoformat()}}]})
def ubi():return script({'pageData':{'competition':{'id':502,'name':'测试R6赛事'},'phases':[{'closeAt':(NOW-timedelta(days=100)).isoformat()}],'competitionDetails':{'competition':{'endDate':(NOW-timedelta(days=99)).isoformat()}}}})

class EsportsReferenceTests(unittest.TestCase):
    def test_outcome_order_aliases_and_quotes_not_win_probability(self):
        r=R.match_market(pick(),event(),market(),NOW,R.DEFAULTS)
        self.assertEqual(r['state'],'matched');self.assertAlmostEqual(r['home_price'],.65);self.assertAlmostEqual(r['away_price'],.35)
        self.assertIn('不是模型胜率',r['message']);self.assertNotEqual(R.alias_key('NAVI Junior'),R.alias_key('NAVI'))
    def test_market_type_and_period_gates(self):
        for extra in ({'sportsMarketType':'child_moneyline'},{'sportsMarketType':'totals'},{'line':1.5},{'question':'NAVI vs G2 - Map 1 Winner'}, {'question':'NAVI vs G2 (BO5)'},{'question':'NAVI Tournament Winner'}):
            self.assertIsNone(R.match_market(pick(),event(),dict(market(),**extra),NOW,R.DEFAULTS))
    def test_outright_yes_no_not_used(self):
        m=market();m.update(outcomes='["Yes","No"]',question='Will NAVI win Worlds?',sportsMarketType=None)
        self.assertIsNone(R.match_market(pick(),event(),m,NOW,R.DEFAULTS))
    def test_wrong_game_teams_or_date_rejected(self):
        self.assertIsNone(R.match_market(pick(),event('lol'),market(),NOW,R.DEFAULTS))
        self.assertIsNone(R.match_market(pick(),dict(event(),tags=None),market(),NOW,R.DEFAULTS))
        for extra in ({'outcomes':'["NAVI Junior","G2"]'},{'gameStartTime':(NOW+timedelta(days=1)).isoformat()},{'gameStartTime':None,'endDate':(NOW+timedelta(hours=2)).isoformat()}):
            self.assertIsNone(R.match_market(pick(),event(),dict(market(),**extra),NOW,R.DEFAULTS))
    def test_closed_live_and_invalid_price_rejected(self):
        for extra in ({'closed':True},{'active':False},{'gameStartTime':(NOW-timedelta(seconds=1)).isoformat()},{'outcomePrices':'["NaN","0.2"]'},{'outcomePrices':'["0.1","0.2"]'},{'outcomes':'["NAVI","NAVI"]'}):
            self.assertIsNone(R.match_market(pick(),event(),dict(market(),**extra),NOW,R.DEFAULTS))
    def test_liquidity_spread_and_stale_quote_only_report(self):
        for extra in ({'liquidityNum':10},{'bestAsk':.9},{'bestBid':None},{'updatedAt':(NOW-timedelta(hours=1)).isoformat()}):
            result=R.match_market(pick(),event(),dict(market(),**extra),NOW,R.DEFAULTS)
            self.assertEqual(result['state'],'quality_limited');p=pick();p['references']=[result];self.assertEqual(R.render_match_refs(p),[])
    def test_market_disagreement_only_annotated(self):
        p=pick();m=dict(market(),outcomePrices='["0.7","0.3"]')
        q=R.match_market(p,event(),m,NOW,R.DEFAULTS);self.assertTrue(q['disagreement']);p['references']=[q]
        self.assertIn('市场方向与近况模型有分歧。',R.render_match_refs(p));self.assertEqual(p['direction'],'NAVI')
    def test_opgg_metadata_not_fake_votes(self):
        info=R.opgg_metadata(opgg(),NOW);self.assertEqual(info['state'],'metadata_only');self.assertNotIn('votes',info);self.assertEqual(info['game'],'lol')
    def test_ubisoft_locked_r6_not_cross_applied(self):
        info=R.ubisoft_metadata(ubi(),NOW);self.assertEqual(info['state'],'archived_locked');self.assertEqual(info['game'],'r6')
    def test_chaofan_schedule_validation(self):
        p=pick('lol');rows=R.chaofan_schedule({'code':0,'data':{'list':[{'id':'x','game_id':1,'home':{'name':'NAVI'},'away':{'name':'G2'},'box':3,'start_time':p['fixture']['start']}]}})
        self.assertEqual(R.match_schedule(p,rows)['state'],'matched');rows[0]['bo']=5;self.assertEqual(R.match_schedule(p,rows)['state'],'conflict')
        self.assertIsNone(R.match_schedule(pick(),rows))
    def test_collect_integrates_four_statuses_and_date_filtered_request(self):
        requests=[];p=pick();base=copy.deepcopy(p);ev=event();ev['markets']=[market()]
        class Client:
            def get(self,url):
                requests.append(url)
                if 'esports.op.gg' in url:return opgg()
                if 'ubisoft' in url:return ubi()
                if 'api-pc.chaofan.com' in url:return json.dumps({'code':0,'data':{'list':[]}})
                if url.endswith('/sports'):return json.dumps([{'sport':'cs2','series':'10310'}])
                return json.dumps([ev])
        with tempfile.TemporaryDirectory() as d:
            result=R.collect(Path(d),[p],NOW,Client(),write=False)
            self.assertFalse(list(Path(d).iterdir()))
        self.assertEqual(len(result['sources']),4);self.assertEqual(p['direction'],base['direction']);self.assertIn('0.65',p['reference_lines'][0])
        urls=[u for u in requests if '/events?' in u];self.assertEqual(len(urls),1)
        q=parse_qs(urlsplit(urls[0]).query);self.assertIn('start_time_min',q);self.assertIn('start_time_max',q);self.assertEqual(q['closed'],['false'])
        self.assertFalse(any('/orders' in u or '/login' in u for u in requests))
    def test_no_candidates_does_not_fetch_unrelated_markets(self):
        class Client:
            def get(self,url):
                if 'gamma-api' in url:raise AssertionError('unrelated')
                raise OSError('offline')
        with tempfile.TemporaryDirectory() as d:result=R.collect(Path(d),[],NOW,Client(),write=False)
        poly=next(x for x in result['sources'] if x['name']=='Polymarket');self.assertEqual(poly['state'],'no_candidates')
    def test_disabled_no_network(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'电竞参考设置.json').write_text('{"启用":false}')
            self.assertFalse(R.collect(root,[pick()],NOW,None,write=False)['enabled'])
    def test_bad_config_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);(root/'电竞参考设置.json').write_text('{"最低流动性":"nan"}')
            with self.assertRaises(ValueError):R.load_settings(root)
    def test_cancel_does_not_query(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(RuntimeError):R.collect(Path(d),[pick()],NOW,None,write=False,cancel=lambda:True)

if __name__=='__main__':unittest.main()
