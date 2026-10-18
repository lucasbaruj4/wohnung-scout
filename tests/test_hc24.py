import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scout import Collector, DEFAULTS, HC24, Store, evaluate, housing_type, parse_detail, parse_search


SEARCH = HC24 + '/de/moeblierter-wohnraum-in-wuerzburg/'
PHOTO = 'https://hc24-media-new.s3.eu-central-1.amazonaws.com/hcwu/12345_1.jpg'


def offer():
    return {
        'externalId': '12345', 'agency': {'agencyShort': 'WU'},
        'geo': {'city': 'Würzburg', 'citySlugName': 'wuerzburg', 'zip': '97074'},
        'propertyType': {'objectType': 'WOHNUNG'},
        'texts': {'headline': 'Furnished test apartment', 'interiorText': 'Einbauküche, Dusche',
                  'generalText': 'Private kitchen and bathroom. Shared garden.'},
        'prices': {'completeRent': 650, 'deposit': 1300, 'currency': 'EUR', 'rentUnit': 'MONTH',
                   'includedServicesTextDeu': 'Betriebskosten enthalten',
                   'additionalCostsTextDeu': 'Strom nach Verbrauch. Endreinigung nach Aufwand.'},
        'areas': {'squareMeters': 40}, 'active': True, 'inactiveSince': '2100-01-01',
        'administrationInformation': {'availableFrom': '2027-01-01', 'minDays': 90},
        'images': [{'imageLink': 'hcwu/12345_1.jpg'}],
    }


def page(offers=None, detail=False):
    offers = [offer()] if offers is None else offers
    content = ({'propertyDetailPageData': {'properties': offers}} if detail else
               {'mapData': {'response': {'properties': {'features': [{'properties': row} for row in offers]}}}})
    payload = {'props': {'pageProps': {'pageData': {'pageContent': content}}}}
    return '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(payload) + '</script>'


