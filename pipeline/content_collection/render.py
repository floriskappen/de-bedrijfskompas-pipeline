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


class PageRenderer:
    """Render multiple URLs reusing a single headless browser instance.

    The browser is opened lazily on the first ``render`` call (so a static
    site that never renders sub-pages pays no launch cost) and reused for
    every subsequent sub-page on a detected JS-site. ``close`` MUST be called
    to release the browser; it is a no-op when the browser was never opened.
    """

    def __init__(self, *, timeout_ms: int = DEFAULT_NAVIGATION_TIMEOUT_MS) -> None:
        self._timeout_ms = timeout_ms
        self._pw = None
        self._browser = None
        self._page = None

    def _ensure(self) -> str | None:
        """Open the browser on first use. Returns an error string or None."""
        if self._browser is not None:
            return None
        try:
            from playwright.sync_api import sync_playwright
        except Exception as exc:
            return f"playwright unavailable: {exc}"
        try:
            self._pw = sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            context = self._browser.new_context(user_agent=browser_user_agent())
            self._page = context.new_page()
        except Exception as exc:
            return f"headless launch error: {exc}"
        return None

    def render(self, url: str, *, timeout_ms: int | None = None) -> FetchResult:
        err = self._ensure()
        if err is not None:
            return FetchResult(
                url=url, html=None, error=err, error_kind="headless_unavailable"
            )
        t = timeout_ms if timeout_ms is not None else self._timeout_ms
        try:
            from playwright.sync_api import Error as PlaywrightError
            from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
        except Exception as exc:
            return FetchResult(
                url=url, html=None,
                error=f"playwright unavailable: {exc}",
                error_kind="headless_unavailable",
            )
        try:
            self._page.set_default_navigation_timeout(t)
            response = self._page.goto(url, wait_until="networkidle", timeout=t)
            if response is not None and response.status >= 400:
                return FetchResult(
                    url=self._page.url, html=None,
                    error=f"HTTP {response.status}",
                    error_kind=f"http_{response.status}",
                )
            return FetchResult(
                url=self._page.url, html=self._page.content(),
                error=None, error_kind=None,
            )
        except PlaywrightTimeoutError as exc:
            return FetchResult(
                url=url, html=None,
                error=f"headless timeout after {t}ms: {exc}",
                error_kind="timeout",
            )
        except PlaywrightError as exc:
            return FetchResult(
                url=url, html=None,
                error=f"headless navigation error: {exc}",
                error_kind="headless",
            )
        except Exception as exc:
            return FetchResult(
                url=url, html=None,
                error=f"headless error: {exc}",
                error_kind="headless",
            )

    def close(self) -> None:
        if self._browser is not None:
            try:
                self._browser.close()
            except Exception:
                pass
            self._browser = None
        if self._pw is not None:
            try:
                self._pw.stop()
            except Exception:
                pass
            self._pw = None
        self._page = None
