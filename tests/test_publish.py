"""Publish: artifact validates against its own schema, manifest checksums match bytes, all six
record types present, and the build is byte-deterministic."""

import json
from pathlib import Path

from registry.build import build, fixture_transport
from registry.connectors import default_connectors
from registry.fetch import sha256_hex
from registry.publish import MANIFEST_JSON, RECORDS_JSON, publish
from registry.schema import ARTIFACT_ADAPTER


def _build(fixtures_dir: Path):
    connectors = default_connectors()
    transport = fixture_transport(fixtures_dir, connectors)
    return build(connectors, transport, now="2026-07-29T00:00:00+00:00")


def test_artifact_validates_against_schema(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    # Round-trips through the same adapter the published JSON Schema is exported from.
    payload = result.artifact.model_dump(mode="json")
    ARTIFACT_ADAPTER.validate_python(payload)


def test_all_six_record_types_present(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    kinds = {r.record_type for r in result.artifact.records}
    assert kinds == {
        "model",
        "provider_offering",
        "document",
        "evaluation_result",
        "claim",
        "source_snapshot",
    }


def test_manifest_checksums_match_written_bytes(fixtures_dir: Path, tmp_path: Path) -> None:
    result = _build(fixtures_dir)
    manifest = publish(result, tmp_path)
    for name, meta in manifest["artifacts"].items():
        written = (tmp_path / name).read_bytes()
        assert sha256_hex(written) == meta["sha256"], f"{name} checksum mismatch"
        assert len(written) == meta["bytes"]
    # records.json on disk parses and re-validates.
    payload = json.loads((tmp_path / RECORDS_JSON).read_bytes())
    ARTIFACT_ADAPTER.validate_python(payload)
    assert (tmp_path / MANIFEST_JSON).exists()


def test_build_is_byte_deterministic(fixtures_dir: Path, tmp_path: Path) -> None:
    a = publish(_build(fixtures_dir), tmp_path / "a")
    b = publish(_build(fixtures_dir), tmp_path / "b")
    assert a["artifacts"][RECORDS_JSON]["sha256"] == b["artifacts"][RECORDS_JSON]["sha256"]


def test_fixture_build_is_deterministic_without_callers_supplying_a_clock(fixtures_dir: Path) -> None:
    connectors = default_connectors()
    first = build(connectors, fixture_transport(fixtures_dir, connectors))
    second = build(connectors, fixture_transport(fixtures_dir, connectors))
    assert first.artifact.model_dump(mode="json") == second.artifact.model_dump(mode="json")
