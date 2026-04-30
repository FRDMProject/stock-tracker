"""
api.py
FastAPI web service that serves stock data from the database.
"""

import os
from typing import Optional
from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import or_
from sqlalchemy.orm import Session

from database import SessionLocal, Asset, DailyBar, Holding, init_db

load_dotenv()

# Create the FastAPI app
app = FastAPI(
    title="Stock Tracker API",
    description="A simple API for fetching stored stock price data.",
    version="0.1.0",
)

STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")


@app.on_event("startup")
def on_startup():
    """Initialize database tables on app startup."""
    init_db()


def get_db():
    """Dependency: provides a database session for each request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# -----------------------------
# Endpoints
# -----------------------------

@app.get("/api/health")
def health():
    """Health check — confirms the API is running."""
    return {
        "status": "ok",
        "message": "Stock Tracker API is running",
        "docs": "/docs",
    }


@app.get("/account")
def get_account():
    """Return a snapshot of the configured Alpaca paper account."""
    api_key = os.getenv("ALPACA_API_KEY")
    secret_key = os.getenv("ALPACA_SECRET_KEY")
    if not api_key or not secret_key or api_key in ("x", "fake"):
        raise HTTPException(
            status_code=503,
            detail="Alpaca credentials not configured. Set ALPACA_API_KEY and ALPACA_SECRET_KEY.",
        )

    # Imported lazily so the app can boot without alpaca installed in dev
    from alpaca.trading.client import TradingClient

    try:
        client = TradingClient(api_key, secret_key, paper=True)
        account = client.get_account()
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Alpaca error: {e}")

    def to_float(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    return {
        "buying_power": to_float(account.buying_power),
        "cash": to_float(account.cash),
        "portfolio_value": to_float(account.portfolio_value),
        "equity": to_float(account.equity),
        "currency": getattr(account, "currency", "USD"),
        "status": str(account.status) if account.status else None,
        "paper": True,
    }


@app.get("/portfolio")
def get_portfolio():
    """Return the user's holdings with current price and market value."""
    db = SessionLocal()
    try:
        holdings = db.query(Holding).all()
        items = []
        total_value = 0.0
        total_basis = 0.0
        for h in holdings:
            latest = (
                db.query(DailyBar)
                .filter(DailyBar.symbol == h.symbol)
                .order_by(DailyBar.timestamp.desc())
                .first()
            )
            asset = db.query(Asset).filter(Asset.symbol == h.symbol).first()
            price = float(latest.close) if latest else None
            value = price * h.shares if price is not None else None
            if value is not None:
                total_value += value
            total_basis += h.cost_basis

            items.append(
                {
                    "symbol": h.symbol,
                    "name": asset.name if asset else None,
                    "shares": h.shares,
                    "cost_basis": h.cost_basis,
                    "price": price,
                    "market_value": value,
                    "gain_loss": (value - h.cost_basis) if value is not None else None,
                    "gain_loss_pct": (
                        ((value - h.cost_basis) / h.cost_basis * 100)
                        if value is not None and h.cost_basis
                        else None
                    ),
                }
            )

        items.sort(key=lambda x: x["symbol"])
        return {
            "count": len(items),
            "total_cost_basis": total_basis,
            "total_market_value": total_value,
            "total_gain_loss": total_value - total_basis if items else 0.0,
            "holdings": items,
        }
    finally:
        db.close()


@app.get("/search")
def search_assets(
    q: str = Query(..., min_length=1, max_length=64, description="Symbol or company name"),
    limit: int = Query(10, ge=1, le=50),
):
    """Search the universe by ticker symbol or company name."""
    query = q.strip()
    if not query:
        return {"results": []}

    db = SessionLocal()
    try:
        like = f"%{query}%"
        starts = f"{query.upper()}%"
        rows = (
            db.query(Asset)
            .filter(Asset.tradable == True)
            .filter(or_(Asset.symbol.ilike(like), Asset.name.ilike(like)))
            .limit(limit * 4)
            .all()
        )

        # Rank: exact symbol > symbol prefix > anything else, then alpha
        q_upper = query.upper()

        def score(a: Asset) -> tuple:
            sym = (a.symbol or "").upper()
            name = (a.name or "")
            if sym == q_upper:
                rank = 0
            elif sym.startswith(q_upper):
                rank = 1
            elif name.lower().startswith(query.lower()):
                rank = 2
            else:
                rank = 3
            return (rank, sym)

        rows.sort(key=score)
        results = [
            {
                "symbol": a.symbol,
                "name": a.name,
                "exchange": a.exchange,
            }
            for a in rows[:limit]
        ]
        return {"query": query, "results": results}
    finally:
        db.close()


