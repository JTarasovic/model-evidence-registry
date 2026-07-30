# Contributing

Thanks for helping improve the model-evidence registry. Please read the **boundary invariant** first
— it constrains every change here.

## Boundary invariant

This repo **never imports Agent Foundry code, and Agent Foundry never imports this repo's code.** The
only contract between them is the published, versioned artifact (`records.json` + per-record-type
Parquet + `manifest.json` + `records.schema.json`) plus its JSON Schema. This repo is **advisory
evidence**: it _proposes_; a human reviews and Agent Foundry decides. See
[ADR 0028](https://github.com/JTarasovic/agent-foundry/blob/main/docs/adrs/0028-model-evidence-registry-adopt-vs-build.md)
and [`docs/versioning.md`](docs/versioning.md).

## Setup

```sh
python -m pip install -e ".[dev]"     # Python 3.12+
```

## Build & test

```sh
registry build --fixtures --out dist/   # deterministic, no network (the default)
registry build --live --out dist/       # hit real public sources (best-effort)
pytest                                  # deterministic against saved fixtures
ruff check .                            # lint
pyright                                 # typecheck
```

CI (`.github/workflows/ci.yml`) runs `ruff` + `pyright` + `pytest` on every push/PR. The scheduled
`publish.yml` builds `--live` and publishes an immutable dated release + attestation. Keep the
fixtures build byte-deterministic — reviewability depends on it.

## Adding a source connector

A connector owns exactly one source and is a **pure `bytes -> records` parser** (fetching, caching,
and snapshot bookkeeping live in `registry.build`, so connectors stay deterministic). To add one:

1. Implement the `Connector` protocol in `src/registry/connectors/base.py`: declare `source_id`,
   `url`, `license`, `parser_version`, and a snapshot `trust_level` from the ladder (official
   structured result > official model-card/release claim > benchmark-maintainer leaderboard >
   independently reproducible run > third-party report), and a `parse(body, observed_at)` method.
2. **Never call `datetime.now()`** in a connector — use the injected `observed_at` so identical bytes
   produce identical checksums.
3. **Preserve source-native identifiers verbatim.** Emit the model id as `source_model_id` exactly as
   the source states it (it may contain `/`; the first segment is not a developer). Do not merge,
   rename, or normalize ids into a canonical form — deciding two ids are "the same model" is a
   curation decision that belongs in the advisory crosswalk, and a wrong central merge is invisible
   to every consumer. Keep the access path and any source-supplied provider value separate: set a
   stable registry-owned `service_id` for the offering's access service (or leave it null), and put
   any verbatim provider value the source supplied in `source_provider_id` / `source_provider_label`.
   See the [identity-namespaces glossary](docs/versioning.md#identity-namespaces-glossary).
4. **Never manufacture equivalence** between distinct benchmarks or run settings (e.g. `SWE-bench`
   vs `SWE-bench Verified` vs `SWE-bench Pro`, or scores under different agents/reasoning) — each is
   a distinct `evaluation_result`/`claim` with comparability metadata.
5. Respect the source's license, terms, robots, and rate limits. Store hashes + extracted facts by
   default; retain raw bytes only where licensing permits. **No API keys in artifacts** — a fully
   useful public baseline must exist without any paid source.
6. Register it in `src/registry/connectors/__init__.py` (`default_connectors()`) and add a **saved
   fixture** plus a test in `tests/` so the parser is deterministic.

### Credentialed / redistribution-restricted sources

A source that needs an API key **or** whose terms restrict redistribution does **not** go in
`default_connectors()` — that set must stay a fully-public, no-credential baseline. Instead:

- Expose an `auth_headers()` method returning the request header(s); the build layer passes them to
  `conditional_fetch` (the only place a secret ever appears — never a record or snapshot).
- Read the key from an env var, defaulting to absent; emit nothing without it.
- Register it in `credentialed_connectors()`, which self-gates on the env var so a keyless public
  build never calls it. A live build appends it only when the key is present.
- Store extracted facts only (no raw bytes) and complete a **licensing/redistribution review before
  enabling it in the scheduled publish**. `ArtificialAnalysisConnector` is the reference example.

## Schema changes

Changing a record shape means bumping `SCHEMA_VERSION` in `src/registry/schema.py` per the SemVer
rules in [`docs/versioning.md`](docs/versioning.md), in the same commit. `records.schema.json` is
regenerated from the pydantic models.
