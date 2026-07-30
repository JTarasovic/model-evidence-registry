"""Cohere's official Models documentation connector.

The public Models page supplies a clean Markdown representation at ``/docs/models.md``.  It is
used instead of ``GET /v1/models``, which requires an API key.  Only the page hash and the
source-native model identifiers and statuses are emitted; the documentation itself is not
re-hosted.  The saved fixture is a purpose-built, facts-only subset of its model tables.
"""

from __future__ import annotations

import re
from typing import Literal

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_INDEX_URL = "https://docs.cohere.com/docs/models.md"
_CODE_CELL_RE = re.compile(r"^`([^`]+)`$")
AvailabilityState = Literal["available", "unavailable", "unknown"]


def _table_cells(line: str) -> list[str]:
    """Return the cells from one Markdown table row."""
    return [cell.strip() for cell in line.strip().strip("|").split("|")]


def _availability(status: str | None) -> AvailabilityState:
    """Map Cohere's documented lifecycle labels without inventing unknown state."""
    if status is None:
        return "available"
    normalized = status.casefold()
    if normalized.startswith("live"):
        return "available"
    if normalized.startswith("retired"):
        return "unavailable"
    return "unknown"


def _model_rows(markdown: str) -> list[tuple[str, AvailabilityState]]:
    """Extract Cohere API model rows, excluding cross-platform identifier tables."""
    rows: list[tuple[str, AvailabilityState]] = []
    lines = markdown.splitlines()
    index = 0
    while index < len(lines):
        header = _table_cells(lines[index]) if lines[index].lstrip().startswith("|") else []
        header_names = [cell.casefold() for cell in header]
        if not header_names or header_names[0] != "model name" or "endpoints" not in header_names:
            index += 1
            continue

        status_index = header_names.index("status") if "status" in header_names else None
        index += 2  # Skip the Markdown separator row immediately below the header.
        while index < len(lines) and lines[index].lstrip().startswith("|"):
            cells = _table_cells(lines[index])
            model_match = _CODE_CELL_RE.fullmatch(cells[0]) if cells else None
            if model_match:
                status = cells[status_index] if status_index is not None and status_index < len(cells) else None
                rows.append((model_match.group(1), _availability(status)))
            index += 1
    return rows


class CohereDocsConnector:
    """Parse Cohere API model IDs from its public Models documentation page."""

    source_id = "cohere-model-docs"
    fixture_filename = "cohere-model-docs.md"
    url = MODELS_INDEX_URL
    license = "Cohere documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Cohere documentation endpoints deliberately share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="cohere-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        offerings: dict[str, AvailabilityState] = {
            model_id: availability_state for model_id, availability_state in _model_rows(body.decode("utf-8"))
        }
        records: list[Record] = [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="api_doc",
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            )
        ]
        records.extend(
            ProviderOfferingRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                source_model_id=model_id,
                service_id="cohere-api",
                source_provider_label="Cohere",
                availability_state=availability_state,
                observed_at=observed_at,
            )
            for model_id, availability_state in sorted(offerings.items())
        )
        return records
