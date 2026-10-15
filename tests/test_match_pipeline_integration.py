import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hybrid.match as match

class MatchPipelineIntegrationTests(unittest.TestCase):
    def test_unverified_artist_search_result_is_kept_separate_from_validated_matches(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp)
            event = {
                "event_title": "Oasis tribute? Oasis live",
                "date": "2026-10-20",
                "artists": ["Oasis"],
                "venue_room": "Unverified Newcastle-area venue",
                "event_url": "https://example.org/events/oasis",
                "ticket_url": "",
                "evidence_quote": "Oasis live 20 October 2026",
                "source_type": "public_web_search",
                "research_venue": "",
                "research_status": "unverified_search_lead"
            }
            (out / "research_events.json").write_text(json.dumps([event]))
            with patch.object(match, "OUT", out), patch.dict(os.environ, {"WINDOW_START":"2026-10-15","WINDOW_END":"2026-10-28"}):
                self.assertEqual(match.main(), 0)
            validated = json.loads((out / "artist_matches.json").read_text())
            leads = json.loads((out / "artist_discovery_leads.json").read_text())
            self.assertEqual(validated, [])
            self.assertEqual(len(leads), 1)
            self.assertIn("Oasis", leads[0]["matched_artists"])
            self.assertEqual(leads[0]["validation_status"], "discovery_lead_needs_venue_verification")

if __name__ == "__main__":
    unittest.main()
