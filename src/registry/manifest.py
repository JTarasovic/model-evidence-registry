"""Manifest assembly: per-source snapshot summary + per-artifact-file SHA-256 checksums.

The manifest is the trust surface the ``af`` importer verifies: it re-hashes each artifact file and
compares against ``artifacts[name].sha256`` before trusting a byte of the payload.
"""

from __future__ import annotations

from registry.fetch import sha256_hex
from registry.schema import SCHEMA_VERSION, SourceSnapshotRecord


def source_entry(snapshot: SourceSnapshotRecord) -> dict:
    return {
        "source_id": snapshot.source_id,
        "url": snapshot.url,
        "license": snapshot.license,
        "trust_level": snapshot.trust_level.value,
        "fetch_outcome": snapshot.fetch_outcome.value,
        "etag": snapshot.etag,
        "last_modified": snapshot.last_modified,
        "content_sha256": snapshot.content_sha256,
        "parser_version": snapshot.parser_version,
        "error": snapshot.error,
        "retrieved_at": snapshot.retrieved_at,
    }


def build_manifest(
    *,
    generated_at: str,
    snapshots: list[SourceSnapshotRecord],
    artifact_files: dict[str, bytes],
) -> dict:
    """``artifact_files`` maps output filename -> its exact bytes (as they will be written)."""
    return {
        "schema_version": SCHEMA_VERSION,
        "generated_at": generated_at,
        "sources": [source_entry(s) for s in sorted(snapshots, key=lambda s: s.source_id)],
        "artifacts": {
            name: {"sha256": sha256_hex(data), "bytes": len(data)}
            for name, data in sorted(artifact_files.items())
        },
    }
