"""
ReceiptExtraction schema.

Grounded in the SROIE (ICDAR 2019) dataset — confirmed by inspecting real
sample data (entities/X00016469612.txt) and the official LayoutLM
fine-tuning notebook, which confirms the ground-truth label set is exactly:
    ['COMPANY', 'DATE', 'ADDRESS', 'TOTAL']

Key findings from real data that shaped this schema:
  - date arrives as "DD/MM/YYYY" (e.g. "25/12/2018") — NOT ISO format,
    so it needs an explicit parser, not a naive datetime cast.
  - total arrives as a plain string (e.g. "9.00") — coerced to Decimal
    here, not float, to avoid floating-point rounding on money.
  - Line items (CODE/DESC/QTY/PRICE/AMOUNT) are visible on the physical
    receipt but are NOT part of SROIE's ground truth — confirmed by the
    labels list above. Included here anyway as OPTIONAL, because the
    anomaly rule "line items don't sum to total" needs somewhere to
    attach for receipts, not just invoices.
    Optional because OCR reliably captures header fields but often
    struggles with itemized rows on low-quality receipt scans.
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import DocumentType, FinancialDocument


class ReceiptLineItem(BaseModel):
    """A single itemized line on a receipt. Optional — see module docstring."""

    description: str = Field(..., description="Item description as printed on the receipt.")
    quantity: float | None = Field(default=None, description="Quantity purchased, if legible.")
    unit_price: Decimal | None = Field(default=None, description="Price per unit, if legible.")
    amount: Decimal = Field(..., description="Total amount for this line.")


class ReceiptExtraction(FinancialDocument):
    """
    Extracted structured data for a receipt.

    Required fields mirror SROIE's confirmed ground-truth set
    (company, date, address, total). Everything else is optional,
    since it's not guaranteed by real-world OCR quality.
    """

    document_type: DocumentType = Field(default=DocumentType.RECEIPT, frozen=True)

    merchant_name: str = Field(..., description="Company/merchant name (SROIE: 'company').")
    merchant_address: str | None = Field(
        default=None, description="Merchant address as printed (SROIE: 'address')."
    )
    transaction_date: date_type = Field(
        ..., description="Date of purchase, parsed from source format (SROIE: 'date', DD/MM/YYYY)."
    )
    total: Decimal = Field(..., description="Total amount on the receipt (SROIE: 'total').")

    document_number: str | None = Field(
        default=None, description="Receipt/document number, if printed (e.g. 'Document No')."
    )
    cashier: str | None = Field(default=None, description="Cashier name/ID, if printed.")
    line_items: list[ReceiptLineItem] | None = Field(
        default=None,
        description="Itemized line items, if legible. Not guaranteed — see module docstring.",
    )

    @field_validator("transaction_date", mode="before")
    @classmethod
    def parse_dd_mm_yyyy(cls, value):
        """
        SROIE-style receipts commonly print dates as DD/MM/YYYY (e.g. '25/12/2018').
        Accept that raw string format in addition to already-parsed dates/ISO strings,
        since the Extraction Agent may hand us either depending on LLM output.
        """
        if isinstance(value, str) and "/" in value:
            day, month, year = value.split("/")[:3]
            year = year.split(" ")[0]
            return date_type(int(year), int(month), int(day))
        return value
