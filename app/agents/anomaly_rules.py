"""Anomaly detection rules — deterministic checks for financial anomalies."""

from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from enum import StrEnum

from app.models.anomaly import AnomalySeverity
from app.schemas.invoice import InvoiceExtraction
from app.schemas.receipt import ReceiptExtraction


@dataclass
class AnomalyResult:
    """Result of running a single anomaly detection rule."""
    
    rule_name: str
    """Name of the rule that ran (e.g., 'amount_mismatch')."""
    
    flagged: bool
    """Whether this rule detected an anomaly."""
    
    severity: AnomalySeverity | None
    """Severity level (CRITICAL/HIGH/MEDIUM/LOW) if flagged, None if not."""
    
    description: str | None
    """Human-readable explanation if flagged, None otherwise."""
    
    details: dict | None
    """Rule-specific details as a dict (e.g., {line_sum: 100, reported_total: 120})."""
    
    confidence: float
    """Confidence in this result (0.0-1.0). 1.0 = deterministic, 0.5 = borderline."""


def check_amount_mismatch(extraction: InvoiceExtraction | ReceiptExtraction) -> AnomalyResult:
    """
    Check if line items sum matches the reported totals.

    For invoices: flags if line_items sum ≠ subtotal OR subtotal + tax ≠ total
    For receipts: flags if line_items sum ≠ total
    Tolerance: ±0.01 for rounding
    """
    if extraction.line_items is None or extraction.total is None:
        return AnomalyResult(
            rule_name="amount_mismatch",
            flagged=False,
            severity=None,
            description=None,
            details=None,
            confidence=1.0,
        )

    # Use net_worth (pre-tax line subtotal) for invoices, or generic amount field for receipts
    line_sum = sum(
        getattr(item, "net_worth", None) or getattr(item, "amount", Decimal("0"))
        for item in extraction.line_items
    )

    # Determine schema type and check accordingly
    subtotal_mismatch = False
    total_mismatch = False
    subtotal = getattr(extraction, "subtotal", None)
    tax = getattr(extraction, "tax", None)

    if subtotal is not None:
        # Invoice-style: line items should match subtotal (pre-tax)
        subtotal_mismatch = abs(line_sum - subtotal) > Decimal("0.01")
        # And subtotal + tax should match total
        tax_amt = tax or Decimal("0.00")
        total_mismatch = abs((subtotal + tax_amt) - extraction.total) > Decimal("0.01")
    else:
        # Receipt-style: line items should match total directly
        total_mismatch = abs(line_sum - extraction.total) > Decimal("0.01")

    if subtotal_mismatch or total_mismatch:
        mismatch_type = []
        if subtotal_mismatch:
            mismatch_type.append(f"line items (${line_sum}) ≠ subtotal (${subtotal})")
        if total_mismatch:
            if subtotal is not None:
                tax_amt = tax or Decimal("0.00")
                calculated_total = subtotal + tax_amt
                mismatch_type.append(f"subtotal + tax (${calculated_total}) ≠ total (${extraction.total})")
            else:
                mismatch_type.append(f"line items (${line_sum}) ≠ total (${extraction.total})")

        return AnomalyResult(
            rule_name="amount_mismatch",
            flagged=True,
            severity=AnomalySeverity.HIGH,
            description=f"Amount mismatch: {'; '.join(mismatch_type)}",
            details={
                "line_sum": str(line_sum),
                "reported_subtotal": str(subtotal) if subtotal else None,
                "reported_total": str(extraction.total),
                "tax": str(tax or Decimal("0.00")) if tax else None,
                "subtotal_mismatch": subtotal_mismatch,
                "total_mismatch": total_mismatch,
            },
            confidence=1.0,
        )

    return AnomalyResult(
        rule_name="amount_mismatch",
        flagged=False,
        severity=None,
        description=None,
        details=None,
        confidence=1.0,
    )


