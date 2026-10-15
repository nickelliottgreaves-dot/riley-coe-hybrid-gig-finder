import datetime as dt
import unittest
from hybrid.research import PageParser, extract_events, relevant_links, walk_jsonld
from unittest.mock import patch\nfrom hybrid.search_discovery import parse_date, SearchParser, _normalise_search_results, search_html

class ResearchTests(unittest.TestCase):
    def test_jsonld_event_extracted_within_window(self):
        parser = PageParser()
        parser.feed("""<script type="application/ld+json">{"@type":"MusicEvent","name":"Test Band","startDate":"2026-10-20T19:00:00","url":"/events/test","performer":{"@type":"MusicGroup","name":"Test Band"}}</script>""")
        events = extract_events(parser, "Test Venue", "https://example.org/gigs/", dt.date(2026,10,15), dt.date(2026,10,28))
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["event_title"], "Test Band")
        self.assertEqual(events[0]["event_url"], "https://example.org/events/test")
        self.assertEqual(events[0]["artists"], ["Test Band"])

    def test_schema_event_type_variants_are_recognized(self):
        for event_type in ("Event", "MusicEvent", "Music Event", "Festival"):
            with self.subTest(event_type=event_type):
                parser = PageParser()
                parser.feed(
                    f'<script type="application/ld+json">'
                    f'{{"@type":"{event_type}","name":"Variant Show",'
                    f'"startDate":"2026-10-20","url":"/variant"}}'
                    f'</script>'
                )
                events = extract_events(
                    parser,
                    "Venue",
                    "https://example.org/",
                    dt.date(2026, 10, 15),
                    dt.date(2026, 10, 28),
                )
                self.assertEqual(len(events), 1)

    def test_event_outside_window_is_excluded(self):
        parser = PageParser()
        parser.feed("""<script type="application/ld+json">{"@type":"Event","name":"Past Show","startDate":"2026-09-01","url":"/past"}</script>""")
        self.assertEqual(extract_events(parser, "Venue", "https://example.org/", dt.date(2026,10,1), dt.date(2026,10,14)), [])

    def test_event_detail_link_discovered(self):
        parser = PageParser()
        parser.feed('<a href="/events/2026-10-20-test">Test show</a><a href="/about">About</a>')
        links = relevant_links(parser, "https://example.org/")
        self.assertEqual([x["url"] for x in links], ["https://example.org/events/2026-10-20-test"])

    def test_search_result_date_parsing(self):
        start, end = dt.date(2026, 10, 15), dt.date(2026, 10, 28)
        self.assertEqual(parse_date('Tickets 20 October 2026 live', start, end), '2026-10-20')
        self.assertEqual(parse_date('Event date 2026-10-22', start, end), '2026-10-22')
        self.assertEqual(parse_date('Event 2026-11-02', start, end), '')

    def test_search_parser_reads_duckduckgo_result_links(self):
        body = '<div class="result"><a class="result__a" href="https://example.org/gig">Gig Listing</a><a class="result__snippet">Fri 16 Oct 2026</a></div>'
        parser = SearchParser()
        parser.feed(body)
        results = _normalise_search_results(parser.results, "DuckDuckGo HTML")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Gig Listing")
        self.assertEqual(results[0]["url"], "https://example.org/gig")

    def test_search_parser_reads_bing_result_links(self):
        body = '<li class="b_algo"><h2><a href="https://example.org/gig">Gig Listing</a></h2><div class="b_caption"><p>Fri 16 Oct 2026</p></div></li>'
        parser = SearchParser()
        parser.feed(body)
        results = _normalise_search_results(parser.results, "Bing HTML")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["title"], "Gig Listing")

    def test_search_html_falls_back_to_next_provider(self):
        with patch("hybrid.search_discovery._fetch_search_page", side_effect=[
            RuntimeError("blocked"),
            '<a class="result-link" href="https://example.org/gig">Gig Listing</a>'
        ]):
            results = search_html("Newcastle gig")
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["search_provider"], "DuckDuckGo Lite")

    def test_search_html_fails_loudly_when_all_frontends_are_unreadable(self):
        with patch("hybrid.search_discovery._fetch_search_page", return_value="<html>challenge</html>"):
            with self.assertRaisesRegex(RuntimeError, "All free search frontends failed"):
                search_html("Newcastle gig")

    def test_visible_listing_without_jsonld_extracts_dated_bill(self):
        from hybrid.research import extract_visible_events
        body='<article><p>Fri 16 Oct 2026</p><h3>Byker Grave: Ye Gods + Pale World + Y Gwacter + Depletion</h3><p>The Lubber Fiend</p><a href="https://example.org/events/byker-grave">Byker Grave: Ye Gods + Pale World + Y Gwacter + Depletion</a></article>'
        events=extract_visible_events(body,"The Lubber Fiend","https://soundbitenortheast.com/newcastle-gigs/",dt.date(2026,10,15),dt.date(2026,10,28))
        self.assertEqual(len(events),1); self.assertEqual(events[0]["date"],"2026-10-16")
        self.assertIn("Ye Gods",events[0]["event_title"]); self.assertEqual(events[0]["event_url"],"https://example.org/events/byker-grave")

    def test_visible_listing_excludes_out_of_window_date(self):
        from hybrid.research import extract_visible_events
        body='<article><p>Fri 30 Oct 2026</p><h3>Future Show With Support</h3></article>'
        self.assertEqual(extract_visible_events(body,"Venue","https://example.org/",dt.date(2026,10,15),dt.date(2026,10,28)),[])

    def test_nested_jsonld_event(self):
        obj = {"@type":"@graph", "@graph":[{"@type":"Event","name":"Nested"}]}
        self.assertEqual(len(list(walk_jsonld(obj))), 1)

if __name__ == "__main__":
    unittest.main()
