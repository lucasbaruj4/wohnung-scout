"""Token-safe Telegram requests and private-chat pairing."""
import json
import os
import re
import secrets
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent


def credentials():
    values = {}
    path = ROOT / ".env"
    if path.exists():
        for line in path.read_text().splitlines():
            key, sep, value = line.partition("=")
            if sep and key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID"):
                values[key] = value
    return {key: os.environ.get(key, values.get(key, "")) for key in ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID")}


def call(token, method, data=None):
    if not re.fullmatch(r"\d+:[A-Za-z0-9_-]{20,}", token):
        raise RuntimeError("The bot token format is invalid. Copy the token from BotFather.")
    try:
        response = requests.post(f"https://api.telegram.org/bot{token}/{method}", json=data or {}, timeout=20)
        payload = response.json()
        if not response.ok or not payload.get("ok"):
            raise RuntimeError("Telegram rejected the request. Check the bot token and chat setup.")
        return payload["result"]
    except (requests.RequestException, ValueError):
        # Request exception URLs contain tokens. Never expose them to logs or the UI.
        raise RuntimeError("Telegram request failed. Check connectivity and try again.") from None


def notify(row):
    config = credentials()
    if not all(config.values()):
        return False
    text = (f"Würzburg · {row['size']:g} m²\n{row['title'][:220]}\n"
            f"Listed rent: €{row['rent']:g}\nEstimated monthly total: €{row['estimated_total']:g}\n"
            f"Estimated saving vs current home: €{row['estimated_saving']:g}/month\n"
            "Extra costs are a reserve, not verified utility charges.\n" + row["url"])
    call(config["TELEGRAM_BOT_TOKEN"], "sendMessage", {"chat_id": config["TELEGRAM_CHAT_ID"], "text": text})
    return True


def setup(command):
    config = credentials()
    token = config["TELEGRAM_BOT_TOKEN"]
    if command == "verify":
        bot = call(token, "getMe")
        print(bot["username"])
    elif command == "code":
        print("wohnung-" + secrets.token_hex(4))
    elif command == "pair":
        code = sys.argv[2]
        updates = call(token, "getUpdates", {"allowed_updates": ["message"]})
        matches = [u["message"] for u in updates if "message" in u
                   and u["message"].get("text", "").strip() == code
                   and u["message"].get("chat", {}).get("type") == "private"]
        if not matches:
            raise RuntimeError("Pairing message not found. Send the displayed code to your bot, then retry.")
        print(matches[-1]["chat"]["id"])
    elif command == "test":
        call(token, "sendMessage", {"chat_id": config["TELEGRAM_CHAT_ID"],
                                   "text": "Wohnung Scout is connected. New Würzburg apartment matches will appear here."})
        print("Test alert sent.")


if __name__ == "__main__":
    try:
        setup(sys.argv[1])
    except (RuntimeError, IndexError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
