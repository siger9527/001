# IPTV Cloud Pre-screen

GitHub Actions pipeline for public IPTV playlist discovery, technical pre-screening, optional cloud vision triage, and daily candidate reports. This does **not** certify channel identity or replace local Ollama review.

## Outputs
Each scheduled/manual run publishes stable raw-file URLs from the `daily-output` branch (after the first successful run):
- [technical_pass.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/technical_pass.m3u)
- [all_candidates.m3u](https://raw.githubusercontent.com/siger9527/001/daily-output/all_candidates.m3u)
- [candidates.csv](https://raw.githubusercontent.com/siger9527/001/daily-output/candidates.csv)
- [report.json](https://raw.githubusercontent.com/siger9527/001/daily-output/report.json)

Each scheduled/manual run also publishes an artifact named `iptv-candidates` containing:
- `all_candidates.m3u`: deduplicated candidate URLs (not approved)
- `technical_pass.m3u`: reachable streams with measured resolution >= 1280x720
- `candidates.csv` and `report.json`: per-stream technical and vision status
- `screenshots/`: sampled frames when FFmpeg can decode them

## Configure
1. In repository Settings → Secrets and variables → Actions, add secret `VISION_API_KEY` for a vision provider using the OpenAI-compatible Chat Completions API. Optional variables: `VISION_BASE_URL` (default `https://api.openai.com/v1`), `VISION_MODEL` (default `gpt-4o-mini`).
2. Edit `config/sources.txt` to add/remove playlist URLs.
3. Run Actions → Daily IPTV Cloud Pre-screen → Run workflow to test immediately. Scheduled run is daily at 02:30 UTC.

Without `VISION_API_KEY`, vision status is `not_configured`; technical collection still runs. Never put API keys in repository files.

## Important
- Public playlist inclusion does not establish permission, legality, channel identity, or reliability.
- A model result is a risk hint only. Uncertain, failed, or missing vision results remain `pending_local_review`; they are not auto-blacklisted.
- The local Windows application must independently perform multi-frame visual review, channel reference checks, blacklisting with evidence, aggregation, and final M3U generation.
- GitHub-hosted runners have limited time/network access. A stream may be temporarily unreachable. Failures are reported, not treated as proof of bad content.
- The collector intentionally avoids exposing secrets in logs or reports.
