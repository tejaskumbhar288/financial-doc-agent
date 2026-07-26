"""
Orchestrator (LangGraph) tests.

Guard/injection-detection correctness is already covered by test_guard.py,
test_guard_agent.py, and the injection test files. Extraction correctness
is untested anywhere yet (extract_receipt.py has been manual-only since
Checkpoint 3 — no automated coverage exists to duplicate here either).

The one genuinely NEW thing orchestrator.py adds is the routing decision:
does a flagged document actually get quarantined without ever reaching
Extraction, and does a clean document actually reach it? That's what these
two tests check — both mock run_guard/extract_receipt_with_retry so this
suite runs without a live Ollama instance, same reasoning as
test_guard_agent.py mocking scan_for_injection.
"""

from datetime import date
from decimal import Decimal
from unittest.mock import patch

from app.agents.guard import GuardResult
from app.agents.guard_agent import GuardAgentResult
from app.agents.injection_scan import InjectionScanResult
from app.orchestrator import build_graph
from app.schemas.base import ProcessingStatus
from app.schemas.receipt import ReceiptExtraction

INITIAL_STATE = {
    "source_filename": "test.jpg",
    "raw_text": "irrelevant — run_guard is mocked",
    "guard_result": None,
    "extraction_result": None,
    "status": None,
}


def test_flagged_document_quarantined_without_reaching_extraction():
    flagged_guard_result = GuardAgentResult(
        redaction_result=GuardResult(redacted_text="[REDACTED]", findings=[]),
        injection_scan_result=InjectionScanResult(
            flagged=True, detection_layer="heuristic", reasoning="matched pattern"
        ),
    )

    with (
        patch("app.orchestrator.run_guard", return_value=flagged_guard_result),
        patch("app.orchestrator.extract_receipt_with_retry") as mock_extract,
    ):
        result = build_graph().invoke(INITIAL_STATE)

    assert result["status"] == ProcessingStatus.QUARANTINED
    assert result["extraction_result"] is None
    mock_extract.assert_not_called()


def test_clean_document_reaches_extraction():
    clean_guard_result = GuardAgentResult(
        redaction_result=GuardResult(redacted_text="clean receipt text", findings=[]),
        injection_scan_result=InjectionScanResult(
            flagged=False, detection_layer="none", reasoning=""
        ),
    )
    extracted = ReceiptExtraction(
        source_filename="test.jpg",
        confidence_score=0.9,
        merchant_name="Test Merchant",
        transaction_date=date(2018, 12, 25),
        total=Decimal("9.00"),
    )

    with (
        patch("app.orchestrator.run_guard", return_value=clean_guard_result),
        patch(
            "app.orchestrator.extract_receipt_with_retry",
            return_value=(extracted, ProcessingStatus.PROCESSED),
        ) as mock_extract,
    ):
        result = build_graph().invoke(INITIAL_STATE)

    assert result["status"] == ProcessingStatus.PROCESSED
    assert result["extraction_result"] == extracted
    mock_extract.assert_called_once_with(
        receipt_text="clean receipt text", source_filename="test.jpg"
    )
