"""Deterministic date parsing (utils/arabic_days): numeric, relative and day-name dates."""

import sys
import unittest
from datetime import datetime, timedelta

sys.path.insert(0, 'cloud')

from app.utils.arabic_days import (
    parse_numeric_date,
    parse_relative_simple,
    parse_date_from_text,
)
from app.utils.time import USER_TZ


class TestDateParsingDeterministic(unittest.TestCase):
    """Test deterministic date parsing without AI."""

    def test_numeric_date_yyyy_mm_dd_slash(self):
        """YYYY/MM/DD format."""
        iso = parse_numeric_date("2026/06/15")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 15)
        self.assertEqual(dt.hour, 9)  # default hour

    def test_numeric_date_dd_mm_yyyy_slash(self):
        """DD/MM/YYYY format."""
        iso = parse_numeric_date("15/06/2026")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 15)

    def test_numeric_date_yyyy_mm_dd_dash(self):
        """YYYY-MM-DD format."""
        iso = parse_numeric_date("2026-06-15")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 15)

    def test_numeric_date_compact_yyyymmdd(self):
        """Compact YYYYMMDD format."""
        iso = parse_numeric_date("20260615")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.year, 2026)
        self.assertEqual(dt.month, 6)
        self.assertEqual(dt.day, 15)

    def test_relative_date_after_n_days(self):
        """بعد X يوم format."""
        iso = parse_relative_simple("بعد 3 أيام")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        now = datetime.now(USER_TZ)
        expected = now.date() + timedelta(days=3)
        self.assertEqual(dt.date(), expected)

    def test_relative_date_tomorrow(self):
        """بكرا / غدا formats."""
        iso = parse_relative_simple("بكرا")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        now = datetime.now(USER_TZ)
        expected = now.date() + timedelta(days=1)
        self.assertEqual(dt.date(), expected)

    def test_relative_date_after_weeks(self):
        """بعد أسبوع format."""
        iso = parse_relative_simple("بعد أسبوع")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        now = datetime.now(USER_TZ)
        expected = now.date() + timedelta(weeks=1)
        self.assertEqual(dt.date(), expected)

    def test_combined_parse_day_name(self):
        """parse_date_from_text: day name (highest priority)."""
        iso = parse_date_from_text("الجمعة")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        # should be next Friday
        self.assertEqual(dt.weekday(), 4)  # Friday

    def test_combined_parse_numeric(self):
        """parse_date_from_text: numeric fallback."""
        iso = parse_date_from_text("15/06/2026")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        self.assertEqual(dt.day, 15)

    def test_combined_parse_relative(self):
        """parse_date_from_text: relative fallback."""
        iso = parse_date_from_text("بعد 2 أيام")
        self.assertIsNotNone(iso)
        dt = datetime.fromisoformat(iso)
        now = datetime.now(USER_TZ)
        expected = now.date() + timedelta(days=2)
        self.assertEqual(dt.date(), expected)


if __name__ == "__main__":
    unittest.main()
