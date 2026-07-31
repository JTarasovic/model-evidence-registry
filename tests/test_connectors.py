"""Connector determinism + the data-model invariants ADR 0028 requires."""

from pathlib import Path

from registry.build import build, connector_urls, fixture_filename, fixture_transport
from registry.connectors import default_connectors
from registry.connectors.anthropic_docs import AnthropicDocsConnector
from registry.connectors.base import Connector
from registry.connectors.cerebras_models import CerebrasModelsConnector
from registry.connectors.cohere_docs import CohereDocsConnector
from registry.connectors.github_models import GitHubModelsConnector
from registry.connectors.google_gemini_docs import GoogleGeminiDocsConnector
from registry.connectors.groq_docs import GroqDocsConnector
from registry.connectors.hf_model_cards import HfModelCardsConnector
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.mistral_docs import MistralDocsConnector
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
    SourceSnapshotRecord,
    TrustLevel,
)


def _body(fixtures_dir: Path, connector: Connector, url: str | None = None) -> bytes:
    return (fixtures_dir / fixture_filename(connector, url)).read_bytes()


def test_all_connectors_parse_deterministically(fixtures_dir: Path) -> None:
    for connector in default_connectors():
        for url in connector_urls(connector):
            body = _body(fixtures_dir, connector, url)
            first = [r.model_dump(mode="json") for r in connector.parse(body)]
            second = [r.model_dump(mode="json") for r in connector.parse(body)]
            assert first == second, f"{connector.source_id} ({url}) parse is not deterministic"
            assert first, f"{connector.source_id} ({url}) produced no records"


def test_models_dev_emits_model_and_offering(fixtures_dir: Path) -> None:
    records = ModelsDevConnector().parse(_body(fixtures_dir, ModelsDevConnector()))
    models = [r for r in records if isinstance(r, ModelRecord)]
    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    # Source-native ids, verbatim — no canonicalization mutation in the connector.
    assert {m.source_model_id for m in models} == {"claude-opus-4", "gpt-5"}
    opus = next(o for o in offerings if o.source_model_id == "claude-opus-4")
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
    assert {o.source_model_id for o in offerings} == {"claude-haiku-4-5", "claude-opus-4-6", "claude-sonnet-4-6"}
    assert all(o.source_provider_label == "Anthropic" for o in offerings)
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
    assert {o.source_model_id for o in offerings} == {"gpt-5.3-codex", "gpt-5.4", "gpt-5.4-mini"}
    assert all(o.source_provider_label == "OpenAI" for o in offerings)
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
    assert {o.source_model_id for o in offerings} == {"gemini-2.5-flash", "gemini-2.5-flash-lite", "gemini-2.5-pro"}
    assert all(o.source_provider_label == "Google" for o in offerings)
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
    assert {o.source_model_id for o in offerings} == {
        "command-a-03-2025",
        "command-experimental",
        "command-r-08-2024",
        "embed-v4.0",
    }
    by_model = {offering.source_model_id: offering for offering in offerings}
    assert by_model["command-a-03-2025"].availability_state == "available"
    assert by_model["command-r-08-2024"].availability_state == "unavailable"
    assert by_model["command-experimental"].availability_state == "unknown"
    assert by_model["embed-v4.0"].availability_state == "available"
    assert all(o.source_provider_label == "Cohere" for o in offerings)


def test_groq_docs_emits_hash_only_document_and_lifecycle_offerings(fixtures_dir: Path) -> None:
    connector = GroqDocsConnector()
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
    by_model = {offering.source_model_id: offering for offering in offerings}
    assert set(by_model) == {
        "groq/compound-mini",
        "llama-3.3-70b-versatile",
        "openai/gpt-oss-120b",
        "retired-model-v1",
    }
    assert by_model["llama-3.3-70b-versatile"].availability_state == "available"
    assert by_model["groq/compound-mini"].availability_state == "available"
    assert by_model["openai/gpt-oss-120b"].availability_state == "available"
    assert by_model["retired-model-v1"].availability_state == "unavailable"
    assert all(o.source_provider_label == "Groq" for o in offerings)


