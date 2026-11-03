import os
import json
import time
from pathlib import Path
from datetime import datetime, timezone

import requests


# ============================================================
# NARRATIVE HUNTER V3
# Solana token discovery + risk flags + Telegram alerts
# Signal-only: NO TRADES ARE EXECUTED
# ============================================================

PROJECT_DIR = Path(__file__).parent
ENV_FILE = PROJECT_DIR / ".env"
STATE_FILE = PROJECT_DIR / "alert_state.json"

BASE_URL = "https://api.dexscreener.com"

PROFILE_URL = f"{BASE_URL}/token-profiles/latest/v1"
BOOST_URL = f"{BASE_URL}/token-boosts/latest/v1"
TOKEN_PAIRS_URL = f"{BASE_URL}/token-pairs/v1/solana/{{}}"
SEARCH_URL = f"{BASE_URL}/latest/dex/search"

MIN_LIQUIDITY = 5000
MIN_VOLUME_24H = 10000

MAX_CANDIDATES = 50
FAST_SCAN_INTERVAL_SECONDS = 120  # 2 minutes
NORMAL_SCAN_INTERVAL_SECONDS = 180  # 3 minutes

GOOD_TOKEN_SCORE = 75
MAX_EARLY_AGE_HOURS = 24

MIN_ALERT_SCORE = 60
MAX_TELEGRAM_ALERTS_PER_SCAN = 5
ALERT_COOLDOWN_HOURS = 6

SEARCH_TERMS = [
    "AI agent",
    "meme",
    "dog",
    "cat",
    "frog",
    "pepe",
    "trump",
    "solana meme",
]

session = requests.Session()


# ============================================================
# CONFIGURATION
# ============================================================

def load_env():
    """Load configuration from the local .env file."""

    if not ENV_FILE.exists():
        print("WARNING: .env file was not found.")
        return

    for line in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()

        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)

        os.environ.setdefault(
            key.strip(),
            value.strip().strip('"').strip("'"),
        )


load_env()

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")

TELEGRAM_ENABLED = bool(
    TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID
)


# ============================================================
# HTTP HELPERS
# ============================================================

def fetch_json(url, params=None):
    try:
        response = session.get(
            url,
            params=params,
            timeout=15,
        )
        response.raise_for_status()
        return response.json()

    except (requests.RequestException, ValueError) as error:
        print(f"\nAPI error: {error}")
        return None


# ============================================================
# TELEGRAM
# ============================================================

def send_telegram(message):
    """Send a Telegram message. Return True only on success."""

    if not TELEGRAM_ENABLED:
        print("Telegram is not configured. Skipping alert.")
        return False

    url = (
        f"https://api.telegram.org/"
        f"bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    )

    try:
        response = session.post(
            url,
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "disable_web_page_preview": True,
            },
            timeout=15,
        )

        response.raise_for_status()

        result = response.json()

        if not result.get("ok"):
            print("Telegram rejected the message.")
            return False

        return True

    except (requests.RequestException, ValueError) as error:
        print(f"Telegram error: {error}")
        return False


# ============================================================
# ALERT HISTORY
# ============================================================

def load_alert_state():
    """Load recent alert timestamps to reduce duplicate alerts."""

    if not STATE_FILE.exists():
        return {}

    try:
        data = json.loads(
            STATE_FILE.read_text(encoding="utf-8")
        )

        return data if isinstance(data, dict) else {}

    except (OSError, ValueError):
        print("WARNING: Could not read alert history.")
        return {}


def save_alert_state(state):
    try:
        STATE_FILE.write_text(
            json.dumps(state, indent=2),
            encoding="utf-8",
        )

    except OSError as error:
        print(f"Could not save alert history: {error}")


def can_alert(address, state):
    """Allow a new alert if the previous one is old enough."""

    previous = state.get(address)

    if not previous:
        return True

    try:
        last_alert = float(previous)
    except (TypeError, ValueError):
        return True

    elapsed = time.time() - last_alert

    return elapsed >= ALERT_COOLDOWN_HOURS * 3600


# ============================================================
# TOKEN DISCOVERY
# ============================================================

def discover_candidates():
    candidates = {}

    source_urls = [
        (PROFILE_URL, "profile"),
        (BOOST_URL, "boost"),
    ]

    for url, source in source_urls:
        data = fetch_json(url)

        if not isinstance(data, list):
            continue

        for token in data:
            if token.get("chainId") != "solana":
                continue

            address = token.get("tokenAddress")

            if not address:
                continue

            if address not in candidates:
                candidates[address] = {
                    "address": address,
                    "sources": set(),
                    "description": "",
                }

            candidates[address]["sources"].add(source)

            if token.get("description"):
                candidates[address]["description"] = (
                    token["description"]
                )

    for term in SEARCH_TERMS:
        data = fetch_json(
            SEARCH_URL,
            params={"q": term},
        )

        if not isinstance(data, dict):
            continue

        for pair in data.get("pairs") or []:
            if pair.get("chainId") != "solana":
                continue

            token = pair.get("baseToken") or {}
            address = token.get("address")

            if not address:
                continue

            if address not in candidates:
                candidates[address] = {
                    "address": address,
                    "sources": set(),
                    "description": "",
                }

            candidates[address]["sources"].add(
                f"search:{term}"
            )

        time.sleep(0.15)

    return list(candidates.values())[:MAX_CANDIDATES]


