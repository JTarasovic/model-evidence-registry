"""Conditional HTTP fetching, cache revalidation, and bounded request policies.

Connectors only declare a :class:`FetchPolicy` and parse bytes.  The build scheduler owns request
ordering, clocks, and rate limiting; this module keeps conditional requests and failure semantics
consistent for both live and fixture transports.
"""

from __future__ import annotations

import hashlib
import random
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from threading import Condition, RLock
from typing import Protocol
from urllib.parse import urlsplit

PARSER_ENV_NOTE = "network responses are cached with validators; a 304 reuses cached bytes"


class Clock(Protocol):
    """Injectable time source; tests can advance it without a real sleep."""

    def monotonic(self) -> float: ...

    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def monotonic(self) -> float:
        return time.monotonic()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


@dataclass(frozen=True)
class FetchPolicy:
    """Scheduling limits declared by a connector, not implemented by its parser.

    A missing ``source_key`` is resolved to the URL host.  Providers with several endpoints should
    give each connector the same explicit key, so their aggregate request rate remains bounded.
    """

    source_key: str | None = None
    max_concurrency: int = 1
    min_interval_seconds: float = 0.0
    timeout_seconds: float = 30.0
    source_budget_seconds: float = 90.0
    retries: int = 2
    backoff_seconds: float = 0.25
    max_backoff_seconds: float = 4.0
    jitter_seconds: float = 0.1

    def validated(self) -> FetchPolicy:
        if self.max_concurrency < 1:
            raise ValueError("fetch policy max_concurrency must be at least 1")
        if self.min_interval_seconds < 0 or self.timeout_seconds <= 0 or self.source_budget_seconds <= 0:
            raise ValueError("fetch policy intervals, timeout, and budget must be positive")
        if self.retries < 0 or self.backoff_seconds < 0 or self.max_backoff_seconds < 0 or self.jitter_seconds < 0:
            raise ValueError("fetch policy retry values must not be negative")
        return self

    def key_for(self, url: str) -> str:
        return self.source_key or urlsplit(url).netloc.lower()


def _utcnow() -> str:
    return datetime.now(UTC).isoformat()


@dataclass(frozen=True)
class Validators:
    """HTTP cache validators carried across fetches for one URL."""

    etag: str | None = None
    last_modified: str | None = None


@dataclass
class RawResponse:
    """A concrete transport response. status 304 carries no fresh body."""

    status: int
    body: bytes = b""
    etag: str | None = None
    last_modified: str | None = None


class Transport(Protocol):
    def request(self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None) -> RawResponse: ...


@dataclass
class FetchResult:
    url: str
    outcome: str  # "ok" | "not_modified" | "error" | "stale"
    body: bytes
    etag: str | None
    last_modified: str | None
    content_sha256: str | None
    retrieved_at: str
    error: str | None = None

    @property
    def not_modified(self) -> bool:
        return self.outcome == "not_modified"


@dataclass
class FetchCache:
    """Thread-safe, per-URL last-successful bytes and HTTP validators."""

    _bodies: dict[str, bytes] = field(default_factory=dict)
    _validators: dict[str, Validators] = field(default_factory=dict)
    _lock: RLock = field(default_factory=RLock, init=False, repr=False)

    def validators_for(self, url: str) -> Validators:
        with self._lock:
            return self._validators.get(url, Validators())

    def body_for(self, url: str) -> bytes | None:
        with self._lock:
            return self._bodies.get(url)

    def store(self, url: str, body: bytes, validators: Validators) -> None:
        with self._lock:
            self._bodies[url] = body
            self._validators[url] = validators


