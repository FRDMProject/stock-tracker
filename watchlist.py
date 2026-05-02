"""
watchlist.py
Defines the scoped set of symbols we track bars for:
  - S&P 500 + Nasdaq 100 (constituents, fetched from Wikipedia)
  - Major index ETFs (SPY, QQQ, DIA, IWM) — used as benchmarks and as the
    frontend's default landing chart

Sourced live from Wikipedia at first call, then cached in-process.
"""

from io import StringIO
import pandas as pd
import requests

SP500_URL = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
NDX_URL = "https://en.wikipedia.org/wiki/Nasdaq-100"

# Major index ETFs — always include even though they aren't in either index.
# SPY = S&P 500, QQQ = Nasdaq 100, DIA = Dow Jones, IWM = Russell 2000.
EXTRA_TICKERS = ["SPY", "QQQ", "DIA", "IWM"]

# Wikipedia 403s the default urllib User-Agent that pd.read_html uses.
USER_AGENT = "stock-tracker/0.1 (educational project)"

_cache: list[str] | None = None


def _fetch_html(url: str) -> str:
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=30)
    resp.raise_for_status()
    return resp.text


def _fetch_sp500() -> list[str]:
    tables = pd.read_html(StringIO(_fetch_html(SP500_URL)))
    df = tables[0]
    return df["Symbol"].astype(str).str.strip().tolist()


def _fetch_nasdaq100() -> list[str]:
    tables = pd.read_html(StringIO(_fetch_html(NDX_URL)))
    for df in tables:
        cols = {str(c).lower(): c for c in df.columns}
        col = cols.get("ticker") or cols.get("symbol")
        if col is not None:
            return df[col].astype(str).str.strip().tolist()
    raise RuntimeError("Could not find ticker column on Nasdaq-100 page")


def _normalize(sym: str) -> str:
    # Wikipedia sometimes uses "BRK.B" vs Alpaca's "BRK.B" — same convention, so just upper+strip.
    return sym.upper().strip()


def get_watchlist_symbols(force_refresh: bool = False) -> list[str]:
    """Return the deduped, sorted list of watchlist tickers."""
    global _cache
    if _cache is not None and not force_refresh:
        return _cache

    sp500 = {_normalize(s) for s in _fetch_sp500()}
    ndx = {_normalize(s) for s in _fetch_nasdaq100()}
    extras = {_normalize(s) for s in EXTRA_TICKERS}
    combined = sorted(sp500 | ndx | extras)
    _cache = combined
    return combined


if __name__ == "__main__":
    syms = get_watchlist_symbols()
    print(f"Watchlist size: {len(syms)}")
    print(f"First 20: {syms[:20]}")
