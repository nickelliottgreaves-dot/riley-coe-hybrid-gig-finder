"""Deterministic validation and artist matching for AI-researched venue events."""
from __future__ import annotations
import csv, datetime as dt, json, os, pathlib, re, sys, unicodedata

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
POOL = ROOT / "data" / "artist_pool.csv"
ALIASES = ROOT / "config" / "artist_aliases.csv"
VENUES = ROOT / "config" / "venue_sources.csv"

def norm(value: str) -> str:
    value = unicodedata.normalize("NFKD", value or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", value).strip()

def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))

def build_artist_index():
    pool = read_csv(POOL)
    aliases = read_csv(ALIASES) if ALIASES.exists() else []
    index = {}
    for row in pool:
        artist = (row.get("artist") or row.get("name") or "").strip()
        status = (row.get("status") or "ACTIVE").strip().upper()
        if artist and status not in {"INACTIVE", "RETIRED", "REMOVED"}:
            index.setdefault(norm(artist), artist)
    for row in aliases:
        canonical = (row.get("artist") or row.get("canonical_artist") or "").strip()
        alias = (row.get("alias") or row.get("artist_alias") or "").strip()
        if canonical and alias and norm(canonical) in index:
            index[norm(alias)] = index[norm(canonical)]
    return index

def match_names(event, index):
    found = set()
    # Use artist-by-artist whole normalized-name matching; avoid substring matches.
    haystacks = [norm(x) for x in event.get("artists", []) if isinstance(x, str)]
    title = norm(event.get("event_title", ""))
    haystacks.extend(haystacks_from_notes(event))
    for key, canonical in index.items():
        if not key:
            continue
        for hay in haystacks:
            if hay == key or re.search(r"(?<![a-z0-9])" + re.escape(key) + r"(?![a-z0-9])", hay):
                found.add(canonical)
                break
        if key == title:
            found.add(canonical)
    return sorted(found, key=str.casefold)

def haystacks_from_notes(event):
    # Titles are a weak source but can rescue a bill where artist fields are incomplete.
    return [norm(event.get("event_title", ""))]

def main():
    events_path = OUT / "research_events.json"
    if not events_path.exists():
        print(f"ERROR: missing {events_path}", file=sys.stderr); return 2
    events = json.loads(events_path.read_text(encoding="utf-8"))
    if not isinstance(events, list):
        print("ERROR: research_events.json must be an array", file=sys.stderr); return 2
    index = build_artist_index()
    venue_rows = read_csv(VENUES)
    allowed_venues = {r.get("venue", "").strip() for r in venue_rows}
    start = dt.date.fromisoformat(os.environ.get("WINDOW_START") or dt.datetime.now(dt.timezone.utc).date().isoformat())
    end = dt.date.fromisoformat(os.environ.get("WINDOW_END") or (start + dt.timedelta(days=13)).isoformat())
    checked, invalid, matches = [], [], []
    seen = set()
    for n, event in enumerate(events, 1):
        reasons = []
        try:
            date = dt.date.fromisoformat(str(event.get("date", "")))
            if not start <= date <= end: reasons.append("outside_requested_window")
        except ValueError:
            reasons.append("invalid_or_missing_date")
            date = None
        url = str(event.get("event_url", "")).strip()
        if not url.startswith("https://"): reasons.append("missing_https_event_url")
        if not str(event.get("event_title", "")).strip(): reasons.append("missing_event_title")
        venue = str(event.get("research_venue", "")).strip()
        if venue not in allowed_venues: reasons.append("venue_not_in_registry")
        if not str(event.get("evidence_quote", "")).strip(): reasons.append("missing_evidence_quote")
        key = (date.isoformat() if date else "", norm(event.get("event_title", "")), norm(venue))
        duplicate = key in seen
        seen.add(key)
        matched = match_names(event, index)
        row = dict(event)
        row["matched_artists"] = matched
        row["validation_status"] = "invalid" if reasons else ("duplicate_candidate" if duplicate else "valid_candidate")
        row["validation_reasons"] = reasons
        checked.append(row)
        if reasons: invalid.append(row)
        if matched and not reasons and not duplicate:
            matches.append(row)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "validated_events.json").write_text(json.dumps(checked, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "artist_matches.json").write_text(json.dumps(matches, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "validation_summary.json").write_text(json.dumps({
        "window_start": start.isoformat(), "window_end": end.isoformat(),
        "artist_pool_entries": len(index), "research_event_count": len(events),
        "valid_candidate_count": sum(not x["validation_reasons"] for x in checked),
        "invalid_candidate_count": len(invalid), "duplicate_candidate_count": sum(x["validation_status"]=="duplicate_candidate" for x in checked),
        "artist_match_count": len(matches),
        "matches_are_candidates_not_final_confirmation": True
    }, indent=2), encoding="utf-8")
    print(f"Deterministic matching: {len(index)} artist names/aliases; {len(events)} events; {len(matches)} candidate matches; {len(invalid)} invalid.")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
