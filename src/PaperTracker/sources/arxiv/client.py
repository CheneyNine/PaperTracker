"""arXiv API client.

Calls the arXiv Atom API over HTTP, with retry/backoff and HTTPS→HTTP fallback.
"""

from __future__ import annotations

import json
import random
import time
from email.utils import parsedate_to_datetime
from pathlib import Path
from tempfile import gettempdir
from typing import Optional

import requests

from PaperTracker.utils.log import log

ARXIV_HTTPS = "https://export.arxiv.org/api/query"
ARXIV_HTTP = "http://export.arxiv.org/api/query"

DEFAULT_TIMEOUT = 45.0
MAX_ATTEMPTS = 6
BASE_PAUSE = 1.5
MAX_SLEEP = 20
DEFAULT_MIN_INTERVAL_SECONDS = 5.0
TOO_MANY_REQUESTS_MAX_SLEEP = 180.0
RATE_LIMIT_STATE_PATH = Path(gettempdir()) / "paper-tracker-arxiv-rate-limit.json"

RETRYABLE_STATUS = {429, 500, 502, 503, 504}

HEADERS = {
    "User-Agent": "paper-tracker/0.2 (+https://github.com/CheneyNine/PaperTracker)",
    "Accept": "application/atom+xml,application/xml;q=0.9,*/*;q=0.8",
}


class ArxivRateLimitedError(RuntimeError):
    """Raised when arXiv rate-limits requests and the client aborts early."""


