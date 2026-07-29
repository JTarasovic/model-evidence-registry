"""Build orchestrator: fetch (conditional, cached) -> parse -> collect records + snapshots.

Keeps connectors pure ``bytes -> records`` parsers. Fetching, snapshot bookkeeping, and the
"a failed/stale source is recorded, not treated as a deletion" rule live here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

from registry.connectors.base import Connector, snapshot_from_fetch
from registry.fetch import (
    FetchCache,
    RawResponse,
    Transport,
    conditional_fetch,
    sha256_hex,
)
from registry.normalize import build_crosswalk
from registry.schema import Artifact, Crosswalk, Record


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
        result = conditional_fetch(connector.url, transport, cache)
        snapshot = snapshot_from_fetch(connector, result)
        # Pin every record's retrieval/observation time to the build's single timestamp so identical
        # inputs produce byte-identical output (and identical checksums), rather than a fresh
        # wall-clock reading per source.
        snapshot = snapshot.model_copy(update={"retrieved_at": generated_at})
        snapshots.append(snapshot)
        if result.outcome in ("ok", "not_modified") and result.body:
            records.extend(connector.parse(result.body, observed_at=generated_at))
        # On error/stale with no body, the snapshot alone records the failure — no records emitted,
        # and crucially nothing is *removed*: absence of a fresh response is not evidence of deletion.
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
