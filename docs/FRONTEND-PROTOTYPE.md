# Frontend preview

Lucas selected B1. `static/index.html` is the authoritative dashboard.
The dashboard uses a dark palette with high-contrast text.
Photos are 280 × 210 pixels on desktop and fill the apartment row on phones.
Titles remain 20 pixels and totals remain 28 pixels.
Select a title for the cost breakdown, Save, Hide, or the original listing.
Compare has a two-part Within my limits / Go crazy toggle. Go crazy shows the
current apartments that fail at least one search condition, including unconfirmed
charges. Switching views does not change search settings or alerts.
Saved has its own navigation button. It includes saved apartments outside the
limits and those no longer in the latest sample. Hidden remains accessible for
restoring apartments. Returning to Compare preserves the selected toggle position.
Search limits contain the budget, size, reserve, current costs, and temporary-let setting.
Sources opens a dialog with eleven provider icons and links. It distinguishes
automatic sources from website searches. Website searches do not supply the
comparison or alerts. The preview explains that its source support belongs to
this branch and does not activate providers in the running app.

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
for 30 minutes. It reads only WG-Gesucht searches.
GET /api/sources reads the configured non-WG-Gesucht public searches and checks
at most four incomplete offers for rent details. Its memory cache lasts 30 minutes.
Those offers join the comparison after the existing local data loads.
Neither route opens a database, reads credentials, or sends alerts.

On the production app, the same dashboard uses the existing status and settings
POST routes. It performs no writes on load. The preview flag separates those modes.

B2 and B3 remain read-only alternatives at
http://127.0.0.1:8766/static/prototype/comparison.html.
Old B1 links redirect to the authoritative dashboard. The earlier A/B/C drafts
remain on the prototype branch for reference.

Only whole apartments qualify. WG-Gesucht remains a source alongside
[ohne-makler](https://www.ohne-makler.net/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/)
and [Frauenland](https://www.wg-frauenland.de/mieten/).
HC24 adds furnished whole apartments from public embedded page data. These are
temporary lets with unconfirmed additional charges and are excluded from matches.
The Go crazy view shows them with their published costs and minimum
stay when available. Provider-hosted photos use the same honest missing-photo state.
Frauenland is a housing cooperative, not a shared-flat category.
Its offers require membership; unquoted share costs remain unknown.
Its current illustrations and floor plans are not shown as apartment photos.
The backend owns shared-flat exclusion. The dashboard receives eligible records.
Provider photos have an honest unavailable state and stay outside Git.
