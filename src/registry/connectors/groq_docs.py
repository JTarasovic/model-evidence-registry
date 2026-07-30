"""Groq's official Supported Models documentation connector.

The public Supported Models page is used instead of ``GET /openai/v1/models``, which requires an
API key.  The connector emits only the page hash and the source-native model IDs and lifecycle
facts from Groq's model tables; it does not re-host the documentation.  Its saved fixture is a
small, facts-only table subset.
"""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Literal

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_INDEX_URL = "https://console.groq.com/docs/models"
AvailabilityState = Literal["available", "unavailable", "unknown"]
_AVAILABILITY_BY_HEADING: dict[str, AvailabilityState] = {
    "production models": "available",
    "production systems": "available",
    "preview models": "available",
    "deprecated models": "unavailable",
}


class _ModelsPageParser(HTMLParser):
    """Collect model IDs from the lifecycle-labelled tables on Groq's public page."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.offerings: dict[str, AvailabilityState] = {}
        self._heading_level: int | None = None
        self._heading_parts: list[str] = []
        self._availability_state: AvailabilityState = "unknown"
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None
        self._cell_model_id: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        attributes = dict(attrs)
        if tag in {"h2", "h3"}:
            self._heading_level = int(tag[1])
            self._heading_parts = []
        elif tag == "table":
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell_parts = []
            self._cell_model_id = None

        # Groq's current table renders the display name and source-native model ID in one cell,
        # with the latter on an inner ``div id``.  Prefer that identifier over the rendered text.
        if self._cell_parts is not None and self._cell_model_id is None and (model_id := attributes.get("id")):
            self._cell_model_id = model_id

    def handle_data(self, data: str) -> None:
        if self._heading_level is not None:
            self._heading_parts.append(data)
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._heading_level is not None and tag == f"h{self._heading_level}":
            heading = " ".join("".join(self._heading_parts).split()).casefold()
            self._availability_state = _AVAILABILITY_BY_HEADING.get(heading, "unknown")
            self._heading_level = None
            self._heading_parts = []
        elif tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append(self._cell_model_id or " ".join("".join(self._cell_parts).split()))
            self._cell_parts = None
            self._cell_model_id = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self._add_table_offerings(self._table, self._availability_state)
            self._table = None

    def _add_table_offerings(self, table: list[list[str]], availability_state: AvailabilityState) -> None:
        if not table:
            return
        headers = [cell.casefold() for cell in table[0]]
        if "model id" not in headers:
            return
        model_id_index = headers.index("model id")
        for row in table[1:]:
            if model_id_index >= len(row) or not (model_id := row[model_id_index]):
                continue
            self.offerings[model_id] = availability_state


class GroqDocsConnector:
    """Parse GroqCloud model IDs from Groq's public Supported Models page."""

    source_id = "groq-model-docs"
    fixture_filename = "groq-model-docs.html"
    url = MODELS_INDEX_URL
    license = "Groq documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Groq documentation endpoints deliberately share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="groq-docs", min_interval_seconds=0.5)

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
                service_id="groq",
                source_provider_label="Groq",
                availability_state=availability_state,
                observed_at=observed_at,
            )
            for model_id, availability_state in sorted(parser.offerings.items())
        )
        return records
