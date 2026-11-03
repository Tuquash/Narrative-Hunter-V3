import os
from pathlib import Path

import requests


def load_env():
	env_path = Path(__file__).parent / ".env"

	if not env_path.exists():
		raise RuntimeError(".env file not found in the project folder.")

	for line in env_path.read_text(encoding="utf-8").splitlines():
		line = line.strip()

		if line and not line.startswith("#") and "=" in line:
			key, value = line.split("=", 1)
			os.environ.setdefault(
				key.strip(),
				value.strip().strip('"').strip("'")
			)


load_env()

BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

if not BOT_TOKEN:
	raise RuntimeError("TELEGRAM_BOT_TOKEN is missing from .env.")

if not CHAT_ID:
	raise RuntimeError("TELEGRAM_CHAT_ID is missing from .env.")

API_URL = f"https://api.telegram.org/bot{BOT_TOKEN}"


def send_alert(message):
	response = requests.post(
		f"{API_URL}/sendMessage",
		json={
			"chat_id": CHAT_ID,
			"text": message,
			"disable_web_page_preview": True,
		},
		timeout=15,
	)

	response.raise_for_status()
	result = response.json()

	if not result.get("ok"):
		raise RuntimeError("Telegram rejected the alert.")

	return True
