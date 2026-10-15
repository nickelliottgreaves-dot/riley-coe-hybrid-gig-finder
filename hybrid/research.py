"""No-paid-API public venue collector with bounded event-detail crawling."""
from __future__ import annotations
import csv, datetime as dt, html, json, os, pathlib, re, sys, time, urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENUES = ROOT / "config" / "venue_sources.csv"
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
UA = "Mozilla/5.0 (compatible; RileyCoeGigFinder/2.1; public-calendar-check)"
TIMEOUT, MAX_BYTES, MAX_DETAIL_PAGES = 20, 3_000_000, 8

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.jsonld = [], []
        self._anchor = None
        self._script_type, self._script_data = "", []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag.lower() == "a" and a.get("href"):
            self._anchor = {"href": a["href"], "text": ""}
            self.links.append(self._anchor)
        if tag.lower() == "script":
            self._script_type, self._script_data = a.get("type", "").lower(), []
    def handle_data(self, data):
        if self._script_type:
            self._script_data.append(data)
        elif self._anchor is not None:
            self._anchor["text"] += data
    def handle_endtag(self, tag):
        if tag.lower() == "a":
            self._anchor = None
        if tag.lower() == "script":
            if "ld+json" in self._script_type:
                self.jsonld.append("".join(self._script_data))
            self._script_type, self._script_data = "", []

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        data = r.read(MAX_BYTES + 1)[:MAX_BYTES]
        return r.geturl(), data.decode(r.headers.get_content_charset() or "utf-8", errors="replace"), r.status

def absolute(base, raw):
    result = urljoin(base, html.unescape((raw or "").strip()))
    return result if urlparse(result).scheme in ("http", "https") else ""

def walk_jsonld(obj):
    if isinstance(obj, dict):
        typ = obj.get("@type", [])
        if isinstance(typ, str): typ = [typ]
        if any(str(t).lower() in {"event", "music event", "festival"} for t in typ):
            yield obj
        for value in obj.values(): yield from walk_jsonld(value)
    elif isinstance(obj, list):
        for value in obj: yield from walk_jsonld(value)

def textval(value):
    if isinstance(value, dict): return str(value.get("name") or value.get("url") or "")
    if isinstance(value, list): return "; ".join(filter(None, (textval(x) for x in value)))
    return str(value or "")

def extract_events(parser, venue, page_url, start, end):
    events = []
    for blob in parser.jsonld:
        try: parsed = json.loads(blob)
        except (ValueError, TypeError): continue
        for obj in walk_jsonld(parsed):
            try: date = dt.date.fromisoformat(str(obj.get("startDate", ""))[:10])
            except ValueError: continue
            if not start <= date <= end: continue
            title = textval(obj.get("name", "")).strip()
            event_url = absolute(page_url, str(obj.get("url") or page_url))
            location = obj.get("location", {})
            room = textval(location.get("name", "")) if isinstance(location, dict) else textval(location)
            performers = obj.get("performer", obj.get("performers", []))
            if not isinstance(performers, list): performers = [performers]
            offers = obj.get("offers", {})
            if isinstance(offers, list): offers = offers[0] if offers else {}
            ticket = absolute(page_url, str(offers.get("url") or "")) if isinstance(offers, dict) else ""
            if title and event_url:
                events.append({"event_title": title, "date": date.isoformat(),
                  "artists": [textval(x).strip() for x in performers if textval(x).strip()],
                  "venue_room": room or venue, "event_url": event_url, "ticket_url": ticket,
                  "evidence_quote": "JSON-LD Event metadata extracted from public page: " + title,
                  "source_type": "official", "confidence": "medium",
                  "notes": "Structured metadata; verify event page and support bill",
                  "research_venue": venue, "research_status": "public_source_candidate",
                  "source_page": page_url})
    return events

def relevant_links(parser, base):
    out, seen = [], set()
    for link in parser.links:
        url = absolute(base, link["href"])
        label = " ".join(link["text"].split())
        if not url or url in seen or urlparse(url).scheme != "https": continue
        # Follow links that look like event/detail/calendar pages, not arbitrary site links.
        if re.search(r"(event|gig|show|concert|ticket|what.?s.?on|calendar|listing|live-music|20[0-9]{2}[-/][0-9]{1,2})", url + " " + label, re.I):
            seen.add(url)
            out.append({"url": url, "label": label[:180]})
    return out

