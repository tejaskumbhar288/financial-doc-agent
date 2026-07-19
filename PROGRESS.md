# Financial Document Intelligence Agent — Progress Log

> **Purpose:** This file tracks actual build progress, git state, and any
> decisions/loopholes discovered that update or deviate from ARCHITECTURE.md.
> Re-upload this file to Project knowledge whenever it changes, so any new
> chat has full context without re-explaining everything from scratch.
>
> Last updated: Checkpoint 3 complete (tagged v0.3.0)

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

## Checkpoint 3 — Self-Check/Retry Loop — ✅ COMPLETE

**What works:** `extract_receipt_with_retry()` in `app/agents/extract_receipt.py`
wraps extraction in the retry loop from Architecture doc Section 9. On
`ValidationError`, the failure is converted to a readable message via
Pydantic's `.errors()` (e.g. `"transaction_date: Input should be a valid
date..."`) and threaded back into the next attempt's prompt as
`prior_failure_context` — the short-term/in-loop memory mechanism from
Section 10. Capped at `MAX_RETRIES = 2` (3 attempts total, per Section 9's
table for the Extraction Agent). All attempts are logged via `print()`
(attempt number, success/failure, reason) — a stand-in for the real
Postgres audit trail / `review_queue` table, which lands in Checkpoint 5+.
Returns `(ReceiptExtraction | None, status)` rather than raising, matching
the `processed | needs_review | unreconciled` status enum already defined
in `base.py`.

Refactored `extract_receipt.py` into three pieces first (own commit, no
behavior change) so the retry loop's diff stayed readable:
- `_call_llm(prior_failure_context)` — LLM call only
- `_to_receipt_extraction(content, source_filename)` — Pydantic
  construction/validation only (the piece that can raise)
- `_build_prompt(prior_failure_context)` — prompt assembly, with a
  "your previous attempt had a problem: ..." block injected on retry

**Tested manually (no automated tests yet):**
- Happy path: clean receipt text → attempt 1 succeeds, `status="processed"`
- Failure path: corrupted the date field in `RAW_RECEIPT_TEXT` to force a
  `ValidationError` → confirmed all 3 attempts logged individually, loop
  exhausted cleanly, returned `(None, "needs_human_review")` with no
  unhandled exception

**Design gap discovered (deviates from naive assumption, doesn't block
Checkpoint 3):** during failure-path testing, corrupting the date to a
prose format ("25 December 2018") caused all 3 retries to fail with the
*identical* error every time — the retry mechanism worked correctly, but
retrying didn't help, because the failure wasn't the LLM extracting
wrong data (it faithfully transcribed the OCR text each time); it was
`ReceiptExtraction`'s `parse_dd_mm_yyyy` validator only handling
slash-separated `DD/MM/YYYY`, per its SROIE-grounded design (see
`receipt.py` docstring). Retry only helps when the *LLM's* extraction
was the actual problem (hallucinated/misread fields) — not when a
downstream parser is narrower than valid real-world input. Decision:
leave the date parser narrow for now, since it's grounded in confirmed
real SROIE ground-truth data, not guessed — broaden it later (e.g. with
`dateutil.parser` as a fallback) only if/when real evidence shows other
date formats showing up often. Flagged here rather than silently fixed.

**Not yet solved:** no automated tests for the retry loop (manual testing
only so far); `_call_llm`'s own exceptions (e.g. Ollama connection errors)
are NOT caught by the retry loop — only `ValidationError` is, deliberately,
since infra failures and extraction-quality failures are different
failure classes and probably shouldn't share a retry strategy.

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

## Git Housekeeping Notes (addendum)

- Discovered mid-Checkpoint-3: `PROGRESS.md` had been merged into `main`
  (via v0.2.0) but never merged back into `development`, so a
  freshly-pulled `development` was missing it. Fixed by pulling
  `development`, merging `origin/main` into it, pushing, then rebasing
  the feature branch on top. Lesson: when a docs/fix commit goes into
  `main` directly (e.g. via a hotfix-style PR), remember to merge it back
  into `development` too, or future feature branches silently diverge.
