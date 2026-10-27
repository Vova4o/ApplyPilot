from __future__ import annotations

from pathlib import Path

from applypilot import browser
from applypilot.browser import browser_settings, launch_context, real_user_agent
from applypilot.cli import build_parser


class _Context:
    def __init__(self):
        self.init_scripts = []

    def add_init_script(self, script):
        self.init_scripts.append(script)

    def close(self):
        pass


class _Chromium:
    def __init__(self):
        self.calls = []

    def launch_persistent_context(self, user_data_dir, **kwargs):
        self.calls.append((user_data_dir, kwargs))
        return _Context()


class _Playwright:
    def __init__(self):
        self.chromium = _Chromium()


def _launch(tmp_path: Path, headless: bool):
    playwright = _Playwright()
    session = launch_context(
        playwright,
        data_dir=tmp_path,
        profile={"browser": {"headless": headless}},
    )
    session.close()
    return playwright.chromium.calls[0][1]


def test_browser_defaults_keep_visible_real_chrome_and_hh_timezone():
    settings = browser_settings({})

    assert settings["headless"] is False
    assert settings["locale"] == "ru-RU"
    assert settings["timezone"] == "Asia/Krasnoyarsk"
    assert settings["manual_captcha_timeout_seconds"] == 300


def test_chrome_version_resolves_launcher_symlink_before_execution(tmp_path, monkeypatch):
    executable = tmp_path / "Google Chrome.app" / "Contents" / "MacOS" / "Google Chrome"
    executable.parent.mkdir(parents=True)
    executable.write_text("", encoding="utf-8")
    launcher = tmp_path / "google-chrome"
    launcher.symlink_to(executable)
    monkeypatch.setattr(browser.shutil, "which", lambda name: str(launcher) if name == "google-chrome" else None)

    assert browser._chrome_binary() == str(executable)


def test_headless_user_agent_matches_macos_platform(monkeypatch):
    monkeypatch.setattr(browser.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(browser, "chrome_version", lambda: "155.0.8059.85")

    assert "Macintosh; Intel Mac OS X 10_15_7" in real_user_agent()
    assert "X11; Linux" not in real_user_agent()


def test_visible_mode_uses_the_real_window_without_ua_override(tmp_path):
    kwargs = _launch(tmp_path, headless=False)

    assert kwargs["headless"] is False
    assert kwargs["no_viewport"] is True
    assert "user_agent" not in kwargs
    assert kwargs["ignore_default_args"] == ["--enable-automation"]
    assert "--disable-blink-features=AutomationControlled" in kwargs["args"]


def test_headless_mode_keeps_chrome_identity_and_desktop_dimensions(tmp_path):
    kwargs = _launch(tmp_path, headless=True)

    assert kwargs["headless"] is True
    assert "--headless=new" in kwargs["args"]
    assert "HeadlessChrome" not in kwargs["user_agent"]
    assert kwargs["user_agent"] == real_user_agent()
    assert kwargs["viewport"] == {"width": 1366, "height": 768}
    assert kwargs["screen"] == {"width": 1366, "height": 768}
    assert kwargs["timezone_id"] == "Asia/Krasnoyarsk"
    assert "no_viewport" not in kwargs


def test_launch_context_adds_stealth_init_script(tmp_path):
    playwright = _Playwright()
    session = launch_context(
        playwright,
        data_dir=tmp_path,
        profile={"browser": {"headless": True}},
    )
    assert len(session.context.init_scripts) == 1
    assert "webdriver" in session.context.init_scripts[0]
    session.close()


def test_cli_exposes_explicit_visible_and_headless_modes():
    parser = build_parser()

    apply_args = parser.parse_args(["apply", "--input", "in.json", "--run", "--headless"])
    queue_args = parser.parse_args(["queue", "apply", "--track", "ai", "--run", "--visible"])

    assert apply_args.headless is True and apply_args.visible is False
    assert queue_args.headless is False and queue_args.visible is True
