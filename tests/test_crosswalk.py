"""The advisory crosswalk proposes identity without mutating evidence, and never fabricates one."""

from pathlib import Path

from registry.build import build, fixture_transport
from registry.connectors import default_connectors
from registry.normalize import build_crosswalk, propose_canonical
from registry.schema import ProviderOfferingRecord, Record, TrustLevel


def _build(fixtures_dir: Path):
    connectors = default_connectors()
    return build(connectors, fixture_transport(fixtures_dir, connectors), now="2026-07-29T00:00:00+00:00")


def test_crosswalk_links_source_native_ids_via_reviewed_alias_only(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    entries = {(e.source_id, e.service_id, e.source_model_id): e for e in result.crosswalk.entries}

    # models.dev emits the source-native "claude-opus-4" (no access service); OpenRouter emits
    # "anthropic/claude-opus-4" under the openrouter service. Neither record id was rewritten, yet a
    # reviewed alias proposes the same canonical for both.
    md = entries[("models.dev", None, "claude-opus-4")]
    orr = entries[("openrouter", "openrouter", "anthropic/claude-opus-4")]
    assert md.canonical_model_id == "anthropic/claude-opus-4"
    assert orr.canonical_model_id == "anthropic/claude-opus-4"
    assert md.method == "reviewed_alias"
    assert md.developer_id == "anthropic"

    # A submission string with no reviewed alias is honestly unmapped — never fuzzy-merged.
    swe = entries[("swe-bench", None, "OpenHands (GPT-5)")]
    assert swe.method == "unmapped"
    assert swe.canonical_model_id is None
    assert swe.developer_id is None


def test_canonical_ids_are_never_derived_from_access_service() -> None:
    # The exact false proposals from issue #8 must never be generated from the serving path.
    for raw in ("gemma-4-31b", "zai-glm-4.7"):
        canonical, developer_id, method = propose_canonical(raw)
        assert canonical is None
        assert developer_id is None
        assert method == "unmapped"


def test_unreviewed_slashless_id_is_unmapped_not_service_prefixed(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    by_key = {(e.source_id, e.source_model_id): e for e in result.crosswalk.entries}
    # Cerebras' slashless, unreviewed ids never become "cerebras/<id>".
    for raw in ("gemma-4-31b", "zai-glm-4.7"):
        entry = by_key[("cerebras-models", raw)]
        assert entry.canonical_model_id is None
        assert entry.method == "unmapped"
        assert entry.service_id == "cerebras"


def test_reviewed_gpt_oss_gets_one_canonical_id_across_services(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    # Cerebras serves it as "gpt-oss-120b"; Groq serves it as "openai/gpt-oss-120b". One canonical.
    by_key = {(e.source_id, e.source_model_id): e for e in result.crosswalk.entries}
    cerebras = by_key[("cerebras-models", "gpt-oss-120b")]
    groq = by_key[("groq-model-docs", "openai/gpt-oss-120b")]
    assert cerebras.canonical_model_id == "openai/gpt-oss-120b"
    assert groq.canonical_model_id == "openai/gpt-oss-120b"
    assert cerebras.method == groq.method == "reviewed_alias"


def test_embedded_slash_stays_opaque() -> None:
    # A slash in an unreviewed source id is opaque data — its first segment is not a developer.
    canonical, developer_id, method = propose_canonical("zai-org/GLM-5.2")
    assert canonical is None
    assert developer_id is None
    assert method == "unmapped"


def test_crosswalk_is_independent_of_record_emission_order() -> None:
    def offering(service_id: str, model_id: str) -> ProviderOfferingRecord:
        return ProviderOfferingRecord(
            source_id="s",
            trust_level=TrustLevel.OFFICIAL_MODEL_CARD_CLAIM,
            source_model_id=model_id,
            service_id=service_id,
            observed_at="2026-07-29T00:00:00+00:00",
        )

    records: list[Record] = [offering("cerebras", "gpt-oss-120b"), offering("groq", "openai/gpt-oss-120b")]
    forward = build_crosswalk(records)
    reverse = build_crosswalk(list(reversed(records)))
    assert forward == reverse


def test_evidence_record_ids_stay_source_native(fixtures_dir: Path) -> None:
    result = _build(fixtures_dir)
    offering_ids = {
        r.model_dump()["source_model_id"] for r in result.artifact.records if r.record_type == "provider_offering"
    }
    # The raw models.dev key is present untouched (would be absent if we had canonicalized it).
    assert "claude-opus-4" in offering_ids
