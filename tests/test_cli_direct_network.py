from contextlib import contextmanager
from pathlib import Path

import requests

from applypilot import cli
from applypilot.parser import ScanSegment


def test_doctor_online_uses_scoped_interface_proxy(monkeypatch, tmp_path, capsys):
    observed = {}

    @contextmanager
    def fake_direct_proxy(interface_name):
        observed["interface"] = interface_name
        yield "http://127.0.0.1:43210"

    class Response:
        status_code = 200

    def fake_get(session, url, **kwargs):
        observed["url"] = url
        observed["proxies"] = dict(session.proxies)
        return Response()

    monkeypatch.setenv("APPLYPILOT_HH_INTERFACE", "en0")
    monkeypatch.setattr(cli, "direct_proxy", fake_direct_proxy)
    monkeypatch.setattr(requests.Session, "get", fake_get)

    assert cli.main(["--data-dir", str(tmp_path / "data"), "doctor", "--online"]) == 0
    assert observed == {
        "interface": "en0",
        "url": "https://hh.ru",
        "proxies": {
            "http": "http://127.0.0.1:43210",
            "https": "http://127.0.0.1:43210",
        },
    }
    assert "network: HTTP 200" in capsys.readouterr().out


def test_scan_uses_scoped_proxy_and_budgets_actual_requests(monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    observed = {"budgets": [], "proxies": []}

    @contextmanager
    def fake_direct_proxy(interface_name):
        assert interface_name == "en0"
        yield "http://127.0.0.1:43210"

    class Session:
        def __init__(self):
            self.proxies = {}

        def close(self):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *_args):
            self.close()

    def fake_scan_many(queries, areas, pages, remote, **kwargs):
        observed["budgets"].append(kwargs["request_budget"])
        observed["proxies"].append(dict(kwargs["session"].proxies))
        used = 2 if len(observed["budgets"]) == 1 else 1
        return [], [ScanSegment(queries[0], areas[0], 1, "ok", 0, requests=used)]

    monkeypatch.setenv("APPLYPILOT_HH_INTERFACE", "en0")
    monkeypatch.setattr(cli, "direct_proxy", fake_direct_proxy)
    monkeypatch.setattr(requests, "Session", Session)
    monkeypatch.setattr(cli, "scan_many", fake_scan_many)
    search = Path("search.toml")
    search.write_text('''request_budget = 3
details_limit = 0
[[groups]]
name = "first"
queries = ["Go"]
[[groups]]
name = "second"
queries = ["Python"]
''', encoding="utf-8")

    result = cli.main(["--search", str(search), "--data-dir", str(tmp_path / "data"), "scan"])

    assert result == 0
    assert observed["budgets"] == [3, 1]
    expected = {"http": "http://127.0.0.1:43210", "https": "http://127.0.0.1:43210"}
    assert observed["proxies"] == [expected, expected]
