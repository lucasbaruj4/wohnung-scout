#!/usr/bin/env python3
"""Serve read-only frontend options without starting another collector."""
from pathlib import Path
import json
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from flask import Flask, Response, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scout import BASE, SEARCHES, evaluate, parse_detail, parse_search, source_catalog

app = Flask(__name__, static_folder=str(ROOT / "static"))
photo_cache = {}
photos_checked = None
photo_lock = threading.Lock()
source_cache = {"listings": [], "errors": []}
sources_checked = None
source_lock = threading.Lock()


@app.get("/")
def preview():
    return send_from_directory(ROOT / "static", "index.html")


@app.get("/api/state")
def state():
    try:
        with build_opener(ProxyHandler({})).open("http://127.0.0.1:8765/api/state", timeout=5) as result:
            data = json.load(result)
        data["preview"] = True
        data["listings"] = evaluate(data["listings"], data["settings"])
        data["sources"] = source_catalog()
        return data
    except URLError:
        return {"error": "The local app is unavailable. Start it to view apartment data."}, 503


@app.get("/api/photos")
def photos():
    """Fill preview photos without running the collector or changing saved data."""
    global photos_checked
    with photo_lock:
        if photos_checked is None or time.monotonic() - photos_checked >= 1800:
            for _, url in SEARCHES:
                if not url.startswith(BASE + "/"):
                    continue
                request = Request(url, headers={"User-Agent": "WohnungScout/1.0 personal research"})
                try:
                    with build_opener(ProxyHandler({})).open(request, timeout=8) as result:
                        rows = parse_search(result.read().decode("utf-8"), url)
                    photo_cache.update({row["id"]: row["image_url"] for row in rows if row.get("image_url")})
                except (URLError, OSError, ValueError):
                    continue
            photos_checked = time.monotonic()
        return dict(photo_cache)


def public_html(url):
    request = Request(url, headers={"User-Agent": "WohnungScout/1.0 personal research"})
    with build_opener(ProxyHandler({})).open(request, timeout=8) as result:
        return result.read().decode("utf-8")


@app.get("/api/sources")
def sources():
    global sources_checked, source_cache
    with source_lock:
        if sources_checked is None or time.monotonic() - sources_checked >= 1800:
            listings, errors = [], []
            for label, url in SEARCHES:
                if url.startswith(BASE + "/"):
                    continue
                try:
                    listings.extend(parse_search(public_html(url), url))
                except (URLError, OSError, ValueError):
                    errors.append(label + " is unavailable. Open the source to check its current offers.")
            unchecked = sorted((row for row in listings if not row["details_checked"]),
                               key=lambda row: row["rent"])[:4]
            for index, row in enumerate(unchecked):
                if index:
                    threading.Event().wait(1)
                try:
                    row.update(parse_detail(public_html(row["url"]), row))
                except (URLError, OSError, ValueError):
                    errors.append(row["source"] + " details unavailable. Charges remain unconfirmed.")
            source_cache = {"listings": [dict(row, status="new", currently_seen=True, notified=False)
                                          for row in listings if row["housing_type"] == "entire_apartment"],
                            "errors": list(dict.fromkeys(errors))}
            sources_checked = time.monotonic()
        return source_cache


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8766, debug=False, use_reloader=False)
