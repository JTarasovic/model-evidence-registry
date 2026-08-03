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
| `provider_offering` | An observed inference/access-service offering: availability, modalities, context/output limits, and pricing. |
| `document`          | A fetched asset: url, hash/etag, retrieval time, redistribution policy.        |
| `evaluation_result` | A benchmark result with id/version/split/metric + harness/agent/comparability. |
| `claim`             | A reported number **not** backed by a reproducible result row.                 |
| `source_snapshot`   | Per-source fetch outcome, validators, checksum, license, freshness.            |

Every record carries a `trust_level` from the source ladder, and the pipeline **never manufactures
equivalence** between `SWE-bench` / `SWE-bench Verified` / `SWE-bench Pro` or across differing
agent/reasoning settings.

### Connectors (public sources only, no credentials)

- **Anthropic Models overview** — official direct-Claude-API availability evidence. Documentation is
  represented as **hash + extracted facts only**, not re-hosted.
- **Anthropic Claude Code configuration** — official Claude Code catalogue evidence, separate from
  the direct Anthropic API. Subscription-plan limits remain source-qualified rather than inferred.
- **OpenAI Codex models** — official Codex product catalogue evidence, separate from the Platform
  API model index.
- **GitHub Copilot supported models** — official Copilot catalogue evidence, separate from GitHub
  Models; client, plan, and organization-policy restrictions remain source-qualified.
- **Cerebras public model catalog** — official keyless availability, modality, token-limit, and pricing
  evidence; represented as **hash + extracted facts only**.
- **models.dev** — offering/pricing/capability/context evidence (MIT).
- **OpenRouter** — availability/pricing/context **evidence only**, never a benchmark authority.
- **Hugging Face** — the public `cais/hle` leaderboard API, with source-native evaluation
  configuration filenames retained as distinct result splits.
- **Hugging Face model cards** — a finite, consumer-inventory-driven set of official model-card API
  responses, pinned to source revisions and represented as hash + extracted facts only. Hub repository
  or weights-hosting metadata is document evidence, not an inference offering.
- **SWE-bench** `master/data/leaderboards.json` — official resolved-% (rows without logs+trajs → `claim`).
  Stored **hash + facts only** (the site repo is NOASSERTION-licensed).
- **Terminal-Bench 2.0** — official versioned leaderboard rows (Apache-2.0); compound submissions remain
  distinct. LiveCodeBench is deferred (stale).

See [`docs/eee-evaluation.md`](docs/eee-evaluation.md) for the Every Eval Ever qualification finding.

## Usage

```sh
uv venv --python 3.12 .venv && . .venv/bin/activate
uv pip install -e ".[dev]"

registry build --fixtures --out dist/   # deterministic, no network (PoC default)
registry build --live --out dist/ --global-concurrency 8  # best-effort live smoke against public sources

pytest            # determinism + conditional-fetch (200/304) + publish schema/checksum tests
ruff check . && pyright
```

The `--fixtures` build replays the saved responses in [`fixtures/`](fixtures/) byte-for-byte, so
identical inputs produce identical checksums. The Agent Foundry side consumes `dist/` via
`scripts/model-evidence-import.ts`, which verifies the manifest checksums and emits a **reviewable
diff** against `model-inventory.yaml` without auto-applying.

### Live-fetch limits

Live builds use a bounded worker pool (eight in-flight requests by default; adjust it with
`--global-concurrency`). Each connector declares a `FetchPolicy` at the transport boundary: a
shared provider/host key, per-source request concurrency, minimum interval, request timeout, source
budget, and finite exponential retry policy. Multiple endpoints from one provider should use the
same source key. Fetch completion never changes artifact ordering: parsed records and source
snapshots remain in declared connector order. Failed, timed-out, or exhausted sources become
`error`/`stale` snapshots; cached bytes are retained and are never treated as model deletion.

## Releases

Snapshots are published as **immutable, dated GitHub Releases** (`snapshot-YYYY-MM-DD`) by the
scheduled [`publish.yml`](.github/workflows/publish.yml) workflow — never reused, never overwritten.
Each release carries the full artifact set (`records.json`, `records.schema.json`, `manifest.json`,
`crosswalk.json`, and one Parquet per record type) plus **build-provenance attestation** (keyless,
SLSA via GitHub OIDC) and a keyless Sigstore signature for `manifest.json`. There is no mutable
`latest` release; consumers resolve the newest `snapshot-*` release client-side if needed.

Consumers should **pin a dated release** and validate `records.json` against that release's shipped
`records.schema.json`. Verify integrity with the checksums in `manifest.json`
(`artifacts[name].sha256`) and the build-provenance attestation:

```sh
gh release download snapshot-2026-07-29 --repo JTarasovic/model-evidence-registry
gh attestation verify records.json --repo JTarasovic/model-evidence-registry
```

The manifest's Sigstore bundle lets consumers verify it independently of GitHub's attestation API.
Download both `manifest.json` and `manifest.json.sigstore.json` from the same pinned release, then
verify the exact publishing workflow identity:

```sh
cosign verify-blob manifest.json \
  --bundle manifest.json.sigstore.json \
  --certificate-identity "https://github.com/JTarasovic/model-evidence-registry/.github/workflows/publish.yml@refs/heads/main" \
  --certificate-oidc-issuer "https://token.actions.githubusercontent.com"
```

After verification, check every downloaded release asset against the signed manifest's
`artifacts[name].sha256` values.

Versioning policy: [`docs/versioning.md`](docs/versioning.md). Contributing (incl. adding a
connector): [`CONTRIBUTING.md`](CONTRIBUTING.md).

## Status

Public, scheduled snapshots with build-provenance attestation and keyless Cosign manifest signing
(Phase 3). SBOM signing and broader provider/claim coverage are follow-ups (ADR 0028).
