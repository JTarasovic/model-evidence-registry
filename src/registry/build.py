"""Build orchestrator: fetch (conditional, cached) -> parse -> collect records + snapshots.

Keeps connectors pure ``bytes -> records`` parsers. Fetching, snapshot bookkeeping, and the
"a failed/stale source is recorded, not treated as a deletion" rule live here.
"""

from __future__ import annotations

from collections.abc import Sequence
from concurrent.futures import FIRST_COMPLETED, Future, ThreadPoolExecutor, wait
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from registry.connectors.base import Connector, snapshot_from_fetch
from registry.fetch import (
    Clock,
    FetchCache,
    FetchPolicy,
    FetchResult,
    RawResponse,
    SourceRateLimiter,
    SystemClock,
    Transport,
    conditional_fetch,
    sha256_hex,
)
from registry.normalize import build_crosswalk
from registry.schema import Artifact, Crosswalk, FetchOutcome, Record


@dataclass
class FixtureTransport:
    """Replays saved fixtures by URL — the deterministic, no-network transport for builds/tests.

    ``fixtures_dir`` holds source-response files. JSON remains the default filename convention, but
    connectors whose source is HTML (or another format) declare ``fixture_filename`` explicitly.
    ``url_to_fixture`` maps each connector URL to that filename. Optionally returns 304 for URLs
    whose validators already match (``not_modified``).
    """

    fixtures_dir: Path
    url_to_fixture: dict[str, str]
    return_304_for: set[str] = field(default_factory=set)

    def request(self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None) -> RawResponse:
        if url in self.return_304_for and (
            "If-None-Match" in headers or "If-Modified-Since" in headers
        ):
            return RawResponse(status=304)
        body = (self.fixtures_dir / self.url_to_fixture[url]).read_bytes()
        return RawResponse(
            status=200,
            body=body,
            etag=f'"{sha256_hex(body)[:16]}"',
            last_modified="Wed, 29 Jul 2026 00:00:00 GMT",
        )


@dataclass
class BuildResult:
    artifact: Artifact
    crosswalk: Crosswalk
    snapshots: list  # list[SourceSnapshotRecord]


DEFAULT_GLOBAL_CONCURRENCY = 8
FIXTURE_GENERATED_AT = "2026-07-29T00:00:00+00:00"


def fetch_policy_for(connector: Connector) -> FetchPolicy:
    """Read opt-in connector metadata, preserving compatibility with existing connectors."""
    declared = getattr(connector, "fetch_policy", None)
    if declared is None:
        return FetchPolicy()
    if not isinstance(declared, FetchPolicy):
        raise TypeError(f"{connector.source_id}.fetch_policy must be a FetchPolicy")
    return declared.validated()


def shared_source_policies(
    connectors: Sequence[Connector], policies: Sequence[FetchPolicy]
) -> list[FetchPolicy]:
    """Apply one conservative set of rate limits to each declared source key.

    Multiple endpoints may deliberately share a source key while having different request
    timeouts or retry budgets.  Their rate limits, however, govern the provider as a whole:
    the lowest declared concurrency and greatest declared interval therefore apply to every
    connector for that key.
    """
    limits_by_source: dict[str, tuple[int, float]] = {}
    for connector, policy in zip(connectors, policies, strict=True):
        key = policy.key_for(connector.url)
        existing = limits_by_source.get(key)
        if existing is None:
            limits_by_source[key] = (policy.max_concurrency, policy.min_interval_seconds)
        else:
            limits_by_source[key] = (
                min(existing[0], policy.max_concurrency),
                max(existing[1], policy.min_interval_seconds),
            )
    return [
        replace(
            policy,
            max_concurrency=limits_by_source[policy.key_for(connector.url)][0],
            min_interval_seconds=limits_by_source[policy.key_for(connector.url)][1],
        )
        for connector, policy in zip(connectors, policies, strict=True)
    ]


def _fetch_connector(
    connector: Connector,
    transport: Transport,
    cache: FetchCache,
    policy: FetchPolicy,
    limiter: SourceRateLimiter,
    clock: Clock,
) -> FetchResult:
    """Perform one connector's bounded request/retry sequence in a scheduler worker."""
    auth_fn = getattr(connector, "auth_headers", None)
    extra_headers = cast("dict[str, str] | None", auth_fn() if callable(auth_fn) else None)
    return conditional_fetch(
        connector.url,
        transport,
        cache,
        retries=policy.retries,
        backoff_seconds=policy.backoff_seconds,
        max_backoff_seconds=policy.max_backoff_seconds,
        jitter_seconds=policy.jitter_seconds,
        timeout_seconds=policy.timeout_seconds,
        source_budget_seconds=policy.source_budget_seconds,
        extra_headers=extra_headers,
        clock=clock,
        request_gate=lambda deadline: limiter.acquire(policy, connector.url, deadline),
        request_release=lambda: limiter.release(policy, connector.url),
    )


