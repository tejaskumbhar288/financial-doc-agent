"""
Experiment (not wired into the real pipeline): does llama3.2:3b, given a real
tool-calling loop via Ollama's `tools` API, actually behave like an agent —
choosing to call a tool, reading its real result, and deciding for itself
when it's done — instead of following a retry count we wrote for it?

Contrast with extract_receipt.py's extract_receipt_with_retry(): that loop
decides "retry or stop" in OUR code based on a Pydantic ValidationError. Here,
the MODEL decides whether to call check_arithmetic, and whether the tool's
result means it should look again or finalize. We just execute what it asks
for and hand the real result back.

Round 2 addition: the loop can now ONLY end via a finalize_extraction tool
call, never via plain text. finalize_extraction's arguments are literally
ReceiptContentRaw (the same flat schema the real pipeline validates through),
so "the model decides it's done" and "we get a real, checkable structured
answer" are the same action. If Pydantic rejects it, the actual validation
error goes back as that tool's result — same self-correction idea as the
retry loop's prior_failure_context, except the model decides what to do with
it instead of us re-running a hardcoded 3rd attempt.

MAX_ITERATIONS is a safety cap (same reasoning Claude Code itself needs some
bound), not a retry budget the model is told about or reasoning around.

Sample receipt text below has a DELIBERATE mismatch (line items sum to 19.00,
printed total says 21.00) so there's an actual reason for the model to call
check_arithmetic and something real for it to catch.
"""

import json
from decimal import Decimal, InvalidOperation

import ollama
from pydantic import ValidationError

from app.agents.extract_receipt import (
    ReceiptContentRaw,
    _describe_validation_error,
    _to_receipt_extraction,
)
from app.schemas.base import ProcessingStatus
from app.schemas.receipt import ReceiptExtraction

MODEL = "llama3.2:3b"
MAX_ITERATIONS = 8  # raised from 6: the mismatch-rejection round-trip costs iterations

SAMPLE_RECEIPT_TEXT = """
FRESH MART SDN BHD
123 JALAN BUKIT BINTANG,
50200 KUALA LUMPUR

DATE: 14/03/2024

ITEM                QTY   PRICE   AMOUNT
Milk 1L               2    4.50    9.00
Bread                  1    3.20    3.20
Eggs (12pc)            1    6.80    6.80

SUBTOTAL:                           19.00
TOTAL:                               21.00
"""

CHECK_ARITHMETIC_TOOL = {
    "type": "function",
    "function": {
        "name": "check_arithmetic",
        "description": (
            "Checks whether a receipt's line-item amounts sum to its printed "
            "total. Call this after reading the line items and total off the "
            "receipt, to verify the reading is internally consistent before "
            "finalizing an answer."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "line_item_amounts": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Each line item's amount, as printed (e.g. '9.00').",
                },
                "total": {
                    "type": "string",
                    "description": "The receipt's printed total, as printed (e.g. '21.00').",
                },
            },
            "required": ["line_item_amounts", "total"],
        },
    },
}

# Arguments mirror ReceiptContentRaw exactly (flat strings only, empty string
# for absent fields) so a successful call can be handed straight to the same
# _to_receipt_extraction() the real pipeline uses.
FINALIZE_TOOL = {
    "type": "function",
    "function": {
        "name": "finalize_extraction",
        "description": (
            "Call this ONLY once you're satisfied the extraction is complete "
            "and internally consistent (verified via check_arithmetic if line "
            "items are present). This ends the task. Do not give a plain-text "
            "final answer instead - it will not be accepted."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "merchant_name": {"type": "string"},
                "merchant_address": {
                    "type": "string",
                    "description": "Empty string if not present.",
                },
                "transaction_date": {
                    "type": "string",
                    "description": "As printed on the receipt.",
                },
                "total": {"type": "string"},
                "document_number": {
                    "type": "string",
                    "description": "Empty string if not present.",
                },
                "cashier": {"type": "string", "description": "Empty string if not present."},
            },
            "required": [
                "merchant_name",
                "merchant_address",
                "transaction_date",
                "total",
                "document_number",
                "cashier",
            ],
        },
    },
}


