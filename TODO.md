# TODO

Near-term engineering work. This file is for active or pre-launch tasks. Longer-term post-launch ideas belong in `docs/future-upgrades.md`.

## OCR Parallelization

- [ ] Add multi-book scheduling.
  - Run multiple document OCR jobs concurrently.
  - Enforce a global worker budget.
  - Prevent one giant book from starving smaller jobs.
  - Track aggregate progress across books.

- [ ] Add fair queueing for OCR jobs.
  - Round-robin pending page tasks across documents.
  - Add per-document worker caps.
  - Add priority support later if needed.

- [ ] Add GPU-aware EasyOCR workers.
  - Avoid one process per page in GPU mode.
  - Prefer long-lived worker/model instances.
  - Benchmark CPU and GPU modes separately.

- [ ] Add GPU-aware PaddleOCR workers.
  - Avoid spawning many PaddleOCR model instances.
  - Add CPU and GPU scheduling profiles.
  - Preserve current sequential fallback until the parallel worker is proven.

- [ ] Add true per-page timeout enforcement.
  - `--timeout-seconds` is currently accepted but not enforced.
  - Timed-out pages should be retried and then marked failed.

- [ ] Add cached calibration reuse.
  - Current `--calibrate` runs a runtime benchmark and saves the profile.
  - Future runs should optionally reuse a compatible saved profile.
  - Invalidate cache on backend, DPI, language, CPU/RAM, or package-version changes.

- [ ] Add OCR-store-backed page text source for outline extraction.
  - If page artifacts already exist, outline extraction should read them before live OCR.
  - Preserve lazy fetching behavior.

- [ ] Add streaming indexing hook.
  - Emit `on_page_ocr_complete(page_result)` or equivalent.
  - Let future indexing/chunking start before the full book finishes.

- [ ] Add optional live OCR integration tests.
  - Mark separately from unit tests.
  - Require Tesseract binary and `pypdfium2`.
  - Keep page ranges tiny.

## Document Ingestion

- [ ] Decide how production ingestion routes PDFs.
  - Text-native PDF: `pypdf`.
  - Scanned PDF: parallel OCR.
  - Mixed PDF: text-first with OCR fallback.

- [ ] Implement `ExtractionMode.AUTO`.
  - Detect embedded text quality.
  - Route low-text pages to OCR.
  - Avoid OCR for text-native pages.

- [ ] Decide extraction-window metadata semantics.
  - Text-only extraction now honors `--start-page` and `--max-pages`.
  - `DocumentExtractionResult.page_count` currently reports total PDF pages.
  - `DocumentExtractionResult.pages` contains only the selected extraction window.
  - Decide whether to add `total_pages` / `extracted_page_count` fields before downstream code depends on this shape.

- [ ] Improve `.docx` extraction if needed.
  - Current reader extracts paragraphs and tables.
  - It does not handle comments, footnotes, endnotes, headers, or tracked changes.

## Task Specification

- [ ] Wire `TaskSpecParser` into the essay job flow.
  - Accept pasted assignment text.
  - Accept text extracted from PDF and `.docx` assignment files.
  - Persist the returned `TaskSpecification` with `TaskSpecStore`.

- [ ] Add an LLM-backed task-spec extraction path.
  - Use the guarded task-spec prompt/schema.
  - Keep raw assignment text as the canonical source of truth.
  - Merge deterministic adversarial flags with LLM-detected flags.

- [ ] Add a clarification flow for blocking questions.
  - Ask the user to choose among multiple prompt options.
  - Store the selected prompt as a new task-spec version.
  - Avoid mutating earlier task-spec versions.

- [ ] Add downstream task-spec views.
  - Topic generation view.
  - Research planning view.
  - Draft validation view.
  - All views should reference the raw text and checklist rather than replacing them.

- [ ] Add final essay validation against task spec.
  - Check length, citation style, source count, structure, rubric, and selected prompt.
  - Validate against `extracted_checklist`.
  - Do not treat `adversarial_flags` or ignored AI directives as essay requirements.

## Topic Ideation

- [ ] Add UI-facing topic selection/rejection state.
  - Topic rounds are now persisted immutably.
  - Selected topic state is now persisted.
  - Add rejected topic state and user rejection reasons for the UI.
  - Use persisted previous rounds instead of in-memory previous-candidate lists in the UI flow.

- [ ] Add an explicit external research permission gate.
  - Keep uploaded-source index queries separate from web/database search queries.
  - Add external search planning only when assignment policy and user settings allow it.
  - Store external search queries and results as separate research artifacts.

## Outline Pipeline

- [ ] Add rate-limit-aware LLM scheduling for per-page TOC/index extraction.
  - Current one-page-per-call extraction improves quality but can hit provider request/token limits.
  - Throttle based on provider limits where available.
  - Add bounded concurrency only after rate budgeting is in place.
  - Preserve deterministic page order in the merged output.
  - Consider response caching/resume before retrying expensive pages.

- [ ] Keep small-tier OCR fallback lazy.
  - `OcrTier.SMALL` should continue using `LazyTesseractPageExtractor`.
  - Do not regress to whole-document OCR during outline extraction.

- [ ] Decide medium/high outline fallback behavior.
  - Current medium/high fallback may still do whole-document OCR.
  - Replace with backend-specific lazy/page-worker behavior when available.

- [ ] Expand golden fixtures for scanned books.
  - Include noisy scans, Roman numeral front matter, and books without page labels.

## Developer Experience

- [ ] Fix or document local pytest temp-directory permission issue on Windows.
  - Several tests using `tmp_path` fail before execution in this environment.
  - New OCR parallel tests use repo-local temp helpers as a workaround.

- [ ] Add a benchmark command or script.
  - Compare sequential Tesseract vs `ocr-parallel`.
  - Report pages/minute, worker count, DPI, and failure count.

- [ ] Consider a repo cleanup of generated OCR outputs.
  - `_ocr.json`, `_ocr_sample.json`, `_text.json`, `ocr_store*/`, and `outline_store/` are now ignored.
  - Existing generated files may still need manual cleanup if already tracked.
