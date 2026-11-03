# Narrative Hunter V3

A Python-based Solana token discovery and risk-screening tool that scans newly emerging tokens and sends Telegram alerts for qualifying opportunities.

## Main Script

`narrative_hunter_early_entry.py`

## Features

- Scans token data from DexScreener.
- Checks newly launched tokens from Pump.fun.
- Scores candidates using configurable screening criteria.
- Flags potential risks.
- Sends Telegram alerts for qualifying tokens.
- Tracks price milestones and alert cooldowns.
- Runs in signal-only mode. It does not execute trades.

## Screening Configuration

The scanner uses configurable thresholds, including:

- Early-entry market-cap threshold: $4,500
- Graduated-token market-cap threshold: $20,000
- Minimum liquidity: $5,000
- Minimum 24-hour volume: $10,000
- Maximum token age: 50 minutes

These are screening settings, not guarantees of performance.

## Installation

Requires Python 3.10 or newer.

Clone the repository:

```bash
git clone https://github.com/Tuquash/Narrative-Hunter-V3.git
cd Narrative-Hunter-V3
