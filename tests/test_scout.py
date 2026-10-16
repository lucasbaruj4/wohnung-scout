import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from app import create_app
from scout import Collector, DEFAULTS, Store, evaluate, number, parse_detail, parse_search, validate_settings
from telegram_alerts import call, is_configured

SEARCH = '''<div class="offer_list_item" data-id="123">
<div class="card_body"><h2><a href="/wohnungen-in-Wuerzburg.123.html">Sunny flat</a></h2>
<div class="col-xs-11"><span>Wohnung | Würzburg Altstadt | Mainstraße</span></div>
<div class="middle"><b>730 €</b><span>01.11.2026</span><b>55 m²</b></div></div></div>'''
DETAIL = '''<div><span class="key_fact_detail">Gesamtmiete</span><b class="key_fact_value">730€</b></div>
<div class="row"><span class="section_panel_detail">Miete:</span><span class="section_panel_value">550€</span></div>
<div class="row"><span class="section_panel_detail">Nebenkosten:</span><span class="section_panel_value">180€</span></div>
<div class="row"><span class="section_panel_detail">Sonstige Kosten:</span><span class="section_panel_value">n.a.</span></div>
<div class="row"><span class="section_panel_detail">frei bis:</span><span class="section_panel_value">31.12.2026</span></div>'''
MODERN_SEARCH = '''<a class="wgg-list-card offer_list_item" data-id="789"
href="/wohnungen-in-Wuerzburg.789.html">
<div class="card-content"><div class="price-row"><div>
<span class="card-main-text">730 €</span><span class="card-subtitle">pro Monat</span></div></div>
<h2><span class="ad-title">Sunny flat</span></h2>
<div class="ad-subtitle"><span>Wohnung · Würzburg Altstadt · Example street</span></div>
<div class="middle-row"><div><span class="size-value">55 m²</span></div><div>01.11.2026</div></div>
</div></a>'''


class ScoutTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / "scout.db")

    def test_german_prices_and_real_card_layout(self):
        self.assertEqual(number("1.250,50 €"), 1250.5)
        row = parse_search(SEARCH)[0]
        self.assertEqual((row["rent"], row["size"], row["id"]), (730, 55, "123"))
        self.assertTrue(row["url"].startswith("https://www.wg-gesucht.de/"))

    def test_modern_anchor_cards_keep_price_size_location_and_date(self):
        row = parse_search(MODERN_SEARCH)[0]
        self.assertEqual((row["id"], row["rent"], row["size"]), ("789", 730, 55))
        self.assertEqual(row["title"], "Sunny flat")
        self.assertIn("Würzburg Altstadt", row["location"])
        self.assertEqual(row["available"], "01.11.2026")

    def test_modern_nightly_prices_are_excluded_even_with_generic_titles(self):
        nightly = MODERN_SEARCH.replace('data-id="789"', 'data-id="790"').replace('pro Monat', 'pro Nacht')
        rows = parse_search(MODERN_SEARCH + nightly)
        self.assertEqual([r["id"] for r in rows], ["789"])

    def test_unknown_charges_and_temporary_lets_are_not_fabricated(self):
        row = parse_detail(DETAIL, parse_search(SEARCH)[0])
        self.assertEqual((row["base_rent"], row["service_costs"]), (550, 180))
        self.assertIsNone(row["other_costs"])
        self.assertTrue(row["temporary"])
        result = evaluate([row], DEFAULTS)[0]
        self.assertEqual(result["estimated_total"], 790)
        self.assertEqual(result["estimated_saving"], 210)
        self.assertFalse(result["matches"])

    def test_layout_change_is_a_failure_not_zero_results(self):
        with self.assertRaises(ValueError):
            parse_search("<html>Verify you are human</html>")

    def test_nightly_stays_do_not_become_cheap_monthly_apartments(self):
        nightly = SEARCH.replace('data-id="123"', 'data-id="456"').replace('Sunny flat', 'overnight stay')
        rows = parse_search(SEARCH + nightly)
        self.assertEqual([r["id"] for r in rows], ["123"])

    def test_peer_comparison_requires_enough_like_sized_homes(self):
        base = parse_search(SEARCH)[0]
        rows = [dict(base, id=str(i), rent=rent, currently_seen=True) for i, rent in enumerate([500, 750, 800, 850])]
        tiny = dict(base, id="tiny", size=12, rent=200, currently_seen=True)
        result = evaluate(rows + [tiny], DEFAULTS)
        self.assertTrue(result[0]["good_value"])
        self.assertEqual(result[0]["peer_count"], 3)
        self.assertIsNone(result[-1]["value_discount"])

    def test_duplicates_preserve_saved_state_and_alert_delivery(self):
        row = parse_search(SEARCH)[0]
        self.store.upsert(row, "first")
        self.store.status("123", "saved")
        self.store.notified("123")
        self.store.upsert(dict(row, rent=700), "second")
        saved = self.store.rows()[0]
        self.assertEqual((saved["first_seen"], saved["status"], saved["notified"]), ("first", "saved", True))
        self.assertEqual(len(self.store.rows()), 1)

    def test_failed_alert_retries_without_losing_listing(self):
        row = parse_search(SEARCH)[0]
        self.store.upsert(row, "first")
        self.store.put("seen_ids", ["123"])
        collector = Collector(self.store, lambda row: False)
        collector.alert()
        self.assertFalse(self.store.rows()[0]["notified"])
        collector.notifier = lambda row: True
        collector.alert()
        self.assertTrue(self.store.rows()[0]["notified"])

    def test_source_failure_retains_history_and_reports_failure(self):
        self.store.upsert(parse_search(SEARCH)[0], "first")
        collector = Collector(self.store)
        with patch.object(collector, "fetch", side_effect=RuntimeError("Offline")):
            collector.scan()
        self.assertEqual(len(self.store.rows()), 1)
        self.assertEqual(len(self.store.get("errors")), 2)
        self.assertIsNone(self.store.get("last_success"))

    def test_cached_costs_do_not_freeze_listing_title_or_start_date(self):
        old = parse_detail(DETAIL, parse_search(SEARCH)[0])
        self.store.upsert(old, "first")
        changed = SEARCH.replace("Sunny flat", "Renovated flat").replace("01.11.2026", "15.11.2026")
        collector = Collector(self.store)
        with patch.object(collector, "fetch", return_value=changed):
            collector.scan()
        row = self.store.rows()[0]
        self.assertEqual(row["title"], "Renovated flat")
        self.assertEqual(row["available"], "15.11.2026 → 31.12.2026")
        self.assertEqual(row["service_costs"], 180)

    def test_settings_and_cross_origin_writes(self):
        client = create_app(self.store, Collector(self.store)).test_client()
        self.assertEqual(client.get("/api/state").status_code, 200)
        self.assertEqual(client.post("/api/settings", json=DEFAULTS).status_code, 200)
        self.assertEqual(client.post("/api/settings", json=DEFAULTS, headers={"Origin": "https://evil.example"}).status_code, 403)
        with self.assertRaises(ValueError):
            validate_settings(DEFAULTS | {"budget": float("nan")})
        self.assertEqual(client.post("/api/settings", json=DEFAULTS | {"min_size": -1}).status_code, 400)

    def test_telegram_errors_never_disclose_token(self):
        token = "123:" + "a" * 30
        with patch("telegram_alerts.requests.post", side_effect=requests.ConnectionError(token)):
            with self.assertRaises(RuntimeError) as error:
                call(token, "getMe")
        self.assertNotIn(token, str(error.exception))

    def test_telegram_configuration_requires_both_values_and_returns_boolean(self):
        for token, chat_id, expected in [("", "", False), ("test-token", "", False),
                                         ("", "test-chat", False), ("test-token", "test-chat", True)]:
            with self.subTest(token_present=bool(token), chat_present=bool(chat_id)):
                with patch("telegram_alerts.ROOT", Path(self.temp.name)), patch.dict(
                    "os.environ", {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}
                ):
                    self.assertIs(is_configured(), expected)

    def test_api_reports_telegram_configuration_without_credentials(self):
        client = create_app(self.store, Collector(self.store)).test_client()
        token = "123:" + "x" * 30
        chat_id = "private-chat-test"
        with patch("telegram_alerts.ROOT", Path(self.temp.name)), patch.dict(
            "os.environ", {"TELEGRAM_BOT_TOKEN": token, "TELEGRAM_CHAT_ID": chat_id}
        ):
            response = client.get("/api/state")
        self.assertEqual(response.status_code, 200)
        self.assertIs(response.get_json()["telegram_connected"], True)
        for value in (token, chat_id, "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
            self.assertNotIn(value, response.get_data(as_text=True))


if __name__ == "__main__":
    unittest.main()
