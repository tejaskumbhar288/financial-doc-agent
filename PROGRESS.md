# Financial Document Intelligence Agent — Progress Log

> **Purpose:** This file tracks actual build progress, git state, and any
> decisions/loopholes discovered that update or deviate from ARCHITECTURE.md.
> Re-upload this file to Project knowledge whenever it changes, so any new
> chat has full context without re-explaining everything from scratch.
>
> Last updated: Checkpoint 2 complete (tagged v0.2.0)

---

## Environment

- OS: Ubuntu
- Python: 3.12, managed via `uv` (not plain venv/pip)
- Local LLM: Ollama, model `llama3.2:3b` (chosen over `llama3.1:8b` from the
  architecture doc — machine has 7.1GB RAM, not enough headroom for an 8B
  model comfortably)
- GitHub repo: `tejaskumbhar288/financial-doc-agent`
- Branching model: `main` (protected, PR-only) ← `development` ← `feature/*`
- Commit convention: Conventional Commits (`feat:`, `fix:`, `docs:`, etc.)

---

## Checkpoint 1 — Pydantic Schemas — ✅ COMPLETE (tagged v0.1.0)

All merged to `main`. Tag: `v0.1.0`.

- `FinancialDocument` (base) — `app/schemas/base.py`
- `ReceiptExtraction` — `app/schemas/receipt.py` — grounded in real **SROIE
  (ICDAR 2019)** Kaggle dataset. Confirmed ground-truth fields: company,
  date, address, total (only 4 — line items NOT in ground truth, added as
  optional anyway to support the "line items sum to total" anomaly rule).
  Date format: DD/MM/YYYY.
- `InvoiceExtraction` — `app/schemas/invoice.py` — grounded in real
  **"High-Quality Invoice Images for OCR"** Kaggle dataset (via a public
  notebook's OCR output). Line items REQUIRED (unlike receipts). European
  decimal commas ("72,00") normalized in a validator. Date format:
  MM/DD/YYYY (opposite of SROIE!). `vendor_iban` added optionally to
  support the vendor/account-mismatch anomaly rule.
- `StatementExtraction` — `app/schemas/statement.py` — NOT grounded in
  Kaggle (real statement data too PII-sensitive to find publicly).
  Designed from general knowledge, validated against synthetic Faker data
  (`app/data/generate_synthetic_statement.py`). Key decision:
  `account_number_redacted`/`routing_number_redacted` model the
  **already-redacted** form, since the Guard Agent runs before Extraction
  in the real pipeline — the schema should never hold raw PII.

**Architecture doc updates made:** added Section 5 (Kaggle/synthetic data
sources for testing) and an MCP tool-integration subsection to Section 8,
documenting MCP as the general tool-integration layer for agents (e.g.
Kaggle connector for dev/test data, Postgres query tool for the Query
Agent). See the updated `ARCHITECTURE.md` (re-upload separately if not
already current in Project knowledge).

---

## Checkpoint 2 — First Real LLM Extraction Call — ✅ COMPLETE (tagged v0.2.0)

**Status:** Merged to `development`, then `main`. Tagged `v0.2.0`.

**What works:** `app/agents/extract_receipt.py` — raw OCR text (real SROIE
sample `X00016469612.jpg`) → local LLM (`llama3.2:3b` via Ollama) →
JSON-schema-constrained decoding → Pydantic validation → validated
`ReceiptExtraction` object. Tested successfully end-to-end.

**Important loophole discovered (deviates from naive Checkpoint 1 assumption):**
Ollama's JSON-schema-constrained decoding converts schemas into a GBNF
grammar under the hood, which is much more limited than full JSON Schema.
It **cannot handle**:
- `$ref`/`$defs` (i.e. nested Pydantic models, like `ReceiptLineItem`
  nested inside `ReceiptExtraction`)
- `anyOf` (i.e. `Optional[...]` / `X | None` fields)
- Non-primitive types like `Decimal` or `date`

**Resolution:** introduced an intermediate flat, string-only schema
(`ReceiptContentRaw` in `extract_receipt.py`) that the LLM extracts into.
Our existing `ReceiptExtraction` field validators (built in Checkpoint 1)
then do the real type coercion (str → date, str → Decimal) afterward, and
raise `ValidationError` if the LLM's output doesn't actually fit — this is
exactly the mechanism the future retry loop (Checkpoint 3) will catch.

**Not yet solved:** line items were dropped from what the LLM extracts in
this first pass (nested list-of-objects extraction is harder under grammar
constraints) — will need a separate approach when we tackle invoice
extraction (nested `line_items` is required there, not optional).

**Design boundary reinforced:** the LLM only ever extracts *content*
fields. System metadata (`document_id`, `source_filename`, `upload_date`,
`confidence_score` placeholder, `status`) is assigned by our own code, not
invented by the LLM.

---

## Checkpoint 3 — Self-Check/Retry Loop — ⬜ NOT STARTED

Plan: wrap `extract_receipt()` in the retry loop shape from Architecture
doc Section 9 — catch `ValidationError`, extract structured failure info
via `.errors()`, feed back as `prior_failure_context` into the next LLM
attempt, up to `MAX_RETRIES` (2 retries / 3 attempts total for Extraction
Agent per Section 9's table), fall back to `needs_human_review` status
after that.

---

## Not Yet Started (per architecture doc build phases)

- Guard Agent (PII/prompt-injection redaction)
- LangGraph orchestration (currently everything is plain Python, no graph)
- Anomaly Detection Agent
- Postgres persistence
- Redis queue
- Reconciliation step
- Query Agent (text-to-SQL)
- Docker + Langfuse
- AWS deployment

---

## Git Housekeeping Notes

- `feature/financial-document-schema` — merged, deleted after Checkpoint 1
- `feature/first-llm-extraction` — merged to `development`, then
  `development` merged to `main`. Tagged `v0.2.0`.
- Learned/reinforced habit: always branch new `feature/*` work directly
  off freshly-pulled `development`, not off a previous feature branch —
  use `git stash` if switching branches with uncommitted work in progress,
  rather than carrying uncommitted changes across via checkout
- Branch protection active on `main`: PR required, force-push blocked,
  deletion restricted
- Tags so far: `v0.1.0` (Checkpoint 1 — all schemas), `v0.2.0`
  (Checkpoint 2 — first working LLM extraction)