def build(
    connectors: Sequence[Connector],
    transport: Transport,
    *,
    cache: FetchCache | None = None,
    now: str | None = None,
    global_concurrency: int = DEFAULT_GLOBAL_CONCURRENCY,
    clock: Clock | None = None,
) -> BuildResult:
    if global_concurrency < 1:
        raise ValueError("global_concurrency must be at least 1")
    cache = cache or FetchCache()
    # Fixture replays are byte-stable even when callers omit ``now``.  Live builds retain their
    # actual build time, while tests can still provide an explicit timestamp for either mode.
    generated_at = now or (
        FIXTURE_GENERATED_AT if isinstance(transport, FixtureTransport) else datetime.now(UTC).isoformat()
    )
    current_clock = clock or SystemClock()
    records: list[Record] = []
    snapshots = []
    policies = shared_source_policies(connectors, [fetch_policy_for(connector) for connector in connectors])
    limiter = SourceRateLimiter(current_clock)
    # A finite worker pool bounds all in-flight transport requests.  At most each source policy's
    # request concurrency is submitted at once, so a rate-delayed provider cannot fill the pool and
    # make unrelated hosts wait behind its sleeps.  Results are consumed below in declared connector
    # order, not completion order, so the artifact and manifest remain stable.
    pending = list(enumerate(zip(connectors, policies, strict=True)))
    results_by_index: dict[int, FetchResult] = {}
    active_by_source: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=global_concurrency, thread_name_prefix="registry-fetch") as executor:
        futures: dict[Future[FetchResult], tuple[int, str]] = {}
        while pending or futures:
            while len(futures) < global_concurrency:
                eligible_index = next(
                    (
                        index
                        for index, (_, (connector, policy)) in enumerate(pending)
                        if active_by_source.get(policy.key_for(connector.url), 0) < policy.max_concurrency
                    ),
                    None,
                )
                if eligible_index is None:
                    break
                connector_index, (connector, policy) = pending.pop(eligible_index)
                source_key = policy.key_for(connector.url)
                active_by_source[source_key] = active_by_source.get(source_key, 0) + 1
                future = executor.submit(_fetch_connector, connector, transport, cache, policy, limiter, current_clock)
                futures[future] = (connector_index, source_key)
            if not futures:
                raise RuntimeError("fetch scheduler found no eligible connector")
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                connector_index, source_key = futures.pop(future)
                active_by_source[source_key] -= 1
                results_by_index[connector_index] = future.result()

    results = [results_by_index[index] for index in range(len(connectors))]

    for connector, result in zip(connectors, results, strict=True):
        snapshot = snapshot_from_fetch(connector, result)
        # Pin every record's retrieval/observation time to the build's single timestamp so identical
        # inputs produce byte-identical output (and identical checksums), rather than a fresh
        # wall-clock reading per source.
        snapshot = snapshot.model_copy(update={"retrieved_at": generated_at})
        if result.outcome in ("ok", "not_modified") and result.body:
            # A connector parses raw source bytes it does not control. A live source can return HTTP
            # 200 with a body whose *shape* the parser doesn't expect (e.g. an endpoint that starts
            # returning a list instead of the documented object). That is a source failure, not a
            # reason to crash the whole build and drop every other source — so we downgrade this one
            # source's snapshot to a recorded parse error and emit no records for it, exactly as we
            # already do for a fetch error. Absence of parseable evidence is never a deletion (§5).
            try:
                parsed = connector.parse(result.body, observed_at=generated_at)
            except Exception as exc:  # noqa: BLE001 - isolate one bad source; record, don't crash
                snapshot = snapshot.model_copy(
                    update={
                        "fetch_outcome": FetchOutcome.ERROR,
                        "error": f"parse failed: {type(exc).__name__}: {exc}",
                    }
                )
            else:
                records.extend(parsed)
        # On error/stale (fetch or parse) nothing is *removed*: absence of a fresh, parseable response
        # is not evidence a model disappeared — the snapshot alone records the failure.
        snapshots.append(snapshot)
    # Advisory crosswalk is built from the evidence records' *source-native* ids (before appending
    # the snapshots, which carry no model identity).
    crosswalk = Crosswalk(generated_at=generated_at, entries=build_crosswalk(records))
    records.extend(snapshots)
    artifact = Artifact(generated_at=generated_at, records=records)
    return BuildResult(artifact=artifact, crosswalk=crosswalk, snapshots=snapshots)


def fixture_transport(fixtures_dir: Path, connectors: list[Connector]) -> FixtureTransport:
    return FixtureTransport(
        fixtures_dir=fixtures_dir,
        url_to_fixture={c.url: fixture_filename(c) for c in connectors},
    )


def fixture_filename(connector: Connector) -> str:
    """Return a connector's saved-response filename, defaulting to its historical JSON convention."""
    return str(getattr(connector, "fixture_filename", f"{connector.source_id}.json"))
