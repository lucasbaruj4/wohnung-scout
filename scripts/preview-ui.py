#!/usr/bin/env python3
"""Serve read-only frontend options without starting another collector."""
from pathlib import Path
import sys
import threading
import time
from urllib.error import URLError
from urllib.request import ProxyHandler, Request, build_opener

from flask import Flask, Response, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scout import SEARCHES, parse_search

app = Flask(__name__, static_folder=str(ROOT / "static"))
photo_cache = {}
photos_checked = None
photo_lock = threading.Lock()


@app.get("/")
def preview():
    return send_from_directory(ROOT / "static/prototype", "index.html")


@app.get("/api/state")
def state():
    try:
        with build_opener(ProxyHandler({})).open("http://127.0.0.1:8765/api/state", timeout=5) as result:
            return Response(result.read(), content_type="application/json")
    except URLError:
        return {"error": "Start the main app for live data. Previews use labeled examples otherwise."}, 503


@app.get("/api/photos")
def photos():
    """Fill preview photos without running the collector or changing saved data."""
    global photos_checked
    with photo_lock:
        if photos_checked is None or time.monotonic() - photos_checked >= 1800:
            for _, url in SEARCHES:
                request = Request(url, headers={"User-Agent": "WohnungScout/1.0 personal research"})
                try:
                    with build_opener(ProxyHandler({})).open(request, timeout=8) as result:
                        rows = parse_search(result.read().decode("utf-8"))
                    photo_cache.update({row["id"]: row["image_url"] for row in rows if row.get("image_url")})
                except (URLError, OSError, ValueError):
                    continue
            photos_checked = time.monotonic()
        return dict(photo_cache)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8766, debug=False, use_reloader=False)
