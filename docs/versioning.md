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
   overwritten; a separate mutable `latest` release mirrors the newest snapshot's assets.

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
verbatim. The `crosswalk.json` sidecar is **advisory** — it _proposes_ canonical ids; the consumer
owns the final identity decision. The registry never manufactures equivalence between distinct
benchmarks/settings. See the [design doc](https://github.com/JTarasovic/agent-foundry/blob/main/docs/designs/model-evidence-registry.md).

## Integrity

`manifest.json` lists every artifact file's SHA-256 (`artifacts[name].sha256`) and byte length; it is
written last, after all other bytes are known. Scheduled releases additionally carry **build
provenance attestation** (keyless, SLSA via GitHub OIDC) — verify with `gh attestation verify <file>
--repo JTarasovic/model-evidence-registry`. Sigstore/cosign signing is a planned addition.
