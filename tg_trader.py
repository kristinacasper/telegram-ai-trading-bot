# -*- coding: utf-8 -*-
"""
Sanitized public portfolio demo.

This project demonstrates Python automation, Telegram integration, market-data
retrieval, SQLite persistence, and paper-trading workflow design.

IMPORTANT:
- This bot does NOT trade real money.
- The public signal logic below is intentionally simplified.
- Private strategy thresholds / scoring rules are not published here.
"""

import logging
import os
import sqlite3
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

import requests
from dotenv import load_dotenv
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes, JobQueue

load_dotenv()

# ============================= CONFIG =============================
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
INITIAL_USD = float(os.getenv("INITIAL_USD", "100"))
TRADE_AMOUNT_USD = float(os.getenv("TRADE_AMOUNT_USD", "10"))
TICK_SECONDS = int(os.getenv("TICK_SECONDS", "300"))
DB_PATH = os.getenv("DB_PATH", "trader_state.db")

# Public demo risk settings only. These are not production strategy parameters.
DEMO_STOP_LOSS_PCT = float(os.getenv("DEMO_STOP_LOSS_PCT", "0.03"))
DEMO_TAKE_PROFIT_PCT = float(os.getenv("DEMO_TAKE_PROFIT_PCT", "0.06"))

WATCHLIST = ["bitcoin", "ethereum", "solana"]
CG_BASE = "https://api.coingecko.com/api/v3"
CG_TIMEOUT = 10

logging.basicConfig(
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    level=logging.INFO,
)
log = logging.getLogger("tg_trader")


# ============================= DATABASE =============================
def db_init() -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS portfolio (
            id INTEGER PRIMARY KEY,
            cash_usd REAL NOT NULL,
            started_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS positions (
            coin_id TEXT PRIMARY KEY,
            symbol TEXT NOT NULL,
            qty REAL NOT NULL,
            entry_price REAL NOT NULL,
            entry_at TEXT NOT NULL,
            stop_loss REAL NOT NULL,
            take_profit REAL NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS trades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            side TEXT NOT NULL,
            coin_id TEXT NOT NULL,
            symbol TEXT NOT NULL,
            qty REAL NOT NULL,
            price REAL NOT NULL,
            usd REAL NOT NULL,
            pnl_usd REAL,
            reason TEXT
        )
        """
    )

    cur.execute("SELECT COUNT(*) FROM portfolio")
    if cur.fetchone()[0] == 0:
        now = datetime.now(timezone.utc).isoformat()
        cur.execute(
            "INSERT INTO portfolio (cash_usd, started_at, updated_at) VALUES (?, ?, ?)",
            (INITIAL_USD, now, now),
        )

    con.commit()
    con.close()


def db_get_cash() -> float:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT cash_usd FROM portfolio LIMIT 1")
    row = cur.fetchone()
    con.close()
    return float(row[0]) if row else 0.0


def db_set_cash(new_cash: float) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "UPDATE portfolio SET cash_usd=?, updated_at=? WHERE id=1",
        (new_cash, datetime.now(timezone.utc).isoformat()),
    )
    con.commit()
    con.close()


def db_get_positions() -> Dict[str, dict]:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        "SELECT coin_id, symbol, qty, entry_price, entry_at, stop_loss, take_profit FROM positions"
    )
    out: Dict[str, dict] = {}
    for row in cur.fetchall():
        out[row[0]] = {
            "coin_id": row[0],
            "symbol": row[1],
            "qty": row[2],
            "entry_price": row[3],
            "entry_at": row[4],
            "stop_loss": row[5],
            "take_profit": row[6],
        }
    con.close()
    return out


def db_upsert_position(position: dict) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO positions (coin_id, symbol, qty, entry_price, entry_at, stop_loss, take_profit)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(coin_id) DO UPDATE SET
            qty=excluded.qty,
            entry_price=excluded.entry_price,
            entry_at=excluded.entry_at,
            stop_loss=excluded.stop_loss,
            take_profit=excluded.take_profit
        """,
        (
            position["coin_id"],
            position["symbol"],
            position["qty"],
            position["entry_price"],
            position["entry_at"],
            position["stop_loss"],
            position["take_profit"],
        ),
    )
    con.commit()
    con.close()


def db_delete_position(coin_id: str) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("DELETE FROM positions WHERE coin_id=?", (coin_id,))
    con.commit()
    con.close()


