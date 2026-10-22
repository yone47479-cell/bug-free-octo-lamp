"""v3.1.3 离线回归：故障保留、内容签名与原子缓存。"""
import argparse,copy,json,sys,tempfile,unittest
from dataclasses import fields,replace
from datetime import datetime,date,timezone,timedelta
from functools import partial
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import reliability as R
import match_model as M
import team_data as T
import export_500_all as E
import sina_data as S
NOW=datetime(2026,10,19,18,tzinfo=timezone(timedelta(hours=8)))

def draw(name='排列3',**extra):
    values={f.name:'' for f in fields(E.DrawResult)}
    values.update(lottery=name,issue='2026280',draw_date='2026-10-18',numbers='1 2 3',fetched_at='2026-10-18 22:00:00')
    values.update(extra);return E.DrawResult(**values)
def zc(game='4场进球'):
    values={f.name:'' for f in fields(E.ZucaiResult)}
    values.update(game=game,issue='26001',draw_date='2026-10-18',seq='1',result='3',fetched_at='2026-10-18 22:00:00')
    return E.ZucaiResult(**values)
def task(name='排列3',keep=True):
    return E.Task(name+' 开奖',E.SHEET_DRAWS,'https://open.500.com/test',lambda p:E.ParseOutcome(),reuse_tag=('lottery',name),view=partial(E.drawn_view,keep_older=keep))
def result(t,status=E.Status.FAILED,rows=()):return E.TaskResult(t,status,rows,'模拟超时',t.url,'2026-10-19 18:00:00')

