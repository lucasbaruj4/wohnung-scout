"""Public WG-Gesucht collection, durable listing history, and market comparisons."""
from __future__ import annotations

import json
import math
import re
import sqlite3
import statistics
import threading
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

BASE = "https://www.wg-gesucht.de"
SEARCHES = (
    ("Studios", f"{BASE}/1-zimmer-wohnungen-in-Wuerzburg.141.1.1.0.html"),
    ("Apartments", f"{BASE}/wohnungen-in-Wuerzburg.141.2.1.0.html"),
)
DEFAULTS = {"current_total": 1000, "budget": 850, "min_size": 30,
            "extra_costs": 60, "include_temporary": False}


def now():
    return datetime.now(timezone.utc).isoformat()


def number(text):
    match = re.search(r"\d[\d.,]*", text.replace("\xa0", ""))
    if not match:
        return None
    return float(match[0].replace(".", "").replace(",", "."))


def nightly_stay(title):
    return bool(re.search(r"overnight|übernachtung|pro nacht|per night|nightly|tagesmiete", title, re.I))


def parse_search(html):
    soup = BeautifulSoup(html, "html.parser")
    listings = []
    for card in soup.select(".offer_list_item[data-id]"):
        link = card.select_one("h2 a")
        facts = card.select_one(".middle")
        location = card.select_one(".card_body .col-xs-11 span")
        if not link or not facts or not location:
            continue
        text = facts.get_text(" ", strip=True)
        price = re.search(r"([\d.,]+)\s*€", text)
        size = re.search(r"([\d.,]+)\s*m[²2]", text)
        if not price or not size:
            continue
        url = urljoin(BASE, link.get("href", ""))
        if not url.startswith(BASE + "/"):
            continue
        title = link.get_text(" ", strip=True)
        if nightly_stay(title):
            continue
        listings.append({"id": card["data-id"], "title": title, "url": url,
                         "rent": number(price[1]), "size": number(size[1]),
                         "location": " ".join(location.get_text(" ", strip=True).split()),
                         "available": " · ".join(re.findall(r"\d{2}\.\d{2}\.\d{4}", text)),
                         "temporary": bool(re.search(r"zwischenmiete|befristet|sublet|temporary", title, re.I)),
                         "rent_basis": "advertised", "base_rent": None,
                         "service_costs": None, "other_costs": None, "deposit": None,
                         "details_checked": False})
    # A changed layout or challenge must not masquerade as an empty market.
    if not listings:
        raise ValueError("No readable listing cards. The source may be empty, blocked, or have changed layout.")
    return listings


def parse_detail(html, listing):
    soup = BeautifulSoup(html, "html.parser")
    result = dict(listing)
    for label in soup.select(".key_fact_detail"):
        if label.get_text(strip=True) == "Gesamtmiete":
            value = label.parent.select_one(".key_fact_value")
            if value and "€" in value.get_text():
                result["rent"] = number(value.get_text())
                result["rent_basis"] = "listed total"
    labels = {"Miete:": "base_rent", "Nebenkosten:": "service_costs",
              "Sonstige Kosten:": "other_costs", "Kaution:": "deposit"}
    for label in soup.select(".section_panel_detail"):
        key = label.get_text(" ", strip=True)
        row = label.find_parent("div", class_="row")
        value = row.select_one(".section_panel_value") if row else None
        if key in labels and value:
            text = value.get_text(" ", strip=True)
            result[labels[key]] = number(text) if "€" in text else None
        if key == "frei bis:" and value and re.search(r"\d{2}\.\d{2}\.\d{4}", value.get_text()):
            result["temporary"] = True
            result["available"] += " → " + value.get_text(strip=True)
    result["details_checked"] = result["rent_basis"] == "listed total"
    return result