def db_log_trade(
    side: str,
    coin_id: str,
    symbol: str,
    qty: float,
    price: float,
    usd: float,
    pnl: Optional[float] = None,
    reason: str = "",
) -> None:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute(
        """
        INSERT INTO trades (ts, side, coin_id, symbol, qty, price, usd, pnl_usd, reason)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            side,
            coin_id,
            symbol,
            qty,
            price,
            usd,
            pnl,
            reason,
        ),
    )
    con.commit()
    con.close()


def db_get_trade_count() -> int:
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.execute("SELECT COUNT(*) FROM trades")
    count = int(cur.fetchone()[0])
    con.close()
    return count


# ============================= MARKET DATA =============================
def cg_simple_price(ids: List[str]) -> Dict[str, dict]:
    if not ids:
        return {}
    try:
        response = requests.get(
            f"{CG_BASE}/simple/price",
            params={
                "ids": ",".join(ids),
                "vs_currencies": "usd",
                "include_24h_change": "true",
            },
            timeout=CG_TIMEOUT,
        )
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        log.warning("Price request failed: %s", exc)
        return {}


def cg_market_chart(coin_id: str, days: int = 3) -> List[float]:
    try:
        response = requests.get(
            f"{CG_BASE}/coins/{coin_id}/market_chart",
            params={"vs_currency": "usd", "days": str(days)},
            timeout=CG_TIMEOUT,
        )
        response.raise_for_status()
        return [point[1] for point in response.json().get("prices", [])]
    except Exception as exc:
        log.warning("Market history request failed for %s: %s", coin_id, exc)
        return []


def sma(values: List[float], window: int) -> Optional[float]:
    if len(values) < window:
        return None
    return sum(values[-window:]) / window


# ============================= SANITIZED DEMO SIGNAL =============================
def demo_signal(coin_id: str, price: float, change24: float) -> Tuple[str, str]:
    """Return a deliberately simplified public-demo signal.

    This function is not the original/private strategy. It exists only to keep
    the portfolio repository runnable while demonstrating the application flow.
    """
    series = cg_market_chart(coin_id, days=3)
    if len(series) < 12 or price <= 0:
        return "HOLD", "insufficient demo history"

    fast = sma(series, 4)
    slow = sma(series, 12)
    if fast is None or slow is None:
        return "HOLD", "moving average unavailable"

    if fast > slow and change24 > 0:
        return "BUY", "public demo trend condition"

    return "HOLD", "public demo hold condition"


# ============================= PAPER TRADING =============================
def execute_buy(coin_id: str, symbol: str, price: float, reason: str) -> Optional[str]:
    cash = db_get_cash()
    positions = db_get_positions()

    if price <= 0 or cash < TRADE_AMOUNT_USD or coin_id in positions:
        return None

    usd = min(TRADE_AMOUNT_USD, cash)
    qty = usd / price
    stop_loss = price * (1 - DEMO_STOP_LOSS_PCT)
    take_profit = price * (1 + DEMO_TAKE_PROFIT_PCT)

    db_set_cash(cash - usd)
    db_upsert_position(
        {
            "coin_id": coin_id,
            "symbol": symbol,
            "qty": qty,
            "entry_price": price,
            "entry_at": datetime.now(timezone.utc).isoformat(),
            "stop_loss": stop_loss,
            "take_profit": take_profit,
        }
    )
    db_log_trade("BUY", coin_id, symbol, qty, price, usd, None, reason)
    return f"BUY {symbol} qty={qty:.6f} @ ${price:.4f} for ${usd:.2f}"


def execute_sell(coin_id: str, price: float, reason: str) -> Optional[str]:
    positions = db_get_positions()
    if coin_id not in positions or price <= 0:
        return None

    position = positions[coin_id]
    qty = position["qty"]
    proceeds = qty * price
    cost = qty * position["entry_price"]
    pnl = proceeds - cost

    db_set_cash(db_get_cash() + proceeds)
    db_delete_position(coin_id)
    db_log_trade(
        "SELL",
        coin_id,
        position["symbol"],
        qty,
        price,
        proceeds,
        pnl,
        reason,
    )

    return (
        f"SELL {position['symbol']} qty={qty:.6f} @ ${price:.4f} "
        f"-> ${proceeds:.2f}, PnL ${pnl:+.2f}"
    )


async def tick_job(context: ContextTypes.DEFAULT_TYPE) -> None:
    price_map = cg_simple_price(WATCHLIST)

    # Risk checks for existing simulated positions.
    for coin_id, position in list(db_get_positions().items()):
        price = float(price_map.get(coin_id, {}).get("usd", 0) or 0)
        if price <= 0:
            continue
        if price <= position["stop_loss"]:
            execute_sell(coin_id, price, "DEMO_STOP_LOSS")
        elif price >= position["take_profit"]:
            execute_sell(coin_id, price, "DEMO_TAKE_PROFIT")

    # Simplified public-demo entry logic.
    positions = db_get_positions()
    for coin_id in WATCHLIST:
        if coin_id in positions:
            continue
        data = price_map.get(coin_id, {})
        price = float(data.get("usd", 0) or 0)
        change24 = float(data.get("usd_24h_change", 0) or 0)
        signal, reason = demo_signal(coin_id, price, change24)
        if signal == "BUY":
            execute_buy(coin_id, coin_id.upper(), price, reason)


# ============================= TELEGRAM COMMANDS =============================
async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    db_init()
    positions = db_get_positions()
    text = (
        "*AI Paper Trading Demo*\n\n"
        f"Virtual cash: *${db_get_cash():.2f}*\n"
        f"Open positions: *{len(positions)}*\n"
        f"Recorded trades: *{db_get_trade_count()}*\n\n"
        "Commands:\n"
        "/status - current watchlist prices\n"
        "/positions - open simulated positions\n"
        "/pnl - simulated portfolio PnL\n"
        "/buy <coin_id> - manual paper buy\n"
        "/sell <coin_id> - manual paper sell\n"
        "/close all - close all simulated positions\n\n"
        "Paper trading only. No real funds are used."
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    await cmd_start(update, ctx)


async def cmd_status(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    price_map = cg_simple_price(WATCHLIST)
    if not price_map:
        await update.message.reply_text("Market data is temporarily unavailable.")
        return

    lines = []
    for coin_id in WATCHLIST:
        data = price_map.get(coin_id, {})
        price = float(data.get("usd", 0) or 0)
        change24 = float(data.get("usd_24h_change", 0) or 0)
        lines.append(f"• `{coin_id}`: ${price:.4f} ({change24:+.2f}% 24h)")

    await update.message.reply_text("\n".join(lines), parse_mode="Markdown")


async def cmd_positions(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    positions = db_get_positions()
    if not positions:
        await update.message.reply_text("No open simulated positions.")
        return

    price_map = cg_simple_price(list(positions.keys()))
    lines = []
    for coin_id, position in positions.items():
        current = float(price_map.get(coin_id, {}).get("usd", position["entry_price"]))
        pnl = (current - position["entry_price"]) * position["qty"]
        lines.append(
            f"• `{position['symbol']}` qty={position['qty']:.6f}\n"
            f"  entry ${position['entry_price']:.4f} -> ${current:.4f}\n"
            f"  demo PnL ${pnl:+.2f}"
        )

    await update.message.reply_text("\n\n".join(lines), parse_mode="Markdown")


async def cmd_pnl(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    cash = db_get_cash()
    positions = db_get_positions()
    price_map = cg_simple_price(list(positions.keys()))

    position_value = 0.0
    for coin_id, position in positions.items():
        current = float(price_map.get(coin_id, {}).get("usd", position["entry_price"]))
        position_value += position["qty"] * current

    total = cash + position_value
    pnl = total - INITIAL_USD
    pnl_pct = (pnl / INITIAL_USD) * 100 if INITIAL_USD else 0.0

    text = (
        "*Paper Portfolio PnL*\n\n"
        f"Cash: *${cash:.2f}*\n"
        f"Positions: *${position_value:.2f}*\n"
        f"Total equity: *${total:.2f}*\n"
        f"PnL: *${pnl:+.2f} ({pnl_pct:+.2f}%)*"
    )
    await update.message.reply_text(text, parse_mode="Markdown")


async def cmd_buy(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /buy <coin_id>")
        return

    coin_id = ctx.args[0].lower()
    price_map = cg_simple_price([coin_id])
    if coin_id not in price_map:
        await update.message.reply_text("Unknown or unavailable coin_id.")
        return

    price = float(price_map[coin_id].get("usd", 0) or 0)
    message = execute_buy(coin_id, coin_id.upper(), price, "manual demo buy")
    await update.message.reply_text(message or "Buy could not be simulated.")


async def cmd_sell(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not ctx.args:
        await update.message.reply_text("Usage: /sell <coin_id>")
        return

    coin_id = ctx.args[0].lower()
    price_map = cg_simple_price([coin_id])
    if coin_id not in price_map:
        await update.message.reply_text("Unknown or unavailable coin_id.")
        return

    price = float(price_map[coin_id].get("usd", 0) or 0)
    message = execute_sell(coin_id, price, "manual demo sell")
    await update.message.reply_text(message or "No open position for that coin.")


async def cmd_close_all(update: Update, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    positions = db_get_positions()
    if not positions:
        await update.message.reply_text("No positions to close.")
        return

    price_map = cg_simple_price(list(positions.keys()))
    messages = []
    for coin_id, position in list(positions.items()):
        price = float(price_map.get(coin_id, {}).get("usd", position["entry_price"]))
        message = execute_sell(coin_id, price, "manual close all")
        if message:
            messages.append(message)

    await update.message.reply_text("\n".join(messages) if messages else "Nothing was closed.")


# ============================= STARTUP =============================
def main() -> None:
    if not BOT_TOKEN or BOT_TOKEN == "your_token_here":
        raise SystemExit("Set TELEGRAM_BOT_TOKEN in your local .env file.")

    db_init()
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("positions", cmd_positions))
    app.add_handler(CommandHandler("pnl", cmd_pnl))
    app.add_handler(CommandHandler("buy", cmd_buy))
    app.add_handler(CommandHandler("sell", cmd_sell))
    app.add_handler(CommandHandler("close", cmd_close_all))

    job_queue: JobQueue = app.job_queue
    job_queue.run_repeating(tick_job, interval=TICK_SECONDS, first=10)

    log.info("Sanitized paper-trading demo started.")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
