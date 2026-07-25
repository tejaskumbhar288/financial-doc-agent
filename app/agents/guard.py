"""
Guard Agent — PII/PCI redaction (Architecture doc Section 2 & 6).

Runs BEFORE any document text reaches an LLM (Section 2, step 2). Detects
and redacts:
  - Credit card numbers (PAN)   -> Presidio built-in CREDIT_CARD
  - Bank account numbers         -> Presidio built-in US_BANK_NUMBER
  - ABA routing numbers          -> custom recognizer (Presidio has none
                                     built-in -- confirmed via manual
                                     testing, see PROGRESS.md Checkpoint 4)
  - SSN / Tax ID                 -> Presidio built-in US_SSN
  - IBAN                         -> Presidio built-in IBAN_CODE

Deliberately NOT redacted:
  - PERSON (names). Not in Architecture doc Section 6's redaction list
    (that list is scoped to data that alone enables impersonation/fraud:
    account numbers, routing numbers, PANs, SSN/Tax ID, full addresses --
    a name alone doesn't). Also a hard functional requirement: schemas
    like StatementExtraction.account_holder_name are required fields the
    Extraction Agent must populate downstream. Redacting names would
    break extraction, not improve security. See PROGRESS.md Checkpoint 4
    for the full reasoning.

Design boundary: this module only works on raw TEXT, never on parsed
Pydantic schemas -- it runs upstream of Extraction, on the raw document
text pulled from the uploaded file. Guard doesn't know what Extraction
does with the redacted text afterward (least-privilege data flow,
Section 2).
"""

from __future__ import annotations

from dataclasses import dataclass

from presidio_analyzer import AnalyzerEngine, Pattern, PatternRecognizer
from presidio_anonymizer import AnonymizerEngine
from presidio_anonymizer.entities import OperatorConfig

# Filters out low-confidence noise -- e.g. US_PASSPORT/US_DRIVER_LICENSE
# showing up at 0.01-0.05 on numbers that are actually something else
# entirely (confirmed via manual exploration before this module existed).
SCORE_THRESHOLD = 0.4

REDACT_ENTITIES = [
    "CREDIT_CARD",
    "US_BANK_NUMBER",
    "US_SSN",
    "IBAN_CODE",
    "US_ABA_ROUTING_NUMBER",
]


def is_valid_aba_checksum(routing_number: str) -> bool:
    """
    ABA routing number checksum: 3*(d1+d4+d7) + 7*(d2+d5+d8) + (d3+d6+d9)
    must be divisible by 10. This is what separates a real routing number
    from an arbitrary 9-digit string (invoice number, reference code,
    etc.) -- the regex alone can't do that distinction.
    """
    if len(routing_number) != 9 or not routing_number.isdigit():
        return False
    d = [int(c) for c in routing_number]
    checksum = (
        3 * (d[0] + d[3] + d[6])
        + 7 * (d[1] + d[4] + d[7])
        + 1 * (d[2] + d[5] + d[8])
    )
    return checksum % 10 == 0


class ABARoutingRecognizer(PatternRecognizer):
    """
    Detects US ABA bank routing numbers as their own entity type, so they
    don't collide with PHONE_NUMBER or get silently missed (both observed
    happening with Presidio's built-in recognizers alone).
    """

    PATTERNS = [
        Pattern(name="aba_routing_9digit", regex=r"\b\d{9}\b", score=0.3),
    ]

    def __init__(self):
        super().__init__(
            supported_entity="US_ABA_ROUTING_NUMBER",
            patterns=self.PATTERNS,
            context=["routing", "aba", "bank", "transit"],
        )

    def validate_result(self, pattern_text: str):
        """
        NOTE: must return True/False explicitly, never rely on Python
        truthy shortcuts like `x or None` -- `False or None` evaluates to
        None in Python, which Presidio reads as "no opinion" (keep
        original low score) rather than "reject." That bug was caught
        during manual testing before this module existed; every non-
        routing 9-digit number would otherwise have leaked through at a
        nonzero confidence score.
        """
        return True if is_valid_aba_checksum(pattern_text) else False


def _build_analyzer() -> AnalyzerEngine:
    analyzer = AnalyzerEngine()
    analyzer.registry.add_recognizer(ABARoutingRecognizer())
    return analyzer


_analyzer = _build_analyzer()
_anonymizer = AnonymizerEngine()

# All redacted entities get the same partial-mask treatment: mask
# everything except the last few characters. This matches what
# StatementExtraction already expects (account_number_redacted like
# "****1234") -- see app/schemas/statement.py.
_OPERATORS = {
    entity: OperatorConfig(
        "mask", {"masking_char": "*", "chars_to_mask": 12, "from_end": False}
    )
    for entity in REDACT_ENTITIES
}


@dataclass
class GuardFinding:
    """One redaction decision -- feeds the audit trail (Section 6)."""

    entity_type: str
    score: float
    original_span: str


@dataclass
class GuardResult:
    redacted_text: str
    findings: list[GuardFinding]


def redact_text(text: str) -> GuardResult:
    """
    Detects and redacts PII/PCI in raw text before it reaches any LLM.

    Returns both the redacted text and a findings list. The findings list
    is what the audit trail requirement (Section 6) needs -- every Guard
    Agent decision should be loggable with what was found and how
    confident the detector was, not just silently applied.
    """
    results = [
        r
        for r in _analyzer.analyze(text=text, language="en", entities=REDACT_ENTITIES)
        if r.score >= SCORE_THRESHOLD
    ]

    findings = [
        GuardFinding(
            entity_type=r.entity_type,
            score=r.score,
            original_span=text[r.start : r.end],
        )
        for r in results
    ]

    anonymized = _anonymizer.anonymize(
        text=text, analyzer_results=results, operators=_OPERATORS
    )

    return GuardResult(redacted_text=anonymized.text, findings=findings)