# ADR 0002: Doc-scraper capability-signal audit

- Status: Accepted
- Date: 2026-08-05
- Decision source: [Issue #17](https://github.com/JTarasovic/model-evidence-registry/issues/17)

## Context

The structured-JSON `provider_offering` connectors gained documented `tool_use` / `reasoning` /
`structured_output` mapping in #13 and #15. The doc-scraping connectors were deliberately left out
of that work: they emit offerings from ID-only table/prose extraction, and reliable HTML/markdown
capability extraction is fragile and per-source. #17 tracks auditing each doc scraper's **live**
source to decide, per connector, whether a targeted extraction rule can reliably pull a capability
field — landing it where it can, and recording "the source doesn't document this" where it can't.

## Audit outcome

Each source below was checked live on 2026-08-05.

| Connector | Live source | Reliably extractable capability signal | Action |
|---|---|---|---|
| `anthropic_docs` | Models overview comparison table | **Reasoning** — per-model "Extended thinking" and "Adaptive thinking" rows. No tool-use or structured-output row. | **Mapped `reasoning`** (this change) |
| `anthropic_claude_code_docs` | Claude Code model-configuration support article | None — lists model name + ID only | Record only |
| `openai_docs` | developers.openai.com models index | Reasoning/tools shown only in per-model JS card widgets, not a parseable table | Record only (fragile) |
| `openai_codex_docs` | learn.chatgpt.com models | React `<ModelDetails>` components; effort levels, no per-model capability fields | Record only |
| `github_copilot_docs` | GitHub Copilot supported-models | **Reasoning** — a separate "Models with extended capabilities" table marks a "Configurable reasoning" column per model with a Supported / Not supported octicon (`aria-label`). Covers only the latest models. | **Mapped `reasoning`** (this change) |
| `cohere_docs` | docs.cohere.com models.md | None — columns are name/status/description/modality/context/output/endpoints | Record only |
| `groq_docs` | console.groq.com models | None — columns are id/speed/price/rate-limits/context/output/file-size | Record only |
| `mistral_docs` | model-selection-guide | Capabilities are page-level feature checkboxes, not per-model table columns | Record only (fragile) |
| `google_gemini_docs` | ai.google.dev models | None on this page — capabilities live on separate feature pages, not per-model here | Record only |

## Decision

Map documented `reasoning` from the two sources that expose it reliably per model:

- **`anthropic_docs`** — the overview comparison table's thinking rows. A model reasons when either
  the "Extended thinking" or "Adaptive thinking" row states "Yes"; when a table carries those rows,
  every column is a documented Yes/No, so both-"No" is a real documented `False`. A table without
  thinking rows (the legacy-models table) leaves reasoning `None`.
- **`github_copilot_docs`** — the "Models with extended capabilities" table's "Configurable
  reasoning" column. The octicon `aria-label` is the documented value: Supported → `True`, Not
  supported → `False`. That table lists only the latest models, so a model absent from it (present
  only in the main catalogue) leaves reasoning `None`.

Tool use and structured output are not stated in either table and stay `None`. Semantics follow
#13/#15: `None` for absent, real `False` for a documented negative.

For every other doc scraper the live source does not expose a per-model capability field a targeted
rule can extract reliably, so no capability mapping is added; this is a valid, recorded outcome, not
a deferred TODO. If a source later adds a stable per-model capability table, revisit that connector.

## Addendum (2026-08-05): per-model detail-page crawl

The audit above only checked each connector's single **index** page. Several providers publish
capability signal on separate **per-model detail pages** instead. To reach it without hardcoding a
model roster, the build orchestrator gained an optional two-phase crawl (`discover(url, body)` →
follow-up URLs, `parse_all({url: body})` → records): a connector's live index enumerates the models,
the build fetches each model's detail page under the same per-source rate limit, and `parse_all`
correlates them. Detail pages were then checked live (2026-08-05):

| Connector | Per-model detail page | Reliably extractable? | Action |
|---|---|---|---|
| `groq_docs` | `console.groq.com/docs/model/<id>` | **Yes** — a CAPABILITIES card enumerates supported capabilities as `/docs/{tool-use,structured-outputs,reasoning}` links (server-rendered). | **Crawl + map `tool_use` / `structured_output` / `reasoning`** |
| `openai_docs` | `developers.openai.com/api/docs/models/<id>` | No — the per-model capability matrix is client-rendered; raw HTML holds only left-nav chrome (`function_calling` / `structured_output` appear as sidebar links, not model facts). | Record only |
| `google_gemini_docs` | `ai.google.dev/gemini-api/docs/models` | No — every `Function calling` / `Structured outputs` / `Thinking` token in the page is `devsite` left-nav. The structured per-model signal (`supportedGenerationMethods`, `thinking`) lives only in the **authenticated** `models.list` API, which is out of scope for a keyless doc scraper. | Record only |
| `cohere_docs` | `docs.cohere.com/docs/<model>.md` | No — capabilities are marketing prose ("excels at tool use, RAG, agents…"), not a per-model boolean matrix; every Command model claims tool use and none states a documented negative. | Record only |

For `groq_docs` the CAPABILITIES card is a complete enumeration of the model's capabilities: a
listed capability is `True`, a known capability absent from a present card is a documented `False`,
and a detail page with no recognizable card leaves every field `None`. The crawl infrastructure is
general and available to any future connector whose source splits capabilities onto detail pages.
