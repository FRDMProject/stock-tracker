"""
api.py
FastAPI web service that serves stock data from the database.
"""

from typing import Optional
from fastapi import FastAPI, HTTPException, Query
from sqlalchemy.orm import Session

from database import SessionLocal, DailyBar, init_db

# Create the FastAPI app
app = FastAPI(
    title="Stock Tracker API",
    description="A simple API for fetching stored stock price data.",
    version="0.1.0",
)

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

@app.get("/")
def root():
    """Root endpoint — confirms the API is running."""
    return {
        "status": "ok",
        "message": "Stock Tracker API is running",
        "docs": "/docs",
    }


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
    limit: int = Query(30, ge=1, le=365, description="Number of days to return"),
):
    """Return all bars for a given symbol, newest first."""
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