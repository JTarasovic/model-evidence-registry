"""SWE-bench leaderboard connector — official resolved-% per submission.

Parses ``data/leaderboards.json``: ``{leaderboards: [{name, results: [{name, folder, resolved, date,
logs, trajs}]}]}``. Each top-level ``name`` is a *distinct* benchmark split (Test / Lite / Verified /
Multimodal / Multilingual) — kept separate, never merged. Each ``results[].name`` is a submission
(agent+model) string that has **not** been crosswalked to a canonical model, so results are
``needs_review`` comparability and carry the raw submission name.

Licensing: the SWE-bench site repo is **NOASSERTION** — we emit a ``document`` record with
``redistribution_policy="hash_and_facts_only"`` and store extracted facts + a content hash, never
re-hosting the raw asset.
"""

from __future__ import annotations

import json

from registry.fetch import sha256_hex
from registry.schema import (
    ClaimRecord,
    ComparabilityStatus,
    DocumentRecord,
    EvaluationResultRecord,
    Record,
    TrustLevel,
)

LEADERBOARD_URL = "https://raw.githubusercontent.com/SWE-bench/swe-bench.github.io/main/data/leaderboards.json"


class SweBenchConnector:
    source_id = "swe-bench"
    url = LEADERBOARD_URL
    license = "NOASSERTION"
    parser_version = "1"
    trust_level = TrustLevel.BENCHMARK_MAINTAINER_LEADERBOARD

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        records: list[Record] = []
        # One document record: hash + facts only (NOASSERTION license), not re-hosted bytes.
        records.append(
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="leaderboard_asset",
                content_sha256=sha256_hex(body),
                retrieved_at=data.get("_retrieved_at") or observed_at,
                redistribution_policy="hash_and_facts_only",
            )
        )
        for board in data.get("leaderboards", []):
            split = board.get("name", "")  # e.g. "Verified" — part of the result identity.
            for result in sorted(board.get("results", []), key=lambda r: r.get("name", "")):
                resolved = result.get("resolved")
                if resolved is None:
                    continue
                submission = result.get("name", "")
                # A row is only an *evaluation_result* if the maintainer has downloadable logs AND
                # trajectories backing it. Otherwise it is a self-/independently-reported number — a
                # `claim`, never presented as an independently reproduced leaderboard result (§2).
                verifiable = bool(result.get("logs")) and bool(result.get("trajs"))
                if verifiable:
                    records.append(
                        EvaluationResultRecord(
                            source_id=self.source_id,
                            trust_level=self.trust_level,
                            # Uncrosswalked submission string — a model/agent identity mapper is
                            # future work; we must not fabricate a canonical model id here.
                            model_id=submission,
                            benchmark_id="swe-bench",
                            benchmark_version=None,
                            split=split,
                            metric="resolved",
                            value=float(resolved),
                            unit="percent",
                            agent=submission,
                            provenance_url=self.url,
                            comparability_status=ComparabilityStatus.NEEDS_REVIEW,
                        )
                    )
                else:
                    records.append(
                        ClaimRecord(
                            source_id=self.source_id,
                            trust_level=TrustLevel.THIRD_PARTY_REPORT,
                            model_id=submission,
                            benchmark_name=f"SWE-bench {split}".strip(),
                            value=f"{resolved}%",
                            unit="percent",
                            source_url=self.url,
                            note="Leaderboard row without downloadable logs+trajectories; treated as a claim.",
                        )
                    )
        return records
