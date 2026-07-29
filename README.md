# model-evidence-registry

A reproducible, provenance-first **model-evidence registry** — a proof of concept for Phase 2 of the
Agent Foundry model-evidence work (issue #168), governed by
[ADR 0028](https://github.com/JTarasovic/agent-foundry/blob/main/docs/adrs/0028-model-evidence-registry-adopt-vs-build.md)
and the [design doc](https://github.com/JTarasovic/agent-foundry/blob/main/docs/designs/model-evidence-registry.md).

> **Boundary invariant.** This repo never imports Agent Foundry code, and Agent Foundry never imports
> this repo's code. The only contract between them is the published, versioned artifact
> (`records.json` + `records.parquet` + `manifest.json` + `records.schema.json`) plus its JSON Schema.
> This repo is **advisory evidence** — it proposes; a human reviews and Agent Foundry decides.

## What it does

Adopt-and-compose public sources (never a monolithic scraper), normalize them into **six separate
record types**, and publish a validated, checksummed artifact:

| Record type         | Meaning                                                                        |
| ------------------- | ------------------------------------------------------------------------------ |
| `model`             | Canonical id, publisher/developer, family, release, aliases.                   |
| `provider_offering` | Availability, modalities, context/output limits, pricing **observation**.      |
| `document`          | A fetched asset: url, hash/etag, retrieval time, redistribution policy.        |
| `evaluation_result` | A benchmark result with id/version/split/metric + harness/agent/comparability. |
| `claim`             | A reported number **not** backed by a reproducible result row.                 |
| `source_snapshot`   | Per-source fetch outcome, validators, checksum, license, freshness.            |

Every record carries a `trust_level` from the source ladder, and the pipeline **never manufactures
equivalence** between `SWE-bench` / `SWE-bench Verified` / `SWE-bench Pro` or across differing
agent/reasoning settings.

### Connectors (public sources only, no credentials)

- **models.dev** — offering/pricing/capability/context evidence (MIT).
- **OpenRouter** — availability/pricing/context **evidence only**, never a benchmark authority.
- **Hugging Face** — leaderboard eval data for open-weight models.
- **SWE-bench** `data/leaderboards.json` — official resolved-% (rows without logs+trajs → `claim`).
  Stored **hash + facts only** (the site repo is NOASSERTION-licensed).
- **Terminal-Bench** — agentic terminal-task benchmark (Apache-2.0). LiveCodeBench is deferred (stale).

See [`docs/eee-evaluation.md`](docs/eee-evaluation.md) for the Every Eval Ever qualification finding.

## Usage

```sh
uv venv --python 3.12 .venv && . .venv/bin/activate
uv pip install -e ".[dev]"

registry build --fixtures --out dist/   # deterministic, no network (PoC default)
registry build --live --out dist/       # best-effort live smoke against public sources

pytest            # determinism + conditional-fetch (200/304) + publish schema/checksum tests
ruff check . && pyright
```

The `--fixtures` build replays the saved responses in [`fixtures/`](fixtures/) byte-for-byte, so
identical inputs produce identical checksums. The Agent Foundry side consumes `dist/` via
`scripts/model-evidence-import.ts`, which verifies the manifest checksums and emits a **reviewable
diff** against `model-inventory.yaml` without auto-applying.

## Status

Local PoC — **not yet scheduled or public**. GitHub Release transport, `latest` pointer,
attestations/SBOM, scheduling, and broader coverage are later phases (ADR 0028 follow-ups).
