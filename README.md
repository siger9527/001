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


## Local Windows review workbench

The repository now includes a loopback-only local review dashboard. It is intentionally separate from the cloud technical pre-screen: a cloud pass never equals channel approval.

### Start
1. Install Python 3.10+ and FFmpeg; make sure `python` and `ffmpeg` work in Command Prompt.
2. Ensure Ollama is running locally and the configured vision-capable model is installed. The default is `qwen3.5:9b-q4_k_m`; override with `OLLAMA_MODEL` if needed.
3. On Windows, double-click `启动本地IPTV审核工作台.bat`.
4. Open `http://127.0.0.1:8765/`.
5. Paste the content of `all_candidates.m3u` or another playlist into the import box. The database is stored under `local_data/`.

### Review and playlist rules
- `all.m3u` contains pending and approved candidates, but excludes entries explicitly rejected/blacklisted.
- `approved.m3u` contains only entries explicitly approved by a human reviewer.
- Duplicate imports do not reset prior review decisions.
- **Ollama is advisory only.** The local app captures up to three frames with FFmpeg and requests a JSON description/match recommendation. It never automatically approves a stream.
- Failed frame capture or model requests are reported; they are not silently treated as approval or rejection.
- The dashboard binds only to `127.0.0.1`. Do not change it to a public interface without adding authentication, CSRF protections, and network isolation.

### Local data and limitations
The SQLite database, saved review frames, and decisions live under `local_data/`. Back up that directory if review history matters. Stream URLs can contain expiring tokens; do not share candidate exports or logs publicly without reviewing them. The local sniffer and cloud checks are technical aids, not a guarantee of legality, channel identity, or continuous playback.


## Batch visual review (Windows local)

The local reviewer includes `batch_review.py` so hundreds of imported candidates do not need to be clicked one by one. Start the local workbench once to initialize its database, then stop it or leave it running; run the batch command from the repository directory in a second Command Prompt:

```powershell
python batch_review.py
```

Useful options:

- `python batch_review.py --status pending`: process pending-review candidates only (default).
- `python batch_review.py --status all`: scan all review statuses.
- `python batch_review.py --retry-failed`: retry only candidates with a recorded analysis error.
- `python batch_review.py --limit 20`: limit a run to the first 20 eligible candidates.
- `python batch_review.py --pause 1.5`: wait 1.5 seconds between candidates.

The runner prints live progress and writes `batch-review-report.csv` as it proceeds. Each row records review status, AI label/confidence, observed text, summary, and error reason. It saves errors to SQLite and continues to the next candidate rather than stopping the whole batch. The report may contain stream URLs (including temporary tokens); inspect it before sharing.

Batch analysis does not approve or reject anything. AI results are suggestions only; use the dashboard's human review decision before a channel enters `approved.m3u`. Analysis is sequential to avoid overloading an 8 GB VRAM local model. A channel can take up to the FFmpeg and Ollama timeouts, so a large batch may take a while.
