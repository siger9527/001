import importlib.util
import unittest
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("resource_sniffer", ROOT / "resource_sniffer.py")
sniffer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(sniffer)


class ResourceSnifferTests(unittest.TestCase):
    def test_parses_relative_hls_variants_and_dimensions(self):
        rows = sniffer.parse_hls_variants(
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.4d401f"\n720/index.m3u8\n'
            '#EXT-X-STREAM-INF:BANDWIDTH=5000000,RESOLUTION=1920x1080\nhttps://cdn.example.org/1080.m3u8\n',
            "https://example.org/live/master.m3u8",
        )
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["url"], "https://example.org/live/720/index.m3u8")
        self.assertEqual((rows[0]["width"], rows[0]["height"]), (1280, 720))
        self.assertEqual(rows[1]["height"], 1080)

    def test_parses_commas_inside_quoted_codec_attribute(self):
        rows = sniffer.parse_hls_variants(
            '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2500000,RESOLUTION=1280x720,CODECS="avc1.4d401f,mp4a.40.2"\n720.m3u8\n',
            "https://example.org/master.m3u8",
        )
        self.assertEqual(rows[0]["codecs"], "avc1.4d401f,mp4a.40.2")
        self.assertEqual(rows[0]["bandwidth"], 2500000)

    def test_sniff_resource_classifies_hls_master_without_network(self):
        body = b'#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=2000000,RESOLUTION=1280x720\n720.m3u8\n'
        with patch.object(sniffer, "_fetch", return_value=(
            "https://example.org/master.m3u8", "application/vnd.apple.mpegurl", body, 200
        )):
            result = sniffer.sniff_resource("https://example.org/master.m3u8")
        self.assertEqual(result["sniff_status"], "ok")
        self.assertEqual(result["resource_type"], "hls_master")
        self.assertEqual(len(result["hls_variants"]), 1)

    def test_sniff_resource_rejects_unsafe_input_without_network(self):
        with patch.object(sniffer, "_opener") as opener_factory:
            result = sniffer.sniff_resource("http://127.0.0.1/private.m3u8")
        self.assertEqual(result["sniff_status"], "error")
        self.assertIn("URL rejected", result["sniff_reason"])
        opener_factory.assert_not_called()

    def test_rejects_private_hls_variant(self):
        rows = sniffer.parse_hls_variants(
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1000,RESOLUTION=1280x720\nhttp://127.0.0.1/secret.m3u8\n",
            "https://example.org/master.m3u8",
        )
        self.assertEqual(rows, [])

    def test_extracts_relative_embedded_manifests(self):
        urls = sniffer.extract_embedded_media_urls(
            '<video src="media/live.m3u8"></video><script>file: "dash/stream.mpd"</script>',
            "https://example.org/watch/page",
        )
        self.assertIn("https://example.org/watch/media/live.m3u8", urls)
        self.assertIn("https://example.org/watch/dash/stream.mpd", urls)

    def test_deduplicates_variants(self):
        rows = sniffer.parse_hls_variants(
            "#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1,RESOLUTION=1280x720\na.m3u8\n"
            "#EXT-X-STREAM-INF:BANDWIDTH=2,RESOLUTION=1920x1080\na.m3u8\n",
            "https://example.org/master.m3u8",
        )
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
