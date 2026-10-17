## 2026-10-17
- Selected B1 as the dashboard with larger photos, persistent production actions, and isolated preview actions.
- Excluded shared flats and shared kitchens or bathrooms from comparisons and alerts without deleting history.
- Added public ohne-makler apartment search and detail parsing for Würzburg, with explicit rent basis and unknown charges.
- Added real listing photos to all three comparison drafts with honest missing-photo states.
- Removed dot-separated summaries and separated addresses from comparison values.
- Added photo parsing, retention, read-only preview caching, and a design regression check.
- Recorded purposeful, readable UI guidance without dot-separated summaries.

## 2026-10-16
- Added three cleaner comparison drafts on an isolated prototype branch.
- Added module ownership checks and a shared local/CI verification command.
- Kept raw Telegram credentials out of the HTTP layer.
- Extended secret scans to staged, edited, and non-ignored new files.
- Restored collection for the updated WG-Gesucht listing cards while keeping support for the previous layout.
- Added tests for the new cards and excluded nightly prices shown outside the title.

## 2026-10-15
- Prepared the source for public release with generic example settings and no private task links.
- Added credential/database ignore rules and a full-history secret check in CI.

## 2026-10-13
- Added public WG-Gesucht collection, durable listing history, and a 30-minute local schedule.
- Added market charts, comparisons by apartment size, editable search limits, and saved/hidden listings.
- Added Telegram alert delivery and a guided private-chat setup script.
- Added behavior tests and GitHub CI.
