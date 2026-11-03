# Narrative Hunter V3

A Python-based Solana token discovery and screening tool that scans public market data and sends Telegram alerts for qualifying candidates.

## Main Script

The recommended entry point is `narrative_hunter_early_entry.py`.

The repository also contains alternative scanner versions for comparison.

## Features

- Scans Solana token listings using public market data.
- Discovers candidates from DexScreener and Pump.fun.
- Applies liquidity, trading-volume and token-age filters.
- Uses heuristic scoring to rank potential candidates.
- Identifies keyword-based narratives.
- Sends Telegram alerts when configured.
- Tracks price movements against the first observed price.
- Monitors milestones such as +30%, 2x, 3x and 4x.

## Screening Settings

- Minimum DexScreener liquidity: $5,000
- Minimum 24-hour volume: $10,000
- Maximum candidate age: 50 minutes
- Minimum alert score: 60
- Maximum alerts per scan: 5
- Token alert cooldown: 6 hours
- Fast scan interval: 120 seconds
- Normal scan interval: 180 seconds

These are screening rules, not guarantees of performance.

## Requirements

- Python 3.10 or newer
- pip
- Internet connection
- Telegram bot credentials if Telegram alerts are required

## Installation

```bash
git clone https://github.com/Tuquash/Narrative-Hunter-V3.git
cd Narrative-Hunter-V3
python -m venv .venv
```

On Windows PowerShell:

```powershell
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
```

## Running the Scanner

```bash
python narrative_hunter_early_entry.py
```

Check the script configuration and Telegram setup before running it.

## Telegram Configuration

Telegram alerts require a bot token and chat ID if the script is configured to send them.

Keep credentials in local environment variables or a local configuration file excluded from Git. Never upload bot tokens, API keys or private credentials to GitHub.

## Limitations and Risks

- This is a discovery and alerting tool, not an automated trading bot.
- It does not execute trades or connect to a trading wallet.
- Its scoring system uses heuristics and cannot guarantee price increases.
- Keyword matching is not genuine AI analysis or live social-media sentiment analysis.
- Liquidity and volume filters do not establish that a token is safe or sellable.
- It does not guarantee detection of scams, honeypots, concentrated holders or malicious token permissions.
- Public endpoints can change, fail or impose rate limits.
- Price milestones use the scanner's first observed price as a baseline, not your personal purchase price.

Always conduct independent research before trading. You can lose your entire investment in speculative tokens.

## Project Status

Experimental Python project under development. Features and screening rules may change.

## Author

GitHub: https://github.com/Tuquash
