"""The registry data model: six *separate* record types + JSON-Schema export.

Governed by ADR 0028 and docs/designs/model-evidence-registry.md (§2) in the Agent Foundry repo.
Hard rules encoded here:

- Six record types stay **separate** — never collapsed into one "model row".
- Every record carries a ``trust_level`` from the ladder and preserves ``unknown`` explicitly
  (fields are omitted / ``None``, never guessed to ``False``).
- No manufactured equivalence between ``SWE-bench`` / ``SWE-bench Verified`` / ``SWE-bench Pro`` or
  across differing agent/reasoning settings: each is a distinct ``evaluation_result`` / ``claim``
  carrying benchmark id/version/split/metric + harness/agent/comparability metadata.
"""

from __future__ import annotations

import json
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

SCHEMA_VERSION = "0.1.0"

RECORD_TYPES = (
    "model",
    "provider_offering",
    "document",
    "evaluation_result",
    "claim",
    "source_snapshot",
)


class TrustLevel(StrEnum):
    """The source trust ladder (design §5), highest to lowest."""

    OFFICIAL_STRUCTURED_RESULT = "official_structured_result"
    OFFICIAL_MODEL_CARD_CLAIM = "official_model_card_claim"
    BENCHMARK_MAINTAINER_LEADERBOARD = "benchmark_maintainer_leaderboard"
    INDEPENDENTLY_REPRODUCIBLE_RUN = "independently_reproducible_run"
    THIRD_PARTY_REPORT = "third_party_report"


class ComparabilityStatus(StrEnum):
    """Whether an evaluation_result can be compared against others of the same benchmark."""

    COMPARABLE = "comparable"
    NEEDS_REVIEW = "needs_review"
    NOT_COMPARABLE = "not_comparable"
    UNKNOWN = "unknown"


class FetchOutcome(StrEnum):
    OK = "ok"
    NOT_MODIFIED = "not_modified"
    ERROR = "error"
    STALE = "stale"


class _Record(BaseModel):
    # ``extra="forbid"`` keeps a connector from silently smuggling an un-modelled field into the
    # artifact; ``None`` is how we preserve "unknown" (see module docstring).
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(description="ID of the source connector that produced this record.")
    trust_level: TrustLevel


class ModelRecord(_Record):
    record_type: Literal["model"] = "model"
    id: str = Field(description="Canonical model id, e.g. 'anthropic/claude-opus-4'.")
    publisher: str | None = None
    developer: str | None = None
    family: str | None = None
    release_date: str | None = None
    version: str | None = None
    aliases: list[str] = Field(default_factory=list)


class PriceObservation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    input_usd_per_mtok: float | None = None
    output_usd_per_mtok: float | None = None
    observed_at: str


class ProviderOfferingRecord(_Record):
    record_type: Literal["provider_offering"] = "provider_offering"
    model_id: str
    provider: str
    availability_state: Literal["available", "unavailable", "unknown"] = "unknown"
    modalities: list[str] = Field(default_factory=list)
    context_window_tokens: int | None = None
    max_output_tokens: int | None = None
    price: PriceObservation | None = None
    observed_at: str


class DocumentRecord(_Record):
    record_type: Literal["document"] = "document"
    url: str
    kind: str = Field(description="model_card | release_note | api_doc | benchmark_paper | leaderboard_asset")
    revision: str | None = None
    etag: str | None = None
    content_sha256: str | None = None
    retrieved_at: str
    redistribution_policy: str = Field(
        description="hash_and_facts_only | raw_permitted | link_only — how the raw bytes may be reused."
    )


class EvaluationResultRecord(_Record):
    record_type: Literal["evaluation_result"] = "evaluation_result"
    model_id: str
    benchmark_id: str
    benchmark_version: str | None = None
    split: str | None = None
    metric: str
    value: float
    unit: str | None = None
    direction: Literal["higher_is_better", "lower_is_better"] = "higher_is_better"
    harness: str | None = None
    agent: str | None = None
    reasoning: str | None = None
    pass_at_k: int | None = None
    sample_count: int | None = None
    provenance_url: str | None = None
    comparability_status: ComparabilityStatus = ComparabilityStatus.UNKNOWN


class ClaimRecord(_Record):
    """A vendor- or third-party-reported value not tied to a canonical result row."""

    record_type: Literal["claim"] = "claim"
    model_id: str
    benchmark_name: str
    value: str = Field(description="Kept as the reported string (e.g. '80.3%') — under-specified.")
    unit: str | None = None
    source_url: str | None = None
    source_date: str | None = None
    note: str | None = None


class SourceSnapshotRecord(_Record):
    record_type: Literal["source_snapshot"] = "source_snapshot"
    url: str
    fetch_outcome: FetchOutcome
    etag: str | None = None
    last_modified: str | None = None
    content_sha256: str | None = None
    parser_version: str
    license: str | None = None
    error: str | None = None
    retrieved_at: str


Record = Annotated[
    ModelRecord | ProviderOfferingRecord | DocumentRecord | EvaluationResultRecord | ClaimRecord | SourceSnapshotRecord,
    Field(discriminator="record_type"),
]


class Artifact(BaseModel):
    """The published artifact envelope written to ``records.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: str
    records: list[Record]


class CrosswalkEntry(BaseModel):
    """One advisory identity mapping: a *source-native* id and a **proposed** canonical id.

    The registry never mutates the ids on the evidence records — every record keeps the identifier
    exactly as its source emitted it. This crosswalk is a *separate, advisory* sidecar: it suggests
    which source-native ids are likely the same model, so a consumer can adopt, override, or ignore
    it. Deciding the final mapping to a curated inventory stays consumer-owned (ADR 0028 authority
    invariant) — the registry proposes, it does not decide.
    """

    model_config = ConfigDict(extra="forbid")

    source: str = Field(description="Connector that observed this id (e.g. 'models.dev').")
    raw_id: str = Field(description="The source-native identifier, verbatim.")
    provider: str | None = None
    proposed_canonical_id: str = Field(description="Advisory canonical id — a suggestion, not authority.")
    method: Literal["alias_table", "verbatim"] = Field(
        description="alias_table = an explicit reviewed alias merged it; verbatim = no merge, id normalized only."
    )


class Crosswalk(BaseModel):
    """The advisory crosswalk sidecar written to ``crosswalk.json``."""

    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    generated_at: str
    entries: list[CrosswalkEntry]


ARTIFACT_ADAPTER: TypeAdapter[Artifact] = TypeAdapter(Artifact)
CROSSWALK_ADAPTER: TypeAdapter[Crosswalk] = TypeAdapter(Crosswalk)


def export_json_schema() -> dict:
    """The published JSON Schema the ``af`` importer validates the artifact against."""
    return ARTIFACT_ADAPTER.json_schema()


def write_json_schema(path: str) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(export_json_schema(), fh, indent=2, sort_keys=True)
        fh.write("\n")
