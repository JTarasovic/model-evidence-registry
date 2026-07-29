# Every Eval Ever (EEE) — evaluation-layer qualification finding

**Question (ADR 0028 §2.2, design §6, issue #168):** does
[`evaleval/every_eval_ever`](https://github.com/evaleval/every_eval_ever) qualify as the registry's
**evaluation layer** — or does the direct benchmark-maintainer fallback (SWE-bench + Terminal-Bench +
Hugging Face for open-weight models) stand for the PoC?

Assessed against four criteria: **license**, **datastore reachability**, **coding-benchmark
coverage**, and **agent/harness-metadata fidelity**.

## Finding (PoC): **do not depend on EEE as the evaluation layer yet — the direct-maintainer fallback stands.**

The fallback is already implemented (`connectors/swebench.py`, `connectors/terminal_bench.py`,
`connectors/huggingface.py`), so the PoC is **not blocked** either way. EEE remains the preferred
_future_ contribution target — an EEE-compatible adapter over an invented schema — once the gaps below
are closed and re-verified against a live datastore snapshot.

| Criterion                           | Assessment                                                                                                                                                                                                         | Verdict                                                                                                                        |
| ----------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------ |
| **License**                         | Project + `eval.schema.json` are MIT; the crowdsourced datastore rows carry **per-source** upstream terms.                                                                                                         | ⚠ Mixed — must be checked per row, exactly like SWE-bench's NOASSERTION content. Not a blanket "safe to redistribute."         |
| **Reachability**                    | A public Hugging Face "EEE Datastore" exists, reachable via `huggingface_hub` / the datasets API.                                                                                                                  | ✅ Reachable, but versioning/immutability of a given snapshot is unconfirmed — we need a pinnable revision to be reproducible. |
| **Coding-benchmark coverage**       | Converters exist for Inspect AI / HELM / lm-eval-harness; coverage of **coding/agentic** benchmarks (SWE-bench Verified/Pro, Terminal-Bench, LiveCodeBench) is **unverified** and appears sparse as of 2026-07-29. | ❌ Insufficient for our primary use case (coding-model routing) without direct-maintainer sources anyway.                      |
| **Agent/harness-metadata fidelity** | The schema models framework/task metadata, but preservation of **agent scaffold + reasoning-effort + pass@k + benchmark split** for agentic coding results is **not confirmed** end-to-end.                        | ❌ This is the exact metadata ADR 0028 forbids us to lose or fabricate; unconfirmed = cannot rely on it.                       |

## Why this is the safe call

ADR 0028's non-negotiable is that we **never manufacture equivalence** between benchmark variants or
across agent/reasoning settings, and never present a `claim` as a reproduced result. Adopting EEE
before confirming criteria 3–4 would risk importing under-specified rows as if they were fully
provenanced `evaluation_result`s. The direct-maintainer connectors give us fully-provenanced rows
today (with `benchmark_id`/`split`/`comparability_status` preserved and unverifiable rows demoted to
`claim`s — see `connectors/swebench.py`), so nothing is lost by deferring EEE.

## Re-check before Phase 3/4

1. Pin a specific EEE datastore revision and confirm it is immutable/reproducible.
2. Enumerate its coding/agentic-benchmark coverage against our target list.
3. Confirm a single instance round-trips **split + harness + agent scaffold + reasoning + pass@k**
   without loss, for at least SWE-bench Verified and Terminal-Bench.
4. If (1)–(3) hold, build an EEE-compatible **adapter** (map EEE rows → our `evaluation_result` /
   `claim` records) rather than inventing a competing schema — the ADR's stated preference.