def evaluate(rows, settings):
    # Compare like-sized homes. A tiny studio must not define the value of a large flat.
    market = [r for r in rows if not r["temporary"] and r.get("currently_seen", True)]
    for row in rows:
        row["estimated_total"] = round(row["rent"] + settings["extra_costs"], 2)
        row["estimated_saving"] = round(settings["current_total"] - row["estimated_total"], 2)
        row["price_per_m2"] = round(row["rent"] / row["size"], 2)
        peers = [r["rent"] / r["size"] for r in market
                 if r["id"] != row["id"] and .75 * row["size"] <= r["size"] <= 1.25 * row["size"]]
        row["peer_count"] = len(peers)
        row["value_discount"] = round((1 - row["price_per_m2"] / statistics.median(peers)) * 100, 1) if len(peers) >= 3 and not row["temporary"] else None
        row["matches"] = (row["estimated_total"] <= settings["budget"] and row["size"] >= settings["min_size"]
                          and (settings["include_temporary"] or not row["temporary"]))
        row["good_value"] = row["value_discount"] is not None and row["value_discount"] >= 10
    return rows


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS listings (
                    id TEXT PRIMARY KEY, payload TEXT NOT NULL, first_seen TEXT NOT NULL,
                    last_seen TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'new',
                    notified INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            """)

    def connect(self):
        db = sqlite3.connect(self.path, timeout=20)
        db.row_factory = sqlite3.Row
        return db

    def get(self, key, default=None):
        with self.connect() as db:
            row = db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return json.loads(row[0]) if row else default

    def put(self, key, value):
        with self.connect() as db:
            db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, json.dumps(value)))

    def settings(self):
        return DEFAULTS | self.get("settings", {})

    def upsert(self, listing, stamp):
        with self.connect() as db:
            db.execute("""INSERT INTO listings (id,payload,first_seen,last_seen) VALUES (?,?,?,?)
                ON CONFLICT(id) DO UPDATE SET payload=excluded.payload,last_seen=excluded.last_seen""",
                       (listing["id"], json.dumps(listing), stamp, stamp))

    def rows(self):
        ids = set(self.get("seen_ids", []))
        with self.connect() as db:
            data = db.execute("SELECT * FROM listings ORDER BY first_seen DESC").fetchall()
        return [json.loads(r["payload"]) | {"first_seen": r["first_seen"], "last_seen": r["last_seen"],
                 "status": r["status"], "notified": bool(r["notified"]), "currently_seen": r["id"] in ids}
                for r in data if not nightly_stay(json.loads(r["payload"])["title"])]

    def status(self, id, status):
        if status not in ("new", "saved", "hidden"):
            raise ValueError("Status must be new, saved, or hidden.")
        with self.connect() as db:
            return db.execute("UPDATE listings SET status=? WHERE id=?", (status, id)).rowcount

    def notified(self, id):
        with self.connect() as db:
            db.execute("UPDATE listings SET notified=1 WHERE id=?", (id,))


class Collector:
    def __init__(self, store, notifier=None):
        self.store, self.notifier = store, notifier
        self.lock = threading.Lock()

    def fetch(self, url):
        # Only fixed source URLs or source-owned listing URLs are used.
        try:
            response = requests.get(url, timeout=(8, 20), headers={"User-Agent": "WohnungScout/1.0 personal research"})
            response.raise_for_status()
            return response.text
        except requests.RequestException:
            raise RuntimeError("Source request failed. Check connectivity or try again later.") from None

    def scan(self, detail_limit=12):
        if not self.lock.acquire(blocking=False):
            return False
        try:
            stamp, found, errors = now(), {}, []
            for label, url in SEARCHES:
                try:
                    for listing in parse_search(self.fetch(url)):
                        found[listing["id"]] = listing
                except (RuntimeError, ValueError) as exc:
                    errors.append(f"{label}: {exc}")
            previous = {r["id"]: r for r in self.store.rows()}
            # Enrich new affordable homes first; keep full public search results for charts.
            prioritized = sorted(found.values(), key=lambda r: (r["rent"] > self.store.settings()["budget"], r["rent"]))
            checked = 0
            for listing in prioritized:
                old = previous.get(listing["id"])
                if old and old["details_checked"] and old["rent"] == listing["rent"]:
                    for key in ("rent_basis", "base_rent", "service_costs", "other_costs", "deposit", "details_checked"):
                        listing[key] = old[key]
                    listing["temporary"] = listing["temporary"] or old["temporary"]
                    if " → " in old["available"]:
                        listing["available"] += " → " + old["available"].split(" → ", 1)[1]
                elif checked < detail_limit:
                    checked += 1
                    try:
                        listing = parse_detail(self.fetch(listing["url"]), listing)
                    except (RuntimeError, ValueError) as exc:
                        errors.append(f"Details {listing['id']}: {exc}")
                    threading.Event().wait(1)
                self.store.upsert(listing, stamp)
            if found:
                # On partial failures, retain visibility for rows from the failed category.
                ids = set(found)
                if errors:
                    ids.update(self.store.get("seen_ids", []))
                self.store.put("seen_ids", sorted(ids))
                self.store.put("last_success", stamp)
            self.store.put("last_check", stamp)
            self.store.put("errors", errors)
            self.alert()
            return True
        finally:
            self.lock.release()

    def alert(self):
        if not self.notifier:
            return
        rows = evaluate(self.store.rows(), self.store.settings())
        candidates = sorted((r for r in rows if r["matches"] and r["currently_seen"]
                             and not r["notified"] and r["status"] != "hidden"), key=lambda r: r["estimated_total"])
        for row in candidates[:5]:
            try:
                sent = self.notifier(row)
            except RuntimeError:
                self.store.put("telegram_error", "Alert failed. It will retry on the next check.")
                return
            if sent:
                self.store.notified(row["id"])
                self.store.put("telegram_error", None)


def validate_settings(data):
    result = {}
    bounds = {"current_total": (1, 10000), "budget": (1, 10000), "min_size": (1, 500), "extra_costs": (0, 1000)}
    for key, (low, high) in bounds.items():
        value = float(data[key])
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be between {low} and {high}.")
        result[key] = value
    if not isinstance(data.get("include_temporary"), bool):
        raise ValueError("include_temporary must be true or false.")
    result["include_temporary"] = data["include_temporary"]
    return result
