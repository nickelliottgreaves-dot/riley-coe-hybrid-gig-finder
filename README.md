# Riley & Coe Hybrid Gig Finder

A scheduled, best-effort gig-discovery workflow for the maintained Riley & Coe artist pool and 18 configured Newcastle-area venue sources.

## Run it

- GitHub Actions workflow: **Hybrid gig finder v2**.
- Schedule: Mondays at 08:00 UTC; manual runs are available from **Actions → Hybrid gig finder v2 → Run workflow**.
- Runtime: Python 3.12. No paid model API or API key is used.
- Tests: `python -m unittest discover -s tests -v`.

The workflow collects accessible public venue pages, runs free public web-search discovery, then validates candidates deterministically. It also checks RadioFiles first and BBC Sounds second for episode evidence. Outputs are uploaded as a run-specific Actions artifact for 90 days.

## Important limitations

This is **not an exhaustive or guaranteed gig listing**. Public venue pages may be JavaScript-rendered, paginated, blocked, or hosted by third-party ticketing services. Search results can omit events or contain stale snippets. The run's coverage ledger and evidence files must be consulted; a successful workflow status means the code completed, not that every source was fully covered.

A previous baseline run completed successfully but reported all 18 configured venue sources as partial/failed, 22 research events, and zero validated artist matches. Treat that as evidence the collection pipeline ran, **not** as evidence that there were no matching gigs. Check the latest run artifact before relying on results.

Episode refresh is also conservative and best-effort. It scans discovered episode links, extracts possible artist names, and emits proposals only when its parser considers a tracklist complete. It does not yet reliably prove that every discovered tracklist is complete, does not robustly track only episodes newly published since the previous run, and does **not** automatically change the approved artist pool. Review episode proposals against source pages before approving additions.

## Output and trust model

Artifacts in `artifacts/current` include reports, event candidates, match files, episode refresh evidence/proposals, and per-source coverage. Confirmed matches require deterministic checks including date window, HTTPS event URL, registered venue identity and supporting evidence. Search leads whose venue identity is not verified are kept separately from validated matches.

- `artist_matches.csv/json`: validated candidates; not a guarantee that an event is still on sale.
- `artist_discovery_leads.csv/json`: useful leads that did not pass all venue-validation checks; verify them manually.
- `episode_artist_proposals.csv`: proposed artist additions, not approved pool changes.
- `episode_refresh_coverage.csv` and the gig-source coverage ledger: inspect before interpreting an empty result.
- `report.md`: run summary and caveats.

The authoritative pool at the start of this build contained 833 records. The workflow preserves it and does not silently add or delete artists. Keep dated, independently verified backups if changing the pool manually.

## Configured venues

The source registry contains 18 entries, including The Cluny and Cluny 2 as separate room identities. Coverage is reported per configured source; it must not be described as complete merely because a page fetch succeeded.

## Privacy and security

No credentials are required by this workflow. Never commit access tokens or secrets. The workflow does not call this ChatGPT conversation and does not use paid AI research.
