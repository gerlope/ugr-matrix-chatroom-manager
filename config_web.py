"""Compatibility shim for the web dashboard config.

The real config now lives in web_dashboard/config_web.py.
"""

from importlib import util as _importlib_util
from pathlib import Path as _Path

_config_path = _Path(__file__).resolve().parent / "web_dashboard" / "config_web.py"
_spec = _importlib_util.spec_from_file_location("web_dashboard_config_web", str(_config_path))
_module = _importlib_util.module_from_spec(_spec)
_spec.loader.exec_module(_module)

for _name, _value in vars(_module).items():
	if not _name.startswith("_"):
		globals()[_name] = _value
