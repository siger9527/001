#!/usr/bin/env python3
"""Public IPTV playlist collector and conservative cloud pre-screen.

No stream is considered finally approved here. Local visual review remains mandatory.
"""
from __future__ import annotations

import base64
import csv
import json
import os
import re
import shutil
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
SHOTS = OUT / "screenshots"
SOURCES_FILE = ROOT / "config" / "sources.txt"
MAX_CANDIDATES = max(1, int(os.getenv("MAX_CANDIDATES", "300")))
PROBE_TIMEOUT = max(4, int(os.getenv("PROBE_TIMEOUT_SECONDS", "12")))
VISION_MAX_ITEMS = max(0, int(os.getenv("VISION_MAX_ITEMS", "40")))
VISION_KEY = os.getenv("VISION_API_KEY", "").strip()
VISION_BASE = (os.getenv("VISION_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/")
VISION_MODEL = (os.getenv("VISION_MODEL") or "gpt-4o-mini").strip()
USER_AGENT = "IPTVCloudPrescreen/1.0 (GitHub Actions; conservative public playlist audit)"
MIN_WIDTH, MIN_HEIGHT = 1280, 720


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def http_get(url: str, timeout: int = 20) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read(20 * 1024 * 1024 + 1)


def read_sources():
    if not SOURCES_FILE.exists():
        return []
    rows = []
    for line in SOURCES_FILE.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            parsed = urllib.parse.urlparse(line)
            if parsed.scheme in ("http", "https") and parsed.netloc:
                rows.append(line)
    return list(dict.fromkeys(rows))


def parse_m3u(text: str, source: str):
    entries, name = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            match = re.search(r',\s*(.*)$', line)
            name = match.group(1).strip() if match else "Unknown channel"
            name = re.sub(r"\s+", " ", name)[:200] or "Unknown channel"
        elif line and not line.startswith("#") and line.lower().startswith(("http://", "https://")):
            entries.append({"name": name or "Unknown channel", "url": line, "source": source})
            name = None
    return entries


def fetch_candidates(report):
    found = []
    for source in read_sources():
        item = {"url": source, "status": "pending"}
        try:
            raw = http_get(source, timeout=30)
            if len(raw) > 20 * 1024 * 1024:
                raise ValueError("playlist exceeds 20 MiB safety limit")
            text = raw.decode("utf-8-sig", errors="replace")
            rows = parse_m3u(text, source)
            item.update(status="ok", candidates=len(rows))
            found.extend(rows)
        except Exception as exc:
            item.update(status="error", error=f"{type(exc).__name__}: {str(exc)[:300]}")
        report["sources"].append(item)

    dedup = {}
    for row in found:
        url = row["url"].strip()
        if url not in dedup:
            row["url"] = url
            dedup[url] = row
        elif dedup[url]["name"] == "Unknown channel" and row["name"] != "Unknown channel":
            dedup[url]["name"] = row["name"]
    rows = list(dedup.values())[:MAX_CANDIDATES]
    report["source_candidates_total"] = len(found)
    report["unique_candidates"] = len(dedup)
    report["candidates_processed"] = len(rows)
    return rows


def probe_stream(row):
    ffprobe = shutil.which("ffprobe")
    if not ffprobe:
        return {"technical_status": "tool_missing", "technical_reason": "ffprobe not installed"}
    command = [
        ffprobe, "-v", "error", "-rw_timeout", str(PROBE_TIMEOUT * 1_000_000),
        "-user_agent", USER_AGENT, "-select_streams", "v:0",
        "-show_entries", "stream=width,height,codec_name",
        "-of", "json", row["url"],
    ]
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=PROBE_TIMEOUT + 3)
        if result.returncode != 0:
            reason = (result.stderr or "ffprobe failed").strip()[-300:]
            return {"technical_status": "unreachable_or_unreadable", "technical_reason": reason}
        data = json.loads(result.stdout or "{}")
        streams = data.get("streams") or []
        if not streams:
            return {"technical_status": "no_video", "technical_reason": "no video stream detected"}
        stream = streams[0]
        width, height = int(stream.get("width") or 0), int(stream.get("height") or 0)
        passed = width >= MIN_WIDTH and height >= MIN_HEIGHT
        return {
            "technical_status": "pass" if passed else "below_resolution",
            "technical_reason": "measured video dimensions" if passed else "measured dimensions below 1280x720",
            "width": width, "height": height, "codec": stream.get("codec_name", ""),
        }
    except subprocess.TimeoutExpired:
        return {"technical_status": "timeout", "technical_reason": f"probe exceeded {PROBE_TIMEOUT + 3}s"}
    except Exception as exc:
        return {"technical_status": "error", "technical_reason": f"{type(exc).__name__}: {str(exc)[:200]}"}


def capture_frame(url: str, dest: Path):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        return False, "ffmpeg not installed"
    cmd = [
        ffmpeg, "-hide_banner", "-loglevel", "error", "-y",
        "-user_agent", USER_AGENT, "-rw_timeout", str(PROBE_TIMEOUT * 1_000_000),
        "-i", url, "-frames:v", "1", "-vf", "scale=640:-2",
        "-q:v", "5", str(dest),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=PROBE_TIMEOUT + 8)
        if result.returncode == 0 and dest.exists() and dest.stat().st_size > 0:
            return True, ""
        return False, (result.stderr or "frame extraction failed")[-250:]
    except subprocess.TimeoutExpired:
        return False, "frame extraction timed out"
    except Exception as exc:
        return False, f"{type(exc).__name__}: {str(exc)[:200]}"


