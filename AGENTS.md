# Agent guide

Read README.md before changing collection, comparisons, or alert behavior.
Run `./scripts/check.sh` after changes. CI uses the same command.

Keep SQLite and listing rules in `scout.py`, HTTP and scheduling in `app.py`,
and credentials and Telegram requests in `telegram_alerts.py`.
Pass Telegram delivery into the collector as a callback.
Use `is_configured()` when the dashboard needs Telegram status.
The import contract in `tests/test_architecture.py` checks these owners.
Register a new production module there only after deciding what it owns.

Use synthetic listing data in tests. Keep unknown charges unknown.
Preserve saved status and delivery history across collection updates.
Keep credentials, real settings, listing data, and logs local and ignored.
Live collection can send alerts. Use offline tests for routine verification.

Keep the UI minimal and purposeful. Give each visible element a clear role in
choosing or comparing an apartment. Keep apartment information large and readable.
Use separate fields for distinct facts; never pack counts, limits, or listing facts
into small dot-separated summaries. Keep search limits in their controls.
Show only real listing photos, with an honest fallback when unavailable.
The UI check in `tests/test_design.py` prevents these summaries.

B1 is the chosen dashboard. Show only whole apartments with a private kitchen
and bathroom. Keep WG-Gesucht's apartment categories; exclude shared-flat offers
and shared facilities in parsing, comparisons, and alerts. Keep saved and delivery
history intact. Whole-apartment eligibility belongs in `scout.py`.
`tests/test_whole_apartments.py` checks this rule across rescans.
