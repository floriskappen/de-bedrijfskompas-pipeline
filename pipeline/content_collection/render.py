"""Triggered headless homepage rendering for JS/anti-bot fallbacks."""

from __future__ import annotations

from typing import Final

from .fetch import FetchResult, browser_user_agent

DEFAULT_NAVIGATION_TIMEOUT_MS: Final = 15_000


def render_homepage(
    url: str,
    *,
    timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS,
) -> FetchResult:
    """Render *url* with Playwright/Chromium and return the final DOM HTML.

    Playwright is imported inside the function so module import still works
    when the optional browser binary has not been installed yet.
    """

    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        from playwright.sync_api import sync_playwright
    except Exception as exc:
        return FetchResult(
            url=url,
            html=None,
            error=f"playwright unavailable: {exc}",
            error_kind="headless_unavailable",
        )

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=browser_user_agent())
                page.set_default_navigation_timeout(timeout_ms)
                response = page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                if response is not None and response.status >= 400:
                    return FetchResult(
                        url=page.url,
                        html=None,
                        error=f"HTTP {response.status}",
                        error_kind=f"http_{response.status}",
                    )
                return FetchResult(
                    url=page.url,
                    html=page.content(),
                    error=None,
                    error_kind=None,
                )
            finally:
                browser.close()
    except PlaywrightTimeoutError as exc:
        return FetchResult(
            url=url,
            html=None,
            error=f"headless timeout after {timeout_ms}ms: {exc}",
            error_kind="timeout",
        )
    except PlaywrightError as exc:
        return FetchResult(
            url=url,
            html=None,
            error=f"headless navigation error: {exc}",
            error_kind="headless",
        )
    except Exception as exc:
        return FetchResult(
            url=url,
            html=None,
            error=f"headless error: {exc}",
            error_kind="headless",
        )
