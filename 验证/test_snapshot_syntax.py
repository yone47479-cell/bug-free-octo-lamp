"""图片快照语法与HTML结构回归，不启动浏览器。"""
import unittest,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import snapshot as S

class SnapshotTests(unittest.TestCase):
    def test_row_with_badge(self):
        match=S.ROW_RE.match('01 阿森纳-切尔西 ▶ 3 🎯')
        html=S._row(match)
        self.assertIn('<span class="tr">🎯</span>',html)
        self.assertIn('<span>阿森纳</span>',html)
        self.assertEqual(html.count('<div'),html.count('</div>'))

    def test_row_without_badge(self):
        html=S._row(S.ROW_RE.match('01 皇马vs巴萨 ▶ 3'))
        self.assertNotIn('class="tr"',html)
        self.assertIn('<i>vs</i>',html)
        self.assertEqual(html.count('<div'),html.count('</div>'))

if __name__=='__main__':unittest.main(verbosity=2)
