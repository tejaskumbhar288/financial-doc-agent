"""AnomalyFlag model — audit trail of detected anomalies."""

from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class AnomalySeverity(StrEnum):
    """Severity levels for flagged anomalies."""

    CRITICAL = "critical"
    """Immediate action required (e.g., duplicate invoice, BEC account mismatch)."""

    HIGH = "high"
    """Significant risk, needs review (e.g., z-score >3σ, round-number structuring)."""

    MEDIUM = "medium"
    """Potential issue, worth noting (e.g., future-dated invoice, minor mismatch)."""

    LOW = "low"
    """Informational, unlikely to be actionable (e.g., weekend-dated receipt)."""


class AnomalyFlag(Base):
    """
    Represents an anomaly detected by a rule on a specific document.

    Part of the audit trail (Section 6/9) — every flag is logged with
    the detecting rule, severity, reasoning, and timestamp. Used by the
    review queue to surface high-confidence/high-severity cases.
    """

    __tablename__ = "anomaly_flags"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    """Auto-incrementing primary key."""

    document_id: Mapped[str] = mapped_column(
        String(64), ForeignKey("extracted_documents.document_id")
    )
    """Document this anomaly was detected on."""

    rule_name: Mapped[str] = mapped_column(String(64))
    """
    Name of the rule that detected this. Examples:
    - "amount_mismatch"
    - "duplicate_invoice"
    - "z_score_outlier"
    - "vendor_account_mismatch"
    - "round_number_bias"
    - "date_anomaly"
    """

    severity: Mapped[AnomalySeverity] = mapped_column()
    """How urgent this is: CRITICAL / HIGH / MEDIUM / LOW."""

    description: Mapped[str] = mapped_column(String(512))
    """Human-readable summary of the anomaly."""

    details: Mapped[dict] = mapped_column(JSON, default=dict)
    """
    Rule-specific details as JSON. Examples:
    - amount_mismatch: {line_items_sum: 100.00, reported_total: 120.00}
    - z_score_outlier: {amount: 50000, mean: 5000, stddev: 1000, z_score: 4.5}
    - vendor_account_mismatch: {new_fingerprint: "****1234", prior_fingerprints: [...]}
    """

    created_at: Mapped[datetime] = mapped_column(
        server_default=func.now()
    )
    """Timestamp when anomaly was detected."""

    # Relationship to document
    document: Mapped["ExtractedDocument"] = relationship(
        back_populates="anomalies"
    )

    def __repr__(self) -> str:
        return (
            f"<AnomalyFlag(document_id='{self.document_id}', "
            f"rule_name='{self.rule_name}', severity={self.severity})>"
        )
