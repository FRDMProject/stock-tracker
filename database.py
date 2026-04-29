"""
database.py
Defines the database connection and tables.
"""

import os
from datetime import datetime
from sqlalchemy import (
    create_engine,
    Column,
    Integer,
    String,
    Float,
    DateTime,
    BigInteger,
    Boolean,
    UniqueConstraint,
)
from sqlalchemy.orm import declarative_base, sessionmaker

# SQLite database file lives in the project folder
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///stocks.db")

# Railway/Heroku use "postgres://" but SQLAlchemy needs "postgresql://"
if DATABASE_URL.startswith("postgres://"):
    DATABASE_URL = DATABASE_URL.replace("postgres://", "postgresql://", 1)

# The "engine" is the connection to the database
engine = create_engine(DATABASE_URL, echo=False)

# Sessions are how we read/write data
SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)

# Base class for our table definitions
Base = declarative_base()

class Asset(Base):
    """One row = one tradeable security (e.g., AAPL, MSFT)."""

    __tablename__ = "assets"

    symbol = Column(String, primary_key=True)
    name = Column(String, nullable=True)
    exchange = Column(String, nullable=True)
    asset_class = Column(String, nullable=True)
    tradable = Column(Boolean, default=True)
    status = Column(String, nullable=True)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<Asset {self.symbol} ({self.exchange})>"
class DailyBar(Base):
    """One row = one day of price data for one stock."""

    __tablename__ = "daily_bars"

    id = Column(Integer, primary_key=True, autoincrement=True)
    symbol = Column(String, nullable=False, index=True)
    timestamp = Column(DateTime, nullable=False, index=True)
    open = Column(Float, nullable=False)
    high = Column(Float, nullable=False)
    low = Column(Float, nullable=False)
    close = Column(Float, nullable=False)
    volume = Column(BigInteger, nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    # Prevent duplicate rows for the same symbol+date
    __table_args__ = (
        UniqueConstraint("symbol", "timestamp", name="uq_symbol_timestamp"),
    )

    def __repr__(self):
        return f"<DailyBar {self.symbol} {self.timestamp.date()} close=${self.close}>"


def init_db():
    """Create all tables. Safe to call multiple times — it skips existing tables."""
    Base.metadata.create_all(bind=engine)
    print("✅ Database initialized (stocks.db)")


if __name__ == "__main__":
    # Running this file directly creates the database
    init_db()