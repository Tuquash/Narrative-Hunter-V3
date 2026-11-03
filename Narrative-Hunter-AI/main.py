import requests
from datetime import datetime, timezone

URL = 'https://api.dexscreener.com/token-profiles/latest/v1'
PAIR_URL = 'https://api.dexscreener.com/latest/dex/tokens/{}'


def scan():
    print('Fetching recent token profiles...')
    profiles = requests.get(URL, timeout=20)
    profiles.raise_for_status()
    solana = [p for p in profiles.json() if p.get('chainId') == 'solana'][:12]
    if not solana:
        print('No Solana profiles in this response. Try again later.')
        return
    for profile in solana:
        address = profile.get('tokenAddress')
        if not address:
            continue
        try:
            result = requests.get(PAIR_URL.format(address), timeout=20)
            result.raise_for_status()
            pairs = [p for p in result.json().get('pairs') or [] if p.get('chainId') == 'solana']
            if not pairs:
                continue
            pair = max(pairs, key=lambda p: (p.get('liquidity') or {}).get('usd') or 0)
            token = pair.get('baseToken') or {}
            if token.get('address') != address:
                token = pair.get('quoteToken') or {}
            created = pair.get('pairCreatedAt')
            age = (datetime.now(timezone.utc).timestamp() * 1000 - created) / 60000 if created else None
            print(f"\n{token.get('symbol', '?')} | {address}")
            print(f"Price: ${pair.get('priceUsd', '?')} | Liquidity: ${(pair.get('liquidity') or {}).get('usd', 0):,.0f}")
            print(f"24h volume: ${(pair.get('volume') or {}).get('h24', 0):,.0f} | Pair age: {age:.0f} min" if age is not None else f"24h volume: ${(pair.get('volume') or {}).get('h24', 0):,.0f} | Pair age: unknown")
            print(f"Chart: {pair.get('url', 'N/A')}")
        except (requests.RequestException, ValueError, TypeError) as exc:
            print(f'Could not inspect {address}: {exc}')


if __name__ == '__main__':
    try:
        scan()
    except (requests.RequestException, ValueError) as exc:
        print(f'Unable to fetch token profiles: {exc}')
