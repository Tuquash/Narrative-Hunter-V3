"""Narrative Hunter v4 — remade Solana meme-token discovery scanner.

Sources:
- DexScreener public endpoints (DEX-listed tokens/pairs)
- Pump.fun's currently public frontend endpoint (undocumented and may change)

This is a screening/alert tool, not a trading bot. It does not place trades.
"""

import html
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

BASE_DIR = Path(__file__).resolve().parent
ENV_FILE = BASE_DIR / ".env"
STATE_FILE = BASE_DIR / "alert_state.json"
PERFORMANCE_FILE = BASE_DIR / "performance_state.json"

# Filters requested by the user
EARLY_MIN_MARKET_CAP_USD = 4_500
GRADUATED_MIN_MARKET_CAP_USD = 20_000
MIN_LIQUIDITY_USD = 5_000          # Applied to DEX-listed candidates only
MIN_VOLUME_24H_USD = 10_000        # Applied to DEX-listed candidates only
MAX_TOKEN_AGE_MINUTES = 50       # Hard cutoff: never alert on tokens/pools older than 50 minutes
MAX_CANDIDATES = 60
MAX_ALERTS_PER_SCAN = 5
ALERT_SCORE_MIN = 60
FAST_SCAN_SECONDS = 120
NORMAL_SCAN_SECONDS = 180
ALERT_COOLDOWN_SECONDS = 6 * 60 * 60
REQUEST_TIMEOUT = 12

DEX_BASE = "https://api.dexscreener.com"
PUMP_BASE = "https://frontend-api-v3.pump.fun"
SOLANA = "solana"

SEARCH_TERMS = [
    "AI agent", "AI", "meme", "dog", "cat", "frog", "pepe",
    "trump", "gaming", "solana meme", "agent"
]
THEME_KEYWORDS = {
    "AI": ["ai", "agent", "gpt", "llm", "bot", "neural", "compute"],
    "Dogs": ["dog", "doge", "shib", "puppy", "inu", "woof"],
    "Cats": ["cat", "kitty", "meow", "feline"],
    "Frogs/Pepe": ["frog", "pepe", "ribbit"],
    "Politics": ["trump", "maga", "president", "election", "politics"],
    "Gaming": ["game", "gaming", "play", "arcade", "pixel"],
    "Culture/Meme": ["meme", "viral", "brainrot", "chad", " wojak", "cult"],
}

SESSION = requests.Session()
SESSION.headers.update({"User-Agent": "NarrativeHunter/4.0 (+public-data-screening)"})


def load_env_file():
    """Read simple KEY=VALUE lines without requiring python-dotenv."""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key, value = key.strip(), value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()
TELEGRAM_BOT_TOKEN = (os.getenv("TELEGRAM_BOT_TOKEN") or os.getenv("BOT_TOKEN") or "").strip()
TELEGRAM_CHAT_ID = (os.getenv("TELEGRAM_CHAT_ID") or os.getenv("CHAT_ID") or "").strip()


def get_json(url, params=None):
    try:
        response = SESSION.get(url, params=params, timeout=REQUEST_TIMEOUT)
        if response.status_code == 429:
            print(f"[WARN] Rate limited by {url}; skipping this source for now.")
            return None
        response.raise_for_status()
        return response.json()
    except (requests.RequestException, ValueError) as exc:
        print(f"[WARN] Source request failed ({url}): {exc}")
        return None


def as_float(value, default=0.0):
    try:
        if value is None or value == "":
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def safe_age_hours(timestamp):
    """Pump.fun creation timestamps are usually milliseconds; accept seconds too."""
    try:
        ts = float(timestamp)
        if ts > 10_000_000_000:
            ts /= 1000
        return max(0.0, (time.time() - ts) / 3600)
    except (TypeError, ValueError):
        return None


def theme_for(name, symbol, description=""):
    text = f"{name} {symbol} {description}".lower()
    found = []
    for theme, words in THEME_KEYWORDS.items():
        if any(word.strip() in text for word in words):
            found.append(theme)
    return found or ["Unclassified"]


def rating_for(score):
    if score >= 85:
        return "A"
    if score >= 75:
        return "B"
    if score >= 60:
        return "C"
    return "D"


