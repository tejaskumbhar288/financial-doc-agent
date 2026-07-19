"""
Checkpoint 2: first real LLM extraction call.

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
from pydantic import BaseModel

from app.schemas.receipt import ReceiptExtraction

MODEL = "llama3.2:3b"


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

EXTRACTION_PROMPT = f"""You are extracting structured data from a scanned receipt's raw OCR text.
The OCR text is messy and may have spacing/formatting errors — infer the correct values.
If a field is genuinely not present, use an empty string "".

Receipt OCR text:
---
{RAW_RECEIPT_TEXT}
---

Extract the receipt's merchant name, address, transaction date (keep original format as printed),
total, document number, and cashier.
"""


def extract_receipt(source_filename: str) -> ReceiptExtraction:
    response = ollama.chat(
        model=MODEL,
        messages=[{"role": "user", "content": EXTRACTION_PROMPT}],
        format=ReceiptContentRaw.model_json_schema(),
    )

    raw_json = response["message"]["content"]
    print("--- Raw LLM output ---")
    print(raw_json)
    print("----------------------")

    content = ReceiptContentRaw.model_validate_json(raw_json)

    receipt = ReceiptExtraction(
        source_filename=source_filename,
        confidence_score=0.9,
        merchant_name=content.merchant_name,
        merchant_address=content.merchant_address or None,
        transaction_date=content.transaction_date,
        total=content.total,
        document_number=content.document_number or None,
        cashier=content.cashier or None,
    )
    return receipt


if __name__ == "__main__":
    result = extract_receipt(source_filename="X00016469612.jpg")
    print("\n--- Validated ReceiptExtraction ---")
    print(result.model_dump_json(indent=2))
