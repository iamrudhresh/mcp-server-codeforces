"""
Hardened async HTTP client for the official Codeforces API.

Mirrors `src/http.js`: global throttling, TTL caching, bounded retries with
exponential backoff, redirect pinning and the Codeforces `status: FAILED`
envelope. A single shared `httpx.AsyncClient` is reused and closed cleanly on
shutdown.
"""

import asyncio
import re
import time
from typing import Any, Optional
from urllib.parse import urlencode

import httpx

from app.config import config
from app.utils.errors import CodeforcesError
from app.utils.logger import logger

_ALLOWED_HOST = "codeforces.com"

# `contest.standings` only accepts a bare ?contestId= for anonymous callers;
# Codeforces rejects every extra parameter, including `lang`.
_BARE_ENDPOINTS = {"contest.standings"}

_HANDLE_RE = re.compile(r"^[A-Za-z0-9._-]{3,24}$")
_RATE_LIMIT_RE = re.compile(r"call limit exceeded|limit exceeded", re.IGNORECASE)
_NOT_FOUND_RE = re.compile(r"not found|does not exist|incorrect|invalid", re.IGNORECASE)

# ── Shared state ───────────────────────────────────────────────────

_client: Optional[httpx.AsyncClient] = None
_client_lock = asyncio.Lock()
_throttle_lock = asyncio.Lock()
_last_request_at: float = 0.0

_cache: dict[str, tuple[float, Any]] = {}
_last_error: Optional[dict] = None
_last_latency_ms: Optional[int] = None


async def get_client() -> httpx.AsyncClient:
    """Lazily create the shared HTTP client."""
    global _client
    async with _client_lock:
        if _client is None or _client.is_closed:
            _client = httpx.AsyncClient(
                timeout=config.REQUEST_TIMEOUT,
                follow_redirects=True,
                headers={
                    "Accept": "application/json",
                    "User-Agent": config.USER_AGENT,
                },
            )
        return _client


async def close_client() -> None:
    """Close the shared HTTP client. Safe to call multiple times."""
    global _client
    async with _client_lock:
        if _client is not None and not _client.is_closed:
            await _client.aclose()
        _client = None


def is_valid_handle(handle: Any) -> bool:
    """Codeforces handles: letters, digits, dot, dash, underscore, 3-24 chars."""
    return isinstance(handle, str) and bool(_HANDLE_RE.match(handle))


def assert_handle(handle: Any) -> str:
    """Validate a handle locally so malformed input never costs an API call."""
    if not is_valid_handle(handle):
        raise CodeforcesError(
            f"Invalid Codeforces handle: {handle!r}. "
            "Handles are 3-24 characters of letters, digits, '.', '-' or '_'.",
            code="INVALID_HANDLE",
        )
    return handle


def is_rate_limit_comment(comment: Any) -> bool:
    """Detect the Codeforces 'call limit exceeded' soft rate-limit."""
    return isinstance(comment, str) and bool(_RATE_LIMIT_RE.search(comment))


def build_url(endpoint: str, params: Optional[dict] = None) -> str:
    """
    Build an API URL.

    IMPORTANT: Codeforces returns Russian names unless `lang=en` is supplied,
    except for the bare-only endpoints which reject it.
    """
    base = f"{config.CODEFORCES_API_URL}/{endpoint}"
    params = params or {}

    if endpoint in _BARE_ENDPOINTS:
        contest_id = params.get("contestId")
        return f"{base}?contestId={contest_id}" if contest_id is not None else base

    query = {"lang": config.CODEFORCES_LANG}
    for key, value in params.items():
        if value is None or value == "":
            continue
        query[key] = value
    return f"{base}?{urlencode(query)}"


def clear_cache() -> None:
    """Drop every cached response. Used by the test suite."""
    global _last_error, _last_latency_ms
    _cache.clear()
    _last_error = None
    _last_latency_ms = None


def health_snapshot() -> dict:
    """Snapshot of observed upstream health, used by the `get_health` tool."""
    return {
        "lastError": _last_error,
        "lastLatencyMs": _last_latency_ms,
        "cachedEntries": len(_cache),
    }


def _prune_cache() -> None:
    if len(_cache) <= config.MAX_CACHE_ENTRIES:
        return
    oldest = sorted(_cache.items(), key=lambda item: item[1][0])
    for key, _ in oldest[: len(_cache) - config.MAX_CACHE_ENTRIES]:
        _cache.pop(key, None)


