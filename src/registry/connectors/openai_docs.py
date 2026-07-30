"""OpenAI's official API Models documentation connector.

The public Models index is used instead of ``GET /v1/models``, which requires an API key.
This connector stores the page hash and the model identifiers linked by the index, not a
redistributable copy of the documentation.  Its fixture is a small, facts-only set of
model links rather than a saved OpenAI documentation page.
"""

from __future__ import annotations

import re
from html.parser import HTMLParser
from urllib.parse import urlsplit

from registry.fetch import FetchPolicy, sha256_hex
from registry.schema import DocumentRecord, ProviderOfferingRecord, Record, TrustLevel

MODELS_INDEX_URL = "https://developers.openai.com/api/docs/models"
_MODEL_PATH_RE = re.compile(r"^/api/docs/models/([^/]+)$")


class _ModelsPageParser(HTMLParser):
    """Collect model-detail links and any provider-supplied build revision."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.model_ids: set[str] = set()
        self.revision: str | None = None

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = dict(attrs)
        if tag == "a":
            href = attributes.get("href")
            if href is not None:
                parsed = urlsplit(href)
                if parsed.netloc in {"", "developers.openai.com"}:
                    match = _MODEL_PATH_RE.fullmatch(parsed.path)
                    if match:
                        self.model_ids.add(match.group(1))
        if self.revision is None:
            self.revision = (
                attributes.get("data-build-id")
                or attributes.get("data-page-revision")
                or (
                    attributes.get("content")
                    if tag == "meta" and attributes.get("name") in {"build-id", "build-revision", "revision"}
                    else None
                )
            )


class OpenAIDocsConnector:
    """Parse direct OpenAI API model IDs from the public Models index."""

    source_id = "openai-model-docs"
    fixture_filename = "openai-model-docs.html"
    url = MODELS_INDEX_URL
    license = "OpenAI documentation terms; extracted facts and content hash only"
    parser_version = "1"
    trust_level = TrustLevel.OFFICIAL_MODEL_CARD_CLAIM
    # Documentation endpoints intentionally share a conservative provider-wide rate limit.
    fetch_policy = FetchPolicy(source_key="openai-docs", min_interval_seconds=0.5)

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
                revision=parser.revision,
                content_sha256=sha256_hex(body),
                retrieved_at=observed_at,
                redistribution_policy="hash_and_facts_only",
            )
        ]
        records.extend(
            ProviderOfferingRecord(
                source_id=self.source_id,
                trust_level=self.trust_level,
                model_id=model_id,
                provider="OpenAI",
                availability_state="available",
                observed_at=observed_at,
            )
            for model_id in sorted(parser.model_ids)
        )
        return records
