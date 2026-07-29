"""Serialize a build into the published artifact: JSON + Parquet + JSON Schema + manifest.

Determinism matters: JSON is written with ``sort_keys`` and a fixed separator, so identical inputs
produce byte-identical output (and therefore identical checksums). The manifest is written *last*,
after every other file's bytes are known, so its checksums describe exactly what landed on disk.
"""

from __future__ import annotations

import json
from pathlib import Path

import pyarrow as pa
import pyarrow.parquet as pq

from registry.build import BuildResult
from registry.manifest import build_manifest
from registry.schema import export_json_schema

RECORDS_JSON = "records.json"
RECORDS_PARQUET = "records.parquet"
SCHEMA_JSON = "records.schema.json"
MANIFEST_JSON = "manifest.json"


def _records_json_bytes(build: BuildResult) -> bytes:
    payload = build.artifact.model_dump(mode="json")
    text = json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False)
    return (text + "\n").encode("utf-8")


def _schema_json_bytes() -> bytes:
    text = json.dumps(export_json_schema(), indent=2, sort_keys=True)
    return (text + "\n").encode("utf-8")


def _parquet_bytes(build: BuildResult) -> bytes:
    """One analytical table: a few queryable columns + the full record JSON as ``payload_json``.

    Heterogeneous record types share no wide schema, so the full record is carried as a JSON string
    (queryable via DuckDB's ``json_extract``) rather than forcing a sparse union of every field.
    """
    rows = [r.model_dump(mode="json") for r in build.artifact.records]
    table = pa.table(
        {
            "record_type": [r["record_type"] for r in rows],
            "source_id": [r["source_id"] for r in rows],
            "trust_level": [r["trust_level"] for r in rows],
            "model_id": [r.get("model_id") or r.get("id") for r in rows],
            "payload_json": [json.dumps(r, sort_keys=True) for r in rows],
        }
    )
    sink = pa.BufferOutputStream()
    pq.write_table(table, sink)
    return sink.getvalue().to_pybytes()


def publish(build: BuildResult, out_dir: Path) -> dict:
    """Write all artifact files to ``out_dir`` and return the manifest dict."""
    out_dir.mkdir(parents=True, exist_ok=True)

    records_bytes = _records_json_bytes(build)
    schema_bytes = _schema_json_bytes()
    parquet_bytes = _parquet_bytes(build)

    artifact_files = {
        RECORDS_JSON: records_bytes,
        SCHEMA_JSON: schema_bytes,
        RECORDS_PARQUET: parquet_bytes,
    }
    for name, data in artifact_files.items():
        (out_dir / name).write_bytes(data)

    manifest = build_manifest(
        generated_at=build.artifact.generated_at,
        snapshots=build.snapshots,
        artifact_files=artifact_files,
    )
    manifest_bytes = (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8")
    (out_dir / MANIFEST_JSON).write_bytes(manifest_bytes)
    return manifest
