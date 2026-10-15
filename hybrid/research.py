#!/usr/bin/env python3
"""Venue-by-venue web research using the OpenAI Responses API.

This is intentionally a research stage, not a scraper. It makes one explicit
web-search-enabled model request per configured venue, preserves raw responses,
and marks coverage honestly. It never silently substitutes scraping when the
API key is absent.
"""
from __future__ import annotations

import csv
import datetime as dt
import json
import os
import pathlib
import sys
import time
import urllib.error
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENUES = ROOT / "config" / "venue_sources.csv"
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
API_URL = "https://api.openai.com/v1/responses"
MODEL = os.environ.get("OPENAI_MODEL", "gpt-4.1-mini")


def request_json(url: str, payload: dict, api_key: str) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url, data=body, method="POST",
        headers={"Authorization": f"Bearer {api_key}",
                 "Content-Type": "application/json"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=180) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:2000]
            if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"Responses API HTTP {exc.code}: {detail}") from exc
        except (TimeoutError, urllib.error.URLError) as exc:
            if attempt < 2:
                time.sleep(3 * (attempt + 1))
                continue
            raise RuntimeError(f"Responses API request failed: {exc}") from exc
    raise RuntimeError("Responses API retries exhausted")


def extract_output_text(response: dict) -> str:
    chunks = []
    for item in response.get("output", []):
        if item.get("type") != "message":
            continue
        for part in item.get("content", []):
            if part.get("type") == "output_text" and part.get("text"):
                chunks.append(part["text"])
    if not chunks:
        raise ValueError("API response contained no output_text")
    return "\n".join(chunks)


def parse_json_text(text: str) -> dict:
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("\n", 1)[1].rsplit("```", 1)[0].strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start < 0 or end < start:
        raise ValueError("Model output did not contain a JSON object")
    return json.loads(cleaned[start:end + 1])


def build_prompt(venue: dict, start: str, end: str) -> str:
    return f"""Research live music and gig events in Newcastle/Gateshead, UK, at this venue for the inclusive dates {start} through {end}.
Venue identity: {venue['venue']}
Official starting source: {venue['source_url']}
Venue-specific guidance: {venue.get('notes', '')}

Use web search actively. Inspect the official venue/promoter calendar and individual event pages, and search ticketing platforms and reputable local listings to find events the official page may omit. Follow relevant event/ticket links. Include announced support acts and multi-artist bills. Do not invent dates, billing, or URLs. Dates must fall inside the requested window. The Cluny and Cluny 2 are distinct room identities even though they share a calendar; only assign a room when evidence supports it. The Glasshouse/Sage Two similarly need room-specific classification. Riverside is a status-check row; do not infer events from absence.

Return exactly one JSON object, no markdown, with this shape:
{{
 "venue": "{venue['venue']}",
 "window_start": "{start}",
 "window_end": "{end}",
 "coverage_status": "complete|partial|failed",
 "sources_checked": [{{"url":"https://...","kind":"official|ticketing|local_listing","result":"checked|blocked|not_found","note":"short factual note"}}],
 "events": [
  {{"event_title":"...", "date":"YYYY-MM-DD", "artists":["..."], "venue_room":"...",
    "event_url":"https://...", "ticket_url":"https://... or empty",
    "evidence_quote":"short text supporting date/billing", "source_type":"official|ticketing|local_listing",
    "confidence":"high|medium|low", "notes":"..." }}
 ],
 "limitations": ["specific access or coverage limitation, if any"]
}}
A coverage_status of complete requires a meaningful inspection of the venue's dated listings and linked event pages for the window; otherwise use partial. Use failed only if research could not meaningfully proceed. An empty events list is valid only if the sources checked support that result. Keep sources and event claims evidence-backed. Do not claim to have checked a page you did not inspect."""


def main() -> int:
    key = os.environ.get("OPENAI_API_KEY")
    if not key:
        print("ERROR: OPENAI_API_KEY is required. No scraping-only fallback is allowed.", file=sys.stderr)
        return 2
    today = dt.datetime.now(dt.timezone.utc).date()
    start = os.environ.get("WINDOW_START", today.isoformat())
    end = os.environ.get("WINDOW_END", (today + dt.timedelta(days=13)).isoformat())
    if dt.date.fromisoformat(end) < dt.date.fromisoformat(start):
        raise ValueError("WINDOW_END must not precede WINDOW_START")
    OUT.mkdir(parents=True, exist_ok=True)
    with VENUES.open(encoding="utf-8-sig", newline="") as f:
        venues = list(csv.DictReader(f))
    if not venues:
        raise RuntimeError(f"No venues loaded from {VENUES}")
    ledger = []
    all_events = []
    raw_dir = OUT / "raw_research"
    raw_dir.mkdir(parents=True, exist_ok=True)
    for i, venue in enumerate(venues, 1):
        name = venue.get("venue", "").strip()
        if not name or not venue.get("source_url", "").startswith("http"):
            ledger.append({"venue": name, "status": "failed", "events": 0,
                           "error": "Missing venue name or valid source URL"})
            continue
        print(f"[{i}/{len(venues)}] Researching {name}", flush=True)
        try:
            payload = {
                "model": MODEL,
                "tools": [{"type": "web_search"}],
                "input": build_prompt(venue, start, end),
                "max_output_tokens": 7000
            }
            raw = request_json(API_URL, payload, key)
            (raw_dir / f"{i:02d}-response.json").write_text(
                json.dumps(raw, ensure_ascii=False, indent=2), encoding="utf-8")
            result = parse_json_text(extract_output_text(raw))
            if result.get("venue") != name:
                raise ValueError(f"Venue identity mismatch: {result.get('venue')!r}")
            events = result.get("events", [])
            if not isinstance(events, list):
                raise ValueError("events must be a JSON array")
            for event in events:
                event["research_venue"] = name
                event["research_status"] = "candidate_needs_deterministic_validation"
            all_events.extend(events)
            ledger.append({
                "venue": name,
                "status": result.get("coverage_status", "partial"),
                "events": len(events),
                "sources_checked": result.get("sources_checked", []),
                "limitations": result.get("limitations", []),
                "raw_response": f"raw_research/{i:02d}-response.json"
            })
            (raw_dir / f"{i:02d}-parsed.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception as exc:
            ledger.append({"venue": name, "status": "failed", "events": 0,
                           "error": f"{type(exc).__name__}: {exc}"})
            print(f"  FAILED: {exc}", file=sys.stderr, flush=True)
    (OUT / "research_events.json").write_text(
        json.dumps(all_events, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "coverage_ledger.json").write_text(
        json.dumps({"window_start": start, "window_end": end,
                    "venue_count": len(venues), "venues": ledger},
                   ensure_ascii=False, indent=2), encoding="utf-8")
    failed = sum(row["status"] == "failed" for row in ledger)
    partial = sum(row["status"] != "complete" for row in ledger)
    print(f"Research finished: {len(all_events)} candidate events; "
          f"{len(venues)-failed}/{len(venues)} venue requests returned; "
          f"{partial}/{len(venues)} venues not marked complete.")
    # Partial coverage is reported, never falsely promoted to complete.
    return 0 if failed == 0 and partial == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
