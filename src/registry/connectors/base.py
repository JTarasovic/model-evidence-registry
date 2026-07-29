"""Connector protocol + shared helpers.

A connector owns one source. It declares its identity, URL, license, and redistribution policy, and
knows how to turn raw bytes into the normalized record types. The build orchestrator
(:mod:`registry.build`) handles fetching (conditional, cached) and snapshot bookkeeping so a
connector stays a pure ``bytes -> records`` parser — which is exactly what makes it deterministic
against a saved fixture.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from registry.fetch import FetchResult
from registry.schema import FetchOutcome, Record, SourceSnapshotRecord, TrustLevel


@runtime_checkable
class Connector(Protocol):
    source_id: str
    url: str
    license: str
    parser_version: str
    #: Trust level for the *snapshot* record; per-record trust is set inside ``parse``.
    trust_level: TrustLevel

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        """Deterministically turn raw source bytes into normalized records.

        ``observed_at`` is the build's single retrieval timestamp, injected so observation times are
        deterministic (identical inputs -> identical bytes -> identical checksums). Connectors must
        never call ``datetime.now()`` themselves.
        """
        ...


def snapshot_from_fetch(connector: Connector, result: FetchResult) -> SourceSnapshotRecord:
    """Build the ``source_snapshot`` record that records this source's fetch outcome."""
    return SourceSnapshotRecord(
        source_id=connector.source_id,
        trust_level=connector.trust_level,
        url=result.url,
        fetch_outcome=FetchOutcome(result.outcome),
        etag=result.etag,
        last_modified=result.last_modified,
        content_sha256=result.content_sha256,
        parser_version=connector.parser_version,
        license=connector.license,
        error=result.error,
        retrieved_at=result.retrieved_at,
    )
