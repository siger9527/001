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

    def test_private_and_loopback_streams_are_excluded(self):
        rows = collector.parse_m3u(
            '#EXTM3U\n#EXTINF:-1,Public\nhttps://example.com/live.m3u8\n'
            '#EXTINF:-1,Local\nhttp://127.0.0.1:8080/admin\n'
            '#EXTINF:-1,Private\nhttp://192.168.1.5/live\n',
            "fixture",
        )
        self.assertEqual([row["name"] for row in rows], ["Public"])

    def test_handles_missing_extinf(self):
        rows = collector.parse_m3u("https://example.com/a.m3u8\n", "fixture")
        self.assertEqual(rows[0]["name"], "Unknown channel")

    def test_channel_name_whitespace_is_normalized(self):
        rows = collector.parse_m3u(
            '#EXTM3U\n#EXTINF:-1,Example    HD\nhttps://example.com/a.m3u8\n',
            "fixture",
        )
        self.assertEqual(rows[0]["name"], "Example HD")

    def test_selected_hls_variant_replaces_master_url(self):
        row = {"url": "https://example.org/master.m3u8"}
        probes = [
            {"technical_status": "pass", "height": 720, "width": 1280,
             "variant_bandwidth": 2500000, "variant_url": "https://example.org/720.m3u8"},
            {"technical_status": "pass", "height": 1080, "width": 1920,
             "variant_bandwidth": 5000000, "variant_url": "https://example.org/1080.m3u8"},
        ]
        collector.apply_selected_probe(row, probes, "hls_master")
        self.assertEqual(row["url"], "https://example.org/1080.m3u8")
        self.assertEqual(row["technical_status"], "pass")

    def test_selected_html_manifest_replaces_wrapper_page(self):
        row = {"url": "https://example.org/watch"}
        probes = [{"technical_status": "pass", "height": 720, "width": 1280,
                   "variant_url": "https://cdn.example.org/live.m3u8"}]
        collector.apply_selected_probe(row, probes, "html_page")
        self.assertEqual(row["url"], "https://cdn.example.org/live.m3u8")
        self.assertIn("embedded media manifest", row["technical_reason"])

    def test_failed_variant_does_not_overwrite_source_url(self):
        row = {"url": "https://example.org/master.m3u8"}
        probes = [{"technical_status": "unreachable_or_unreadable",
                   "technical_reason": "timeout", "variant_url": "https://example.org/720.m3u8"}]
        collector.apply_selected_probe(row, probes, "hls_master")
        self.assertEqual(row["url"], "https://example.org/master.m3u8")
        self.assertEqual(row["variant_probe_count"], 1)

    def test_resolution_gate_is_strict(self):
        self.assertGreaterEqual(collector.MIN_WIDTH, 1280)
        self.assertGreaterEqual(collector.MIN_HEIGHT, 720)


if __name__ == "__main__":
    unittest.main()