def score_candidate(liquidity, volume, change_5m, change_1h, txns, age_hours, risks, narrative_clues):
    score = 25
    if liquidity >= 50_000:
        score += 18
    elif liquidity >= 15_000:
        score += 13
    elif liquidity >= MIN_LIQUIDITY_USD:
        score += 8
    if volume >= 100_000:
        score += 18
    elif volume >= 30_000:
        score += 13
    elif volume >= MIN_VOLUME_24H_USD:
        score += 8
    if 0 < change_5m <= 20:
        score += 8
    elif change_5m > 20:
        score += 3
    if 0 < change_1h <= 60:
        score += 12
    elif change_1h > 60:
        score += 5
    if txns >= 200:
        score += 12
    elif txns >= 60:
        score += 8
    elif txns >= 20:
        score += 4
    if age_hours is not None and age_hours <= 6:
        score += 6
    if len(narrative_clues) >= 2:
        score += 4
    score -= min(45, len(risks) * 9)
    return max(0, min(100, int(score)))


def fetch_dex_candidate_addresses():
    addresses = set()
    # Latest token profiles and boosts can surface newly noticed tokens.
    for endpoint in ("/token-profiles/latest/v1", "/token-boosts/latest/v1"):
        data = get_json(DEX_BASE + endpoint)
        if isinstance(data, list):
            for item in data[:250]:
                if str(item.get("chainId", "")).lower() == SOLANA and item.get("tokenAddress"):
                    addresses.add(item["tokenAddress"])

    # Search terms widen discovery, but search results are not proof of quality.
    for term in SEARCH_TERMS:
        data = get_json(DEX_BASE + "/latest/dex/search", {"q": term})
        pairs = data.get("pairs", []) if isinstance(data, dict) else []
        for pair in pairs[:25]:
            if str(pair.get("chainId", "")).lower() != SOLANA:
                continue
            base = pair.get("baseToken") or {}
            if base.get("address"):
                addresses.add(base["address"])
            if len(addresses) >= MAX_CANDIDATES * 3:
                return list(addresses)
    return list(addresses)


def analyze_dex_address(address):
    data = get_json(f"{DEX_BASE}/token-pairs/v1/solana/{address}")
    if not isinstance(data, list) or not data:
        return None
    pairs = [p for p in data if str(p.get("chainId", "")).lower() == SOLANA]
    if not pairs:
        return None
    pair = max(pairs, key=lambda p: as_float((p.get("liquidity") or {}).get("usd")))
    base = pair.get("baseToken") or {}
    liq = as_float((pair.get("liquidity") or {}).get("usd"))
    vol = as_float((pair.get("volume") or {}).get("h24"))
    # Deliberately do NOT use FDV as market cap. Reject if actual marketCap is absent.
    market_cap = as_float(pair.get("marketCap"), default=0.0)
    if market_cap <= 0:
        return None
    created_ms = pair.get("pairCreatedAt")
    age_hours = safe_age_hours(created_ms) if created_ms else None
    price_change = pair.get("priceChange") or {}
    txns = pair.get("txns") or {}
    h1 = txns.get("h1") or {}
    h24 = txns.get("h24") or {}
    tx_count = sum(as_float(v.get("buys")) + as_float(v.get("sells")) for v in (h1, h24))
    buys = as_float(h1.get("buys")) + as_float(h24.get("buys"))
    sells = as_float(h1.get("sells")) + as_float(h24.get("sells"))
    risks = []
    if liq < MIN_LIQUIDITY_USD:
        risks.append("Low liquidity")
    if vol < MIN_VOLUME_24H_USD:
        risks.append("Low 24h volume")
    if liq > 0 and vol / liq > 20:
        risks.append("Extreme volume/liquidity ratio")
    if tx_count < 20:
        risks.append("Low transaction count")
    if sells > buys * 1.5 and sells >= 10:
        risks.append("Sell transactions dominate")
    # Strict age gate: reject candidates if the DEX pool age is unknown or over 50 minutes.
    # For DEX-listed tokens, pairCreatedAt is pool age, not necessarily token mint age.
    if age_hours is None or age_hours * 60 > MAX_TOKEN_AGE_MINUTES:
        return None
    clues = theme_for(base.get("name", ""), base.get("symbol", ""))
    # DEX pool presence alone is not used as proof of Pump.fun graduation.
    stage = "DEX-listed — graduation unverified"
    change_5m = as_float(price_change.get("m5"))
    change_1h = as_float(price_change.get("h1"))
    score = score_candidate(liq, vol, change_5m, change_1h, tx_count, age_hours, risks, clues)
    if market_cap < GRADUATED_MIN_MARKET_CAP_USD:
        risks.append("Below $20,000 DEX-listed market-cap threshold")
    if liq < MIN_LIQUIDITY_USD or vol < MIN_VOLUME_24H_USD or market_cap < GRADUATED_MIN_MARKET_CAP_USD:
        return None
    return {
        "name": base.get("name") or "Unknown", "symbol": base.get("symbol") or "?",
        "address": address, "category": stage, "source": "DexScreener",
        "age_hours": age_hours, "market_cap": market_cap, "price_usd": as_float(pair.get("priceUsd"), 0.0), "liquidity": liq,
        "volume": vol, "change_5m": round(change_5m, 2), "change_1h": round(change_1h, 2),
        "txns": int(tx_count), "score": score, "rating": rating_for(score),
        "risks": risks, "narrative_clues": clues,
        "url": pair.get("url") or f"https://dexscreener.com/solana/{address}",
        "photon_url": f"https://photon-sol.tinyastro.io/en/lp/{address}",
        "pumpfun_url": f"https://pump.fun/coin/{address}",
    }


