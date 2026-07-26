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
    """
    Outcome of running a document through the pipeline.

    QUARANTINED is deliberately distinct from NEEDS_REVIEW: it means the
    Guard Agent detected a prompt-injection attempt, so the document was
    refused outright and never processed. NEEDS_REVIEW means we DID
    process it and couldn't get a trustworthy result. Anyone triaging the
    review queue needs to tell those two apart -- "we refused to touch
    this" and "we tried and failed" call for different handling.

    UNRECONCILED is narrower: extraction succeeded, but the document
    couldn't be matched against its counterpart (invoice <-> statement
    transaction) even after widening the match window.
    """

    PROCESSED = "processed"
    NEEDS_REVIEW = "needs_review"
    QUARANTINED = "quarantined"
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
        description=(
            "Extraction confidence, 0.0-1.0. COMPUTED by our own code from "
            "observable signals (how many attempts extraction needed, whether "
            "the arithmetic self-check passed, how many optional fields came "
            "back empty, whether the source was a native PDF text layer or "
            "OCR). Never self-reported by the LLM -- a model's stated "
            "confidence is a generated token sequence, not a calibrated "
            "probability, and correlates with how confident the input text "
            "sounds rather than with correctness."
        ),
    )
    status: ProcessingStatus = Field(
        default=ProcessingStatus.PROCESSED,
        description="Processing outcome — set by the retry/human-review policy.",
    )

    model_config = {
        "use_enum_values": True,
    }
