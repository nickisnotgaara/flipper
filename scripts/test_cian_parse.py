"""
Tests for cian_parse — pure parser, no I/O.

Run:  py scripts/test_cian_parse.py
or:   py -m pytest scripts/test_cian_parse.py
"""
from __future__ import annotations

import io
import json
import sys
import unittest
from pathlib import Path

# stdout is sometimes captured/mangled on Windows; force utf-8 line buffering.
try:
    sys.stdout.reconfigure(encoding="utf-8", line_buffering=True)
    sys.stderr.reconfigure(encoding="utf-8", line_buffering=True)
except Exception:
    pass

sys.path.insert(0, str(Path(__file__).resolve().parent))

from cian_parse import (  # noqa: E402
    parse_offer,
    parse_house_page,
    _extract_offer_data,
    _scan_balanced_array,
    BuildingRecord,
    OfferRecord,
)

REPO = Path(__file__).resolve().parents[1]
GOOD_HTML = REPO.parent / "flippercrawl" / "cian-flat.html"
ALT_HTML = REPO / "services" / "parsers" / "cian_sold" / "examples" / "cian-sale-flat.html"
CAPTCHA_HTML = REPO / "data" / "logs" / "cian_327856435.html"


class TestScanBalancedArray(unittest.TestCase):
    def test_simple_array(self):
        s = "[1, 2, 3]"
        self.assertEqual(_scan_balanced_array(s, 0), s)

    def test_nested(self):
        s = '[{"a": 1}, [2, 3]]'
        self.assertEqual(_scan_balanced_array(s, 0), s)

    def test_string_with_escapes(self):
        s = r'["a\"b", "c"]'
        self.assertEqual(_scan_balanced_array(s, 0), s)

    def test_unterminated(self):
        s = "[1, 2, "
        self.assertIsNone(_scan_balanced_array(s, 0))


class TestExtractOfferData(unittest.TestCase):
    def test_no_marker(self):
        self.assertIsNone(_extract_offer_data("<html>no cian here</html>"))

    def test_captcha(self):
        if not CAPTCHA_HTML.exists():
            self.skipTest(f"missing fixture {CAPTCHA_HTML}")
        # captcha page should have no _cianConfig marker
        html = CAPTCHA_HTML.read_text(encoding="utf-8", errors="replace")
        self.assertIsNone(_extract_offer_data(html))


class TestParseOffer(unittest.TestCase):
    def setUp(self):
        if not GOOD_HTML.exists():
            self.skipTest(f"missing fixture {GOOD_HTML}")

    def test_real_offer(self):
        html = GOOD_HTML.read_text(encoding="utf-8", errors="replace")
        rec = parse_offer(html)
        self.assertIsNotNone(rec, "expected offerData to be extractable")
        assert rec is not None
        self.assertEqual(rec.cian_id, 330637131)
        self.assertEqual(rec.cian_house_id, 35703)
        self.assertIsNotNone(rec.full_address)
        self.assertIn("Варшавское", rec.full_address or "")
        self.assertIn("145К1", rec.full_address or "")
        self.assertAlmostEqual(rec.lat or 0, 55.580482, places=5)
        self.assertAlmostEqual(rec.lng or 0, 37.598061, places=5)
        # building
        self.assertIsNotNone(rec.building)
        b = rec.building
        self.assertEqual(b.year_built, 1978)
        self.assertEqual(b.levels, 16)
        self.assertEqual(b.material, "panel")
        # price & area & rooms
        self.assertIsInstance(rec.price, int)
        self.assertGreater(rec.price or 0, 1_000_000)
        self.assertIsInstance(rec.area, float)
        self.assertGreater(rec.area or 0, 0)
        self.assertIn(rec.rooms, (2, 3))  # 3-комн in the title
        # url
        self.assertEqual(rec.url, "https://www.cian.ru/sale/flat/330637131/")

    def test_html_without_offer_data(self):
        rec = parse_offer("<html><body>plain page</body></html>")
        self.assertIsNone(rec)

    def test_alt_html_also_works(self):
        if not ALT_HTML.exists():
            self.skipTest(f"missing fixture {ALT_HTML}")
        html = ALT_HTML.read_text(encoding="utf-8", errors="replace")
        # alt HTML might not have the _cianConfig marker (older format)
        rec = parse_offer(html)
        # we accept either None or a valid record
        if rec is not None:
            self.assertIsInstance(rec, OfferRecord)


class TestParseHousePage(unittest.TestCase):
    def test_no_marker(self):
        self.assertIsNone(parse_house_page("<html></html>"))


class TestDataclassImmutability(unittest.TestCase):
    def test_offer_record_frozen(self):
        r = OfferRecord(cian_id=1, cian_house_id=2)
        with self.assertRaises(Exception):
            r.cian_id = 5  # type: ignore

    def test_building_record_frozen(self):
        b = BuildingRecord(year_built=1980, levels=9)
        with self.assertRaises(Exception):
            b.year_built = 2000  # type: ignore


if __name__ == "__main__":
    # When called from PowerShell, stdout gets mangled (UTF-8 mixed with
    # the system code page). Run via `py -X utf8` OR with a log file path
    # as argv[1] to capture results cleanly.
    log_path = sys.argv[1] if len(sys.argv) > 1 else None
    if log_path:
        # Use a real test runner to capture results without involving stdout.
        import unittest as _u
        from io import StringIO
        buf = StringIO()
        runner = _u.TextTestRunner(stream=buf, verbosity=2)
        loader = _u.TestLoader()
        suite = loader.loadTestsFromModule(sys.modules[__name__])
        result = runner.run(suite)
        Path(log_path).write_text(buf.getvalue(), encoding="utf-8")
        sys.exit(0 if result.wasSuccessful() else 1)
    unittest.main(verbosity=2)