def fetch_pumpfun_candidates():
    """Scan Pump.fun's public frontend endpoint. This is undocumented and can break."""
    params = {"offset": 0, "limit": 50, "sort": "created_timestamp", "order": "DESC", "includeNsfw": "false"}
    data = get_json(PUMP_BASE + "/coins", params)
    if isinstance(data, dict):
        data = data.get("coins", data.get("data", []))
    if not isinstance(data, list):
        return []
    results = []
    for coin in data:
        address = coin.get("mint") or coin.get("address")
        if not address:
            continue
        # Require explicitly USD-denominated market-cap fields. Never treat SOL cap or FDV as USD MC.
        market_cap = as_float(coin.get("market_cap_usd") or coin.get("usd_market_cap"), 0.0)
        if market_cap <= 0:
            continue
        complete = coin.get("complete") is True
        age_hours = safe_age_hours(coin.get("created_timestamp"))
        stage = "Graduated (Pump.fun complete flag)" if complete else "Bonding curve (not graduated)"
        min_cap = GRADUATED_MIN_MARKET_CAP_USD if complete else EARLY_MIN_MARKET_CAP_USD
        if market_cap < min_cap:
            continue
        name = coin.get("name") or "Unknown"
        symbol = coin.get("symbol") or "?"
        description = coin.get("description") or ""
        clues = theme_for(name, symbol, description)
        risks = []
        # Strict age gate: no Pump.fun candidate can qualify without a creation timestamp,
        # or if its age exceeds 50 minutes. This applies to graduated and ungraduated tokens.
        if age_hours is None or age_hours * 60 > MAX_TOKEN_AGE_MINUTES:
            continue
        # Pump.fun responses may omit comparable DEX liquidity and volume. Do not fabricate them.
        liq = 0.0
        volume = 0.0
        score = 35 + min(20, len(clues) * 5)
        if age_hours is not None and age_hours <= 6:
            score += 8
        if complete:
            score += 5
        score -= min(20, len(risks) * 8)
        score = max(0, min(100, int(score)))
        results.append({
            "name": name, "symbol": symbol, "address": address,
            "category": stage, "source": "Pump.fun public frontend",
            "age_hours": age_hours, "market_cap": market_cap, "price_usd": as_float(coin.get("price_usd") or coin.get("usd_price") or coin.get("priceUsd"), 0.0),
            "liquidity": liq, "volume": volume,
            "change_5m": None, "change_1h": None, "txns": None,
            "score": score, "rating": rating_for(score), "risks": risks,
            "narrative_clues": clues,
            "url": f"https://pump.fun/coin/{address}",
            "photon_url": f"https://photon-sol.tinyastro.io/en/ray/{address}",
            "pumpfun_url": f"https://pump.fun/coin/{address}",
        })
    return results


