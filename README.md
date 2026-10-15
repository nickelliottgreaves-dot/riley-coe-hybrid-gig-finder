# Riley & Coe Hybrid Gig Finder

Independent v2 project. It uses web-search-enabled AI research for each configured venue, then deterministic Python validation and matching against the persistent artist pool. A candidate is not represented as confirmed unless evidence supports it; partial/failed venue coverage remains visible in the coverage ledger.

## Run

Requires Python 3.12. No paid API key or external API billing is required. Run `python -m unittest discover -s tests`, then run `python -m hybrid.research` followed by `python -m hybrid.match`. Artifacts are written to `artifacts/current` including `report.md`, `artist_matches.csv`, JSON evidence, and a venue coverage ledger.

The weekly schedule is Monday 08:00 UTC. Use Actions → Hybrid gig finder v2 → Run workflow for a manual run. Never put API keys in source files.

## Coverage integrity

The research step records per-venue status, sources, limitations and raw API responses. The matcher validates event dates, HTTPS event links, venue registry identity, evidence text, duplicates, and artist-pool matches. Model-discovered events are candidates for review, not guaranteed booking/attendance facts.
