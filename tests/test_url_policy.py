import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("url_policy", ROOT / "url_policy.py")
url_policy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(url_policy)


class PublicUrlPolicyTests(unittest.TestCase):
    def test_accepts_public_http_and_https_urls(self):
        self.assertTrue(url_policy.public_http_url("https://example.com/live.m3u8"))
        self.assertTrue(url_policy.public_http_url("http://cdn.example.org:8080/tv"))

    def test_rejects_loopback_private_and_link_local_ip_literals(self):
        for url in (
            "http://127.0.0.1/live",
            "http://10.0.0.8/live",
            "http://192.168.1.10/live",
            "http://169.254.169.254/latest/meta-data/",
            "http://[::1]/live",
            "http://[fe80::1]/live",
        ):
            with self.subTest(url=url):
                self.assertFalse(url_policy.public_http_url(url))

    def test_rejects_local_names_and_single_label_hosts(self):
        for url in (
            "http://localhost/live",
            "http://router.local/live",
            "http://service.internal/live",
            "http://printer/live",
        ):
            with self.subTest(url=url):
                self.assertFalse(url_policy.public_http_url(url))

    def test_rejects_credentials_and_non_http_schemes(self):
        for url in (
            "https://user:password@example.com/live",
            "file:///etc/passwd",
            "rtmp://example.com/live",
            "https:///missing-host",
        ):
            with self.subTest(url=url):
                self.assertFalse(url_policy.public_http_url(url))

    def test_rejects_malformed_ports_and_surrounding_whitespace(self):
        self.assertFalse(url_policy.public_http_url("https://example.com:bad/live"))
        self.assertFalse(url_policy.public_http_url(" https://example.com/live "))


if __name__ == "__main__":
    unittest.main()
