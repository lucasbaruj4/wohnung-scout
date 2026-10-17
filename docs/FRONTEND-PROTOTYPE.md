# Frontend preview

Lucas selected B1. `static/index.html` is the authoritative dashboard.
The dashboard uses a dark palette with high-contrast text.
Photos are 280 × 210 pixels on desktop and fill the apartment row on phones.
Titles remain 20 pixels and totals remain 28 pixels.
Select a title for the cost breakdown, Save, Hide, or the original listing.
Search limits contain the budget, size, reserve, current costs, and temporary-let setting.

Run this branch without starting a second collector:

```bash
../wohnung-scout/.venv/bin/python scripts/preview-ui.py
```

Open http://127.0.0.1:8766/.
The preview proxies GET /api/state from port 8765, applies whole-apartment
filtering, and marks the response `preview: true`. Save, Hide, and settings
changes stay in browser memory. No preview write routes exist.
API failure shows an error rather than synthetic apartment offers.
GET /api/photos reads fixed public searches and caches photo URLs in memory
for 30 minutes. It never opens a database, reads credentials, or sends alerts.

On the production app, the same dashboard uses the existing status and settings
POST routes. It performs no writes on load. The preview flag separates those modes.

B2 and B3 remain read-only alternatives at
http://127.0.0.1:8766/static/prototype/comparison.html.
Old B1 links redirect to the authoritative dashboard. The earlier A/B/C drafts
remain on the prototype branch for reference.

Only whole apartments qualify. WG-Gesucht remains a source alongside
[ohne-makler](https://www.ohne-makler.net/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/).
The backend owns shared-flat exclusion. The dashboard receives eligible records.
Provider photos have an honest unavailable state and stay outside Git.
