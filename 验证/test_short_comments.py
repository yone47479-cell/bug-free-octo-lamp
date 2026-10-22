"""简短评论生成：长度、去重、迁移、事实门槛和换批验收。"""
import sys,unittest,tempfile,json,copy
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import commentary as C


def data(recommend=True):
    entries=[]
    for home,away in [('阿森纳','切尔西'),('皇马','巴萨'),('拜仁','多特蒙德')]:
        picks=[{'play':'竞足','market':'胜平负','label':'胜','home':home,'away':away,'kick':'2026-10-17 23:00'}] if recommend else []
        entries.append({'home':home,'away':away,'lg':'测试联赛','kick':'2026-10-17 23:00','picks':picks,'plays':['竞足']})
    return C.collect('2026-10-17',entries,{'stars':False,'cp':False,'score':False,'basis':False})


class ShortCommentsTests(unittest.TestCase):
    def test_legacy_library_gets_new_bank_without_deleting_custom_data(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'话术库.json';old=C.lib_default_json();old.pop('简短评论');old['自定义备注']='保留'
            path.write_text(json.dumps(old,ensure_ascii=False))
            C.ensure_lib_file(path)
            self.assertIn('简短评论',json.loads(path.read_text()))
            self.assertEqual(json.loads(path.read_text())['自定义备注'],'保留')
            lib,warnings=C.load_lib(path)
            out=C.compose(data(),lib,max_len=110,emoji=True)
            self.assertGreater(out['n_line'],0)
            self.assertTrue(all(len(line)<=48 for line in out['plain'].splitlines()))

    def test_length_plain_unique_and_repeatable(self):
        lib,_=C.load_lib(None);facts=data()
        out=C.compose(facts,lib,seed=0,max_len=110,emoji=True)
        lines=out['plain'].splitlines()
        self.assertEqual(len(lines),len(set(lines)))
        self.assertEqual(len(lines),out['n_line'])
        self.assertEqual(out['plain'],C.compose(facts,lib,seed=0,max_len=110,emoji=True)['plain'])
        self.assertNotEqual(out['plain'],C.compose(facts,lib,seed=1,max_len=110,emoji=True)['plain'])
        for line in lines:
            self.assertLessEqual(len(line),48)
            self.assertNotIn('【',line)
            self.assertNotIn('数据模型',line)
            self.assertNotIn('口径',line)
            self.assertNotIn('样本',line)
            self.assertNotIn('🧮',line)

    def test_without_facts_does_not_invent_them(self):
        lib,_=C.load_lib(None)
        out=C.compose(data(False),lib)
        for line in out['plain'].splitlines():
            self.assertFalse(any(t in line for t in ('胜','近6场','伤停','平局','赢盘','概率','让2球')))

    def test_available_facts_only_and_custom_short_bank(self):
        raw=C.lib_default_json()
        raw['简短评论']={'观战':['{主}这场先看看。','{伤停主}，先看看。']}
        lib,_=C._build_lib(raw,[],[])
        out=C.compose(data(False),lib,watch_per=1)
        self.assertTrue(all('这场先看看' in line for line in out['plain'].splitlines()))
        self.assertNotIn('{',out['plain'])

    def test_draw_recommendation_includes_match_context(self):
        lib,_=C.load_lib(None)
        facts=data()
        for fact in facts['matches']:
            fact['slots']['方向']='平局'
            fact['slots'].pop('推荐队',None);fact['slots'].pop('对手',None)
        out=C.compose(facts,lib,per=8)
        self.assertIn('平局',out['plain'])
        for match in out['items']:
            for line in match['lines']:
                self.assertTrue(match['home'] in line['text'] or match['away'] in line['text'])

    def test_user_max_length_still_respected(self):
        lib,_=C.load_lib(None)
        out=C.compose(data(),lib,max_len=24)
        self.assertGreater(out['n_line'],0)
        self.assertTrue(all(len(line)<=24 for line in out['plain'].splitlines()))

    def test_same_match_not_six_paraphrases_of_one_pick(self):
        lib,_=C.load_lib(None)
        out=C.compose(data(),lib,per=6,max_len=110)
        for match in out['items']:
            self.assertLessEqual(sum('赢' in line['text'] for line in match['lines']),2)
            self.assertFalse(any('这条线' in line['text'] for line in match['lines']))


if __name__=='__main__':unittest.main(verbosity=2)
