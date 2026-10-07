from __future__ import annotations

import os
from pathlib import Path

from playwright.sync_api import BrowserContext, Page, sync_playwright

from .config import AppConfig
from .domain import ConfigError


def _credentials(path: Path) -> tuple[str, str]:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise ConfigError("Cannot read .env beside config") from error
    values: dict[str, str] = {}
    for line in lines:
        key, separator, value = line.partition("=")
        if separator and key in ("ID", "PASSWORD"):
            values[key] = value.strip()
    identifier = values.get("ID", "")
    password = values.get("PASSWORD", "")
    if not identifier or not password:
        raise ConfigError(".env requires non-empty ID and PASSWORD")
    return identifier, password


def _prepare_paths(config: AppConfig, replace: bool) -> None:
    if (config.auth_state_path.exists() or config.api_token_path.exists()) and not replace:
        raise ConfigError("Authentication files exist; pass --replace to overwrite them")
    config.auth_state_path.parent.mkdir(parents=True, exist_ok=True)
    config.api_token_path.parent.mkdir(parents=True, exist_ok=True)
    if os.name != "nt":
        config.auth_state_path.parent.chmod(0o700)
        config.api_token_path.parent.chmod(0o700)


def _save_session(config: AppConfig, context: BrowserContext, page: Page) -> None:
    token = page.evaluate("sessionStorage.getItem('accessToken')")
    if not isinstance(token, str) or not token:
        raise ConfigError("Login did not produce an access token")
    context.storage_state(path=str(config.auth_state_path))
    config.api_token_path.write_text(f"{token}\n", encoding="utf-8")
    if os.name != "nt":
        config.auth_state_path.chmod(0o600)
        config.api_token_path.chmod(0o600)


def manual_login(config: AppConfig, replace: bool) -> None:
    if not config.base_url:
        raise ConfigError("login requires a configured base_url")
    _prepare_paths(config, replace)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(config.reservations_url)
            input(
                "Complete normal login, MFA, or CAPTCHA in the browser, then press Enter to save local storage state: "
            )
            page.wait_for_url("**#/facilityReservation")
            _save_session(config, context, page)
        finally:
            browser.close()


def login_from_env(config: AppConfig, replace: bool) -> None:
    if not config.base_url:
        raise ConfigError("login requires a configured base_url")
    identifier, password = _credentials(config.path.parent / ".env")
    _prepare_paths(config, replace)
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=False)
        try:
            context = browser.new_context()
            page = context.new_page()
            page.goto(config.reservations_url)
            page.locator("#userId").fill(identifier)
            page.locator("#userPwd").fill(password)
            page.get_by_text("Log-in", exact=True).click()
            page.wait_for_url("**#/facilityReservation")
            _save_session(config, context, page)
        finally:
            browser.close()


def saved_context_path(auth_state: Path) -> str:
    if not auth_state.exists():
        raise ConfigError("No authentication state exists; run login")
    return str(auth_state)
