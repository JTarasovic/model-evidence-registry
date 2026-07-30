# Versioning & the artifact contract

This registry's only contract with any consumer (Agent Foundry included) is the **published,
versioned artifact** plus its **JSON Schema** — never this repo's source. This document formalizes
what that contract guarantees and how it changes.

## What is versioned

Two independent version lines:

1. **Schema version** — `SCHEMA_VERSION` in `src/registry/schema.py`, stamped into every
   `records.json` and `manifest.json` as `schema_version`, and materialized as the shipped
   `records.schema.json`. This is the shape of the data.
2. **Snapshot release** — each scheduled publish is an immutable, dated GitHub Release
   (`snapshot-YYYY-MM-DD`). This is the _content_ at a point in time. Snapshots are never reused or
   overwritten; consumers resolve the newest `snapshot-*` release client-side when they need it.

## Schema SemVer

`schema_version` follows [Semantic Versioning](https://semver.org):

- **MAJOR** — a breaking change to record shape: removing/renaming a field, tightening a type,
  changing an enum's meaning, or splitting/merging a record type. Consumers pinned to an older
  schema will not validate.
- **MINOR** — a backward-compatible addition: a new **optional** field, a new record type, or a new
  enum value in an already-open set. Existing consumers keep validating.
- **PATCH** — documentation/clarification only; no shape change.

Bump `SCHEMA_VERSION` in the same commit that changes `schema.py`, and note the change in this repo's
release notes. `records.schema.json` is regenerated from the pydantic models, so it always matches
the code that produced a given snapshot.

## JSON Schema is the contract; Parquet is the analytical surface

- **`records.json` (+ `records.schema.json`) is the authoritative, validated contract.** It is
  sorted-key, byte-deterministic, and diffable — the property the Agent Foundry reviewable-diff flow
  depends on. Consumers **pin a dated release** and validate `records.json` against **that release's**
  shipped `records.schema.json`.
- **Parquet is the compact/analytical surface** — a star schema, one file per record type
  (`model.parquet`, `provider_offering.parquet`, …, plus `crosswalk.parquet`), so DuckDB queries
  typed columns directly with no extra artifact.
- **SQLite (single-file DB) was considered and rejected** (ADR 0028 §4 / design §4): it forces a
  native dependency on the TypeScript consumer, can't be validated against the published JSON Schema,
  and fights byte-stable checksums/diffs — for no gain over DuckDB-over-Parquet.

## Trust, not just shape

Every record carries a `trust_level` from the source ladder and preserves source-native identifiers
verbatim. The `crosswalk.json` sidecar is **advisory** — it _proposes_ canonical ids **only** from an
explicit reviewed identity table (`method="reviewed_alias"`) and otherwise says `unmapped` with a
null canonical id; the consumer owns the final identity decision. A canonical id is never derived
from an access `service_id` or a provider label. The registry never manufactures equivalence between
distinct benchmarks/settings. See the [design doc](https://github.com/JTarasovic/agent-foundry/blob/main/docs/designs/model-evidence-registry.md).

## Identity namespaces (glossary)

These are **separate** namespaces and are named separately in the artifact. Conflating them (for
example, deriving a canonical id from an access provider) is the bug corrected in schema `0.2.0`.

| field / concept | meaning |
| --- | --- |
| `source_id` | connector / evidence origin (`models.dev`, `cerebras-models`, `groq-model-docs`). |
| `service_id` | stable **registry-owned** inference/access-service id (`cerebras`, `groq`, `openai-api`). Null when no reviewed access service applies; never derived from a source display string. |
| `source_provider_id` / `source_provider_label` | optional **verbatim** provider value the source itself supplied. |
| `source_model_id` | the model id exactly as the source emitted it; opaque, may contain `/`. Its first segment is never interpreted as a developer. |
| `developer_id` | reviewed canonical developer-organization id, when known; never guessed from a free-text label. |
| `canonical_model_id` | reviewed cross-source identity, when known; `null` when unmapped. Never derived from `service_id`. |

Direct-provider API access and any subscription/product access path are **distinct** `service_id`s:
direct OpenAI API evidence (`openai-api`) is not evidence for an OpenAI Codex subscription route.
`hf-model-cards` and `huggingface` remain distinct `source_id`s (different endpoints, parsers, trust
levels, licences, and evidence types).

The exact canonical slug policy: a developer-prefixed canonical id (`openai/gpt-oss-120b`) is
acceptable **only** when both the `developer_id` and the model equivalence are explicitly reviewed and
recorded in `registry/normalize.py::_REVIEWED_IDENTITY`. Lowercasing a free-text developer or
provider label is not sufficient.

## Integrity

`manifest.json` lists every artifact file's SHA-256 (`artifacts[name].sha256`) and byte length; it is
written last, after all other bytes are known. Scheduled releases additionally carry **build
provenance attestation** (keyless, SLSA via GitHub OIDC) — verify with `gh attestation verify <file>
--repo JTarasovic/model-evidence-registry`. They also carry a keyless Sigstore bundle for
`manifest.json`; verify it with `cosign verify-blob manifest.json --bundle
manifest.json.sigstore.json`, pinning the publishing workflow identity and GitHub Actions OIDC issuer
as documented in the README. The signed manifest transitively protects every artifact digest.
