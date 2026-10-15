# Riley & Coe Hybrid Gig Finder — Operational Contract

This document describes the current implementation honestly. It supersedes the earlier design text that assumed a paid model API/web-search stage.

## Fixed requirements

- Keep the approved artist pool in `data/artist_pool.csv`; current baseline is 833 records (content blob SHA at baseline: `f27ec3e0501dc12d90849830d1724dfdbe310469`).
- Use the configured 18 venue source rows. Keep The Cluny and Cluny 2 as separate venue/room identities.
- Search an inclusive 14-day window.
- Schedule weekly for Monday 08:00 UTC, with manual dispatch available.
- Candidate evidence should include date, venue/room, artist/billing role where available, source URL, retrieval time, evidence text and validation status.
- Do not call source coverage exhaustive when pages, pagination, ticket links or detail pages could not be checked.
- Do not automatically mutate the authoritative artist pool.
- Do not use Mixcloud.
- Do not use a paid model API or require a model API key.

## Current pipeline

1. Refresh episode evidence from RadioFiles, with BBC Sounds as a secondary source.
2. Extract artist proposals conservatively; the approved pool remains unchanged.
3. Fetch accessible public venue pages using the standard-library collector.
4. Discover additional leads using free public HTML web search, within a bounded query budget.
5. Validate and match candidates using deterministic Python rules.
6. Upload per-run evidence, match files, and source-coverage ledgers as a GitHub Actions artifact.

## Acceptance and interpretation

A green Actions run means the workflow steps completed; it does **not** prove completeness of source coverage or that a zero-match result means there are no gigs. Public sources can block requests, render content with JavaScript, paginate results, or rely on external ticketing platforms. Search is best-effort and may miss events.

The collector's known baseline was weak: a completed run reported 18/18 venue sources partial/failed, 22 candidate research events and zero validated artist matches. Therefore the implementation must not be represented as a fully validated gig-finding service until a real run demonstrates materially improved coverage and useful verified matches. Always inspect the latest artifact and distinguish:
- validated matches,
- unverified discovery leads,
- failed/partial venue coverage,
- episode tracklist proposals.

## Episode refresh limitations

The current episode parser scans a limited number of discovered RadioFiles/BBC links and uses HTML text/class heuristics. Its completeness threshold is a heuristic, not proof of a complete tracklist. It does not yet reliably maintain a last-seen episode cursor and does not automatically append approved artists. Proposals require manual source verification and approval. Do not claim automatic cumulative pool maintenance is complete.

## Workflow and artifact retention

The workflow is defined in `.github/workflows/hybrid-gig-finder.yml`, with a Monday 08:00 UTC schedule and a 45-minute job timeout. Artifacts are configured for 90-day retention. The current workflow uses GitHub-hosted Actions and public unauthenticated page/search requests. No paid API secret is configured or expected.

## Bounded build plan

1. Establish isolated baseline and preserve artist/venue data.
2. Implement free multi-source gig discovery.
3. Add conservative episode evidence and unverified-lead separation.
4. Add unit/integration tests and run the pipeline.
5. Finalize documentation and report verified operating status and remaining limitations.

This is the final step of the bounded plan; do not extend it with an open-ended sixth phase.