def main():
    start = dt.date.fromisoformat(os.environ.get("WINDOW_START") or dt.datetime.now(dt.timezone.utc).date().isoformat())
    end = dt.date.fromisoformat(os.environ.get("WINDOW_END") or (start + dt.timedelta(days=13)).isoformat())
    if end < start: raise ValueError("WINDOW_END must be on or after WINDOW_START")
    OUT.mkdir(parents=True, exist_ok=True); rawdir = OUT / "raw_pages"; rawdir.mkdir(exist_ok=True)
    with VENUES.open(encoding="utf-8-sig", newline="") as f: venues = list(csv.DictReader(f))
    all_events, ledger = [], []
    for i, v in enumerate(venues, 1):
        name, url = v.get("venue", "").strip(), v.get("source_url", "").strip()
        row = {"venue": name, "url": url, "status": "failed", "events": 0, "sources_checked": [], "limitations": []}
        if not name or not url.startswith("https://"):
            row["limitations"].append("Missing venue name or HTTPS source URL"); ledger.append(row); continue
        print(f"[{i}/{len(venues)}] Fetching {name}: {url}", flush=True)
        try:
            final, body, status = fetch(url)
            parser = PageParser(); parser.feed(body)
            (rawdir / f"{i:02d}-main.html").write_text(body, encoding="utf-8")
            found = extract_events(parser, name, final, start, end)
            links = relevant_links(parser, final)
            row["sources_checked"].append({"url": final, "kind": "configured_venue_page", "result": "checked", "http_status": status, "chars": len(body)})
            # Crawl a bounded number of likely detail pages. Prefer same host to avoid unrelated sites.
            host = urlparse(final).netloc.lower()
            candidates = [x for x in links if urlparse(x["url"]).netloc.lower() == host]
            candidates = candidates[:MAX_DETAIL_PAGES]
            detail_checked = []
            for j, link in enumerate(candidates, 1):
                try:
                    detail_url, detail_body, detail_status = fetch(link["url"])
                    detail_parser = PageParser(); detail_parser.feed(detail_body)
                    (rawdir / f"{i:02d}-detail-{j:02d}.html").write_text(detail_body, encoding="utf-8")
                    detail_events = extract_events(detail_parser, name, detail_url, start, end)
                    found.extend(detail_events)
                    detail_checked.append({"url": detail_url, "kind": "same_host_event_detail", "result": "checked", "http_status": detail_status, "events": len(detail_events)})
                except Exception as exc:
                    detail_checked.append({"url": link["url"], "kind": "same_host_event_detail", "result": "failed", "error": f"{type(exc).__name__}: {str(exc)[:180]}"})
                time.sleep(0.15)
            # Preserve ticketing links as research leads, without claiming they were checked.
            row["candidate_links"] = links[:100]
            row["sources_checked"].extend(detail_checked)
            # Deduplicate same event emitted by calendar and detail page.
            unique = {}
            for event in found:
                key = (event["date"], re.sub(r"[^a-z0-9]+", " ", event["event_title"].lower()).strip(), event["event_url"])
                unique.setdefault(key, event)
            found = list(unique.values())
            row["events"] = len(found); row["status"] = "partial"
            row["limitations"].append("Bounded static HTML/JSON-LD crawl only; JavaScript calendars, pagination, external ticketing pages and independent local listings may be missed.")
            if not parser.jsonld: row["limitations"].append("No JSON-LD scripts on the configured page.")
            if links and not candidates: row["limitations"].append("Relevant links were found but none were crawled because they were external or outside the bounded crawl.")
            all_events.extend(found)
        except Exception as exc:
            row["limitations"].append(f"{type(exc).__name__}: {str(exc)[:400]}")
            print(f"  FAILED: {row['limitations'][-1]}", file=sys.stderr, flush=True)
        ledger.append(row); time.sleep(0.25)
    (OUT / "research_events.json").write_text(json.dumps(all_events, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "coverage_ledger.json").write_text(json.dumps({"window_start": start.isoformat(), "window_end": end.isoformat(), "venue_count": len(venues), "events_found": len(all_events), "venues": ledger}, ensure_ascii=False, indent=2), encoding="utf-8")
    failed = sum(x["status"] == "failed" for x in ledger)
    print(f"Collection finished: {len(all_events)} event candidates; {len(venues)-failed}/{len(venues)} configured pages fetched; all successful venues remain partial pending independent verification.")
    return 0 if failed < len(venues) else 1

if __name__ == "__main__": raise SystemExit(main())
