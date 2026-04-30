"""
ingester.py
Fetches stock bars from Alpaca and stores them in the database.

Two modes (controlled by the INGESTER_MODE environment variable):
  - "daily" (default): Fetches the last week of bars for the watchlist. Fast. Used by cron.
  - "backfill": Fetches 2 years of history for the watchlist. Run once manually.

The watchlist is S&P 500 + Nasdaq 100 (~550 symbols), defined in watchlist.py.
"""

import os
import time
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from database import SessionLocal, DailyBar, init_db
from watchlist import get_watchlist_symbols

load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")
MODE = os.getenv("INGESTER_MODE", "daily").lower()

if not API_KEY or not SECRET_KEY:
    raise ValueError("Missing Alpaca credentials. Check your .env file.")

# How many symbols to request from Alpaca in a single API call.
# Alpaca supports many symbols per call; 200 is a safe sweet spot.
SYMBOLS_PER_CALL = 200

# How many database rows to insert before committing a batch.
DB_BATCH_SIZE = 5000


def check_account():
    """Verify connection by fetching account info."""
    trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)
    account = trading_client.get_account()
    print("=" * 60)
    print("ACCOUNT INFO")
    print("=" * 60)
    print(f"Status:           {account.status}")
    print(f"Buying Power:     ${account.buying_power}")
    print(f"Portfolio Value:  ${account.portfolio_value}")
    print()


def fetch_bars_for_symbols(data_client, symbols, start, end):
    """Fetch daily bars for a batch of symbols in one API call."""
    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    return data_client.get_stock_bars(request)


def store_bars(session, bars_response, symbols):
    """Insert bars into the database, skipping duplicates. Returns (inserted, skipped)."""
    inserted = 0
    skipped = 0
    pending = []

    for symbol in symbols:
        symbol_bars = bars_response.data.get(symbol, [])
        for bar in symbol_bars:
            pending.append(
                DailyBar(
                    symbol=symbol,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
            )

    # Insert in chunks to keep memory low and transactions reasonable
    for i in range(0, len(pending), DB_BATCH_SIZE):
        chunk = pending[i : i + DB_BATCH_SIZE]
        for row in chunk:
            existing = (
                session.query(DailyBar)
                .filter_by(symbol=row.symbol, timestamp=row.timestamp)
                .first()
            )
            if existing:
                skipped += 1
            else:
                session.add(row)
                inserted += 1
        session.commit()
    return inserted, skipped


def run_backfill(years_back: int = 2):
    """Backfill mode: fetch many years of daily history for the watchlist."""
    print("=" * 60)
    print(f"BACKFILL MODE: {years_back} years of daily history")
    print("=" * 60)

    symbols = get_watchlist_symbols()
    print(f"\nBackfilling {len(symbols):,} watchlist symbols...\n")

    data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    end = datetime.now() - timedelta(minutes=20)
    start = end - timedelta(days=years_back * 365)

    total_inserted = 0
    total_skipped = 0
    failed_batches = 0
    start_time = time.time()

    session = SessionLocal()
    try:
        for i in range(0, len(symbols), SYMBOLS_PER_CALL):
            batch = symbols[i : i + SYMBOLS_PER_CALL]
            batch_num = i // SYMBOLS_PER_CALL + 1
            total_batches = (len(symbols) + SYMBOLS_PER_CALL - 1) // SYMBOLS_PER_CALL
            elapsed = time.time() - start_time
            print(
                f"[Batch {batch_num}/{total_batches}] "
                f"Symbols {i + 1}-{min(i + SYMBOLS_PER_CALL, len(symbols))}  "
                f"(elapsed: {elapsed:.0f}s)"
            )

            try:
                response = fetch_bars_for_symbols(data_client, batch, start, end)
                ins, skp = store_bars(session, response, batch)
                total_inserted += ins
                total_skipped += skp
                print(f"  Inserted: {ins:,}  Skipped: {skp:,}")
            except Exception as e:
                print(f"  ❌ Batch failed: {e}")
                failed_batches += 1
                session.rollback()
                # Sleep briefly and continue
                time.sleep(2)
                continue

            # Gentle rate-limit cushion (Alpaca allows 200 req/min)
            time.sleep(0.5)
    finally:
        session.close()

    elapsed = time.time() - start_time
    print()
    print("=" * 60)
    print(f"BACKFILL COMPLETE in {elapsed / 60:.1f} minutes")
    print(f"Total inserted: {total_inserted:,}")
    print(f"Total skipped:  {total_skipped:,}")
    print(f"Failed batches: {failed_batches}")
    print("=" * 60)


def run_daily():
    """Daily mode: fetch the last week of bars for the watchlist (incremental)."""
    print("=" * 60)
    print("DAILY MODE: incremental update")
    print("=" * 60)

    symbols = get_watchlist_symbols()
    print(f"Updating {len(symbols):,} watchlist symbols...\n")

    data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    end = datetime.now() - timedelta(minutes=20)
    start = end - timedelta(days=7)  # last 7 days catches any missed days

    total_inserted = 0
    total_skipped = 0
    start_time = time.time()

    session = SessionLocal()
    try:
        for i in range(0, len(symbols), SYMBOLS_PER_CALL):
            batch = symbols[i : i + SYMBOLS_PER_CALL]
            try:
                response = fetch_bars_for_symbols(data_client, batch, start, end)
                ins, skp = store_bars(session, response, batch)
                total_inserted += ins
                total_skipped += skp
            except Exception as e:
                print(f"  ❌ Batch starting at {i} failed: {e}")
                session.rollback()
                continue
            time.sleep(0.5)
    finally:
        session.close()

    elapsed = time.time() - start_time
    print(f"\n✅ Daily update complete in {elapsed:.1f}s")
    print(f"Inserted: {total_inserted:,}  Skipped: {total_skipped:,}")


def show_database_summary():
    """Print a quick summary of what's currently in the database."""
    session = SessionLocal()
    try:
        total_bars = session.query(DailyBar).count()
        total_symbols = (
            session.query(DailyBar.symbol).distinct().count()
        )
        print(f"\nDatabase contains {total_bars:,} bars across {total_symbols:,} symbols.")
    finally:
        session.close()


def main():
    init_db()
    check_account()

    if MODE == "backfill":
        run_backfill(years_back=2)
    else:
        run_daily()

    show_database_summary()
    print("\n✅ Done.")


if __name__ == "__main__":
    main()