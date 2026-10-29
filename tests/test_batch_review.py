import csv
import importlib
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


class BatchReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        import local_iptv_server as app
        self.app = app
        self.old = (app.DATA, app.DB, app.FRAMES)
        app.DATA = self.root / "local_data"
        app.DB = app.DATA / "review.sqlite3"
        app.FRAMES = app.DATA / "frames"
        app.import_m3u(
            "#EXTM3U\n#EXTINF:-1,Test One\nhttps://example.com/one.m3u8\n"
            "#EXTINF:-1,Test Two\nhttps://example.com/two.m3u8\n"
        )
        self.old_cwd = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old_cwd)
        self.app.DATA, self.app.DB, self.app.FRAMES = self.old
        self.temp.cleanup()

    def test_batch_continues_after_one_failure_and_writes_report(self):
        import batch_review
        def fake_analyze(cid):
            if cid == 2:
                raise RuntimeError("simulated decode failure")
            conn = self.app.connect()
            try:
                conn.execute(
                    "UPDATE candidates SET ai_label='match', ai_confidence=0.9, ai_summary='test summary' WHERE id=?",
                    (cid,))
                conn.commit()
            finally:
                conn.close()
            return {"id": cid, "ai_label": "match", "confidence": 0.9}

        with mock.patch.object(self.app, "analyze", side_effect=fake_analyze):
            with mock.patch.object(sys, "argv", ["batch_review.py"]):
                result = batch_review.main()

        self.assertEqual(result, 2)
        report = self.root / "batch-review-report.csv"
        self.assertTrue(report.exists())
        with report.open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["ai_label"], "match")
        self.assertIn("simulated decode failure", rows[1]["analysis_error"])
        db_rows = self.app.list_candidates()
        self.assertEqual(db_rows[0]["status"], "pending")
        self.assertEqual(db_rows[1]["status"], "pending")

    def test_retry_failed_only_selects_error_rows(self):
        conn = self.app.connect()
        try:
            conn.execute("UPDATE candidates SET analysis_error='previous failure' WHERE id=2")
            conn.commit()
        finally:
            conn.close()
        import batch_review
        with mock.patch.object(self.app, "analyze", return_value={"ai_label": "match", "confidence": 0.8}) as analyze:
            with mock.patch.object(sys, "argv", ["batch_review.py", "--retry-failed"]):
                batch_review.main()
        analyze.assert_called_once_with(2)


if __name__ == "__main__":
    unittest.main()
