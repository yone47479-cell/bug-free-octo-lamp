"""设置损坏不能让桌面操作台启动失败。"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "程序"))
from console_config import read_settings


class ConsoleSettingsTests(unittest.TestCase):
    def read(self, text):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "settings.json"
            path.write_text(text, encoding="utf-8")
            result = read_settings(path)
            self.assertEqual(path.read_text(encoding="utf-8"), text)
            return result

    def test_missing_file_and_independent_defaults(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "missing.json"
            first = read_settings(path)
            first["auto"] = False
            self.assertTrue(read_settings(path)["auto"])
            self.assertFalse(path.exists())

    def test_corrupt_and_non_object_json(self):
        for text in ("{broken", "[]", "null", '"hello"'):
            with self.subTest(text=text):
                self.assertEqual(self.read(text)["limit"], 280)

    def test_invalid_fields_do_not_erase_valid_preferences(self):
        settings = self.read(json.dumps({"limit": None, "auto": "false", "daily_time": "25:90",
                                         "proxy": "http://localhost:8080", "custom": [1]}))
        self.assertEqual(settings["limit"], 280)
        self.assertIs(settings["auto"], True)
        self.assertEqual(settings["daily_time"], "15:00")
        self.assertEqual(settings["proxy"], "http://localhost:8080")
        self.assertEqual(settings["custom"], [1])

    def test_bom_legacy_string_limit_and_valid_schedule(self):
        settings = self.read('\ufeff' + json.dumps({"limit": "25000", "sched_time": "09:05", "auto": False}))
        self.assertEqual(settings["limit"], 25000)
        self.assertEqual(settings["sched_time"], "09:05")
        self.assertFalse(settings["auto"])

    def test_invalid_limits(self):
        for value in (True, 0, -1, 1.5, [], "NaN"):
            with self.subTest(value=value):
                self.assertEqual(self.read(json.dumps({"limit": value}))["limit"], 280)


if __name__ == "__main__":
    unittest.main()
