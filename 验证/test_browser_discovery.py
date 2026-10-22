"""浏览器查找与手选保存回归，不运行浏览器。"""
import ast,json,os,sys,tempfile,unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'程序'))
import snapshot as S
import gen_tips as G

class BrowserTests(unittest.TestCase):
    def test_quoted_expanded_custom_path(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'chrome.exe';exe.write_bytes(b'fake')
            with patch.dict(os.environ,{'SCREENSHOT_TEST_ROOT':d}):
                self.assertEqual(S.find_browser('"${SCREENSHOT_TEST_ROOT}/chrome.exe"'),str(exe))

    def test_custom_application_directory(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'Application'/'msedge.exe';exe.parent.mkdir();exe.write_bytes(b'fake')
            self.assertEqual(S.find_browser(d),str(exe))

    def test_registry_candidate(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'custom-edge.exe';exe.write_bytes(b'fake')
            with patch.object(S,'_registry_browser_candidates',return_value=[str(exe)]):
                self.assertEqual(S.find_browser(),str(exe))

    def test_existing_playwright_cache(self):
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'chromium-1234'/'chrome-win64'/'chrome.exe';exe.parent.mkdir(parents=True);exe.write_bytes(b'fake')
            with patch.dict(os.environ,{'PLAYWRIGHT_BROWSERS_PATH':d}),patch.object(S,'_registry_browser_candidates',return_value=[]),patch.object(S.shutil,'which',return_value=None):
                self.assertEqual(S.find_browser(),str(exe))

    def test_chooser_persists_path(self):
        source=Path(__file__).resolve().parents[1]/'程序'/'tips_console.pyw'
        tree=ast.parse(source.read_text());app=next(n for n in tree.body if isinstance(n,ast.ClassDef) and n.name=='App')
        method=next(n for n in app.body if isinstance(n,ast.FunctionDef) and n.name=='choose_browser')
        with tempfile.TemporaryDirectory() as d:
            exe=Path(d)/'chrome.exe';exe.write_bytes(b'fake');settings=Path(d)/'settings.json'
            ns={'Path':Path,'json':json,'SETTINGS':settings,
                'filedialog':SimpleNamespace(askopenfilename=lambda **kw:str(exe)),
                'messagebox':SimpleNamespace(showerror=lambda *a,**k:self.fail('不应报错'))}
            exec(compile(ast.Module(body=[method],type_ignores=[]),'chooser','exec'),ns)
            app=SimpleNamespace(busy=False,img_busy=False,settings={'limit':280},G=G,_set_status=lambda *a:None,_append_log=lambda *a:None)
            self.assertEqual(ns['choose_browser'](app),str(exe))
            self.assertEqual(json.loads(settings.read_text())['browser'],str(exe))
            self.assertEqual(app.settings['limit'],280)

if __name__=='__main__':unittest.main(verbosity=2)
