# Wohnung Scout

A local apartment-search dashboard for Würzburg. Compare the current asking-rent sample before choosing your budget, then receive new matching listings in Telegram.

## Run

Requires Python 3.12+ and Bash. On Ubuntu, install `python3-venv` if needed.

```bash
./scripts/start.sh
```

Open **http://localhost:8765**. The first collection starts automatically. After a restart, the app waits until the previous check is 30 minutes old. Later checks run 30 minutes after each scan finishes. Closing the process, suspending the computer, or shutting down WSL pauses collection. GitHub hosts the source and runs tests; it does not run the live collector.

## Keep the app running locally

Stop any manually started app before installing the service. Run `./scripts/start.sh` once to install dependencies, then stop that process with Ctrl+C.

On Linux with a running systemd user manager, install the service:

```bash
python3 scripts/install-service.py
```

On WSL, use the optional Windows logon task too:

```bash
python3 scripts/install-service.py --windows-startup
```

The service starts with the systemd user manager and restarts ten seconds after an exit. Repeating the installer leaves an unchanged running service alone. Credentials stay in the ignored `.env` file. The service and Windows task contain no credentials. The service creates new files with private permissions. A process lock prevents a second collector, including a manual `--once` run, from overlapping the service.

Check the service or read its latest logs from Linux:

```bash
systemctl --user status wohnung-scout.service
journalctl --user -u wohnung-scout.service -n 50 --no-pager
```

Stop or start the collector from Linux:

```bash
systemctl --user stop wohnung-scout.service
systemctl --user start wohnung-scout.service
```