# The second legitimate exit. Without this the agent has only one terminal
# action ("finish successfully"), so a document it correctly judges
# un-finalizable leaves it with no legal move - confirmed live, where the
# model looped writing "cannot finalize" as prose because no tool said it.
# Mirrors the review_queue concept: a reason, recorded, not a silent failure.
FLAG_FOR_REVIEW_TOOL = {
    "type": "function",
    "function": {
        "name": "flag_for_review",
        "description": (
            "Call this to end the task by sending the document to human review "
            "instead of finalizing it. Use it when the document cannot be "
            "extracted correctly - for example the numbers genuinely do not add "
            "up, or the text is too damaged to read reliably. This is a valid "
            "way to finish, not a failure."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "Why this document needs a human, stated specifically.",
                },
            },
            "required": ["reason"],
        },
    },
}


def check_arithmetic(line_item_amounts: list[str], total: str) -> dict:
    """
    The tool's real implementation. Same ±0.01 tolerance as the
    architecture's amount-mismatch rule (legitimate per-line rounding).

    line_item_amounts is typed as an array in the tool schema, but confirmed
    live (4/4 runs) that llama3.2:3b consistently emits it as a JSON-encoded
    STRING instead (e.g. '["9.00", "3.20"]') rather than a real list - the
    same grammar-decoding limitation Section 8a documents for structured
    output, showing up here on tool-call arguments instead. Parsed
    defensively rather than trusting the declared schema type.
    """
    if isinstance(line_item_amounts, str):
        try:
            line_item_amounts = json.loads(line_item_amounts)
        except json.JSONDecodeError:
            return {"error": "line_item_amounts was a string that wasn't valid JSON"}

    # str() first: the model sometimes sends JSON numbers (9.0) rather than
    # strings ("9.00"), and Decimal(float) expands the binary representation
    # (19.00000000000000000000000000). Going via str keeps money exact -
    # the same reason the schemas use Decimal rather than float throughout.
    try:
        amounts = [Decimal(str(a)) for a in line_item_amounts]
        total_decimal = Decimal(str(total))
    except InvalidOperation:
        return {"error": "could not parse one or more amounts as a number"}

    computed_sum = sum(amounts, start=Decimal("0"))
    discrepancy = computed_sum - total_decimal
    return {
        "matches": abs(discrepancy) <= Decimal("0.01"),
        "computed_sum": str(computed_sum),
        "printed_total": str(total_decimal),
        "discrepancy": str(discrepancy),
    }


def _build_prompt(receipt_text: str) -> str:
    return f"""You are extracting and verifying data from a scanned receipt's raw OCR text.

Tools available:
- check_arithmetic: verifies line-item amounts sum to the printed total. Use it if line
  items are visible, before finalizing.
- finalize_extraction: end the task with a clean extraction. Only accepted once
  check_arithmetic reports the numbers match.
- flag_for_review: end the task by sending the document to a human, with a reason. Use
  this if the document genuinely cannot be extracted correctly.

You must end by calling either finalize_extraction or flag_for_review. Plain text is
not accepted as an answer.

Receipt OCR text:
---
{receipt_text}
---

Extract merchant name, address, transaction date, total, document number, and cashier.
Use empty string "" for any field that is genuinely not present.
"""


