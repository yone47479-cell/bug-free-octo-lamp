"""针对2026-10-17运行日志的队名匹配回归。"""
import sys,unittest,tempfile
from pathlib import Path
from datetime import datetime,timezone,timedelta
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import sina_data as S
import gen_tips as G
import export_500_all as E

class TeamNamesTests(unittest.TestCase):
    def test_logged_short_names(self):
        n=S.ZhNames()
        for short,full in [('伯恩茅','伯恩茅斯'),('诺丁汉','诺丁汉森林'),('勒沃','勒沃库森'),('霍芬海','霍芬海姆'),
                           ('佛罗伦','佛罗伦萨'),('阿拉维','阿拉维斯'),('塞维利','塞维利亚'),('维戈塞尔塔','塞尔塔')]:
            self.assertEqual(n.canon(short),n.canon(full))

    def test_reserve_gender_age_are_distinct(self):
        for a,b in [('皇家社会','皇家社会C队'),('霍芬海姆','霍芬海姆业余队'),('甲U21','甲U23'),
                    ('甲B队','甲C队'),('甲女足','甲U21'),('皇家社会','皇家社会(B队)')]:
            self.assertFalse(S.marks_ok(a,b),(a,b))
            self.assertEqual(S.name_sim(a,b),0,(a,b))
            self.assertEqual(G.sim(a,b),0,(a,b))
        self.assertTrue(S.marks_ok('甲B队','甲Ⅱ'))
        self.assertNotEqual(S.clean('皇家社会(C队)'),S.clean('皇家社会'))

    def test_incorrect_builtin_merge_removed(self):
        n=S.ZhNames()
        self.assertNotEqual(n.canon('奥格斯堡'),n.canon('埃夫斯堡'))
        self.assertNotEqual(n.canon('社会'),n.canon('皇家社会C队'))

    def test_ambiguous_short_name_needs_league(self):
        original={'home':'AC米兰','away':'亚特兰','lg':'意甲'}
        self.assertEqual(S.resolve_match_names(original)['away'],'亚特兰大')
        self.assertEqual(original['away'],'亚特兰')
        self.assertEqual(S.resolve_match_names(dict(original,lg='墨西甲'))['away'],'亚特兰')
        self.assertEqual(S.resolve_match_names({'home':'马拉加','away':'社会','lg':'西乙'})['away'],'社会')

    def test_historical_form_uses_alias_and_excludes_reserves(self):
        with tempfile.TemporaryDirectory() as d:
            db=S.ResultsDB(Path(d));db.rows=[{'k':f'2026-10-{i:02} 19:00','h':'伯恩茅斯','a':'阿森纳','hs':2,'as':1,'lg':'英超'} for i in range(1,7)]
            db.rows += [{'k':'2026-10-10 19:00','h':'伯恩茅斯U21','a':'阿森纳U21','hs':9,'as':0,'lg':'青年联赛'}]
            self.assertEqual(db.form('伯恩茅','2026-10-17 23:00')['n'],6)
            self.assertEqual(db.form('伯恩茅','2026-10-17 23:00')['gf'],12)

    def test_full_attributes_preferred(self):
        attrs={'data-matchnum':'周六001','data-processdate':'2026-10-17','data-matchdate':'2026-10-17',
               'data-matchtime':'23:00','data-homesxname':'马拉加','data-awaysxname':'社会',
               'data-homename':'马拉加','data-awayname':'皇家社会B队'}
        rows=E._fixtures_from_attributes([E.HtmlRow(attrs)],'2026-10-17',E.Page('u','u','', '2026-10-17 18:00:00'))
        self.assertEqual(rows[0].away,'皇家社会B队')
        self.assertIn('社会',rows[0].raw_pairing)

    def test_league_context_enriched_without_guessing(self):
        kick=datetime(2026,10,17,23,tzinfo=timezone(timedelta(hours=8)))
        m={'home':'AC米兰','away':'亚特兰','kick':kick,'lg':''}
        wb={'竞足-今日未开赛':[{'主队':'AC米兰','客队':'亚特兰','联赛':'意甲','开赛时间(北京时间)':'2026-10-17 23:00'}]}
        G.enrich_match_leagues([m],wb)
        self.assertEqual(m['lg'],'意甲')

    def test_resolved_notes_keep_original_match_key(self):
        provider=S.SinaProvider.__new__(S.SinaProvider)
        provider.source_text='测试'
        def notes(matches,day):
            self.assertEqual(matches[0]['away'],'亚特兰大')
            return [{'mk':['AC米兰','亚特兰大'],'数据':'可用'}],[]
        provider._notes_football=notes
        result,problems=provider.notes_for([{'home':'AC米兰','away':'亚特兰','lg':'意甲','sport':'football'}],'2026-10-17')
        self.assertEqual(tuple(result[0]['mk']),('AC米兰','亚特兰'))

if __name__=='__main__':unittest.main(verbosity=2)
