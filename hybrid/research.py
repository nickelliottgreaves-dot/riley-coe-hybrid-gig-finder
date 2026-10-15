"""No-paid-API public-source collector for the independent gig finder.

Fetches configured public venue pages and extracts event-shaped JSON-LD plus
date-bearing event links. It does not claim exhaustive coverage: ordinary HTML
pages frequently hide listings behind JavaScript, ticketing APIs, or pagination.
"""
from __future__ import annotations
import csv, datetime as dt, html, json, os, pathlib, re, sys, time, urllib.error, urllib.request
from html.parser import HTMLParser

ROOT = pathlib.Path(__file__).resolve().parents[1]
VENUES = ROOT / "config" / "venue_sources.csv"
OUT = pathlib.Path(os.environ.get("RUN_DIR", "artifacts/current"))
UA = "Mozilla/5.0 (compatible; RileyCoeGigFinder/2.0; public-calendar-check)"
TIMEOUT = 25
MAX_BYTES = 3_000_000

class Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links=[]; self.scripts=[]; self._script=False; self._script_type=""
        self._script_data=[]
    def handle_starttag(self, tag, attrs):
        a=dict(attrs)
        if tag.lower()=="a" and a.get("href"):
            self.links.append({"href":a["href"],"text":""})
            self._last=len(self.links)-1
        if tag.lower()=="script":
            self._script=True; self._script_type=a.get("type","").lower(); self._script_data=[]
    def handle_data(self,data):
        if self._script: self._script_data.append(data)
        elif getattr(self,"_last",None) is not None:
            self.links[self._last]["text"] += data
    def handle_endtag(self,tag):
        if tag.lower()=="script" and self._script:
            if "ld+json" in self._script_type:
                self.scripts.append("".join(self._script_data))
            self._script=False; self._script_data=[]

def fetch(url):
    req=urllib.request.Request(url,headers={"User-Agent":UA,"Accept":"text/html,application/xhtml+xml"})
    with urllib.request.urlopen(req,timeout=TIMEOUT) as r:
        data=r.read(MAX_BYTES+1)
        if len(data)>MAX_BYTES: data=data[:MAX_BYTES]
        charset=r.headers.get_content_charset() or "utf-8"
        return r.geturl(),data.decode(charset,errors="replace"),r.status

def absolutize(base,url):
    from urllib.parse import urljoin,urlparse
    result=urljoin(base,html.unescape(url.strip()))
    return result if urlparse(result).scheme in ("http","https") else ""

def walk_jsonld(obj):
    if isinstance(obj,dict):
        typ=obj.get("@type",[])
        if isinstance(typ,str): typ=[typ]
        if any(t.lower() in {"event","music event","festival"} for t in typ):
            yield obj
        for value in obj.values(): yield from walk_jsonld(value)
    elif isinstance(obj,list):
        for value in obj: yield from walk_jsonld(value)

def textval(value):
    if isinstance(value,dict): return str(value.get("name") or value.get("url") or "")
    if isinstance(value,list): return "; ".join(filter(None,(textval(x) for x in value)))
    return str(value or "")

def event_from_jsonld(obj, venue, base):
    start=str(obj.get("startDate",""))[:10]
    location=obj.get("location",{})
    room=textval(location.get("name","")) if isinstance(location,dict) else textval(location)
    performers=obj.get("performer",obj.get("performers",[]))
    artists=[textval(x).strip() for x in (performers if isinstance(performers,list) else [performers])]
    offers=obj.get("offers",{})
    if isinstance(offers,list): offers=offers[0] if offers else {}
    event_url=absolutize(base,str(obj.get("url") or ""))
    ticket_url=absolutize(base,str(offers.get("url") or "")) if isinstance(offers,dict) else ""
    return {"event_title":textval(obj.get("name","")).strip(),"date":start,
      "artists":[x for x in artists if x],"venue_room":room or venue,
      "event_url":event_url,"ticket_url":ticket_url,"evidence_quote":"JSON-LD Event metadata extracted from fetched public page",
      "source_type":"official","confidence":"medium","notes":"Structured metadata; confirm against visible event page",
      "research_venue":venue,"research_status":"public_source_candidate"}

