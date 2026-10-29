"""Batch-analyze every pending IPTV candidate using the existing local review pipeline.

Run from the repository root while Ollama and FFmpeg are available:
    python batch_review.py
Optional:
    python batch_review.py --status pending --retry-failed
The script never approves or rejects channels. It writes batch-review-report.csv.
"""
from __future__ import annotations

import argparse
import csv
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import local_iptv_server as app


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def main() -> int:
    parser = argparse.ArgumentParser(description="Batch visual analysis for local IPTV candidates")
    parser.add_argument("--status", choices=("pending", "approved", "rejected", "all"), default="pending")
    parser.add_argument("--retry-failed", action="store_true", help="Retry candidates with previous analysis errors")
    parser.add_argument("--limit", type=int, default=0, help="Optional maximum candidate count; 0 means no limit")
    parser.add_argument("--pause", type=float, default=0.5, help="Seconds between candidates")
    args = parser.parse_args()

    if args.limit < 0 or args.pause < 0:
        parser.error("--limit and --pause must not be negative")

    conn = app.connect()
    try:
        if args.status == "all":
            rows = [dict(r) for r in conn.execute("SELECT * FROM candidates ORDER BY id")]
        else:
            rows = [dict(r) for r in conn.execute(
                "SELECT * FROM candidates WHERE status=? ORDER BY id", (args.status,))]
    finally:
        conn.close()
    if args.retry_failed:
        rows = [r for r in rows if r.get("analysis_error")]
    else:
        rows = [r for r in rows if not r.get("ai_label") or r.get("analysis_error")]
    if args.limit:
        rows = rows[:args.limit]

    report_path = Path("batch-review-report.csv").resolve()
    total = len(rows)
    succeeded = failed = 0
    print("IPTV batch visual review")
    print("Started:", stamp())
    print("Candidates:", total)
    print("Report:", report_path)
    print("Note: AI results are advisory; human approval is still required.")

    with report_path.open("w", newline="", encoding="utf-8-sig") as handle:
        fields = ("id", "name", "url", "review_status", "ai_label", "ai_confidence",
                  "ai_summary", "ai_observed_text", "analysis_error", "processed_at")
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for index, row in enumerate(rows, 1):
            cid = int(row["id"])
            print(f"[{index}/{total}] {row['name'][:100]} (ID {cid})", flush=True)
            error = ""
            try:
                result = app.analyze(cid)
                succeeded += 1
                print(f"    result={result['ai_label']} confidence={result['confidence']:.2f}", flush=True)
            except Exception as exc:
                failed += 1
                error = f"{type(exc).__name__}: {exc}"[:500]
                conn = app.connect()
                try:
                    conn.execute("UPDATE candidates SET analysis_error=?, updated_at=? WHERE id=?",
                                 (error, app.now(), cid))
                    conn.commit()
                finally:
                    conn.close()
                print("    FAILED:", error, flush=True)

            conn = app.connect()
            try:
                latest = conn.execute("SELECT * FROM candidates WHERE id=?", (cid,)).fetchone()
                latest = dict(latest) if latest else row
            finally:
                conn.close()
            writer.writerow({
                "id": cid,
                "name": latest.get("name", ""),
                "url": latest.get("url", ""),
                "review_status": latest.get("status", ""),
                "ai_label": latest.get("ai_label", ""),
                "ai_confidence": latest.get("ai_confidence", 0),
                "ai_summary": latest.get("ai_summary", ""),
                "ai_observed_text": latest.get("ai_observed_text", ""),
                "analysis_error": latest.get("analysis_error", error),
                "processed_at": stamp(),
            })
            handle.flush()
            if args.pause and index < total:
                time.sleep(args.pause)

    print("\nFinished:", stamp())
    print(f"Summary: total={total}, succeeded={succeeded}, failed={failed}")
    print("CSV report:", report_path)
    return 0 if failed == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
