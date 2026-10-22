"""离线验收：python 验证/test_reliability.py，无需联网或图形界面。"""
import ast
import copy
import json
import os
import sys
import tempfile
import unittest
from collections import Counter
from dataclasses import asdict, fields
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / '程序'))
import reliability as R
import export_500_all as E
import gen_tips as G
import commentary as CM
import composite as C
import match_model as M

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def fixture(code='周六001'):
    values = {f.name: '' for f in fields(E.Fixture)}
    values.update(sales_day='2026-10-17', code=code, league='测试联赛', home='甲队', away='乙队',
                  kickoff='2026-10-17 23:00', fetched_at='2026-10-17 18:00:00')
    return E.Fixture(**values)


class ReliabilityTests(unittest.TestCase):
    def test_fallback_after_timeout(self):
        task = E.Task('测试', E.SHEET_UPCOMING, 'https://primary/', lambda p: E.ParseOutcome((fixture(),), ''),
                      fallback_url='https://backup/')
        calls = []
        def fetch(client, address, clock):
            calls.append(address)
            if address == task.url:
                raise E.FetchError('超时')
            return E.Page(address, address, '<html/>', '2026-10-17 18:00:00')
        with patch.object(E, 'fetch_page', fetch):
            got = E.run_task(task, None, lambda: NOW)
        self.assertEqual(got.status, E.Status.SUCCESS)
        self.assertEqual(calls, [task.url, task.fallback_url])
        self.assertEqual(got.url, task.fallback_url)

    def test_fallback_after_parse_error_and_bad_encoding(self):
        for html in ('bad', '\ufffd' * (E.MOJIBAKE_LIMIT + 1)):
            task = E.Task('测试', E.SHEET_UPCOMING, 'https://a/',
                          lambda p: (_ for _ in ()).throw(ValueError('结构错误')) if p.url.endswith('a/') else E.ParseOutcome((fixture(),), ''),
                          fallback_url='https://b/')
            with patch.object(E, 'fetch_page', lambda c,u,k: E.Page(u,u,html if u.endswith('a/') else 'ok','2026-10-17 18:00:00')):
                self.assertEqual(E.run_task(task,None,lambda: NOW).status,E.Status.SUCCESS)

    def test_batch_rollback_and_success(self):
        with tempfile.TemporaryDirectory() as d:
            a,b,manifest = [Path(d)/n for n in ('a.txt','b.txt','批次.json')]
            a.write_text('old-a'); b.write_text('old-b')
            original = os.replace
            def fail_once(src, dst):
                if str(src).endswith('1.new'):
                    raise PermissionError('模拟文件占用')
                return original(src,dst)
            with patch.object(R.os,'replace',fail_once):
                with self.assertRaises(PermissionError):
                    R.atomic_batch({a:'new-a',b:'new-b'},manifest)
            self.assertEqual(a.read_text(),'old-a');self.assertEqual(b.read_text(),'old-b')
            self.assertFalse(manifest.exists())
            batch = R.atomic_batch({a:'new-a',b:'new-b'},manifest)
            self.assertEqual(json.loads(manifest.read_text())['batch_id'],batch)
            self.assertEqual(b.read_text(),'new-b')

    def test_interrupted_transaction_recovers(self):
        with tempfile.TemporaryDirectory() as d:
            parent = Path(d); stage=parent/'stage';stage.mkdir()
            a=parent/'a.txt';a.write_text('partly-updated');(stage/'0.bak').write_text('old')
            manifest=parent/'batch.json';journal=parent/'batch.json.journal'
            journal.write_text(json.dumps({'state':'prepared','stage':str(stage),'files':[
                {'target':str(a),'backup':'0.bak','new':'0.new','existed':True}]}))
            R._recover(journal)
            self.assertEqual(a.read_text(),'old');self.assertFalse(stage.exists())

    def test_freshness_gate(self):
        wb={'采集状态':[{'栏目':'竞彩足球赛程 2026-10-17','状态':'成功'}],
            '竞足-今日未开赛':[{'抓取时间(北京时间)':'2026-10-17 18:00:00'}]}
        self.assertTrue(G.validate_live_workbook(wb,'2026-10-17',now=NOW.replace(tzinfo=None)))
        for state in ('失败','沿用旧数据'):
            bad=copy.deepcopy(wb);bad['采集状态'][0]['状态']=state
            with self.assertRaises(G.TipsError):G.validate_live_workbook(bad,'2026-10-17',now=NOW.replace(tzinfo=None))
        wb['竞足-今日未开赛'][0]['抓取时间(北京时间)']='2026-10-16 18:00:00'
        with self.assertRaises(G.TipsError):G.validate_live_workbook(wb,'2026-10-17',now=NOW.replace(tzinfo=None))
        with self.assertRaises(G.TipsError):G.validate_live_workbook({},'2026-10-17')

    def test_date_groups_never_cross_segments(self):
        rows=[{'k':f'2026-09-{i:02} 20:00','id':j} for i in range(1,21) for j in range(3)]
        tr,va,te=R.date_split(rows,lambda r:r['k'])
        dates=[{r['k'][:10] for r in x} for x in (tr,va,te)]
        self.assertTrue(all(dates));self.assertFalse(dates[0]&dates[1]);self.assertFalse(dates[1]&dates[2])
        self.assertLess(max(dates[0]),min(dates[1]));self.assertLess(max(dates[1]),min(dates[2]))

    def test_retry_retains_successful_tasks_and_only_requests_failure(self):
        with tempfile.TemporaryDirectory() as d:
            tasks=[E.Task('成功项',E.SHEET_UPCOMING,'https://a/',lambda p: None,day='2026-10-17'),
                   E.Task('失败项',E.SHEET_UPCOMING,'https://b/',lambda p: None,day='2026-10-17')]
            resume={'items':[{'item':'成功项','status':'成功','note':'','url':'https://a/',
                    'fetched_at':'2026-10-17 18:00:00','rows':[{'type':'Fixture','data':asdict(fixture())}]}]}
            opts=E.RunOptions(end_day=date(2026,10,17),days=2,extra_urls=(),output=Path(d)/'test.xlsx')
            called=[]
            def run(task,*args):
                called.append(task.key)
                return E.TaskResult(task,E.Status.SUCCESS,(fixture('周六002'),),'',task.url,'2026-10-17 18:00:00')
            with patch.object(E,'run_task',run):
                report=E.execute(tasks,None,opts,clock=lambda:NOW,resume=resume)
            self.assertEqual(called,['失败项']);self.assertEqual(report.counts[E.Status.SUCCESS],2)
            self.assertEqual(len(E.read_sheet(report.saved,E.SHEET_UPCOMING)),2)
            summary=Path(d)/'summary.json';E.write_summary(summary,report,opts)
            self.assertEqual(len(json.loads(summary.read_text())['items']),2)

    def test_comments_plain(self):
        out={'items':[{'lines':[{'text':'第一句。\n第二句。'},{'text':'第一句。 第二句。'},{'text':'另一条评论。'}]}],
             'intro':['不导出总评'],'asks':['不导出提问'],'recap':[]}
        self.assertEqual(CM.render_text(out),'第一句。 第二句。\n另一条评论。\n')
        self.assertEqual(G.SHOW_KW,1);self.assertEqual(G.SHOW_CM,1)

    def test_model_rejects_candidate_that_fails_test(self):
        # 训练和验证支持增加模型占比，末段反转后必须保留默认权重。
        picks={}
        for i in range(200):
            dt=(datetime(2026,1,1)+timedelta(days=i)).strftime('%Y-%m-%d')
            picks[str(i)]={'date':dt,'status':'hit' if i<160 else 'miss','cp_x':True,'cp_m':0.5,'cp_q':0.95}
        out=C.fit_weight({'picks':picks})
        self.assertFalse(out['changed']);self.assertIn('test_gain',out);self.assertLess(out['test_gain'],0)

    def test_gui_fetch_abnormal_return_and_timeout(self):
        source=Path(__file__).resolve().parents[1]/'程序'/'tips_console.pyw'
        tree=ast.parse(source.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
        method=next(n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name=='_fetch')
        class FakeTimer:
            fire=False
            def __init__(self, seconds, callback):self.callback=callback
            def start(self):
                if self.fire:self.callback()
            def cancel(self):pass
        class Proc:
            stdout=[]
            def wait(self):return -15
            def terminate(self):pass
        with tempfile.TemporaryDirectory() as d:
            import threading,queue
            ns={'Optional':object, 'Path':Path} # annotations postponed for isolated compilation
            import __future__
            ns.update(threading=SimpleNamespace(Event=threading.Event,Timer=FakeTimer),
                      subprocess=SimpleNamespace(Popen=lambda *a,**kw:Proc(),PIPE=-1,STDOUT=-2,DEVNULL=-3),
                      os=os, L=SimpleNamespace(d=lambda *a:Path(d),DAY=''),APP_DIR=Path(d),BACKFILL_DIR=Path(d),
                      EXPORT=Path(d)/'export.py',EXPORT_TIMEOUT=1,child_python=lambda:sys.executable,beijing_now=R.beijing_now)
            exec(compile(ast.Module(body=[method],type_ignores=[]),'fetch-test','exec',flags=__future__.annotations.compiler_flag),ns)
            obj=SimpleNamespace(q=queue.Queue(),settings={},cancel=threading.Event())
            self.assertIn('异常退出',ns['_fetch'](obj))
            FakeTimer.fire=True
            self.assertIn('超时',ns['_fetch'](obj))

    def test_full_excel_to_exports_pipeline(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d); xlsx=folder/'500网数据_2026-10-17.xlsx'
            specs=E.specs_for_mode(E.MODE_FOCUS,False)
            states=[E.StatusRecord('竞彩足球赛程 2026-10-17',E.Status.SUCCESS,1,'','','2026-10-17 18:00:00')]
            E.save_workbook(xlsx,[(sp,[fixture()] if sp.name==E.SHEET_UPCOMING else states if sp.name==E.SHEET_STATUS else [])
                                for sp in specs],created=NOW,allow_fallback=False)
            res=G.run(xlsx,folder/'tips_history.json',output=folder,day='2026-10-17',include_esports=False,
                      now=NOW.replace(tzinfo=None),strict_live=True)
            for key in ('txt','kw_txt','cm_txt'):
                self.assertTrue(Path(res[key]).exists())
            self.assertEqual(json.loads((folder/'导出批次_2026-10-17.json').read_text())['batch_id'],res['batch_id'])
            self.assertTrue((folder/'tips_history.json').exists())
            self.assertGreater(res['comments']['n_line'],0)
            self.assertFalse(any(not x.strip() for x in Path(res['cm_txt']).read_text().splitlines()))

    def test_comment_next_persists_batch_and_restore(self):
        source=Path(__file__).resolve().parents[1]/'程序'/'tips_console.pyw'
        tree=ast.parse(source.read_text())
        cls=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
        methods=[n for n in cls.body if isinstance(n,ast.FunctionDef) and n.name in ('cm_next','_show_cm')]
        import __future__
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d); last=folder/'console_last_run.json'
            ns={'Path':Path,'APP_DIR':folder,'LAST':last,'json':json,'atomic_batch':R.atomic_batch,
                'L':SimpleNamespace(p=lambda folder,name:folder/name)}
            exec(compile(ast.Module(body=methods,type_ignores=[]),'comment-test','exec',flags=__future__.annotations.compiler_flag),ns)
            selected={'value':'数据官'}
            var=SimpleNamespace(get=lambda:selected['value'],set=lambda value:selected.update(value=value))
            out={'day':'2026-10-17','seed':1,'text':'新评论。\n','plain':'新评论。\n','n_match':1,'n_line':1}
            obj=SimpleNamespace(busy=False,cm={'data':{'matches':[1]}},cm_seed=0,cm_out=None,result={'blocks':[]},
                                cm_who=var,_set_status=lambda *args:None,CM_ALL='全部人设')
            obj._cm_recompose=lambda:setattr(obj,'cm_out',out)
            ns['cm_next'](obj)
            saved=json.loads(last.read_text())
            self.assertEqual(saved['comments']['out']['seed'],1)
            self.assertEqual(saved['comments']['only'],'数据官')
            self.assertEqual((folder/'评论话术_2026-10-17.txt').read_text(),'新评论。\n')
            obj.cm_seed=0;selected['value']='全部人设'
            ns['_show_cm'](obj,saved['comments'])
            self.assertEqual(obj.cm_seed,1);self.assertEqual(selected['value'],'数据官')

    def test_backtest_reports_only_heldout_dates(self):
        samples=[{'k':(datetime(2025,1,1)+timedelta(days=i)).isoformat(),
                  'p':(0.6,0.2,0.2),'y':0,'prior':(0.45,0.27,0.28),'o25':0.5,'ov':0,'ovp':0.5}
                 for i in range(200)]
        dummy=[{'k':s['k'],'lg':'联赛'} for s in samples]
        with patch.object(M,'_collect',return_value=samples):
            result=M.backtest(dummy)
        self.assertEqual(result['sample_total'],200)
        self.assertEqual(result['n'],40)
        self.assertEqual(result['split'],{'train':120,'validation':40,'test':40})


if __name__=='__main__':unittest.main(verbosity=2)
