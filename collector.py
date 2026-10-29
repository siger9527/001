#!/usr/bin/env python3
"""Public IPTV playlist collector and conservative cloud pre-screen.

No stream is considered finally approved here. Local visual review remains mandatory.
"""
from __future__ import annotations

import csv
from concurrent.futures import ThreadPoolExecutor
import json
import os
import re
import shutil
import subprocess
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from url_policy import public_http_url
from resource_sniffer import sniff_resource

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "output"
SOURCES_FILE = ROOT / "config" / "sources.txt"
MAX_CANDIDATES = max(1, int(os.getenv("MAX_CANDIDATES", "300")))
PROBE_TIMEOUT = max(4, int(os.getenv("PROBE_TIMEOUT_SECONDS", "12")))
USER_AGENT = "IPTVCloudPrescreen/1.0 (GitHub Actions; conservative public playlist audit)"
MIN_WIDTH, MIN_HEIGHT = 1280, 720
URL_POLICY_REJECTIONS = 0


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
        if line and not line.startswith("#") and public_http_url(line):
            rows.append(line)
    return list(dict.fromkeys(rows))


def extinf_display_name(line: str) -> str:
    # EXTINF attributes can contain commas inside quoted values. The display name
    # starts after the last comma that is outside a quoted string.
    quoted = False
    last_comma = -1
    escaped = False
    for index, char in enumerate(line):
        if char == '"' and not escaped:
            quoted = not quoted
        elif char == ',' and not quoted:
            last_comma = index
        if char == "\\" and not escaped:
            escaped = True
        else:
            escaped = False
    if last_comma < 0:
        return "Unknown channel"
    name = line[last_comma + 1:].strip()
    name = re.sub(r"\s+", " ", name)[:200]
    return name or "Unknown channel"


def parse_m3u(text: str, source: str):
    global URL_POLICY_REJECTIONS
    entries, name = [], None
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#EXTINF"):
            name = extinf_display_name(line)
        elif line and not line.startswith("#"):
            if public_http_url(line):
                entries.append({"name": name or "Unknown channel", "url": line, "source": source})
            elif line.lower().startswith(("http://", "https://")):
                URL_POLICY_REJECTIONS += 1
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
            before = URL_POLICY_REJECTIONS
            rows = parse_m3u(text, source)
            rejected = URL_POLICY_REJECTIONS - before
            item.update(status="ok", candidates=len(rows), rejected_by_url_policy=rejected)
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
    rows = list(dedup.values())
    report["candidate_limit_applied_to_probing"] = MAX_CANDIDATES
    if len(rows) <= MAX_CANDIDATES:
        probe_rows = rows
    elif MAX_CANDIDATES == 1:
        probe_rows = [rows[0]]
    else:
        # Spread the bounded probe budget across the whole source list instead of
        # probing only alphabetically early channel names every day.
        indexes = sorted({round(i * (len(rows) - 1) / (MAX_CANDIDATES - 1)) for i in range(MAX_CANDIDATES)})
        probe_rows = [rows[i] for i in indexes]
    report["source_candidates_total"] = len(found)
    report["unique_candidates"] = len(dedup)
    report["candidates_processed"] = len(probe_rows)
    report["candidates_published_all"] = len(rows)
    report["url_policy_rejections"] = URL_POLICY_REJECTIONS
    return rows, probe_rows


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


def apply_selected_probe(row, probes, resource_type):
    """Apply the best passing probe and publish its actual media URL, not its wrapper page."""
    passing = [item for item in probes if item.get("technical_status") == "pass"]
    if not passing:
        if probes:
            row.update(probes[0])
            row["variant_probe_count"] = len(probes)
            row["variant_probe_failures"] = [item.get("technical_reason", "") for item in probes]
        return row
    selected = max(passing, key=lambda item: (
        item.get("height", 0), item.get("width", 0), item.get("variant_bandwidth", 0)
    ))
    row.update(selected)
    target_url = selected.get("variant_url")
    if target_url:
        row["url"] = target_url
    if resource_type == "html_page":
        row["technical_reason"] = "an embedded media manifest passed measured video checks"
    else:
        row["technical_reason"] = "a discovered HLS variant passed measured resolution checks"
    return row


