"""Bounded IPTV resource sniffer for public HTTP(S) media resources.

It inspects one resource at a time, validates redirects, and never treats discovery
as approval. It does not crawl arbitrary domains or execute page scripts.
"""
from __future__ import annotations

import re
import urllib.parse
import urllib.request
from typing import Any

from url_policy import public_http_url

MAX_BODY_BYTES = 2 * 1024 * 1024
DEFAULT_TIMEOUT = 8
USER_AGENT = "IPTVCloudSniffer/1.0"


class SafeRedirectHandler(urllib.request.HTTPRedirectHandler):
    """Reject redirect targets that violate the public URL policy."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        if not public_http_url(target):
            raise urllib.error.HTTPError(target, code, "redirect target rejected by URL policy", headers, fp)
        return super().redirect_request(req, fp, code, msg, headers, target)


def _opener():
    return urllib.request.build_opener(SafeRedirectHandler())


def _fetch(url: str, timeout: int = DEFAULT_TIMEOUT) -> tuple[str, str, bytes, int]:
    if not public_http_url(url):
        raise ValueError("URL rejected by public URL policy")
    request = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT,
        "Accept": "application/vnd.apple.mpegurl, application/x-mpegURL, application/dash+xml, video/*, audio/*, text/html, */*;q=0.5",
        "Range": f"bytes=0-{MAX_BODY_BYTES - 1}",
    })
    with _opener().open(request, timeout=timeout) as response:
        final_url = response.geturl()
        if not public_http_url(final_url):
            raise ValueError("final redirect URL rejected by public URL policy")
        body = response.read(MAX_BODY_BYTES + 1)
        if len(body) > MAX_BODY_BYTES:
            body = body[:MAX_BODY_BYTES]
        return final_url, response.headers.get("Content-Type", "").split(";", 1)[0].lower(), body, response.status


def _decode(body: bytes) -> str:
    return body.decode("utf-8-sig", errors="replace")


def parse_hls_variants(text: str, base_url: str) -> list[dict[str, Any]]:
    """Parse HLS master playlist variants; reject unsafe or malformed child URLs."""
    lines = [line.strip() for line in text.splitlines()]
    variants = []
    pending: dict[str, Any] | None = None
    for line in lines:
        if line.startswith("#EXT-X-STREAM-INF:"):
            attrs = line.split(":", 1)[1]
            pending = {}
            # HLS attribute lists use commas as separators except inside quoted values.
            parts, token, quoted, escaped = [], [], False, False
            for char in attrs:
                if char == '"' and not escaped:
                    quoted = not quoted
                if char == "," and not quoted:
                    parts.append("".join(token).strip())
                    token = []
                else:
                    token.append(char)
                if char == "\\\\" and not escaped:
                    escaped = True
                else:
                    escaped = False
            if token:
                parts.append("".join(token).strip())
            for part in parts:
                if "=" not in part:
                    continue
                key, value = part.split("=", 1)
                pending[key.strip()] = value.strip().strip('"')
        elif line and not line.startswith("#") and pending is not None:
            target = urllib.parse.urljoin(base_url, line)
            if public_http_url(target):
                resolution = pending.get("RESOLUTION", "")
                match = re.fullmatch(r"(\d{1,5})x(\d{1,5})", resolution)
                width, height = (int(match.group(1)), int(match.group(2))) if match else (0, 0)
                try:
                    bandwidth = int(pending.get("AVERAGE-BANDWIDTH", pending.get("BANDWIDTH", "0")))
                except ValueError:
                    bandwidth = 0
                variants.append({
                    "url": target, "width": width, "height": height,
                    "bandwidth": bandwidth, "codecs": pending.get("CODECS", ""),
                })
            pending = None
    # Preserve source order but remove duplicate child URLs.
    result, seen = [], set()
    for row in variants:
        if row["url"] not in seen:
            seen.add(row["url"])
            result.append(row)
    return result


def extract_embedded_media_urls(text: str, base_url: str) -> list[str]:
    """Extract explicit media URLs from HTML/text without executing scripts."""
    patterns = (
        r'''(?i)["']([^"'\s<>]+\.(?:m3u8?|mpd)(?:\?[^"'\s<>]*)?)["']''',
        r'''(?i)(?:src|href|file|source)\s*[:=]\s*["']([^"'\s<>]+)["']''',
    )
    found, seen = [], set()
    for pattern in patterns:
        for match in re.finditer(pattern, text):
            raw = match.group(1).replace("\\/", "/").replace("&amp;", "&")
            target = urllib.parse.urljoin(base_url, raw)
            path = urllib.parse.urlsplit(target).path.lower()
            if public_http_url(target) and path.endswith((".m3u", ".m3u8", ".mpd")) and target not in seen:
                seen.add(target)
                found.append(target)
    return found[:50]


def sniff_resource(url: str, timeout: int = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Classify an HTTP resource and expose safe HLS variants/embedded manifests."""
    result: dict[str, Any] = {
        "input_url": url, "sniff_status": "error", "resource_type": "unknown",
        "final_url": "", "content_type": "", "http_status": 0,
        "hls_variants": [], "embedded_manifests": [], "sniff_reason": "",
    }
    try:
        final_url, content_type, body, status = _fetch(url, timeout)
        text = _decode(body)
        prefix = text.lstrip()[:2048]
        result.update(final_url=final_url, content_type=content_type, http_status=status,
                      sniff_status="ok", sniff_reason="bounded HTTP response inspected")
        if prefix.startswith("#EXTM3U"):
            if "#EXT-X-STREAM-INF" in text:
                result["resource_type"] = "hls_master"
                result["hls_variants"] = parse_hls_variants(text, final_url)
            else:
                result["resource_type"] = "hls_media_playlist"
        elif content_type in ("application/dash+xml",) or "<MPD" in prefix or "<mpd" in prefix:
            result["resource_type"] = "dash_mpd"
        elif content_type.startswith("text/html") or re.search(r"(?i)<(?:!doctype\s+html|html\b)", prefix):
            result["resource_type"] = "html_page"
            result["embedded_manifests"] = extract_embedded_media_urls(text, final_url)
        elif content_type.startswith("video/") or content_type.startswith("audio/"):
            result["resource_type"] = "direct_media"
        elif content_type in ("application/vnd.apple.mpegurl", "application/x-mpegurl"):
            result["resource_type"] = "hls_media_playlist"
        else:
            result["resource_type"] = "unknown"
            result["sniff_reason"] = "HTTP response did not match a recognized media signature"
    except Exception as exc:
        result["sniff_reason"] = f"{type(exc).__name__}: {str(exc)[:240]}"
    return result


if __name__ == "__main__":
    import argparse
    import json
    parser = argparse.ArgumentParser(description="Inspect one public IPTV media resource")
    parser.add_argument("url")
    parser.add_argument("--timeout", type=int, default=DEFAULT_TIMEOUT)
    args = parser.parse_args()
    print(json.dumps(sniff_resource(args.url, args.timeout), ensure_ascii=False, indent=2))
