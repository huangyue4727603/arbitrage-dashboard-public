from datetime import datetime
from sqlalchemy import String, Integer, Float, Boolean, Text, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from typing import Optional

from app.database import Base


class PostInvestmentMonitor(Base):
    __tablename__ = "arb_post_investment_monitors"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("arb_users.id"), nullable=False, index=True)
    coin_name: Mapped[str] = mapped_column(String(50), nullable=False)
    long_exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    short_exchange: Mapped[str] = mapped_column(String(50), nullable=False)
    spread_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oi_drop_1h_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    oi_drop_4h_threshold: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lark_bot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arb_lark_bots.id", ondelete="SET NULL"), nullable=True
    )
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    # Relationships
    user = relationship("User", back_populates="post_investment_monitors")
    lark_bot = relationship("LarkBot")


class BasisAlertConfig(Base):
    __tablename__ = "arb_basis_alert_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("arb_users.id"), nullable=False, unique=True, index=True
    )
    basis_threshold: Mapped[float] = mapped_column(Float, nullable=False, default=-1.0)
    expand_multiplier: Mapped[float] = mapped_column(Float, nullable=False, default=1.1)
    clear_interval_hours: Mapped[int] = mapped_column(Integer, nullable=False, default=4)
    blocked_coins: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lark_bot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arb_lark_bots.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    # Relationships
    user = relationship("User", back_populates="basis_alert_config")
    lark_bot = relationship("LarkBot")


class NewListingAlertConfig(Base):
    __tablename__ = "arb_new_listing_alert_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("arb_users.id"), nullable=False, unique=True, index=True
    )
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lark_bot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arb_lark_bots.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    # Relationships
    user = relationship("User", back_populates="new_listing_alert_config")
    lark_bot = relationship("LarkBot")


class FundingBreakAlertConfig(Base):
    __tablename__ = "arb_funding_break_alert_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("arb_users.id"), nullable=False, unique=True, index=True
    )
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lark_bot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arb_lark_bots.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    user = relationship("User", back_populates="funding_break_alert_config")
    lark_bot = relationship("LarkBot")


class UnhedgedAlertConfig(Base):
    __tablename__ = "arb_unhedged_alert_configs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("arb_users.id"), nullable=False, unique=True, index=True
    )
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    lark_bot_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("arb_lark_bots.id", ondelete="SET NULL"), nullable=True
    )

    # Relationships
    user = relationship("User", back_populates="unhedged_alert_config")
    lark_bot = relationship("LarkBot")
