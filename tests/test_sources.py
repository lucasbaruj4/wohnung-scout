import unittest

from scout import SEARCHES, SOURCES, source_catalog


class SourceCatalogTests(unittest.TestCase):
    def test_all_eleven_sources_have_names_icons_and_public_websites(self):
        catalog = source_catalog()
        self.assertEqual({source['id'] for source in catalog}, {
            'wg-gesucht', 'ohne-makler', 'frauenland', 'immoscout24', 'kleinanzeigen',
            'immowelt', 'stadtbau', 'main-post', 'wunderflats', 'housinganywhere', 'hc24'})
        self.assertEqual(len(catalog), 11)
        for source in catalog:
            self.assertEqual(set(source), {'id', 'name', 'icon', 'url', 'kind', 'collection', 'note'})
            self.assertTrue(source['name'] and source['icon'] and source['note'])
            self.assertTrue(source['url'].startswith('https://'))
            self.assertNotIn('?', source['url'])
            self.assertIn(source['kind'], ('regular', 'furnished'))
            self.assertIn(source['collection'], ('automatic', 'website'))

    def test_website_sources_are_never_fetched_as_searches(self):
        catalog = source_catalog()
        automatic = {source['id'] for source in catalog if source['collection'] == 'automatic'}
        self.assertEqual(automatic, {'wg-gesucht', 'ohne-makler', 'frauenland', 'hc24'})
        self.assertEqual(len(SEARCHES), 5)
        for source in SOURCES:
            searches = source.get('searches', ())
            self.assertEqual(bool(searches), source['collection'] == 'automatic')
            if source['collection'] == 'website':
                self.assertNotIn(source['url'], [url for _, url in SEARCHES])

    def test_callers_cannot_change_catalog_metadata(self):
        first = source_catalog()
        first[0]['name'] = 'Changed'
        first.clear()
        self.assertEqual(source_catalog()[0]['name'], 'WG-Gesucht')
