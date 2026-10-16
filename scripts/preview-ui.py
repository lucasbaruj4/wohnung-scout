#!/usr/bin/env python3
"""Serve read-only frontend options without starting another collector."""
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

from flask import Flask, Response, send_from_directory

ROOT = Path(__file__).resolve().parents[1]
app = Flask(__name__, static_folder=str(ROOT / "static"))


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


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8766, debug=False, use_reloader=False)
