"""
Base schema shared by all financial document types.

Every extracted document (invoice, statement, receipt) inherits from
FinancialDocument. This is the contract boundary between the Extraction
Agent and everything downstream (Anomaly Detection, Reconciliation,
Postgres persistence).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class DocumentType(str, Enum):
    INVOICE = "invoice"
    STATEMENT = "statement"
    RECEIPT = "receipt"


class ProcessingStatus(str, Enum):
    """Mirrors the status enum from Section 9 of the architecture doc."""
    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    UNRECONCILED = "unreconciled"


class FinancialDocument(BaseModel):
    """
    Base fields common to every document type.

    Subclasses (InvoiceExtraction, StatementExtraction, ReceiptExtraction)
    add their own document-specific fields on top of this.
    """

    document_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="System-generated unique ID for this document.",
    )
    document_type: DocumentType = Field(
        ...,
        description="Which schema this document was extracted as.",
    )
    source_filename: str = Field(
        ...,
        description="Original uploaded filename, for traceability back to the raw file.",
    )
    upload_date: datetime = Field(
        default_factory=datetime.utcnow,
        description="When the document was ingested into the system.",
    )
    confidence_score: float = Field(
        ...,
        ge=0.0,
        le=1.0,
        description="Extraction Agent's self-reported confidence for this document, 0.0-1.0.",
    )
    status: ProcessingStatus = Field(
        default=ProcessingStatus.PROCESSED,
        description="Processing outcome — set by the retry/human-review policy (Section 9).",
    )

    model_config = {
        "use_enum_values": True,
    }
