"""Live diagnostics for Narrative Hunter. Place beside narrative_hunter_early_entry.py and .env."""
import importlib.util
import os
from pathlib import Path
import requests

HERE = Path(__file__).resolve().parent
BOT_FILE = HERE / "narrative_hunter_early_entry.py"
if not BOT_FILE.exists():
    raise SystemExit("FAIL: narrative_hunter_early_entry.py must be in the same folder as this test file.")

spec = importlib.util.spec_from_file_location("narrative_hunter", BOT_FILE)
bot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bot)

print("\n=== NARRATIVE HUNTER LIVE DIAGNOSTICS ===")
print("Project folder:", HERE)
print("Python requests:", requests.__version__)

checks = []
def check(label, ok, detail=""):
    checks.append((label, bool(ok)))
    print(f"{'PASS' if ok else 'FAIL'}: {label}" + (f" — {detail}" if detail else ""))

# Check live discovery APIs.
dex = bot.get_json(bot.DEX_BASE + "/token-profiles/latest/v1")
check("DexScreener profiles endpoint reachable", isinstance(dex, list), f"response type={type(dex).__name__}")

pump = bot.get_json(bot.PUMP_BASE + "/coins", params={"offset": 0, "limit": 3, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "false"})
if isinstance(pump, dict):
    pump_items = pump.get("coins", pump.get("data", []))
else:
    pump_items = pump
check("Pump.fun endpoint reachable and response parseable", isinstance(pump_items, list), f"response type={type(pump_items).__name__}")

# Check market data endpoint with the well-known wrapped SOL mint; no trade is made.
sol_price = bot.get_json(bot.DEX_BASE + "/tokens/v1/solana/So11111111111111111111111111111111111111112")
check("DexScreener token-price endpoint reachable", isinstance(sol_price, list), f"response type={type(sol_price).__name__}")

# Check Telegram token without printing it. getMe does not send a message.
token = bot.TELEGRAM_BOT_TOKEN
chat_id = bot.TELEGRAM_CHAT_ID
telegram_ok = False
if token:
    try:
        r = requests.get(f"https://api.telegram.org/bot{token}/getMe", timeout=12)
        payload = r.json()
        telegram_ok = r.ok and payload.get("ok") is True
        bot_name = (payload.get("result") or {}).get("username", "unknown") if telegram_ok else ""
        check("Telegram bot token accepted", telegram_ok, f"bot=@{bot_name}" if telegram_ok else f"HTTP {r.status_code}; token not printed")
    except Exception as exc:
        check("Telegram bot token accepted", False, type(exc).__name__)
else:
    check("Telegram bot token configured", False, "Set TELEGRAM_BOT_TOKEN in .env; token was not found")

check("Telegram chat ID configured", bool(chat_id), "present" if chat_id else "not found in .env")

if telegram_ok and chat_id:
    choice = input("Send one real Telegram test message to your configured chat? Type YES to send: ").strip()
    if choice == "YES":
        ok = bot.send_telegram("<b>Narrative Hunter live test</b>\n\nTelegram delivery works. This is a test message; no trade was made.")
        check("Telegram test message delivered", ok)
    else:
        print("SKIP: Telegram message not sent (you did not type YES).")
else:
    print("SKIP: Cannot test Telegram delivery until both token and chat ID are valid.")

print("\n=== SUMMARY ===")
passed = sum(1 for _, ok in checks if ok)
print(f"{passed}/{len(checks)} checks passed.")
if any(not ok for _, ok in checks):
    print("At least one check failed. Review network access, endpoint availability, and .env variable names.")
else:
    print("All checks passed. This confirms source connectivity and, if opted in, Telegram delivery; it does not prove future alerts will be profitable or never missed.")
