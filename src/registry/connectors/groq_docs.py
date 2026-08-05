"""Groq's official Supported Models documentation connector.

The public Supported Models page is used instead of ``GET /openai/v1/models``, which requires an
API key.  The connector emits the index page hash and the source-native model IDs and lifecycle
facts from Groq's model tables, then crawls each model's public detail page for the capabilities it
documents (tool use, structured output, reasoning).  It does not re-host the documentation; each
fetched page contributes only a content hash and extracted facts.  Its saved fixtures are small,
facts-only subsets.

Detail-page discovery is dynamic: the live index enumerates the models, and ``discover`` turns each
into its ``/docs/model/<id>`` page.  The static ``FIXTURE_FILENAMES`` map exists only so the
deterministic fixture build can replay those same URLs offline; live builds never consult it.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Literal

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_INDEX_URL = "https://console.groq.com/docs/models"
MODEL_DETAIL_PREFIX = "https://console.groq.com/docs/model/"
AvailabilityState = Literal["available", "unavailable", "unknown"]
_AVAILABILITY_BY_HEADING: dict[str, AvailabilityState] = {
    "production models": "available",
    "production systems": "available",
    "preview models": "available",
    "deprecated models": "unavailable",
}

# Groq's model detail page lists the model's supported capabilities as links to the relevant docs,
# inside a small ``text-xs … text-primary`` label row on the CAPABILITIES card.  Scoping to that row
# avoids the sidebar's navigation links to the same docs.  The card is a complete enumeration of the
# model's capabilities, so a known capability whose link is absent is a documented negative (False);
# a page with no recognizable capability row at all leaves every field undocumented (None).
_CAPABILITY_ROW_RE = re.compile(r'<div class="[^"]*text-xs[^"]*text-primary[^"]*">(.*?)</div>', re.DOTALL)
_CAPABILITY_HREF_RE = re.compile(r'href="(/docs/(?:tool-use|structured-outputs|reasoning))(?:[#/][^"]*)?"')
_CAPABILITY_FIELD_BY_PATH = {
    "/docs/tool-use": "tool_use",
    "/docs/structured-outputs": "structured_output",
    "/docs/reasoning": "reasoning",
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


def _parse_index(body: bytes) -> dict[str, AvailabilityState]:
    parser = _ModelsPageParser()
    parser.feed(body.decode("utf-8"))
    parser.close()
    return parser.offerings


def _detail_capabilities(body: bytes) -> dict[str, bool]:
    """Extract documented capabilities from a Groq model detail page.

    Returns a mapping over the known capability fields, or an empty mapping when the page exposes no
    recognizable capability row (so the caller records ``None`` — undocumented — rather than False).
    """
    text = body.decode("utf-8", "replace")
    found = {path for row in _CAPABILITY_ROW_RE.findall(text) for path in _CAPABILITY_HREF_RE.findall(row)}
    if not found:
        return {}
    return {field: (path in found) for path, field in _CAPABILITY_FIELD_BY_PATH.items()}


def detail_url(model_id: str) -> str:
    """Return the public detail-page URL for one source-native Groq model ID."""
    return f"{MODEL_DETAIL_PREFIX}{model_id}"


def _detail_fixture_filename(model_id: str) -> str:
    return f"groq-model-detail-{model_id.replace('/', '-')}.html"


# Fixture-replay only: the model IDs present in the saved index fixture, so the offline build can map
# each discovered detail URL to a saved page.  Live builds discover these from the real index.
_FIXTURE_DETAIL_MODEL_IDS = (
    "llama-3.3-70b-versatile",
    "openai/gpt-oss-120b",
    "groq/compound-mini",
    "retired-model-v1",
)
FIXTURE_FILENAMES = {
    MODELS_INDEX_URL: "groq-model-docs.html",
    **{detail_url(model_id): _detail_fixture_filename(model_id) for model_id in _FIXTURE_DETAIL_MODEL_IDS},
}


class GroqDocsConnector:
    """Parse GroqCloud model IDs and per-model capabilities from Groq's public documentation."""

    source_id = "groq-model-docs"
    fixture_filenames = FIXTURE_FILENAMES
    url = MODELS_INDEX_URL
    license = "Groq documentation terms; extracted facts and content hash only"
    parser_version = "2"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Groq documentation endpoints deliberately share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="groq-docs", min_interval_seconds=0.5)

    def discover(self, url: str, body: bytes) -> tuple[str, ...]:
        """From the fetched index page, return each model's detail-page URL (deterministic order)."""
        if url != self.url:
            return ()
        return tuple(detail_url(model_id) for model_id in sorted(_parse_index(body)))

    def parse(self, body: bytes, observed_at: str = "") -> list[Record]:
        """Parse the index alone — capabilities stay ``None`` without the crawled detail pages."""
        return self.parse_all({self.url: body}, observed_at=observed_at)

    def parse_all(self, bodies: dict[str, bytes | None], observed_at: str = "") -> list[Record]:
        records: list[Record] = []
        offerings: dict[str, AvailabilityState] = {}
        capabilities_by_id: dict[str, dict[str, bool]] = {}

        index_body = bodies.get(self.url)
        if index_body is not None:
            offerings = _parse_index(index_body)
            records.append(self._document(self.url, index_body, observed_at))

        for url, body in bodies.items():
            if url == self.url or body is None:
                continue
            capabilities_by_id[url[len(MODEL_DETAIL_PREFIX) :]] = _detail_capabilities(body)
            records.append(self._document(url, body, observed_at))

        for model_id, availability_state in sorted(offerings.items()):
            capabilities = capabilities_by_id.get(model_id, {})
            records.append(
                ProviderOfferingRecord(
                    source_id=self.source_id,
                    trust_level=self.trust_level,
                    source_model_id=model_id,
                    service_id="groq",
                    source_provider_label="Groq",
                    availability_state=availability_state,
                    tool_use=capabilities.get("tool_use"),
                    structured_output=capabilities.get("structured_output"),
                    reasoning=capabilities.get("reasoning"),
                    observed_at=observed_at,
                )
            )
        return records

    def _document(self, url: str, body: bytes, observed_at: str) -> DocumentRecord:
        return DocumentRecord(
            source_id=self.source_id,
            trust_level=self.trust_level,
            url=url,
            kind="api_doc",
            content_sha256=sha256_hex(body),
            retrieved_at=observed_at,
            redistribution_policy="hash_and_facts_only",
        )
