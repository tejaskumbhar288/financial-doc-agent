"""Tests for anomaly detection rules."""

from datetime import date, timedelta
from decimal import Decimal

import pytest

from app.agents.anomaly_rules import (
    check_amount_mismatch,
    check_date_anomalies,
    check_duplicate_line_items,
    check_round_number_bias,
)
from app.models.anomaly import AnomalySeverity
from app.schemas.invoice import InvoiceExtraction, InvoiceLineItem
from app.schemas.receipt import ReceiptExtraction

# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def valid_invoice_with_matching_amounts():
    """
    A valid invoice with all amounts perfectly matching.

    Line items:
    - Item 1: 2 × $100 = $200 (net)
    - Item 2: 3 × $50 = $150 (net)
    - Subtotal: $350
    - Tax (10%): $35
    - Total: $385
    """
    return InvoiceExtraction(
        source_filename="invoice_001.pdf",
        confidence_score=0.95,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-001",
        invoice_date=date(2024, 8, 1),
        line_items=[
            InvoiceLineItem(
                description="Widget A",
                quantity=Decimal("2"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("200"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("220"),
            ),
            InvoiceLineItem(
                description="Widget B",
                quantity=Decimal("3"),
                unit_of_measure="each",
                net_price=Decimal("50"),
                net_worth=Decimal("150"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("165"),
            ),
        ],
        subtotal=Decimal("350"),
        tax=Decimal("35"),
        total=Decimal("385"),
    )


@pytest.fixture
def invoice_with_subtotal_mismatch():
    """
    Invoice where line items sum ($350) doesn't match reported subtotal ($400).
    Difference is $50 — way beyond the 0.01 tolerance.
    Also, since subtotal doesn't match, the total should be wrong too.
    """
    return InvoiceExtraction(
        source_filename="invoice_002.pdf",
        confidence_score=0.85,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-002",
        invoice_date=date(2024, 8, 2),
        line_items=[
            InvoiceLineItem(
                description="Widget A",
                quantity=Decimal("2"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("200"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("220"),
            ),
            InvoiceLineItem(
                description="Widget B",
                quantity=Decimal("3"),
                unit_of_measure="each",
                net_price=Decimal("50"),
                net_worth=Decimal("150"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("165"),
            ),
        ],
        subtotal=Decimal("400"),  # WRONG! Should be 350 (line sum is $350)
        tax=Decimal("40"),  # Also adjusted so total calculation is also wrong
        total=Decimal("450"),  # WRONG! Should be 385 (350 + 35)
    )


@pytest.fixture
def invoice_with_total_mismatch():
    """
    Invoice where subtotal + tax doesn't match reported total.
    Subtotal: $350, Tax: $35, Calculated total: $385
    But reported total: $400 (intentional error of $15)
    """
    return InvoiceExtraction(
        source_filename="invoice_003.pdf",
        confidence_score=0.85,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-003",
        invoice_date=date(2024, 8, 3),
        line_items=[
            InvoiceLineItem(
                description="Widget A",
                quantity=Decimal("2"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("200"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("220"),
            ),
            InvoiceLineItem(
                description="Widget B",
                quantity=Decimal("3"),
                unit_of_measure="each",
                net_price=Decimal("50"),
                net_worth=Decimal("150"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("165"),
            ),
        ],
        subtotal=Decimal("350"),
        tax=Decimal("35"),
        total=Decimal("400"),  # WRONG! Should be 385
    )


@pytest.fixture
def invoice_at_rounding_boundary():
    """
    Invoice where difference is exactly at the 0.01 tolerance boundary.
    Line items sum to $350.00, subtotal reported as $350.01.
    Difference = 0.01, which is NOT > 0.01, so should NOT flag.
    """
    return InvoiceExtraction(
        source_filename="invoice_004.pdf",
        confidence_score=0.90,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-004",
        invoice_date=date(2024, 8, 4),
        line_items=[
            InvoiceLineItem(
                description="Widget A",
                quantity=Decimal("2"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("200"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("220"),
            ),
            InvoiceLineItem(
                description="Widget B",
                quantity=Decimal("3"),
                unit_of_measure="each",
                net_price=Decimal("50"),
                net_worth=Decimal("150"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("165"),
            ),
        ],
        subtotal=Decimal("350.01"),  # Exactly 0.01 difference
        tax=Decimal("35"),
        total=Decimal("385.01"),
    )


@pytest.fixture
def invoice_with_missing_line_items():
    """Receipt with no line items (None) — should skip gracefully."""
    return ReceiptExtraction(
        source_filename="receipt_005.jpg",
        confidence_score=0.75,
        merchant_name="Example Corp",
        merchant_address="123 Main St",
        transaction_date=date(2024, 8, 5),
        line_items=None,  # Missing!
        total=Decimal("385"),
    )


# ============================================================================
# Tests
# ============================================================================


def test_amount_mismatch_happy_path(valid_invoice_with_matching_amounts):
    """Valid amounts should not be flagged."""
    result = check_amount_mismatch(valid_invoice_with_matching_amounts)

    assert not result.flagged
    assert result.rule_name == "amount_mismatch"
    assert result.severity is None
    assert result.description is None
    assert result.details is None
    assert result.confidence == 1.0


def test_amount_mismatch_subtotal_mismatch(invoice_with_subtotal_mismatch):
    """Line items sum ($350) doesn't match reported subtotal ($400) — should flag."""
    result = check_amount_mismatch(invoice_with_subtotal_mismatch)

    assert result.flagged
    assert result.rule_name == "amount_mismatch"
    assert result.severity == AnomalySeverity.HIGH
    assert "line items" in result.description.lower()
    assert result.confidence == 1.0
    assert result.details is not None
    assert result.details["subtotal_mismatch"] is True
    assert result.details["total_mismatch"] is True


def test_amount_mismatch_total_mismatch(invoice_with_total_mismatch):
    """Subtotal + tax ($385) doesn't match reported total ($400) — should flag."""
    result = check_amount_mismatch(invoice_with_total_mismatch)

    assert result.flagged
    assert result.rule_name == "amount_mismatch"
    assert result.severity == AnomalySeverity.HIGH
    assert "subtotal + tax" in result.description.lower()
    assert result.confidence == 1.0
    assert result.details is not None
    assert result.details["total_mismatch"] is True


def test_amount_mismatch_at_rounding_boundary(invoice_at_rounding_boundary):
    """Difference of exactly 0.01 should NOT flag (at tolerance boundary)."""
    result = check_amount_mismatch(invoice_at_rounding_boundary)

    # Difference is exactly 0.01, which is NOT > 0.01, so no flag
    assert not result.flagged
    assert result.confidence == 1.0


def test_amount_mismatch_missing_data(invoice_with_missing_line_items):
    """Missing line items should not flag, but confidence is still 1.0 (deterministic skip)."""
    result = check_amount_mismatch(invoice_with_missing_line_items)

    assert not result.flagged
    assert result.rule_name == "amount_mismatch"
    assert result.severity is None
    assert result.description is None
    assert result.details is None
    assert result.confidence == 1.0


# ============================================================================
# Tests for check_round_number_bias
# ============================================================================


@pytest.fixture
def invoice_safe_amount():
    """Invoice well below the suspicious zone."""
    return InvoiceExtraction(
        source_filename="invoice_safe.pdf",
        confidence_score=0.95,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-100",
        invoice_date=date(2024, 8, 1),
        line_items=[
            InvoiceLineItem(
                description="Widget",
                quantity=Decimal("1"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("100"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("110"),
            ),
        ],
        subtotal=Decimal("100"),
        tax=Decimal("10"),
        total=Decimal("110"),
    )


@pytest.fixture
def invoice_in_suspicious_zone():
    """Invoice within 2% below $5000 threshold (suspicious zone)."""
    # $4900 is 2% below $5000 — right in the suspicious zone
    return InvoiceExtraction(
        source_filename="invoice_suspicious.pdf",
        confidence_score=0.90,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-101",
        invoice_date=date(2024, 8, 1),
        line_items=[
            InvoiceLineItem(
                description="Service",
                quantity=Decimal("1"),
                unit_of_measure="each",
                net_price=Decimal("4500"),
                net_worth=Decimal("4500"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("4950"),
            ),
        ],
        subtotal=Decimal("4500"),
        tax=Decimal("450"),
        total=Decimal("4950"),
    )


def test_round_number_bias_safe_amount(invoice_safe_amount):
    """Amount well below threshold should not flag."""
    result = check_round_number_bias(invoice_safe_amount)

    assert not result.flagged
    assert result.confidence == 1.0


def test_round_number_bias_suspicious_zone(invoice_in_suspicious_zone):
    """Amount within 2% below threshold should flag."""
    result = check_round_number_bias(invoice_in_suspicious_zone)

    assert result.flagged
    assert result.rule_name == "round_number_bias"
    assert result.severity == AnomalySeverity.MEDIUM
    assert "structuring" in result.description.lower()
    assert result.confidence == 0.7  # Pattern-based, not definitive
    assert result.details is not None
    assert Decimal(result.details["total"]) == Decimal("4950")


def test_round_number_bias_custom_threshold():
    """Test with a custom approval threshold."""
    invoice = InvoiceExtraction(
        source_filename="invoice_custom.pdf",
        confidence_score=0.90,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-102",
        invoice_date=date(2024, 8, 1),
        line_items=[
            InvoiceLineItem(
                description="Service",
                quantity=Decimal("1"),
                unit_of_measure="each",
                net_price=Decimal("950"),
                net_worth=Decimal("950"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("1045"),
            ),
        ],
        subtotal=Decimal("950"),
        tax=Decimal("95"),
        total=Decimal("1045"),
    )

    # With $1000 threshold, $1045 is above it (no flag)
    result = check_round_number_bias(invoice, approval_threshold=Decimal("1000"))
    assert not result.flagged

    # With $1100 threshold, $1045 is within 2% below ($1078 lower bound)? No, it's 5% below.
    # So it should NOT flag (only flags if within 2% below, not more)
    result = check_round_number_bias(invoice, approval_threshold=Decimal("1100"))
    assert not result.flagged

    # With $1050 threshold, $1045 is within 2% below ($1029 lower bound), so flag
    result = check_round_number_bias(invoice, approval_threshold=Decimal("1050"))
    assert result.flagged


# ============================================================================
# Tests for check_date_anomalies
# ============================================================================


@pytest.fixture
def invoice_normal_date():
    """Invoice with a past weekday date (normal)."""
    # Use yesterday if yesterday was a weekday, else use last weekday
    today = date.today()
    yesterday = today - timedelta(days=1)
    # If yesterday is a weekday (0-4), use it; else go back to last Friday
    if yesterday.weekday() < 5:  # 0-4 are Mon-Fri
        normal_date = yesterday
    else:
        # Yesterday was Sat or Sun, go back to Friday
        normal_date = today - timedelta(days=(today.weekday() - 4) % 7 or 7)

    return InvoiceExtraction(
        source_filename="invoice_normal_date.pdf",
        confidence_score=0.95,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-200",
        invoice_date=normal_date,
        line_items=[
            InvoiceLineItem(
                description="Widget",
                quantity=Decimal("1"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("100"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("110"),
            ),
        ],
        subtotal=Decimal("100"),
        tax=Decimal("10"),
        total=Decimal("110"),
    )


@pytest.fixture
def invoice_future_dated():
    """Invoice dated 5 days in the future."""
    future_date = date.today() + timedelta(days=5)
    return InvoiceExtraction(
        source_filename="invoice_future.pdf",
        confidence_score=0.85,
        vendor_name="Acme Corp",
        vendor_tax_id="12-3456789",
        client_name="Example Inc",
        client_tax_id="98-7654321",
        invoice_number="INV-2024-201",
        invoice_date=future_date,
        line_items=[
            InvoiceLineItem(
                description="Widget",
                quantity=Decimal("1"),
                unit_of_measure="each",
                net_price=Decimal("100"),
                net_worth=Decimal("100"),
                vat_percent=Decimal("10"),
                gross_worth=Decimal("110"),
            ),
        ],
        subtotal=Decimal("100"),
        tax=Decimal("10"),
        total=Decimal("110"),
    )


@pytest.fixture
def receipt_weekend_dated():
    """Receipt dated on a Saturday."""
    # Find next Saturday
    today = date.today()
    days_until_saturday = (5 - today.weekday()) % 7
    if days_until_saturday == 0:
        days_until_saturday = 7
    saturday = today + timedelta(days=days_until_saturday)

    return ReceiptExtraction(
        source_filename="receipt_weekend.jpg",
        confidence_score=0.80,
        merchant_name="Corner Store",
        merchant_address="123 Main St",
        transaction_date=saturday,
        total=Decimal("50"),
    )


def test_date_anomalies_normal(invoice_normal_date):
    """Normal date should not flag."""
    result = check_date_anomalies(invoice_normal_date)

    assert not result.flagged
    assert result.confidence == 1.0


def test_date_anomalies_future_dated(invoice_future_dated):
    """Future-dated invoice should flag."""
    result = check_date_anomalies(invoice_future_dated)

    assert result.flagged
    assert result.rule_name == "date_anomalies"
    assert result.severity == AnomalySeverity.LOW
    assert "future" in result.description.lower()
    assert result.details["is_future_dated"] is True


def test_date_anomalies_weekend(receipt_weekend_dated):
    """Weekend-dated receipt should flag."""
    result = check_date_anomalies(receipt_weekend_dated)

    assert result.flagged
    assert result.rule_name == "date_anomalies"
    assert result.severity == AnomalySeverity.LOW
    assert "saturday" in result.description.lower() or "sunday" in result.description.lower()
    assert result.details["is_weekend"] is True


# ============================================================================
# check_duplicate_line_items
# ============================================================================


def _line(description: str, net_worth: str) -> InvoiceLineItem:
    """Build a line item; only description and net_worth matter to this rule."""
    return InvoiceLineItem(
        description=description,
        quantity=Decimal("1"),
        unit_of_measure="each",
        net_price=Decimal(net_worth),
        net_worth=Decimal(net_worth),
        vat_percent=Decimal("0"),
        gross_worth=Decimal(net_worth),
    )


def _invoice(*line_items: InvoiceLineItem) -> InvoiceExtraction:
    total = sum((item.net_worth for item in line_items), Decimal("0"))
    return InvoiceExtraction(
        source_filename="dupes.pdf",
        confidence_score=0.9,
        vendor_name="Acme Corp",
        client_name="Example Inc",
        invoice_number="INV-DUP-001",
        invoice_date=date(2024, 8, 1),
        line_items=list(line_items),
        subtotal=total,
        tax=Decimal("0"),
        total=total,
    )


def test_flags_an_exact_duplicate_line():
    invoice = _invoice(
        _line("Consulting fee", "1200"),
        _line("Consulting fee", "1200"),
        _line("Travel", "300"),
    )

    result = check_duplicate_line_items(invoice)

    assert result.flagged is True
    assert result.severity == AnomalySeverity.HIGH
    assert "consulting fee" in result.description


def test_duplicate_detection_ignores_casing_and_padding():
    invoice = _invoice(_line("Consulting Fee", "1200"), _line("  consulting fee ", "1200"))

    assert check_duplicate_line_items(invoice).flagged is True


def test_same_description_at_a_different_price_is_not_a_duplicate():
    """Two site visits at different rates are legitimate, not double billing."""
    invoice = _invoice(_line("Site visit", "500"), _line("Site visit", "750"))

    assert check_duplicate_line_items(invoice).flagged is False


def test_a_clean_invoice_is_not_flagged():
    invoice = _invoice(_line("Widget A", "200"), _line("Widget B", "150"))

    result = check_duplicate_line_items(invoice)

    assert result.flagged is False
    assert result.severity is None


def test_shipping_repeats_are_ignored_by_default():
    invoice = _invoice(_line("Shipping", "50"), _line("Shipping", "50"))

    assert check_duplicate_line_items(invoice).flagged is False
