from __future__ import annotations

from time import sleep
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

RETRYABLE_STATUS_CODES = {500, 502, 503, 504}
DEFAULT_RETRIES = 2
DEFAULT_BACKOFF_SECONDS = 1.0


def fetch_bytes(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    referer: str | None = None,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> bytes:
    """GET a URL with shared header handling and bounded retries.

    Transient failures (timeouts, connection errors, HTTP 5xx) are retried
    with exponential backoff; client errors (4xx) fail immediately.
    """
    request = Request(
        url,
        headers={
            "User-Agent": user_agent,
            **({"Referer": referer} if referer else {}),
        },
    )

    attempt = 0
    while True:
        try:
            with urlopen(request, timeout=timeout_seconds) as response:
                return response.read()
        except HTTPError as exc:
            if exc.code not in RETRYABLE_STATUS_CODES or attempt >= retries:
                raise
        except (URLError, TimeoutError, OSError):
            if attempt >= retries:
                raise
        sleep(backoff_seconds * (2**attempt))
        attempt += 1


def fetch_text(
    url: str,
    *,
    user_agent: str,
    timeout_seconds: int,
    encoding: str,
    referer: str | None = None,
    retries: int = DEFAULT_RETRIES,
    backoff_seconds: float = DEFAULT_BACKOFF_SECONDS,
) -> str:
    return fetch_bytes(
        url,
        user_agent=user_agent,
        timeout_seconds=timeout_seconds,
        referer=referer,
        retries=retries,
        backoff_seconds=backoff_seconds,
    ).decode(encoding, errors="ignore")