def check_round_number_bias(
    extraction: InvoiceExtraction | ReceiptExtraction,
    approval_threshold: Decimal = Decimal("5000"),
) -> AnomalyResult:
    """
    Check for round-number bias / invoice structuring fraud.

    Flags if the invoice total is within 2% below an approval threshold —
    the pattern of intentionally splitting invoices to stay under limits.

    Args:
        extraction: Invoice or receipt extraction
        approval_threshold: Amount threshold to check against (default: $5000)

    Returns:
        AnomalyResult flagging if the pattern is detected
    """
    if extraction.total is None:
        return AnomalyResult(
            rule_name="round_number_bias",
            flagged=False,
            severity=None,
            description=None,
            details=None,
            confidence=1.0,
        )

    # Calculate the "suspicious zone": within 2% below threshold
    tolerance_pct = Decimal("0.02")  # 2%
    lower_bound = approval_threshold * (Decimal("1") - tolerance_pct)

    # Flag if amount is in the suspicious zone (between lower_bound and threshold)
    if lower_bound < extraction.total < approval_threshold:
        pct_below = (
            (approval_threshold - extraction.total) / approval_threshold * 100
        ).quantize(Decimal("0.01"))

        return AnomalyResult(
            rule_name="round_number_bias",
            flagged=True,
            severity=AnomalySeverity.MEDIUM,
            description=(
                f"Potential invoice structuring: ${extraction.total} is "
                f"{pct_below}% below the ${approval_threshold} threshold"
            ),
            details={
                "total": str(extraction.total),
                "approval_threshold": str(approval_threshold),
                "percent_below_threshold": str(pct_below),
                "lower_bound": str(lower_bound),
            },
            confidence=0.7,  # Pattern-based, not definitive
        )

    return AnomalyResult(
        rule_name="round_number_bias",
        flagged=False,
        severity=None,
        description=None,
        details=None,
        confidence=1.0,
    )


def check_date_anomalies(
    extraction: InvoiceExtraction | ReceiptExtraction,
) -> AnomalyResult:
    """
    Check for date anomalies: future-dated or weekend invoices.

    Flags if:
    - Invoice date is in the future (OCR/entry error or backdating)
    - Invoice date is on a weekend (unusual for business transactions)

    Returns:
        AnomalyResult with severity LOW (informational, unlikely actionable)
    """
    # Get the invoice date from whichever schema field is present
    invoice_date = None
    if isinstance(extraction, InvoiceExtraction):
        invoice_date = extraction.invoice_date
    elif isinstance(extraction, ReceiptExtraction):
        invoice_date = extraction.transaction_date

    if invoice_date is None:
        return AnomalyResult(
            rule_name="date_anomalies",
            flagged=False,
            severity=None,
            description=None,
            details=None,
            confidence=1.0,
        )

    today = date.today()
    anomalies = []

    # Check if future-dated
    if invoice_date > today:
        days_in_future = (invoice_date - today).days
        anomalies.append(f"future-dated by {days_in_future} days")

    # Check if weekend (5 = Saturday, 6 = Sunday in Python's weekday())
    if invoice_date.weekday() >= 5:
        day_name = invoice_date.strftime("%A")
        anomalies.append(f"dated on a {day_name}")

    if anomalies:
        return AnomalyResult(
            rule_name="date_anomalies",
            flagged=True,
            severity=AnomalySeverity.LOW,
            description=f"Date anomaly: {', '.join(anomalies)}",
            details={
                "invoice_date": str(invoice_date),
                "today": str(today),
                "weekday": invoice_date.strftime("%A"),
                "is_future_dated": invoice_date > today,
                "is_weekend": invoice_date.weekday() >= 5,
            },
            confidence=1.0,
        )

    return AnomalyResult(
        rule_name="date_anomalies",
        flagged=False,
        severity=None,
        description=None,
        details=None,
        confidence=1.0,
    )