# ============================================================
# MARKET DATA
# ============================================================

def get_best_pair(address):
    data = fetch_json(
        TOKEN_PAIRS_URL.format(address)
    )

    if not isinstance(data, list) or not data:
        return None

    data.sort(
        key=lambda pair: (
            (pair.get("liquidity") or {}).get("usd") or 0
        ),
        reverse=True,
    )

    return data[0]


# ============================================================
# NARRATIVE CLUES
# ============================================================

def detect_narrative_clues(name, symbol, description):
    """
    Detect keyword clues from token metadata only.

    This does NOT verify social-media trends or organic demand.
    """

    text = (
        f"{name} {symbol} {description}"
    ).lower()

    themes = {
        "AI": [
            "ai",
            "artificial intelligence",
            "ai agent",
        ],
        "Dogs": [
            "dog",
            "doge",
            "puppy",
            "shiba",
        ],
        "Cats": [
            "cat",
            "kitten",
        ],
        "Frogs": [
            "frog",
            "pepe",
        ],
        "Political": [
            "trump",
            "political",
            "election",
        ],
        "Gaming": [
            "gaming",
            "gamefi",
            "game",
        ],
    }

    matches = []

    for theme, keywords in themes.items():
        if any(keyword in text for keyword in keywords):
            matches.append(theme)

    return matches or ["Unverified theme"]


# ============================================================
# RISK CHECKS
# ============================================================

def assess_risks(pair, liquidity, volume):
    """
    Flag observable warning signs.

    These checks do not establish that a token is safe.
    """

    risks = []

    changes = pair.get("priceChange") or {}

    change_5m = changes.get("m5") or 0
    change_1h = changes.get("h1") or 0
    change_24h = changes.get("h24") or 0

    txns = pair.get("txns") or {}
    txns_1h = txns.get("h1") or {}

    buys = txns_1h.get("buys") or 0
    sells = txns_1h.get("sells") or 0

    total_txns = buys + sells

    if liquidity < 10000:
        risks.append("Relatively low liquidity")

    if volume > 0 and liquidity > 0:
        if volume / liquidity > 20:
            risks.append("Very high volume relative to liquidity")

    if change_5m > 30:
        risks.append("Extreme 5-minute price increase")

    if change_1h > 100:
        risks.append("Extreme 1-hour price increase")

    if change_24h < -50:
        risks.append("Severe 24-hour price decline")

    if total_txns >= 10 and sells > buys * 2:
        risks.append("Strong sell-side transaction imbalance")

    if total_txns < 5:
        risks.append("Very limited recent transaction activity")

    if not pair.get("pairCreatedAt"):
        risks.append("Pool creation time unavailable")

    return risks


# ============================================================
# SCORING
# ============================================================

def calculate_score(pair, risks):
    score = 0
    signals = []

    liquidity = (
        (pair.get("liquidity") or {}).get("usd") or 0
    )

    volume = (
        (pair.get("volume") or {}).get("h24") or 0
    )

    changes = pair.get("priceChange") or {}

    change_5m = changes.get("m5") or 0
    change_1h = changes.get("h1") or 0
    change_24h = changes.get("h24") or 0

    txns = pair.get("txns") or {}
    txns_1h = txns.get("h1") or {}

    buys = txns_1h.get("buys") or 0
    sells = txns_1h.get("sells") or 0
    total_txns = buys + sells

    # Liquidity: maximum 30 points.
    if liquidity >= 50000:
        score += 30
        signals.append("Strong reported liquidity")
    elif liquidity >= 20000:
        score += 20
        signals.append("Good reported liquidity")
    elif liquidity >= MIN_LIQUIDITY:
        score += 10
        signals.append("Minimum liquidity passed")

    # Volume: maximum 25 points.
    if volume >= 100000:
        score += 25
        signals.append("High 24-hour volume")
    elif volume >= 50000:
        score += 20
        signals.append("Good 24-hour volume")
    elif volume >= MIN_VOLUME_24H:
        score += 10
        signals.append("Minimum volume passed")

    # Momentum: maximum 20 points.
    if 0 < change_5m <= 15:
        score += 5
        signals.append("Positive 5-minute momentum")

    if 0 < change_1h <= 30:
        score += 10
        signals.append("Positive 1-hour momentum")

    if 0 < change_24h <= 100:
        score += 5
        signals.append("Positive 24-hour momentum")

    # Trading activity: maximum 25 points.
    if total_txns >= 20:
        score += 10
        signals.append("Active recent trading")

    if total_txns > 0 and buys > sells:
        score += 10
        signals.append("More buys than sells")

    if total_txns > 0 and buys / total_txns >= 0.60:
        score += 5
        signals.append("Buy-heavy transaction count")

    # Risk penalties.
    if "Relatively low liquidity" in risks:
        score -= 5

    if "Very high volume relative to liquidity" in risks:
        score -= 10

    if "Extreme 5-minute price increase" in risks:
        score -= 10

    if "Extreme 1-hour price increase" in risks:
        score -= 10

    if "Severe 24-hour price decline" in risks:
        score -= 10

    if "Strong sell-side transaction imbalance" in risks:
        score -= 10

    if "Very limited recent transaction activity" in risks:
        score -= 5

    score = max(0, min(100, score))

    return score, signals


