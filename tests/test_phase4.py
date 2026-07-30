"""Phase 4 (#170, ADR 0028): AA connector, credential gating, and live-build parse robustness."""

from __future__ import annotations

from pathlib import Path

import pytest

from registry.build import build, fixture_filename
from registry.connectors import credentialed_connectors, default_connectors
from registry.connectors.artificial_analysis import (
    API_KEY_ENV,
    ArtificialAnalysisConnector,
)
from registry.connectors.base import Connector
from registry.connectors.huggingface import HuggingFaceConnector
from registry.connectors.terminal_bench import TerminalBenchConnector
from registry.fetch import FetchCache, RawResponse, sha256_hex
from registry.schema import ClaimRecord, FetchOutcome, SourceSnapshotRecord, TrustLevel


def _body(fixtures_dir: Path, connector: Connector) -> bytes:
    return (fixtures_dir / fixture_filename(connector)).read_bytes()


# --- Artificial Analysis connector -------------------------------------------------------------


def test_aa_emits_only_claims_verbatim_ids(fixtures_dir: Path) -> None:
    records = ArtificialAnalysisConnector().parse(_body(fixtures_dir, ArtificialAnalysisConnector()))
    # Aggregated third-party numbers are *claims*, never evaluation_results (§2).
    claims = [r for r in records if isinstance(r, ClaimRecord)]
    assert claims and len(claims) == len(records)
    assert all(c.trust_level == TrustLevel.THIRD_PARTY_REPORT for c in claims)
    # Source-native slugs, verbatim — no canonicalization in the connector.
    assert {c.source_model_id for c in claims} == {"claude-opus-4", "gpt-5"}
    # A null score is preserved as absence, never a guessed value.
    assert not any(c.benchmark_name == "livecodebench" for c in claims)
    # Reported value kept as a string (index vs %) — never coerced.
    idx = next(
        c
        for c in claims
        if c.source_model_id == "gpt-5" and c.benchmark_name == "artificial_analysis_intelligence_index"
    )
    assert idx.value == "73"


def test_aa_parse_is_deterministic(fixtures_dir: Path) -> None:
    body = _body(fixtures_dir, ArtificialAnalysisConnector())
    first = [r.model_dump(mode="json") for r in ArtificialAnalysisConnector().parse(body)]
    second = [r.model_dump(mode="json") for r in ArtificialAnalysisConnector().parse(body)]
    assert first == second


def test_aa_rejects_unexpected_shape() -> None:
    with pytest.raises(ValueError, match="unexpected Artificial Analysis shape"):
        ArtificialAnalysisConnector().parse(b"[]")


def test_aa_auth_header_only_when_keyed() -> None:
    assert ArtificialAnalysisConnector(api_key=None).auth_headers() == {}
    assert ArtificialAnalysisConnector(api_key="secret").auth_headers() == {"x-api-key": "secret"}


# --- credential gating: AA stays out of the default public set ---------------------------------


def test_aa_not_in_default_connectors() -> None:
    assert not any(isinstance(c, ArtificialAnalysisConnector) for c in default_connectors())


def test_credentialed_connectors_gate_on_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(API_KEY_ENV, raising=False)
    assert credentialed_connectors() == []
    monkeypatch.setenv(API_KEY_ENV, "secret")
    gated = credentialed_connectors()
    assert len(gated) == 1 and isinstance(gated[0], ArtificialAnalysisConnector)


# --- HuggingFace shape guard -------------------------------------------------------------------


def test_huggingface_rejects_non_leaderboard_body() -> None:
    with pytest.raises(ValueError, match="unexpected HuggingFace leaderboard shape"):
        HuggingFaceConnector().parse(b'{"id": "some-dataset"}')


def test_terminal_bench_rejects_page_without_embedded_rows() -> None:
    with pytest.raises(ValueError, match="unexpected Terminal-Bench leaderboard shape"):
        TerminalBenchConnector().parse(b"<html>not a leaderboard</html>")


# --- build robustness: one source's parse failure degrades, never crashes ----------------------


class _GoodTransport:
    """Returns a fixed 200 body for any URL (each connector gets its own via url_to_source-free path)."""

    def __init__(self, body: bytes) -> None:
        self._body = body

    def request(self, url: str, headers: dict[str, str], *, timeout_seconds: float | None = None) -> RawResponse:
        return RawResponse(status=200, body=self._body, etag=f'"{sha256_hex(self._body)[:16]}"')


class _ExplodingConnector:
    source_id = "boom"
    url = "https://example.test/boom"
    license = "test"
    parser_version = "1"
    trust_level = TrustLevel.THIRD_PARTY_REPORT

    def parse(self, body: bytes, observed_at: str = "") -> list:
        raise RuntimeError("kaboom")


def test_build_records_parse_failure_as_error_snapshot_without_crashing() -> None:
    result = build([_ExplodingConnector()], _GoodTransport(b"{}"), cache=FetchCache(), now="2026-07-29T00:00:00+00:00")
    snaps = [r for r in result.artifact.records if isinstance(r, SourceSnapshotRecord)]
    assert len(snaps) == 1
    snap = snaps[0]
    # The bad source is recorded as an error, with the failure surfaced — not silently dropped.
    assert snap.fetch_outcome == FetchOutcome.ERROR
    assert snap.error is not None and "parse failed" in snap.error and "kaboom" in snap.error
    # No evidence records were emitted for it (and, crucially, the build did not crash).
    assert all(isinstance(r, SourceSnapshotRecord) for r in result.artifact.records)
