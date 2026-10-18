import importlib.util
import json
import io
import unittest
from pathlib import Path
from unittest.mock import patch
from urllib.error import URLError

spec = importlib.util.spec_from_file_location(
    "preview_ui", Path(__file__).resolve().parents[1] / "scripts/preview-ui.py")
preview = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preview)
from scout import BASE, DEFAULTS, OHNE, parse_search, source_catalog
from tests.test_scout import SEARCH
from tests.test_whole_apartments import OM_SEARCH, OM_DETAIL, OM_URL


class PreviewTests(unittest.TestCase):
    def setUp(self):
        preview.photo_cache.clear()
        preview.photos_checked = None
        preview.source_cache = {"listings": [], "errors": []}
        preview.sources_checked = None
        self.client = preview.app.test_client()

    def test_state_marks_preview_and_filters_shared_history_without_forwarding_writes(self):
        row = parse_search(SEARCH)[0]
        shared = dict(row, id='shared', title='WG-Zimmer')
        payload = json.dumps({'settings': DEFAULTS, 'listings': [row, shared]}).encode()
        with patch.object(preview, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(payload)
            response = self.client.get('/api/state')
        self.assertIs(response.json['preview'], True)
        self.assertEqual(response.json['sources'], source_catalog())
        self.assertEqual([r['id'] for r in response.json['listings']], ['123'])
        self.assertEqual(self.client.post('/api/settings', json=DEFAULTS).status_code, 404)
        self.assertEqual(self.client.post('/api/listings/123/status', json={'status': 'saved'}).status_code, 404)

    def test_photos_use_fixed_public_searches_and_cache_without_writing_state(self):
        card = b'''<a class="offer_list_item" data-id="123" href="/wohnungen-in-Wuerzburg.123.html">
        <div class="ad-title">Synthetic studio</div><div class="ad-subtitle">Test area</div>
        <div class="middle-row">35 m2</div><div class="price-row">650 &euro;</div>
        <img class="top-image-card" src="https://img.wg-gesucht.de/media/up/test.jpg"></a>'''
        with patch.object(preview, "build_opener") as opener:
            opener.return_value.open.side_effect = lambda *args, **kwargs: io.BytesIO(card)
            first = self.client.get("/api/photos")
            second = self.client.get("/api/photos")
            self.assertEqual(first.json, {"123": "https://img.wg-gesucht.de/media/up/test.jpg"})
            self.assertEqual(second.json, first.json)
            calls = opener.return_value.open.call_args_list
            self.assertEqual([call.args[0].full_url for call in calls],
                             [url for _, url in preview.SEARCHES if url.startswith(BASE + '/')])

    def test_unavailable_photos_leave_comparisons_available_and_do_not_retry_each_load(self):
        with patch.object(preview, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("offline")
            self.assertEqual(self.client.get("/api/photos").json, {})
            self.assertEqual(self.client.get("/api/photos").json, {})
            self.assertEqual(opener.return_value.open.call_count,
                             sum(url.startswith(BASE + '/') for _, url in preview.SEARCHES))
        self.assertEqual(self.client.post("/api/photos").status_code, 405)
        self.assertEqual(self.client.post("/api/collect").status_code, 404)

    def test_additional_sources_show_real_apartments_and_cache_reads_without_store_or_notifier(self):
        def public_page(request, **kwargs):
            return io.BytesIO((OM_SEARCH if request.full_url == OM_URL else OM_DETAIL).encode())
        searches = [('WG-Gesucht', BASE + '/search'), ('ohne-makler', OM_URL)]
        with patch.object(preview, 'SEARCHES', searches), patch.object(preview, 'build_opener') as opener:
            opener.return_value.open.side_effect = public_page
            first = self.client.get('/api/sources')
            second = self.client.get('/api/sources')
            self.assertEqual(first.json, second.json)
            row = first.json['listings'][0]
            self.assertEqual((row['id'], row['rent'], row['status'], row['currently_seen']),
                             ('ohne-makler:123', 670, 'new', True))
            self.assertEqual(row['image_url'], OHNE + '/immobilie/123/picture/0/medium.jpg')
            self.assertEqual([call.args[0].full_url for call in opener.return_value.open.call_args_list],
                             [OM_URL, OHNE + '/immobilie/123/'])
        self.assertEqual(self.client.post('/api/sources').status_code, 405)

    def test_failed_details_keep_charges_unknown_and_failed_sources_remain_explicit(self):
        def public_page(request, **kwargs):
            if request.full_url == OM_URL:
                return io.BytesIO(OM_SEARCH.encode())
            raise URLError('offline')
        searches = [('ohne-makler', OM_URL), ('Unavailable', 'https://example.org/search')]
        with patch.object(preview, 'SEARCHES', searches), patch.object(preview, 'build_opener') as opener:
            opener.return_value.open.side_effect = public_page
            response = self.client.get('/api/sources')
            self.assertFalse(response.json['listings'][0]['monthly_charges_known'])
            self.assertEqual(len(response.json['errors']), 2)
            self.client.get('/api/sources')
            self.assertEqual(opener.return_value.open.call_count, 3)

    def test_unavailable_additional_sources_do_not_invent_apartments(self):
        with patch.object(preview, 'SEARCHES', [('Unavailable', 'https://example.org/search')]), patch.object(preview, 'public_html', side_effect=URLError('offline')):
            response = self.client.get('/api/sources')
            self.assertEqual(response.json['listings'], [])
            self.assertIn('Unavailable', response.json['errors'][0])

    def test_additional_sources_exclude_shared_and_miscategorized_commercial_space(self):
        for description in ('Shared kitchen', 'Helle Ladenfläche mit großer Fensterfront.'):
            with self.subTest(description=description), patch.object(preview, 'SEARCHES', [('ohne-makler', OM_URL)]), patch.object(preview, 'public_html') as fetch:
                preview.sources_checked = None
                fetch.side_effect = [OM_SEARCH, OM_DETAIL.replace('Own kitchen and bathroom.', description)]
                self.assertEqual(self.client.get('/api/sources').json['listings'], [])
