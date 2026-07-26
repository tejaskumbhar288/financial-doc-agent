"""
InvoiceExtraction schema.

Grounded in the "High-Quality Invoice Images for OCR" Kaggle dataset —
confirmed via a public notebook's OCR + ground-truth output, not just the
raw images. Real sample OCR text showed a genuine line-item table with
this structure:

    No. Description   Qty  UM   Net price  Net worth  VAT[%]  Gross worth
    1.  Kids Jordan 7  5,00 each 72,00      360,00     10%     396,00

And header-level fields confirmed from ground-truth extraction work already
done on this dataset:
    Seller Name, Seller Tax ID, Client Name, Client Tax ID,
    Invoice Number, Invoice Date, Net Worth, VAT, Gross Worth

Key findings from real data that shaped this schema:
  - Numbers use European decimal format ("72,00" = 72.00), unlike SROIE's
    receipts. Needs comma->period normalization before Decimal parsing.
  - Dates in this dataset are MM/DD/YYYY (US-style) — the OPPOSITE
    convention from SROIE's DD/MM/YYYY receipts. Confirms date format
    can't be assumed consistent across document types/vendors; the
    Extraction Agent's retry loop is the real defense here, not a single
    hardcoded parser.
  - IBAN observed on the seller block in raw OCR text. Added as an
    optional field specifically to support the "vendor/account mismatch"
    anomaly rule — without it, that rule has nothing to compare against
    for invoices.
  - Line items are NOT optional here (unlike ReceiptExtraction) — every
    real sample had a populated items table, and it's core to invoice
    semantics (net/VAT/gross math depends on it).
"""

from __future__ import annotations

from datetime import date as date_type
from decimal import Decimal

from pydantic import BaseModel, Field, field_validator

from app.schemas.base import DocumentType, FinancialDocument


def _normalize_decimal(value):
    """
    Handle European-style decimal numbers (comma as decimal separator,
    e.g. "72,00") alongside standard period-decimal strings and raw
    numbers. Confirmed necessary from real dataset sample OCR text.
    """
    if isinstance(value, str):
        cleaned = value.strip().replace("%", "")
        if "," in cleaned and "." not in cleaned:
            cleaned = cleaned.replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
        return Decimal(cleaned)
    return value


class InvoiceLineItem(BaseModel):
    """
    A single line item on an invoice. Required (not optional) on
    InvoiceExtraction — real sample data confirmed every invoice has
    a populated items table, and net/VAT/gross math depends on it.
    """

    description: str = Field(..., description="Item/service description.")
    quantity: Decimal = Field(..., description="Quantity (e.g. '5,00' in source -> 5.00).")
    unit_of_measure: str | None = Field(
        default=None, description="Unit of measure, e.g. 'each' (source: 'UM')."
    )
    net_price: Decimal = Field(..., description="Unit price before tax (source: 'Net price').")
    net_worth: Decimal = Field(..., description="Line subtotal before tax (source: 'Net worth').")
    vat_percent: Decimal = Field(
        ..., description="VAT/tax rate as a percentage, e.g. 10.00 for 10%."
    )
    gross_worth: Decimal = Field(..., description="Line total after tax (source: 'Gross worth').")

    @field_validator(
        "quantity", "net_price", "net_worth", "vat_percent", "gross_worth", mode="before"
    )
    @classmethod
    def normalize_numbers(cls, value):
        return _normalize_decimal(value)


class InvoiceExtraction(FinancialDocument):
    """
    Extracted structured data for an invoice.

    Header fields mirror the confirmed real-world field set (Seller/Client
    name+tax ID, invoice number/date, Net/VAT/Gross totals). Line items
    are required, unlike ReceiptExtraction.
    """

    document_type: DocumentType = Field(default=DocumentType.INVOICE, frozen=True)

    vendor_name: str = Field(..., description="Seller/issuer name (source: 'Seller Name').")
    vendor_tax_id: str | None = Field(
        default=None, description="Seller's tax/VAT ID (source: 'Seller Tax ID')."
    )
    vendor_iban: str | None = Field(
        default=None,
        description=(
            "Seller's bank IBAN, if present. Optional — added specifically to support "
            "the 'vendor/account mismatch' anomaly rule, which needs prior banking "
            "info to compare against for BEC/wire fraud detection."
        ),
    )
    client_name: str = Field(..., description="Buyer/recipient name (source: 'Client Name').")
    client_tax_id: str | None = Field(
        default=None, description="Buyer's tax/VAT ID (source: 'Client Tax ID')."
    )

    invoice_number: str = Field(..., description="Invoice identifier (source: 'Invoice Number').")
    invoice_date: date_type = Field(..., description="Date of issue (source: 'Invoice Date').")
    due_date: date_type | None = Field(
        default=None, description="Payment due date, if present on the source document."
    )

    line_items: list[InvoiceLineItem] = Field(
        ..., description="Itemized invoice lines. Required — see module docstring.", min_length=1
    )

    subtotal: Decimal = Field(..., description="Pre-tax total (source: 'Net Worth').")
    tax: Decimal = Field(..., description="Total tax/VAT amount (source: 'VAT').")
    total: Decimal = Field(..., description="Final amount due (source: 'Gross Worth').")

    @field_validator("subtotal", "tax", "total", mode="before")
    @classmethod
    def normalize_totals(cls, value):
        return _normalize_decimal(value)

    @field_validator("invoice_date", "due_date", mode="before")
    @classmethod
    def parse_mm_dd_yyyy(cls, value):
        """
        This dataset's invoices use MM/DD/YYYY (US-style) — confirmed from
        real sample OCR text (e.g. "11/24/2014"). Note this is the OPPOSITE
        convention from SROIE's receipts (DD/MM/YYYY) — date format is not
        safe to assume consistent across document types.
        """
        if isinstance(value, str) and "/" in value:
            month, day, year = value.split("/")[:3]
            year = year.split(" ")[0]
            return date_type(int(year), int(month), int(day))
        return value
