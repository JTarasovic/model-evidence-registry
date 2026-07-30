"""Terminal-Bench 2.0 connector — agentic terminal-task benchmark (Apache-2.0).

The official versioned leaderboard page embeds its ranked rows in a Next.js payload. A row can name
multiple models, so only a single-model row uses the source-native ``modelNames`` identifier. A
multi-model row keeps its source-native submission ``key`` rather than inventing separate results.
"""

from __future__ import annotations

import json

from registry.schema import (
    ComparabilityStatus,
    EvaluationResultRecord,
    Record,
    TrustLevel,
)

BENCHMARK_VERSION = "2.0"
LEADERBOARD_URL = f"https://www.tbench.ai/leaderboard/terminal-bench/{BENCHMARK_VERSION}"


class TerminalBenchConnector:
    source_id = "terminal-bench"
    fixture_filename = "terminal-bench.html"
    url = LEADERBOARD_URL
    license = "Apache-2.0"
    parser_version = "2"
    trust_level = TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        # The official page's React Server Component payload serializes the rows as escaped JSON.
        # Decode its quote escapes, then let JSONDecoder stop precisely at the end of the array.
        page = body.decode("utf-8")
        decoded = page.replace(r'\"', '"')
        marker = '"rows":'
        start = decoded.find(marker)
        if start < 0:
            raise ValueError("unexpected Terminal-Bench leaderboard shape: missing embedded rows")
        try:
            rows, _ = json.JSONDecoder().raw_decode(decoded[start + len(marker) :])
        except json.JSONDecodeError as exc:
            raise ValueError("unexpected Terminal-Bench leaderboard shape: invalid embedded rows") from exc
        if not isinstance(rows, list) or not all(isinstance(entry, dict) for entry in rows):
            raise ValueError("unexpected Terminal-Bench leaderboard shape: expected an array of rows")

        records: list[Record] = []
        for entry in sorted(rows, key=lambda entry: str(entry.get("key", ""))):
            model_names = entry.get("modelNames")
            if isinstance(model_names, list) and len(model_names) == 1 and isinstance(model_names[0], str):
                model_id = model_names[0]
            else:
                # ``key`` is the published source-native identifier for one compound submission.
                # Do not split a multi-model submission into fabricated per-model observations.
                model_id = str(entry.get("key", ""))
            records.append(
                EvaluationResultRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    model_id=model_id,
                    benchmark_id="terminal-bench",
                    benchmark_version=BENCHMARK_VERSION,
                    metric="accuracy",
                    value=float(entry["accuracy"]),
                    unit="fraction",
                    agent=entry.get("agent"),
                    provenance_url=self.url,
                    comparability_status=ComparabilityStatus.NEEDS_REVIEW,
                )
            )
        return records