async def _throttle() -> None:
    """Serialize outbound requests to respect the Codeforces rate limit."""
    global _last_request_at
    async with _throttle_lock:
        wait = config.MIN_REQUEST_INTERVAL - (time.monotonic() - _last_request_at)
        if wait > 0:
            await asyncio.sleep(wait)
        _last_request_at = time.monotonic()


async def call_api(
    endpoint: str,
    params: Optional[dict] = None,
    *,
    force: bool = False,
    ttl: Optional[int] = None,
) -> Any:
    """
    Call a Codeforces API method and return its unwrapped ``result`` payload.

    Raises:
        CodeforcesError: with a stable ``code`` for every failure mode.
    """
    global _last_error, _last_latency_ms

    url = build_url(endpoint, params)
    ttl_seconds = config.CACHE_TTL if ttl is None else ttl

    cached = _cache.get(url)
    if not force and cached and time.monotonic() - cached[0] < ttl_seconds:
        return cached[1]

    client = await get_client()
    last_error: Optional[CodeforcesError] = None

    for attempt in range(config.MAX_RETRIES):
        await _throttle()
        started = time.monotonic()
        try:
            response = await client.get(url)

            host = httpx.URL(str(response.url)).host or ""
            if host.replace("www.", "") != _ALLOWED_HOST:
                raise CodeforcesError(
                    f"Refusing response redirected to unexpected host: {host}",
                    code="UNEXPECTED_REDIRECT",
                )

            if response.status_code == 429:
                retry_after = response.headers.get("retry-after")
                delay_ms = int(float(retry_after) * 1000) if retry_after else 2000
                last_error = CodeforcesError(
                    "Codeforces API rate limit exceeded.",
                    code="RATE_LIMITED",
                    status=429,
                    retryable=True,
                    retry_after_ms=delay_ms,
                )
                await asyncio.sleep(delay_ms / 1000)
                continue

            # HTTP 400 still carries a meaningful Codeforces envelope, so only
            # 403/5xx count as transport-level failures.
            if response.status_code >= 500 or response.status_code == 403:
                last_error = CodeforcesError(
                    f"Codeforces responded with HTTP {response.status_code}.",
                    code="UPSTREAM",
                    status=response.status_code,
                    retryable=True,
                )
                await asyncio.sleep(0.6 * (2**attempt))
                continue

            try:
                payload = response.json()
            except Exception as exc:
                raise CodeforcesError(
                    "Codeforces API returned invalid JSON.",
                    code="SCHEMA_CHANGED",
                    retryable=True,
                ) from exc

            if payload.get("status") == "FAILED":
                comment = payload.get("comment") or "Codeforces API returned status FAILED."
                if is_rate_limit_comment(comment):
                    last_error = CodeforcesError(
                        comment, code="RATE_LIMITED", retryable=True, retry_after_ms=2000
                    )
                    await asyncio.sleep(2)
                    continue
                raise CodeforcesError(
                    comment,
                    code="NOT_FOUND" if _NOT_FOUND_RE.search(comment) else "UPSTREAM",
                    status=response.status_code,
                )

            if payload.get("status") != "OK" or "result" not in payload:
                raise CodeforcesError(
                    "Codeforces API response did not match the expected envelope.",
                    code="SCHEMA_CHANGED",
                )

            result = payload["result"]
            _last_latency_ms = int((time.monotonic() - started) * 1000)
            _last_error = None
            _cache[url] = (time.monotonic(), result)
            _prune_cache()
            return result

        except CodeforcesError as err:
            if not err.retryable:
                _last_error = {"code": err.code, "message": err.message}
                raise
            last_error = err
            await asyncio.sleep(0.6 * (2**attempt))
        except httpx.TimeoutException as err:
            last_error = CodeforcesError(
                "Codeforces API request timed out.", code="NETWORK_TIMEOUT", retryable=True
            )
            logger.warning("Timeout calling %s (attempt %d): %s", endpoint, attempt + 1, err)
            await asyncio.sleep(0.6 * (2**attempt))
        except httpx.HTTPError as err:
            last_error = CodeforcesError(str(err), code="UPSTREAM", retryable=True)
            logger.warning("HTTP error calling %s (attempt %d): %s", endpoint, attempt + 1, err)
            await asyncio.sleep(0.6 * (2**attempt))

    final = last_error or CodeforcesError(
        f"Codeforces request failed after {config.MAX_RETRIES} attempts.",
        code="FETCH_FAILED",
        retryable=True,
    )
    _last_error = {"code": final.code, "message": final.message}
    raise final
