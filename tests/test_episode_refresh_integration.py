import csv
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import hybrid.episode_refresh as refresh

ARTISTS = [f"Test Artist {i:02d}" for i in range(1, 13)]
EPISODE_HTML = '<html><body><h2>Tracklist</h2>' + ''.join(
    f'<div class="track"><span class="track-artist">{name}</span></div>' for name in ARTISTS
) + '</body></html>'

class EpisodeRefreshIntegrationTests(unittest.TestCase):
    def test_complete_episode_creates_review_proposals_without_mutating_pool(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "artifacts"
            before = refresh.POOL.read_bytes()
            def fake_fetch(url):
                if url == refresh.RADIOFILES:
                    return url, '<a href="/show/riley-coe/episode-1">Episode 1</a>', 200
                if url == refresh.BBC_PROGRAMME:
                    return url, '<a href="/sounds/play/p0episode">Episode</a>', 200
                if url.endswith("/episode-1") or url.endswith("/p0episode"):
                    return url, EPISODE_HTML, 200
                raise AssertionError("Unexpected URL " + url)
            with patch.object(refresh, "OUT", out), patch.object(refresh, "fetch", side_effect=fake_fetch), patch.object(refresh.time, "sleep"):
                self.assertEqual(refresh.main(), 0)
            self.assertEqual(refresh.POOL.read_bytes(), before)
            report = json.loads((out / "episode_refresh.json").read_text())
            self.assertEqual(len(report["episodes"]), 2)
            self.assertTrue(all(x["status"] == "COMPLETE" for x in report["episodes"]))
            with (out / "episode_artist_proposals.csv").open(newline="", encoding="utf-8") as f:
                proposals = list(csv.DictReader(f))
            self.assertEqual(len(proposals), 24)
            self.assertTrue(all(x["status"] == "PROPOSED_REVIEW" for x in proposals))

    def test_both_sources_failed_is_reported_as_failure_and_pool_survives(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / "artifacts"
            before = refresh.POOL.read_bytes()
            with patch.object(refresh, "OUT", out), patch.object(refresh, "fetch", side_effect=OSError("offline")):
                self.assertEqual(refresh.main(), 1)
            self.assertEqual(refresh.POOL.read_bytes(), before)
            report = json.loads((out / "episode_refresh.json").read_text())
            self.assertTrue(all(x["status"] == "failed" for x in report["sources"]))
            self.assertFalse(report["pool_mutated"])

if __name__ == "__main__":
    unittest.main()
