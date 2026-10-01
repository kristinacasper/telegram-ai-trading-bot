# AI Paper Trading Bot — Telegram Assistant

A public portfolio project demonstrating Python automation, market-data API integration, stateful paper trading, and Telegram interaction.

> **Portfolio note:** This repository is a sanitized public demo. The original strategy parameters and any private implementation details are intentionally not published. The included signal logic uses simplified demo rules for educational purposes only.

> **Safety note:** This project uses paper trading only. It does not place real trades or control real funds, and it is not financial advice.

## What the project demonstrates

- Python application architecture
- Telegram Bot API integration
- Real-time cryptocurrency market-data retrieval
- Automated scheduled jobs
- Lightweight signal evaluation
- Position and PnL tracking
- SQLite persistence
- Environment-variable based secret handling
- Basic risk controls and error handling

## High-level architecture

```text
Telegram user
     |
     v
Telegram Bot API
     |
     v
Python application -----> Market-data API
     |
     +-----> Signal evaluation (sanitized demo logic)
     |
     +-----> Paper-trading engine
     |
     +-----> SQLite portfolio / trade history
```

## Main capabilities

The bot can:

- retrieve market prices for a small watchlist,
- evaluate simplified demo market signals,
- simulate paper-trading entries and exits,
- maintain virtual cash and open positions,
- track trade history and PnL,
- apply demo risk controls,
- expose status and portfolio information through Telegram commands.

## Telegram commands

| Command | Description |
|---|---|
| `/start` | Show portfolio status and commands |
| `/status` | Show current watchlist prices |
| `/positions` | Show open paper-trading positions |
| `/pnl` | Show simulated portfolio PnL |
| `/buy <coin_id>` | Manually simulate a buy |
| `/sell <coin_id>` | Manually simulate a sell |
| `/close all` | Close all simulated positions |

## Security and privacy

Secrets are not stored in source code.

The Telegram token is loaded from an environment variable:

```python
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
```

The local `.env` file and database files are excluded from Git. Only `.env.example` is public, and it contains placeholder/demo values.

Never commit:

- Telegram bot tokens,
- exchange API credentials,
- wallet private keys or seed phrases,
- personal chat IDs,
- private strategy files,
- production database files.

## Running the demo

1. Install dependencies:

```bash
pip install python-telegram-bot[job-queue] requests python-dotenv
```

2. Copy the example configuration:

```bash
cp .env.example .env
```

3. Add your own Telegram bot token to the local `.env` file.

4. Run:

```bash
python tg_trader.py
```

## Public vs. private implementation

This repository intentionally separates **portfolio evidence** from **private strategy IP**.

Publicly visible:

- application structure,
- API integration,
- Telegram commands,
- database design,
- paper-trading flow,
- simplified demo signal logic.

Intentionally not published:

- private trading thresholds,
- proprietary weighting/scoring rules,
- production risk parameters,
- credentials or account identifiers.

## Tech stack

- Python
- python-telegram-bot
- CoinGecko public API
- SQLite
- python-dotenv
- APScheduler / Telegram JobQueue

## Project status

**Portfolio prototype / sanitized public demo.**

The purpose of this repository is to demonstrate implementation skills rather than publish a production trading strategy.

---

Built by **Kristina Casper** as an AI / automation portfolio project.