def scan_once():
    candidates = {}
    print("[SCAN] Scanning DexScreener...")
    addresses = fetch_dex_candidate_addresses()
    print(f"[INFO] Checking {len(addresses)} discovered DEX token addresses.")
    for address in addresses[:MAX_CANDIDATES]:
        item = analyze_dex_address(address)
        if item:
            candidates[item["address"]] = item

    print("[SCAN] Scanning Pump.fun latest launches...")
    for item in fetch_pumpfun_candidates():
        # Prefer the Pump.fun result where it has bonding-curve/graduation information.
        existing = candidates.get(item["address"])
        if existing:
            item["liquidity"] = existing["liquidity"]
            item["volume"] = existing["volume"]
            item["change_5m"] = existing["change_5m"]
            item["change_1h"] = existing["change_1h"]
            item["txns"] = existing["txns"]
            item["price_usd"] = existing.get("price_usd", 0.0)
            item["url"] = existing["url"]
            item["source"] = "Pump.fun + DexScreener"
        candidates[item["address"]] = item

    results = list(candidates.values())
    results.sort(key=lambda item: (item["score"], item["market_cap"]), reverse=True)
    print(f"[INFO] Qualified candidates: {len(results)}")
    for item in results[:20]:
        print(f"[{item['rating']}] {item['name']} (${item['symbol']}) | MC ${item['market_cap']:,.0f} | score {item['score']} | {item['category']}")
    send_candidate_alerts(results)
    return results


def load_alert_state():
    try:
        if STATE_FILE.exists():
            data = json.loads(STATE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def save_alert_state(state):
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] Could not save alert state: {exc}")


def format_alert(item):
    """HTML code formatting makes the contract address easy to select/copy in Telegram."""
    esc = lambda value: html.escape(str(value if value is not None else "N/A"), quote=True)
    age = "Unknown" if item.get("age_hours") is None else (f"{item['age_hours'] * 60:.0f} minutes" if item['age_hours'] * 60 < 60 else f"{item['age_hours']:.1f} hours")
    change_5m = "N/A" if item.get("change_5m") is None else f"{item['change_5m']}%"
    change_1h = "N/A" if item.get("change_1h") is None else f"{item['change_1h']}%"
    liq = "Not reported" if not item.get("liquidity") else f"${item['liquidity']:,.2f}"
    vol = "Not reported" if not item.get("volume") else f"${item['volume']:,.2f}"
    txns = "Not reported" if item.get("txns") is None else str(item["txns"])
    clues = ", ".join(item.get("narrative_clues") or []) or "None detected"
    risks = item.get("risks") or []
    risk_text = "\n".join(f"• {esc(risk)}" for risk in risks) if risks else "No automated risk flags; this is not proof of safety."
    chart_url = esc(item.get("url", "https://dexscreener.com/solana"))
    photon_url = esc(item.get("photon_url", "https://photon-sol.tinyastro.io"))
    pump_url = esc(item.get("pumpfun_url", "https://pump.fun"))
    return (
        f"<b>NARRATIVE HUNTER — RATING {esc(item.get('rating'))}</b>\n\n"
        f"<b>Token:</b> {esc(item.get('name'))} (${esc(item.get('symbol'))})\n"
        f"<b>Score:</b> {esc(item.get('score'))}/100\n"
        f"<b>Stage:</b> {esc(item.get('category'))}\n"
        f"<b>Market cap (USD):</b> ${item['market_cap']:,.0f}\n"
        f"<b>Liquidity:</b> {esc(liq)}\n"
        f"<b>24h volume:</b> {esc(vol)}\n"
        f"<b>5m change:</b> {esc(change_5m)} | <b>1h change:</b> {esc(change_1h)}\n"
        f"<b>Age:</b> {esc(age)} | <b>Transactions:</b> {esc(txns)}\n"
        f"<b>Narrative clues:</b> {esc(clues)}\n\n"
        f"<b>CONTRACT ADDRESS — COPY THIS</b>\n<code>{esc(item.get('address'))}</code>\n\n"
        f"<a href=\"{chart_url}\">Open chart</a> | "
        f"<a href=\"{photon_url}\">Open Photon</a> | "
        f"<a href=\"{pump_url}\">Open Pump.fun</a>\n\n"
        f"<b>Risk flags:</b>\n{risk_text}\n\n"
        f"<b>Age limit:</b> {MAX_TOKEN_AGE_MINUTES} minutes maximum. "
        "For DEX-listed tokens, age is based on pool creation time, which may differ from mint age.\n"
        "<b>Warning:</b> Experimental screening only. Ratings do not predict a pump. "
        "Pump.fun's public frontend endpoint is undocumented and may stop working."
    )


