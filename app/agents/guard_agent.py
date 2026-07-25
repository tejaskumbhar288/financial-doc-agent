from dataclasses import dataclass
from app.agents.guard import GuardResult, redact_text
from app.agents.injection_scan import InjectionScanResult, scan_for_injection


@dataclass
class GuardAgentResult:
    """
    The result of running the Guard Agent on a document.

    This is the main output object for Guard Agent usage. It contains
    both the redacted text and the injection scan result.
    """

    guard_result: GuardResult
    injection_scan_result: InjectionScanResult


def run_guard(text: str) -> GuardAgentResult:
    """
    Runs the Guard Agent on the text, returning a GuardAgentResult with
    redacted text and findings. This is the main entry point for
    Guard Agent usage.
    """
    guard_result = redact_text(text)
    injection_scan_result = scan_for_injection(guard_result.redacted_text)
    return GuardAgentResult(
        guard_result=guard_result,
        injection_scan_result=injection_scan_result
    )