class HC24Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite3')

    def test_public_apartment_has_stable_source_id_real_photo_and_unknown_charges(self):
        row = parse_search(page(), SEARCH)[0]
        self.assertEqual((row['id'], row['source'], row['rent'], row['size']), ('hc24:wu12345', 'HC24', 650, 40))
        self.assertEqual(row['url'], HC24 + '/de/expose/wu12345/')
        self.assertEqual(row['image_url'], PHOTO)
        self.assertEqual(housing_type(row), 'entire_apartment')
        self.assertTrue(row['temporary'])
        self.assertFalse(row['monthly_charges_known'])
        self.assertFalse(evaluate([row], dict(DEFAULTS, include_temporary=True))[0]['matches'])
        changed = offer()
        changed['prices']['completeRent'] = 700
        self.assertEqual(parse_search(page([changed]), SEARCH)[0]['id'], row['id'])
        untrusted = dict(row, url='https://example.org/de/expose/wu12345/')
        self.assertEqual(housing_type(untrusted), 'unknown')

    def test_detail_keeps_separate_deposit_minimum_stay_and_unquoted_costs(self):
        row = parse_search(page(), SEARCH)[0]
        detail = parse_detail(page(detail=True), row)
        self.assertEqual(detail['deposit'], 1300)
        self.assertEqual(detail['minimum_stay_days'], 90)
        self.assertEqual(detail['included_costs'], 'Betriebskosten enthalten')
        self.assertIn('Endreinigung', detail['additional_costs'])
        self.assertIsNone(detail['one_time_fees'])
        self.assertTrue(detail['details_checked'] and detail['housing_checked'])
        self.assertFalse(detail['monthly_charges_known'])
        self.assertIsNone(detail['service_costs'])
        self.assertIsNone(detail['base_rent'])
        with self.assertRaises(ValueError):
            parse_detail(page([dict(offer(), externalId='99999')], detail=True), row)

    def test_rooms_nearby_towns_daily_rent_and_inactive_offers_are_excluded(self):
        for key, value in [('propertyType', {'objectType': 'ZIMMER'}),
                           ('geo', {'city': 'Gerbrunn', 'zip': '97218'}),
                           ('agency', {'agencyShort': 'NU'})]:
            with self.subTest(key=key):
                data = offer()
                data[key] = value
                self.assertEqual(parse_search(page([data]), SEARCH), [])
        for title in ('Test apartment pro Nacht', 'Overnight test studio'):
            data = offer()
            data['texts']['headline'] = title
            self.assertEqual(parse_search(page([data]), SEARCH), [])
        data = offer()
        data['prices']['rentUnit'] = 'DAY'
        self.assertEqual(parse_search(page([data]), SEARCH), [])
        row = parse_search(page(), SEARCH)[0]
        data = dict(offer(), inactiveSince='2000-01-01')
        self.assertEqual(parse_search(page([data]), SEARCH), [])
        self.assertEqual(evaluate([parse_detail(page([data], detail=True), row)], DEFAULTS), [])
        data = dict(offer(), active=False)
        self.assertEqual(evaluate([parse_detail(page([data], detail=True), row)], DEFAULTS), [])
        data = offer()
        data['geo']['zip'] = '97218'
        self.assertEqual(evaluate([parse_detail(page([data], detail=True), row)], DEFAULTS), [])
        data = offer()
        data['geo']['city'] = 'Heidingsfeld'
        self.assertEqual(len(parse_search(page([data]), SEARCH)), 1)

    def test_shared_facilities_and_unconfirmed_kitchen_or_bathroom_are_not_eligible(self):
        for description in ('Gemeinschaftsküche', 'gemeinsames Bad', 'shared bathroom', 'Küchenmitbenutzung',
                            'Gemeinschaftsdusche', 'shared shower'):
            data = offer()
            data['texts']['generalText'] = description
            rows = parse_search(page([data]), SEARCH)
            self.assertEqual(rows[0]['housing_type'], 'shared')
            self.assertEqual(evaluate(rows, DEFAULTS), [])
        data = offer()
        data['texts'] = {'headline': 'Furnished apartment', 'interiorText': 'Bett, Küche'}
        rows = parse_search(page([data]), SEARCH)
        self.assertEqual(housing_type(rows[0]), 'unknown')
        self.assertEqual(evaluate(rows, DEFAULTS), [])

    def test_photo_must_belong_to_this_apartment_on_the_real_photo_path(self):
        for image in ('https://example.org/photo.jpg', '../hcwu/12345_1.jpg',
                      'hcwu/99999_1.jpg', 'hcwu/12345_1.svg', 'strapi/avatar.jpg'):
            data = offer()
            data['images'] = [{'imageLink': image}]
            self.assertIsNone(parse_search(page([data]), SEARCH)[0]['image_url'])

    def test_layout_failures_raise_and_explicit_empty_market_is_valid(self):
        self.assertEqual(parse_search(page([]), SEARCH), [])
        for html in ('Access denied', '<script id="__NEXT_DATA__">{}</script>', page([{}])):
            with self.subTest(html=html[:40]), self.assertRaises(ValueError):
                parse_search(html, SEARCH)
        for value in (-1, None, float('nan'), True):
            data = offer()
            data['prices']['completeRent'] = value
            with self.assertRaises(ValueError):
                parse_search(page([data]), SEARCH)

    def test_rescan_preserves_details_saved_delivery_and_photo_without_freezing_price(self):
        old = parse_detail(page(detail=True), parse_search(page(), SEARCH)[0])
        self.store.upsert(old, 'first')
        self.store.status(old['id'], 'saved')
        self.store.notified(old['id'])
        collector = Collector(self.store, lambda row: self.fail('HC24 unknown charges caused alert.'))
        data = offer()
        data['images'] = []
        del data['administrationInformation']['minDays']
        del data['prices']['includedServicesTextDeu']
        del data['prices']['additionalCostsTextDeu']
        with patch('scout.SEARCHES', [('Synthetic HC24', SEARCH)]), patch.object(
                collector, 'fetch', return_value=page([data])) as fetch:
            collector.scan()
        fetch.assert_called_once_with(SEARCH)
        row = self.store.rows()[0]
        self.assertEqual((row['status'], row['notified'], row['image_url']), ('saved', True, PHOTO))
        self.assertEqual((row['minimum_stay_days'], row['deposit']), (90, 1300))
        self.assertIn('Endreinigung', row['additional_costs'])
        data['prices']['completeRent'] = 700
        detail = copy.deepcopy(data)
        detail['prices']['deposit'] = 1400
        with patch('scout.SEARCHES', [('Synthetic HC24', SEARCH)]), patch.object(
                collector, 'fetch', side_effect=[page([data]), page([detail], detail=True)]), patch('scout.threading.Event.wait'):
            collector.scan()
        row = self.store.rows()[0]
        self.assertEqual((row['rent'], row['deposit'], row['status'], row['notified']), (700, 1400, 'saved', True))
        self.assertEqual(row['image_url'], PHOTO)

    def test_shared_detail_evidence_survives_later_price_changes(self):
        data = offer()
        data['texts']['generalText'] = 'Gemeinschaftsküche'
        old = parse_detail(page([data], detail=True), parse_search(page(), SEARCH)[0])
        self.store.upsert(old, 'first')
        data = offer()
        data['prices']['completeRent'] = 700
        collector = Collector(self.store)
        with patch('scout.SEARCHES', [('Synthetic HC24', SEARCH)]), patch.object(
                collector, 'fetch', side_effect=[page([data]), page([data], detail=True)]), patch('scout.threading.Event.wait'):
            collector.scan()
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])

    def test_verified_private_facilities_survive_a_sparse_search_without_overriding_shared_evidence(self):
        sparse = offer()
        sparse['texts'] = {'headline': 'Furnished test apartment'}
        search = parse_search(page([sparse]), SEARCH)[0]
        self.assertEqual(housing_type(search), 'unknown')
        old = parse_detail(page(detail=True), search)
        self.store.upsert(old, 'first')
        collector = Collector(self.store)
        with patch('scout.SEARCHES', [('Synthetic HC24', SEARCH)]), patch.object(
                collector, 'fetch', return_value=page([sparse])) as fetch:
            collector.scan()
        fetch.assert_called_once_with(SEARCH)
        self.assertEqual(len(evaluate(self.store.rows(), DEFAULTS)), 1)
        sparse['texts']['generalText'] = 'Shared bathroom'
        with patch('scout.SEARCHES', [('Synthetic HC24', SEARCH)]), patch.object(
                collector, 'fetch', return_value=page([sparse])):
            collector.scan()
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])
