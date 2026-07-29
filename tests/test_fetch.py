"""Conditional-fetch behaviour: 200 stores validators, 304 reuses cache, errors don't delete."""

from registry.fetch import (
    FetchCache,
    RawResponse,
    Validators,
    conditional_fetch,
)


class SequenceTransport:
    """Returns queued responses in order, recording the headers it was asked to send."""

    def __init__(self, responses: list[RawResponse]) -> None:
        self._responses = responses
        self.sent_headers: list[dict[str, str]] = []
        self._i = 0

    def request(self, url: str, headers: dict[str, str]) -> RawResponse:
        self.sent_headers.append(dict(headers))
        resp = self._responses[self._i]
        self._i += 1
        if isinstance(resp, Exception):  # pragma: no cover - defensive
            raise resp
        return resp


def test_200_stores_validators_then_304_reuses_body() -> None:
    cache = FetchCache()
    url = "https://example.test/api.json"
    transport = SequenceTransport(
        [
            RawResponse(status=200, body=b'{"a":1}', etag='"v1"', last_modified="Mon, 01 Jan 2026 00:00:00 GMT"),
            RawResponse(status=304),
        ]
    )

    first = conditional_fetch(url, transport, cache)
    assert first.outcome == "ok"
    assert first.body == b'{"a":1}'
    assert first.etag == '"v1"'
    # First request carried no conditional headers (nothing cached yet).
    assert "If-None-Match" not in transport.sent_headers[0]

    second = conditional_fetch(url, transport, cache)
    assert second.outcome == "not_modified"
    assert second.not_modified
    # The revalidation sent both validators...
    assert transport.sent_headers[1]["If-None-Match"] == '"v1"'
    assert transport.sent_headers[1]["If-Modified-Since"] == "Mon, 01 Jan 2026 00:00:00 GMT"
    # ...and the 304 reused the cached body byte-for-byte.
    assert second.body == b'{"a":1}'


def test_error_after_retries_reports_stale_not_deletion() -> None:
    cache = FetchCache()
    cache.store("https://example.test/x", b"cached", Validators(etag='"e"'))
    transport = SequenceTransport([RawResponse(status=500), RawResponse(status=500), RawResponse(status=500)])

    result = conditional_fetch("https://example.test/x", transport, cache, retries=2)
    # A source that fails is recorded as stale (cached body retained), never as gone.
    assert result.outcome == "stale"
    assert result.body == b"cached"
    assert result.error == "HTTP 500"


def test_error_with_no_cache_is_error_outcome() -> None:
    cache = FetchCache()
    transport = SequenceTransport([RawResponse(status=503)])
    result = conditional_fetch("https://example.test/y", transport, cache, retries=0)
    assert result.outcome == "error"
    assert result.body == b""
