import unittest

import tests  # noqa: F401  (wires stub sys.path)
from app.models import Track
from app.sync.matcher import (
    find_best_playlist_name_match,
    find_duplicates,
    find_match,
    normalize,
    tracks_match,
)


def t(id_, title, artists, ms=200000, isrc=None, uri=None):
    return Track(id=id_, provider="x", title=title, artists=artists, duration_ms=ms, isrc=isrc, uri=uri or id_)


class TestNormalize(unittest.TestCase):
    def test_strips_feat_and_punctuation(self):
        self.assertEqual(normalize("Blinding Lights (feat. Someone)"), "blinding lights")
        self.assertEqual(normalize("Don't Stop Me Now!"), "dont stop me now")

    def test_case_insensitive(self):
        self.assertEqual(normalize("HELLO"), normalize("hello"))


class TestTracksMatch(unittest.TestCase):
    def test_isrc_exact_match_wins_even_with_different_titles(self):
        a = t("1", "Song A", ["Artist"], isrc="USRC17607839")
        b = t("2", "Totally Different Title", ["Someone Else"], isrc="usrc17607839")  # case-insensitive
        self.assertTrue(tracks_match(a, b))

    def test_isrc_mismatch_fails_even_with_same_title(self):
        a = t("1", "Song A", ["Artist"], isrc="USRC17607839")
        b = t("2", "Song A", ["Artist"], isrc="GBUM71029601")
        self.assertFalse(tracks_match(a, b))

    def test_fuzzy_fallback_when_no_isrc(self):
        a = t("1", "Blinding Lights", ["The Weeknd"])
        b = t("2", "Blinding Lights (feat. Someone)", ["The Weeknd"])
        self.assertTrue(tracks_match(a, b))

    def test_fuzzy_fallback_rejects_different_songs(self):
        a = t("1", "Blinding Lights", ["The Weeknd"])
        b = t("2", "Save Your Tears", ["The Weeknd"])
        self.assertFalse(tracks_match(a, b))

    def test_fuzzy_fallback_rejects_same_title_different_artist(self):
        a = t("1", "Photograph", ["Ed Sheeran"])
        b = t("2", "Photograph", ["Some Cover Band"])
        self.assertFalse(tracks_match(a, b))

    def test_duration_mismatch_rejects_match_without_isrc(self):
        a = t("1", "Some Song", ["Artist"], ms=180000)
        b = t("2", "Some Song", ["Artist"], ms=400000)  # >4s off -> reject
        self.assertFalse(tracks_match(a, b))

    def test_missing_duration_does_not_block_match(self):
        a = t("1", "Some Song", ["Artist"], ms=0)
        b = t("2", "Some Song", ["Artist"], ms=200000)
        self.assertTrue(tracks_match(a, b))


class TestFindMatch(unittest.TestCase):
    def test_returns_none_on_empty_candidates(self):
        a = t("1", "X", ["Y"])
        self.assertIsNone(find_match(a, []))

    def test_finds_correct_candidate_among_several(self):
        a = t("1", "Song B", ["Artist"], isrc="ISRC2")
        candidates = [
            t("c1", "Song A", ["Artist"], isrc="ISRC1"),
            t("c2", "Song B", ["Artist"], isrc="ISRC2"),
            t("c3", "Song C", ["Artist"], isrc="ISRC3"),
        ]
        match = find_match(a, candidates)
        self.assertIsNotNone(match)
        self.assertEqual(match.id, "c2")


class TestFindDuplicates(unittest.TestCase):
    def test_no_duplicates(self):
        tracks = [
            (0, t("1", "A", ["X"], isrc="I1")),
            (1, t("2", "B", ["X"], isrc="I2")),
        ]
        self.assertEqual(find_duplicates(tracks), [])

    def test_keeps_first_occurrence_flags_rest(self):
        tracks = [
            (0, t("1", "Same Song", ["Artist"], isrc="I1")),
            (1, t("2", "Other Song", ["Artist"], isrc="I2")),
            (2, t("3", "Same Song", ["Artist"], isrc="I1")),  # dup of position 0
            (3, t("4", "Same Song", ["Artist"], isrc="I1")),  # dup of position 0
        ]
        dupes = find_duplicates(tracks)
        self.assertEqual([pos for pos, _ in dupes], [2, 3])

    def test_fuzzy_duplicates_without_isrc(self):
        tracks = [
            (0, t("1", "Blinding Lights", ["The Weeknd"])),
            (1, t("2", "Blinding Lights (feat. Someone)", ["The Weeknd"])),
        ]
        dupes = find_duplicates(tracks)
        self.assertEqual([pos for pos, _ in dupes], [1])


class TestPlaylistNameMatch(unittest.TestCase):
    def test_exact_and_close_matches(self):
        self.assertEqual(find_best_playlist_name_match("Road Trip 2024", ["Road Trip 2024", "Chill"]), "Road Trip 2024")
        self.assertEqual(find_best_playlist_name_match("Road Trip 2024", ["Road Trip '24", "Chill"]), "Road Trip '24")

    def test_no_match_below_threshold(self):
        self.assertIsNone(find_best_playlist_name_match("Road Trip 2024", ["Focus Music", "Sleep"]))

    def test_empty_candidates(self):
        self.assertIsNone(find_best_playlist_name_match("Anything", []))


if __name__ == "__main__":
    unittest.main()
