from __future__ import annotations

from pathlib import Path
from types import TracebackType

import pytest

from gist_studyroom import auth
from gist_studyroom.config import load_config
from gist_studyroom.domain import ConfigError


def _config(tmp_path: Path) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(
        """[site]
base_url = "https://example.invalid"
reservations_url = "https://example.invalid/#/facilityReservation"
api_url = "https://api.example.invalid"
[paths]
live_db = "live.sqlite3"
fixture_db = "fixture.sqlite3"
auth_state = "private/auth-state.json"
api_token = "private/access-token"
exports_dir = "exports"
backups_dir = "backups"
lock_file = "private/collector.lock"
[study]
start_date = ""
duration_days = 60
max_lag_hours = 26
[[facilities]]
id = "101"
name = "Room 101"
""",
        encoding="utf-8",
    )
    return path


class FakePage:
    def __init__(self) -> None:
        self.filled: dict[str, str] = {}
        self.goto_urls: list[str] = []
        self.selector = ""
        self.url = "https://example.invalid/#/login"

    def goto(self, url: str) -> None:
        self.goto_urls.append(url)
        return None

    def locator(self, selector: str) -> FakePage:
        self.selector = selector
        return self

    def fill(self, value: str) -> None:
        self.filled[self.selector] = value

    def get_by_text(self, _text: str, *, exact: bool) -> FakePage:
        assert exact
        return self

    def click(self) -> None:
        self.url = "https://example.invalid/#/facilityReservation"

    def wait_for_url(self, _url: str) -> None:
        return None

    def evaluate(self, expression: str) -> str:
        assert expression == "sessionStorage.getItem('accessToken')"
        return "fake-access-token"


class FakeContext:
    def __init__(self, page: FakePage) -> None:
        self.page = page

    def new_page(self) -> FakePage:
        return self.page

    def storage_state(self, *, path: str) -> None:
        Path(path).write_text("{}", encoding="utf-8")


class FakeBrowser:
    def __init__(self, context: FakeContext) -> None:
        self.context = context

    def new_context(self) -> FakeContext:
        return self.context

    def close(self) -> None:
        return None


class FakeChromium:
    def __init__(self, browser: FakeBrowser) -> None:
        self.browser = browser

    def launch(self, *, headless: bool) -> FakeBrowser:
        assert not headless
        return self.browser


class FakePlaywright:
    def __init__(self, page: FakePage) -> None:
        self.chromium = FakeChromium(FakeBrowser(FakeContext(page)))

    def __enter__(self) -> FakePlaywright:
        return self

    def __exit__(
        self,
        _type: type[BaseException] | None,
        _value: BaseException | None,
        _traceback: TracebackType | None,
    ) -> None:
        return None


def test_login_from_env_uses_stable_selectors_and_saves_separate_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    # Given
    config = load_config(_config(tmp_path))
    (tmp_path / ".env").write_text("ID=fake-id\nPASSWORD=fake-password\nOTHER=ignored\n")
    page = FakePage()
    monkeypatch.setattr(auth, "sync_playwright", lambda: FakePlaywright(page))

    # When
    auth.login_from_env(config, replace=False)

    # Then
    assert page.goto_urls == [config.reservations_url]
    assert page.filled == {"#userId": "fake-id", "#userPwd": "fake-password"}
    assert config.auth_state_path.read_text(encoding="utf-8") == "{}"
    assert config.api_token_path.read_text(encoding="utf-8") == "fake-access-token\n"
    assert "fake-id" not in capsys.readouterr().out
    assert "fake-password" not in capsys.readouterr().err
    with pytest.raises(ConfigError):
        auth.login_from_env(config, replace=False)


def test_manual_login_opens_reservations_url(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Given
    config = load_config(_config(tmp_path))
    page = FakePage()
    monkeypatch.setattr(auth, "sync_playwright", lambda: FakePlaywright(page))

    def press_enter(_prompt: str) -> str:
        return ""

    monkeypatch.setattr("builtins.input", press_enter)

    # When
    auth.manual_login(config, replace=False)

    # Then
    assert page.goto_urls == [config.reservations_url]
