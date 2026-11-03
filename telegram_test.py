import os
import requests
from pathlib import Path

# Read the local .env file without installing another package.
env_file = Path(__file__).parent / ".env"

if not env_file.exists():
	raise SystemExit("ERROR: .env file not found.")

for line in env_file.read_text(encoding="utf-8").splitlines():
	line = line.strip()

	if line and not line.startswith("#") and "=" in line:
		key, value = line.split("=", 1)
		os.environ[key.strip()] = value.strip().strip('"').strip("'")

token = os.getenv("TELEGRAM_BOT_TOKEN")

if not token or token == "PASTE_YOUR_BOT_TOKEN_HERE":
	raise SystemExit("ERROR: Add your real Telegram bot token to .env.")

base_url = f"https://api.telegram.org/bot{token}"

try:
	# Find messages sent to your bot.
	response = requests.get(
		f"{base_url}/getUpdates",
		timeout=15
	)
	response.raise_for_status()
	data = response.json()

	if not data.get("ok"):
		raise SystemExit(
			"Telegram rejected the request. Check your bot token."
		)

	updates = data.get("result", [])

	if not updates:
		raise SystemExit(
			"No messages found. Open your bot in Telegram, "
			"press Start, send /start, then run this script again."
		)

	# Use the most recent message to identify your chat.
	latest_update = updates[-1]
	message = (
		latest_update.get("message")
		or latest_update.get("edited_message")
	)

	if not message:
		raise SystemExit(
			"No normal chat message found. Send /start to your bot "
			"and run the script again."
		)

	chat_id = message["chat"]["id"]

	# Send a test alert.
	alert = (
		"NARRATIVE HUNTER: TELEGRAM CONNECTED\n\n"
		"Your bot can now send alerts to this chat.\n"
		"Next: connect it to the coin scanner."
	)

	result = requests.post(
		f"{base_url}/sendMessage",
		json={
			"chat_id": chat_id,
			"text": alert
		},
		timeout=15
	)
	result.raise_for_status()

	if not result.json().get("ok"):
		raise SystemExit("Telegram could not send the test message.")

	print("SUCCESS: Telegram alert sent.")
	print(f"Your Telegram chat ID is: {chat_id}")
	print("Check your Telegram chat.")

except requests.RequestException as error:
	print(f"NETWORK OR TELEGRAM ERROR: {error}")
