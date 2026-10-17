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
from scout import DEFAULTS, parse_search
from tests.test_scout import SEARCH


class PreviewTests(unittest.TestCase):
    def setUp(self):
        preview.photo_cache.clear()
        preview.photos_checked = None
        self.client = preview.app.test_client()

    def test_state_marks_preview_and_filters_shared_history_without_forwarding_writes(self):
        row = parse_search(SEARCH)[0]
        shared = dict(row, id='shared', title='WG-Zimmer')
        payload = json.dumps({'settings': DEFAULTS, 'listings': [row, shared]}).encode()
        with patch.object(preview, 'build_opener') as opener:
            opener.return_value.open.return_value = io.BytesIO(payload)
            response = self.client.get('/api/state')
        self.assertIs(response.json['preview'], True)
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
                             [url for _, url in preview.SEARCHES])

    def test_unavailable_photos_leave_comparisons_available_and_do_not_retry_each_load(self):
        with patch.object(preview, "build_opener") as opener:
            opener.return_value.open.side_effect = URLError("offline")
            self.assertEqual(self.client.get("/api/photos").json, {})
            self.assertEqual(self.client.get("/api/photos").json, {})
            self.assertEqual(opener.return_value.open.call_count, len(preview.SEARCHES))
        self.assertEqual(self.client.post("/api/photos").status_code, 405)
        self.assertEqual(self.client.post("/api/collect").status_code, 404)
