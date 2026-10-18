import tempfile
import fcntl
import sys
import unittest
import importlib.util
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

import requests

from app import create_app, initial_scan_delay
from scout import Collector, DEFAULTS, SEARCHES, Store, evaluate, number, parse_detail, parse_search, validate_settings
from telegram_alerts import call, is_configured

SEARCH = '''<div class="offer_list_item" data-id="123">
<div class="card_body"><h2><a href="/wohnungen-in-Wuerzburg.123.html">Sunny flat</a></h2>
<div class="col-xs-11"><span>Wohnung | Würzburg Altstadt | Mainstraße</span></div>
<div class="middle"><b>730 €</b><span>01.11.2026</span><b>55 m²</b></div></div></div>'''
DETAIL = '''<div><span class="key_fact_detail">Gesamtmiete</span><b class="key_fact_value">730€</b></div>
<div class="row"><span class="section_panel_detail">Miete:</span><span class="section_panel_value">550€</span></div>
<div class="row"><span class="section_panel_detail">Nebenkosten:</span><span class="section_panel_value">180€</span></div>
<div class="row"><span class="section_panel_detail">Sonstige Kosten:</span><span class="section_panel_value">n.a.</span></div>
<div class="row"><span class="section_panel_detail">frei bis:</span><span class="section_panel_value">31.12.2026</span></div>
<div id="ad_description_text">Private kitchen and bathroom.</div>'''
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

    def test_second_collector_exits_before_opening_database(self):
        root = Path(self.temp.name)
        data = root / "data"
        data.mkdir()
        with (data / "collector.lock").open("a") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            result = subprocess.run([
                sys.executable, "-c",
                "import app, pathlib, sys; app.ROOT=pathlib.Path(sys.argv[1]); "
                "sys.argv=['app.py', '--once']; app.main()", str(root),
            ], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1)
        self.assertIn("A collector is already running", result.stderr)
        self.assertFalse((data / "scout.sqlite3").exists())

    def test_restart_waits_for_remaining_check_interval(self):
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        self.assertEqual(initial_scan_delay((now - timedelta(minutes=5)).isoformat(), now), 1500)
        self.assertEqual(initial_scan_delay((now - timedelta(minutes=30)).isoformat(), now), 0)
        self.assertEqual(initial_scan_delay((now - timedelta(hours=1)).isoformat(), now), 0)

    def test_initial_check_handles_missing_invalid_and_future_timestamps(self):
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        for last in (None, "", "invalid", "2026-10-16T12:00:00"):
            with self.subTest(last=last):
                self.assertEqual(initial_scan_delay(last, now), 0)
        self.assertEqual(initial_scan_delay((now + timedelta(hours=1)).isoformat(), now), 1800)

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

    def test_search_photos_use_listing_images_not_avatars_or_icons(self):
        image = 'https://img.wg-gesucht.de/media/up/2026/01/flat.small.JPEG'
        modern = MODERN_SEARCH.replace('<div class="card-content">', f'''
            <img class="avatar" src="https://img.wg-gesucht.de/media/up/2026/01/user.jpg">
            <img class="top-image-card" src="{image}">
            <img src="/img/icons/virtual_tour_icon.svg"><div class="card-content">''')
        self.assertEqual(parse_search(modern)[0]["image_url"], image)
        legacy = SEARCH.replace('<div class="card_body">', '''
            <div class="card_image"><img src="/img/d.gif"
            data-src="/media/up/2026/01/flat.jpg"></div><div class="card_body">''')
        self.assertEqual(parse_search(legacy)[0]["image_url"],
                         "https://www.wg-gesucht.de/media/up/2026/01/flat.jpg")

    def test_missing_placeholder_and_unsafe_photos_remain_unknown(self):
        for url in ("/img/placeholder/empty_state_offer.svg", "/img/d.gif",
                    "javascript:alert(1)", "data:image/jpeg;base64,example",
                    "https://evil.example/media/up/flat.jpg", "https://[",
                    "https://img.wg-gesucht.de.evil.example/media/up/flat.jpg",
                    "https://name:password@img.wg-gesucht.de/media/up/flat.jpg",
                    "https://img.wg-gesucht.de/media/up/user_photo_1.jpg"):
            with self.subTest(url=url):
                html = MODERN_SEARCH.replace('<div class="card-content">',
                                             f'<img class="top-image-card" src="{url}"><div class="card-content">')
                self.assertIsNone(parse_search(html)[0]["image_url"])
        self.assertIsNone(parse_search(SEARCH)[0]["image_url"])

    def test_detail_photo_replaces_thumbnail_and_keeps_it_when_gallery_is_missing(self):
        thumbnail = "https://img.wg-gesucht.de/media/up/2026/01/flat.small.jpg"
        full = "https://img.wg-gesucht.de/media/up/2026/01/flat.large.jpg"
        row = dict(parse_search(SEARCH)[0], image_url=thumbnail)
        gallery = f'<img class="sp-image" src="/img/d.gif" data-src="{full}">'
        self.assertEqual(parse_detail(DETAIL + gallery, row)["image_url"], full)
        self.assertEqual(parse_detail(DETAIL, row)["image_url"], thumbnail)
        unrelated = '<img class="avatar" src="https://img.wg-gesucht.de/media/up/user.jpg">'
        self.assertIsNone(parse_detail(DETAIL + unrelated, parse_search(SEARCH)[0])["image_url"])

    def test_photo_and_saved_delivery_history_survive_rescans(self):
        image = "https://img.wg-gesucht.de/media/up/2026/01/flat.large.jpg"
        for price_changed, details_fail in ((False, False), (True, True), (True, False)):
            with self.subTest(price_changed=price_changed, details_fail=details_fail):
                old = dict(parse_detail(DETAIL, parse_search(SEARCH)[0]), image_url=image)
                self.store.upsert(old, "first")
                self.store.status("123", "saved")
                self.store.notified("123")
                search = SEARCH.replace("730 €", "700 €") if price_changed else SEARCH
                collector = Collector(self.store)

                def fetch(url):
                    if url == old["url"]:
                        if details_fail:
                            raise RuntimeError("Offline")
                        return DETAIL
                    return search

                with patch.object(collector, "fetch", side_effect=fetch), patch("scout.threading.Event.wait"):
                    collector.scan()
                row = self.store.rows()[0]
                self.assertEqual(row["image_url"], image)
                self.assertEqual((row["status"], row["notified"]), ("saved", True))
                self.assertEqual(len(self.store.rows()), 1)

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
        self.assertEqual(len(self.store.get("errors")), len(SEARCHES))
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

    def test_state_exposes_all_sources_without_collecting_or_changing_history(self):
        self.store.upsert(parse_search(SEARCH)[0], "first")
        self.store.status("123", "saved")
        self.store.notified("123")
        collector = Collector(self.store)
        before = self.store.rows()
        with patch.object(collector, "fetch") as fetch:
            response = create_app(self.store, collector).test_client().get("/api/state")
        self.assertEqual(response.status_code, 200)
        sources = response.json["sources"]
        self.assertEqual({source["name"] for source in sources}, {
            "WG-Gesucht", "ohne-makler", "Frauenland", "ImmoScout24", "Kleinanzeigen",
            "Immowelt", "Stadtbau Würzburg", "Main-Post", "Wunderflats", "HousingAnywhere", "HC24",
        })
        self.assertEqual(sum(source["collection"] == "automatic" for source in sources), 4)
        self.assertTrue(all(source["icon"] and source["url"].startswith("https://") for source in sources))
        self.assertTrue(all("searches" not in source for source in sources))
        fetch.assert_not_called()
        self.assertEqual(self.store.rows(), before)

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


