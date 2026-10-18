import html
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def has_summary_separator(source):
    return bool(re.search("[·•]", html.unescape(source)))


class DesignTests(unittest.TestCase):
    def test_apartment_ui_uses_separate_fields_instead_of_dot_summaries(self):
        paths = [ROOT / "static/index.html", *ROOT.glob("static/prototype/compare-*.html"),
                 ROOT / "static/prototype/comparison.html",
                 ROOT / "static/prototype/listing-photos.js"]
        for path in paths:
            with self.subTest(path=path.name):
                self.assertFalse(has_summary_separator(path.read_text()),
                                 "Give each value a purposeful field or remove it. "
                                 "Keep search limits in their controls; remove dot-separated summaries.")

    def test_guard_catches_the_reported_mistake_and_encoded_variants(self):
        for source in ("3 apartments · Up to 850 € · At least 30 m²",
                       "3 apartments &middot; Up to 850 €",
                       "3 apartments &#183; Up to 850 €",
                       "3 apartments • Up to 850 €"):
            self.assertTrue(has_summary_separator(source))
        self.assertFalse(has_summary_separator("<th>Monthly total</th><th>Space</th>"))
