"""Anthropic's official Models overview documentation connector.

The Models overview is an official provider document that lists the identifiers available through
the Claude API.  Anthropic's documentation is not bundled or re-hosted in the artifact: the
connector emits only the document hash, the page build revision, and the extracted offering facts.
The saved fixture is likewise a small, purpose-built facts-only HTML table rather than a copy of
the provider's documentation.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_OVERVIEW_URL = "https://platform.claude.com/docs/en/about-claude/models/overview"
_BUILD_ID_RE = re.compile(r'\bdata-build-id=["\']([^"\']+)["\']')


class _TableParser(HTMLParser):
    """Collect text cells from documentation tables without depending on page styling."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.tables: list[list[list[str]]] = []
        self._table: list[list[str]] | None = None
        self._row: list[str] | None = None
        self._cell_parts: list[str] | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:  # noqa: ARG002
        if tag == "table":
            self._table = []
        elif self._table is not None and tag == "tr":
            self._row = []
        elif self._row is not None and tag in {"td", "th"}:
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_parts is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag in {"td", "th"} and self._row is not None and self._cell_parts is not None:
            self._row.append("".join(self._cell_parts).strip())
            self._cell_parts = None
        elif tag == "tr" and self._table is not None and self._row is not None:
            self._table.append(self._row)
            self._row = None
        elif tag == "table" and self._table is not None:
            self.tables.append(self._table)
            self._table = None


class AnthropicDocsConnector:
    """Parse direct Claude API model IDs from Anthropic's official Models overview."""

    source_id = "anthropic-model-docs"
    fixture_filename = "anthropic-model-docs.html"
    url = MODELS_OVERVIEW_URL
    license = "Anthropic documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Provider documentation is deliberately conservative.  Additional Anthropic documentation
    # endpoints should reuse this key so they share the same rate limit.
    fetch_policy = FetchPolicy(source_key="anthropic-docs", min_interval_seconds=0.5)

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        text = body.decode("utf-8")
        parser = _TableParser()
        parser.feed(text)
        parser.close()

        # Only the provider's direct API identifiers are offerings here. Bedrock and Vertex IDs in
        # the same document remain their own provider offerings and must not be relabelled Anthropic.
        model_ids = sorted(
            {
                cell.strip()
                for table in parser.tables
                for row in table
                if row and row[0].casefold() == "claude api id"
                for cell in row[1:]
                if cell.strip()
            }
        )
        revision_match = _BUILD_ID_RE.search(text)
        records: list[Record] = [
            DocumentRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                url=self.url,
                kind="api_doc",
                revision=revision_match.group(1) if revision_match else None,
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
                service_id="anthropic-api",
                source_provider_label="Anthropic",
                availability_state="available",
                observed_at=observed_at,
            )
            for model_id in model_ids
        )
        return records
