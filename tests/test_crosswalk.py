"""The advisory crosswalk proposes identity without mutating evidence-record ids."""

from pathlib import Path

from registry.build import build, fixture_transport
from registry.connectors import default_connectors


def _build(fixtures_dir: Path):
    connectors = default_connectors()
    return build(connectors, fixture_transport(fixtures_dir, connectors), now="2026-07-29T00:00:00+00:00")


def test_crosswalk_links_source_native_ids_without_mutating_records(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    entries = {(e.source, e.raw_id): e for e in result.crosswalk.entries}

    # models.dev emits the source-native "claude-opus-4"; OpenRouter emits "anthropic/claude-opus-4".
    # Neither record id was rewritten, but the crosswalk *proposes* the same canonical for both.
    md = entries[("models.dev", "claude-opus-4")]
    orr = entries[("openrouter", "anthropic/claude-opus-4")]
    assert md.proposed_canonical_id == "anthropic/claude-opus-4"
    assert orr.proposed_canonical_id == "anthropic/claude-opus-4"
    assert md.method == "alias_table"

    # A submission string with no reviewed alias passes through verbatim — never fuzzy-merged.
    swe = entries[("swe-bench", "OpenHands (GPT-5)")]
    assert swe.method == "verbatim"
    assert swe.proposed_canonical_id == "openhands (gpt-5)"


def test_evidence_record_ids_stay_source_native(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    offering_ids = {
        r.model_dump()["model_id"]
        for r in result.artifact.records
        if r.record_type == "provider_offering"
    }
    # The raw models.dev key is present untouched (would be absent if we had canonicalized it).
    assert "claude-opus-4" in offering_ids
