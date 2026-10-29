"""Conservative URL policy for the public IPTV discovery pipeline.

This is a defense-in-depth filter, not a substitute for network isolation.
"""
from __future__ import annotations

import ipaddress
import urllib.parse


_BLOCKED_HOSTS = {"localhost", "localhost.localdomain", "metadata.google.internal"}
_BLOCKED_SUFFIXES = (".localhost", ".local", ".internal", ".test", ".invalid")


def public_http_url(value: str) -> bool:
    """Return True only for syntactically valid HTTP(S) URLs without local targets."""
    if not isinstance(value, str) or not value or value != value.strip():
        return False
    try:
        parsed = urllib.parse.urlsplit(value)
        if parsed.scheme.lower() not in {"http", "https"}:
            return False
        if not parsed.hostname or parsed.username is not None or parsed.password is not None:
            return False
        host = parsed.hostname.rstrip(".").lower()
        if host in _BLOCKED_HOSTS or host.endswith(_BLOCKED_SUFFIXES):
            return False
        # Require a fully qualified hostname for names, while allowing public IP literals.
        try:
            address = ipaddress.ip_address(host)
        except ValueError:
            if "." not in host or any(not label for label in host.split(".")):
                return False
        else:
            if not address.is_global:
                return False
        # Reject malformed ports instead of allowing a later parser/prober to interpret them.
        _ = parsed.port
        return True
    except (ValueError, UnicodeError):
        return False
