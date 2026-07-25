"""
Guard Agent (combined entry point) tests.

Redaction correctness is already covered by test_guard.py; injection-
detection correctness is already covered by test_injection_heuristic.py /
test_injection_llm_judge.py. The only NEW behavior guard_agent.py adds is
the ordering rule: scan_for_injection() must run on the redacted text, not
the raw text. That's the one thing worth testing here.
"""

from unittest.mock import patch

from app.agents.guard_agent import run_guard
from app.agents.injection_scan import InjectionScanResult

REAL_ABA_ROUTING = "021000021"  # real Chase routing number, passes checksum


def test_injection_scan_receives_redacted_text_not_raw():
    raw_text = f"Account holder: Sarah Chen. Routing number: {REAL_ABA_ROUTING}."

    with patch("app.agents.guard_agent.scan_for_injection") as mock_scan:
        mock_scan.return_value = InjectionScanResult(
            flagged=False, detection_layer="none", reasoning=""
        )
        run_guard(raw_text)

    scanned_text = mock_scan.call_args[0][0]
    assert REAL_ABA_ROUTING not in scanned_text
    assert scanned_text != raw_text
