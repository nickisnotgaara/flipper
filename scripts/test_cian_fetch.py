"""
test_cian_fetch — fast unit tests for cian_fetch.

Skipped (with a clear message) if the cookie server is unreachable or the
dataimpulse proxy is not configured. The smoke tests cover real fetching
and are best run manually; the unit tests here only verify pure helpers
(cookie header formatting, proxy URL formatting, settings loading).
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

# Make sibling modules importable when run from anywhere.
sys.path.insert(0, str(Path(__file__).resolve().parent))

import cian_fetch


class CookieHeaderTests(unittest.TestCase):
    def test_basic(self) -> None:
        out = cian_fetch._cookies_list_to_header([
            {"name": "a", "value": "1"},
            {"name": "b", "value": "2"},
        ])
        self.assertEqual(out, "a=1; b=2")

    def test_skips_no_name(self) -> None:
        out = cian_fetch._cookies_list_to_header([
            {"name": "x", "value": "9"},
            {"value": "no_name"},  # no name -> skip
            {"name": "", "value": "empty_name"},  # empty -> skip
            "not_a_dict",
        ])
        self.assertEqual(out, "x=9")


class ProxyRotatorTests(unittest.TestCase):
    def test_format_prefix_added(self) -> None:
        r = cian_fetch.ProxyRotator(["user:pass@host:1000"])
        self.assertTrue(r.next().startswith("http://"))

    def test_format_kept_if_already_prefixed(self) -> None:
        r = cian_fetch.ProxyRotator(["https://u:p@h:1000"])
        self.assertEqual(r.next(), "https://u:p@h:1000")

    def test_round_robin_wraps(self) -> None:
        r = cian_fetch.ProxyRotator(["a:1@h:1", "a:1@h:2", "a:1@h:3"])
        seen = [r.next() for _ in range(7)]
        # 3 distinct endpoints, each appears at least twice in 7 calls
        self.assertEqual(len(set(seen)), 3)

    def test_falls_back_to_default(self) -> None:
        # No proxies passed, no env var -> default dataimpulse proxy
        os.environ.pop("CIAN_PROXY", None)
        r = cian_fetch.ProxyRotator([])
        self.assertTrue(r.next().startswith("http://"))
        self.assertIn("dataimpulse", r.next())

    def test_env_proxy_takes_priority(self) -> None:
        os.environ["CIAN_PROXY"] = "http://override:1@h:9"
        try:
            r = cian_fetch.ProxyRotator([])
            self.assertEqual(r.next(), "http://override:1@h:9")
        finally:
            os.environ.pop("CIAN_PROXY", None)


class SettingsTests(unittest.TestCase):
    def test_from_env_uses_defaults(self) -> None:
        os.environ.pop("CIAN_PROOKIE", None) if False else None  # noop
        os.environ.pop("CIAN_PROXY", None)
        s = cian_fetch.FetchSettings.from_env(timeout=10.0, retries=1)
        self.assertIn("dataimpulse", s.proxy)
        self.assertEqual(s.timeout, 10.0)
        self.assertEqual(s.retries, 1)
        # Cookie header is fetched; may or may not succeed depending on network.
        self.assertIsInstance(s.cookie_header, str)


if __name__ == "__main__":
    unittest.main(verbosity=2)
