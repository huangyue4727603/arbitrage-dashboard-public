from datetime import datetime
from decimal import Decimal
from sqlalchemy import String, Integer, BigInteger, Float, Boolean, DateTime, JSON, Index, UniqueConstraint, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.database import Base


class FundingCap(Base):
    __tablename__ = "arb_funding_caps"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    funding_cap: Mapped[float] = mapped_column(Float, nullable=False)
    funding_floor: Mapped[float] = mapped_column(Float, nullable=False)
    interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=8)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_funding_caps_exchange_symbol"),
    )


class NewListing(Base):
    __tablename__ = "arb_new_listings"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    coin_name: Mapped[str] = mapped_column(String(50), nullable=False)
    listing_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    listing_days: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    current_funding_rate: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    settlement_period: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=8)
    price_change: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    raw_data: Mapped[Optional[dict]] = mapped_column(JSON, nullable=True)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("exchange", "symbol", name="uq_new_listings_exchange_symbol"),
    )


class OISnapshot(Base):
    __tablename__ = "arb_oi_snapshots"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, nullable=False)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    current_oi: Mapped[float] = mapped_column(Float, nullable=False)
    max_oi_1h: Mapped[float] = mapped_column(Float, nullable=False)
    max_oi_4h: Mapped[float] = mapped_column(Float, nullable=False)
    max_oi_1h_reset_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    max_oi_4h_reset_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("user_id", "symbol", name="uq_oi_snapshots_user_symbol"),
    )


class PriceKline(Base):
    __tablename__ = "arb_price_klines"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    symbol: Mapped[str] = mapped_column(String(50), nullable=False)
    interval_type: Mapped[str] = mapped_column(String(10), nullable=False)
    open_price: Mapped[float] = mapped_column(Float, nullable=False)
    close_price: Mapped[float] = mapped_column(Float, nullable=False)
    high_price: Mapped[float] = mapped_column(Float, nullable=False)
    low_price: Mapped[float] = mapped_column(Float, nullable=False)
    kline_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("symbol", "interval_type", "kline_time", name="uq_price_klines_symbol_interval_time"),
    )


class PriceTrend(Base):
    __tablename__ = "arb_price_trends"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    coin_name: Mapped[str] = mapped_column(String(50), nullable=False)
    daily: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    h4: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    h1: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    m15: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_score: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    __table_args__ = (
        UniqueConstraint("coin_name", name="uq_price_trends_coin_name"),
    )


class FundingHistory(Base):
    __tablename__ = "arb_funding_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)
    coin: Mapped[str] = mapped_column(String(50), nullable=False)
    funding_rate: Mapped[float] = mapped_column(Float, nullable=False)
    funding_time: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("exchange", "coin", "funding_time", name="uq_funding_history"),
        Index("ix_funding_history_exchange_coin", "exchange", "coin"),
        Index("ix_funding_history_time", "funding_time"),
    )


class IndexConstituent(Base):
    """One row per (coin, derivative_exchange, spot_exchange) — the actual
    weight a spot exchange contributes to the index price for a coin's
    perpetual contract on a given derivatives exchange.

    Example: BTC perp on Binance uses Coinbase BTC-USD with weight 0.25 →
        coin=BTC, exchange=BN, spot_exchange=Coinbase, spot_symbol=BTC-USD, weight=0.25
    """
    __tablename__ = "arb_index_constituents"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    coin: Mapped[str] = mapped_column(String(50), nullable=False)
    exchange: Mapped[str] = mapped_column(String(10), nullable=False)  # BN / OKX / BY
    spot_exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    spot_symbol: Mapped[str] = mapped_column(String(50), nullable=False, default="")
    weight: Mapped[float] = mapped_column(Float, nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        default=datetime.now,
        onupdate=datetime.now,
    )

    __table_args__ = (
        UniqueConstraint("coin", "exchange", "spot_exchange", name="uq_index_constituents_coin_ex_spot"),
        Index("ix_index_constituents_coin", "coin"),
        Index("ix_index_constituents_coin_ex", "coin", "exchange"),
    )


class MarketHistory(Base):
    """Snapshot rows from /api/v1/arbitrage/chance/histories — one row per
    (coin, exchange, instrument) per ms tick. Retained for 3 days.
    """
    __tablename__ = "arb_market_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    seq_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    exchange: Mapped[str] = mapped_column(String(20), nullable=False)
    coin: Mapped[str] = mapped_column(String(50), nullable=False)
    symbol: Mapped[str] = mapped_column(String(80), nullable=False)
    inst_id: Mapped[str] = mapped_column(String(80), nullable=False)
    inst_type: Mapped[str] = mapped_column(String(20), nullable=False)
    price: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 10), nullable=True)
    funding_rate: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10), nullable=True)
    premium: Mapped[Optional[Decimal]] = mapped_column(Numeric(20, 10), nullable=True)
    open_interest: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 8), nullable=True)
    funding_interval: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    base_vol24h: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 8), nullable=True)
    quote_vol24h: Mapped[Optional[Decimal]] = mapped_column(Numeric(28, 8), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False)

    __table_args__ = (
        UniqueConstraint("seq_id", "inst_id", name="uq_market_history_seq_inst"),
        Index("ix_market_history_created_at", "created_at"),
        Index("ix_market_history_coin_created", "coin", "created_at"),
        Index("ix_market_history_inst_created", "inst_id", "created_at"),
        Index("ix_market_history_seq", "seq_id"),
    )