def main():
    start=dt.date.fromisoformat(os.environ.get("WINDOW_START") or dt.datetime.now(dt.timezone.utc).date().isoformat())
    end=dt.date.fromisoformat(os.environ.get("WINDOW_END") or (start+dt.timedelta(days=13)).isoformat())
    OUT.mkdir(parents=True,exist_ok=True); rawdir=OUT/"raw_pages"; rawdir.mkdir(exist_ok=True)
    with VENUES.open(encoding="utf-8-sig",newline="") as f: venues=list(csv.DictReader(f))
    all_events=[]; ledger=[]
    for i,v in enumerate(venues,1):
        name=v.get("venue","").strip(); url=v.get("source_url","").strip()
        row={"venue":name,"url":url,"status":"failed","events":0,"sources_checked":[],"limitations":[]}
        if not name or not url.startswith("https://"):
            row["limitations"].append("Missing venue name or HTTPS source URL"); ledger.append(row); continue
        print(f"[{i}/{len(venues)}] Fetching {name}: {url}",flush=True)
        try:
            final,body,status=fetch(url)
            (rawdir/f"{i:02d}.html").write_text(body,encoding="utf-8")
            parser=Links(); parser.feed(body)
            row["sources_checked"].append({"url":final,"kind":"official","result":"checked","note":f"HTTP {status}; {len(body)} chars; parsed structured metadata and links"})
            found=[]
            for blob in parser.scripts:
                try: parsed=json.loads(blob)
                except Exception: continue
                for obj in walk_jsonld(parsed):
                    event=event_from_jsonld(obj,name,final)
                    try: date=dt.date.fromisoformat(event["date"])
                    except ValueError: continue
                    if start<=date<=end and event["event_title"] and event["event_url"]:
                        found.append(event)
            # Record useful dated event links for later inspection, but don't fabricate event records.
            dated_links=[]
            for link in parser.links:
                href=absolutize(final,link["href"]); label=" ".join(link["text"].split())
                if href and (re.search(r"20\d{2}[-/]\d{1,2}[-/]\d{1,2}",href) or re.search(r"\b(?:gig|event|show|tickets|what.?s on)\b",label,re.I)):
                    dated_links.append({"url":href,"label":label[:180]})
            row["events"]=len(found); row["status"]="partial"
            row["limitations"].append("Static public-page extraction only; JavaScript, pagination, linked detail pages and ticketing/local listings may be missing.")
            if not parser.scripts: row["limitations"].append("No JSON-LD scripts were present on the fetched page.")
            row["candidate_links"]=dated_links[:100]
            all_events.extend(found)
        except Exception as e:
            row["limitations"].append(f"{type(e).__name__}: {str(e)[:500]}")
            print(f"  FAILED: {row['limitations'][-1]}",file=sys.stderr,flush=True)
        ledger.append(row); time.sleep(0.4)
    (OUT/"research_events.json").write_text(json.dumps(all_events,ensure_ascii=False,indent=2),encoding="utf-8")
    (OUT/"coverage_ledger.json").write_text(json.dumps({"window_start":start.isoformat(),"window_end":end.isoformat(),"venue_count":len(venues),"events_found":len(all_events),"venues":ledger},ensure_ascii=False,indent=2),encoding="utf-8")
    failed=sum(x["status"]=="failed" for x in ledger)
    partial=sum(x["status"]!="complete" for x in ledger)
    print(f"Public-source collection finished: {len(all_events)} structured event candidates; {len(venues)-failed}/{len(venues)} pages fetched; {partial}/{len(venues)} venues have explicitly partial/non-complete coverage.")
    # Public-page extraction cannot establish exhaustive coverage; exit success means the run completed, not that coverage is complete.
    return 0 if failed < len(venues) else 1

if __name__=="__main__": raise SystemExit(main())
