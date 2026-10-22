"""读取操作台设置，不依赖 Tk，也不在导入时创建目录或修改文件。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict


DEFAULTS = {
    "limit": 280, "auto": True, "daily": False, "daily_time": "15:00",
    "last_ok": "", "proxy": "", "backfill": True, "team_data": False,
    "td_source": "", "sched_time": "15:00",
}


def read_settings(path: Path) -> Dict[str, Any]:
    """兼容旧设置并保留扩展字段；损坏字段独立回退，不覆盖用户文件。"""
    settings = dict(DEFAULTS)
    try:
        raw = json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return settings
    if not isinstance(raw, dict):
        return settings
    settings.update(raw)
    for key, default in DEFAULTS.items():
        value = settings[key]
        if key == "limit":
            try:
                if isinstance(value, bool) or not re.fullmatch(r"[0-9]+", str(value)):
                    raise ValueError
                value = int(value)
                if value <= 0:
                    raise ValueError
            except (ValueError, TypeError):
                value = default
        elif isinstance(default, bool):
            value = value if isinstance(value, bool) else default
        elif not isinstance(value, str):
            value = default
        if key in ("daily_time", "sched_time") and not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            value = default
        settings[key] = value
    return settings
