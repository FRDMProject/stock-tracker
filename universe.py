"""
universe.py
Fetches the list of tradeable US stocks from Alpaca and stores them in the database.

A "universe" is the set of all securities we want to track. This module builds it.
"""

import os
from dotenv import load_dotenv
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import GetAssetsRequest
from alpaca.trading.enums import AssetClass, AssetStatus

from database import SessionLocal, Asset, init_db

load_dotenv()
API_KEY = os.getenv("ALPACA_API_KEY")
SECRET_KEY = os.getenv("ALPACA_SECRET_KEY")

if not API_KEY or not SECRET_KEY:
    raise ValueError("Missing Alpaca credentials. Check your .env file.")


def fetch_and_store_universe(only_us_equities: bool = True) -> int:
    """
    Fetch the full list of tradeable assets from Alpaca and save them to the database.
    Returns the number of assets stored.
    """
    print("=" * 60)
    print("BUILDING UNIVERSE OF TRADEABLE ASSETS")
    print("=" * 60)

    trading_client = TradingClient(API_KEY, SECRET_KEY, paper=True)

    # Request all active, tradeable US equities
    request = GetAssetsRequest(
        status=AssetStatus.ACTIVE,
        asset_class=AssetClass.US_EQUITY if only_us_equities else None,
    )
    print("Fetching asset list from Alpaca...")
    assets = trading_client.get_all_assets(request)
    print(f"Alpaca returned {len(assets):,} assets")

    # Filter to only tradeable ones (Alpaca returns some that exist but can't be traded)
    tradeable_assets = [a for a in assets if a.tradable]
    print(f"After filtering to tradeable: {len(tradeable_assets):,}")

    # Save to database, in batches to keep memory and transactions reasonable
    session = SessionLocal()
    inserted = 0
    updated = 0
    BATCH_SIZE = 500

    try:
        for i in range(0, len(tradeable_assets), BATCH_SIZE):
            batch = tradeable_assets[i : i + BATCH_SIZE]
            for a in batch:
                existing = session.query(Asset).filter_by(symbol=a.symbol).first()
                if existing:
                    existing.name = a.name
                    existing.exchange = str(a.exchange) if a.exchange else None
                    existing.asset_class = str(a.asset_class) if a.asset_class else None
                    existing.tradable = a.tradable
                    existing.status = str(a.status) if a.status else None
                    updated += 1
                else:
                    session.add(
                        Asset(
                            symbol=a.symbol,
                            name=a.name,
                            exchange=str(a.exchange) if a.exchange else None,
                            asset_class=str(a.asset_class) if a.asset_class else None,
                            tradable=a.tradable,
                            status=str(a.status) if a.status else None,
                        )
                    )
                    inserted += 1
            session.commit()
            print(f"  Processed {min(i + BATCH_SIZE, len(tradeable_assets)):,} / {len(tradeable_assets):,}")

        print(f"\n✅ Universe updated. Inserted: {inserted:,}  |  Updated: {updated:,}")
        return inserted + updated
    except Exception as e:
        session.rollback()
        print(f"❌ Error: {e}")
        raise
    finally:
        session.close()


def get_active_symbols(limit: int = None) -> list[str]:
    """Return the list of active, tradeable symbols from the database."""
    session = SessionLocal()
    try:
        query = session.query(Asset.symbol).filter(Asset.tradable == True)
        if limit:
            query = query.limit(limit)
        return [row[0] for row in query.all()]
    finally:
        session.close()


def main():
    init_db()
    fetch_and_store_universe(only_us_equities=True)

    # Quick summary
    symbols = get_active_symbols()
    print(f"\nTotal tradeable symbols in database: {len(symbols):,}")
    print(f"First 10: {symbols[:10]}")


if __name__ == "__main__":
    main()