"""
Checkpoint 2: first real LLM extraction call.
Checkpoint 3: self-check/retry loop around it.

Design note: Ollama's JSON-schema-constrained decoding converts your schema
into a GBNF grammar under the hood — this is much more limited than full
JSON Schema. It can't handle $ref/$defs (nested models), anyOf (Optional
fields), or non-primitive types like Decimal/date. So the schema we hand
the LLM (ReceiptContentRaw) is deliberately FLAT and STRING-ONLY — no
nested line_items, no Optional, no Decimal/date types. Our own
ReceiptExtraction schema (built in Checkpoint 1) still does the real
type coercion and validation afterward, exactly as it did in our earlier
manual tests. This is a real-world local-model constraint, not present
in the same way with cloud providers' proper tool-calling APIs.
"""

import ollama
from pydantic import BaseModel, ValidationError

from app.schemas.receipt import ReceiptExtraction

MODEL = "llama3.2:3b"
MAX_RETRIES = 2  # 2 retries = 3 attempts total, per Architecture doc Section 9


class ReceiptContentRaw(BaseModel):
    """
    What the LLM is asked to produce: flat strings only, so Ollama's
    grammar-based constrained decoding can actually handle it. Type
    coercion (str date -> date, str total -> Decimal) happens afterward
    via ReceiptExtraction's own field validators.
    """

    merchant_name: str
    merchant_address: str
    transaction_date: str
    total: str
    document_number: str
    cashier: str


RAW_RECEIPT_TEXT = """
TAN WOON YANN
BOOK TA .K(TAMAN DAYA) SDN BND
789417-W
NO.53 55,57 & 59, JALAN SAGU 18,
TAMAN DAYA,
81100 JOHOR BAHRU,
JOHOR.
DOCUMENT NO : TD01167104
DATE: 25/12/2018 8:13:39 PM
CASHIER: MANIS
MEMBER:
CASH BILL
TOTAL: 9.00
"""


def _describe_validation_error(exc: ValidationError) -> str:
    """
    Turns a pydantic ValidationError into a short, LLM-readable failure
    reason — e.g. "total: could not parse 'nine dollars' as Decimal".
    This is what gets threaded back in as prior_failure_context (Section 10's
    short-term/in-loop memory) — without it, a retry is just re-asking the
    same question with no new information.
    """
    parts = []
    for err in exc.errors():
        field = ".".join(str(loc) for loc in err["loc"])
        parts.append(f"{field}: {err['msg']}")
    return "; ".join(parts)


def extract_receipt_with_retry(source_filename: str) -> tuple[ReceiptExtraction | None, str]:
    """
    Extraction with the self-check/retry loop from Architecture doc Section 9.

    Returns (result, status):
      - (ReceiptExtraction, "processed")       on success
      - (None, "needs_human_review")           if all attempts fail

    Every attempt is logged (attempt number, failure reason if any) — the
    audit trail requirement. For now this is just print(); Checkpoint 5+
    (Postgres) replaces this with a real review_queue / audit log table.
    """
    prior_failure_context: str | None = None

    for attempt in range(1, MAX_RETRIES + 2):  # +2: 1-indexed, inclusive of final attempt
        print(f"[extract_receipt] attempt {attempt}/{MAX_RETRIES + 1} "
              f"(source_filename={source_filename})")

        try:
            content = _call_llm(prior_failure_context)
            result = _to_receipt_extraction(content, source_filename)
        except ValidationError as exc:
            failure_reason = _describe_validation_error(exc)
            print(f"[extract_receipt] attempt {attempt} FAILED: {failure_reason}")
            prior_failure_context = failure_reason
            continue

        print(f"[extract_receipt] attempt {attempt} SUCCEEDED")
        return result, "processed"

    print(f"[extract_receipt] all {MAX_RETRIES + 1} attempts exhausted — needs_human_review")
    return None, "needs_human_review"


def _build_prompt(prior_failure_context: str | None = None) -> str:
    """
    Builds the extraction prompt. If a previous attempt failed validation,
    prior_failure_context carries the specific reason back in — this is
    the "short-term/in-loop memory" mechanism from Architecture doc
    Section 10: it's what makes a retry an actual second attempt instead
    of just re-asking the same question and hoping for a different answer.
    """
    retry_note = ""
    if prior_failure_context:
        retry_note = f"""
Your previous attempt had a problem: {prior_failure_context}
Please correct this in your new extraction.
"""

    return f"""You are extracting structured data from a scanned receipt's raw OCR text.
The OCR text is messy and may have spacing/formatting errors — infer the correct values.
If a field is genuinely not present, use an empty string "".
{retry_note}
Receipt OCR text:
---
{RAW_RECEIPT_TEXT}
---

Extract the receipt's merchant name, address, transaction date (keep original format as printed),
total, document number, and cashier.
"""


def _call_llm(prior_failure_context: str | None = None) -> ReceiptContentRaw:
    """Single LLM call. Raises nothing itself beyond what ollama/pydantic raise natively."""
    prompt = _build_prompt(prior_failure_context)
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": prompt}],
        format=ReceiptContentRaw.model_json_schema(),
    )
    raw_json = response["message"]["content"]
    return ReceiptContentRaw.model_validate_json(raw_json)


def _to_receipt_extraction(content: ReceiptContentRaw, source_filename: str) -> ReceiptExtraction:
    """
    The validation boundary. This is what can raise pydantic.ValidationError
    if the LLM's string output doesn't actually coerce (e.g. bad date format,
    non-numeric total) — exactly the failure the retry loop is built to catch.
    """
    return ReceiptExtraction(
        source_filename=source_filename,
        confidence_score=0.9,
        merchant_name=content.merchant_name,
        merchant_address=content.merchant_address or None,
        transaction_date=content.transaction_date,
        total=content.total,
        document_number=content.document_number or None,
        cashier=content.cashier or None,
    )


def extract_receipt(source_filename: str) -> ReceiptExtraction:
    """Single-attempt extraction, no retry. Kept for Checkpoint 2 compatibility."""
    content = _call_llm()
    return _to_receipt_extraction(content, source_filename)


if __name__ == "__main__":
    result, status = extract_receipt_with_retry(source_filename="X00016469612.jpg")

    print("\n--- Retry loop result ---")
    print(f"status: {status}")

    if result is not None:
        print(result.model_dump_json(indent=2))
    else:
        print("No valid extraction — flagged for human review.")