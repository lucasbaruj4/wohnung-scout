"""Local dashboard. One process owns the collector and its 30-minute schedule."""
import argparse
import threading
from pathlib import Path
from urllib.parse import urlparse

from flask import Flask, jsonify, request, send_from_directory

from scout import Collector, Store, evaluate, validate_settings
from telegram_alerts import credentials, notify

ROOT = Path(__file__).resolve().parent


def create_app(store, collector):
    app = Flask(__name__, static_folder="static")
    app.config["MAX_CONTENT_LENGTH"] = 8192

    @app.before_request
    def local_changes():
        if request.method == "POST":
            origin = request.headers.get("Origin")
            if origin and urlparse(origin).netloc != request.host:
                return jsonify(error="Open the dashboard directly to make changes."), 403
            if not request.is_json:
                return jsonify(error="Send JSON."), 415

    @app.get("/")
    def index():
        return send_from_directory(ROOT / "static", "index.html")

    @app.get("/api/state")
    def state():
        settings = store.settings()
        return jsonify(settings=settings, listings=evaluate(store.rows(), settings),
                       last_check=store.get("last_check"), last_success=store.get("last_success"),
                       errors=store.get("errors", []), scanning=collector.lock.locked(),
                       telegram_connected=all(credentials().values()), telegram_error=store.get("telegram_error"),
                       source="WG-Gesucht · first page of studios and apartments", interval_minutes=30)

    @app.post("/api/settings")
    def settings():
        try:
            value = validate_settings(request.get_json())
        except (KeyError, TypeError, ValueError) as exc:
            return jsonify(error=str(exc)), 400
        store.put("settings", value)
        return jsonify(settings=value)

    @app.post("/api/listings/<id>/status")
    def status(id):
        try:
            changed = store.status(id, request.get_json().get("status"))
        except ValueError as exc:
            return jsonify(error=str(exc)), 400
        return (jsonify(ok=True), 200) if changed else (jsonify(error="Listing not found."), 404)

    @app.post("/api/scan")
    def scan():
        if collector.lock.locked():
            return jsonify(error="A check is already running."), 409
        # Prevent repeated UI clicks from hammering the source.
        from datetime import datetime, timezone
        last = store.get("last_check")
        if last and (datetime.now(timezone.utc) - datetime.fromisoformat(last)).total_seconds() < 300:
            return jsonify(error="Checked recently. Wait five minutes before checking again."), 429
        threading.Thread(target=collector.scan, daemon=True).start()
        return jsonify(started=True), 202

    return app


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--once", action="store_true", help="Collect once without starting the dashboard")
    args = parser.parse_args()
    store = Store(ROOT / "data" / "scout.sqlite3")
    collector = Collector(store, notify)
    if args.once:
        collector.scan()
        print(f"Stored {len(store.rows())} listings. Source errors: {len(store.get('errors', []))}")
        if store.get("errors"):
            print("\n".join(store.get("errors")))
        return

    def schedule():
        while True:
            try:
                collector.scan()
            except Exception:
                store.put("errors", ["Collection failed. Existing results are preserved; the next check will retry."])
            threading.Event().wait(1800)

    threading.Thread(target=schedule, daemon=True).start()
    create_app(store, collector).run(host="127.0.0.1", port=args.port, debug=False, use_reloader=False)


if __name__ == "__main__":
    main()
