"""Refresh Riley & Coe episode tracklist evidence from RadioFiles and BBC Sounds.
Conservative by design: never mutate the approved artist pool automatically. Only
complete, parsed tracklists can create proposed additions; all proposals are reviewable.
"""
from __future__ import annotations
import csv, datetime as dt, html, json, os, pathlib, re, time, urllib.request
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

ROOT = pathlib.Path(__file__).resolve().parents[1]
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
POOL = ROOT / "data" / "artist_pool.csv"
RADIOFILES = "https://radiofiles.io/show/riley-coe"
BBC_PROGRAMME = "https://www.bbc.co.uk/programmes/m001mf2c"
UA = "Mozilla/5.0 (compatible; RileyCoeEpisodeAudit/1.0)"
TIMEOUT, MAX_BYTES, MAX_EPISODES = 18, 2_000_000, 24

class Page(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links, self.text, self._a, self._script, self._script_data = [], [], None, False, []
    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "a" and a.get("href"):
            self._a = {"href": a["href"], "text": ""}
            self.links.append(self._a)
        if tag == "script" and "ld+json" in (a.get("type") or "").lower():
            self._script, self._script_data = True, []
    def handle_data(self, data):
        if self._script: self._script_data.append(data)
        else:
            self.text.append(data)
            if self._a is not None: self._a["text"] += data
    def handle_endtag(self, tag):
        if tag == "a": self._a = None
        if tag == "script" and self._script: self._script = False

def fetch(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        body = r.read(MAX_BYTES).decode(r.headers.get_content_charset() or "utf-8", "replace")
        return r.geturl(), body, r.status

def clean(s):
    return re.sub(r"\s+", " ", html.unescape(s or "")).strip()

def episode_links(base, body, source):
    p = Page(); p.feed(body)
    out = []
    for link in p.links:
        url = urljoin(base, link["href"].strip())
        label = clean(link["text"])
        if source == "radiofiles":
            valid = urlparse(url).netloc.endswith("radiofiles.io") and "/show/riley-coe/" in url and url.rstrip("/") != RADIOFILES
        else:
            valid = urlparse(url).netloc.endswith("bbc.co.uk") and "/sounds/play/" in url or urlparse(url).netloc.endswith("bbc.com") and "/sounds/play/" in url
        if valid and url not in [x["url"] for x in out]:
            out.append({"url":url, "title":label, "source":source})
    return out

def parse_tracklist(body):
    """Extract only explicit artist labels from track rows; otherwise fail closed."""
    p = Page(); p.feed(body)
    text = clean(" ".join(p.text))
    # RadioFiles page markup exposes track names and artists as adjacent repeated text;
    # BBC programme pages expose "Music Played" blocks with artist headings.
    artists = []
    patterns = [
        r"(?m)(?:Artist|artist)\s*[:\n]\s*([^\n]{2,100})",
        r"(?m)(?:by|By)\s+([^\n]{2,100})",
    ]
    for pattern in patterns:
        for m in re.finditer(pattern, text):
            name = clean(m.group(1)).strip(" .|–—")
            if 1 < len(name) <= 90 and not re.search(r"track|listen|episode|bbc|sounds|playlist|album", name, re.I):
                artists.append(name)
    # BBC's public HTML uses track title and artist as distinct repeated labels.
    if not artists:
        lines = [clean(x) for x in p.text if clean(x)]
        for i, line in enumerate(lines):
            if line.lower() in {"tracklist", "music played"}:
                window = lines[i+1:i+180]
                for j, item in enumerate(window):
                    if item.lower() in {"artist", "track"} and j+1 < len(window):
                        candidate = window[j+1]
                        if candidate.lower() not in {"artist","track","tracklist"} and len(candidate) < 90:
                            artists.append(candidate)
    unique = []
    for a in artists:
        if a not in unique: unique.append(a)
    return unique, text

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    now = dt.datetime.now(dt.timezone.utc)
    with POOL.open(encoding="utf-8-sig", newline="") as f: pool = list(csv.DictReader(f))
    known = {re.sub(r"[^a-z0-9]+"," ",r["artist"].lower()).strip() for r in pool if r.get("artist")}
    sources = [
        ("radiofiles", RADIOFILES),
        ("bbc_sounds", BBC_PROGRAMME),
    ]
    ledger, episodes, proposed = [], [], []
    seen_urls = set()
    for source, index_url in sources:
        source_row = {"source":source,"index_url":index_url,"status":"failed","episodes_discovered":0,"error":""}
        try:
            final, body, status = fetch(index_url)
            links = episode_links(final, body, source)
            source_row.update(status="checked",http_status=status,episodes_discovered=len(links))
            for ep in links[:MAX_EPISODES]:
                if ep["url"] in seen_urls: continue
                seen_urls.add(ep["url"])
                item = {"source":source,"url":ep["url"],"title":ep["title"],"status":"FAILED","artists":[],"track_count":0,"retrieved_at":now.isoformat(),"error":""}
                try:
                    eurl, ebody, estate = fetch(ep["url"])
                    artists, plain = parse_tracklist(ebody)
                    # Completeness is deliberately conservative: require substantial extracted list,
                    # and explicit page tracklist marker. No inference from search snippets.
                    marker = bool(re.search(r"tracklist|music played|track listings|playlist", plain, re.I))
                    if marker and len(artists) >= 12:
                        item.update(status="COMPLETE",artists=artists,track_count=len(artists),final_url=eurl,http_status=estate)
                    elif artists:
                        item.update(status="PARTIAL",artists=artists,track_count=len(artists),final_url=eurl,http_status=estate)
                    else:
                        item.update(status="MISSING",final_url=eurl,http_status=estate,error="No artist rows extracted by conservative parser")
                    for artist in artists:
                        key = re.sub(r"[^a-z0-9]+"," ",artist.lower()).strip()
                        if item["status"] == "COMPLETE" and key and key not in known:
                            proposed.append({"artist":artist,"episode_url":eurl,"source":source,"track_count":len(artists),"status":"PROPOSED_REVIEW"})
                except Exception as exc:
                    item["error"] = f"{type(exc).__name__}: {str(exc)[:200]}"
                episodes.append(item)
                time.sleep(0.2)
        except Exception as exc:
            source_row["error"] = f"{type(exc).__name__}: {str(exc)[:220]}"
        ledger.append(source_row)
    # Proposals are not silently merged: keep the approved pool unchanged until a human
    # can inspect the source evidence. A failed refresh must never shrink or rewrite it.
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    (OUT/"episode_refresh.json").write_text(json.dumps({"run_at":now.isoformat(),"sources":ledger,"episodes":episodes,"approved_pool_entries":len(pool),"pool_mutated":False},ensure_ascii=False,indent=2),encoding="utf-8")
    with (OUT/"episode_artist_proposals.csv").open("w",encoding="utf-8",newline="") as f:
        fields=["artist","episode_url","source","track_count","status"]
        w=csv.DictWriter(f,fieldnames=fields); w.writeheader(); w.writerows(proposed)
    with (OUT/"episode_refresh_coverage.csv").open("w",encoding="utf-8",newline="") as f:
        w=csv.DictWriter(f,fieldnames=["source","index_url","status","http_status","episodes_discovered","error"],extrasaction="ignore"); w.writeheader(); w.writerows(ledger)
    print(f"Episode refresh: sources checked={sum(x['status']=='checked' for x in ledger)}/{len(ledger)}, episodes inspected={len(episodes)}, complete={sum(x['status']=='COMPLETE' for x in episodes)}, proposals={len(proposed)}; approved pool unchanged ({len(pool)} entries).",flush=True)
    # Fail the step only if both primary/secondary sources failed, while preserving gig search.
    return 0 if any(x["status"]=="checked" for x in ledger) else 1

if __name__ == "__main__": raise SystemExit(main())
