"""
Guard Agent tests -- TDD with known-answer PII fixtures, per Architecture
doc Section 4's testing row ("especially the Guard agent").

We embed KNOWN values into a raw text blob (simulating extracted document
text) and assert the Guard Agent actually redacts them. This is the same
"known-answer PII" approach the architecture doc calls out for
generate_synthetic_statement.py -- except here it's inline, since we need
control over exact values to test the checksum edge cases.
"""

from app.agents.guard import is_valid_aba_checksum, redact_text

# Known-good real-format values.
# REAL_CREDIT_CARD uses Stripe's well-known public test card number --
# Luhn-valid (so Presidio's CREDIT_CARD recognizer treats it like a real
# PAN) but a recognized "known fake" pattern, so SAST/secret scanners
# don't flag it as a possible live card number the way an arbitrary
# Luhn-valid string would.
REAL_CREDIT_CARD = "4242424242424242"
REAL_ABA_ROUTING = "021000021"  # real Chase routing number, passes checksum
FAKE_9_DIGITS = "123456789"  # 9 digits, fails ABA checksum -- should NOT be flagged as routing
PERSON_NAME = "Sarah Chen"


def test_aba_checksum_accepts_real_routing_number():
    assert is_valid_aba_checksum(REAL_ABA_ROUTING) is True


def test_aba_checksum_rejects_arbitrary_9_digits():
    assert is_valid_aba_checksum(FAKE_9_DIGITS) is False


def test_redacts_credit_card_number():
    text = f"Card on file: {REAL_CREDIT_CARD}"
    result = redact_text(text)
    assert REAL_CREDIT_CARD not in result.redacted_text
    assert any(f.entity_type == "CREDIT_CARD" for f in result.findings)


def test_redacts_valid_aba_routing_number():
    text = f"My routing number is {REAL_ABA_ROUTING} for the wire transfer."
    result = redact_text(text)
    assert REAL_ABA_ROUTING not in result.redacted_text
    assert any(f.entity_type == "US_ABA_ROUTING_NUMBER" for f in result.findings)


def test_does_not_flag_arbitrary_9_digit_number_as_routing():
    text = f"Reference code: {FAKE_9_DIGITS}"
    result = redact_text(text)
    # Should survive untouched -- fails the ABA checksum, so it's not a
    # plausible routing number (this is the exact false-positive case
    # the checksum validator exists to prevent).
    assert FAKE_9_DIGITS in result.redacted_text
    assert not any(f.entity_type == "US_ABA_ROUTING_NUMBER" for f in result.findings)


def test_keeps_person_names_visible():
    text = f"Account holder: {PERSON_NAME}"
    result = redact_text(text)
    # Deliberate design decision -- see guard.py module docstring.
    assert PERSON_NAME in result.redacted_text


def test_masks_long_values_completely_not_just_first_12_chars():
    """
    Regression test: an earlier version used a fixed chars_to_mask=12,
    which only masked the first 12 characters -- fine for a 16-digit
    card, but left most of a long IBAN exposed. This confirms masking
    now scales with length instead of a fixed count.
    """
    # A standard example IBAN used in banking documentation -- real
    # checksum-valid format, not a live account. Needs to be a genuinely
    # valid IBAN, not just IBAN-shaped, or Presidio's IBAN_CODE
    # recognizer (checksum-validated, like our ABA recognizer) won't
    # flag it at all -- confirmed while writing this test.
    long_iban = "GB33BUKB20201555555555"  # 22 chars
    text = f"IBAN: {long_iban}"
    result = redact_text(text)

    assert long_iban not in result.redacted_text
    # Only the last 4 characters should ever survive, regardless of length.
    assert long_iban[-4:] in result.redacted_text
    assert long_iban[:-4] not in result.redacted_text


def test_findings_never_contain_raw_pii():
    """
    Regression test: GuardFinding used to store the raw original_span,
    which meant an audit-log object literally contained the unredacted
    PAN/SSN/routing number -- defeating the point of redaction the
    moment those findings got logged or persisted. Confirms findings
    only ever carry a masked preview now.
    """
    text = f"Card on file: {REAL_CREDIT_CARD}"
    result = redact_text(text)

    for finding in result.findings:
        assert REAL_CREDIT_CARD not in finding.masked_preview
        assert "*" in finding.masked_preview


def test_combined_statement_like_text():
    """
    A more realistic blob resembling actual extracted statement text --
    multiple PII types in one document, some that should be redacted and
    one (the name) that shouldn't.
    """
    text = (
        f"Account Holder: {PERSON_NAME}\n"
        f"Routing Number: {REAL_ABA_ROUTING}\n"
        f"Card ending in: {REAL_CREDIT_CARD}\n"
        f"Statement Period: 01/01/2024 - 01/31/2024"
    )
    result = redact_text(text)

    assert PERSON_NAME in result.redacted_text
    assert REAL_ABA_ROUTING not in result.redacted_text
    assert REAL_CREDIT_CARD not in result.redacted_text

    entity_types_found = {f.entity_type for f in result.findings}
    assert "US_ABA_ROUTING_NUMBER" in entity_types_found
    assert "CREDIT_CARD" in entity_types_found