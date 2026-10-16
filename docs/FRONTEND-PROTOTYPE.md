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

The server proxies only GET /api/state from the main app on port 8765.
It starts no collector and reads no local credential file.
If the main app is unavailable, each option labels its synthetic examples.

The design decision is pending. Keep these drafts on
`prototype/frontend-options`; implement the selected direction separately.
