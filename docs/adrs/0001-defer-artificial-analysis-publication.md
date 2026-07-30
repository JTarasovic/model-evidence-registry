# ADR 0001: Defer Artificial Analysis publication

- Status: Accepted
- Date: 2026-07-30
- Decision source: [Issue #3](https://github.com/JTarasovic/model-evidence-registry/issues/3)

## Context

The registry publishes a public GitHub Release artifact. Including data from an external source in
that artifact is redistribution, even when the stored rows contain only extracted facts rather than
the source response.

Artificial Analysis is a third-party aggregated source. Its Data API terms reviewed on 2026-07-29
state that the Free tier permits internal use only and no redistribution; the Pro tier has restricted
external use; and commercial redistribution with attribution requires a Commercial license. The
terms also require attribution and direct users seeking redistribution rights to contact Artificial
Analysis.

The existing connector is intentionally credentialed and classified as `THIRD_PARTY_REPORT`. It is
not a primary or independently reproduced evaluation source, so its additional signal does not
justify a separate private build path or licensing risk.

## Decision

Do not publish Artificial Analysis data in any public registry artifact. Keep
`ArtificialAnalysisConnector` out of `default_connectors()` and retain its API-key gate in
`credentialed_connectors()`.

Do not enable the connector in the scheduled public publishing workflow. A private build is also
out of scope: it would add key management and a second pipeline while leaving the use of the data in
Agent Foundry's committed inventory legally uncertain.

## Consequences

- Public fixture and live builds remain free of Artificial Analysis records.
- The connector, fixture, and parser tests remain available for a future licensed integration.
- No schema or artifact change is required for this decision.
- The registry continues to prefer sources with redistribution terms compatible with its public,
  versioned artifacts.

## Revisit criteria

Revisit this decision only after obtaining a Commercial license or a written agreement that clearly
permits onward redistribution in the registry's public, open artifact. Before enabling publication,
confirm the agreement's scope and add the required Artificial Analysis attribution to the records or
manifest, then add the API key only to the appropriate publishing workflow secrets.

## References

- [Issue #3](https://github.com/JTarasovic/model-evidence-registry/issues/3)
- [Artificial Analysis Data API documentation](https://artificialanalysis.ai/data-api/docs)
- [Artificial Analysis Data API](https://artificialanalysis.ai/data-api)
- [Artificial Analysis documentation](https://artificialanalysis.ai/documentation)
