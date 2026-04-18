# AGENTS

Guidelines for coding agents and human contributors working in this repository.

## Purpose

This repo is evolving from a PDF extraction prototype into a document ingestion
pipeline for an essay writer system. Changes should preserve correctness,
traceability, and compatibility across source types.

## Required Session Logging

Every agent that makes a code, test, doc, dependency, or configuration change
must add an entry to `session-log.md` before ending the session.

The entry should include:

- date
- agent/tool name, if known
- summary of changes
- files changed
- tests or commands run
- known caveats or follow-ups

Keep entries concise but specific enough that the next agent can continue
without rediscovering context.

## Active Planning Files

- `TODO.md`: near-term engineering tasks.
- `docs/plan.md`: product/system architecture plan.
- `docs/future-upgrades.md`: post-launch or larger future ideas.
- `docs/superpowers/specs/`: formal specs.
- `docs/superpowers/plans/`: implementation plans.
- `session-log.md`: chronological record of agent sessions.

Do not put near-term implementation work only in `docs/future-upgrades.md`.

## Current Important Constraints

- Keep existing `pdf-extract extract` behavior backward-compatible.
- Keep existing `pdf-extract outline` behavior backward-compatible.
- Keep `DocumentExtractionResult` and `PageText` compatible unless explicitly planned.
- Keep `.docx` support working through `DocumentReader`.
- Keep small-tier outline OCR fallback lazy and per-page.
- Do not naively parallelize EasyOCR/PaddleOCR GPU mode.
- Do not add slow live OCR tests to the default test suite.

## OCR Notes

The current parallel OCR implementation supports Tesseract small-tier page-level
parallelism through:

```powershell
pdf-extract ocr-parallel path.pdf --ocr-tier small
```

Medium/high OCR remain compatible but are not truly parallelized yet.

Use `--resume` with a stable `--document-id` for interrupted long runs.

Use `--calibrate` with `--workers auto` to benchmark sample pages and pick a
measured worker count.

## Testing Notes

Prefer focused tests while iterating. Useful commands:

```powershell
pytest tests\ocr_parallel
pytest tests\outline\test_page_text.py
pytest tests\test_ocr_pipeline.py::test_tesseract_backend_with_mocks
python -m compileall pdf_pipeline tests\ocr_parallel
```

There is a known Windows temp-directory permission issue in this environment
that can block tests using pytest's `tmp_path` fixture before the tests execute.
Do not treat that as a product regression unless assertions fail after setup.

## File Hygiene

Generated OCR output is ignored by `.gitignore`:

```text
ocr_store*/
*_ocr.json
*_ocr_sample.json
*_text.json
test-output/
```

Do not commit generated OCR artifacts unless a fixture is intentionally needed
for a test.

## Dependency Changes

When changing `pyproject.toml`:

- keep optional OCR extras separated by backend
- avoid silently skipping required OCR dependencies
- document install commands in `README.md`
- consider Python version compatibility for OCR/ML packages

## Code Style

- Keep changes scoped.
- Prefer small, testable modules.
- Use structured dataclasses for OCR artifacts and summaries.
- Prefer deterministic behavior and explicit warnings over hidden fallbacks.
- Avoid adding abstractions unless they remove real complexity.