class ServiceInstallerTests(unittest.TestCase):
    def test_install_and_repeat_do_not_restart_but_changed_active_unit_does(self):
        path = Path(__file__).resolve().parents[1] / "scripts/install-service.py"
        spec = importlib.util.spec_from_file_location("install_service", path)
        installer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(installer)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            python = root / ".venv/bin/python"
            python.parent.mkdir(parents=True)
            python.touch()
            active = False

            def run(command, **kwargs):
                nonlocal active
                if command[2] == "is-active":
                    return subprocess.CompletedProcess(command, 0 if active else 3)
                if command[2] in ("enable", "restart"):
                    active = True
                return subprocess.CompletedProcess(command, 0)

            with patch.object(installer, "ROOT", root), patch.object(installer.Path, "home", return_value=root), \
                    patch.object(installer.subprocess, "run", side_effect=run) as commands, \
                    patch("sys.argv", [str(path)]), patch("builtins.print"):
                installer.main()
                unit = root / ".config/systemd/user/wohnung-scout.service"
                content = unit.read_text()
                self.assertIn("Restart=always\nRestartSec=10", content)
                self.assertIn("UMask=0077", content)
                self.assertIn("WantedBy=default.target", content)
                self.assertNotIn("TELEGRAM", content)
                self.assertFalse(any(call.args[0][2] == "restart" for call in commands.call_args_list))
                commands.reset_mock()
                installer.main()
                self.assertFalse(any(call.args[0][2] in ("daemon-reload", "restart")
                                     for call in commands.call_args_list))
                unit.write_text(content.replace("RestartSec=10", "RestartSec=15"))
                commands.reset_mock()
                installer.main()
                self.assertEqual(unit.read_text(), content)
                self.assertEqual(sum(call.args[0][2] == "restart" for call in commands.call_args_list), 1)


if __name__ == "__main__":
    unittest.main()
