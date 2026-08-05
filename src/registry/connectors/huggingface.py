"""Hugging Face's public HLE leaderboard connector.

The documented ``/leaderboard`` endpoint returns ranked rows for one benchmark dataset.  Its
``filename`` is the source-native evaluation configuration, so it is kept as the record split rather
than treating results from different configurations (for example, with-tools) as interchangeable.
"""

from __future__ import annotations

import json

from registry.fetch import FetchPolicy
from registry.schema import (
    ComparabilityStatus,
    EvaluationResultRecord,
    Record,
    TrustLevel,
)

DATASET_ID = "cais/hle"
API_URL = f"https://huggingface.co/api/datasets/{DATASET_ID}/leaderboard"


class HuggingFaceConnector:
    source_id = "huggingface"
    url = API_URL
    license = "Per-dataset"
    parser_version = "1"
    trust_level = TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD
    fetch_policy = FetchPolicy()

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        if not isinstance(data, list) or not all(isinstance(entry, dict) for entry in data):
            raise ValueError("unexpected HuggingFace leaderboard shape: expected a JSON array of leaderboard rows")
        records: list[Record] = []
        for entry in sorted(data, key=lambda entry: (str(entry.get("modelId", "")), str(entry.get("filename", "")))):
            verified = entry.get("verified")
            source = entry.get("source")
            provenance_url = source.get("url") if isinstance(source, dict) else None
            records.append(
                EvaluationResultRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=entry.get("modelId", ""),
                    benchmark_id=DATASET_ID,
                    # The endpoint has no benchmark version field. Its filename identifies the
                    # submitted evaluation configuration and must remain distinct from other rows.
                    split=entry.get("filename"),
                    metric="score",
                    value=float(entry["value"]),
                    direction=("lower_is_better" if entry.get("lower_is_better") else "higher_is_better"),
                    provenance_url=provenance_url,
                    comparability_status=(
                        ComparabilityStatus.COMPARABLE if verified else ComparabilityStatus.NEEDS_REVIEW
                    ),
                )
            )
        return records
