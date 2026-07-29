"""Terminal-Bench connector — agentic terminal-task benchmark (Apache-2.0, active).

Chosen over LiveCodeBench for the PoC (LiveCodeBench is ~1yr stale — ADR 0028). Parses a leaderboard-
export shape: ``{version, results: [{agent, model, accuracy, split, date}]}``. ``version`` (e.g.
"2.1") is part of the result identity and is preserved. As with SWE-bench, submissions pair an agent
with a model, so comparability is ``needs_review``.
"""

from __future__ import annotations

import json

from registry.schema import (
    ComparabilityStatus,
    EvaluationResultRecord,
    Record,
    TrustLevel,
)

LEADERBOARD_URL = "https://www.tbench.ai/leaderboard"


class TerminalBenchConnector:
    source_id = "terminal-bench"
    url = LEADERBOARD_URL
    license = "Apache-2.0"
    parser_version = "1"
    trust_level = TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        version = data.get("version")
        records: list[Record] = []
        for entry in sorted(data.get("results", []), key=lambda e: (e.get("agent", ""), e.get("model", ""))):
            records.append(
                EvaluationResultRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    model_id=entry.get("model", ""),
                    benchmark_id="terminal-bench",
                    benchmark_version=version,
                    split=entry.get("split"),
                    metric="accuracy",
                    value=float(entry["accuracy"]),
                    unit="percent",
                    agent=entry.get("agent"),
                    provenance_url=self.url,
                    comparability_status=ComparabilityStatus.NEEDS_REVIEW,
                )
            )
        return records
