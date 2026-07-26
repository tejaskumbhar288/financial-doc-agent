"""
Guard Agent -- prompt-injection scan. The second Guard Agent
responsibility, alongside PII/PCI redaction in guard.py.

Hybrid two-layer detector:
  1. Heuristic pre-filter (injection_heuristic.py) -- cheap, deterministic.
     If it flags something, we trust it and skip the LLM call entirely --
     no need to pay for a model call to confirm what a regex already
     caught with high confidence.
  2. LLM-judge (injection_llm_judge.py) -- only runs when the heuristic
     found nothing. Catches rephrased/subtle attempts the heuristic isn't
     shaped to catch.

This funnel shape (cheap check decides the obvious "yes" cases, expensive
check only runs on the ambiguous "no from cheap check" cases) is standard
layered-defense practice, not just cost-saving for its own sake -- see
PROGRESS.md Checkpoint 5 for the fuller reasoning on why hybrid over
either layer alone.

NOT included yet: a dedicated classifier model (a third, faster-than-LLM
layer). Deliberately deferred -- we don't yet have real test cases,
including cases the LLM-judge gets wrong, to validate a classifier
against. Same data-grounding principle used throughout this project:
validate against real evidence rather than assumption. Tracked in
PROGRESS.md as a future extension.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.agents.injection_heuristic import heuristic_scan
from app.agents.injection_llm_judge import judge_injection


@dataclass
class InjectionScanResult:
    flagged: bool
    detection_layer: str  # "heuristic" | "llm_judge" | "none"
    reasoning: str


def scan_for_injection(text: str) -> InjectionScanResult:
    """
    Runs the hybrid injection scan. Heuristic first (free); LLM-judge
    only if the heuristic found nothing.
    """
    heuristic_result = heuristic_scan(text)

    if heuristic_result.flagged:
        return InjectionScanResult(
            flagged=True,
            detection_layer="heuristic",
            reasoning=f"Matched pattern(s): {', '.join(heuristic_result.matched_patterns)}",
        )

    judgment = judge_injection(text)

    return InjectionScanResult(
        flagged=judgment.is_injection,
        detection_layer="llm_judge" if judgment.is_injection else "none",
        reasoning=judgment.reasoning,
    )