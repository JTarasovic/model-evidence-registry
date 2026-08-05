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


def connector_urls(connector: Connector) -> tuple[str, ...]:
    """Return a connector's finite source URL set, preserving its declared order."""
    urls = getattr(connector, "urls", None)
    if urls is None:
        return (connector.url,)
    if not isinstance(urls, tuple) or not urls or not all(isinstance(url, str) and url for url in urls):
        raise TypeError(f"{connector.source_id}.urls must be a non-empty tuple of URLs")
    return urls


def _fetch_url(
    connector: Connector,
    url: str,
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
        url,
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
        request_gate=lambda deadline: limiter.acquire(policy, url, deadline),
        request_release=lambda: limiter.release(policy, url),
    )


def _run_jobs(
    jobs: Sequence[tuple[Connector, str, FetchPolicy]],
    transport: Transport,
    cache: FetchCache,
    limiter: SourceRateLimiter,
    clock: Clock,
    global_concurrency: int,
) -> list[FetchResult]:
    """Run one bounded, per-source-rate-limited wave of fetches, returning results in ``jobs`` order.

    A finite worker pool bounds all in-flight transport requests.  At most each source policy's
    request concurrency is submitted at once, so a rate-delayed provider cannot fill the pool and
    make unrelated hosts wait behind its sleeps.  Results are returned in job order, not completion
    order, so the artifact and manifest remain stable.  The shared ``limiter`` carries per-source
    spacing across successive waves (e.g. a crawl's seed and follow-up fetches).
    """
    pending = list(enumerate(jobs))
    results_by_index: dict[int, FetchResult] = {}
    active_by_source: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=global_concurrency, thread_name_prefix="registry-fetch") as executor:
        futures: dict[Future[FetchResult], tuple[int, str]] = {}
        while pending or futures:
            while len(futures) < global_concurrency:
                eligible_index = next(
                    (
                        index
                        for index, (_, (connector, url, policy)) in enumerate(pending)
                        if active_by_source.get(policy.key_for(url), 0) < policy.max_concurrency
                    ),
                    None,
                )
                if eligible_index is None:
                    break
                connector_index, (connector, url, policy) = pending.pop(eligible_index)
                source_key = policy.key_for(url)
                active_by_source[source_key] = active_by_source.get(source_key, 0) + 1
                future = executor.submit(_fetch_url, connector, url, transport, cache, policy, limiter, clock)
                futures[future] = (connector_index, source_key)
            if not futures:
                raise RuntimeError("fetch scheduler found no eligible connector")
            done, _ = wait(futures, return_when=FIRST_COMPLETED)
            for future in done:
                connector_index, source_key = futures.pop(future)
                active_by_source[source_key] -= 1
                results_by_index[connector_index] = future.result()
    return [results_by_index[index] for index in range(len(jobs))]


