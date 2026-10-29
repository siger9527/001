# IPTV Cloud Pre-screen

GitHub Actions pipeline for public IPTV playlist discovery, technical pre-screening, and daily candidate reports. This does **not** certify channel identity or replace local Ollama review.

## Outputs
Each successful run publishes stable subscription URLs from the `daily-output` branch:
- **HD feed (technical pass):** [hd.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/hd.m3u)
- **All candidates:** [all.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/all.m3u)
- Detailed technical feed: [technical_pass.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/technical_pass.m3u)
- Full candidate list: [all_candidates.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/all_candidates.m3u)
- Report: [report.json](https://raw.githubusercontent.com/siger9527/001/daily-output/report.json)

Schedule: daily at **10:30 and 22:30 Singapore time** (02:30 and 14:30 UTC).

Each scheduled/manual run also publishes an artifact named `iptv-candidates` containing:
- `all_candidates.m3u`: deduplicated candidate URLs that pass URL-policy filtering (not approved)
- `technical_pass.m3u`: reachable streams with measured resolution >= 1280x720
- `candidates.csv` and `report.json`: per-stream technical status, URL-policy counts, and local-review flags

## Configure
1. Edit `config/sources.txt` to add/remove playlist URLs.
2. Run Actions → Daily IPTV Cloud Pre-screen → Run workflow to test immediately. Scheduled runs are daily at 02:30 and 14:30 UTC (10:30 and 22:30 Singapore time).

No visual-model API key is required. The cloud stage collects playlists, deduplicates URLs, applies conservative URL filtering, probes video dimensions, and publishes candidates. The Windows local application performs visual review.

## URL safety policy
- Only HTTP(S) URLs are eligible.
- URLs containing embedded credentials are rejected.
- Loopback, private, link-local, reserved/non-global IP literals and local-only hostnames (such as `.local` and `.internal`) are rejected before publishing or probing.
- Rejected candidate counts are included in `report.json` and per-source status rows.
- This is defense-in-depth, not a complete SSRF boundary: redirects and DNS rebinding are not fully prevented. Do not run untrusted streams in a privileged network environment.

## Important
- Public playlist inclusion does not establish permission, legality, channel identity, or reliability.
- All cloud candidates remain subject to local visual review; cloud technical checks do not approve channel identity or content.
- The local Windows application must independently perform multi-frame visual review, channel reference checks, blacklisting with evidence, aggregation, and final M3U generation.
- GitHub-hosted runners have limited time/network access. A stream may be temporarily unreachable. Failures are reported, not treated as proof of bad content.
- The collector intentionally avoids exposing secrets in logs or reports.


## Resource sniffing
The cloud pre-screen performs bounded HTTP inspection for each selected candidate:
- identifies HLS master/media playlists, DASH MPD manifests, direct audio/video responses, and HTML pages;
- parses HLS master variants and probes up to eight discovered variants, selecting a passing variant based on measured dimensions;
- extracts up to 50 explicit embedded HLS/DASH manifest links from HTML without running JavaScript;
- validates discovered URLs and redirect destinations against the public URL policy;
- records sniff type, final URL, content type, manifest count, variant probe result and reason in `candidates.csv`.

This is a bounded sniffer, not a general-purpose website crawler. It does not execute scripts, bypass access controls, or infer channel identity. HTML discovery is heuristic; providers requiring cookies, tokens, or special headers may remain undetected. DNS rebinding is not fully prevented.
