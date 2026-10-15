import unittest
from hybrid.episode_refresh import Page, episode_links, parse_tracklist, RADIOFILES

class EpisodeRefreshTests(unittest.TestCase):
    def test_radiofiles_episode_links_are_scoped(self):
        html = '<a href="/show/riley-coe/2026-10-14">14 October</a><a href="/other/show">Other</a>'
        links = episode_links(RADIOFILES, html, "radiofiles")
        self.assertEqual(len(links), 1)
        self.assertIn("/show/riley-coe/2026-10-14", links[0]["url"])

    def test_structured_artist_nodes_are_extracted(self):
        html = '<main><h2>Tracklist</h2>' + ''.join(f'<div class="track"><span class="track-artist">{name}</span></div>' for name in [
            "Artist One", "Artist Two", "Artist Three", "Artist Four", "Artist Five",
            "Artist Six", "Artist Seven", "Artist Eight", "Artist Nine", "Artist Ten",
            "Artist Eleven", "Artist Twelve"
        ]) + '</main>'
        artists, text = parse_tracklist(html)
        self.assertGreaterEqual(len(artists), 12)
        self.assertIn("Tracklist", text)

    def test_no_artist_rows_fails_closed(self):
        artists, _ = parse_tracklist("<html><body>Riley &amp; Coe episode</body></html>")
        self.assertEqual(artists, [])

if __name__ == "__main__":
    unittest.main()
