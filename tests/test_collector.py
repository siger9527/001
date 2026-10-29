import importlib.util
import unittest
from pathlib import Path

SPEC = importlib.util.spec_from_file_location("collector", Path(__file__).resolve().parents[1] / "collector.py")
collector = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(collector)


class PlaylistParsingTests(unittest.TestCase):
    def test_parses_extinf_and_urls(self):
        rows = collector.parse_m3u(
            '#EXTM3U\n#EXTINF:-1 tvg-id="x",Example HD\nhttps://example.com/live.m3u8\n',
            "fixture",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "Example HD")
        self.assertEqual(rows[0]["url"], "https://example.com/live.m3u8")


    def test_parses_commas_inside_quoted_extinf_attributes(self):
        rows = collector.parse_m3u(
            '#EXTM3U\n#EXTINF:-1 user-agent="Chrome/149.0, Safari/537.36" group-title="General",1+1 International HD\nhttps://example.com/live.m3u8\n',
            "fixture",
        )
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["name"], "1+1 International HD")

    def test_ignores_comments_and_non_http_urls(self):
        rows = collector.parse_m3u(
            '#EXTM3U\n#EXTINF:-1,Example\nrtmp://example.com/live\n# comment\n',
            "fixture",
        )
        self.assertEqual(rows, [])

    def test_handles_missing_extinf(self):
        rows = collector.parse_m3u("https://example.com/a.m3u8\n", "fixture")
        self.assertEqual(rows[0]["name"], "Unknown channel")

    def test_resolution_gate_is_strict(self):
        self.assertGreaterEqual(collector.MIN_WIDTH, 1280)
        self.assertGreaterEqual(collector.MIN_HEIGHT, 720)


if __name__ == "__main__":
    unittest.main()