def test_mistral_docs_emits_hash_only_document_and_lifecycle_offerings(fixtures_dir: Path) -> None:
    connector = MistralDocsConnector()
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
    by_model = {offering.source_model_id: offering for offering in offerings}
    assert set(by_model) == {
        "codestral-2405",
        "mistral-large-2407",
        "mistral-large-2512",
        "mistral-medium-3-5",
    }
    assert by_model["mistral-large-2512"].availability_state == "available"
    assert by_model["mistral-medium-3-5"].availability_state == "available"
    assert by_model["mistral-large-2407"].availability_state == "unavailable"
    assert by_model["codestral-2405"].availability_state == "unavailable"
    assert all(o.source_provider_label == "Mistral AI" for o in offerings)


def test_github_models_emits_hash_only_document_and_catalog_offerings(fixtures_dir: Path) -> None:
    connector = GitHubModelsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-30T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-30T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    by_model = {offering.source_model_id: offering for offering in offerings}
    assert set(by_model) == {"deepseek/deepseek-r1", "meta/llama-3.3-70b-instruct", "openai/gpt-4.1"}
    assert by_model["openai/gpt-4.1"].modalities == ["text", "image"]
    assert by_model["openai/gpt-4.1"].context_window_tokens == 1048576
    assert by_model["openai/gpt-4.1"].max_output_tokens == 32768
    assert all(o.source_provider_label == "GitHub Models" for o in offerings)


def test_cerebras_models_emits_hash_only_document_and_catalog_offerings(fixtures_dir: Path) -> None:
    connector = CerebrasModelsConnector()
    body = _body(fixtures_dir, connector)
    records = connector.parse(body, observed_at="2026-07-30T00:00:00+00:00")

    docs = [r for r in records if isinstance(r, DocumentRecord)]
    assert len(docs) == 1
    document = docs[0]
    assert document.url == connector.url
    assert document.content_sha256 == sha256_hex(body)
    assert document.retrieved_at == "2026-07-30T00:00:00+00:00"
    assert document.redistribution_policy == "hash_and_facts_only"
    assert document.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM

    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    by_model = {offering.source_model_id: offering for offering in offerings}
    assert set(by_model) == {"gemma-4-31b", "gpt-oss-120b", "zai-glm-4.7"}
    assert by_model["gemma-4-31b"].modalities == ["text+vision"]
    assert by_model["gpt-oss-120b"].context_window_tokens == 131072
    assert by_model["gpt-oss-120b"].max_output_tokens == 40960
    assert by_model["gpt-oss-120b"].price is not None
    assert by_model["gpt-oss-120b"].price.input_usd_per_mtok == 0.35
    assert by_model["gpt-oss-120b"].price.output_usd_per_mtok == 0.75
    assert all(o.source_provider_label == "Cerebras" for o in offerings)


def test_hf_model_cards_emit_revision_pinned_documents_without_inference_offerings(fixtures_dir: Path) -> None:
    connector = HfModelCardsConnector()
    records = [
        record
        for url in connector.urls
        for record in connector.parse(_body(fixtures_dir, connector, url), observed_at="2026-07-30T00:00:00+00:00")
    ]

    docs = [record for record in records if isinstance(record, DocumentRecord)]
    assert len(docs) == len(connector.urls)
    assert {document.url for document in docs} == set(connector.urls)
    assert all(document.kind == "model_card" for document in docs)
    assert all(document.redistribution_policy == "hash_and_facts_only" for document in docs)
    assert all(document.retrieved_at == "2026-07-30T00:00:00+00:00" for document in docs)
    by_url = {document.url: document for document in docs}
    assert by_url["https://huggingface.co/api/models/Qwen/Qwen3.6-27B"].revision == (
        "6a9e13bd6fc8f0983b9b99948120bc37f49c13e9"
    )
    # The organization slash remains part of the opaque source-native repository identifier in the URL.
    assert "https://huggingface.co/api/models/Qwen/Qwen3.6-27B" in by_url
    assert not any(isinstance(record, ProviderOfferingRecord) for record in records)


