"""Conditional-fetch helper: ETag / Last-Modified revalidation, retry/backoff, per-source cache.

The connectors call :func:`conditional_fetch`. Tests inject a fake transport (see
``tests/test_fetch.py``) so 200-vs-304 behaviour is exercised without a network. Determinism in the
build pipeline instead comes from the fixture cache (``FixtureTransport``): a saved raw response with
its validators, replayed byte-for-byte.
"""

from __future__ import annotations

import hashlib
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Protocol

PARSER_ENV_NOTE = "network responses are cached with validators; a 304 reuses cached bytes"


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
    def request(self, url: str, headers: dict[str, str]) -> RawResponse: ...


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
    """Per-URL cache of the last successful body + validators (in-memory for the PoC)."""

    _bodies: dict[str, bytes] = field(default_factory=dict)
    _validators: dict[str, Validators] = field(default_factory=dict)

    def validators_for(self, url: str) -> Validators:
        return self._validators.get(url, Validators())

    def body_for(self, url: str) -> bytes | None:
        return self._bodies.get(url)

    def store(self, url: str, body: bytes, validators: Validators) -> None:
        self._bodies[url] = body
        self._validators[url] = validators


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def conditional_fetch(
    url: str,
    transport: Transport,
    cache: FetchCache,
    *,
    retries: int = 2,
    backoff_seconds: float = 0.0,
    extra_headers: dict[str, str] | None = None,
) -> FetchResult:
    """Fetch ``url`` conditionally.

    Sends ``If-None-Match`` / ``If-Modified-Since`` from ``cache`` when present. A ``304`` reuses the
    cached body (``outcome="not_modified"``); a ``200`` refreshes cache + validators. Transport errors
    are retried with backoff, then reported as ``outcome="error"`` reusing any stale cached body
    (``outcome="stale"`` if one exists) — *absence of a fresh response is never treated as deletion*.
    """
    prior = cache.validators_for(url)
    # Static per-source headers (e.g. an auth key for a credentialed source) are seeded first; the
    # conditional-request validators below are layered on top. Auth secrets live only in the request
    # headers, never in a snapshot/record — the fetch layer is the only place they appear.
    headers: dict[str, str] = dict(extra_headers or {})
    if prior.etag:
        headers["If-None-Match"] = prior.etag
    if prior.last_modified:
        headers["If-Modified-Since"] = prior.last_modified

    last_error: str | None = None
    for attempt in range(retries + 1):
        try:
            resp = transport.request(url, headers)
        except Exception as exc:  # noqa: BLE001 - report, don't crash the pipeline on one source
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retries:
                time.sleep(backoff_seconds)
                continue
            break
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
            if attempt < retries:
                time.sleep(backoff_seconds)
                continue
            break

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