class V313Tests(unittest.TestCase):
    def test_draw_roundtrip_workbook(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'old.xlsx'
            E.write_workbook(p,[(E.DRAW_SPEC,[draw()]),(E.ZC_SETTLED_SPEC,[zc()])],created=NOW)
            got=E.load_previous(p,(E.DRAW_SPEC,E.ZC_SETTLED_SPEC))
            self.assertEqual(got[E.SHEET_DRAWS],[draw()]);self.assertEqual(got[E.SHEET_ZC_SETTLED],[zc()])
    def test_failure_preserves_only_requested_lottery(self):
        got=E.finalize(result(task()),{E.SHEET_DRAWS:[draw(),draw('排列5')]},NOW)
        self.assertIs(got.status,E.Status.STALE);self.assertEqual(len(got.rows),1);self.assertEqual(got.rows[0].lottery,'排列3')
        self.assertEqual(got.rows[0].fetched_at,'2026-10-18 22:00:00');self.assertIn('旧数据',got.note)
    def test_legitimate_empty_not_replaced(self):
        got=E.finalize(result(task(),E.Status.NO_DATA),{E.SHEET_DRAWS:[draw()]},NOW)
        self.assertIs(got.status,E.Status.NO_DATA);self.assertFalse(got.rows)
    def test_fresh_result_wins(self):
        got=E.finalize(result(task(),E.Status.SUCCESS,(draw(numbers='4 5 6'),)),{E.SHEET_DRAWS:[draw()]},NOW)
        self.assertIs(got.status,E.Status.SUCCESS);self.assertEqual(got.rows[0].numbers,'4 5 6')
    def test_old_draw_still_filtered_by_date(self):
        got=E.finalize(result(task(keep=False)),{E.SHEET_DRAWS:[draw(draw_date='2026-10-17')]},NOW)
        self.assertFalse(got.rows);self.assertIs(got.status,E.Status.STALE)
    def test_traditional_lottery_separated_by_game(self):
        t=replace(task(),sheet=E.SHEET_ZC_SETTLED,reuse_tag=('game','4场进球'))
        got=E.finalize(result(t),{E.SHEET_ZC_SETTLED:[zc(),zc('6场半全场')]},NOW)
        self.assertEqual(len(got.rows),1);self.assertEqual(got.rows[0].game,'4场进球')
    def test_build_tasks_scope_all_draws(self):
        ts=E.build_tasks(date(2026,10,19),2,[],mode=E.MODE_FOCUS,keep_older_draws=True)
        draws=[t for t in ts if t.sheet==E.SHEET_DRAWS];zcrows=[t for t in ts if t.sheet==E.SHEET_ZC_SETTLED]
        self.assertEqual(len(draws),7);self.assertTrue(all(t.reuse_tag[0]=='lottery' for t in draws));self.assertTrue(all(t.reuse_tag[0]=='game' for t in zcrows))
    def test_atomic_write_failure_keeps_original_and_cleans_temp(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'x.json';p.write_text('original')
            with patch.object(R.os,'replace',side_effect=PermissionError('busy')):
                with self.assertRaises(PermissionError):R.atomic_write_text(p,'new')
            self.assertEqual(p.read_text(),'original');self.assertEqual([x.name for x in Path(d).iterdir()],['x.json'])
            R.atomic_write_text(p,'new');self.assertEqual(p.read_text(),'new')
    def test_cache_future_and_bad_shape_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            c=T.Client('',T.FOOTBALL_BASE,Path(d),T.Budget(90))
            for stamp in (2001,'NaN','Infinity'):
                c._cpath('x').write_text(json.dumps({'ck':'x','t':stamp,'data':['old']}))
                with patch.object(T.time,'time',return_value=2000):self.assertIsNone(c._cache_read('x',3600))
            c._cpath('x').write_text('[]');self.assertIsNone(c._cache_read('x',3600))
    def test_empty_cache_is_valid_until_expiry(self):
        with tempfile.TemporaryDirectory() as d:
            c=T.Client('',T.FOOTBALL_BASE,Path(d),T.Budget(90))
            with patch.object(T.time,'time',return_value=100):c._cache_write('x',[])
            with patch.object(T.time,'time',return_value=120):self.assertEqual(c._cache_read('x',30),[])
            with patch.object(T.time,'time',return_value=130):self.assertIsNone(c._cache_read('x',30))
    def test_fingerprint_detects_corrected_scores_and_aliases(self):
        rows=[{'k':'2026-10-18 21:00','h':'甲','a':'乙','hs':1,'as':0,'lg':'测试'}]
        before=copy.deepcopy(rows);sig=M.results_fingerprint(rows)
        for field,value in [('hs',2),('as',1),('lg','另一联赛'),('k','2026-10-18 22:00')]:
            amended=copy.deepcopy(rows);amended[0][field]=value;self.assertNotEqual(sig,M.results_fingerprint(amended))
        self.assertNotEqual(sig,M.results_fingerprint(rows,lambda s:'丙' if s=='甲' else s));self.assertEqual(before,rows)
    def test_unchanged_model_cache_reused_score_correction_rechecks(self):
        with tempfile.TemporaryDirectory() as d:
            rows=[{'k':'2026-10-18 21:00','h':'甲','a':'乙','hs':1,'as':0,'lg':'测试'}]
            db=SimpleNamespace(rows=rows,names=SimpleNamespace(canon=lambda s:s))
            with patch.object(M,'backtest',return_value={'n':100,'ok':False}) as bt,patch.object(M,'beijing_now',return_value=NOW.replace(tzinfo=None)):
                M.run_check(Path(d),db,tune=False);M.run_check(Path(d),db,tune=False)
                self.assertEqual(bt.call_count,1)
                rows[0]['hs']=2;M.run_check(Path(d),db,tune=False);self.assertEqual(bt.call_count,2)
    def test_model_save_error_explained_and_original_kept(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/M.CHECK_FILE;p.write_text('{}');messages=[]
            db=SimpleNamespace(rows=[],names=SimpleNamespace(canon=lambda s:s))
            with patch.object(M,'backtest',return_value={'n':0}),patch.object(M,'atomic_write_text',side_effect=PermissionError('busy')):
                M.run_check(Path(d),db,tune=False,log=messages.append)
            self.assertEqual(p.read_text(),'{}');self.assertTrue(any('未能保存' in x for x in messages))
    def test_sina_cache_atomic_write_and_expiration(self):
        with tempfile.TemporaryDirectory() as d:
            fetcher=S.Fetcher(Path(d))
            data={'url':'https://sports.sina.com.cn/example','t':100,'text':'测试','links':[]}
            fetcher._write_cache(data)
            with patch.object(S.time,'time',return_value=110):
                self.assertEqual(fetcher._read_cache(data['url'],20),data)
            with patch.object(S.time,'time',return_value=99):
                self.assertIsNone(fetcher._read_cache(data['url'],20))
            original=fetcher._cpath(data['url']).read_bytes()
            with patch.object(S,'atomic_write_text',side_effect=PermissionError('busy')):
                fetcher._write_cache(dict(data,text='new'))
            self.assertEqual(fetcher._cpath(data['url']).read_bytes(),original)
            fetcher._cpath(data['url']).write_text('[]')
            self.assertIsNone(fetcher._read_cache(data['url'],20))

    def test_network_parameters_reject_infinity(self):
        for convert in (E.positive_float,E.non_negative_float):
            for value in ('inf','-inf','nan'):
                with self.assertRaises(argparse.ArgumentTypeError):convert(value)
            self.assertEqual(convert('1.5'),1.5)

if __name__=='__main__':unittest.main()
