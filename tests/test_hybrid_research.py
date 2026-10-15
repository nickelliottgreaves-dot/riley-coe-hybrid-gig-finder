import datetime as dt
import unittest
from hybrid.research import PageParser, extract_events, relevant_links, walk_jsonld
from hybrid.search_discovery import parse_date

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

    def test_nested_jsonld_event(self):
        obj = {"@type":"@graph", "@graph":[{"@type":"Event","name":"Nested"}]}
        self.assertEqual(len(list(walk_jsonld(obj))), 1)

if __name__ == "__main__":
    unittest.main()