class ArxivApiClient:
    """Low-level HTTP client for the arXiv Atom API.

    Responsible only for making network requests and returning the raw feed XML.
    Parsing and domain mapping are handled elsewhere.
    """

    def __init__(
        self,
        *,
        min_interval_seconds: float = DEFAULT_MIN_INTERVAL_SECONDS,
        rate_limit_state_path: str | Path | None = None,
    ) -> None:
        """Initialize the client with a reusable HTTP session.

        Args:
            min_interval_seconds: Minimum spacing between arXiv requests.
            rate_limit_state_path: Optional shared state file used to carry
                rate-limit cooldowns across CLI runs.
        """
        self._session = requests.Session()
        self._min_interval_seconds = min_interval_seconds
        self._rate_limit_state_path = (
            Path(rate_limit_state_path)
            if rate_limit_state_path is not None
            else RATE_LIMIT_STATE_PATH
        )
        self._next_request_not_before = 0.0

    def close(self) -> None:
        """Close the underlying HTTP session and release pooled connections.
        """
        self._session.close()

    def __enter__(self) -> ArxivApiClient:
        """Enter context manager."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        """Exit context manager and close session."""
        self.close()

    def fetch_feed(
        self,
        *,
        search_query: str,
        start: int = 0,
        max_results: int = 10,
        sort_by: str = "submittedDate",
        sort_order: str = "descending",
        timeout: Optional[float] = None,
    ) -> str:
        """Fetch arXiv Atom feed XML using the official API endpoint.

        Args:
            search_query: arXiv API search_query string.
            start: Start offset.
            max_results: Maximum number of results.
            sort_by: Sort field.
            sort_order: Sort order.
            timeout: Optional request timeout in seconds.

        Returns:
            Atom feed XML text.

        Raises:
            Exception: Propagates the last request error after retries and HTTPS/HTTP fallback.
        """
        params = {
            "search_query": search_query,
            "start": str(start),
            "max_results": str(max_results),
            "sortBy": sort_by,
            "sortOrder": sort_order,
        }

        last_err: Exception | None = None
        for base_url in (ARXIV_HTTPS, ARXIV_HTTP):
            try:
                log.debug(
                    "arXiv fetch feed: base_url=%s start=%s max_results=%s sort_by=%s sort_order=%s",
                    base_url,
                    start,
                    max_results,
                    sort_by,
                    sort_order,
                )
                resp = self._get_with_retry(base_url, params=params, timeout=timeout)
                resp.raise_for_status()
                log.debug("arXiv response ok: status=%s bytes=%s", resp.status_code, len(resp.text))
                return resp.text
            except Exception as e:  # noqa: BLE001 - keep last error for fallback
                last_err = e
                log.debug("arXiv fetch failed for %s: %s", base_url, e)
                continue

        assert last_err is not None
        raise last_err

    def current_cooldown_seconds(self) -> float:
        """Return remaining shared arXiv cooldown seconds."""
        now = time.time()
        shared_next_allowed = self._read_shared_next_allowed_at()
        next_allowed = max(self._next_request_not_before, shared_next_allowed)
        return max(0.0, next_allowed - now)

    def _get_with_retry(
        self,
        base_url: str,
        *,
        params: dict[str, str],
        timeout: Optional[float],
    ) -> requests.Response:
        """Issue GET request with retry/backoff.

        Retries on timeouts/connection errors and selected HTTP status codes.

        Args:
            base_url: Endpoint base URL.
            params: Query parameters.
            timeout: Optional timeout seconds.

        Returns:
            requests.Response on success.

        Raises:
            Exception: Last observed error when all attempts failed.
        """
        timeout = timeout or DEFAULT_TIMEOUT
        last_err: Exception | None = None
        last_status_code: int | None = None

        for attempt in range(1, MAX_ATTEMPTS + 1):
            last_status_code = None
            try:
                self._wait_for_request_slot()
                log.info("arXiv request attempt %d/%d", attempt, MAX_ATTEMPTS)
                resp = self._session.get(base_url, params=params, headers=HEADERS, timeout=timeout)
                if resp.status_code in RETRYABLE_STATUS:
                    raise requests.exceptions.HTTPError(
                        f"HTTP {resp.status_code}",
                        response=resp,
                    )
                return resp
            except (
                requests.exceptions.Timeout,
                requests.exceptions.ReadTimeout,
                requests.exceptions.ConnectionError,
            ) as e:
                last_err = e
            except requests.exceptions.HTTPError as e:
                last_err = e
                st = getattr(e.response, "status_code", None)
                last_status_code = st if isinstance(st, int) else None
                if last_status_code == 429:
                    delay = self._resolve_429_delay(attempt, response=getattr(e, "response", None))
                    self._block_requests_for(delay)
                    raise ArxivRateLimitedError(
                        f"arXiv rate limited request; cooldown scheduled for {delay:.1f}s"
                    ) from e
                if st not in RETRYABLE_STATUS:
                    break

            if attempt < MAX_ATTEMPTS:
                log.warning("arXiv retry scheduled after attempt %d: %s", attempt, last_err)
                self._sleep_backoff(
                    attempt,
                    status_code=last_status_code,
                    response=getattr(last_err, "response", None),
                )

        assert last_err is not None
        raise last_err

    def _wait_for_request_slot(self) -> None:
        """Sleep until the next shared arXiv request slot becomes available."""
        now = time.time()
        shared_next_allowed = self._read_shared_next_allowed_at()
        next_allowed = max(now, self._next_request_not_before, shared_next_allowed)
        if next_allowed > now:
            delay = next_allowed - now
            log.info("arXiv waiting %.1fs before next request", delay)
            time.sleep(delay)
            now = time.time()

        reserved_until = now + self._min_interval_seconds
        self._next_request_not_before = reserved_until
        self._write_shared_next_allowed_at(reserved_until)

    def _sleep_backoff(
        self,
        attempt: int,
        *,
        status_code: int | None = None,
        response: requests.Response | None = None,
    ) -> None:
        """Sleep with status-aware backoff.

        Args:
            attempt: Current attempt index (1-based).
            status_code: Last HTTP status code when available.
            response: Optional HTTP response used for `Retry-After`.
        """
        if status_code == 429:
            delay = self._resolve_429_delay(attempt, response=response)
            self._block_requests_for(delay)
            time.sleep(delay)
            return

        delay = min(BASE_PAUSE * (2 ** (attempt - 1)) + random.uniform(0, 0.5), MAX_SLEEP)
        time.sleep(delay)

    def _resolve_429_delay(
        self,
        attempt: int,
        *,
        response: requests.Response | None,
    ) -> float:
        """Resolve the cooldown delay to use after HTTP 429."""
        retry_after_seconds = _parse_retry_after_seconds(response)
        if retry_after_seconds is not None:
            return min(max(retry_after_seconds, self._min_interval_seconds), TOO_MANY_REQUESTS_MAX_SLEEP)

        fallback = self._min_interval_seconds * (2 ** attempt)
        return min(fallback, TOO_MANY_REQUESTS_MAX_SLEEP)

    def _block_requests_for(self, delay: float) -> None:
        """Persist a shared cooldown so subsequent runs also wait."""
        next_allowed = time.time() + max(delay, self._min_interval_seconds)
        self._next_request_not_before = max(self._next_request_not_before, next_allowed)
        self._write_shared_next_allowed_at(next_allowed)

    def _read_shared_next_allowed_at(self) -> float:
        """Load the persisted shared cooldown timestamp."""
        try:
            payload = json.loads(self._rate_limit_state_path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return 0.0
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            return 0.0

        value = payload.get("next_allowed_at")
        if isinstance(value, (int, float)):
            return float(value)
        return 0.0

    def _write_shared_next_allowed_at(self, next_allowed_at: float) -> None:
        """Persist the shared cooldown timestamp atomically."""
        try:
            self._rate_limit_state_path.parent.mkdir(parents=True, exist_ok=True)
            temp_path = self._rate_limit_state_path.with_suffix(".tmp")
            payload = {"next_allowed_at": next_allowed_at}
            temp_path.write_text(json.dumps(payload), encoding="utf-8")
            temp_path.replace(self._rate_limit_state_path)
        except OSError:
            log.debug("arXiv rate-limit state write failed: %s", self._rate_limit_state_path)


def _parse_retry_after_seconds(response: requests.Response | None) -> float | None:
    """Parse `Retry-After` into seconds when possible."""
    if response is None:
        return None

    raw_value = response.headers.get("Retry-After", "").strip()
    if not raw_value:
        return None

    try:
        return max(float(raw_value), 0.0)
    except ValueError:
        pass

    try:
        retry_after_at = parsedate_to_datetime(raw_value)
    except (TypeError, ValueError, IndexError, OverflowError):
        return None

    if retry_after_at.tzinfo is None:
        retry_after_at = retry_after_at.astimezone()

    return max(retry_after_at.timestamp() - time.time(), 0.0)
