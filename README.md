# Wohnung Scout

A local apartment-search dashboard for Würzburg. Compare the current asking-rent sample before choosing your budget, then receive new matching listings in Telegram.

## Run

Requires Python 3.12+ and Bash. On Ubuntu, install `python3-venv` if needed.

```bash
./scripts/start.sh
```

Open **http://localhost:8765**. The first collection starts automatically. The app checks every 30 minutes while this process is running. Closing the process, suspending the computer, or shutting down WSL pauses collection. GitHub hosts the source and runs tests; it does not run the live collector.

## Explore the market

- Rent versus size chart: select a dot to open its card.
- Median asking rent, size, rent/m², and rent by size band.
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

The collector reads the first public result page for [studios](https://www.wg-gesucht.de/1-zimmer-wohnungen-in-Wuerzburg.141.1.1.0.html) and [apartments](https://www.wg-gesucht.de/wohnungen-in-Wuerzburg.141.2.1.0.html) in Würzburg. Listing IDs remove duplicates. It does not cover every portal or every result page. These are asking rents, not signed leases, and this is not a representative statistical survey. Explicitly named overnight/nightly stays are excluded. Temporary lets are excluded from market statistics and alerts by default. Some temporary lets may remain unidentified until their detail pages are checked.

Each scan enriches at most 12 previously unchecked listings, prioritizing affordable homes, with a one-second gap between detail requests. The details show advertised total rent, base rent, service charges, other costs, deposit, and fixed end dates when available. No authentication, CAPTCHA bypass, or private API is used. Blocks, network failures, and layout changes are reported, and existing data is retained. Respect the provider’s terms and access controls; pause the collector if automated access is disallowed. Do not increase the polling rate.

“Currently seen” means present in the latest successful first-page sample, not confirmed available. Listings that disappear remain in history and can still be viewed under Saved or Hidden. Partial source failures conservatively retain the previous sample.

## Verify

```bash
.venv/bin/python -m unittest discover -s tests -v
bash -n scripts/start.sh scripts/setup-telegram.sh
./scripts/check-secrets.sh
.venv/bin/python app.py --once
```

CI runs parser, cost comparison, deduplication, delivery retry, source-failure, settings, and token-redaction tests. Tests use synthetic HTML matching the source structure, not copied listing data. A live collection is a separate manual check because external pages can change.

CI also rejects tracked credential/database files and scans the complete Git history with checksum-verified Gitleaks. The scanner downloads a pinned release from its official GitHub repository. Local credentials and listing data belong only in ignored files.

## Code ownership

`scout.py` owns collection, SQLite history, settings validation, and comparisons. `telegram_alerts.py` owns Telegram credentials and requests. `app.py` owns the local HTTP interface and schedule. `static/` owns the dashboard. `tests/` and CI provide the normal checks. Runtime data in `data/`, the virtual environment, and credentials stay untracked. The server binds to loopback; do not expose this personal dashboard publicly without adding authentication and a production server.
