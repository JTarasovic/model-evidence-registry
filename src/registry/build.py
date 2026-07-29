"""Build orchestrator: fetch (conditional, cached) -> parse -> collect records + snapshots.

Keeps connectors pure ``bytes -> records`` parsers. Fetching, snapshot bookkeeping, and the
"a failed/stale source is recorded, not treated as a deletion" rule live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from registry.connectors.base import Connector, snapshot_from_fetch
from registry.fetch import (
    FetchCache,
    RawResponse,
    Transport,
    conditional_fetch,
    sha256_hex,
)
from registry.normalize import build_crosswalk
from registry.schema import Artifact, Crosswalk, FetchOutcome, Record


@dataclass
class FixtureTransport:
    """Replays saved fixtures by URL — the deterministic, no-network transport for builds/tests.

    ``fixtures_dir`` holds ``<source_id>.json`` files. ``url_to_source`` maps each connector URL to a
    source id. Optionally returns 304 for URLs whose validators already match (``not_modified``).
    """

    fixtures_dir: Path
    url_to_source: dict[str, str]
    return_304_for: set[str] = field(default_factory=set)

    def request(self, url: str, headers: dict[str, str]) -> RawResponse:
        if url in self.return_304_for and (
            "If-None-Match" in headers or "If-Modified-Since" in headers
        ):
            return RawResponse(status=304)
        source_id = self.url_to_source[url]
        body = (self.fixtures_dir / f"{source_id}.json").read_bytes()
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


def build(
    connectors: list[Connector],
    transport: Transport,
    *,
    cache: FetchCache | None = None,
    now: str | None = None,
) -> BuildResult:
    cache = cache or FetchCache()
    generated_at = now or datetime.now(UTC).isoformat()
    records: list[Record] = []
    snapshots = []
    for connector in connectors:
        # A connector may expose static per-source request headers (e.g. an auth key for a
        # credentialed source); pass them through to the fetch layer, which is the only place a
        # secret ever appears (never a record/snapshot).
        auth_fn = getattr(connector, "auth_headers", None)
        extra_headers = cast("dict[str, str] | None", auth_fn() if callable(auth_fn) else None)
        result = conditional_fetch(connector.url, transport, cache, extra_headers=extra_headers)
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
        url_to_source={c.url: c.source_id for c in connectors},
    )
