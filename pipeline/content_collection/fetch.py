"""HTTP fetch with one retry, classifying failure modes for reporting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

import httpx

PINNED_BROWSER_USER_AGENT: Final = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/125.0.0.0 Safari/537.36"
)
DEFAULT_TIMEOUT: Final = 15.0


@dataclass(frozen=True)
class FetchResult:
    """Outcome of a single HTTP fetch.

    Exactly one of ``html`` or ``error`` is set. ``error_kind`` is a
    short stable token (``"timeout"``, ``"dns"``, ``"http_<status>"``,
    ``"transport"``) so callers can group failures.
    """

    url: str
    html: str | None
    error: str | None
    error_kind: str | None

    @property
    def ok(self) -> bool:
        return self.html is not None


def browser_user_agent() -> str:
    """Return a browser-class UA, falling back to a pinned modern Chrome UA."""

    try:
        from fake_useragent import UserAgent

        ua = UserAgent()
        value = getattr(ua, "random", None)
        if isinstance(value, str) and value.strip():
            return value.strip()
    except Exception:
        pass
    return PINNED_BROWSER_USER_AGENT


def get(url: str, *, timeout: float = DEFAULT_TIMEOUT) -> FetchResult:
    last_err: tuple[str, str] | None = None
    for attempt in (1, 2):
        try:
            with httpx.Client(
                follow_redirects=True,
                timeout=timeout,
                headers={"User-Agent": browser_user_agent()},
            ) as client:
                resp = client.get(url)
        except httpx.TimeoutException as exc:
            last_err = ("timeout", f"timeout after {timeout}s: {exc}")
            continue
        except (httpx.ConnectError, httpx.NetworkError) as exc:
            last_err = ("dns", f"connection error: {exc}")
            continue
        except httpx.HTTPError as exc:
            last_err = ("transport", f"transport error: {exc}")
            continue

        if resp.status_code >= 400:
            # 4xx/5xx are not retried — they are deterministic.
            return FetchResult(
                url=str(resp.url),
                html=None,
                error=f"HTTP {resp.status_code}",
                error_kind=f"http_{resp.status_code}",
            )

        return FetchResult(
            url=str(resp.url),
            html=resp.text,
            error=None,
            error_kind=None,
        )

    assert last_err is not None
    kind, msg = last_err
    return FetchResult(url=url, html=None, error=msg, error_kind=kind)
