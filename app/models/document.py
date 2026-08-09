"""ExtractedDocument model — normalized storage of extraction results."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import JSON, ForeignKey, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base
from app.schemas.base import DocumentType, ProcessingStatus

if TYPE_CHECKING:
    from app.models.anomaly import AnomalyFlag  # noqa: F401
    from app.models.vendor import Vendor  # noqa: F401


class ExtractedDocument(Base):
    """
    Represents a document that has been parsed, guarded, and extracted.

    Stores the full extraction output (Pydantic-validated) plus metadata
    (confidence, status, audit timestamps). Linked to a Vendor for anomaly
    detection rules that need cross-document history.
    """

    __tablename__ = "extracted_documents"

    document_id: Mapped[str] = mapped_column(String(64), primary_key=True)
    """
    Unique identifier, typically a content hash (SHA256 of raw text).
    Ensures dedup (Section 2).
    """

    source_filename: Mapped[str] = mapped_column(String(255))
    """Original filename as uploaded."""

    document_type: Mapped[DocumentType] = mapped_column()
    """Type of document: RECEIPT, INVOICE, or STATEMENT."""

    vendor_name: Mapped[str | None] = mapped_column(
        String(255), ForeignKey("vendors.vendor_name"), default=None
    )
    """
    Name of the vendor (for receipts/invoices) or account holder
    (for statements). Nullable for safety, but expected to be populated
    for anomaly detection to work. Foreign key to vendors table.
    """

    extracted_data: Mapped[dict] = mapped_column(JSON)
    """
    Full extraction output as JSON (the Pydantic model serialized).
    Preserves all fields: company/date/total/line_items etc.
    """

    confidence_score: Mapped[Decimal] = mapped_column(Numeric(3, 2), default=Decimal("0.0"))
    """
    Extraction confidence (0.0–1.0), computed deterministically from
    observable signals: attempts used, arithmetic checks, missing fields,
    parse route (Section 7/9). Not self-reported by the LLM.
    """

    status: Mapped[ProcessingStatus] = mapped_column(default=ProcessingStatus.PROCESSED)
    """
    Current processing state: PROCESSED, NEEDS_REVIEW, QUARANTINED, or
    UNRECONCILED. Set by orchestrator based on guard/extraction/anomaly
    results.
    """

    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    """Timestamp when document was first ingested."""

    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())
    """Timestamp of last status update (anomaly detection, reconciliation, etc.)."""

    # Relationship to vendor (many documents belong to one vendor)
    vendor: Mapped[Vendor] = relationship(back_populates="documents")

    # Relationship to anomalies (one document can have many flagged anomalies)
    anomalies: Mapped[list[AnomalyFlag]] = relationship(back_populates="document")

    def __repr__(self) -> str:
        return (
            f"<ExtractedDocument(document_id='{self.document_id}', "
            f"vendor_name='{self.vendor_name}', type={self.document_type})>"
        )
