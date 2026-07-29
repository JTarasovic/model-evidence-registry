"""Hugging Face leaderboard connector — eval results for open-weight models.

Strong for open-weight models, weak/absent for closed/API models (source-inventory.md) — so results
here are ``benchmark_maintainer_leaderboard`` trust and ``needs_review`` comparability by default.
Parses a leaderboard-export shape: ``{dataset, benchmark, split, results: [{model_id, value,
verified, source, harness}]}``.
"""

from __future__ import annotations

import json

from registry.normalize import canonical_model_id
from registry.schema import (
    ComparabilityStatus,
    EvaluationResultRecord,
    Record,
    TrustLevel,
)

API_URL = "https://huggingface.co/api/datasets/{dataset}/leaderboard"


class HuggingFaceConnector:
    source_id = "huggingface"
    url = "https://huggingface.co/api/datasets"
    license = "Per-dataset"
    parser_version = "1"
    trust_level = TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        benchmark_id = data.get("benchmark", data.get("dataset", "unknown"))
        split = data.get("split")
        records: list[Record] = []
        for entry in sorted(data.get("results", []), key=lambda e: e.get("model_id", "")):
            verified = entry.get("verified")
            records.append(
                EvaluationResultRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    model_id=canonical_model_id(entry.get("model_id", "")),
                    benchmark_id=benchmark_id,
                    benchmark_version=data.get("version"),
                    split=split,
                    metric=data.get("metric", "score"),
                    value=float(entry["value"]),
                    unit=data.get("unit"),
                    harness=entry.get("harness"),
                    provenance_url=entry.get("source"),
                    comparability_status=(
                        ComparabilityStatus.COMPARABLE
                        if verified
                        else ComparabilityStatus.NEEDS_REVIEW
                    ),
                )
            )
        return records
