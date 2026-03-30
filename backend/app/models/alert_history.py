from datetime import datetime
from sqlalchemy import String, Integer, Float, DateTime, ForeignKey, text
from sqlalchemy.orm import Mapped, mapped_column
from typing import Optional

from app.database import Base


class BasisAlertRecord(Base):
    __tablename__ = "arb_basis_alert_records"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("arb_users.id"), nullable=False, index=True)
    coin_name: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    last_basis: Mapped[float] = mapped_column(Float, nullable=False)
    alert_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    first_alert_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    last_alert_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
    cleared_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)


class BasisAlertHistory(Base):
    __tablename__ = "arb_basis_alert_history"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("arb_users.id"), nullable=False, index=True)
    coin_name: Mapped[str] = mapped_column(String(50), nullable=False)
    alert_type: Mapped[str] = mapped_column(String(20), nullable=False)  # "new" or "expand"
    basis_value: Mapped[float] = mapped_column(Float, nullable=False)
    alert_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP")
    )