The Windows task uses a windowless script host to start WSL at Windows sign-in. It starts the service and keeps a foreground sleep process alive. [Systemd alone does not keep WSL running](https://learn.microsoft.com/en-us/windows/wsl/systemd). The task does not prevent Windows sleep. The computer must stay awake, powered on, and online for successful checks. This setup has no cloud component.

Manage the optional task from Windows PowerShell:

```powershell
Get-ScheduledTask -TaskName 'Wohnung Scout'
Stop-ScheduledTask -TaskName 'Wohnung Scout'
Start-ScheduledTask -TaskName 'Wohnung Scout'
```

Use the Linux service stop command to stop the collector. Stopping the Windows task alone can leave its WSL keeper running. Starting the task starts the service again.

To remove automatic startup, stop and unregister the Windows task in PowerShell:

```powershell
Stop-ScheduledTask -TaskName 'Wohnung Scout'
Unregister-ScheduledTask -TaskName 'Wohnung Scout' -Confirm:$false
Remove-Item "$env:LOCALAPPDATA\WohnungScout\keep-running.ps1", "$env:LOCALAPPDATA\WohnungScout\keep-running.vbs"
```

Then remove the service from Linux:

```bash
systemctl --user disable --now wohnung-scout.service
rm ~/.config/systemd/user/wohnung-scout.service
systemctl --user daemon-reload
```

## Explore the market

- B1 comparison table with large listing photos, monthly estimates, and apartment size.
- Select a title to expand costs, the original listing, Save, and Hide.
- “Good value”: at least 10% lower rent/m² than the median of at least three other currently sampled, non-temporary listings within ±25% of its size. This compares price and size only, not condition, location, or included utilities.
- Editable budget, minimum size, current total cost, and extra-cost reserve.
- Saved and hidden listings persist across checks. No automated landlord contact or applications.

The initial limits (€850 and 30 m²) are exploration defaults, not a claim that these define a good apartment. The current-cost comparison starts at an example €1,000; replace it with your own total including utilities. The €60 extra-cost reserve is an editable placeholder, not a local utility estimate. **Estimated total = listed rent + reserve.** The app never labels utility costs or estimated savings as confirmed. Unknown costs remain unknown. Read the original listing and confirm heating, electricity, water, internet, deposit, and any furniture fee before deciding.

## Connect Telegram

Install Telegram and sign in. Run this from the repository:

```bash
./scripts/setup-telegram.sh
```

The script opens the [official BotFather](https://t.me/BotFather), guides you through `/newbot`, captures the token in hidden input, pairs your private chat using a random code, and sends a test message. Tokens are stored in an ignored `.env` file with restricted permissions. Do not paste them into chat or commit them. The app loads credentials at each check, so restarting after setup is not required.

At each check, up to five currently seen, unnotified, unhidden matches are sent, cheapest estimated totals first. Initial matches can be sent after setup. A successful delivery is recorded in SQLite; failed deliveries remain pending. Saved or hidden status does not reset delivery history. A crash after Telegram accepts a message but before SQLite records it can cause a duplicate. Price changes do not generate a second alert for an already notified listing.

The supported Telegram API steps follow [Telegram’s bot tutorial](https://core.telegram.org/bots/tutorial) and [Bot API](https://core.telegram.org/bots/api).

## Source coverage and limits

Only whole apartments with a private kitchen and bathroom are eligible. Shared-flat offers, shared kitchens, and shared bathrooms are excluded when identified in titles or descriptions. Apartment categories are a starting point, not proof of facilities; confirm the original offer before applying. Saved records and delivery history remain stored even when an offer is excluded.

The collector reads the first public result page for [studios](https://www.wg-gesucht.de/1-zimmer-wohnungen-in-Wuerzburg.141.1.1.0.html) and [apartments](https://www.wg-gesucht.de/wohnungen-in-Wuerzburg.141.2.1.0.html) in Würzburg, plus [ohne-makler whole apartments in Würzburg city](https://www.ohne-makler.net/immobilien/wohnung-mieten/bayern/kreis-wuerzburg-stadt/). WG-Gesucht stays as a source for its apartment categories. Nearby towns on source pages are excluded from the ohne-makler sample. IDs include the source where needed to prevent collisions. It does not cover every portal or every result page. These are asking rents, not signed leases, and this is not a representative statistical survey. Explicitly named overnight/nightly stays are excluded. Temporary lets are excluded from market statistics and alerts by default. Some temporary lets may remain unidentified until their detail pages are checked.

Listing records retain a photo URL from public listing cards or detail galleries when available. Missing photos remain unknown. The dashboard displays those provider-hosted images. Photos are never copied into Git.

Ohne-makler search prices have unknown charges until detail enrichment. Detail pages separate cold rent, charges, deposit, and parking. The estimate adds known rent and charges plus your reserve. Parking inclusion needs confirmation. Offers with unknown service or heating charges appear under All current apartments but cannot match or trigger an alert. Unknown charges never become zero-cost claims.

Each scan enriches at most 12 previously unchecked listings, prioritizing affordable homes, with a one-second gap between detail requests. The details show advertised total rent, base rent, service charges, other costs, deposit, and fixed end dates when available. No authentication, CAPTCHA bypass, or private API is used. Blocks, network failures, and layout changes are reported, and existing data is retained. Respect the provider’s terms and access controls; pause the collector if automated access is disallowed. Do not increase the polling rate.

“Currently seen” means present in the latest successful first-page sample, not confirmed available. Listings that disappear remain in history and can still be viewed under Saved or Hidden. Partial source failures conservatively retain the previous sample.

## Verify

```bash
./scripts/check.sh
```

This command runs behavior tests, module-boundary checks, shell syntax checks, and secret scans. CI runs the same command. The secret check downloads a pinned, checksum-verified Gitleaks release from its official repository. It scans all fetched Git history, the Git index, and publishable working-tree files, including non-ignored new files. Ignored local credentials and listing data stay outside those snapshots. Run `./scripts/start.sh` once to install dependencies before checking locally.

The boundary checks reject unregistered production Python modules, imports that reverse the module dependencies, and database, HTTP, or HTML-library imports outside their owners. Tests use synthetic HTML rather than copied listing data. A live collection remains a separate check because external pages can change. `app.py --once` also sends pending Telegram alerts when credentials are configured.

## Code ownership

`app.py` owns the local HTTP interface and process schedule. It asks Telegram for a configuration boolean, so the HTTP layer does not receive bot credentials. `scout.py` owns collection, SQLite history, settings validation, and comparisons. It receives a notifier callback rather than importing the Telegram adapter. `telegram_alerts.py` owns credentials, pairing, and Telegram requests. `static/` owns the dashboard.

Keep these three Python modules while their responsibilities remain small. Splitting source parsing, comparisons, and storage into more modules would add navigation without removing a current duplicate owner. `tests/test_architecture.py` records the allowed dependencies and checks newly added production modules. Change that contract deliberately when a new responsibility needs its own owner.

Runtime data in `data/`, the virtual environment, and credentials stay untracked. The server binds to loopback. The dashboard opens on the computer running it; Telegram delivers alerts on your phone. Keep the computer awake and the app running. GitHub does not run the collector. Add authentication and a production server before exposing the dashboard publicly.