def vision_triage(row, image_path: Path):
    if not VISION_KEY:
        return {"vision_status": "not_configured", "vision_label": "pending_local_review",
                "vision_reason": "cloud vision API key is not configured"}
    try:
        encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")
        payload = {
            "model": VISION_MODEL,
            "temperature": 0,
            "max_tokens": 250,
            "messages": [{
                "role": "system",
                "content": (
                    "You are a conservative IPTV screenshot triage assistant. This is only one frame. "
                    "Do not claim channel identity from a logo alone. Do not blacklist. "
                    "Return JSON only with fields risk (possible_shopping, possible_impersonation, "
                    "ordinary_broadcast, unclear), confidence (low/medium/high), visible_evidence "
                    "(short factual description), needs_local_review (always true). If evidence is "
                    "insufficient choose unclear."
                )
            }, {
                "role": "user",
                "content": [
                    {"type": "text", "text": f"Channel metadata label: {row['name']}. Assess only visible evidence; metadata may be wrong."},
                    {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + encoded, "detail": "low"}}
                ]
            }]
        }
        req = urllib.request.Request(
            VISION_BASE + "/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={"Authorization": "Bearer " + VISION_KEY,
                     "Content-Type": "application/json", "User-Agent": USER_AGENT},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as response:
            result = json.loads(response.read().decode("utf-8"))
        text = result["choices"][0]["message"]["content"]
        match = re.search(r"\{.*\}", text, flags=re.S)
        if not match:
            raise ValueError("model did not return a JSON object")
        obj = json.loads(match.group(0))
        allowed = {"possible_shopping", "possible_impersonation", "ordinary_broadcast", "unclear"}
        risk = obj.get("risk") if obj.get("risk") in allowed else "unclear"
        return {
            "vision_status": "completed",
            "vision_label": "pending_local_review",
            "vision_risk_hint": risk,
            "vision_confidence": str(obj.get("confidence", "low"))[:20],
            "vision_evidence": str(obj.get("visible_evidence", ""))[:500],
            "vision_needs_local_review": True,
        }
    except urllib.error.HTTPError as exc:
        # Do not include request headers or secret values in logs.
        return {"vision_status": "error", "vision_label": "pending_local_review",
                "vision_reason": f"HTTP {exc.code}; check provider endpoint/model/quota"}
    except Exception as exc:
        return {"vision_status": "error", "vision_label": "pending_local_review",
                "vision_reason": f"{type(exc).__name__}: {str(exc)[:250]}"}


def write_m3u(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#EXTM3U\n")
        for row in rows:
            name = str(row.get("name", "Unknown channel")).replace("\n", " ").replace("\r", " ")
            handle.write(f'#EXTINF:-1,{name}\n{row["url"]}\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    SHOTS.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": now_iso(),
        "pipeline": "cloud_technical_prescreen_plus_optional_vision_triage",
        "final_approval": False,
        "local_visual_review_required": True,
        "sources": [],
        "notes": [
            "This report is a candidate feed, not a final approved channel list.",
            "Cloud vision analyzes at most one frame per selected stream; it cannot prove identity.",
            "Vision uncertainty, missing credentials, and technical failures are not blacklist evidence.",
            "Local Ollama multi-frame review and trusted-reference checks are mandatory.",
        ],
    }
    rows = fetch_candidates(report)
    all_candidates = []
    technical_pass = []
    vision_done = 0
    for index, row in enumerate(rows, start=1):
        row.update({"checked_at_utc": now_iso(), "technical_status": "pending",
                    "vision_status": "pending", "vision_label": "pending_local_review"})
        row.update(probe_stream(row))
        if row["technical_status"] == "pass":
            technical_pass.append(row)
            if vision_done < VISION_MAX_ITEMS:
                safe_name = re.sub(r"[^A-Za-z0-9_-]+", "_", row["name"])[:45] or "channel"
                shot = SHOTS / f"{index:05d}_{safe_name}.jpg"
                ok, reason = capture_frame(row["url"], shot)
                row["screenshot_status"] = "captured" if ok else "failed"
                if ok:
                    vision_done += 1
                    row.update(vision_triage(row, shot))
                else:
                    row.update({"vision_status": "frame_failed", "vision_label": "pending_local_review",
                                "vision_reason": reason})
            else:
                row.update({"vision_status": "limit_reached", "vision_label": "pending_local_review",
                            "vision_reason": "daily vision item cap reached"})
        else:
            row.update({"vision_status": "not_run_technical_gate", "vision_label": "pending_local_review"})
        all_candidates.append(row)
        if index % 25 == 0:
            print(f"Processed {index}/{len(rows)} candidates; technical pass={len(technical_pass)}")

    fields = sorted({key for row in all_candidates for key in row})
    with (OUT / "candidates.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in all_candidates:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})

    write_m3u(OUT / "all_candidates.m3u", all_candidates)
    write_m3u(OUT / "technical_pass.m3u", technical_pass)
    report.update({
        "finished_at_utc": now_iso(),
        "technical_pass_count": len(technical_pass),
        "vision_completed_count": sum(r.get("vision_status") == "completed" for r in all_candidates),
        "vision_error_count": sum(r.get("vision_status") == "error" for r in all_candidates),
        "pending_local_review_count": len(all_candidates),
        "output_files": ["all_candidates.m3u", "technical_pass.m3u", "candidates.csv", "report.json"],
    })
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "generated_at_utc", "source_candidates_total", "unique_candidates",
        "candidates_processed", "technical_pass_count", "vision_completed_count",
        "vision_error_count", "pending_local_review_count"
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