def test_hf_model_card_disabled_metadata_never_implies_inference_availability() -> None:
    connector = HfModelCardsConnector()
    for disabled in (False, True):
        records = connector.parse(
            f'{{"id":"organization/model", "disabled":{str(disabled).lower()}}}'.encode(),
            observed_at="2026-07-30T00:00:00+00:00",
        )
        assert len(records) == 1
        assert isinstance(records[0], DocumentRecord)
        assert records[0].url == "https://huggingface.co/api/models/organization/model"
        assert not any(isinstance(record, ProviderOfferingRecord) for record in records)


def test_hf_model_cards_fixture_build_keeps_one_snapshot_per_card(fixtures_dir: Path) -> None:
    connector = HfModelCardsConnector()
    result = build(
        [connector],
        fixture_transport(fixtures_dir, [connector]),
        now="2026-07-30T00:00:00+00:00",
    )
    snapshots = [record for record in result.artifact.records if isinstance(record, SourceSnapshotRecord)]
    documents = [record for record in result.artifact.records if isinstance(record, DocumentRecord)]
    assert [snapshot.url for snapshot in snapshots] == list(connector.urls)
    assert len(documents) == len(connector.urls)


def test_swebench_keeps_splits_separate_and_uncrosswalked(fixtures_dir: Path) -> None:
    records = SweBenchConnector().parse(_body(fixtures_dir, SweBenchConnector()))
    evals = [r for r in records if isinstance(r, EvaluationResultRecord)]
    # Verified and Lite are distinct splits — never merged into one "SWE-bench" number.
    splits = {e.split for e in evals}
    assert splits == {"Verified", "Lite"}
    # The submission string is preserved verbatim, not fabricated into a canonical model id.
    assert any(e.source_model_id == "TRAE (Claude Opus 4)" for e in evals)
    assert all(e.comparability_status == ComparabilityStatus.NEEDS_REVIEW for e in evals)
    # A row without downloadable logs+trajectories is a claim, not an evaluation_result.
    claims = [r for r in records if isinstance(r, ClaimRecord)]
    assert any(c.source_model_id == "OpenHands (GPT-5)" for c in claims)
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
    assert any(e.source_model_id == "openai/gpt-oss-20b" for e in evals)
    # A submitted run with multiple models remains one compound source-native observation.
    multi_model = next(e for e in evals if e.agent == "LemonHarness")
    assert multi_model.source_model_id == "lemonharness__gemini 3.1 pro preview,gpt-5.3-codex"


def test_huggingface_parses_live_leaderboard_shape_without_merging_configs(fixtures_dir: Path) -> None:
    evals = [
        r
        for r in HuggingFaceConnector().parse(_body(fixtures_dir, HuggingFaceConnector()))
        if isinstance(r, EvaluationResultRecord)
    ]
    by_model = {e.source_model_id: e for e in evals}
    assert set(by_model) == {"moonshotai/Kimi-K3", "moonshotai/Kimi-K2.6", "zai-org/GLM-5.2"}
    assert all(e.benchmark_id == "cais/hle" for e in evals)
    assert by_model["moonshotai/Kimi-K2.6"].split == ".eval_results/hle_with_tools.yaml"
    assert by_model["moonshotai/Kimi-K3"].provenance_url == "https://huggingface.co/moonshotai/Kimi-K3"
    assert all(e.comparability_status == ComparabilityStatus.NEEDS_REVIEW for e in evals)


def test_huggingface_connectors_remain_distinct_registered_evidence_sources(fixtures_dir: Path) -> None:
    connectors = default_connectors()
    assert {connector.source_id for connector in connectors} >= {"hf-model-cards", "huggingface"}

    card_connector = HfModelCardsConnector()
    card_records = card_connector.parse(_body(fixtures_dir, card_connector, card_connector.url))
    leaderboard_records = HuggingFaceConnector().parse(_body(fixtures_dir, HuggingFaceConnector()))
    assert all(isinstance(record, DocumentRecord) for record in card_records)
    assert all(record.trust_level == TrustLevel.OFFICIAL_MODEL_CARD_CLAIM for record in card_records)
    assert all(isinstance(record, EvaluationResultRecord) for record in leaderboard_records)
    assert all(record.trust_level == TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD for record in leaderboard_records)
