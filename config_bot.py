"""Compatibility shim for the bot config.

The real config now lives in bot/config_bot.py.
"""

from importlib import util as _importlib_util
from pathlib import Path as _Path

_config_path = _Path(__file__).resolve().parent / "bot" / "config_bot.py"
_spec = _importlib_util.spec_from_file_location("bot_config_bot", str(_config_path))
_module = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name, _value in vars(_module).items():
    if not _name.startswith("_"):
        globals()[_name] = _value
