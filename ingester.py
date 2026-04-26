"""
ingester.py
Connects to Alpaca, fetches stock data, and saves it to the database.
"""

import os
from datetime import datetime, timedelta
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.data.historical import StockHistoricalDataClient
from alpaca.data.requests import StockBarsRequest
from alpaca.data.timeframe import TimeFrame

from database import SessionLocal, DailyBar, init_db

# Load credentials from .env
load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise ValueError("Missing Alpaca credentials. Check your .env file.")

# Stocks we want to track
SYMBOLS = ["AAPL", "TSLA", "MSFT", "NVDA", "GOOGL"]


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


def fetch_and_store_bars(data_client, symbols, days_back=30):
    """Fetch daily bars and save them to the database."""
    print("=" * 60)
    print(f"FETCHING + STORING LAST {days_back} DAYS OF DAILY BARS")
    print("=" * 60)

    end = datetime.now() - timedelta(minutes=20)  # account for 15-min delay
    start = end - timedelta(days=days_back)

    request = StockBarsRequest(
        symbol_or_symbols=symbols,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
    )
    bars = data_client.get_stock_bars(request)

    # Open a database session
    session = SessionLocal()
    inserted = 0
    skipped = 0

    try:
        for symbol in symbols:
            symbol_bars = bars.data.get(symbol, [])
            for bar in symbol_bars:
                # Check if this row already exists (avoid duplicates)
                existing = (
                    session.query(DailyBar)
                    .filter_by(symbol=symbol, timestamp=bar.timestamp)
                    .first()
                )
                if existing:
                    skipped += 1
                    continue

                # Create a new database row
                row = DailyBar(
                    symbol=symbol,
                    timestamp=bar.timestamp,
                    open=bar.open,
                    high=bar.high,
                    low=bar.low,
                    close=bar.close,
                    volume=bar.volume,
                )
                session.add(row)
                inserted += 1

        # Commit all the new rows at once
        session.commit()
        print(f"✅ Inserted: {inserted}  |  Skipped (already exists): {skipped}")
    except Exception as e:
        session.rollback()
        print(f"❌ Error saving to database: {e}")
        raise
    finally:
        session.close()


def show_database_summary():
    """Print a summary of what's currently in the database."""
    print()
    print("=" * 60)
    print("DATABASE SUMMARY")
    print("=" * 60)

    session = SessionLocal()
    try:
        total = session.query(DailyBar).count()
        print(f"Total rows in database: {total}")
        print()

        for symbol in SYMBOLS:
            count = session.query(DailyBar).filter_by(symbol=symbol).count()
            latest = (
                session.query(DailyBar)
                .filter_by(symbol=symbol)
                .order_by(DailyBar.timestamp.desc())
                .first()
            )
            if latest:
                print(
                    f"{symbol:6} | {count:3} bars | "
                    f"latest: {latest.timestamp.date()} close=${latest.close:.2f}"
                )
            else:
                print(f"{symbol:6} |   0 bars | (no data)")
    finally:
        session.close()


def main():
    # Make sure the database/tables exist
    init_db()
    print()

    check_account()

    data_client = StockHistoricalDataClient(API_KEY, SECRET_KEY)
    fetch_and_store_bars(data_client, SYMBOLS, days_back=30)

    show_database_summary()

    print()
    print("✅ Done.")


if __name__ == "__main__":
    main()