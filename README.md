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
- `all_candidates.m3u`: deduplicated candidate URLs (not approved)
- `technical_pass.m3u`: reachable streams with measured resolution >= 1280x720
- `candidates.csv` and `report.json`: per-stream technical status and local-review flags

## Configure
1. Edit `config/sources.txt` to add/remove playlist URLs.
2. Run Actions → Daily IPTV Cloud Pre-screen → Run workflow to test immediately. Scheduled runs are daily at 02:30 and 14:30 UTC (10:30 and 22:30 Singapore time).

No visual-model API key is required. The cloud stage only collects playlists, deduplicates URLs, probes video dimensions, and publishes candidates. The Windows local application performs visual review.

## Important
- Public playlist inclusion does not establish permission, legality, channel identity, or reliability.
- All cloud candidates remain subject to local visual review; cloud technical checks do not approve channel identity or content.
- The local Windows application must independently perform multi-frame visual review, channel reference checks, blacklisting with evidence, aggregation, and final M3U generation.
- GitHub-hosted runners have limited time/network access. A stream may be temporarily unreachable. Failures are reported, not treated as proof of bad content.
- The collector intentionally avoids exposing secrets in logs or reports.
