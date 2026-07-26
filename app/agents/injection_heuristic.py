"""
Prompt-injection heuristic pre-filter -- layer 1 of the hybrid detector,
part of the Guard Agent's injection-scanning responsibility alongside
PII/PCI redaction.

Cheap, deterministic pattern matching. Catches the common, unsophisticated
injection attempts for free (no LLM call) -- most real attempts are fairly
blunt copy-paste jobs ("ignore previous instructions" etc.), so this alone
catches a meaningful share. What it misses (rephrased, subtle, or novel
attempts) is caught by layer 2, the LLM-judge (see injection_llm_judge.py).

Design goal: minimize false positives on legitimate financial-document
language. Real invoices/statements DO contain instructive language
("Please remit payment within 30 days", "Manager override approved") --
the patterns here are deliberately specific phrase combinations aimed at
an AI/system, not single common words.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Each pattern targets a specific injection *shape*, not a single keyword.
# Case-insensitive; \s+ handles OCR/formatting inconsistencies in real
# extracted document text (same messiness we already handle in extraction).
HEURISTIC_PATTERNS: dict[str, re.Pattern] = {
    "ignore_instructions": re.compile(
        r"ignore\s+(all\s+)?(your|my|previous|prior|above|the\s+above)\s+instructions",
        re.IGNORECASE,
    ),
    "disregard_instructions": re.compile(
        r"disregard\s+(all\s+)?(previous|prior|above|the\s+above)",
        re.IGNORECASE,
    ),
    "role_override": re.compile(
        r"you\s+are\s+now\s+(an?\s+)?\w+|act\s+as\s+(an?\s+)?\w+|pretend\s+(you\s+are|to\s+be)",
        re.IGNORECASE,
    ),
    "fake_system_turn": re.compile(r"(^|\n)\s*(system|assistant)\s*:", re.IGNORECASE),
    "new_instructions": re.compile(r"new\s+instructions\s*:", re.IGNORECASE),
    "output_override": re.compile(
        r"(instead\s+)?output\s*:\s*['\"]?(approved|verified|\$?0(\.00)?)",
        re.IGNORECASE,
    ),
}


@dataclass
class HeuristicResult:
    flagged: bool
    matched_patterns: list[str]


def heuristic_scan(text: str) -> HeuristicResult:
    """
    Runs all heuristic patterns against the text. Returns every pattern
    name that matched (not just the first) -- useful for the audit trail
    and for understanding false positives during testing.
    """
    matched = [name for name, pattern in HEURISTIC_PATTERNS.items() if pattern.search(text)]
    return HeuristicResult(flagged=len(matched) > 0, matched_patterns=matched)
