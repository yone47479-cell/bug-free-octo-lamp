"""实际 Tk 窗口回归；Linux 需 DISPLAY，无桌面时明确跳过。"""
import importlib.machinery
import importlib.util
import os
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "程序"))


@unittest.skipUnless(os.name == "nt" or os.environ.get("DISPLAY"), "需要图形桌面或 Xvfb")
class ConsoleWindowTests(unittest.TestCase):
    def test_window_navigation_controls_and_compact_layout(self):
        with tempfile.TemporaryDirectory() as folder:
            program = Path(folder) / "程序"
            shutil.copytree(ROOT / "程序", program, ignore=shutil.ignore_patterns("__pycache__"))
            loader = importlib.machinery.SourceFileLoader("console_ui_smoke", str(program / "tips_console.pyw"))
            spec = importlib.util.spec_from_loader(loader.name, loader)
            module = importlib.util.module_from_spec(spec)
            loader.exec_module(module)
            settings = module.load_settings()
            settings["auto"] = False  # UI 回归不触发外部采集。
            errors = []
            with patch.object(module, "load_settings", return_value=settings):
                app = module.App()
            app.report_callback_exception = lambda *exc: errors.append(exc)
            try:
                app.update()
                self.assertEqual(app.nb.index("end"), 7)
                for index in range(7):
                    app._select_tab(index)
                    app.update()
                    self.assertEqual(app.nb.index(app.nb.select()), index)
                app._select_tab(0)
                for width, height in ((960, 680), (1180, 900)):
                    app.geometry(f"{width}x{height}")
                    app.update()
                    for control in (app.btn_go, app.btn_regen, app.btn_retry, app.btn_stop, app.btn_hist, app.bar):
                        self.assertTrue(control.winfo_ismapped())
                        self.assertGreater(control.winfo_width(), 20)
                        self.assertLessEqual(control.winfo_rootx() + control.winfo_width(), app.winfo_rootx() + width)
                    self.assertGreater(app.nb.winfo_height(), 180)
                with patch.object(app, "start_update") as update:
                    app.btn_go.invoke()
                    update.assert_called_once_with(True)
                app._set_busy(True)
                self.assertEqual(str(app.btn_stop["state"]), "normal")
                self.assertEqual(str(app.btn_regen["state"]), "disabled")
                app._set_busy(False)
                for state in ("run", "ok", "fail", "skip", "idle"):
                    app._set_step(0, state)
                app.update()
                self.assertEqual(errors, [])
                screenshot = os.environ.get("CONSOLE_SCREENSHOT")
                if screenshot:
                    from PIL import ImageGrab
                    x, y = app.winfo_rootx(), app.winfo_rooty()
                    ImageGrab.grab(bbox=(x, y, x + app.winfo_width(), y + app.winfo_height())).save(screenshot)
            finally:
                for task in app.tk.call("after", "info"):
                    app.after_cancel(task)
                app.destroy()


if __name__ == "__main__":
    unittest.main()
