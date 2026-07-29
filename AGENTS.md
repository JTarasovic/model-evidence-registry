# Repository Guidelines

## Project Structure & Module Organization

Production code lives in `src/registry/`. The CLI is `cli.py`; the build, fetch,
normalization, schema, manifest, and publishing pipeline are separate modules.
Source-specific parsers belong in `src/registry/connectors/`, with one connector per
source. Deterministic source responses are saved in `fixtures/`; corresponding tests
live in `tests/`. Versioning and evaluation decisions are documented in `docs/`.

Keep the boundary invariant: this repository exchanges only versioned artifacts with
Agent Foundry. Do not import Agent Foundry code or make changes that require it as a
runtime dependency.

## Build, Test, and Development Commands

Install the Python 3.12+ development environment with:

```sh
python -m pip install -e ".[dev]"
```

- `registry build --fixtures --out dist/` builds the deterministic, offline artifact.
- `registry build --live --out dist/` fetches supported public sources best-effort.
- `pytest` runs the fixture-based test suite.
- `ruff check .` checks lint rules; `pyright` performs standard type checking.

Run all three checks before opening a pull request. CI runs them on every push and PR.

## Coding Style & Naming Conventions

Use Python 3.12, four-space indentation, and a 120-character line limit. Ruff enforces
`E`, `F`, `I`, `UP`, and `B` rules; keep imports ordered and type annotations accurate.
Use `snake_case` for functions, modules, and fixtures; `PascalCase` for classes; name
tests `test_<behavior>.py` or `test_<behavior>()`.

Connectors must be pure `bytes -> records` parsers: inject `observed_at`, never call
`datetime.now()`, and preserve source-native identifiers exactly. Register public
connectors in `default_connectors()` and add a saved fixture and deterministic test.

## Testing & Schema Changes

Test both parsed records and reproducibility. Do not merge model identifiers or claim
equivalence across differing benchmarks, harnesses, or reasoning settings. Record-shape
changes must bump `SCHEMA_VERSION` in `src/registry/schema.py` according to
`docs/versioning.md` and regenerate the shipped schema through the build.

## Commits & Pull Requests

Follow the existing Conventional Commit style, such as `feat: add source connector` or
`fix(ci): recreate latest release`. Keep commits focused. PRs should explain the
evidence/source impact, link the relevant issue, include fixture and test updates, and
note licensing, rate-limit, or redistribution considerations for new sources.
