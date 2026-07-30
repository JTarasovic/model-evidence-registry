"""Mistral AI's official model documentation connector.

Mistral's public model-selection guide presents current API identifiers in an ``IDS`` field on
each model card.  Its overview has also used a ``Model | Version | API`` deprecation table.  This
connector accepts both documented shapes so that current offerings and explicit retirements retain
their source-native identifiers and lifecycle facts.  It emits only extracted facts and a content
hash; the documentation is not re-hosted.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Literal

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_GUIDE_URL = "https://docs.mistral.ai/models/model-selection-guide"
AvailabilityState = Literal["available", "unavailable", "unknown"]


class _ModelsPageParser(HTMLParser):
    """Collect model-card IDs and API IDs from Mistral's lifecycle-labelled tables."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.offerings: dict[str, AvailabilityState] = {}
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._availability_state: AvailabilityState = "available"
        self._paragraph_parts: list[str] | None = None
        self._expect_model_id = False
        self._code_parts: list[str] | None = None
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag in {"h2", "h3"}:
            self._heading_level = int(tag[1])
            self._heading_parts = []
        elif tag == "p":
            self._paragraph_parts = []
        elif tag == "code" and self._expect_model_id:
            self._code_parts = []
        elif tag == "table":
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_parts.append(data)
        if self._paragraph_parts is not None:
            self._paragraph_parts.append(data)
        if self._code_parts is not None:
            self._code_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            heading = _normalized("".join(self._heading_parts)).casefold()
            self._availability_state = "unavailable" if "legacy" in heading or "deprecated" in heading else "available"
            self._heading_level = None
            self._heading_parts = []
        elif tag == "p" and self._paragraph_parts is not None:
            self._expect_model_id = _normalized("".join(self._paragraph_parts)).casefold() == "ids"
            self._paragraph_parts = None
        elif tag == "code" and self._code_parts is not None:
            if model_id := _normalized("".join(self._code_parts)):
                self.offerings[model_id] = self._availability_state
            self._code_parts = None
            self._expect_model_id = False
        elif tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(_normalized("".join(self._cell_parts)))
            self._cell_parts = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._add_table_offerings(self._table)
            self._table = None

    def _add_table_offerings(self, table: list[list[str]]) -> None:
        if not table:
            return
        headers = [cell.casefold() for cell in table[0]]
        if "api" not in headers:
            return
        api_index = headers.index("api")
        for row in table[1:]:
            if api_index < len(row) and (model_id := row[api_index]):
                self.offerings[model_id] = self._availability_state


def _normalized(value: str) -> str:
    """Collapse presentation whitespace without altering source-native identifier spelling."""
    return " ".join(value.split())


class MistralDocsConnector:
    """Parse Mistral API model IDs from its public model-selection documentation."""

    source_id = "mistral-model-docs"
    fixture_filename = "mistral-model-docs.html"
    url = MODELS_GUIDE_URL
    license = "Mistral AI documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Mistral documentation endpoints deliberately share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="mistral-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        parser = _ModelsPageParser()
        parser.feed(body.decode("utf-8"))
        parser.close()

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
                service_id="mistral-api",
                source_provider_label="Mistral AI",
                availability_state=availability_state,
                observed_at=observed_at,
            )
            for model_id, availability_state in sorted(parser.offerings.items())
        )
        return records
