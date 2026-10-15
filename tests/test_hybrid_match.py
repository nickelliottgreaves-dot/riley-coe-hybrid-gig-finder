import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from hybrid.match import norm, match_names

class MatchingTests(unittest.TestCase):
    def test_normalization(self):
        self.assertEqual(norm("A Certain Ratio"), "a certain ratio")
        self.assertEqual(norm("The Dells!"), "the dells")

    def test_whole_artist_match_not_substring(self):
        index = {"the leaves": "The Leaves", "oasis": "Oasis"}
        self.assertEqual(match_names({"artists": ["The Leaves"], "event_title": "Live"}, index), ["The Leaves"])
        self.assertEqual(match_names({"artists": ["Oasis tribute night"], "event_title": "Live"}, index), ["Oasis"])
        self.assertEqual(match_names({"artists": ["The Leaflets"], "event_title": "Live"}, index), [])

    def test_title_is_considered(self):
        self.assertEqual(match_names({"artists": [], "event_title": "Oasis live"}, {"oasis": "Oasis"}), ["Oasis"])

if __name__ == "__main__":
    unittest.main()
