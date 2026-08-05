"""Artificial Analysis connector — third-party aggregated model intelligence/benchmark numbers.

Artificial Analysis (https://artificialanalysis.ai) publishes aggregated evaluation scores across
many models. These are **third-party reported** values, not independently reproduced result rows we
control the harness for, so every row is emitted as a ``claim`` (``THIRD_PARTY_REPORT`` trust) —
never an ``evaluation_result`` (design §2, §5). Model ids are kept **source-native/verbatim** (the AA
``slug``); crosswalking to a canonical id stays consumer-owned.

**Gating — read before enabling.** This is a *credentialed* source (``x-api-key``) whose terms
restrict redistribution. Per the Phase 4 plan (ADR 0028) it must **not** ship into the public nightly
artifact until a human completes the licensing/redistribution review. It is therefore deliberately
left **out of** ``default_connectors()``; enable it only via ``credentialed_connectors()`` once (a)
the review clears and (b) ``ARTIFICIAL_ANALYSIS_API_KEY`` is set. We store only *extracted facts*
(the reported score strings) and never the raw response bytes, matching the hash-and-facts-only
posture used for other restrictively-licensed sources.

**Review outcome (issue #3): deferred.** AA's free/Pro tiers are "internal use only; no
redistribution" — only a paid *commercial* license permits redistribution, and the registry's
artifact is public. So this connector stays dormant until a commercial license is acquired. See
https://github.com/JTarasovic/model-evidence-registry/issues/3 for the full finding.
"""

from __future__ import annotations

import json
import os

from registry.fetch import FetchPolicy
from registry.schema import ClaimRecord, Record, TrustLevel

API_URL = "https://artificialanalysis.ai/api/v2/data/llms/models"
API_KEY_ENV = "ARTIFICIAL_ANALYSIS_API_KEY"


class ArtificialAnalysisConnector:
    source_id = "artificial-analysis"
    url = API_URL
    license = "Proprietary (Artificial Analysis API terms) — redistribution restricted"
    parser_version = "1"
    #: Aggregated third-party numbers — the bottom of the trust ladder, and always a claim.
    trust_level = TrustLevel.THIRD_PARTY_REPORT
    fetch_policy = FetchPolicy(source_key="artificial-analysis", min_interval_seconds=0.5)

    def __init__(self, api_key: str | None = None) -> None:
        # Held only for the request header; never written into a record or snapshot.
        self._api_key = api_key or os.environ.get(API_KEY_ENV)

    def auth_headers(self) -> dict[str, str]:
        """Static request headers the fetch layer sends. Empty if no key is configured."""
        return {"x-api-key": self._api_key} if self._api_key else {}

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        data = json.loads(body)
        if not isinstance(data, dict):
            raise ValueError(f"unexpected Artificial Analysis shape: expected a JSON object, got {type(data).__name__}")
        models = data.get("data", [])
        records: list[Record] = []
        for model in sorted(models, key=lambda m: str(m.get("slug", m.get("id", "")))):
            # Source-native id, verbatim — no canonicalization here.
            model_id = str(model.get("slug") or model.get("id") or "")
            evaluations = model.get("evaluations") or {}
            if not isinstance(evaluations, dict):
                continue
            for benchmark_name, value in sorted(evaluations.items()):
                if value is None:
                    continue  # preserve "unknown" as absence, never a guessed 0
                records.append(
                    ClaimRecord(
                        source_id=self.source_id,
                        trust_level=self.trust_level,
                        source_model_id=model_id,
                        benchmark_name=benchmark_name,
                        # Kept as the reported string — AA's values are under-specified (index vs %),
                        # so we never coerce to a float or manufacture a unit.
                        value=str(value),
                        source_url=self.url,
                        source_date=data.get("as_of") or (observed_at or None),
                        note=(
                            "Third-party aggregated value from Artificial Analysis; "
                            "not an independently reproduced result."
                        ),
                    )
                )
        return records
