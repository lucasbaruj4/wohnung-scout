## 2026-10-17
- Recorded B1 selection and the whole-apartment rule while retaining WG-Gesucht apartment categories.
- Recorded purposeful, readable UI guidance without dot-separated summaries.

## 2026-10-16
- Launched Windows startup through a windowless host so the collector does not open a terminal.
- Added a restartable local service and an optional hidden Windows logon task that keeps WSL alive while Windows is awake.
- Preserved the 30-minute check interval across app restarts and blocked overlapping collector processes.
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
