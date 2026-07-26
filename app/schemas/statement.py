"""
StatementExtraction schema.

Unlike InvoiceExtraction/ReceiptExtraction, this is NOT grounded in a Kaggle
dataset — real bank/credit card statement data is too PII-sensitive to find
good public datasets for. Structure here is designed from general knowledge
of statement formats, then validated against synthetic Faker-generated data
(see app/data/generate_synthetic_statement.py).

Key design decision: account_number and routing_number are modeled as
ALREADY-REDACTED/MASKED strings (e.g. "****1234"), not raw PII. This
reflects the actual pipeline order — the Guard Agent runs BEFORE
extraction, so the Extraction Agent (and this schema) never sees real
account/routing numbers in the first place. That's the least-privilege
data flow principle showing up directly in schema design: a schema that
cannot hold raw PII can't leak it, regardless of what callers do.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field

from app.schemas.base import DocumentType, FinancialDocument


class TransactionType(str, Enum):
    DEBIT = "debit"
    CREDIT = "credit"


class StatementTransaction(BaseModel):
    """A single transaction line within a statement."""

    transaction_date: date_type = Field(..., description="Date the transaction posted.")
    description: str = Field(..., description="Merchant/payee description as printed.")
    amount: Decimal = Field(..., description="Transaction amount, always positive.")
    transaction_type: TransactionType = Field(
        ..., description="Whether this transaction debited or credited the account."
    )
    running_balance: Decimal | None = Field(
        default=None, description="Account balance after this transaction, if printed."
    )


class StatementExtraction(FinancialDocument):
    """
    Extracted structured data for a bank/credit card statement.

    account_number / routing_number are modeled as already-redacted —
    see module docstring for why.
    """

    document_type: DocumentType = Field(default=DocumentType.STATEMENT, frozen=True)

    account_holder_name: str = Field(..., description="Name on the account.")
    bank_name: str = Field(..., description="Issuing bank/institution name.")
    account_number_redacted: str = Field(
        ...,
        description=(
            "Masked account number as it arrives post-Guard-Agent redaction "
            "(e.g. '****1234'). Never the raw PAN/account number."
        ),
    )
    routing_number_redacted: str | None = Field(
        default=None,
        description="Masked ABA routing number, if present and applicable (post-redaction).",
    )

    statement_period_start: date_type = Field(..., description="Start of the statement period.")
    statement_period_end: date_type = Field(..., description="End of the statement period.")

    opening_balance: Decimal = Field(..., description="Balance at the start of the period.")
    closing_balance: Decimal = Field(..., description="Balance at the end of the period.")

    transactions: list[StatementTransaction] = Field(
        default_factory=list,
        description="All transactions within the statement period.",
    )
