import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from scout import Collector, DEFAULTS, FRAUENLAND, Store, evaluate, housing_type, parse_detail, parse_search


URL = FRAUENLAND + '/mieten/'
UNIT = '''<h4><strong>Wohnung {unit}</strong></h4>
<p><strong>Zimmer: </strong>2</p><p><strong>Wohnfläche:</strong> 40,5 m²</p>
<p><strong>Nettokaltmiete: </strong>500 €</p><p><strong>Betriebskosten:</strong> 80 €</p>
<p><strong>Heizkosten:</strong> 70 €</p><p><strong>Gesamtmiete: </strong>650 €</p>
<p>Private kitchen and bathroom.</p><hr>'''


def page(units=('1', '2'), address='Teststraße 4<br>97074 Würzburg', description='Gemeinschaftsgarten'):
    return f'''<header>WG Frauenland, Wohnungsgenossenschaft</header>
<div data-label="angebote"><h2>Angebote</h2>
<p>Nur für Genossenschaftsmitglieder. Geschäftsanteile nach Wohnungsgröße.</p>
<h2>Wohnungen</h2><table><tbody><tr><td><h3>{address}</h3>
<h3><img src="{FRAUENLAND}/media/elevation-drawing.jpg"></h3>
<p>Der Bezug ist zum 01.03.2027 geplant. {description}</p>
{''.join(UNIT.format(unit=unit) for unit in units)}</td></tr></tbody></table>
<h2>Stellplätze</h2><table><tr><td><h4>Wohnung 99</h4><p>Parking only.</p></td></tr></table></div>'''


class FrauenlandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.store = Store(Path(self.temp.name) / 'test.sqlite3')

    def test_units_have_stable_source_ids_and_exclude_parking_and_nearby_towns(self):
        rows = parse_search(page(), URL)
        self.assertEqual(len(rows), 2)
        self.assertEqual(len({row['id'] for row in rows}), 2)
        self.assertTrue(all(row['id'].startswith('frauenland:') for row in rows))
        reordered = parse_search(page(('2', '1')).replace('650 €', '700 €').replace('500 €', '550 €'), URL)
        self.assertEqual({row['title']: row['id'] for row in rows},
                         {row['title']: row['id'] for row in reordered})
        other = parse_search(page(('1',), address='Otherstraße 6<br>97074 Würzburg'), URL)[0]
        self.assertNotIn(other['id'], {row['id'] for row in rows})
        self.assertEqual(parse_search(page(address='Teststraße 4<br>97209 Veitshöchheim'), URL), [])

    def test_complete_costs_availability_and_membership_are_honest(self):
        row = parse_search(page(), URL)[0]
        self.assertEqual((row['rent'], row['base_rent'], row['service_costs'], row['size']), (650, 500, 150, 40.5))
        self.assertEqual(row['available'], '01.03.2027 (planned)')
        self.assertTrue(row['details_checked'] and row['housing_checked'] and row['monthly_charges_known'])
        self.assertTrue(row['membership_required'])
        self.assertIsNone(row['membership_costs'])
        self.assertIsNone(row['deposit'])
        self.assertIsNone(row['other_costs'])
        self.assertIsNone(row['image_url'], 'Architectural drawings must not appear as listing photos.')
        self.assertIn('Share costs need confirmation', row['source_note'])
        self.assertTrue(evaluate([row], DEFAULTS)[0]['matches'])
        self.assertEqual(parse_detail('<footer>WG branding</footer>', row), row)

    def test_unknown_charges_do_not_match_or_enter_value_comparisons(self):
        row = parse_search(page().replace('70 €', 'auf Anfrage'), URL)[0]
        self.assertIsNone(row['service_costs'])
        self.assertFalse(row['monthly_charges_known'])
        peers = [dict(row, id=str(index), rent=900, monthly_charges_known=True) for index in range(4)]
        result = evaluate([row] + peers, DEFAULTS)[0]
        self.assertFalse(result['matches'])
        self.assertIsNone(result['value_discount'])
        collector = Collector(self.store, lambda listing: self.fail('Unknown charges caused an alert.'))
        with patch('scout.SEARCHES', [('Synthetic Frauenland', URL)]), patch.object(
                collector, 'fetch', return_value=page().replace('70 €', 'auf Anfrage')) as fetch:
            collector.scan()
        fetch.assert_called_once_with(URL)

    def test_shared_facilities_are_excluded_but_cooperative_branding_and_gardens_are_not(self):
        self.assertEqual(len(evaluate(parse_search(page(), URL), DEFAULTS)), 2)
        for description in ('Gemeinschaftsküche', 'gemeinsames Badezimmer', 'shared kitchen'):
            with self.subTest(description=description):
                rows = parse_search(page(description=description), URL)
                self.assertTrue(all(row['housing_type'] == 'shared' for row in rows))
                self.assertEqual(evaluate(rows, DEFAULTS), [])
        unit_shared = parse_search(page().replace('Private kitchen and bathroom.', 'Gemeinschaftsbad'), URL)
        self.assertEqual(evaluate(unit_shared, DEFAULTS), [])
        untrusted = dict(parse_search(page(), URL)[0], url='https://example.org/mieten/')
        self.assertEqual(housing_type(untrusted), 'unknown')

    def test_missing_or_changed_layout_and_invalid_costs_raise(self):
        broken = ('<html>Access denied</html>', page().replace('data-label="angebote"', 'data-label="other"'),
                  page().replace('<strong>Heizkosten:</strong>', '<strong>Changed:</strong>'),
                  page().replace('Wohnung 1', 'Wohnung A'), page().replace('650 €', '651 €'),
                  page().replace('80 €', 'about 80 €'), page().replace('40,5 m²', 'unknown'),
                  page().replace('80 €', '-80 €'), page().replace('40,5 m²', '-40,5 m²'),
                  page().replace('h3', 'h5').replace('h4', 'h5'),
                  page().replace('<table><tbody>', '<article><tbody>'),
                  '<div data-label="angebote"><h2>Wohnungen</h2><article>Changed cards</article></div>')
        for html in broken:
            with self.subTest(html=html[:80]), self.assertRaises(ValueError):
                parse_search(html, URL)

    def test_empty_apartment_section_does_not_parse_parking_units(self):
        empty = '''<div data-label="angebote"><h2>Wohnungen</h2><p>Derzeit keine Angebote.</p>
<h2>Stellplätze</h2><table><tr><td><h4>Wohnung 99</h4></td></tr></table></div>'''
        self.assertEqual(parse_search(empty, URL), [])
        self.assertEqual(parse_search(empty.replace('<p>Derzeit keine Angebote.</p>', '<table><tr><td></td></tr></table>'), URL), [])

    def test_rescan_uses_one_request_updates_costs_and_preserves_saved_delivery_and_photo(self):
        old = parse_search(page(('1',)), URL)[0]
        old['image_url'] = FRAUENLAND + '/media/test-building-photo.jpg'
        self.store.upsert(old, 'first')
        self.store.status(old['id'], 'saved')
        self.store.notified(old['id'])
        collector = Collector(self.store, lambda row: self.fail('Previously notified apartment alerted again.'))
        updated = page(('1',)).replace('650 €', '700 €').replace('500 €', '550 €')
        with patch('scout.SEARCHES', [('Synthetic Frauenland', URL)]), patch.object(
                collector, 'fetch', return_value=updated) as fetch:
            collector.scan()
        fetch.assert_called_once_with(URL)
        row = self.store.rows()[0]
        self.assertEqual((row['rent'], row['base_rent'], row['status'], row['notified']), (700, 550, 'saved', True))
        self.assertEqual(row['image_url'], old['image_url'])
        self.assertTrue(row['currently_seen'])

    def test_negative_housing_evidence_survives_changed_price_and_sanitized_description(self):
        old = parse_search(page(('1',), description='Gemeinschaftsküche'), URL)[0]
        self.store.upsert(old, 'first')
        collector = Collector(self.store, lambda row: self.fail('Known shared apartment alerted.'))
        updated = page(('1',)).replace('650 €', '700 €').replace('500 €', '550 €')
        with patch('scout.SEARCHES', [('Synthetic Frauenland', URL)]), patch.object(
                collector, 'fetch', return_value=updated):
            collector.scan()
        self.assertEqual(self.store.rows()[0]['housing_type'], 'shared')
        self.assertEqual(evaluate(self.store.rows(), DEFAULTS), [])

    def test_layout_failure_keeps_previous_sample_and_successful_empty_clears_it(self):
        row = parse_search(page(('1',)), URL)[0]
        self.store.upsert(row, 'first')
        self.store.put('seen_ids', [row['id']])
        collector = Collector(self.store)
        with patch('scout.SEARCHES', [('Synthetic Frauenland', URL)]), patch.object(
                collector, 'fetch', return_value='<html>Layout changed</html>'):
            collector.scan()
        self.assertTrue(self.store.rows()[0]['currently_seen'])
        self.assertTrue(self.store.get('errors'))
        with patch('scout.SEARCHES', [('Synthetic Frauenland', URL)]), patch.object(
                collector, 'fetch', return_value='<div data-label="angebote"><h2>Wohnungen</h2><p>Keine Angebote</p></div>'):
            collector.scan()
        self.assertFalse(self.store.rows()[0]['currently_seen'])
        self.assertEqual(len(self.store.rows()), 1)