@app.get("/stocks")
def list_all_stocks(
    limit: int = Query(100, ge=1, le=1000, description="Max rows to return"),
):
    """Return all stored bars across all symbols, newest first."""
    db = SessionLocal()
    try:
        bars = (
            db.query(DailyBar)
            .order_by(DailyBar.timestamp.desc())
            .limit(limit)
            .all()
        )
        return {
            "count": len(bars),
            "bars": [bar_to_dict(bar) for bar in bars],
        }
    finally:
        db.close()


@app.get("/stocks/symbols")
def list_symbols():
    """Return the unique list of symbols stored in the database."""
    db = SessionLocal()
    try:
        symbols = (
            db.query(DailyBar.symbol)
            .distinct()
            .order_by(DailyBar.symbol)
            .all()
        )
        return {"symbols": [s[0] for s in symbols]}
    finally:
        db.close()


@app.get("/stocks/{symbol}")
def get_stock(
    symbol: str,
    limit: int = Query(30, ge=1, le=2000, description="Number of days to return"),
):
    """Return bars for a given symbol, newest first."""
    symbol = symbol.upper()
    db = SessionLocal()
    try:
        bars = (
            db.query(DailyBar)
            .filter(DailyBar.symbol == symbol)
            .order_by(DailyBar.timestamp.desc())
            .limit(limit)
            .all()
        )
        if not bars:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for symbol '{symbol}'",
            )
        return {
            "symbol": symbol,
            "count": len(bars),
            "bars": [bar_to_dict(bar) for bar in bars],
        }
    finally:
        db.close()


@app.get("/stocks/{symbol}/info")
def get_stock_info(symbol: str):
    """Return asset metadata (name, exchange, asset class) for a symbol."""
    symbol = symbol.upper()
    db = SessionLocal()
    try:
        asset = db.query(Asset).filter(Asset.symbol == symbol).first()
        if not asset:
            raise HTTPException(
                status_code=404,
                detail=f"No asset record found for symbol '{symbol}'",
            )
        return {
            "symbol": asset.symbol,
            "name": asset.name,
            "exchange": asset.exchange,
            "asset_class": asset.asset_class,
            "tradable": asset.tradable,
            "status": asset.status,
        }
    finally:
        db.close()


@app.get("/stocks/{symbol}/latest")
def get_latest(symbol: str):
    """Return only the most recent bar for a given symbol."""
    symbol = symbol.upper()
    db = SessionLocal()
    try:
        bar = (
            db.query(DailyBar)
            .filter(DailyBar.symbol == symbol)
            .order_by(DailyBar.timestamp.desc())
            .first()
        )
        if not bar:
            raise HTTPException(
                status_code=404,
                detail=f"No data found for symbol '{symbol}'",
            )
        return bar_to_dict(bar)
    finally:
        db.close()


# -----------------------------
# Helpers
# -----------------------------

def bar_to_dict(bar: DailyBar) -> dict:
    """Convert a DailyBar database row into a clean JSON-friendly dict."""
    return {
        "symbol": bar.symbol,
        "date": bar.timestamp.date().isoformat(),
        "open": bar.open,
        "high": bar.high,
        "low": bar.low,
        "close": bar.close,
        "volume": bar.volume,
    }


# -----------------------------
# Frontend (static files)
# -----------------------------

if os.path.isdir(STATIC_DIR):
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/")
    def index():
        return FileResponse(os.path.join(STATIC_DIR, "index.html"))