class SourceRateLimiter:
    """Shared, source-aware request gate used by the bounded build worker pool."""

    def __init__(self, clock: Clock) -> None:
        self._clock = clock
        self._condition = Condition()
        self._in_flight: dict[str, int] = {}
        self._next_request_at: dict[str, float] = {}

    def acquire(self, policy: FetchPolicy, url: str, deadline: float) -> bool:
        """Reserve one request slot before ``deadline``; never sleeps while holding the lock."""
        policy = policy.validated()
        key = policy.key_for(url)
        while True:
            with self._condition:
                now = self._clock.monotonic()
                if now >= deadline:
                    return False
                in_flight = self._in_flight.get(key, 0)
                next_request_at = self._next_request_at.get(key, now)
                if in_flight < policy.max_concurrency and now >= next_request_at:
                    self._in_flight[key] = in_flight + 1
                    self._next_request_at[key] = now + policy.min_interval_seconds
                    return True
                if in_flight >= policy.max_concurrency:
                    # A running request will notify us on release.  A short timeout also makes a
                    # finite deadline observable if a non-conforming transport never returns.
                    self._condition.wait(timeout=min(0.05, max(0.0, deadline - now)))
                    continue
                delay = min(next_request_at - now, deadline - now)
            # The clock is injected so fixture/scheduler tests can advance instantly without a
            # wall-clock sleep.  This delay affects only this source key.
            if delay > 0:
                self._clock.sleep(delay)

    def release(self, policy: FetchPolicy, url: str) -> None:
        key = policy.key_for(url)
        with self._condition:
            self._in_flight[key] = max(0, self._in_flight.get(key, 1) - 1)
            self._condition.notify_all()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def conditional_fetch(
    url: str,
    transport: Transport,
    cache: FetchCache,
    *,
    retries: int = 2,
    backoff_seconds: float = 0.0,
    max_backoff_seconds: float | None = None,
    jitter_seconds: float = 0.0,
    timeout_seconds: float = 30.0,
    source_budget_seconds: float | None = None,
    extra_headers: dict[str, str] | None = None,
    clock: Clock | None = None,
    random_uniform: Callable[[float, float], float] = random.uniform,
    request_gate: Callable[[float], bool] | None = None,
    request_release: Callable[[], None] | None = None,
) -> FetchResult:
    """Fetch ``url`` conditionally with finite retries and a finite source budget.

    An HTTP 304 exactly reuses cached bytes.  Retry/deadline/HTTP failures yield ``stale`` if those
    bytes exist and ``error`` otherwise; neither result is evidence of a deletion.
    """
    if retries < 0 or backoff_seconds < 0 or jitter_seconds < 0 or timeout_seconds <= 0:
        raise ValueError("invalid fetch retry or timeout configuration")
    current_clock = clock or SystemClock()
    deadline = (
        current_clock.monotonic() + source_budget_seconds if source_budget_seconds is not None else None
    )
    prior = cache.validators_for(url)
    headers: dict[str, str] = dict(extra_headers or {})
    if prior.etag:
        headers["If-None-Match"] = prior.etag
    if prior.last_modified:
        headers["If-Modified-Since"] = prior.last_modified

    last_error: str | None = None
    for attempt in range(retries + 1):
        if deadline is not None and current_clock.monotonic() >= deadline:
            last_error = "source deadline exceeded"
            break
        if request_gate is not None and not request_gate(deadline if deadline is not None else float("inf")):
            last_error = "source deadline exceeded before request"
            break
        try:
            remaining = deadline - current_clock.monotonic() if deadline is not None else timeout_seconds
            request_timeout = min(timeout_seconds, max(0.001, remaining))
            resp = transport.request(url, headers, timeout_seconds=request_timeout)
        except Exception as exc:  # noqa: BLE001 - one source must not abort a build
            last_error = f"{type(exc).__name__}: {exc}"
        else:
            if resp.status == 304:
                cached = cache.body_for(url) or b""
                return FetchResult(
                    url=url,
                    outcome="not_modified",
                    body=cached,
                    etag=prior.etag,
                    last_modified=prior.last_modified,
                    content_sha256=sha256_hex(cached) if cached else None,
                    retrieved_at=_utcnow(),
                )
            if 200 <= resp.status < 300:
                validators = Validators(etag=resp.etag, last_modified=resp.last_modified)
                cache.store(url, resp.body, validators)
                return FetchResult(
                    url=url,
                    outcome="ok",
                    body=resp.body,
                    etag=resp.etag,
                    last_modified=resp.last_modified,
                    content_sha256=sha256_hex(resp.body),
                    retrieved_at=_utcnow(),
                )
            last_error = f"HTTP {resp.status}"
        finally:
            if request_release is not None:
                request_release()

        if attempt < retries:
            delay = backoff_seconds * (2**attempt)
            if max_backoff_seconds is not None:
                delay = min(delay, max_backoff_seconds)
            if jitter_seconds:
                delay += random_uniform(0.0, jitter_seconds)
            if deadline is not None:
                delay = min(delay, max(0.0, deadline - current_clock.monotonic()))
            if delay > 0:
                current_clock.sleep(delay)

    stale_body = cache.body_for(url)
    return FetchResult(
        url=url,
        outcome="stale" if stale_body else "error",
        body=stale_body or b"",
        etag=prior.etag,
        last_modified=prior.last_modified,
        content_sha256=sha256_hex(stale_body) if stale_body else None,
        retrieved_at=_utcnow(),
        error=last_error,
    )
