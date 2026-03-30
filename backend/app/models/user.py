from datetime import datetime
from sqlalchemy import String, Boolean, DateTime, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class User(Base):
    __tablename__ = "arb_users"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, nullable=False, index=True)
    password_hash: Mapped[str] = mapped_column(String(128), nullable=False)
    theme: Mapped[str] = mapped_column(String(10), nullable=False, default="light")
    sound_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    popup_enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False,
        server_default=text("CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP"),
    )

    # Relationships
    lark_bots = relationship("LarkBot", back_populates="user", cascade="all, delete-orphan")
    post_investment_monitors = relationship(
        "PostInvestmentMonitor", back_populates="user", cascade="all, delete-orphan"
    )
    basis_alert_config = relationship(
        "BasisAlertConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    unhedged_alert_config = relationship(
        "UnhedgedAlertConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    new_listing_alert_config = relationship(
        "NewListingAlertConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
    funding_break_alert_config = relationship(
        "FundingBreakAlertConfig", back_populates="user", uselist=False, cascade="all, delete-orphan"
    )
