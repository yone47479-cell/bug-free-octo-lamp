"""随机短评：容量、事实门槛、迁移、语义去重与性能回归。"""
import copy,json,random,sys,tempfile,time,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import commentary as C
from test_short_comments import data

class CommentVarietyTests(unittest.TestCase):
    def test_capacity_valid_unique_complete_templates(self):
        stats=C.short_bank_stats()
        self.assertGreaterEqual(stats['complete_templates'],1500)
        self.assertGreaterEqual(stats['semantic_families'],200)
        for kind,bank in C.SHORT_LINES.items():
            self.assertEqual(len(bank),len(set(bank)))
            for line in bank:
                self.assertIsNone(C._tpl_ok(line,[],C.SLOT_NAMES),(kind,line))
                self.assertNotIn('\n',line)
                self.assertNotIn('，的',line)
                self.assertNotIn('，这场的',line)
    def test_legacy_defaults_upgrade_preserves_custom_entries(self):
        with tempfile.TemporaryDirectory() as d:
            path=Path(d)/'话术库.json'
            old=C.lib_default_json();old['话术库版本']=2;old['简短评论']=copy.deepcopy(C.BASE_SHORT_LINES)
            old['简短评论']['观战'].append('{主}先看开局再聊。');old['我的备注']='保留'
            path.write_text(json.dumps(old,ensure_ascii=False))
            self.assertIn('扩充随机短评句库',C.ensure_lib_file(path))
            newer=json.loads(path.read_text());self.assertEqual(newer['我的备注'],'保留')
            self.assertIn('{主}先看开局再聊。',newer['简短评论']['观战'])
            self.assertGreater(len(newer['简短评论']['观战']),700)
            before=path.read_bytes();C.ensure_lib_file(path);self.assertEqual(before,path.read_bytes())
    def test_custom_replacement_bank_not_forced_to_defaults(self):
        raw=C.lib_default_json();raw['简短评论']['观战']=['{主}先看看。']
        lib,_=C._build_lib(raw,[],[])
        self.assertEqual(lib['简短评论']['观战'],['{主}先看看。'])
    def test_same_match_semantic_family_unique_and_global_rotation(self):
        fact=data()['matches'][0];lib,_=C.load_lib(None);persona=lib['人设'][0];used=set()
        for n in range(6):
            C._build_line(fact,persona,random.Random(n),used,42,[],False)
        families=[v[2] for v in used if len(v)==3 and v[:2]==('同场句意',fact['key'])]
        lines=[v[2] for v in used if len(v)==3 and v[:2]==('同场短句',fact['key'])]
        self.assertEqual(len(families),len(lines));self.assertEqual(len(set(families)),len(lines))
    def test_many_seeds_produce_variety_without_invented_facts(self):
        lib,_=C.load_lib(None);facts=data(False);facts['matches']=facts['matches'][:1];all_lines=set()
        for seed in range(80):
            out=C.compose(facts,lib,seed=seed,watch_per=3)
            lines=out['plain'].splitlines();self.assertEqual(len(lines),len(set(lines)))
            for line in lines:
                self.assertLessEqual(len(line),42)
                self.assertFalse(any(w in line for w in ('伤停','近6场','平局','赢盘','让2球','今晚')))
            all_lines.update(lines)
        self.assertGreater(len(all_lines),140)
    def test_gates_block_risk_and_missing_fact_categories(self):
        lib,_=C.load_lib(None);facts=data();fact=facts['matches'][0];fact['flags']={}
        used=set();persona=lib['人设'][0]
        for seed in range(10):
            C._build_line(fact,persona,random.Random(seed),used,42,[],False)
        kinds=[v[2] for v in used if len(v)==4 and v[:2]==('同场类别',fact['key'])]
        self.assertFalse(set(kinds)&{'防平','防冷','分歧','近况','盘口'})
    def test_explicit_seed_repeatable_and_long_names_not_truncated(self):
        lib,_=C.load_lib(None);facts=data();a=C.compose(facts,lib,seed=123)
        self.assertEqual(a['plain'],C.compose(facts,lib,seed=123)['plain'])
        fact=facts['matches'][0];fact['home']='一支队名特别特别特别特别特别特别特别长的球队';fact['slots']['主']=fact['home']
        out=C.compose(facts,lib,seed=3,max_len=24)
        self.assertTrue(all(len(line)<=24 and '{' not in line for line in out['plain'].splitlines()))
    def test_larger_schedule_has_bounded_generation_cost(self):
        # 宽松的上限用于抓住候选组合全量模糊比较引起的数量级退化。
        lib,_=C.load_lib(None);facts=data();source=copy.deepcopy(facts['matches'][0]);facts['matches']=[]
        for i in range(30):
            f=copy.deepcopy(source);f['key']=str(i);f['home']='主队'+str(i);f['away']='客队'+str(i)
            f['slots'].update({'主':f['home'],'客':f['away'],'方向':f['home']+'胜'})
            facts['matches'].append(f)
        start=time.perf_counter();out=C.compose(facts,lib,seed=9)
        self.assertLess(time.perf_counter()-start,15)
        self.assertGreater(out['n_line'],100)

if __name__=='__main__':unittest.main()