def write_m3u(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        handle.write("#EXTM3U\n")
        for row in rows:
            name = str(row.get("name", "Unknown channel")).replace("\n", " ").replace("\r", " ")
            handle.write(f'#EXTINF:-1,{name}\n{row["url"]}\n')


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    report = {
        "generated_at_utc": now_iso(),
        "probe_workers": max(1, min(8, int(os.getenv("PROBE_WORKERS", "8")))),
        "pipeline": "cloud_technical_prescreen_only",
        "final_approval": False,
        "local_visual_review_required": True,
        "sources": [],
        "notes": [
            "This report is a candidate feed, not a final approved channel list.",
            "Local Ollama multi-frame review and trusted-reference checks are mandatory.",
            "Private, loopback, link-local, reserved IP literals and local-only hostnames are excluded by URL policy.",
            "URL policy is defense-in-depth; it does not guarantee safety against public host redirects or DNS rebinding.",
        ],
    }
    global URL_POLICY_REJECTIONS
    URL_POLICY_REJECTIONS = 0
    all_source_rows, rows = fetch_candidates(report)

    def process_candidate(row):
        row.update({"checked_at_utc": now_iso(), "technical_status": "pending",
                    "vision_status": "pending_local_review", "vision_label": "pending_local_review"})
        row["original_url"] = row["url"]
        sniff = sniff_resource(row["url"], timeout=min(PROBE_TIMEOUT, 8))
        row["sniff_input_url"] = row["url"]
        row["sniff_status"] = sniff["sniff_status"]
        row["sniff_resource_type"] = sniff["resource_type"]
        row["sniff_content_type"] = sniff["content_type"]
        row["sniff_final_url"] = sniff["final_url"]
        row["sniff_reason"] = sniff["sniff_reason"]
        row["embedded_manifest_count"] = len(sniff["embedded_manifests"])
        variants = sniff["hls_variants"]
        # Prioritize likely HD variants so a large master playlist does not waste
        # the bounded probe budget on low-resolution entries listed first.
        ranked_variants = sorted(
            variants,
            key=lambda item: (item.get("height", 0), item.get("width", 0), item.get("bandwidth", 0)),
            reverse=True,
        )
        targets = ranked_variants[:8]
        if not targets and sniff["resource_type"] == "html_page":
            targets = [{"url": item, "width": 0, "height": 0, "bandwidth": 0, "codecs": ""}
                       for item in sniff["embedded_manifests"][:8]]
        if targets:
            probes = []
            for target in targets:
                result = probe_stream({"url": target["url"]})
                result.update({"variant_url": target["url"], "variant_width_hint": target["width"],
                               "variant_height_hint": target["height"], "variant_bandwidth": target["bandwidth"]})
                probes.append(result)
            apply_selected_probe(row, probes, sniff["resource_type"])
        else:
            row.update(probe_stream(row))
        if row["technical_status"] == "pass":
            row.update({"vision_status": "not_run_cloud_vision",
                        "vision_reason": "cloud stage is technical-only; local visual review is required"})
        else:
            row.update({"vision_status": "not_run_technical_gate"})
        return row

    all_candidates = []
    technical_pass = []
    workers = max(1, min(8, int(os.getenv("PROBE_WORKERS", "8"))))
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for index, row in enumerate(pool.map(process_candidate, rows), start=1):
            all_candidates.append(row)
            if row["technical_status"] == "pass":
                technical_pass.append(row)
            if index % 25 == 0 or index == len(rows):
                print(f"Processed {index}/{len(rows)} candidates; technical pass={len(technical_pass)}", flush=True)

    fields = sorted({key for row in all_candidates for key in row})
    with (OUT / "candidates.csv").open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for row in all_candidates:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value
                             for key, value in row.items()})

    write_m3u(OUT / "all_candidates.m3u", all_source_rows)
    write_m3u(OUT / "technical_pass.m3u", technical_pass)
    write_m3u(OUT / "all.m3u", all_source_rows)
    write_m3u(OUT / "hd.m3u", technical_pass)
    report.update({
        "finished_at_utc": now_iso(),
        "technical_pass_count": len(technical_pass),
        "pending_local_review_count": len(all_candidates),
        "output_files": ["all.m3u", "hd.m3u", "all_candidates.m3u", "technical_pass.m3u", "candidates.csv", "report.json"],
        "csv_scope": "deterministic evenly distributed sample selected for technical probing",
        "all_candidates_m3u_scope": "all unique playlist URLs collected from configured sources after URL policy filtering",
    })
    (OUT / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in (
        "generated_at_utc", "source_candidates_total", "unique_candidates",
        "candidates_processed", "technical_pass_count", "pending_local_review_count", "url_policy_rejections",
    )}, ensure_ascii=False))


if __name__ == "__main__":
    main()
