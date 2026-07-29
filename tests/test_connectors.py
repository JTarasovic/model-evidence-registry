"""Connector determinism + the data-model invariants ADR 0028 requires."""

from pathlib import Path

from registry.connectors import default_connectors
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.models_dev import ModelsDevConnector
from registry.connectors.swebench import SweBenchConnector
from registry.connectors.terminal_bench import TerminalBenchConnector
from registry.schema import (
    ClaimRecord,
    ComparabilityStatus,
    DocumentRecord,
    EvaluationResultRecord,
    ModelRecord,
    ProviderOfferingRecord,
)


def _body(fixtures_dir: Path, source_id: str) -> bytes:
    return (fixtures_dir / f"{source_id}.json").read_bytes()


def test_all_connectors_parse_deterministically(fixtures_dir: Path) -> None:
    for connector in default_connectors():
        body = _body(fixtures_dir, connector.source_id)
        first = [r.model_dump(mode="json") for r in connector.parse(body)]
        second = [r.model_dump(mode="json") for r in connector.parse(body)]
        assert first == second, f"{connector.source_id} parse is not deterministic"
        assert first, f"{connector.source_id} produced no records"


def test_models_dev_emits_model_and_offering(fixtures_dir: Path) -> None:
    records = ModelsDevConnector().parse(_body(fixtures_dir, "models.dev"))
    models = [r for r in records if isinstance(r, ModelRecord)]
    offerings = [r for r in records if isinstance(r, ProviderOfferingRecord)]
    assert {m.id for m in models} == {"anthropic/claude-opus-4", "openai/gpt-5"}
    opus = next(o for o in offerings if o.model_id == "anthropic/claude-opus-4")
    assert opus.context_window_tokens == 1000000
    assert opus.price is not None and opus.price.input_usd_per_mtok == 5.0


def test_swebench_keeps_splits_separate_and_uncrosswalked(fixtures_dir: Path) -> None:
    records = SweBenchConnector().parse(_body(fixtures_dir, "swe-bench"))
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
        for r in TerminalBenchConnector().parse(_body(fixtures_dir, "terminal-bench"))
        if isinstance(r, EvaluationResultRecord)
    ]
    assert evals and all(e.benchmark_version == "2.1" for e in evals)
    assert all(e.benchmark_id == "terminal-bench" for e in evals)


def test_huggingface_verified_flag_sets_comparability(fixtures_dir: Path) -> None:
    evals = [
        r
        for r in HuggingFaceConnector().parse(_body(fixtures_dir, "huggingface"))
        if isinstance(r, EvaluationResultRecord)
    ]
    by_model = {e.model_id: e for e in evals}
    assert by_model["qwen/qwen3-coder-480b"].comparability_status == ComparabilityStatus.COMPARABLE
    assert by_model["deepseek/deepseek-v3.1"].comparability_status == ComparabilityStatus.NEEDS_REVIEW