# ============================================================
# ANALYZE ONE TOKEN
# ============================================================

def analyze_candidate(candidate):
    address = candidate["address"]

    pair = get_best_pair(address)

    if not pair:
        return None

    liquidity = (
        (pair.get("liquidity") or {}).get("usd") or 0
    )

    volume = (
        (pair.get("volume") or {}).get("h24") or 0
    )

    if liquidity < MIN_LIQUIDITY:
        return None

    if volume < MIN_VOLUME_24H:
        return None

    created_at = pair.get("pairCreatedAt")
    age_hours = None

    if created_at:
        age_hours = max(
            0,
            (
                datetime.now(timezone.utc).timestamp()
                - created_at / 1000
            ) / 3600,
        )

    if (
        age_hours is not None
        and age_hours <= MAX_EARLY_AGE_HOURS
    ):
        category = "EARLY LAUNCH"
    else:
        category = "TRENDING / ESTABLISHED"

    token = pair.get("baseToken") or {}

    name = token.get("name", "Unknown")
    symbol = token.get("symbol", "???")

    narrative_clues = detect_narrative_clues(
        name,
        symbol,
        candidate.get("description", ""),
    )

    risks = assess_risks(
        pair,
        liquidity,
        volume,
    )

    score, signals = calculate_score(
        pair,
        risks,
    )

    return {
        "name": name,
        "symbol": symbol,
        "address": address,
        "category": category,
        "age_hours": age_hours,
        "liquidity": liquidity,
        "volume": volume,
        "price": pair.get("priceUsd", "Unknown"),
        "change_5m": (
            (pair.get("priceChange") or {}).get("m5") or 0
        ),
        "change_1h": (
            (pair.get("priceChange") or {}).get("h1") or 0
        ),
        "score": score,
        "signals": signals,
        "risks": risks,
        "narrative_clues": narrative_clues,
        "sources": sorted(candidate["sources"]),
        "url": pair.get("url", ""),
    }


# ============================================================
# TELEGRAM ALERT FORMATTING
# ============================================================

def format_alert(item):
    age = (
        f"{item['age_hours']:.1f} hours"
        if item["age_hours"] is not None
        else "Unknown"
    )

    risks = (
        "\n".join(f"- {risk}" for risk in item["risks"])
        if item["risks"]
        else "No configured warning flags triggered"
    )

    signals = (
        ", ".join(item["signals"])
        if item["signals"]
        else "No strong configured signals"
    )

    return (
        "NARRATIVE HUNTER V3 SIGNAL\n\n"
        f"Token: {item['name']} ({item['symbol']})\n"
        f"Category: {item['category']}\n"
        f"Score: {item['score']}/100 (experimental)\n"
        f"Pool age: {age}\n"
        f"Price: ${item['price']}\n"
        f"Liquidity: ${item['liquidity']:,.2f}\n"
        f"24h volume: ${item['volume']:,.2f}\n"
        f"5m change: {item['change_5m']}%\n"
        f"1h change: {item['change_1h']}%\n\n"
        f"Theme clues: {', '.join(item['narrative_clues'])}\n"
        f"Positive signals: {signals}\n\n"
        f"Risk flags:\n{risks}\n\n"
        f"Token address:\n{item['address']}\n\n"
        f"Chart: {item['url']}\n\n"
        "WARNING: A score is not a pump probability. "
        "Theme clues come from token metadata, not verified "
        "social trends. Check the token independently. "
        "No trade has been executed."
    )


