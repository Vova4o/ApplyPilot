import asyncio
import json
from pathlib import Path

import pytest

from applypilot.config import AppConfig
from applypilot.mcp_server import Service, create_server


@pytest.fixture
def service(tmp_path):
    config = AppConfig(tmp_path, tmp_path / 'data', tmp_path / 'profile.toml')
    config.snapshots_dir.mkdir(parents=True)
    path = config.snapshots_dir / 'hh_vacancies_test.json'
    path.write_text(json.dumps({'items': [{'id': '123', 'name': 'Go engineer',
                                           'description': 'PostgreSQL', 'secret': 'NO'}],
                                'status': 'partial'}))
    return Service(config)


def test_path_and_ids(service):
    for bad in ('../profile.toml', '/tmp/x', 'last_successful.json'):
        with pytest.raises(ValueError):
            service.snapshot(bad)
    with pytest.raises(ValueError):
        service.item('hh_vacancies_test.json', '--run')
    with pytest.raises(ValueError):
        service.item('hh_vacancies_test.json', '999')
    with pytest.raises(ValueError):
        service.snapshots(True)


def test_symlink_rejected(service, tmp_path):
    outside = tmp_path / 'outside.json'
    outside.write_text('{"items": []}')
    (service.config.snapshots_dir / 'hh_vacancies_link.json').symlink_to(outside)
    with pytest.raises(ValueError):
        service.snapshot('hh_vacancies_link.json')


def test_public_detail_allowlist(service):
    detail = service.detail('hh_vacancies_test.json', '123')
    assert detail['id'] == '123'
    assert 'secret' not in detail
    assert service.capabilities()['chat_send'] is False


def test_apply_guard_and_exact_selection(service, monkeypatch):
    calls = []
    def command(argv):
        path = Path(argv[argv.index('--input') + 1])
        assert json.loads(path.read_text())['items'][0]['id'] == '123'
        assert path.stat().st_mode & 0o777 == 0o600
        calls.append(argv)
        return {'ok': True, 'exit_code': 0}
    monkeypatch.setattr(service, 'command', command)
    with pytest.raises(ValueError):
        service.application('hh_vacancies_test.json', '123', live=True, confirm=True)
    assert not calls
    result = service.application('hh_vacancies_test.json', '123')
    assert '--dry-run' in calls[0]
    assert result['submission_confirmed'] is False
    assert not list((service.config.data_dir / 'mcp-inputs').glob('*.json'))
    service.enable_apply = True
    with pytest.raises(ValueError):
        service.application('hh_vacancies_test.json', '123', live=True)
    service.application('hh_vacancies_test.json', '123', live=True, confirm=True)
    assert '--run' in calls[-1]


def test_real_subprocess_entrypoint(service):
    result = service.command(['doctor'])
    assert result['exit_code'] == 0
    # A no-op module invocation incorrectly reports zero here.
    assert service.command(['session', 'check'])['exit_code'] != 0


@pytest.mark.parametrize('parameters', [(0, 1, 1, 0), (1, 11, 1, 0), (1, 1, 51, 0)])
def test_scan_bounds(service, parameters):
    with pytest.raises(ValueError):
        service.search(*parameters)


def test_tools_have_side_effect_annotations(service):
    tools = {tool.name: tool for tool in asyncio.run(create_server(service).list_tools())}
    assert tools['apply'].annotations.readOnlyHint is False
    assert tools['application_dry_run'].annotations.openWorldHint is False
    assert tools['vacancies'].annotations.readOnlyHint is True


def test_failed_and_unknown_application(service, monkeypatch):
    monkeypatch.setattr(service, 'command', lambda argv: {
        'ok': False, 'exit_code': 3, 'retry': False})
    monkeypatch.setattr(service, 'application_status', lambda vacancy_id: 'unknown')
    result = service.application('hh_vacancies_test.json', '123')
    assert result['application_status'] == 'unknown'
    assert result['retry'] is False
    assert result['submission_confirmed'] is False
    assert not result['ok']


def test_timeout_kills_process_group_and_hides_output(service, monkeypatch):
    import signal
    import subprocess
    calls = []
    class Process:
        pid = 12345
        waits = 0
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def wait(self, timeout=None):
            self.waits += 1
            if self.waits == 1:
                raise subprocess.TimeoutExpired('private command', 1)
            return 0
    monkeypatch.setattr(subprocess, 'Popen', lambda *args, **kwargs: Process())
    monkeypatch.setattr('applypilot.mcp_server.os.killpg', lambda pid, sig: calls.append(sig))
    result = service.command(['doctor'])
    assert calls == [signal.SIGTERM, signal.SIGKILL]
    assert result['status'] == 'timeout'
    assert result['retry'] is False
    assert 'stdout' not in result and 'stderr' not in result