def run_agentic_extraction(
    receipt_text: str, source_filename: str = "sample.jpg"
) -> tuple[ReceiptExtraction | None, ProcessingStatus]:
    """
    The loop ends only via a tool call: finalize_extraction (clean result) or
    flag_for_review (honest abstention). Plain text is treated as an
    intermediate slip, not a valid end state, and gets nudged back toward a
    tool. A failed finalize_extraction (Pydantic ValidationError) hands the
    real error back as that tool's result and lets the model decide how to
    correct it - the retry loop's prior_failure_context idea, minus the fixed
    attempt count.

    Returns the same (result, status) shape as extract_receipt_with_retry, so
    the two are directly comparable.
    """
    messages: list[dict] = [{"role": "user", "content": _build_prompt(receipt_text)}]
    tools = [CHECK_ARITHMETIC_TOOL, FINALIZE_TOOL, FLAG_FOR_REVIEW_TOOL]
    # Guardrail state: the last SUCCESSFUL check_arithmetic result, or None if
    # it has never run cleanly. finalize_extraction is refused both when this
    # is None (never verified) and when it says matches=False (verified, and
    # the numbers don't add up) - confirmed live that checking only the former
    # lets the model finalize a known-mismatched document as "processed".
    last_arithmetic: dict | None = None

    for iteration in range(1, MAX_ITERATIONS + 1):
        print(f"\n=== iteration {iteration} ===")
        response = ollama.chat(model=MODEL, messages=messages, tools=tools)
        messages.append(response.message.model_dump())

        if not response.message.tool_calls:
            print("[model] plain text, no tool call (not accepted as final):")
            print(response.message.content)
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "You must call a tool to proceed - check_arithmetic to verify, "
                        "finalize_extraction to finish, or flag_for_review to send this "
                        "to a human. Plain text is not accepted."
                    ),
                }
            )
            continue

        for call in response.message.tool_calls:
            name = call.function.name
            args = call.function.arguments
            print(f"[model] called tool: {name}({args})")

            if name == "finalize_extraction" and last_arithmetic is None:
                print("[finalize REJECTED] check_arithmetic not called yet")
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": (
                            "Rejected: you must call check_arithmetic to verify the "
                            "line items sum to the total before finalize_extraction "
                            "will be accepted."
                        ),
                    }
                )

            elif (
                name == "finalize_extraction"
                and last_arithmetic is not None
                and not last_arithmetic["matches"]
            ):
                print("[finalize REJECTED] arithmetic does not match")
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": (
                            f"Rejected: check_arithmetic reported the line items sum to "
                            f"{last_arithmetic['computed_sum']} but the printed total is "
                            f"{last_arithmetic['printed_total']} (discrepancy "
                            f"{last_arithmetic['discrepancy']}). A document whose numbers "
                            "do not add up cannot be finalized as processed."
                        ),
                    }
                )

            elif name == "finalize_extraction":
                try:
                    content = ReceiptContentRaw(**args)
                    result = _to_receipt_extraction(content, source_filename)
                except ValidationError as exc:
                    failure_reason = _describe_validation_error(exc)
                    print(f"[finalize FAILED] {failure_reason}")
                    messages.append(
                        {
                            "role": "tool",
                            "name": name,
                            "content": f"Validation failed: {failure_reason}. "
                            "Correct the fields and call finalize_extraction again.",
                        }
                    )
                else:
                    print("[finalize SUCCEEDED]")
                    return result, ProcessingStatus.PROCESSED

            elif name == "flag_for_review":
                # A legitimate terminal state, not a failure - the agent judged
                # the document un-extractable and said so through a real tool
                # instead of prose. Reason is what the review_queue would store.
                print(f"[flagged for review] {args.get('reason', '(no reason given)')}")
                return None, ProcessingStatus.NEEDS_REVIEW

            elif name == "check_arithmetic":
                try:
                    tool_result = check_arithmetic(**args)
                except TypeError as exc:
                    # Model sent arguments that don't match the declared schema
                    # (wrong/extra/missing keys) - never let that crash the
                    # harness. Feed the real error back like any other tool
                    # failure, same as the finalize_extraction rejection path.
                    tool_result = {"error": f"{exc}. Expected exactly: line_item_amounts, total."}
                else:
                    # Only a real verdict counts as "verified" - check_arithmetic
                    # also returns {"error": ...} for unparseable input, which is
                    # a failed check, not a passed one.
                    if "matches" in tool_result:
                        last_arithmetic = tool_result
                print(f"[tool result] {tool_result}")
                messages.append({"role": "tool", "name": name, "content": json.dumps(tool_result)})

            else:
                messages.append(
                    {
                        "role": "tool",
                        "name": name,
                        "content": json.dumps({"error": f"unknown tool {name}"}),
                    }
                )

    # Budget exhausted without the model reaching either terminal tool. Same
    # outcome as flag_for_review, but note the difference for the audit trail:
    # this is the harness giving up, not the agent deciding.
    print(f"\n[stopped] hit MAX_ITERATIONS={MAX_ITERATIONS} without reaching a terminal tool")
    return None, ProcessingStatus.NEEDS_REVIEW


if __name__ == "__main__":
    final, final_status = run_agentic_extraction(SAMPLE_RECEIPT_TEXT)
    print(f"\n--- Loop result: {final_status.value} ---")
    if final is not None:
        print(final.model_dump_json(indent=2))
