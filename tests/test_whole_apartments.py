import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from app import create_app
from scout import Collector, DEFAULTS, OHNE, Store, evaluate, housing_type, parse_detail, parse_search
from tests.test_scout import SEARCH, DETAIL

OM_URL = OHNE + '/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/'
OM_SEARCH = '''<a data-om-id="123" data-om-type="RENT" href="/immobilie/123/">
<div><span>570 €</span></div><div><h4>Sunny apartment</h4>
<div><span>97072 Würzburg (Sanderau)</span></div></div>
<div title="Wohnfläche"><span>35m²</span></div><div title="Zimmer"><span>1</span></div></a>'''
OM_DETAIL = '''<h1>Sunny apartment</h1><table>
<tr><td>Objektart</td><td>Wohnung</td></tr><tr><td>Kaltmiete</td><td>570 € (zzgl. NK)</td></tr>
<tr><td>Summe Nebenkosten/Heizkosten</td><td>100 €</td></tr>
<tr><td>Mietsicherheit</td><td>1.710 €</td></tr><tr><td>Miete Garage/Stellplatz</td><td>50 €</td></tr>
<tr><td>Übernahme ab</td><td>1. Dezember 2026</td></tr></table>
<div class="prose">Own kitchen and bathroom.</div>
<meta property="og:image" content="https://www.ohne-makler.net/immobilie/123/picture/0/medium.jpg">'''


class WholeApartmentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite3')

    def test_miscategorized_commercial_space_never_matches_or_returns_after_rescan(self):
        offer = parse_search(OM_SEARCH.replace('Sunny apartment', '10008 Laden links'), OM_URL)[0]
        commercial = parse_detail(OM_DETAIL.replace('Own kitchen and bathroom.',
                                      'Helle Ladenfläche mit großer Fensterfront.'), offer)
        self.assertEqual(commercial['housing_type'], 'non_residential')
        self.assertEqual(evaluate([commercial], DEFAULTS), [])
        self.store.upsert(commercial, 'first')
        self.store.status(commercial['id'], 'saved')
        collector = Collector(self.store, lambda row: self.fail('Commercial space alerted'))
        with patch('scout.SEARCHES', [('Synthetic', OM_URL)]), patch.object(
                collector, 'fetch', return_value=OM_SEARCH):
            collector.scan()
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])
        self.assertEqual(self.store.rows()[0]['status'], 'saved')
        normal = parse_search(OM_SEARCH.replace('Sunny apartment', 'Wohnung mit Arbeitszimmer'), OM_URL)[0]
        self.assertEqual(housing_type(normal), 'entire_apartment')

    def test_shared_offers_are_excluded_but_wg_suitability_is_not(self):
        for title in ('WG-Zimmer', 'Zimmer in einer WG', '4er Wohngemeinschaft einzelne Zimmer',
                      'Wohnung mit Gemeinschaftsküche', 'Studio mit geteiltem Badezimmer',
                      'Shared apartment', 'Apartment with shared kitchen'):
            with self.subTest(title=title):
                self.assertEqual(evaluate(parse_search(SEARCH.replace('Sunny flat', title)), DEFAULTS), [])
        for title in ('WG-geeignete Wohnung', 'WG-tauglich', 'Keine WG', 'Keine Wohngemeinschaft',
                      'Apartment with Gemeinschaftsgarten'):
            with self.subTest(title=title):
                self.assertEqual(len(parse_search(SEARCH.replace('Sunny flat', title))), 1)
        self.assertEqual(housing_type({'title': 'Room', 'url': 'https://example.org/room'}), 'unknown')

    def test_detail_description_overrules_apartment_category_without_reading_branding(self):
        row = parse_search(SEARCH)[0]
        html = DETAIL.replace('Private kitchen and bathroom.', 'Gemeinschaftsbad und gemeinsame Küche.')
        shared = parse_detail(html, row)
        self.assertEqual(shared['housing_type'], 'shared')
        self.assertEqual(evaluate([shared], DEFAULTS), [])
        branded = parse_detail(DETAIL + '<footer>WG-Gesucht: Wohngemeinschaft suchen</footer>', row)
        self.assertEqual(branded['housing_type'], 'entire_apartment')

    def test_old_shared_records_do_not_reach_dashboard_comparisons_or_notifier(self):
        shared = dict(parse_search(SEARCH)[0], title='WG-Zimmer')
        shared.pop('housing_type')
        self.store.upsert(shared, 'first')
        self.store.status('123', 'saved')
        self.store.notified('123')
        self.store.put('seen_ids', ['123'])
        sent = []
        collector = Collector(self.store, lambda row: sent.append(row) or True)
        collector.alert()
        self.assertEqual(sent, [])
        response = create_app(self.store, collector).test_client().get('/api/state')
        self.assertEqual(response.json['listings'], [])
        self.assertEqual((self.store.rows()[0]['status'], self.store.rows()[0]['notified']), ('saved', True))

    def test_detail_shared_classification_survives_cached_rescans(self):
        html = DETAIL.replace('Private kitchen and bathroom.', 'Gemeinschaftsküche')
        old = parse_detail(html, parse_search(SEARCH)[0])
        self.store.upsert(old, 'first')
        collector = Collector(self.store, lambda row: self.fail('Shared flat notified'))
        with patch('scout.SEARCHES', [('Synthetic', 'https://example.org/search')]), patch.object(
                collector, 'fetch', return_value=SEARCH):
            collector.scan()
        self.assertEqual(self.store.rows()[0]['housing_type'], 'shared')
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])

    def test_new_source_ids_city_filter_cost_basis_and_actual_photo(self):
        nearby = OM_SEARCH.replace('123', '124').replace('97072 Würzburg', '97204 Höchberg')
        row = parse_search(OM_SEARCH + nearby, OM_URL)[0]
        self.assertEqual(row['id'], 'ohne-makler:123')
        self.assertEqual(len(parse_search(OM_SEARCH + nearby, OM_URL)), 1)
        self.assertFalse(evaluate([dict(row)], DEFAULTS)[0]['matches'])
        detail = parse_detail(OM_DETAIL, row)
        self.assertEqual((detail['rent'], detail['base_rent'], detail['service_costs']), (670, 570, 100))
        self.assertEqual(detail['deposit'], 1710)
        self.assertEqual(detail['parking_costs'], 50)
        self.assertEqual(detail['image_url'], OHNE + '/immobilie/123/picture/0/medium.jpg')
        self.assertTrue(evaluate([detail], DEFAULTS)[0]['matches'])
        partial = parse_detail(OM_DETAIL.replace('Summe Nebenkosten/Heizkosten', 'Nebenkosten ohne Heizkosten'), row)
        self.assertIn('unknown', partial['rent_basis'])
        self.assertFalse(evaluate([partial], DEFAULTS)[0]['matches'])
        self.assertIsNone(detail['other_costs'])
        shared = parse_detail(OM_DETAIL.replace('Own kitchen and bathroom.', 'Gemeinschaftsküche'), row)
        self.assertEqual(shared['housing_type'], 'shared')

    def test_new_source_retains_enrichment_saved_history_and_stable_photos(self):
        old = parse_detail(OM_DETAIL, parse_search(OM_SEARCH, OM_URL)[0])
        self.store.upsert(old, 'first')
        self.store.status(old['id'], 'saved')
        self.store.notified(old['id'])
        collector = Collector(self.store)
        with patch('scout.SEARCHES', [('Synthetic', OM_URL)]), patch.object(collector, 'fetch', return_value=OM_SEARCH) as fetch:
            collector.scan()
        fetch.assert_called_once_with(OM_URL)
        row = self.store.rows()[0]
        self.assertEqual((row['rent'], row['status'], row['notified'], row['image_url']),
                         (670, 'saved', True, old['image_url']))

    def test_all_filtered_success_clears_seen_sample_without_deleting_history(self):
        self.store.upsert(parse_search(SEARCH)[0], 'first')
        self.store.put('seen_ids', ['123'])
        collector = Collector(self.store)
        with patch('scout.SEARCHES', [('Synthetic', 'https://example.org/search')]), patch.object(
                collector, 'fetch', return_value=SEARCH.replace('Sunny flat', 'WG-Zimmer')):
            collector.scan()
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])
        self.assertEqual(len(self.store.rows()), 1)

    def test_shared_evidence_survives_price_change_and_failed_details(self):
        old = parse_detail(DETAIL.replace('Private kitchen and bathroom.', 'Gemeinschaftsküche'), parse_search(SEARCH)[0])
        self.store.upsert(old, 'first')
        collector = Collector(self.store, lambda row: self.fail('Shared listing alerted'))
        def fetch(url):
            if url == old['url']:
                raise RuntimeError('Offline detail')
            return SEARCH.replace('730 €', '700 €')
        with patch('scout.SEARCHES', [('Synthetic', 'https://example.org/search')]), patch.object(
                collector, 'fetch', side_effect=fetch), patch('scout.threading.Event.wait'):
            collector.scan()
        self.assertEqual(self.store.rows()[0]['housing_type'], 'shared')

    def test_new_shared_title_reconciles_saved_history_even_with_other_source_failure(self):
        old = parse_detail(DETAIL, parse_search(SEARCH)[0])
        self.store.upsert(old, 'first')
        self.store.status('123', 'saved')
        self.store.put('seen_ids', ['123'])
        collector = Collector(self.store, lambda row: self.fail('Stale apartment alerted'))
        def fetch(url):
            if url == 'https://example.org/offline':
                raise RuntimeError('Offline source')
            return SEARCH.replace('Sunny flat', 'WG-Zimmer')
        with patch('scout.SEARCHES', [('Synthetic', 'https://example.org/search'), ('Offline', 'https://example.org/offline')]), patch.object(collector, 'fetch', side_effect=fetch):
            collector.scan()
        self.assertEqual(self.store.rows()[0]['housing_type'], 'shared')
        self.assertEqual(self.store.rows()[0]['status'], 'saved')
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])

    def test_unknown_charges_and_temporary_titles_cannot_create_matches(self):
        row = parse_search(OM_SEARCH, OM_URL)[0]
        unknown = parse_detail(OM_DETAIL.replace('100 €', 'auf Anfrage'), row)
        self.assertIsNone(unknown['service_costs'])
        peers = [dict(parse_detail(OM_DETAIL, row), id=str(i), rent=900) for i in range(4)]
        result = evaluate([unknown] + peers, DEFAULTS)[0]
        self.assertFalse(result['matches'])
        self.assertIsNone(result['value_discount'])
        temporary = parse_search(OM_SEARCH.replace('Sunny apartment', 'Zwischenmiete: Sunny apartment'), OM_URL)[0]
        self.assertTrue(temporary['temporary'])
        self.assertFalse(evaluate([parse_detail(OM_DETAIL, temporary)], DEFAULTS)[0]['matches'])
