# Choose a frontend

Compare three read-only versions of the existing apartment dashboard.
A puts the shortlist first. B puts the comparison table first.
C puts price and size on a large chart.

Run the main app for live data, then run this branch with its installed Python:

```bash
../wohnung-scout/.venv/bin/python scripts/preview-ui.py
```

Open http://127.0.0.1:8766/?variant=A.
Use the bottom switcher or the left and right arrow keys to change options.
Inputs keep their normal arrow-key behavior.
All preview changes stay in memory. There are no write API routes.

The server proxies GET /api/state from the main app on port 8765.
GET /api/photos reads the two public search pages and caches photo URLs in memory
for 30 minutes. It starts no collector and reads no local credential file.
It never changes listings, settings, saved status, or delivery history.
If the main app is unavailable, each option labels its synthetic examples.

B was selected as the direction for the next iteration. The original drafts
stay on `prototype/frontend-options`. Implement the final choice separately.

## Second iteration

The chosen direction is B, the comparison layout. The next decision is how
much detail should be visible before selecting an apartment. Larger text,
stronger contrast, and fewer simultaneous controls apply to every option.

- B1 uses one clear table. Apartment details expand inside the selected row.
- B2 compares two or three apartments in aligned columns.
- B3 keeps a short list beside one focused apartment.

Open http://127.0.0.1:8766/static/prototype/comparison.html?variant=B1.
The shared bottom switcher selects B1, B2, or B3. Original B stays available
through the link beside it. All changes remain in browser memory.

These are throwaway drafts on `prototype/comparison-refinements`. The
selection is pending. They do not change the running collector.

The refinements use separate address lines and keep search limits in their
controls. Listing photos identify the apartment beside its comparison values.
Missing or broken photos show “Photo unavailable”; examples have no photos.
The parser stores optional photo URLs from public listing cards and galleries,
and preserves a photo when later pages omit it. Images load from the provider;
no apartment photos are copied into this repository.