def send_candidate_alerts(results):
    if not TELEGRAM_ENABLED:
        print(
            "\nTelegram alerts disabled. Check TELEGRAM_BOT_TOKEN "
            "and TELEGRAM_CHAT_ID in .env."
        )
        return

    state = load_alert_state()
    now = time.time()

    eligible = [
        item for item in results
        if item["score"] >= MIN_ALERT_SCORE
    ]

    eligible.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    sent_count = 0

    for item in eligible:
        if sent_count >= MAX_TELEGRAM_ALERTS_PER_SCAN:
            break

        address = item["address"]

        if not can_alert(address, state):
            continue

        message = format_alert(item)

        if send_telegram(message):
            print(
                f"Telegram alert sent: "
                f"{item['name']} ({item['symbol']})"
            )

            state[address] = now
            save_alert_state(state)

            sent_count += 1

        time.sleep(0.5)

    if sent_count == 0:
        print(
            "\nNo new qualifying Telegram alerts. "
            "There may be no candidates above the score threshold, "
            "or previous alerts may still be in cooldown."
        )


# ============================================================
# MAIN SCANNER
# ============================================================

def main():
    print("=" * 65)
    print("             NARRATIVE HUNTER V3")
    print("       SOLANA DISCOVERY + TELEGRAM ALERTS")
    print("=" * 65)

    print(
        "Scan time:",
        datetime.now(timezone.utc).strftime(
            "%Y-%m-%d %H:%M:%S UTC"
        ),
    )

    print(
        "Telegram:",
        "ENABLED" if TELEGRAM_ENABLED else "NOT CONFIGURED",
    )

    print("\nDiscovering candidates...\n")

    candidates = discover_candidates()

    if not candidates:
        print("No candidates discovered. Check your connection.")
        return

    print(f"Discovered {len(candidates)} candidate tokens.")

    results = []

    for index, candidate in enumerate(candidates, start=1):
        print(
            f"Analyzing token {index}/{len(candidates)}...",
            end="\r",
        )

        result = analyze_candidate(candidate)

        if result:
            results.append(result)

        time.sleep(0.15)

    results.sort(
        key=lambda item: item["score"],
        reverse=True,
    )

    print("\n\n" + "=" * 65)
    print("                    SCAN RESULTS")
    print("=" * 65)

    early = [
        item for item in results
        if item["category"] == "EARLY LAUNCH"
    ]

    trending = [
        item for item in results
        if item["category"] == "TRENDING / ESTABLISHED"
    ]

    for title, group in [
        ("EARLY LAUNCHES", early),
        ("TRENDING / ESTABLISHED", trending),
    ]:
        print(f"\n--- {title} ---")

        if not group:
            print("No candidates passed the current filters.")
            continue

        for item in group[:10]:
            age = (
                f"{item['age_hours']:.1f} hours"
                if item["age_hours"] is not None
                else "Unknown"
            )

            print(f"\n{item['name']} ({item['symbol']})")
            print(f"Score: {item['score']}/100")
            print(f"Pool age: {age}")
            print(f"Price: ${item['price']}")
            print(f"Liquidity: ${item['liquidity']:,.2f}")
            print(f"24h volume: ${item['volume']:,.2f}")
            print(
                "Theme clues:",
                ", ".join(item["narrative_clues"]),
            )
            print(
                "Signals:",
                ", ".join(item["signals"]) or "None",
            )
            print(
                "Risk flags:",
                ", ".join(item["risks"]) or "None triggered",
            )
            print(f"Address: {item['address']}")
            print(f"Chart: {item['url']}")

    print("\n" + "=" * 65)
    print(f"Qualified candidates: {len(results)}")
    print(f"Telegram alert threshold: {MIN_ALERT_SCORE}/100")
    print(
        f"Maximum alerts per scan: "
        f"{MAX_TELEGRAM_ALERTS_PER_SCAN}"
    )
    print(
        f"Repeat-alert cooldown: {ALERT_COOLDOWN_HOURS} hours"
    )
    print("Simulation only: no trades were executed.")
    print("Scores are experimental, not pump probabilities.")
    print("=" * 65)

    send_candidate_alerts(results)


if __name__ == "__main__":
    print("NARRATIVE HUNTER CONTINUOUS SCANNER")
    print("Default scan interval: 3 minutes")
    print("Press Ctrl+C to stop.\n")

    while True:
        scan_started = time.time()

        try:
            main()

        except KeyboardInterrupt:
            print("\nNarrative Hunter stopped by user.")
            break

        except Exception as error:
            print(f"\nUnexpected scanner error: {error}")
            print("The scanner will retry after 3 minutes.")

        elapsed = time.time() - scan_started
        wait_seconds = max(1, 180 - elapsed)

        print("\nNext scan in approximately 3 minutes.")
        print("Waiting...\n")

        try:
            time.sleep(wait_seconds)

        except KeyboardInterrupt:
            print("\nNarrative Hunter stopped by user.")
            break