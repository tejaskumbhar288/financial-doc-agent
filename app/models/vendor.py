"""Vendor model — tracks vendor history for anomaly detection."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

if TYPE_CHECKING:
    from app.models.document import ExtractedDocument  # noqa: F401


class Vendor(Base):
    """
    Represents a vendor with historical data for anomaly detection.

    Used by anomaly rules that need vendor history:
    - Duplicate detection (same vendor + amount + date window)
    - Z-score outlier detection (mean/stddev of vendor's invoice amounts)
    - Vendor/account mismatch (known banking fingerprints for this vendor)
    """

    __tablename__ = "vendors"

    vendor_name: Mapped[str] = mapped_column(String(255), primary_key=True)
    """Unique vendor name/identifier."""

    banking_fingerprints: Mapped[list[str]] = mapped_column(JSON, default=list)
    """
    List of HMAC-masked banking identifiers (IBANs, routing numbers, etc.)
    seen for this vendor. Supports BEC/wire-fraud detection: a new document
    with a banking fingerprint not in this list gets flagged as a potential
    account takeover.
    """

    z_score_mean: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    """
    Mean invoice amount for this vendor. Computed once ≥30 invoices exist
    (per Section 7 sample-size minimum). None if insufficient history.
    """

    z_score_stddev: Mapped[Decimal | None] = mapped_column(Numeric(12, 2), default=None)
    """
    Standard deviation of invoice amounts for this vendor. None if
    insufficient history (< 30 invoices).
    """

    invoice_count: Mapped[int] = mapped_column(default=0)
    """Total number of invoices seen for this vendor."""

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    """Timestamp when vendor record was first created."""

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    """Timestamp of last update (z-score recalculation, new fingerprint, etc.)."""

    # Relationship to documents (one vendor has many documents)
    documents: Mapped[list[ExtractedDocument]] = relationship(back_populates="vendor")

    def __repr__(self) -> str:
        return f"<Vendor(vendor_name='{self.vendor_name}', invoice_count={self.invoice_count})>"
