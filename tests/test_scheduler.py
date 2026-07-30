"""Bounded concurrent scheduler behaviour with controllable transports and clocks."""

from __future__ import annotations

from queue import Queue
from threading import Event, Lock, Thread

from registry.build import build, shared_source_policies
from registry.fetch import FetchCache, FetchPolicy, RawResponse, SourceRateLimiter, Validators, conditional_fetch
from registry.schema import ClaimRecord, Record, SourceSnapshotRecord, TrustLevel


class _Connector:
    license = "test"
    parser_version = "1"
    trust_level = TrustLevel.THIRD_PARTY_REPORT

    def __init__(self, source_id: str, policy: FetchPolicy | None = None) -> None:
        self.source_id = source_id
        self.url = f"https://{source_id}.test/data"
        self.fetch_policy = policy or FetchPolicy(retries=0, jitter_seconds=0.0)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        return [
            ClaimRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                model_id=body.decode(),
                benchmark_name="test",
                value="1",
                source_url=self.url,
            )
        ]


class _OutOfOrderTransport:
    """Starts every request, then completes them in reverse declared order."""

    def __init__(self, count: int) -> None:
        self._count = count
        self._started = 0
        self._all_started = Event()
        self._lock = Lock()

    def request(
        self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None
    ) -> RawResponse:  # noqa: ARG002
        with self._lock:
            self._started += 1
            if self._started == self._count:
                self._all_started.set()
        assert self._all_started.wait(timeout=1)
        return RawResponse(status=200, body=url.split("//", maxsplit=1)[1].split(".", maxsplit=1)[0].encode())


def test_concurrent_completion_does_not_change_artifact_or_snapshot_order() -> None:
    connectors = [_Connector("first"), _Connector("second"), _Connector("third")]
    result = build(
        connectors,
        _OutOfOrderTransport(len(connectors)),
        cache=FetchCache(),
        now="2026-07-30T00:00:00+00:00",
        global_concurrency=3,
    )
    claims = [record for record in result.artifact.records if isinstance(record, ClaimRecord)]
    snapshots = [record for record in result.artifact.records if isinstance(record, SourceSnapshotRecord)]
    assert [claim.source_id for claim in claims] == ["first", "second", "third"]
    assert [snapshot.source_id for snapshot in snapshots] == ["first", "second", "third"]


class _GatedTransport:
    def __init__(self) -> None:
        self.started: Queue[str] = Queue()
        self.release: dict[str, Event] = {}
        self.active = 0
        self.max_active = 0
        self._lock = Lock()

    def request(
        self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None
    ) -> RawResponse:  # noqa: ARG002
        source = url.split("//", maxsplit=1)[1].split(".", maxsplit=1)[0]
        gate = self.release.setdefault(source, Event())
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        self.started.put(source)
        assert gate.wait(timeout=1)
        with self._lock:
            self.active -= 1
        return RawResponse(status=200, body=source.encode())


def test_shared_source_key_never_exceeds_its_declared_request_concurrency() -> None:
    policy = FetchPolicy(source_key="one-provider", max_concurrency=1, retries=0, jitter_seconds=0.0)
    connectors = [_Connector("one", policy), _Connector("two", policy)]
    transport = _GatedTransport()
    result: list = []
    worker = Thread(
        target=lambda: result.append(
            build(connectors, transport, cache=FetchCache(), now="2026-07-30T00:00:00+00:00", global_concurrency=2)
        )
    )
    worker.start()
    first = transport.started.get(timeout=1)
    # The other connector is scheduled but cannot enter the transport until this source's request
    # completes, proving the policy gates in-flight requests rather than just connector jobs.
    assert transport.started.empty()
    transport.release[first].set()
    second = transport.started.get(timeout=1)
    transport.release[second].set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert result
    assert transport.max_active == 1


def test_mixed_shared_source_policies_use_the_strictest_rate_limits() -> None:
    loose = FetchPolicy(
        source_key="one-provider", max_concurrency=2, min_interval_seconds=0.0, retries=0, jitter_seconds=0.0
    )
    strict = FetchPolicy(
        source_key="one-provider", max_concurrency=1, min_interval_seconds=2.0, retries=0, jitter_seconds=0.0
    )
    connectors = [_Connector("one", loose), _Connector("two", strict)]
    policies = shared_source_policies(connectors, [loose, strict])
    assert [(policy.max_concurrency, policy.min_interval_seconds) for policy in policies] == [(1, 2.0), (1, 2.0)]

    clock = _FakeClock()
    transport = _GatedTransport()
    result: list = []
    worker = Thread(
        target=lambda: result.append(
            build(
                connectors,
                transport,
                cache=FetchCache(),
                now="2026-07-30T00:00:00+00:00",
                global_concurrency=2,
                clock=clock,
            )
        )
    )
    worker.start()
    first = transport.started.get(timeout=1)
    assert transport.started.empty()
    transport.release[first].set()
    second = transport.started.get(timeout=1)
    transport.release[second].set()
    worker.join(timeout=1)
    assert not worker.is_alive()
    assert result
    assert transport.max_active == 1
    assert clock.sleeps == [2.0]


class _FakeClock:
    def __init__(self) -> None:
        self.now = 0.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


def test_source_minimum_interval_uses_injected_clock_without_a_real_sleep() -> None:
    clock = _FakeClock()
    limiter = SourceRateLimiter(clock)
    policy = FetchPolicy(source_key="provider", min_interval_seconds=2.0)
    assert limiter.acquire(policy, "https://one.test/a", deadline=10.0)
    limiter.release(policy, "https://one.test/a")
    assert limiter.acquire(policy, "https://two.test/b", deadline=10.0)
    assert clock.sleeps == [2.0]
    assert clock.now == 2.0


class _FailingTransport:
    def __init__(self) -> None:
        self.requests = 0

    def request(
        self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None
    ) -> RawResponse:  # noqa: ARG002
        self.requests += 1
        return RawResponse(status=503)


def test_source_deadline_bounds_exponential_retries_and_keeps_cached_bytes_stale() -> None:
    clock = _FakeClock()
    cache = FetchCache()
    url = "https://provider.test/data"
    cache.store(url, b"cached", Validators(etag='"v1"'))
    transport = _FailingTransport()
    result = conditional_fetch(
        url,
        transport,
        cache,
        retries=5,
        backoff_seconds=0.5,
        max_backoff_seconds=1.0,
        source_budget_seconds=0.75,
        clock=clock,
    )
    assert transport.requests == 2
    assert clock.sleeps == [0.5, 0.25]
    assert result.outcome == "stale"
    assert result.body == b"cached"
    assert result.error == "source deadline exceeded"
