"""Connector determinism + the data-model invariants ADR 0028 requires."""

from pathlib import Path

from registry.build import fixture_filename
from registry.connectors import default_connectors
from registry.connectors.anthropic_docs import AnthropicDocsConnector
from registry.connectors.base import Connector
from registry.connectors.cohere_docs import CohereDocsConnector
from registry.connectors.google_gemini_docs import GoogleGeminiDocsConnector
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.models_dev import ModelsDevConnector
from registry.connectors.openai_docs import OpenAIDocsConnector
from registry.connectors.swebench import SweBenchConnector
from registry.connectors.terminal_bench import TerminalBenchConnector
from registry.fetch import sha256_hex
from registry.schema import (
    ClaimRecord,
    ComparabilityStatus,
    DocumentRecord,
    EvaluationResultRecord,
    ModelRecord,
    ProviderOfferingRecord,
    TrustLevel,
)


def _body(fixtures_dir: Path, connector: Connector) -> bytes:
    return (fixtures_dir / fixture_filename(connector)).read_bytes()


def test_all_connectors_parse_deterministically(fixtures_dir: Path) -> None:
    for connector in default_connectors():
        body = _body(fixtures_dir, connector)
        first = [r.model_dump(mode="json") for r in connector.parse(body)]
        second = [r.model_dump(mode="json") for r in connector.parse(body)]
        assert first == second, f"{connector.source_id} parse is not deterministic"
        assert first, f"{connector.source_id} produced no records"


def test_models_dev_emits_model_and_offering(fixtures_dir: Path) -> None:
    records = ModelsDevConnector().parse(_body(fixtures_dir, ModelsDevConnector()))
    models = [r for r in records if isinstance(r, ModelRecord)]
    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    # Source-native ids, verbatim — no canonicalization mutation in the connector.
    assert {m.id for m in models} == {"claude-opus-4", "gpt-5"}
    opus = next(o for o in offerings if o.model_id == "claude-opus-4")
    assert opus.context_window_tokens == 1000000
    assert opus.price is not None and opus.price.input_usd_per_mtok == 5.0


def test_anthropic_docs_emits_hash_only_document_and_direct_api_offerings(fixtures_dir: Path) -> None:
    connector = AnthropicDocsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-29T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.revision == "fixture-revision-20260729"
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-29T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    assert {o.model_id for o in offerings} == {"claude-haiku-4-5", "claude-opus-4-6", "claude-sonnet-4-6"}
    assert all(o.provider == "Anthropic" for o in offerings)
    assert all(o.availability_state == "available" for o in offerings)


def test_openai_docs_emits_hash_only_document_and_direct_api_offerings(fixtures_dir: Path) -> None:
    connector = OpenAIDocsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-30T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.revision == "fixture-revision-20260730"
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-30T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    assert {o.model_id for o in offerings} == {"gpt-5.3-codex", "gpt-5.4", "gpt-5.4-mini"}
    assert all(o.provider == "OpenAI" for o in offerings)
    assert all(o.availability_state == "available" for o in offerings)


def test_google_gemini_docs_emits_hash_only_document_and_current_api_offerings(fixtures_dir: Path) -> None:
    connector = GoogleGeminiDocsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-30T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.revision == "2026-07-30 UTC"
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-30T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    assert {o.model_id for o in offerings} == {"gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"}
    assert all(o.provider == "Google" for o in offerings)
    assert all(o.availability_state == "available" for o in offerings)


def test_cohere_docs_emits_hash_only_document_and_source_native_offerings(fixtures_dir: Path) -> None:
    connector = CohereDocsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-30T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.revision is None
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-30T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    assert {o.model_id for o in offerings} == {
        "command-a-03-2025",
        "command-experimental",
        "command-r-08-2024",
        "embed-v4.0",
    }
    by_model = {offering.model_id: offering for offering in offerings}
    assert by_model["command-a-03-2025"].availability_state == "available"
    assert by_model["command-r-08-2024"].availability_state == "unavailable"
    assert by_model["command-experimental"].availability_state == "unknown"
    assert by_model["embed-v4.0"].availability_state == "available"
    assert all(o.provider == "Cohere" for o in offerings)


def test_swebench_keeps_splits_separate_and_uncrosswalked(fixtures_dir: Path) -> None:
    records = SweBenchConnector().parse(_body(fixtures_dir, SweBenchConnector()))
    evals = [r for r in records if isinstance(r, EvaluationResultRecord)]
    # Verified and Lite are distinct splits — never merged into one "SWE-bench" number.
    splits = {e.split for e in evals}
    assert splits == {"Verified", "Lite"}
    # The submission string is preserved verbatim, not fabricated into a canonical model id.
    assert any(e.model_id == "TRAE (Claude Opus 4)" for e in evals)
    assert all(e.comparability_status == ComparabilityStatus.NEEDS_REVIEW for e in evals)
    # A row without downloadable logs+trajectories is a claim, not an evaluation_result.
    claims = [r for r in records if isinstance(r, ClaimRecord)]
    assert any(c.model_id == "OpenHands (GPT-5)" for c in claims)
    # A NOASSERTION-licensed source is stored hash+facts-only, not re-hosted.
    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert docs and docs[0].redistribution_policy == "hash_and_facts_only"


def test_terminal_bench_preserves_version_identity(fixtures_dir: Path) -> None:
    evals = [
        r
        for r in TerminalBenchConnector().parse(_body(fixtures_dir, TerminalBenchConnector()))
        if isinstance(r, EvaluationResultRecord)
    ]
    assert evals and all(e.benchmark_version == "2.0" for e in evals)
    assert all(e.benchmark_id == "terminal-bench" for e in evals)
    assert all(e.unit == "fraction" for e in evals)
    assert any(e.model_id == "openai/gpt-oss-20b" for e in evals)
    # A submitted run with multiple models remains one compound source-native observation.
    multi_model = next(e for e in evals if e.agent == "LemonHarness")
    assert multi_model.model_id == "lemonharness__gemini 3.1 pro preview,gpt-5.3-codex"


def test_huggingface_parses_live_leaderboard_shape_without_merging_configs(fixtures_dir: Path) -> None:
    evals = [
        r
        for r in HuggingFaceConnector().parse(_body(fixtures_dir, HuggingFaceConnector()))
        if isinstance(r, EvaluationResultRecord)
    ]
    by_model = {e.model_id: e for e in evals}
    assert set(by_model) == {"moonshotai/Kimi-K3", "moonshotai/Kimi-K2.6", "zai-org/GLM-5.2"}
    assert all(e.benchmark_id == "cais/hle" for e in evals)
    assert by_model["moonshotai/Kimi-K2.6"].split == ".eval_results/hle_with_tools.yaml"
    assert by_model["moonshotai/Kimi-K3"].provenance_url == "https://huggingface.co/moonshotai/Kimi-K3"
    assert all(e.comparability_status == ComparabilityStatus.NEEDS_REVIEW for e in evals)
