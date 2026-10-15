"""Free public-web-search discovery channel; stores leads and dated event candidates.
Uses DuckDuckGo HTML results as a discovery index, not as a source of confirmed facts.
"""
from __future__ import annotations
import csv, datetime as dt, html, json, os, pathlib, re, time, urllib.parse, urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
POOL = ROOT / "data" / "artist_pool.csv"
VENUES = ROOT / "config" / "venue_sources.csv"
UA = "Mozilla/5.0 (compatible; RileyCoeGigFinder/2.2; public research)"
TIMEOUT = 15
MAX_BYTES = 1_500_000

class SearchParser(HTMLParser):
    """Tolerant parser for DuckDuckGo HTML/lite and Bing's public HTML results."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.results = []
        self._active = None
        self._capture = None
        self._in_h2 = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        classes = set((a.get("class") or "").split())
        href = a.get("href", "")
        # DDG full HTML and lite templates.
        if tag == "a" and ({"result__a", "result-link"} & classes):
            self._active = {"url": href, "title": "", "snippet": ""}
        # Bing result links are nested in h2.
        elif tag == "h2":
            self._in_h2 = True
        elif tag == "a" and self._in_h2:
            self._active = {"url": href, "title": "", "snippet": ""}
        if tag in ("a", "div", "p") and ({"result__snippet", "result-snippet", "b_caption"} & classes):
            self._capture = {"text": "", "depth": 1, "tag": tag}

    def handle_data(self, data):
        if self._active is not None:
            self._active["title"] += data
        if self._capture is not None:
            self._capture["text"] += data

    def handle_endtag(self, tag):
        if tag == "h2":
            self._in_h2 = False
        if tag == "a" and self._active is not None:
            title = " ".join(self._active["title"].split())
            url = self._active["url"]
            if title and url and url not in ("#", "/"):
                self.results.append({**self._active, "title": title})
            self._active = None
        if self._capture is not None and tag == self._capture["tag"]:
            snippet = " ".join(self._capture["text"].split())
            if snippet and self.results and not self.results[-1].get("snippet"):
                self.results[-1]["snippet"] = snippet
            self._capture = None


def _normalise_search_results(rows, provider):
    results = []
    for row in rows:
        target = html.unescape((row.get("url") or "").strip())
        # DDG redirect links may be relative or protocol-relative.
        if target.startswith("//"):
            target = "https:" + target
        if target.startswith("/"):
            target = urllib.parse.urljoin("https://html.duckduckgo.com", target)
        m = re.search(r"[?&]uddg=([^&]+)", target)
        if m:
            target = urllib.parse.unquote(m.group(1))
        if not target.startswith("http"):
            continue
        if any(host in urllib.parse.urlparse(target).netloc.lower()
               for host in ("duckduckgo.com", "bing.com")):
            continue
        if target not in {x["url"] for x in results}:
            results.append({"url": target, "title": " ".join(row.get("title", "").split()),
                            "snippet": " ".join(row.get("snippet", "").split()),
                            "search_provider": provider})
    return results


def _fetch_search_page(url):
    req = urllib.request.Request(url, headers={
        "User-Agent": UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-GB,en;q=0.9",
        "Cache-Control": "no-cache",
    })
    with urllib.request.urlopen(req, timeout=TIMEOUT) as response:
        status = getattr(response, "status", 200)
        body = response.read(MAX_BYTES).decode("utf-8", "replace")
    if status < 200 or status >= 300:
        raise RuntimeError(f"search provider HTTP {status}")
    low = body.lower()
    if any(marker in low for marker in ("captcha", "unusual traffic", "verify you are human", "automated queries")):
        raise RuntimeError("search provider returned a bot/challenge page")
    return body


def search_html(query):
    """Try multiple free HTML search frontends; never silently call an unreadable page 'zero results'."""
    providers = [
        ("DuckDuckGo HTML", "https://html.duckduckgo.com/html/?"),
        ("DuckDuckGo Lite", "https://lite.duckduckgo.com/lite/?"),
        ("Bing HTML", "https://www.bing.com/search?"),
    ]
    failures = []
    genuine_empty = False
    for provider, base in providers:
        try:
            url = base + urllib.parse.urlencode({"q": query})
            body = _fetch_search_page(url)
            parser = SearchParser()
            parser.feed(body)
            results = _normalise_search_results(parser.results, provider)
            if results:
                return results
            low = body.lower()
            if "no results found" in low or "there are no results" in low:
                genuine_empty = True
                continue
            failures.append(f"{provider}: HTTP succeeded but no recognised result links")
        except Exception as exc:
            failures.append(f"{provider}: {type(exc).__name__}: {str(exc)[:160]}")
    if genuine_empty and not failures:
        return []
    raise RuntimeError("All free search frontends failed to produce parseable results; " + " | ".join(failures))


def parse_date(text, start, end):
    text = text or ""
    patterns = [
        (r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b", "%Y-%m-%d"),
        (r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", "%d/%m/%Y"),
    ]
    for pattern, fmt in patterns:
        for m in re.finditer(pattern, text):
            raw = m.group(0)
            try: value = dt.datetime.strptime(raw, fmt).date()
            except ValueError: continue
            if start <= value <= end: return value.isoformat()
    # English dates, with or without year; infer year only within the requested window.
    month = r"(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:t(?:ember)?)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)"
    for m in re.finditer(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+" + month + r"(?:\s+(20\d{2}))?\b", text, re.I):
        day, mon, year = m.groups()
        year = int(year) if year else start.year
        try: value = dt.date(year, dt.datetime.strptime(mon[:3].title(), "%b").month, int(day))
        except ValueError: continue
        if start <= value <= end: return value.isoformat()
    return ""

def norm(text):
    return re.sub(r"[^a-z0-9]+", " ", (text or "").lower()).strip()

def main():
    start = dt.date.fromisoformat(os.environ.get("WINDOW_START") or dt.datetime.now(dt.timezone.utc).date().isoformat())
    end = dt.date.fromisoformat(os.environ.get("WINDOW_END") or (start + dt.timedelta(days=13)).isoformat())
    OUT.mkdir(parents=True, exist_ok=True)
    with POOL.open(encoding="utf-8-sig", newline="") as f: pool = list(csv.DictReader(f))
    with VENUES.open(encoding="utf-8-sig", newline="") as f: venues = list(csv.DictReader(f))
    artists = [r.get("artist", "").strip() for r in pool if r.get("artist") and r.get("status", "ACTIVE").upper() not in {"INACTIVE","RETIRED","REMOVED"}]
    # Discovery channel A: searches scoped to each venue/calendar and the date window.
    queries = []
    date_clause = f'"{start.isoformat()}" OR "{end.isoformat()}" OR "October 2026"'
    for v in venues:
        name = v.get("venue", "").strip()
        queries.append({"kind":"venue_search","venue":name,
          "query":f'"{name}" Newcastle (gig OR concert OR live music OR tickets) after:{start.isoformat()} before:{(end + dt.timedelta(days=1)).isoformat()}'})
    # Discovery channel B: reverse searches against batches of the artist pool, rather than 833 serial searches.
    batch_size = 12
    for i in range(0, len(artists), batch_size):
        batch = artists[i:i+batch_size]
        terms = " OR ".join('"' + a.replace('"','') + '"' for a in batch)
        queries.append({"kind":"artist_batch","artists":batch,
          "query":f'({terms}) (Newcastle OR Gateshead OR Gosforth OR Northumberland) (gig OR concert OR tour OR tickets) after:{start.isoformat()} before:{(end + dt.timedelta(days=1)).isoformat()}'})
    max_queries = max(1, int(os.environ.get("SEARCH_MAX_QUERIES", "90")))
    # Always retain all venue searches; use remaining budget for artist batches spread across the pool.
    venue_queries = [q for q in queries if q["kind"] == "venue_search"]
    artist_queries = [q for q in queries if q["kind"] == "artist_batch"]
    budget = max(0, max_queries - len(venue_queries))
    if budget < len(artist_queries) and budget:
        picks = sorted({round(i*(len(artist_queries)-1)/max(1,budget-1)) for i in range(budget)})
        artist_queries = [artist_queries[i] for i in picks]
    elif not budget: artist_queries = []
    selected = venue_queries + artist_queries
    leads, events, ledger = [], [], []
    for i, q in enumerate(selected, 1):
        row = {"query":q["query"],"kind":q["kind"],"status":"failed","result_count":0,"error":""}
        try:
            results = search_html(q["query"])
            row.update(status="checked", result_count=len(results))
            for result in results:
                lead = {**result,"query_kind":q["kind"],"query":q["query"],"query_venue":q.get("venue",""),
                        "query_artists":q.get("artists",[]),"retrieved_at":dt.datetime.now(dt.timezone.utc).isoformat()}
                leads.append(lead)
                combined = result["title"] + " " + result["snippet"]
                date = parse_date(combined, start, end)
                matched = [a for a in (q.get("artists", artists) if q["kind"]=="artist_batch" else artists)
                           if norm(a) and re.search(r"(?<![a-z0-9])"+re.escape(norm(a))+r"(?![a-z0-9])", norm(combined))]
                if date and matched:
                    venue = q.get("venue","")
                    if not venue:
                        venue = next((v.get("venue","") for v in venues if norm(v.get("venue","")) in norm(combined)), "")
                    if not venue: venue = "Unverified Newcastle-area venue"
                    events.append({"event_title":result["title"],"date":date,"artists":matched,"venue_room":venue,
                      "event_url":result["url"],"ticket_url":"","evidence_quote":result["snippet"] or result["title"],
                      "source_type":"public_web_search","confidence":"low","notes":"Search-engine discovery lead; verify original event listing before relying on it.",
                      "research_venue":venue if venue in {v.get("venue","") for v in venues} else "",
                      "research_status":"unverified_search_lead","source_page":result.get("search_provider", "Free web search"),
                      "retrieved_at":lead["retrieved_at"]})
        except Exception as exc:
            row["error"] = f"{type(exc).__name__}: {str(exc)[:240]}"
        ledger.append(row)
        print(f"[search {i}/{len(selected)}] {q['kind']}: {row['status']} ({row['result_count']} results)", flush=True)
        time.sleep(0.6)
    # Keep all search leads for audit; merge only event candidates with the existing collector's output.
    (OUT/"search_leads.json").write_text(json.dumps(leads,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"search_coverage.json").write_text(json.dumps({"window_start":start.isoformat(),"window_end":end.isoformat(),
       "query_count":len(selected),"queries_succeeded":sum(x["status"]=="checked" for x in ledger),
       "results_found":len(leads),"dated_artist_candidates":len(events),"queries":ledger},ensure_ascii=False,indent=2),encoding="utf-8")
    events_path = OUT/"research_events.json"
    existing = json.loads(events_path.read_text(encoding="utf-8")) if events_path.exists() else []
    keys = {(x.get("date"),norm(x.get("event_title")),x.get("event_url")) for x in existing}
    for event in events:
        key=(event["date"],norm(event["event_title"]),event["event_url"])
        if key not in keys:
            existing.append(event); keys.add(key)
    events_path.write_text(json.dumps(existing,ensure_ascii=False,indent=2),encoding="utf-8")
    print(f"Search discovery finished: {len(selected)} queries; {len(leads)} leads; {len(events)} dated artist candidates; merged events total {len(existing)}.",flush=True)
    # Query failures are surfaced in the ledger; the static collector may still provide results.
    return 0 if any(x["status"]=="checked" for x in ledger) else 1

if __name__ == "__main__": raise SystemExit(main())
