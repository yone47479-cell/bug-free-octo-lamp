"""不启动 Tk、不联网，验证实际发布包的版本检查。"""
import ast
import re
import sys
import tempfile
import unittest
from pathlib import Path
from typing import Dict, List

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / '程序'))
import layout as L


def load_checks(root):
    ns = dict(re=re, Path=Path, List=List, Dict=Dict, L=L, APP_DIR=root)
    for filename, names in (
        ('tips_console.pyw', {'NEED_FILES', '_ver_tuple', 'file_problems'}),
        ('gen_tips.py', {'__version__', 'module_versions'}),
    ):
        tree = ast.parse((ROOT / '程序' / filename).read_text(encoding='utf-8-sig'))
        nodes = [n for n in tree.body if
                 isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name in names or
                 isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id in names for t in n.targets)]
        exec(compile(ast.Module(body=nodes, type_ignores=[]), filename, 'exec'), ns)
    return ns


class VersionDetectionTests(unittest.TestCase):
    def test_complete_release_passes(self):
        ns = load_checks(ROOT)
        self.assertEqual(ns['file_problems'](), [])
        versions = ns['module_versions'](ROOT)
        self.assertEqual(versions['esports_data'], '1.3')
        self.assertEqual(versions['esports_refs'], '1.0')
        self.assertEqual(versions['gen_tips'], '3.1.4-esports.5')

    def test_quote_styles_spacing_and_bom(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ns = load_checks(root)
            ns['NEED_FILES'] = (('sample.py', '1.1'),)
            for text in ('__version__ = "1.1"', "__version__='1.1'",
                         '\ufeff__version__ = "1.1"', "  __version__\t=\t'1.1' # release"):
                with self.subTest(text=text):
                    (root / 'sample.py').write_text(text, encoding='utf-8')
                    self.assertEqual(ns['file_problems'](), [])
                    self.assertEqual(ns['module_versions'](root)['sample'], '1.1')

    def test_missing_stale_and_invalid_still_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            ns = load_checks(root)
            ns['NEED_FILES'] = (('sample.py', '1.1'),)
            self.assertEqual(ns['file_problems'](), ['缺少 sample.py'])
            for text in ("__version__='1.0'", '# __version__ = "9.9"',
                         "__version__='9.9\"", '__version__ = run_code()'):
                with self.subTest(text=text):
                    (root / 'sample.py').write_text(text, encoding='utf-8')
                    self.assertEqual(ns['file_problems'](), ['sample.py 还是旧版本'])


if __name__ == '__main__':
    unittest.main()