def _discover_jobs(
    seed_jobs: Sequence[tuple[Connector, str, FetchPolicy]],
    seed_results: Sequence[FetchResult],
) -> list[tuple[Connector, str, FetchPolicy]]:
    """Ask each crawl connector for follow-up URLs derived from its fetched seed body.

    A connector opts into crawling by exposing ``discover(url, body) -> tuple[str, ...]``.  This is a
    bounded, structural expansion (e.g. an index's own model rows -> per-model detail pages), not a
    link-following web crawl: each discovered URL inherits the seed's fetch policy, so it shares the
    provider's rate limit.  URLs already fetched (seeds or earlier discoveries) are skipped.
    """
    discovered: list[tuple[Connector, str, FetchPolicy]] = []
    seen = {url for _, url, _ in seed_jobs}
    for (connector, url, policy), result in zip(seed_jobs, seed_results, strict=True):
        discover = getattr(connector, "discover", None)
        if not callable(discover) or result.outcome not in ("ok", "not_modified") or not result.body:
            continue
        for follow_up in cast("tuple[str, ...]", discover(url, result.body)):
            if follow_up in seen:
                continue
            seen.add(follow_up)
            discovered.append((connector, follow_up, policy))
    return discovered


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
    # Fixtures never contact an upstream service, so source spacing would only make deterministic
    # tests and offline builds artificially slow. Concurrency limits still apply to exercise the
    # same bounded scheduler shape as a live build.
    if isinstance(transport, FixtureTransport):
        policies = [replace(policy, min_interval_seconds=0.0) for policy in policies]
    limiter = SourceRateLimiter(current_clock)

    # Wave 1: every connector's declared seed URL(s).  Wave 2: the follow-up detail URLs crawl
    # connectors discover from their seed bodies.  The shared limiter carries per-source spacing
    # across both waves so a crawl cannot outrun its provider's rate limit.
    seed_jobs = [
        (connector, url, policy)
        for connector, policy in zip(connectors, policies, strict=True)
        for url in connector_urls(connector)
    ]
    seed_results = _run_jobs(seed_jobs, transport, cache, limiter, current_clock, global_concurrency)
    detail_jobs = _discover_jobs(seed_jobs, seed_results)
    detail_results = _run_jobs(detail_jobs, transport, cache, limiter, current_clock, global_concurrency)

    all_jobs = [*seed_jobs, *detail_jobs]
    all_results = [*seed_results, *detail_results]

    # Group every fetched (url, result) under its connector, preserving order (seeds first, then the
    # connector's discovered detail pages).  Grouping lets a crawl connector's ``parse_all`` see all
    # of its bodies at once, while plain connectors keep the pure per-body ``parse`` path.
    fetched_by_connector: dict[int, tuple[Connector, list[tuple[str, FetchResult]]]] = {}
    for (connector, url, _policy), result in zip(all_jobs, all_results, strict=True):
        entry = fetched_by_connector.setdefault(id(connector), (connector, []))
        entry[1].append((url, result))

    for connector, fetched in fetched_by_connector.values():
        # Pin every record's retrieval/observation time to the build's single timestamp so identical
        # inputs produce byte-identical output (and identical checksums), rather than a fresh
        # wall-clock reading per source.
        connector_snapshots = [
            snapshot_from_fetch(connector, result).model_copy(update={"retrieved_at": generated_at})
            for _url, result in fetched
        ]
        # A connector parses raw source bytes it does not control. A live source can return HTTP 200
        # with a body whose *shape* the parser doesn't expect. That is a source failure, not a reason
        # to crash the whole build and drop every other source — so we downgrade the affected
        # snapshot(s) to a recorded parse error and emit no records, exactly as for a fetch error.
        # Absence of parseable evidence is never a deletion (§5).
        parse_all = getattr(connector, "parse_all", None)
        if callable(parse_all):
            bodies = {
                url: (result.body if result.outcome in ("ok", "not_modified") else None)
                for url, result in fetched
            }
            if any(body for body in bodies.values()):
                try:
                    parsed = cast("list[Record]", parse_all(bodies, observed_at=generated_at))
                    records.extend(parsed)
                except Exception as exc:  # noqa: BLE001 - isolate one bad source; record, don't crash
                    # A crawl fails as a unit: downgrade the successfully-fetched snapshots (a
                    # per-URL fetch error keeps its own, more specific outcome).
                    connector_snapshots = [
                        snapshot.model_copy(
                            update={
                                "fetch_outcome": FetchOutcome.ERROR,
                                "error": f"parse failed: {type(exc).__name__}: {exc}",
                            }
                        )
                        if snapshot.fetch_outcome in (FetchOutcome.OK, FetchOutcome.NOT_MODIFIED)
                        else snapshot
                        for snapshot in connector_snapshots
                    ]
        else:
            updated: list = []
            for (_url, result), snapshot in zip(fetched, connector_snapshots, strict=True):
                if result.outcome in ("ok", "not_modified") and result.body:
                    try:
                        records.extend(connector.parse(result.body, observed_at=generated_at))
                    except Exception as exc:  # noqa: BLE001 - isolate one bad source; record, don't crash
                        snapshot = snapshot.model_copy(
                            update={
                                "fetch_outcome": FetchOutcome.ERROR,
                                "error": f"parse failed: {type(exc).__name__}: {exc}",
                            }
                        )
                updated.append(snapshot)
            connector_snapshots = updated
        # On error/stale (fetch or parse) nothing is *removed*: absence of a fresh, parseable response
        # is not evidence a model disappeared — the snapshot alone records the failure.
        snapshots.extend(connector_snapshots)
    # Advisory crosswalk is built from the evidence records' *source-native* ids (before appending
    # the snapshots, which carry no model identity).
    crosswalk = Crosswalk(generated_at=generated_at, entries=build_crosswalk(records))
    records.extend(snapshots)
    artifact = Artifact(generated_at=generated_at, records=records)
    return BuildResult(artifact=artifact, crosswalk=crosswalk, snapshots=snapshots)


def fixture_transport(fixtures_dir: Path, connectors: list[Connector]) -> FixtureTransport:
    mapping: dict[str, str] = {}
    for connector in connectors:
        # A crawl connector fetches detail URLs its seed page reveals at runtime, so those URLs are
        # not in ``connector_urls``.  Its ``fixture_filenames`` map enumerates every URL — seed and
        # detail — the deterministic fixture build will fetch, so replay them all from it.
        fixture_filenames = getattr(connector, "fixture_filenames", None)
        if isinstance(fixture_filenames, dict):
            mapping.update(fixture_filenames)
        else:
            for url in connector_urls(connector):
                mapping[url] = fixture_filename(connector, url)
    return FixtureTransport(fixtures_dir=fixtures_dir, url_to_fixture=mapping)


def fixture_filename(connector: Connector, url: str | None = None) -> str:
    """Return a connector's saved-response filename, defaulting to its historical JSON convention."""
    fixture_filenames = getattr(connector, "fixture_filenames", None)
    if fixture_filenames is not None:
        if not isinstance(fixture_filenames, dict) or url is None or not isinstance(fixture_filenames.get(url), str):
            raise TypeError(f"{connector.source_id}.fixture_filenames must map every source URL to a filename")
        return fixture_filenames[url]
    return str(getattr(connector, "fixture_filename", f"{connector.source_id}.json"))
