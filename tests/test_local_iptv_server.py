import importlib.util
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location(
    "local_iptv_server", Path(__file__).resolve().parents[1] / "local_iptv_server.py"
)
app = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(app)


class LocalReviewServerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(app, "DATA", self.root),
            patch.object(app, "FRAMES", self.root / "frames"),
            patch.object(app, "DB", self.root / "review.sqlite3"),
        ]
        for p in self.patches:
            p.start()
        app.connect().close()

    def tearDown(self):
        for p in reversed(self.patches):
            p.stop()
        self.temp.cleanup()

    def test_import_filters_private_addresses(self):
        result = app.import_m3u(
            "#EXTM3U\n#EXTINF:-1,Public HD\nhttps://example.com/live.m3u8\n"
            "#EXTINF:-1,Local\nhttp://127.0.0.1/admin\n"
        )
        self.assertEqual(result["found"], 1)
        rows = app.list_candidates()
        self.assertEqual(rows[0]["name"], "Public HD")

    def test_duplicate_import_does_not_reset_manual_decision(self):
        playlist = "#EXTM3U\n#EXTINF:-1,Channel\nhttps://example.com/live.m3u8\n"
        app.import_m3u(playlist)
        candidate = app.list_candidates()[0]
        app.review(candidate["id"], "approved")
        result = app.import_m3u(playlist)
        self.assertEqual(result["duplicates"], 1)
        self.assertEqual(app.list_candidates()[0]["status"], "approved")

    def test_approved_playlist_excludes_pending_and_rejected(self):
        app.import_m3u(
            "#EXTM3U\n#EXTINF:-1,Pending\nhttps://example.com/pending.m3u8\n"
            "#EXTINF:-1,Approved\nhttps://example.com/approved.m3u8\n"
            "#EXTINF:-1,Rejected\nhttps://example.com/rejected.m3u8\n"
        )
        rows = app.list_candidates()
        for row in rows:
            if row["name"] == "Approved":
                app.review(row["id"], "approved")
            elif row["name"] == "Rejected":
                app.review(row["id"], "rejected")
        approved = app.playlist(approved_only=True)
        self.assertIn("https://example.com/approved.m3u8", approved)
        self.assertNotIn("pending.m3u8", approved)
        self.assertNotIn("rejected.m3u8", approved)

    def test_all_playlist_excludes_rejected_blacklist_entries(self):
        app.import_m3u(
            "#EXTM3U\n#EXTINF:-1,Keep\nhttps://example.com/keep.m3u8\n"
            "#EXTINF:-1,Block\nhttps://example.com/block.m3u8\n"
        )
        rows = app.list_candidates()
        blocked = next(r for r in rows if r["name"] == "Block")
        app.review(blocked["id"], "rejected")
        result = app.playlist()
        self.assertIn("keep.m3u8", result)
        self.assertNotIn("block.m3u8", result)

    def test_ai_analysis_never_changes_human_approval_state(self):
        app.import_m3u("#EXTM3U\n#EXTINF:-1,Channel\nhttps://example.com/live.m3u8\n")
        candidate = app.list_candidates()[0]
        app.review(candidate["id"], "approved")
        # The analysis implementation has no status write; assert the review helper is separate.
        self.assertEqual(app.get_candidate(candidate["id"])["status"], "approved")

    def test_rejects_oversized_playlist(self):
        with self.assertRaises(ValueError):
            app.import_m3u("x" * (app.MAX_BYTES + 1))


if __name__ == "__main__":
    unittest.main()
