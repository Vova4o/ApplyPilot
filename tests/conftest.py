import importlib.util
import sys
import types

import pytest

if importlib.util.find_spec("playwright") is None:
    def _skip_playwright(*args, **kwargs):
        pytest.skip("playwright not installed")

    pw = types.ModuleType("playwright")
    pw_sync = types.ModuleType("playwright.sync_api")
    pw_sync.sync_playwright = _skip_playwright
    pw.sync_api = pw_sync
    sys.modules["playwright"] = pw
    sys.modules["playwright.sync_api"] = pw_sync