def send_telegram(message):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("[WARN] Telegram credentials not found in .env; alert skipped.")
        return False
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    try:
        response = SESSION.post(url, data={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }, timeout=REQUEST_TIMEOUT)
        if not response.ok:
            print(f"[WARN] Telegram send failed: {response.status_code} {response.text[:300]}")
            return False
        return True
    except requests.RequestException as exc:
        print(f"[WARN] Telegram request failed: {exc}")
        return False


def load_performance_state():
    try:
        if PERFORMANCE_FILE.exists():
            data = json.loads(PERFORMANCE_FILE.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        pass
    return {}


def save_performance_state(state):
    try:
        PERFORMANCE_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")
    except OSError as exc:
        print(f"[WARN] Could not save performance state: {exc}")


def track_new_candidate(item):
    """Store the first available USD price as the tracking baseline."""
    address = item.get("address")
    price = as_float(item.get("price_usd"), 0.0)
    if not address:
        return
    state = load_performance_state()
    if address not in state:
        state[address] = {
            "name": item.get("name", "Unknown"),
            "symbol": item.get("symbol", "?"),
            "entry_price": price if price > 0 else None,
            "baseline_pending": price <= 0,
            "tracked_since": time.time(),
            "milestones_sent": [],
            "url": item.get("url") or f"https://dexscreener.com/solana/{address}",
        }
        save_performance_state(state)


def fetch_current_prices(addresses):
    """Fetch current prices in batches of up to 30 tokens using DexScreener."""
    prices = {}
    for start in range(0, len(addresses), 30):
        batch = addresses[start:start + 30]
        if not batch:
            continue
        data = get_json(f"{DEX_BASE}/tokens/v1/solana/{','.join(batch)}")
        if not isinstance(data, list):
            continue
        for pair in data:
            if str(pair.get("chainId", "")).lower() != SOLANA:
                continue
            address = (pair.get("baseToken") or {}).get("address")
            price = as_float(pair.get("priceUsd"), 0.0)
            if not address or price <= 0:
                continue
            liquidity = as_float((pair.get("liquidity") or {}).get("usd"), 0.0)
            old = prices.get(address)
            if old is None or liquidity > old[1]:
                prices[address] = (price, liquidity)
    return {address: value[0] for address, value in prices.items()}


def format_milestone_alert(item, entry_price, current_price, multiple, percent_gain, label):
    address = html.escape(str(item.get("address", "")), quote=True)
    name = html.escape(str(item.get("name", "Unknown")), quote=True)
    symbol = html.escape(str(item.get("symbol", "?")), quote=True)
    url = html.escape(str(item.get("url") or f"https://dexscreener.com/solana/{item.get('address','')}"), quote=True)
    return (
        f"<b>NARRATIVE HUNTER — PRICE MILESTONE</b>\n\n"
        f"<b>Token:</b> {name} (${symbol})\n"
        f"<b>Milestone:</b> {label}\n"
        f"<b>Change from tracking baseline:</b> +{percent_gain:.1f}%\n"
        f"<b>Multiple:</b> {multiple:.2f}x\n"
        f"<b>Baseline price:</b> ${entry_price:.10f}\n"
        f"<b>Current price:</b> ${current_price:.10f}\n\n"
        f"<b>Contract address — copy this</b>\n<code>{address}</code>\n\n"
        f"<a href=\"{url}\">Open chart</a>\n"
        "<i>Price changes are based on the first tracked USD price, not your actual wallet purchase price. Polling can miss fast moves.</i>"
    )


def monitor_price_milestones():
    """Alert once at +30%, 2x, 3x, 4x, etc. based on observed USD price."""
    state = load_performance_state()
    if not state:
        return
    addresses = list(state.keys())
    current_prices = fetch_current_prices(addresses)
    changed = False
    for address, item in state.items():
        price = current_prices.get(address)
        if not price or price <= 0:
            continue
        entry = as_float(item.get("entry_price"), 0.0)
        if entry <= 0:
            item["entry_price"] = price
            item["baseline_pending"] = False
            item["baseline_set_at"] = time.time()
            changed = True
            if send_telegram(
                "<b>NARRATIVE HUNTER — PRICE TRACKING STARTED</b>\n\n"
                f"<b>Token:</b> {html.escape(str(item.get('name', 'Unknown')))} (${html.escape(str(item.get('symbol', '?')))})\n"
                f"<b>Baseline price:</b> ${price:.10f}\n"
                f"<b>Contract address — copy this</b>\n<code>{html.escape(address)}</code>\n\n"
                "The initial alert did not include a usable USD price. Milestone tracking starts from this first available price."
            ):
                print(f"[TRACK] Started price baseline for {item.get('symbol')}.")
            continue
        multiple = price / entry
        percent_gain = (multiple - 1.0) * 100
        sent = set(item.get("milestones_sent", []))
        milestones = []
        if percent_gain >= 30 and "30pct" not in sent:
            milestones.append(("30pct", 1.3, "+30%"))
        # Notify at every whole multiple from 2x upward; each milestone only once.
        if multiple >= 2:
            whole_multiple = int(multiple)
            for level in range(2, min(whole_multiple, 100) + 1):
                key = f"{level}x"
                if key not in sent:
                    milestones.append((key, float(level), f"{level}x or more"))
        for key, target_multiple, label in milestones:
            if send_telegram(format_milestone_alert(item, entry, price, multiple, percent_gain, label)):
                sent.add(key)
                item["milestones_sent"] = sorted(sent)
                changed = True
                print(f"[MILESTONE] {item.get('symbol')} reached {label} (observed {multiple:.2f}x).")
        item["last_price"] = price
        item["last_checked_at"] = time.time()
        changed = True
    if changed:
        save_performance_state(state)


def send_candidate_alerts(results):
    state = load_alert_state()
    now = time.time()
    sent = 0
    for item in results:
        if item.get("score", 0) < ALERT_SCORE_MIN:
            continue
        address = item.get("address")
        if not address:
            continue
        last_sent = as_float(state.get(address), 0)
        if now - last_sent < ALERT_COOLDOWN_SECONDS:
            continue
        if send_telegram(format_alert(item)):
            state[address] = now
            track_new_candidate(item)
            sent += 1
            print(f"[ALERT] Sent {item.get('symbol')} ({item.get('rating')}) to Telegram.")
        if sent >= MAX_ALERTS_PER_SCAN:
            break
    save_alert_state(state)


def main():
    print("Narrative Hunter Early Entry + Price Milestones starting. Press Ctrl+C to stop.")
    print("Sources: public DexScreener + Pump.fun frontend; Telegram alerts enabled if .env is configured. Price milestones: +30%, 2x, 3x, 4x and onward.")
    while True:
        started = time.time()
        try:
            monitor_price_milestones()
            results = scan_once()
        except KeyboardInterrupt:
            raise
        except Exception as exc:
            print(f"[ERROR] Scan failed but the loop will continue: {exc}")
            results = []
        elapsed = time.time() - started
        has_good_candidates = any(item.get("score", 0) >= ALERT_SCORE_MIN for item in results)
        interval = FAST_SCAN_SECONDS if has_good_candidates else NORMAL_SCAN_SECONDS
        sleep_for = max(5, interval - elapsed)
        print(f"[INFO] Next scan in {int(sleep_for)} seconds.\n")
        time.sleep(sleep_for)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nNarrative Hunter stopped.")
