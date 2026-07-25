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

# Known-good real-format values
REAL_CREDIT_CARD = "4532015112830366"  # passes Luhn
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