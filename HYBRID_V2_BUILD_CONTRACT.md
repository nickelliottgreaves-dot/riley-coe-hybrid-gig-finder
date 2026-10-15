# Riley & Coe Hybrid Gig Finder v2 — Build Contract

This is a clean, isolated rebuild on branch `hybrid-gig-finder-v2`. It does not merge or depend on PR #9 or the old gig-finder workflow.

## Fixed requirements
- Use the preserved authoritative `data/artist_pool.csv` (833 records; SHA-256/content blob SHA `f27ec3e0501dc12d90849830d1724dfdbe310469`).
- Use `config/venue_sources.csv` and `config/required_venues.csv`: 18 configured source rows, including distinct Cluny and Cluny 2 identities sharing a calendar.
- Research 14 inclusive local calendar dates, starting today.
- Weekly schedule target: Monday 08:00 UTC.
- Candidate records must carry event date, venue/room, artist billing/role, source URL, retrieval time, evidence snippet and verification status.
- Do not claim exhaustive coverage if a source, calendar page, pagination path or event detail could not be checked.
- Artist-pool changes are review-only; never mutate the authoritative pool automatically.

## Agreed architecture
1. GitHub stores the authoritative artist pool, aliases, venue registry, historical run outputs and evidence.
2. The research stage is an actual model/API call with web-search capability. It receives the artist pool and venue registry and investigates official venue calendars, ticketing pages and local event listings; it returns structured event candidates and per-source coverage evidence.
3. Deterministic Python code validates the model response, normalizes names/dates/rooms, matches candidates against the complete artist pool, deduplicates events and writes CSV/JSON reports.
4. GitHub Actions schedules and runs the process, then preserves artifacts. The model is not simulated by Python scraping, and Python does not claim the model ran unless an API response is recorded in the run evidence.

## API and deployment constraint
GitHub Actions cannot call this ChatGPT conversation directly. Automated weekly AI research requires a configured model API credential stored as a GitHub Actions secret (for example `OPENAI_API_KEY`). Never commit credentials. The implementation must fail clearly and safely if the secret is absent; it must not silently fall back to claiming that Python scraping is equivalent to AI research.

## Five-proceed acceptance gate
1. Clean isolated scaffold and preserve the agreed database/registry.
2. Implement the AI web-research stage and schema/coverage contract.
3. Implement deterministic matching, deduplication, report generation and tests.
4. Run a real end-to-end research test; inspect actual results and fix integration defects.
5. Verify operational schedule, secret/configuration status, artifact outputs and document any user action that cannot be performed by the available GitHub integration.

No merge to the existing default branch. Do not report completion until the actual AI stage has run successfully and the report artifact has been inspected. If a new repository is needed for an independent default-branch schedule, call this out explicitly rather than pretending a feature branch's cron is active.
