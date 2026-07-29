"""Serialize a build into the published artifact.

Two surfaces, on purpose (ADR 0028 §4):

- **JSON is the validated contract.** ``records.json`` (+ the exported ``records.schema.json``) is
  what the ``af`` importer checksum-verifies and validates against the published JSON Schema. It is
  sorted-key, byte-deterministic, and diffable — the property the reviewable-diff flow depends on.
  ``crosswalk.json`` is the advisory identity sidecar (see ``normalize``).
- **Parquet is the compact/analytical surface**, emitted as a **star schema — one file per record
  type** (``model.parquet``, ``provider_offering.parquet``, …) rather than a single blob column, so
  DuckDB can query typed columns directly with no extra artifact and no SQLite/native dependency.

The manifest is written last, after every other file's bytes are known, so its checksums describe
exactly what landed on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from registry.build import BuildResult
from registry.manifest import build_manifest
from registry.schema import RECORD_TYPES, export_json_schema

RECORDS_JSON = "records.json"
CROSSWALK_JSON = "crosswalk.json"
SCHEMA_JSON = "records.schema.json"
MANIFEST_JSON = "manifest.json"


def _json_bytes(payload: object) -> bytes:
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _parquet_bytes(rows: list[dict]) -> bytes:
    """One typed Parquet table for a single record type (uniform schema within a type)."""
    table = pa.Table.from_pylist(rows)
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def _per_type_parquet(build: BuildResult) -> dict[str, bytes]:
    """A ``<record_type>.parquet`` per non-empty record type — the star-schema analytical surface."""
    by_type: dict[str, list[dict]] = {t: [] for t in RECORD_TYPES}
    for record in build.artifact.records:
        by_type[record.record_type].append(record.model_dump(mode="json"))
    files: dict[str, bytes] = {}
    for record_type, rows in by_type.items():
        if rows:
            files[f"{record_type}.parquet"] = _parquet_bytes(rows)
    crosswalk_rows = [e.model_dump(mode="json") for e in build.crosswalk.entries]
    if crosswalk_rows:
        files["crosswalk.parquet"] = _parquet_bytes(crosswalk_rows)
    return files


def publish(build: BuildResult, out_dir: Path) -> dict:
    """Write all artifact files to ``out_dir`` and return the manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    artifact_files: dict[str, bytes] = {
        RECORDS_JSON: _json_bytes(build.artifact.model_dump(mode="json")),
        CROSSWALK_JSON: _json_bytes(build.crosswalk.model_dump(mode="json")),
        SCHEMA_JSON: _json_bytes(export_json_schema()),
        **_per_type_parquet(build),
    }
    for name, data in artifact_files.items():
        (out_dir / name).write_bytes(data)

    manifest = build_manifest(
        generated_at=build.artifact.generated_at,
        snapshots=build.snapshots,
        artifact_files=artifact_files,
    )
    (out_dir / MANIFEST_JSON).write_bytes(_json_bytes(manifest))
    return manifest
