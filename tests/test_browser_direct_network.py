from __future__ import annotations

import json
import sys
import types

import pytest
import requests

from applypilot import inspection, negotiations, session


class _LaunchReached(Exception):
    pass


def _install_playwright_stub(monkeypatch: pytest.MonkeyPatch, observed: list[dict]) -> None:
    class Chromium:
        def launch(self, **kwargs):
            observed.append(kwargs)
            raise _LaunchReached

    class Playwright:
        chromium = Chromium()

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

    api = types.ModuleType("playwright.sync_api")
    api.sync_playwright = Playwright
    package = types.ModuleType("playwright")
    package.sync_api = api
    monkeypatch.setitem(sys.modules, "playwright", package)
    monkeypatch.setitem(sys.modules, "playwright.sync_api", api)


@pytest.mark.parametrize(
    ("invoke", "expected"),
    [
        (lambda path: session.login(path, proxy_url="http://127.0.0.1:8765"),
         {"headless": False, "proxy": {"server": "http://127.0.0.1:8765"}}),
        (lambda path: session.check_session(path, proxy_url="http://127.0.0.1:8765"),
         {"headless": True, "proxy": {"server": "http://127.0.0.1:8765"}}),
        (lambda path: inspection.inspect_resumes(path, proxy_url="http://127.0.0.1:8765"),
         {"headless": True, "proxy": {"server": "http://127.0.0.1:8765"}}),
        (lambda path: inspection.inspect_items(path, [], proxy_url="http://127.0.0.1:8765"),
         {"headless": True, "proxy": {"server": "http://127.0.0.1:8765"}}),
    ],
)
def test_browser_operations_pass_direct_proxy(
    monkeypatch: pytest.MonkeyPatch, tmp_path, invoke, expected
) -> None:
    observed: list[dict] = []
    _install_playwright_stub(monkeypatch, observed)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"cookies": []}), encoding="utf-8")

    try:
        invoke(state_path)
    except _LaunchReached:
        pass

    assert observed == [expected]


def test_negotiation_session_uses_direct_proxy(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    observed = {}

    class Client:
        def __init__(self):
            self.proxies = {}
            self.cookies = types.SimpleNamespace(set=lambda *_args, **_kwargs: None)
            observed["client"] = self

        def get(self, *_args, **_kwargs):
            raise requests.ConnectionError("offline stub")

        def close(self):
            observed["closed"] = True

    class StoreStub:
        def save_sync_snapshot(self, *args, **kwargs):
            pass

    monkeypatch.setattr(negotiations.requests, "Session", Client)
    state_path = tmp_path / "state.json"
    state_path.write_text(json.dumps({"cookies": []}), encoding="utf-8")

    with pytest.raises(negotiations.SyncError, match="network error"):
        negotiations.sync_statuses(
            state_path, StoreStub(), proxy_url="http://127.0.0.1:8765"
        )

    assert observed["client"].proxies == {
        "http": "http://127.0.0.1:8765",
        "https": "http://127.0.0.1:8765",
    }
    assert observed["closed"] is True
