# Session Log

Chronological log of agent sessions. Add a new entry whenever an agent changes code, tests, docs, dependencies, or configuration.

## 2026-04-19 - Codex - TODO Review After LLM-Only TOC Change

Summary:

- Reviewed `TODO.md` after removing deterministic TOC extraction.
- Confirmed there were no active deterministic TOC TODO items to remove.
- Added active follow-ups for LLM rate-limit-aware TOC/index scheduling and extraction-window metadata semantics.

Files changed:

- `TODO.md`
- `session-log.md`

Verification:

- Documentation-only update; no tests run.

---

## 2026-04-19 - Codex - LLM-Only TOC Extraction And Readable Encrypted PDFs

Summary:

- Removed the deterministic/heuristic TOC parser from the outline extraction path.
- Removed `--toc-extraction-mode` and `--deterministic-min-toc-entries` from the outline CLI.
- Kept Layer 2 as LLM-only after TOC prefiltering, with one page per LLM call.
- Fixed `PyPdfExtractor` so PDFs flagged as encrypted are attempted with an empty password before being rejected.
- Made text-only pypdf extraction honor `start_page` and `max_pages`, matching the OCR command surface.
- Added coverage for readable encrypted PDFs and removed deterministic TOC parser tests.

Files changed:

- `pdf_pipeline/cli.py`
- `pdf_pipeline/extractors/pypdf_extractor.py`
- `pdf_pipeline/pipeline.py`
- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/pipeline.py`
- `docs/superpowers/plans/2026-04-18-hybrid-toc-extraction.md`
- `docs/superpowers/specs/2026-04-18-hybrid-toc-extraction.md`
- `tests/test_cli.py`
- `tests/test_pypdf_extractor.py`
- `tests/outline/test_entry_extraction.py`
- `tests/outline/test_pipeline.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\test_pypdf_extractor.py tests\test_cli.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_uses_llm_even_when_toc_text_has_parseable_rows tests\outline\test_pipeline.py::test_extract_outline_uses_single_page_llm_toc_chunks tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm
python -m compileall pdf_pipeline\extractors\pypdf_extractor.py pdf_pipeline\pipeline.py pdf_pipeline\outline pdf_pipeline\cli.py tests\outline tests\test_cli.py tests\test_pypdf_extractor.py
python -c "from pdf_pipeline.extractors.pypdf_extractor import PyPdfExtractor; r=PyPdfExtractor().extract(r'testpdfs\IntelTechniques-OSINT.pdf'); print(r.page_count); print(r.pages[2].text[:80].replace('\n',' | '))"
python -m pdf_pipeline.cli extract testpdfs\IntelTechniques-OSINT.pdf --mode text_only --start-page 3 --max-pages 1 > outputs\codex_osint_page_3_text_smoke.json
```

Results:

- Focused extractor/CLI/outline tests: 26 passed.
- Compile pass succeeded.
- OSINT direct extractor smoke check succeeded: 590 pages read and page 3 starts with `CONTENTS`.
- OSINT CLI text-only page-window smoke check succeeded and wrote one page, page 3, to `outputs/codex_osint_page_3_text_smoke.json`.

Caveats:

- Historical hybrid TOC plan/spec docs were reduced to superseded tombstones instead of deleted.
- `DocumentExtractionResult.page_count` for text-only pypdf extraction still reports total document pages, while `pages` contains the selected extraction window.

---

## 2026-04-19 - Codex - Skip Deterministic TOC Parser For OCR

Summary:

- Changed outline extraction so `toc_extraction_mode=auto` skips the deterministic TOC parser when OCR is enabled.
- Kept deterministic-first behavior for direct/text-native PDF reads, and rejected explicit `toc_extraction_mode=deterministic` when OCR is enabled.
- Added a regression test proving OCR-enabled auto mode calls the LLM even when OCR text looks deterministically parseable.

Files changed:

- `pdf_pipeline/outline/pipeline.py`
- `tests/outline/test_pipeline.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_pipeline.py::test_extract_outline_auto_skips_llm_when_deterministic_is_strong tests\outline\test_pipeline.py::test_extract_outline_auto_skips_deterministic_when_ocr_enabled tests\outline\test_pipeline.py::test_extract_outline_rejects_deterministic_mode_when_ocr_enabled tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_entry_extraction.py
python -m compileall pdf_pipeline\outline tests\outline
```

Results:

- Focused outline tests: 16 passed.
- Compile pass succeeded.

Caveats:

- OCR `auto` mode now pays the LLM cost for candidate TOC/index pages instead of accepting deterministic entries.
- Explicit deterministic mode still exists for controlled direct-PDF experiments; OCR runs now reject it.

---

## 2026-04-19 - Codex - UTF-8 CLI Output

Summary:

- Configured CLI stdout and stderr to UTF-8 at startup so outline titles with non-CP1252 characters do not crash Windows redirected output.
- Added a CLI unit test for UTF-8 stdio reconfiguration.

Files changed:

- `pdf_pipeline/cli.py`
- `tests/test_cli.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\test_cli.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_uses_single_page_llm_toc_chunks tests\llm\test_adapter_claude.py
python -m compileall pdf_pipeline\cli.py tests\test_cli.py
```

Results:

- Focused CLI/outline/Claude tests: 24 passed.
- Compile pass succeeded.

Caveats:

- If an outline run crashed after `store.save(outline)`, the outline version may already exist. Rerun with a fresh `--source-id` or remove that generated outline store entry.

---

## 2026-04-19 - Codex - Per-Page LLM TOC Extraction

Summary:

- Changed Layer 2 LLM TOC extraction to one PDF page per LLM call by setting the max LLM TOC chunk size to `1`.
- Added `source_pdf_page` to `RawEntry` so extracted entries can retain the TOC/OCR page where they were found.
- Updated the TOC prompt and schema to require `source_pdf_page` in LLM entries.
- Propagated `source_pdf_page` through LLM and deterministic TOC extraction.
- Updated outline tests to expect per-page LLM calls and avoid known Windows `tmp_path` permission issues in the touched tests.

Files changed:

- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/pipeline.py`
- `pdf_pipeline/outline/prompts.py`
- `tests/outline/test_entry_extraction.py`
- `tests/outline/test_pipeline.py`
- `tests/outline/test_prompts.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\outline\test_pipeline.py::test_falls_back_to_llm_when_no_outline tests\outline\test_pipeline.py::test_uses_page_labels_when_present tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_pipeline.py::test_extract_outline_uses_single_page_llm_toc_chunks tests\outline\test_label_resolve.py tests\test_cli.py
python -m compileall pdf_pipeline\outline tests\outline
python -m pytest --import-mode=importlib tests\llm tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\outline\test_pipeline.py::test_extract_outline_uses_single_page_llm_toc_chunks tests\outline\test_label_resolve.py tests\test_cli.py
```

Results:

- Focused outline/CLI tests: 32 passed.
- LLM plus focused outline/CLI tests: 54 passed.
- Compile pass succeeded.

Caveats:

- Per-page LLM extraction increases request count. Bounded concurrency and rate-limit-aware scheduling should be considered only after per-page quality is confirmed.
- `source_pdf_page` is captured internally on raw entries but is not yet persisted in `DocumentOutline` output.

---

## 2026-04-19 - Codex - Nullable TOC Printed Pages

Summary:

- Updated Layer 2 TOC extraction so LLM entries can keep visible titles even when OCR does not expose the printed page number.
- Changed `RawEntry.printed_page` to `str | None`.
- Updated the TOC prompt and tool schema to allow `printed_page: null` when the page label is missing, detached, or unreadable.
- Kept the anti-hallucination rule: the model should not invent page numbers.
- Updated page-label resolution so entries with missing printed pages become unresolved instead of crashing or being dropped.
- Added tests for null/missing printed pages, schema validation, and unresolved label-resolution behavior.

Files changed:

- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/label_resolve.py`
- `pdf_pipeline/outline/prompts.py`
- `tests/outline/test_entry_extraction.py`
- `tests/outline/test_label_resolve.py`
- `tests/outline/test_prompts.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\outline\test_label_resolve.py tests\outline\test_anchor_apply.py tests\test_cli.py
python -m compileall pdf_pipeline\outline tests\outline
python -m pytest --import-mode=importlib tests\llm tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_pipeline.py::test_extract_outline_caps_llm_toc_chunk_size tests\outline\test_prompts.py tests\outline\test_label_resolve.py tests\outline\test_anchor_apply.py tests\test_cli.py
```

Results:

- Focused nullable-page tests: 30 passed.
- LLM plus focused outline/CLI tests: 59 passed.
- Compile pass succeeded.

Caveats:

- Missing printed pages remain unresolved in the current pipeline. Later repair can attempt title-based anchor matching or infer page refs from neighboring TOC rows, but this change intentionally does not invent page numbers.

---

## 2026-04-19 - Codex - Robust LLM TOC Chunking

Summary:

- Hardened Layer 2 TOC response handling so malformed `entries` values do not crash extraction.
- Added recovery for `entries` returned as a JSON string, while logging and ignoring non-JSON strings and non-object list items.
- Added malformed-entry validation before constructing `RawEntry` objects.
- Capped LLM TOC chunking at 4 pages per call so large candidate windows are split instead of sent as one huge request.
- Added logging for the effective LLM TOC chunk size.
- Added tests for malformed `entries` strings, JSON-string recovery, malformed entry skipping, and the 4-page TOC chunk cap.

Files changed:

- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/pipeline.py`
- `tests/outline/test_entry_extraction.py`
- `tests/outline/test_pipeline.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_pipeline.py::test_extract_outline_caps_llm_toc_chunk_size tests\outline\test_prompts.py tests\test_cli.py
python -m compileall pdf_pipeline\outline tests\outline
python -m pytest --import-mode=importlib tests\llm tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_pipeline.py::test_extract_outline_caps_llm_toc_chunk_size tests\outline\test_prompts.py tests\test_cli.py
```

Results:

- Focused outline/CLI tests: 23 passed.
- LLM plus focused outline/CLI tests: 49 passed.
- Compile pass succeeded.

Caveats:

- LLM chunks still run serially. Concurrency should be added only with provider-rate-limit controls and stable per-chunk validation.

---

## 2026-04-19 - Codex - Claude Streaming for High Output

Summary:

- Updated the Claude LLM adapter to use Anthropic `messages.stream(...)` for high-output JSON calls above the non-streaming threshold.
- Added fallback streaming when the Anthropic SDK raises `ValueError: Streaming is required` for a non-streaming request.
- Kept normal non-streaming requests on `messages.create(...)`.
- Added tests for high-token streaming and SDK-required streaming fallback.

Files changed:

- `llm/adapters/claude.py`
- `tests/llm/test_adapter_claude.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\llm\test_adapter_claude.py tests\llm\test_client.py tests\llm\test_mock.py tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\test_cli.py
python -m compileall llm\adapters\claude.py tests\llm\test_adapter_claude.py
```

Results:

- Claude adapter/client/mock plus focused outline/CLI tests: 32 passed.
- Compile pass succeeded.

Caveats:

- Streaming solves the SDK-side long-request guard, but real requests can still hit account rate limits or provider-side model output caps.

---

## 2026-04-19 - Codex - Raised Generic LLM Output Budget

Summary:

- Added shared `DEFAULT_LLM_MAX_OUTPUT_TOKENS = 16000`.
- Updated the LLM protocol, mock client, Claude adapter, OpenAI adapter, and Gemini adapter to use the shared 16k default.
- Kept the TOC-specific extraction override at `64000`.
- Added tests for the shared default and mock default behavior.
- Added `tests/__init__.py` so pytest imports `tests.llm.*` instead of colliding with the source package named `llm`.

Files changed:

- `llm/client.py`
- `llm/mock.py`
- `llm/adapters/claude.py`
- `llm/adapters/openai_.py`
- `llm/adapters/gemini.py`
- `tests/__init__.py`
- `tests/llm/test_client.py`
- `tests/llm/test_mock.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\llm tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\test_cli.py
python -m compileall llm pdf_pipeline\outline tests\llm tests\outline tests\__init__.py
rg -n "4096" llm tests pdf_pipeline\outline
```

Results:

- LLM adapter/client/mock tests plus focused outline/CLI tests: 41 passed.
- Compile pass succeeded.
- No remaining `4096` literals under `llm`, outline tests, or outline code.

Caveats:

- Higher defaults may be rejected by manually selected legacy models with lower provider-side output caps.
- The Gemini SDK emitted its existing deprecation warning for `google.generativeai`.

---

## 2026-04-19 - Codex - Raised TOC LLM Output Budget

Summary:

- Raised the TOC-specific LLM extraction output budget from `4096` to `64000` tokens by default.
- Added `TOC_LLM_MAX_OUTPUT_TOKENS` so the extraction budget is explicit instead of a hidden literal.
- Added a regression test verifying TOC extraction sends the high output budget to the LLM client by default.

Files changed:

- `pdf_pipeline/outline/entry_extraction.py`
- `tests/outline/test_entry_extraction.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_entry_extraction.py tests\outline\test_prompts.py tests\test_cli.py
python -m compileall pdf_pipeline\outline tests\outline
```

Results:

- Focused outline entry extraction/prompt/CLI tests: 17 passed.
- Compile pass succeeded.

Caveats:

- `64000` matches current Haiku 4.5/Sonnet 4.x output limits, but older Claude models with smaller output caps may reject this value if selected manually.

---

## 2026-04-19 - Codex - Stricter TOC LLM Prompt

Summary:

- Tightened the Layer 2 TOC extraction system prompt so the model must return a top-level `entries` array and must not return only page classifications when visible TOC rows are present.
- Added explicit anti-hallucination guidance: extract only rows where both title and printed page label are visible, and allow empty `entries` only when no extractable title+page rows appear.
- Added instructions for OCR-heavy old-book layouts, including dot leaders and two-column TOCs.
- Added a prompt regression test to keep the top-level entries and anti-hallucination requirements in place.

Files changed:

- `pdf_pipeline/outline/prompts.py`
- `tests/outline/test_prompts.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_prompts.py tests\outline\test_entry_extraction.py
python -m compileall pdf_pipeline\outline tests\outline
```

Results:

- Prompt + entry extraction tests: 11 passed.
- Compile pass succeeded.

Caveats:

- Prompt tightening reduces empty TOC responses but does not guarantee compliance. The next hardening step should be schema validation with retry/repair when `is_toc=true` and visible rows are present but `entries` is missing or empty.

---

## 2026-04-18 - Codex - Hybrid TOC Extraction Modes

Summary:

- Added hybrid TOC extraction spec and implementation plan.
- Renamed the heuristic TOC parser to deterministic extraction while keeping a compatibility alias.
- Changed Layer 2 default behavior to deterministic-first `auto` mode.
- Added `deterministic` and `llm` modes so TOC extraction can be forced during debugging.
- Added CLI flags `--toc-extraction-mode` and `--deterministic-min-toc-entries`.
- Added tests for deterministic-first skip behavior, forced LLM mode, forced deterministic mode, and CLI parsing.
- Added defensive recovery/logging for LLM responses that put entries under page objects instead of the required top-level `entries` array.

Files changed:

- `docs/superpowers/specs/2026-04-18-hybrid-toc-extraction.md`
- `docs/superpowers/plans/2026-04-18-hybrid-toc-extraction.md`
- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/pipeline.py`
- `pdf_pipeline/cli.py`
- `tests/outline/test_pipeline.py`
- `tests/outline/test_entry_extraction.py`
- `tests/test_cli.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_prefilter.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_extract_outline_auto_skips_llm_when_deterministic_is_strong tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\outline\test_pipeline.py::test_extract_outline_deterministic_mode_never_calls_llm tests\outline\test_pipeline.py::test_load_pages_text_parallel_calls_run_parallel_ocr tests\test_cli.py
python -m pytest --import-mode=importlib tests\outline\test_page_text.py tests\outline\test_anchor_apply.py tests\outline\test_anchor_offset.py tests\outline\test_anchor_selection.py tests\outline\test_anchor_forward_scan.py tests\outline\test_label_resolve.py tests\outline\test_range_assignment.py
python -m pytest --import-mode=importlib tests\ocr_parallel tests\task_spec
python -m compileall pdf_pipeline\outline tests\outline pdf_pipeline\cli.py tests\test_cli.py
python -m pytest --import-mode=importlib tests\outline\test_entry_extraction.py tests\outline\test_prefilter.py tests\outline\test_pipeline.py::test_extract_outline_auto_skips_llm_when_deterministic_is_strong tests\outline\test_pipeline.py::test_extract_outline_llm_mode_calls_llm_even_with_deterministic_entries tests\test_cli.py
```

Results:

- TOC prefilter/entry extraction/pipeline mode/CLI tests: 23 passed.
- Entry extraction/prefilter/selected pipeline/CLI tests after nested-entry recovery: 21 passed.
- Outline page text/anchor/label/range tests: 35 passed.
- OCR parallel + task-spec tests: 27 passed.
- Compile pass succeeded.

Caveats:

- Full `tests\outline\test_pipeline.py` remains affected by this environment's pytest `tmp_path` permission issue.
- The deterministic parser is intentionally conservative and still needs real-book fixture coverage beyond Gray's Anatomy.

---

## 2026-04-18 - Codex - Outline LLM Call Reduction and TOC Fallback

Summary:

- Fixed outline/indexation path so Layer 2 does not blindly call the LLM over every 5-page chunk in the full TOC scan window.
- Added per-page TOC scoring and candidate-window selection before LLM extraction.
- Increased effective Layer 2 chunk size for the isolated TOC window so common front-matter TOCs are sent in one call instead of many small calls.
- Added info logs for each Layer 2 LLM chunk, including page numbers, `is_toc`, and entry counts.
- Added deterministic OCR-heavy TOC fallback extraction when the LLM returns zero entries on obvious `CONTENTS` pages.
- Kept `--parallel-workers` in the outline path as true OCR of the TOC window; removed the pypdf-first shortcut from this branch because text-source strategy should be explicit, not hidden inside parallel OCR.
- Added tests for TOC page scoring, candidate-window selection, heuristic OCR TOC extraction, and one-call candidate-window dispatch.
- Ignored generated `build/` and `.pytest_tmp*/` directories.

Files changed:

- `.gitignore`
- `pdf_pipeline/outline/prefilter.py`
- `pdf_pipeline/outline/entry_extraction.py`
- `pdf_pipeline/outline/pipeline.py`
- `tests/outline/test_prefilter.py`
- `tests/outline/test_entry_extraction.py`
- `tests/outline/test_pipeline.py`
- `session-log.md`

Verification:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_prefilter.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm
python -m pytest --import-mode=importlib tests\outline\test_prefilter.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_load_pages_text_parallel_calls_run_parallel_ocr
python -m pytest --import-mode=importlib tests\outline\test_page_text.py tests\outline\test_anchor_apply.py tests\outline\test_anchor_offset.py tests\outline\test_anchor_selection.py tests\outline\test_anchor_forward_scan.py tests\outline\test_label_resolve.py tests\outline\test_range_assignment.py
python -m pytest --import-mode=importlib tests\ocr_parallel tests\task_spec
python -m compileall pdf_pipeline\outline tests\outline
```

Results:

- TOC prefilter/entry extraction/new pipeline test: 14 passed.
- TOC prefilter/entry extraction/new pipeline tests after OCR semantics correction: 15 passed.
- Outline page text/anchor/label/range tests: 35 passed.
- OCR parallel + task-spec tests: 27 passed.
- Compile pass succeeded.

Caveats:

- Running the entire `tests\outline\test_pipeline.py` file still hits this environment's known pytest `tmp_path` permission issue before assertions execute.
- The heuristic TOC fallback is conservative. It is meant to avoid empty outlines on obvious OCR TOC pages, not replace the LLM for all TOC layouts.

---

## 2026-04-18 - Codex - Task Specification Parser

Summary:

- Added task specification design and implementation docs.
- Added `essay_writer.task_spec` with schema dataclasses, deterministic adversarial scanning, guarded LLM extraction prompt/schema, parser, and immutable versioned storage.
- Preserved raw assignment text as canonical input and kept adversarial AI-directed text separate from normal checklist requirements.
- Excluded due date, collaboration policy, and AI policy from the task-spec data model.
- Updated high-level plan and near-term TODOs for task-spec integration.
- Added `outline_store/` to ignored generated artifacts.

Files changed:

- `docs/plan.md`
- `.gitignore`
- `docs/superpowers/specs/2026-04-18-task-specification-design.md`
- `docs/superpowers/plans/2026-04-18-task-specification-implementation.md`
- `essay_writer/task_spec/*`
- `tests/task_spec/*`
- `pyproject.toml`
- `TODO.md`
- `session-log.md`

Verification:

```powershell
pytest tests\task_spec
python -m compileall essay_writer tests\task_spec
pytest tests\ocr_parallel
pytest tests\test_ocr_pipeline.py::test_tesseract_backend_with_mocks tests\outline\test_page_text.py
```

Results:

- `tests\task_spec`: 11 passed.
- Compile pass succeeded.
- `tests\ocr_parallel`: 16 passed.
- Tesseract backend mock + outline page-text tests: 11 passed.

Caveats:

- The baseline parser is intentionally conservative. Production-quality subtle requirement extraction should use the guarded LLM path.
- Task-spec parsing is implemented as a module but is not yet wired into the end-to-end essay job workflow.

---

## 2026-04-18 — Claude Sonnet 4.6 — Parallel OCR integrated into outline pipeline

Summary:

- Changed default Claude model in `ClaudeClient` from `claude-sonnet-4-6` to `claude-haiku-4-5-20251001` (cost reduction for structured extraction tasks).
- Added `_parallel_ocr_pages` helper to `pdf_pipeline/outline/pipeline.py` that calls `run_parallel_ocr` scoped to the TOC window (`max_pages=scan_pages`) using a `tempfile.mkdtemp()` store, converts the result to `dict[int, str]`, and cleans up the temp dir in a `finally` block.
- Updated `_load_pages_text` to accept `parallel_workers: int | str | None` and `calibrate: bool`; when `parallel_workers` is set and `lazy=False`, delegates to `_parallel_ocr_pages` instead of sequential Tesseract loop.
- Updated `extract_outline` to accept and thread `parallel_workers` and `calibrate` through to the eager TOC window call only. Layer 3 anchor scan remains lazy/sequential.
- Added `--parallel-workers N|auto` and `--calibrate` flags to the `outline` CLI subparser.
- Added `tests/test_cli.py` with three argparse parsing tests.
- Added two tests to `tests/outline/test_pipeline.py` covering the parallel branch and the `extract_outline` passthrough.

Files changed:

- `llm/adapters/claude.py`
- `pdf_pipeline/outline/pipeline.py`
- `pdf_pipeline/cli.py`
- `tests/outline/test_pipeline.py`
- `tests/test_cli.py` (new)
- `docs/superpowers/specs/2026-04-18-parallel-ocr-outline-design.md` (new)
- `docs/superpowers/plans/2026-04-18-parallel-ocr-outline.md` (new)

Verification:

```bash
pytest tests/outline/ tests/test_cli.py --ignore=pytest-tmp -v
# 85 passed
pytest --ignore=pytest-tmp -v
# 143 passed
```

Usage:

```bash
python -m pdf_pipeline.cli -vv outline testpdfs/anatomydescripti1858gray.pdf \
  --source-id greys-anatomy \
  --ocr-tier small \
  --parallel-workers auto \
  --calibrate \
  > outputs/greys_anatomy_outline.txt 2>&1
```

---

## 2026-04-18 — Codex — Parallel OCR Implementation

Summary:

- Added Tesseract small-tier page-level parallel OCR.
- Added `pdf-extract ocr-parallel`.
- Added OCR artifact store, page result models, worker planning, calibration, and resume support.
- Added single-page PDF rendering helpers.
- Updated EasyOCR and PaddleOCR sequential paths to stream pages instead of eager-rasterizing full PDFs.
- Added README instructions and near-term docs.

Files changed:

- `.gitignore`
- `README.md`
- `pyproject.toml`
- `pdf_pipeline/cli.py`
- `pdf_pipeline/extractors/ocr_common.py`
- `pdf_pipeline/extractors/tesseract_extractor.py`
- `pdf_pipeline/extractors/easyocr_extractor.py`
- `pdf_pipeline/extractors/paddle_extractor.py`
- `pdf_pipeline/ocr_parallel/*`
- `tests/ocr_parallel/*`
- `tests/test_ocr_pipeline.py`

Verification:

```powershell
pytest tests\ocr_parallel
pytest tests\test_ocr_pipeline.py::test_easyocr_backend_with_mocks tests\test_ocr_pipeline.py::test_paddle_backend_with_mocks tests\test_ocr_pipeline.py::test_tesseract_backend_with_mocks tests\outline\test_page_text.py
python -m pdf_pipeline.cli ocr-parallel --help
python -m compileall pdf_pipeline tests\ocr_parallel
```

Results:

- `tests\ocr_parallel`: 16 passed.
- OCR backend focused tests + outline page-text tests: 13 passed.
- CLI help and compile pass succeeded.

Caveats:

- True process parallelism requires `--workers > 1`.
- This sandbox blocks Windows multiprocessing pipes, but the user's normal environment successfully processed 20 pages in under 5 seconds.
- Medium/high OCR are compatible but not truly parallelized yet.
- `--timeout-seconds` is accepted but not enforced yet.
- Cached calibration reuse is not implemented yet; runtime calibration profiles are saved.

Follow-ups:

- See `TODO.md`.

---

## 2026-04-19 - Codex - Source Document Ingestion

Summary:

- Added a real `essay_writer.sources` ingestion layer for uploaded source documents.
- Added page-aware chunking, durable JSON/JSONL artifacts, bounded source cards, and SQLite FTS chunk indexing.
- Added PDF routing behavior for full-read vs indexed sources, OCR fallback for no-text PDFs, and `FileTooLargeWithoutIndexError` when large sources cannot be indexed.
- Added source-card summarization with an LLM-backed path and deterministic fallback that stays grounded in uploaded-source excerpts.
- Ignored generated `source_store*/` artifacts.

Files changed:

- `.gitignore`
- `essay_writer/sources/__init__.py`
- `essay_writer/sources/schema.py`
- `essay_writer/sources/chunking.py`
- `essay_writer/sources/index.py`
- `essay_writer/sources/storage.py`
- `essay_writer/sources/summary.py`
- `essay_writer/sources/ingestion.py`
- `tests/sources/__init__.py`
- `tests/sources/test_chunking.py`
- `tests/sources/test_index.py`
- `tests/sources/test_ingestion.py`
- `tests/sources/test_summary.py`

Verification:

```powershell
pytest tests\sources
pytest tests\task_spec
python -m compileall essay_writer tests\sources
pytest tests\test_pypdf_extractor.py
pytest tests\test_word_doc_extractor.py
pytest tests\test_word_doc_extractor.py --basetemp=.pytest_tmp_sources_docx
```

Results:

- `tests\sources`: 7 passed.
- `tests\task_spec`: 11 passed.
- `compileall`: passed.
- `tests\test_pypdf_extractor.py`: 7 passed.
- `tests\test_word_doc_extractor.py`: blocked during pytest `tmp_path` setup by the known Windows temp-directory permission issue before assertions ran.
- DOCX rerun with repo-local `--basetemp` also hit a pytest temp-directory permission error during setup/cleanup.

Caveats:

- SQLite FTS is the first real local index; embeddings/vector search are not implemented yet.
- Default ingestion does not use web search. Source cards are based only on uploaded-source text.
- Live OCR is not exercised in default tests; OCR routing is covered with a fake extractor.

---

## 2026-04-19 - Codex - Source Index Manifest for Ideation

Summary:

- Added a complete ideation-facing source index manifest for indexed sources.
- Each manifest entry maps one indexed chunk to chunk id, ordinal, page range, char count, heading, and preview.
- Persisted `index_manifest.json` alongside SQLite FTS indexes and exposed `SourceIndexManifest.to_context()` for topic ideation context.

Files changed:

- `essay_writer/sources/__init__.py`
- `essay_writer/sources/schema.py`
- `essay_writer/sources/manifest.py`
- `essay_writer/sources/storage.py`
- `essay_writer/sources/ingestion.py`
- `tests/sources/test_manifest.py`
- `tests/sources/test_ingestion.py`

Verification:

```powershell
pytest tests\sources
python -m compileall essay_writer\sources tests\sources
```

Results:

- `tests\sources`: 8 passed.
- `compileall`: passed.

Caveats:

- The manifest is a complete chunk map, not the full chunk text. Topic ideation should use it to understand source coverage and then query the SQLite FTS index for detailed passages.

---

## 2026-04-19 - Codex - Topic Ideation Context and Retrieval

Summary:

- Added `essay_writer.topic_ideation` for source-grounded topic ideation.
- Added context assembly from `TaskSpecification`, bounded source cards, and complete `SourceIndexManifest` chunk maps.
- Added a guarded structured-output prompt/schema that asks the LLM for candidate topics, source leads, manifest chunk IDs, and suggested source-index search queries.
- Added `TopicEvidenceRetriever` for app-side retrieval: explicit chunk IDs are loaded from `SourceStore`, and suggested searches are executed against internal SQLite FTS indexes.
- Changed model-facing source manifest context to expose `source_id` as the index handle instead of filesystem index paths.

Files changed:

- `essay_writer/sources/schema.py`
- `essay_writer/topic_ideation/__init__.py`
- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/context.py`
- `essay_writer/topic_ideation/prompts.py`
- `essay_writer/topic_ideation/service.py`
- `essay_writer/topic_ideation/retrieval.py`
- `tests/topic_ideation/__init__.py`
- `tests/topic_ideation/test_context.py`
- `tests/topic_ideation/test_service.py`
- `tests/topic_ideation/test_retrieval.py`

Verification:

```powershell
pytest tests\topic_ideation
python -m compileall essay_writer\topic_ideation tests\topic_ideation
pytest tests\sources
pytest tests\task_spec
python -m compileall essay_writer tests\sources tests\topic_ideation
```

Results:

- `tests\topic_ideation`: 3 passed.
- `tests\sources`: 8 passed.
- `tests\task_spec`: 11 passed.
- Compile checks passed.

Caveats:

- Topic ideation currently requires an `LLMClient`; deterministic topic generation is not implemented.
- Retrieval is orchestrator-controlled after ideation. The model receives source IDs/chunk IDs/search-query suggestions, not direct index filesystem paths.

---

## 2026-04-19 - Codex - Clarify Topic Ideation Search Query Semantics

Summary:

- Renamed topic source-lead queries from ambiguous `suggested_search_queries` to `suggested_source_search_queries`.
- Updated the topic ideation prompt/schema to state these queries are only for uploaded-source indexes.
- Added explicit prompt language forbidding external web/database search queries in the current topic ideation stage.
- Updated retrieval and tests to use the renamed field.

Files changed:

- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/prompts.py`
- `essay_writer/topic_ideation/service.py`
- `essay_writer/topic_ideation/retrieval.py`
- `tests/topic_ideation/test_service.py`
- `tests/topic_ideation/test_retrieval.py`

Verification:

```powershell
pytest tests\topic_ideation
python -m compileall essay_writer\topic_ideation tests\topic_ideation
pytest tests\sources
python -m compileall essay_writer tests\sources tests\topic_ideation
```

Results:

- `tests\topic_ideation`: 3 passed.
- `tests\sources`: 8 passed.
- Compile checks passed.

Caveats:

- External web-search planning is intentionally not modeled yet. It should be a separate field/stage gated by explicit user or assignment permission.

---

## 2026-04-19 - Codex - Iterative Topic Ideation Inputs

Summary:

- Added iterative topic ideation support through optional `user_instruction` and compact `previous_candidates` context.
- Added `parent_topic_id` and `novelty_note` to candidate topics so new rounds can refine or distinguish earlier topics.
- Updated the topic ideation prompt/schema to avoid duplicates, follow user refinement requests, and preserve task/source constraints.
- Added tests for "more choices"/refinement behavior.
- Added `TODO.md` items for a future persisted topic ideation session/round store and explicit external research permission gate.

Files changed:

- `TODO.md`
- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/context.py`
- `essay_writer/topic_ideation/prompts.py`
- `essay_writer/topic_ideation/service.py`
- `tests/topic_ideation/test_service.py`

Verification:

```powershell
pytest tests\topic_ideation
python -m compileall essay_writer\topic_ideation tests\topic_ideation
```

Results:

- `tests\topic_ideation`: 4 passed.
- Compile check passed.

Caveats:

- Topic ideation rounds are not persisted yet. The UI/session store is tracked in `TODO.md` and should be added when the essay job flow is wired.

---

## 2026-04-19 - Codex - Essay Job and Topic Round Workflow

Summary:

- Added durable essay job state with `EssayJob`, `EssayJobStore`, and status/current-stage tracking.
- Added immutable persisted topic ideation rounds and selected topic storage.
- Added `EssayWorkflow` helpers to create jobs, record topic rounds, gather previous candidates, select a topic, and gate research planning until a topic is selected.
- Updated `TODO.md` to reflect that round/selection storage exists and remaining topic UI work is rejection/reason state.

Files changed:

- `TODO.md`
- `essay_writer/jobs/__init__.py`
- `essay_writer/jobs/schema.py`
- `essay_writer/jobs/storage.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/topic_ideation/__init__.py`
- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/storage.py`
- `tests/jobs/__init__.py`
- `tests/jobs/test_workflow.py`
- `tests/topic_ideation/test_storage.py`

Verification:

```powershell
pytest tests\jobs tests\topic_ideation tests\sources tests\task_spec
python -m compileall essay_writer tests\jobs tests\topic_ideation tests\sources
```

Results:

- Focused workflow/source/task suites: 29 passed.
- Compile check passed.

Caveats:

- Rejected topic state and rejection reasons are not modeled yet.
- The job workflow does not yet run task-spec parsing or source ingestion end-to-end; it persists and coordinates the artifacts those stages produce.

---

## 2026-04-19 - Codex - Final Topic Research

Summary:

- Added `essay_writer.research` for uploaded-source-only final topic research.
- Added `ResearchNote`, `EvidenceGroup`, `EvidenceMap`, `ResearchReport`, and `FinalTopicResearchResult` schemas.
- Added a guarded structured-output research prompt/service that extracts notes from retrieved chunks for a selected topic.
- Validates note references against retrieved chunk IDs, corrects page ranges to chunk pages, drops fabricated quotes, and removes invalid evidence-group note references.
- Added versioned `ResearchStore` for `evidence_map_vNNN.json` and `research_report_vNNN.json`.

Files changed:

- `essay_writer/research/__init__.py`
- `essay_writer/research/schema.py`
- `essay_writer/research/prompts.py`
- `essay_writer/research/service.py`
- `essay_writer/research/storage.py`
- `tests/research/__init__.py`
- `tests/research/test_schema.py`
- `tests/research/test_service.py`
- `tests/research/test_storage.py`

Verification:

```powershell
pytest tests\research
python -m compileall essay_writer\research tests\research
pytest tests\research tests\jobs tests\topic_ideation tests\sources tests\task_spec
python -m compileall essay_writer tests\research tests\jobs tests\topic_ideation tests\sources
```

Results:

- `tests\research`: 6 passed.
- Focused research/job/topic/source/task suites: 35 passed.
- Compile checks passed.

Caveats:

- This stage uses only already-retrieved uploaded-source chunks; web research is still out of scope.
- Evidence maps are ready for drafting, but the service does not yet update `EssayJob.current_stage` after research completion.

---

## 2026-04-19 - Codex - MVP Workflow Wiring and Artifact Stores

Summary:

- Added `TopicEvidenceRetriever.retrieve_for_selected_topic()` so selected topics can drive uploaded-source retrieval directly.
- Added versioned `DraftStore` and `ValidationStore`.
- Extended `EssayJob` with downstream artifact IDs and statuses for drafting, validation, and completion.
- Added `EssayWorkflow` stage updates for research completion, draft readiness, validation readiness, and validation completion.
- Added `MvpWorkflowRunner` to run selected-topic retrieval, final topic research, draft generation, validation, artifact persistence, and job-state updates.
- Added a mocked end-to-end MVP workflow test from selected topic through validation.

Files changed:

- `essay_writer/jobs/schema.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/topic_ideation/retrieval.py`
- `essay_writer/drafting/__init__.py`
- `essay_writer/drafting/storage.py`
- `essay_writer/validation/__init__.py`
- `essay_writer/validation/storage.py`
- `essay_writer/workflow/__init__.py`
- `essay_writer/workflow/mvp.py`
- `tests/jobs/test_workflow.py`
- `tests/topic_ideation/test_retrieval.py`
- `tests/drafting/test_storage.py`
- `tests/validation/test_storage.py`
- `tests/workflow/__init__.py`
- `tests/workflow/test_mvp.py`

Verification:

```powershell
pytest tests\workflow tests\jobs tests\drafting tests\validation tests\topic_ideation
python -m compileall essay_writer tests\workflow tests\jobs tests\drafting tests\validation tests\topic_ideation
pytest tests\workflow tests\drafting tests\validation tests\research tests\jobs tests\topic_ideation tests\sources tests\task_spec
python -m compileall essay_writer tests\workflow tests\drafting tests\validation tests\research tests\jobs tests\topic_ideation tests\sources
```

Results:

- Workflow/draft/validation/topic focused suite: 66 passed.
- MVP-adjacent task/source/topic/job/research/draft/validation suite: 91 passed.
- Compile checks passed.

Caveats:

- `MvpWorkflowRunner` starts after topic selection. It does not yet create jobs from pasted assignment text or uploaded files.
- Full web research, export, and UI-facing rejection/revision state remain out of scope.

---

## 2026-04-20 - Codex - MVP Bootstrap Flow

Summary:

- Added a pre-topic MVP bootstrapper that creates jobs from pasted assignment text or assignment PDF/DOCX input.
- Wired bootstrap parsing to persist `TaskSpecification` artifacts and include uploaded source IDs on the task spec.
- Wired uploaded source ingestion into job state, preserving source cards and complete index manifests for topic ideation.
- Added topic-round generation from bootstrap results, including support for user instructions and previous-candidate context.
- Added workflow helpers for attaching task specs and sources to an existing job.

Files changed:

- `essay_writer/jobs/workflow.py`
- `essay_writer/workflow/__init__.py`
- `essay_writer/workflow/bootstrap.py`
- `tests/jobs/test_workflow.py`
- `tests/workflow/test_bootstrap.py`
- `session-log.md`

Verification:

```powershell
pytest tests\workflow tests\jobs tests\sources tests\task_spec tests\topic_ideation
python -m compileall essay_writer tests\workflow tests\jobs
pytest tests\workflow tests\drafting tests\validation tests\research tests\jobs tests\topic_ideation tests\sources tests\task_spec
```

Results:

- Focused bootstrap/task/source/topic/job suite: 36 passed.
- MVP-adjacent task/source/topic/job/research/draft/validation suite: 95 passed.
- Compile checks passed.

Caveats:

- Pytest still emits the known Windows `.pytest_cache` warning; no assertions failed.
- The bootstrapper prepares job, task, source, and topic-selection artifacts. UI/session persistence remains outside this change.

---

## 2026-04-20 - Codex - Workflow Gaps Checklist

Summary:

- Added a dedicated workflow gaps checklist for the remaining end-to-end essay-writer pipeline gaps.
- Organized gaps by priority and included concrete completion criteria for future checkoffs.
- Noted that external research remains permission-gated and drafting prompt wording is product-owned separately.

Files changed:

- `docs/workflow-gaps.md`
- `session-log.md`

Verification:

- Documentation-only change; no tests run.

Caveats:

- All gap items are intentionally unchecked until corresponding implementation and tests land.

---

## 2026-04-20 - Codex - Workflow Gap Fixes Batch 1

Summary:

- Added workflow helpers for blocked/error job states and persisted error details.
- Added task-spec block resolution that writes a new task-spec version and clears the blocked state when clarification resolves blocking questions.
- Added persisted `run_selected_job()` orchestration for resuming selected jobs from stored task, topic, source, research, draft, and validation artifacts.
- Added preflight contract validation before retrieval/research/drafting/validation work.
- Added evidence sufficiency gating so no-evidence topics block before drafting.
- Added version-aware research, draft, and validation writes for resume/retry paths.
- Improved source ingestion for partial PDFs and empty indexes.
- Checked off completed items in `docs/workflow-gaps.md`.

Files changed:

- `docs/workflow-gaps.md`
- `essay_writer/jobs/workflow.py`
- `essay_writer/workflow/__init__.py`
- `essay_writer/workflow/bootstrap.py`
- `essay_writer/workflow/mvp.py`
- `essay_writer/sources/ingestion.py`
- `essay_writer/research/service.py`
- `essay_writer/research/storage.py`
- `essay_writer/drafting/service.py`
- `essay_writer/drafting/storage.py`
- `essay_writer/validation/storage.py`
- `tests/jobs/test_workflow.py`
- `tests/workflow/test_bootstrap.py`
- `tests/workflow/test_mvp.py`
- `tests/sources/test_ingestion.py`
- `session-log.md`

Verification:

```powershell
pytest tests\workflow\test_mvp.py tests\workflow\test_bootstrap.py tests\sources\test_ingestion.py tests\jobs\test_workflow.py
pytest tests\sources\test_ingestion.py
pytest tests\workflow\test_bootstrap.py tests\jobs\test_workflow.py
pytest tests\workflow\test_mvp.py
pytest tests\workflow tests\jobs tests\sources tests\task_spec tests\topic_ideation tests\research tests\drafting tests\validation
python -m compileall essay_writer tests\workflow tests\jobs tests\sources tests\research tests\drafting tests\validation
```

Results:

- Focused gap-fix suite: 23 passed.
- Source ingestion focused suite: 7 passed.
- Bootstrap/job focused suite: 13 passed.
- MVP workflow focused suite: 6 passed.
- MVP-adjacent task/source/topic/job/research/draft/validation suite: 106 passed.
- Compile checks passed.

Caveats:

- Pytest still emits the known Windows `.pytest_cache` warning; no assertions failed.
- Research planning and outline/thesis artifacts remain unchecked in `docs/workflow-gaps.md` and are the next high-priority workflow gaps.

---

## 2026-04-20 - Codex - Research Plan and Outline Artifacts

Summary:

- Added persisted `ResearchPlan` artifacts with uploaded-source priorities, source requirements, expected evidence categories, and external-search queries gated by permission.
- Added persisted `ThesisOutline` artifacts with working thesis, section plan, note IDs, and target-word guidance.
- Extended `EssayJob` to track `research_plan_id` and `outline_id`.
- Wired the MVP runner to execute topic selection -> research plan -> final topic research -> thesis outline -> draft -> validation.
- Updated draft generation to receive outline context and record `outline_id` on drafts without modifying the drafting system prompt.
- Checked off the research planning and thesis/outline high-priority items in `docs/workflow-gaps.md`.

Files changed:

- `docs/workflow-gaps.md`
- `essay_writer/jobs/schema.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/workflow/mvp.py`
- `essay_writer/drafting/schema.py`
- `essay_writer/drafting/service.py`
- `essay_writer/research_planning/__init__.py`
- `essay_writer/research_planning/schema.py`
- `essay_writer/research_planning/service.py`
- `essay_writer/research_planning/storage.py`
- `essay_writer/outlining/__init__.py`
- `essay_writer/outlining/schema.py`
- `essay_writer/outlining/service.py`
- `essay_writer/outlining/storage.py`
- `tests/workflow/test_mvp.py`
- `tests/drafting/test_service.py`
- `tests/research_planning/__init__.py`
- `tests/research_planning/test_service.py`
- `tests/research_planning/test_storage.py`
- `tests/outlining/__init__.py`
- `tests/outlining/test_service.py`
- `tests/outlining/test_storage.py`
- `session-log.md`

Verification:

```powershell
pytest tests\research_planning
pytest tests\outlining
pytest tests\drafting tests\workflow\test_mvp.py tests\research_planning tests\outlining tests\jobs
pytest tests\workflow tests\jobs tests\sources tests\task_spec tests\topic_ideation tests\research tests\research_planning tests\outlining tests\drafting tests\validation
python -m compileall essay_writer tests\workflow tests\jobs tests\sources tests\research tests\research_planning tests\outlining tests\drafting tests\validation
```

Results:

- Research planning focused suite: 5 passed.
- Outlining focused suite: 3 passed.
- Integration-focused planning/outline/drafting/workflow/jobs suite: 43 passed.
- MVP-adjacent task/source/topic/job/research/planning/outline/draft/validation suite: 115 passed.
- Compile checks passed.

Caveats:

- Research planning and outlining are deterministic structured services for now; richer LLM-backed versions can be added behind the same artifact schemas later.
- Medium-priority gaps in `docs/workflow-gaps.md` remain open.

---

## 2026-04-20 - Codex - Medium Workflow Gap Completion

Summary:

- Added rejected-topic persistence, including rejection reasons, workflow APIs, and later topic-ideation context so "more choices" can avoid rejected directions.
- Added source manifest context budgeting while preserving complete index context for small manifests and index handles for deeper lookup.
- Expanded plain-text source reading to `.txt`, `.md`, `.markdown`, and `.notes`.
- Added final Markdown export artifacts with source maps and validation summary, plus workflow completion linkage through `final_export_id`.
- Added deterministic citation metadata warnings that compare bibliography candidates against ingested source-card metadata and pass known source metadata into validation context.
- Added a failed-validation revision loop that creates draft v2, reruns validation, and exports only after a passing revision.
- Checked off all remaining items in `docs/workflow-gaps.md`.

Files changed:

- `docs/workflow-gaps.md`
- `pdf_pipeline/document_reader.py`
- `essay_writer/sources/schema.py`
- `essay_writer/topic_ideation/__init__.py`
- `essay_writer/topic_ideation/context.py`
- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/service.py`
- `essay_writer/topic_ideation/storage.py`
- `essay_writer/jobs/schema.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/workflow/bootstrap.py`
- `essay_writer/workflow/mvp.py`
- `essay_writer/drafting/__init__.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/exporting/__init__.py`
- `essay_writer/exporting/schema.py`
- `essay_writer/exporting/service.py`
- `essay_writer/exporting/storage.py`
- `essay_writer/validation/__init__.py`
- `essay_writer/validation/citations.py`
- `essay_writer/validation/schema.py`
- `essay_writer/validation/service.py`
- `essay_writer/validation/storage.py`
- `tests/test_document_reader_text.py`
- `tests/topic_ideation/test_context.py`
- `tests/topic_ideation/test_service.py`
- `tests/topic_ideation/test_storage.py`
- `tests/jobs/test_workflow.py`
- `tests/workflow/test_mvp.py`
- `tests/exporting/test_service_storage.py`
- `tests/validation/test_service.py`
- `tests/validation/test_storage.py`
- `session-log.md`

Verification:

```powershell
pytest tests\topic_ideation tests\jobs\test_workflow.py tests\test_document_reader_text.py
pytest tests\exporting tests\workflow\test_mvp.py
pytest tests\validation tests\workflow\test_mvp.py tests\exporting
pytest tests\workflow tests\jobs tests\sources tests\task_spec tests\topic_ideation tests\research tests\research_planning tests\outlining tests\drafting tests\validation tests\exporting tests\test_document_reader_text.py
python -m compileall essay_writer pdf_pipeline tests\workflow tests\jobs tests\sources tests\research tests\research_planning tests\outlining tests\drafting tests\validation tests\exporting tests\test_document_reader_text.py
```

Results:

- Topic/job/text-reader focused suite: 19 passed.
- Export/workflow focused suite: 8 passed.
- Validation/workflow/export focused suite: 44 passed.
- Broad MVP-adjacent suite: 127 passed.
- Compile checks passed.

Caveats:

- Pytest still emits the known Windows `.pytest_cache` warning; no assertions failed.
- DOCX/PDF final exports, live web/database research, and richer UI/session storage are still future product work rather than open workflow gaps in this file.

---

## 2026-04-20 - Codex - Basic Web App Continuation

Summary:

- Inspected Claude's unfinished web work and continued it into a buildable Vite/FastAPI app.
- Added backend support for source uploads across `DocumentReader` file types, assignment-file text extraction, topic rejection, external-search gating, persisted workflow runner execution, SSE stage events, and frontend static serving/env loading.
- Extended `MvpWorkflowRunner` with per-stage model config, external search propagation, and optional stage callbacks for the web pipeline.
- Updated the frontend for source/assignment setup, topic selection/rejection, pipeline start controls, validation/export viewing, and Markdown download.
- Added web install/run docs and ignored generated frontend artifacts.

Files changed:

- `.gitignore`
- `README.md`
- `pyproject.toml`
- `backend/*`
- `frontend/*`
- `essay_writer/workflow/mvp.py`
- previously-started LLM model/logging/web-search files and tests under `llm/` and `tests/llm/`
- `session-log.md`

Commands run:

```powershell
npm install
npm run build
python -m compileall backend llm essay_writer
pytest tests\llm tests\workflow\test_mvp.py tests\jobs\test_workflow.py
pytest tests\llm tests\workflow\test_mvp.py tests\jobs\test_workflow.py tests\sources tests\task_spec tests\topic_ideation tests\research tests\research_planning tests\outlining tests\drafting tests\validation tests\exporting
python -c "from backend.app import app; print(app.title)"
rg -n "[^\x00-\x7F]" backend frontend\src frontend\index.html frontend\package.json frontend\vite.config.ts frontend\tsconfig.json
npm run dev -- --host 127.0.0.1 --port 5173
```

Results:

- Frontend production build passed.
- Compile checks passed.
- Focused LLM/workflow/job suite: 56 passed.
- Broad MVP-adjacent suite: 159 passed.
- FastAPI app imports and reports `EssayWriter API`.
- Edited backend/frontend source files are ASCII-clean.
- Local API and frontend dev servers responded with HTTP 200 at `http://127.0.0.1:8000/docs` and `http://127.0.0.1:5173`.

Caveats:

- `npm install` reported 2 moderate npm audit findings in Vite-era dependencies; no automatic upgrade was applied.
- The first sandboxed Vite dev-server attempt hit an esbuild `spawn EPERM`; rerunning with approved escalation started the server.
- Pytest still emits the known Windows `.pytest_cache` warning and a Gemini SDK deprecation warning.
- Live LLM/OCR behavior was not exercised; tests used existing mocks/deterministic services.

---

## 2026-04-20 - Codex - Nonstandard Web Ports

Summary:

- Changed local web defaults from conventional Vite/FastAPI ports to nonstandard ports: API `8629`, frontend dev `3527`, Vite preview `4627`.
- Updated backend CORS allowlist, Vite proxy/server/preview config, and README run commands.

Files changed:

- `backend/app.py`
- `frontend/vite.config.ts`
- `README.md`
- `session-log.md`

Commands run:

```powershell
rg -n "8000|5173|4173|3527|4627|8629" README.md backend frontend\vite.config.ts frontend\package.json
python -m compileall backend
npm run build
```

Results:

- Backend compile check passed.
- Frontend production build passed.

Caveats:

- Servers were not started for this change, per user preference.

---

## 2026-04-20 - Codex - Source Access Layer First Pass

Summary:

- Added a source access layer with `SourceAccessConfig`, `SourceUnit`, `SourceMap`, `SourceLocator`, and `SourceTextPacket`.
- Source ingestion now builds and stores PDF page maps and section maps for Markdown/DOCX/TXT-style sources, alongside existing chunks/indexes.
- Added `SourceAccessService` to resolve PDF physical page ranges, non-PDF sections, search locators, and chunk locators into bounded source text packets.
- Added high default source-access budgets with env overrides: research rounds, packet count, total source chars, per-request/total PDF page caps, per-packet chars, and oversized-request policy.
- Topic ideation now sees source maps and can return `source_requests` while keeping `chunk_ids`/search queries backward-compatible.
- Research planning now validates selected-topic source requests against job source IDs, source maps, physical PDF page ranges, and configured bounds.
- The MVP runner resolves source packets before final research; final research treats packets as primary retrieved evidence and keeps legacy chunk retrieval as fallback.
- Outlining can now be LLM-backed when an LLM client is provided and receives source packets plus the evidence map; deterministic outline fallback remains for tests and non-LLM use.
- Added targeted tests for source maps, source access resolution, oversized request rejection, topic `source_requests`, and research-plan validation.

Files changed:

- `README.md`
- `backend/deps.py`
- `backend/routes/topics.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/outlining/service.py`
- `essay_writer/research/service.py`
- `essay_writer/research_planning/schema.py`
- `essay_writer/research_planning/service.py`
- `essay_writer/research_planning/storage.py`
- `essay_writer/sources/__init__.py`
- `essay_writer/sources/access.py`
- `essay_writer/sources/access_schema.py`
- `essay_writer/sources/ingestion.py`
- `essay_writer/sources/map.py`
- `essay_writer/sources/schema.py`
- `essay_writer/sources/storage.py`
- `essay_writer/topic_ideation/context.py`
- `essay_writer/topic_ideation/prompts.py`
- `essay_writer/topic_ideation/schema.py`
- `essay_writer/topic_ideation/service.py`
- `essay_writer/topic_ideation/storage.py`
- `essay_writer/workflow/bootstrap.py`
- `essay_writer/workflow/mvp.py`
- `tests/research_planning/test_service.py`
- `tests/sources/test_source_access.py`
- `tests/topic_ideation/test_service.py`
- `session-log.md`

Commands run:

```powershell
python -m compileall essay_writer backend tests
pytest tests\sources tests\research_planning tests\topic_ideation tests\research tests\outlining tests\workflow\test_mvp.py tests\jobs\test_workflow.py
pytest tests\llm tests\workflow tests\jobs tests\sources tests\task_spec tests\topic_ideation tests\research tests\research_planning tests\outlining tests\drafting tests\validation tests\exporting
npm run build
python -m compileall essay_writer backend tests\sources tests\research_planning tests\topic_ideation tests\research tests\outlining tests\workflow
python -c "from backend.app import app; print(app.title)"
rg -n "[^\x00-\x7F]" essay_writer\sources essay_writer\topic_ideation essay_writer\research_planning essay_writer\research essay_writer\outlining tests\sources tests\research_planning tests\topic_ideation README.md
```

Results:

- Focused source/research/outline workflow suite: 54 passed.
- Broad MVP-adjacent suite: 169 passed.
- Frontend production build passed.
- Backend app import check passed.
- New/edited source-access Python and README files are ASCII-clean.

Caveats:

- Lazy per-page OCR hooks are not implemented in `SourceAccessService` yet; current resolver uses stored page text from ingestion and returns warnings for missing pages.
- Embedding search is still deferred; retrieval uses explicit source requests, legacy chunks, and SQLite FTS fallback.
- Follow-up research rounds are configurable but not yet wired into a multi-round research loop.
- Pytest still emits the known Windows `.pytest_cache` warning and Gemini SDK deprecation warning.

---

## 2026-04-20 - Codex - README E2E Workflow Documentation

Summary:

- Added a complete end-to-end application logic section to `README.md`.
- Documented the web workflow from source ingestion and task specification through topic ideation, source access resolution, research, outlining, drafting, validation, revision, and Markdown export.
- Clarified which stages are LLM-backed, deterministic, or fallback paths, and documented current source-access limitations.

Files changed:

- `README.md`
- `session-log.md`

Commands run:

```powershell
rg -n "End-to-End Application Logic|Source Access|Final Topic Research|Current Limitations" README.md
rg -n "[^\x00-\x7F]" README.md
git diff -- README.md
```

Results:

- README now contains the full E2E application workflow.
- README ASCII scan passed.

Caveats:

- Documentation-only change; no code tests were run.

---

## 2026-04-20 - Codex - Require LLM Configuration And Direct Anti-AI Prompt

Summary:

- Replaced silent no-LLM fallbacks with `LLMConfigurationError` for task specification parsing, source-card generation, and thesis outlining.
- Removed dead deterministic fallback code for task parsing and source-card summarization.
- Added direct inclusion of the local `anti-ai-detection-SKILL.md` document in `DRAFTING_SYSTEM_PROMPT`, so drafting and revision see the full document.
- Kept structured anti-AI word/phrase lists for deterministic validation counters and wired validation checks to those shared constants.
- Updated README LLM usage and prompt inventory to describe required LLM configuration and direct anti-AI document inclusion.
- Updated tests to use `MockLLMClient` for LLM-backed stages and to assert missing task parser LLM raises.

Files changed:

- `README.md`
- `llm/client.py`
- `essay_writer/drafting/anti_ai_rules.py`
- `essay_writer/drafting/anti_ai_skill.py`
- `essay_writer/drafting/prompts.py`
- `essay_writer/outlining/service.py`
- `essay_writer/sources/summary.py`
- `essay_writer/task_spec/parser.py`
- `essay_writer/validation/checks.py`
- `essay_writer/validation/prompts.py`
- `essay_writer/validation/service.py`
- `tests/drafting/test_service.py`
- `tests/outlining/test_service.py`
- `tests/sources/test_ingestion.py`
- `tests/task_spec/test_parser.py`
- `tests/task_spec/test_storage.py`
- `tests/workflow/test_bootstrap.py`
- `tests/workflow/test_mvp.py`
- `session-log.md`

Commands run:

```powershell
python -m compileall llm essay_writer\drafting essay_writer\validation essay_writer\sources essay_writer\task_spec essay_writer\outlining
pytest tests\drafting tests\validation tests\sources\test_summary.py tests\task_spec\test_parser.py tests\outlining\test_service.py
pytest tests\task_spec\test_parser.py tests\outlining\test_service.py
python -m compileall tests\task_spec tests\outlining
pytest tests\sources tests\task_spec tests\outlining tests\workflow\test_bootstrap.py tests\workflow\test_mvp.py tests\drafting tests\validation
pytest tests\drafting tests\validation tests\sources tests\task_spec tests\outlining tests\workflow\test_bootstrap.py tests\workflow\test_mvp.py
python -m compileall llm essay_writer tests\drafting tests\validation tests\sources tests\task_spec tests\outlining tests\workflow
```

Results:

- Final focused LLM/source/workflow suite: 100 passed.
- Compile checks passed.

Caveats:

- Pytest still emits the known Windows `.pytest_cache` warning.
- The anti-AI document is loaded from the repo root at import time; missing file now raises during drafting prompt import.

---

## 2026-04-20 - Codex - Pass Source Packets To Drafting And Revision

Summary:

- Updated `DraftService.generate` to include resolved `SourceTextPacket` objects in the drafting LLM user payload.
- Updated `DraftRevisionService.revise` to include resolved source packets in the revision LLM user payload.
- Updated the MVP workflow runner to pass source packets into drafting and to re-resolve source packets for revision passes.
- Left validation unchanged; it still receives draft text, evidence notes, source-card metadata, bibliography candidates, and deterministic findings, not full excerpts.
- Updated README workflow and prompt inventory to document that drafting and revision receive source packet excerpts.
- Added tests for draft and revision source-packet payloads.

Files changed:

- `README.md`
- `essay_writer/drafting/service.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/workflow/mvp.py`
- `tests/drafting/test_service.py`
- `tests/drafting/test_revision.py`
- `session-log.md`

Commands run:

```powershell
pytest tests\drafting
python -m compileall essay_writer\drafting tests\drafting essay_writer\workflow
pytest tests\workflow\test_mvp.py tests\outlining tests\research tests\research_planning tests\drafting tests\validation
python -m compileall essay_writer tests\workflow tests\outlining tests\research tests\research_planning tests\drafting tests\validation
pytest tests\drafting tests\validation tests\sources tests\task_spec tests\outlining tests\workflow\test_bootstrap.py tests\workflow\test_mvp.py
```

Results:

- Final focused workflow/source/drafting/validation suite: 102 passed.
- Compile checks passed.

Caveats:

- Validation still does not receive full source excerpts; this is intentional for now because validation checks the draft against evidence notes and source metadata.
- Pytest still emits the known Windows `.pytest_cache` warning.

---

## 2026-04-20 - Codex - Lazy PDF Page OCR Source Access

Summary:

- Implemented lazy per-page OCR for source access when requested PDF pages are missing readable text or only have low/partial text.
- Persisted uploaded original source files into each source artifact directory so the resolver can OCR specific pages after ingestion.
- Kept PDF source map units for empty pages so physical PDF page numbers and printed labels remain traceable before lazy OCR refreshes text.
- Added source access config/env controls for lazy OCR tier, DPI, language list, and enable/disable behavior.
- Updated README workflow docs to describe stored originals and lazy page OCR behavior.

Files changed:

- `README.md`
- `essay_writer/sources/__init__.py`
- `essay_writer/sources/access.py`
- `essay_writer/sources/access_schema.py`
- `essay_writer/sources/lazy_ocr.py`
- `essay_writer/sources/map.py`
- `essay_writer/sources/storage.py`
- `tests/sources/test_source_access.py`
- `session-log.md`

Commands run:

```powershell
pytest tests\sources
python -m compileall essay_writer\sources tests\sources
pytest tests\research_planning tests\topic_ideation tests\research tests\outlining tests\workflow\test_mvp.py tests\jobs\test_workflow.py
pytest tests\sources tests\research_planning tests\workflow\test_mvp.py
python -m compileall essay_writer\sources
pytest tests\sources tests\research_planning tests\topic_ideation tests\research tests\outlining tests\workflow\test_mvp.py tests\jobs\test_workflow.py
```

Results:

- Final combined source-to-outline workflow suite: 56 passed.
- Compile checks passed for source modules.

Caveats:

- Lazy OCR requires the stored original PDF and installed OCR dependencies; sources ingested before original-file persistence may need re-ingestion.
- Lazy refresh updates page/full-text/source-map artifacts, but it does not rebuild chunk indexes or source cards yet.
- Pytest still emits the known Windows `.pytest_cache` warning.

---

## 2026-04-20 - Codex - README LLM Step And Prompt Inventory

Summary:

- Updated `README.md` with a workflow table that clearly marks which steps use an LLM, which are conditional, and which are deterministic.
- Added a prompt inventory listing each prompt family, prompt constant, user payload builder, output schema, stored version, and purpose.
- Clarified that research planning and source resolution do not call an LLM today.

Files changed:

- `README.md`
- `session-log.md`

Commands run:

```powershell
rg -n "LLM Usage By Step|Prompt Inventory|Assignment Parsing Prompt|Source Card Prompt|Topic Ideation Prompt|Final Topic Research Prompt|Outline Prompt|Drafting Prompt|Revision Prompt|Validation Prompt" README.md
rg -n "[^\x00-\x7F]" README.md
git diff -- README.md
```

Results:

- README now lists LLM usage per workflow step and documents all current prompt families.
- README ASCII scan passed.

Caveats:

- Documentation-only change; no code tests were run.

---

## 2026-04-20 - Codex - Draft And Revision Source Packet Context

Summary:

- Updated drafting and revision LLM user payloads to include resolved source packets, including source excerpts and locator metadata.
- Wired the workflow to resolve source packets for both initial draft generation and later revision runs.
- Kept validation focused on the draft, evidence map, validation notes, and source-card metadata rather than raw excerpts.
- Updated README workflow/prompt docs and added focused tests for draft/revision source packet payloads.

Files changed:

- `README.md`
- `essay_writer/drafting/service.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/workflow/mvp.py`
- `tests/drafting/test_service.py`
- `tests/drafting/test_revision.py`
- `session-log.md`

Commands run:

```powershell
pytest tests\drafting
python -m compileall essay_writer\drafting tests\drafting essay_writer\workflow
pytest tests\workflow\test_mvp.py tests\outlining tests\research tests\research_planning tests\drafting tests\validation
python -m compileall essay_writer tests\workflow tests\outlining tests\research tests\research_planning tests\drafting tests\validation
pytest tests\drafting tests\validation tests\sources tests\task_spec tests\outlining tests\workflow\test_bootstrap.py tests\workflow\test_mvp.py
```

Results:

- Final focused suite: 102 passed.
- Compile checks passed for drafting, workflow, and related test modules.

Caveats:

- Validation still does not receive full source packet text by design; it validates against evidence notes and source-card metadata.
- Pytest still emits the known Windows `.pytest_cache` warning.

---

## 2026-04-21 - Codex - Humanized Writing Pipeline Plan

Summary:

- Added a formal implementation plan for making human-sounding academic prose a pipeline-level constraint.
- Captured planned updates for the anti-AI skill document, style-aware outlining, drafting evidence scope, diagnostic-only validation, revision diagnostics, a final constrained style pass, deterministic style checks, workflow orchestration, and README updates.
- Explicitly excluded default model changes and section-by-section drafting from this plan.

Files changed:

- `docs/superpowers/plans/2026-04-21-humanized-writing-pipeline.md`
- `session-log.md`

Commands run:

```powershell
Get-ChildItem docs\superpowers\plans | Select-Object -ExpandProperty Name
Get-Content -Tail 60 session-log.md
rg -n "Humanized Writing Pipeline|Phase 1|Phase 4|Acceptance Criteria|Open Questions" docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
rg -n "[^\x00-\x7F]" docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
```

Results:

- Plan file added under active implementation plans.
- ASCII scan passed for the new plan file.

Caveats:

- Documentation-only change; no code tests were run.

---

## 2026-04-21 - Codex - Detailed Anti-AI Plan Revision

Summary:

- Revised the humanized writing pipeline plan to include exact annotated-review deltas for the anti-AI skill rewrite.
- Added explicit add/replace/move instructions for front matter, top framing, detector reality check, em dash clarification, vocabulary, sentence rhythm guardrails, paragraph pattern ordering, Rule of Three, register bleed-through, academic concrete engagement, and the seven-item self-check.
- Reviewed `updated-anti-ai-detection-SKILL.md` and recorded production concerns in the plan.

Files changed:

- `docs/superpowers/plans/2026-04-21-humanized-writing-pipeline.md`
- `session-log.md`

Files reviewed:

- `updated-anti-ai-detection-SKILL.md`
- `anti-ai-detection-SKILL.md`

Commands run:

```powershell
Get-Item updated-anti-ai-detection-SKILL.md | Format-List FullName,Length,LastWriteTime
Get-Content -Raw updated-anti-ai-detection-SKILL.md
Get-Content -Raw updated-anti-ai-detection-SKILL.md -Encoding UTF8
Get-Content -Raw docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
rg -n "Phase 1\.1|Phase 1\.13|Front Matter|Self-Check Replacement|Review Of `updated-anti-ai-detection-SKILL.md`|reader quality is secondary|U\+2014" docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
rg -n "[^\x00-\x7F]" docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
git status --short docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md updated-anti-ai-detection-SKILL.md session-log.md
```

Results:

- Plan now contains exact implementation instructions instead of broad summary bullets.
- `updated-anti-ai-detection-SKILL.md` is populated and broadly matches Claude's annotated review.
- ASCII scan passed for the plan file.

Caveats:

- Documentation-only change; no code tests were run.
- The updated skill rewrite was reviewed but not adopted over `anti-ai-detection-SKILL.md`.
- Production concerns remain around blunt detector-evasion wording, unsourced detector accuracy numbers, and literal em dash glyphs inside the prompt text.

---

## 2026-04-21 - Codex - Anti-AI Candidate Cleanup

Summary:

- Patched `updated-anti-ai-detection-SKILL.md` to resolve the review concerns from the previous session.
- Replaced blunt detector-evasion/secondary-reader-quality wording with detector-risk reduction language that still requires readable, submittable prose.
- Removed exact unsourced detector accuracy numbers from the candidate skill.
- Replaced literal em dash glyphs in the candidate skill with `U+2014` references and added an explicit UTF-8 maintainer note.
- Updated the implementation plan to reflect the resolved concerns.

Files changed:

- `updated-anti-ai-detection-SKILL.md`
- `docs/superpowers/plans/2026-04-21-humanized-writing-pipeline.md`
- `session-log.md`

Commands run:

```powershell
rg -n "reader quality|detector evasion|No detector|80%|70%|—|U\+2014|UTF-8|Encoding" updated-anti-ai-detection-SKILL.md docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
Get-Content -Raw updated-anti-ai-detection-SKILL.md -Encoding UTF8
python -c "from pathlib import Path; p=Path('updated-anti-ai-detection-SKILL.md'); text=p.read_text(encoding='utf-8'); print(len(text)); print('em_dash_present=', '\u2014' in text)"
rg -n "—|~80|70%|reader quality as a secondary goal|detector evasion first|Optimized primarily" updated-anti-ai-detection-SKILL.md docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
rg -n "[^\x00-\x7F]" docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
python -c "from pathlib import Path; text=Path('updated-anti-ai-detection-SKILL.md').read_text(encoding='utf-8'); print('chars=', len(text)); print('em_dash_present=', '\u2014' in text); print('has_exact_accuracy_numbers=', any(s in text for s in ['~80%', '70%']))"
```

Results:

- Candidate skill UTF-8 read passed.
- Candidate skill contains no literal em dash glyphs.
- Candidate skill no longer contains the exact `~80%` or `70%` detector-accuracy claims.
- Plan ASCII scan passed.

Caveats:

- Documentation-only change; no code tests were run.
- `updated-anti-ai-detection-SKILL.md` remains a candidate file and has not been copied over `anti-ai-detection-SKILL.md`.

---

## 2026-04-22 - Codex - Humanized Writing Pipeline Implementation

Summary:

- Promoted the cleaned `updated-anti-ai-detection-SKILL.md` into the active `anti-ai-detection-SKILL.md`.
- Made outlining style-aware and passed full resolved source packet text plus locator metadata, PDF page ranges, printed page labels, headings, extraction method, text quality, and warnings into the outline prompt.
- Updated drafting and revision so source packets are first-class evidence alongside the evidence map.
- Added structured validation diagnostics and expanded deterministic style checks for triplet/contrastive combos, clustered triplets, paragraph length variance, mechanical burstiness, and concrete source engagement.
- Added a constrained final style pass before validation, wired through backend dependency setup and per-stage model/token configuration.
- Updated frontend settings/types and export display for diagnostics and final style pass configuration.
- Updated README workflow and prompt documentation with the new source packet, validation, revision, style pass, and per-stage config details.

Files changed:

- `anti-ai-detection-SKILL.md`
- `README.md`
- `backend/deps.py`
- `backend/routes/export.py`
- `backend/schemas.py`
- `essay_writer/drafting/prompts.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/drafting/style_revision.py`
- `essay_writer/outlining/service.py`
- `essay_writer/validation/checks.py`
- `essay_writer/validation/prompts.py`
- `essay_writer/validation/schema.py`
- `essay_writer/validation/service.py`
- `essay_writer/validation/storage.py`
- `essay_writer/workflow/mvp.py`
- `frontend/src/components/EssayViewer.tsx`
- `frontend/src/pages/Settings.tsx`
- `frontend/src/types.ts`
- `llm/config.py`
- `tests/drafting/test_revision.py`
- `tests/drafting/test_style_revision.py`
- `tests/llm/test_config.py`
- `tests/outlining/test_service.py`
- `tests/validation/test_checks.py`
- `tests/validation/test_service.py`

Commands run:

```powershell
rg -n "Who This Skill Is For|Detector Reality Check|detector-risk|U\+2014|reader quality as a secondary|~80|70%|--" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md
Get-Content -Raw essay_writer\drafting\anti_ai_skill.py
Copy-Item -LiteralPath updated-anti-ai-detection-SKILL.md -Destination anti-ai-detection-SKILL.md
pytest tests\validation tests\drafting tests\outlining
pytest tests\workflow\test_mvp.py
python -m compileall essay_writer backend tests\validation tests\drafting tests\outlining tests\workflow
pytest tests\validation tests\drafting tests\outlining tests\workflow tests\llm\test_config.py
python -m compileall essay_writer backend llm tests\validation tests\drafting tests\outlining tests\workflow tests\llm
npm run build
git status --short
git diff --check
rg -n "reader quality as a secondary|detector evasion first|~80|70%|--" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md
rg -n "Who This Skill Is For|Detector Reality Check|U\+2014|UTF-8" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md
```

Results:

- `pytest tests\validation tests\drafting tests\outlining tests\workflow tests\llm\test_config.py`: 87 passed, 1 known pytest cache warning.
- `python -m compileall essay_writer backend llm tests\validation tests\drafting tests\outlining tests\workflow tests\llm`: passed.
- `npm run build` in `frontend`: passed.
- `git diff --check`: no whitespace errors, only CRLF normalization warnings.
- Active and candidate anti-AI skill files contain the new framing, U+2014 wording, and UTF-8 note, with no old detector-evasion wording or exact detector accuracy numbers found.
- Fixed an intermediate circular import from exporting `FinalStyleRevisionService` in `essay_writer/drafting/__init__.py`.
- Fixed an intermediate workflow failure by adding the missing outlining model override to `StageModelConfig`, backend settings, frontend types/settings, and config tests.

Caveats:

- The final style pass is wired by the backend but remains optional at the runner level for tests and alternate wiring.
- The style pass runs before validation so validation and export refer to the same stored draft version.
- Pytest still emits the known Windows `.pytest_cache` warning in this environment.

---

## 2026-04-22 - Codex - Default Model Setting Fix

Summary:

- Fixed backend model resolution so the Settings page `llm_model` default is actually used for every LLM stage when no per-stage override is set.
- Preserved the intended priority order: per-stage Settings override, per-stage env var, Settings default model, `LLM_MODEL`, adapter default.
- Added regression tests for default-model and per-stage model priority.
- Updated README model configuration docs to match the resolver order.

Files changed:

- `backend/deps.py`
- `README.md`
- `tests/llm/test_backend_model_config.py`
- `session-log.md`

Commands run:

```powershell
rg -n "llm_model|LLM_MODEL|ESSAY_MODEL_|_model_config_from_settings|StageModelConfig" backend llm frontend tests README.md
pytest tests\llm\test_config.py tests\llm\test_backend_model_config.py
pytest tests\workflow\test_mvp.py
python -m compileall backend llm tests\llm tests\workflow
```

Results:

- Model config tests: 9 passed, 1 known pytest cache warning.
- Workflow MVP tests: 7 passed, 1 known pytest cache warning.
- Compile check passed.

Caveats:

- No frontend rebuild was run because this follow-up only changed backend model resolution, README, and Python tests.

---

## 2026-04-22 - Codex - Dash And Colon Punctuation Checks

Summary:

- Updated active and candidate anti-AI skill files to avoid en dashes, decorative hyphen pauses, and colon-heavy explanation patterns in generated prose.
- Replaced the prior guidance that allowed en dashes, hyphens, and colons with stricter generated-prose rules and narrow exceptions for required spellings, source titles, URLs, citations, time stamps, ratios, and technical terms.
- Added deterministic validation checks for en dash count, decorative hyphen pause count, and colon explanation pattern count.
- Passed the new punctuation findings into validation and the final style pass payloads.
- Made validation fail when these disallowed punctuation patterns are present.
- Updated README deterministic check documentation and validation tests.

Files changed:

- `anti-ai-detection-SKILL.md`
- `updated-anti-ai-detection-SKILL.md`
- `essay_writer/validation/checks.py`
- `essay_writer/validation/schema.py`
- `essay_writer/validation/service.py`
- `essay_writer/validation/prompts.py`
- `essay_writer/drafting/style_revision.py`
- `tests/validation/test_checks.py`
- `tests/validation/test_service.py`
- `README.md`
- `session-log.md`

Commands run:

```powershell
rg -n "Em dashes|En dashes|hyphens|colon|Dramatic pause|Parenthetical aside|Setting off a list|SELF-CHECK" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md
pytest tests\validation
python -m compileall essay_writer\validation essay_writer\drafting tests\validation
rg -n "DASH AND COLON|colon-heavy|decorative hyphen|label: explanation|Introducing an explanation" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md essay_writer\validation tests\validation README.md
git diff --check
git status --short anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md essay_writer\validation\checks.py essay_writer\validation\schema.py essay_writer\validation\service.py essay_writer\validation\prompts.py essay_writer\drafting\style_revision.py tests\validation\test_checks.py tests\validation\test_service.py README.md session-log.md
```

Results:

- Validation tests: 48 passed, 1 known pytest cache warning.
- Compile check passed.
- `git diff --check`: no whitespace errors, only CRLF normalization warnings.

Caveats:

- Hyphenated standard words and required source or citation text are not blocked. Only decorative hyphen pauses are counted.

---

## 2026-04-26 - Codex - Anti-AI Fragment Chain Guard

Summary:

- Tightened the anti-AI skill so it explicitly bans stacked clipped mini-sentences used as fake emphasis.
- Added matching drafting and style-revision prompt instructions so the model prefers normal prose over "X. It can Y. It cannot Z." chains.
- Extended the deterministic mechanical-burstiness check to catch consecutive ultra-short declarative runs, not just a single short sentence between long ones.
- Added focused validation tests for the new clipped-fragment heuristic and a clean short-pair case.
- Updated README validation notes to document that mechanical burstiness now includes clipped fragment chains.

Files changed:

- `anti-ai-detection-SKILL.md`
- `updated-anti-ai-detection-SKILL.md`
- `essay_writer/drafting/prompts.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/drafting/style_revision.py`
- `essay_writer/validation/checks.py`
- `tests/validation/test_checks.py`
- `README.md`
- `session-log.md`

Commands run:

```powershell
pytest tests\validation\test_checks.py
python -m compileall essay_writer\validation essay_writer\drafting tests\validation
@'
from essay_writer.drafting.anti_ai_skill import ANTI_AI_SKILL_DOCUMENT
print(len(ANTI_AI_SKILL_DOCUMENT))
'@ | python -
git diff -- anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md essay_writer/drafting/prompts.py essay_writer/drafting/style_revision.py essay_writer/drafting/revision.py essay_writer/validation/checks.py tests/validation/test_checks.py README.md
git status --short
```

Results:

- `tests\validation\test_checks.py`: 33 passed, 1 known pytest cache warning.
- Compile check passed.
- Anti-AI skill document loaded successfully through `essay_writer.drafting.anti_ai_skill`.

Caveats:

- The new clipped-fragment heuristic is intentionally narrow: it targets consecutive ultra-short declarative runs and still allows isolated short landing sentences that are not chained together.

---

## 2026-04-26 - Codex - Direct Core Prose Standard Added

Summary:

- Added the requested plain-prose guidance directly near the top of both anti-AI skill files.
- Kept the live and candidate skill files in sync so the active drafting prompt and the updated reference file carry the same wording.

Files changed:

- `anti-ai-detection-SKILL.md`
- `updated-anti-ai-detection-SKILL.md`
- `session-log.md`

Commands run:

```powershell
rg -n "Core Prose Standard|Write in plain, specific academic prose|What helps most|Avoid staged rhetorical templates" anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md
Get-Content anti-ai-detection-SKILL.md | Select-Object -First 40
```

Results:

- Verified the new `Core Prose Standard` block appears near the top of both skill files.

Caveats:

- No automated tests were needed or run for this wording-only update.

---

## 2026-04-28 - Codex - Anti-Overcorrection Skill Update

Summary:

- Expanded the anti-AI skill to warn against over-correcting into chopped prose.
- Added new `Over-Chopping` and `Stacked Mini-Sentence Endings` subsections under `SENTENCE STRUCTURE`.
- Strengthened the `Anti-mechanical guard` and `Voice Calibration` sections so user voice overrides generic burstiness targets when the user's samples favor longer, conjunction-heavy sentences.
- Added `Preserve Informal Academic Tics` under `TONE AND VOICE` with an explicit preserve-don't-invent rule.
- Did not recreate `updated-anti-ai-detection-SKILL.md` because it is not present in the current worktree.

Files changed:

- `anti-ai-detection-SKILL.md`
- `session-log.md`

Commands run:

```powershell
Get-ChildItem anti-ai-detection-SKILL.md,updated-anti-ai-detection-SKILL.md -ErrorAction SilentlyContinue | Select-Object Name,Length,LastWriteTime
Get-Content anti-ai-detection-SKILL.md | Select-Object -Skip 108 -First 220
```

Results:

- Verified the active skill file exists and the candidate `updated-anti-ai-detection-SKILL.md` file is absent in this checkout.

Caveats:

- No automated tests were needed or run because this update only changes prompt guidance text.

---

## 2026-04-26 - Codex - Reordered Additional Anti-AI Skill Points

Summary:

- Reordered the loose `updated-anti-ai-detection-SKILL.md` tail notes into a deliberate sequence: voice calibration first, then wording-level edits, then sentence-pattern tells, then source specificity, then conclusion checks.
- Replaced the temporary `NEW POINTS: NEED TO REORDER` marker with a titled section and normalized the subsection headings for readability.

Files changed:

- `updated-anti-ai-detection-SKILL.md`
- `session-log.md`

Commands run:

```powershell
rg -n "NEW POINTS|NEED TO REORDER|^#|^##|^- " updated-anti-ai-detection-SKILL.md
Get-Content updated-anti-ai-detection-SKILL.md -Tail 70
```

Results:

- The appended anti-AI guidance now reads as an ordered editing pass instead of an unordered note dump.

Caveats:

- This change only reorganized the draft `updated-anti-ai-detection-SKILL.md`; it did not sync the live `anti-ai-detection-SKILL.md`.
- No automated tests were needed or run for this wording-only update.

---

## 2026-04-27 - Codex - Added Standalone Writing Style Sample Subsystem

Summary:

- Added a new standalone `essay_writer.writing_style` package for optional human writing samples, without wiring it into the essay workflow yet.
- Implemented sample metadata schemas, deterministic sample-text normalization, sample/content stores, a sample ingestion service, and an LLM-backed `WritingStyleContentService`.
- Added prompt helpers for both style-content generation and future drafting-stage injection, including a prompt block that passes the distilled style guidance and the full cleaned sample texts while explicitly marking them as tone/style exemplars only.
- Added focused tests for normalization and prompt-block behavior.

Files changed:

- `essay_writer/writing_style/__init__.py`
- `essay_writer/writing_style/schema.py`
- `essay_writer/writing_style/normalizer.py`
- `essay_writer/writing_style/storage.py`
- `essay_writer/writing_style/ingestion.py`
- `essay_writer/writing_style/prompts.py`
- `essay_writer/writing_style/service.py`
- `tests/writing_style/test_normalizer.py`
- `tests/writing_style/test_prompts.py`
- `session-log.md`

Commands run:

```powershell
pytest tests\writing_style
python -m compileall essay_writer\writing_style tests\writing_style
git diff --check
git status --short
```

Results:

- `tests\writing_style`: 5 passed.
- Compile check passed for the new writing-style package and tests.
- `git diff --check` passed.

Caveats:

- The new writing-style subsystem is intentionally not connected to the current workflow, API routes, or UI selection flow yet.
- Model selection for style-content generation is currently handled via `ESSAY_MODEL_WRITING_STYLE` and `ESSAY_MAX_TOKENS_WRITING_STYLE` in the standalone service layer rather than the app-wide settings UI.

---

## 2026-04-27 - Codex - Wired Writing Style Into Drafting/Revision and Added Parallel Tone Alignment

Summary:

- Threaded optional `WritingStylePayload` support through drafting, revision, and the final style pass so prompts can receive both the distilled style content and full cleaned human samples.
- Added a standalone `essay_writer.tone_alignment` package and integrated it into the MVP workflow as a separate branch that runs in parallel with core validation.
- Changed workflow gating so revision can be triggered by either failed core validation or failed tone alignment, and ensured revision receives both reports together.
- Reworked validation semantics so deterministic anti-AI checks are no longer hard pass/fail blockers; they remain diagnostic signals while tone alignment resolves conflicts in favor of authentic user voice.
- Wired persisted writing-style and tone-alignment state through job/workflow storage and runner dependencies without exposing it in the UI yet.
- Added focused tests covering writing-style prompt injection, validation semantics, and the tone-driven revision loop with parallel validation/tone execution.

Files changed:

- `essay_writer/tone_alignment/__init__.py`
- `essay_writer/tone_alignment/schema.py`
- `essay_writer/tone_alignment/prompts.py`
- `essay_writer/tone_alignment/service.py`
- `essay_writer/tone_alignment/storage.py`
- `essay_writer/drafting/prompts.py`
- `essay_writer/drafting/service.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/drafting/style_revision.py`
- `essay_writer/jobs/schema.py`
- `essay_writer/jobs/workflow.py`
- `essay_writer/validation/prompts.py`
- `essay_writer/validation/schema.py`
- `essay_writer/workflow/mvp.py`
- `backend/deps.py`
- `backend/routes/pipeline.py`
- `tests/drafting/test_service.py`
- `tests/drafting/test_revision.py`
- `tests/drafting/test_style_revision.py`
- `tests/validation/test_service.py`
- `tests/workflow/test_mvp.py`
- `session-log.md`

Commands run:

```powershell
python -m compileall essay_writer backend tests\drafting tests\validation tests\workflow
pytest tests\drafting\test_service.py tests\drafting\test_revision.py tests\drafting\test_style_revision.py tests\validation\test_service.py tests\workflow\test_mvp.py tests\jobs\test_workflow.py
pytest tests\writing_style tests\validation\test_storage.py
python -m compileall essay_writer\tone_alignment
git diff --check
git status --short
```

Results:

- Focused drafting, validation, workflow, and jobs suite: 57 passed.
- Writing-style plus validation storage suite: 8 passed.
- Compile checks passed for the updated workflow and new tone-alignment package.

Caveats:

- Writing-style sample selection remains optional and is still not exposed in the UI/API flow yet; the runner only consumes it when a payload or persisted sample/content IDs are available.
- Tone alignment model selection currently uses environment variables (`ESSAY_MODEL_TONE_ALIGNMENT`, `ESSAY_MAX_TOKENS_TONE_ALIGNMENT`) rather than app settings.
- API/export responses do not yet expose tone-alignment summaries separately; only workflow control now uses them.

---

## 2026-04-27 - Codex - Promoted Updated Anti-AI Skill and Archived Prior Version

Summary:

- Moved the previous active `anti-ai-detection-SKILL.md` into a new local-only `legacy_skills/` folder.
- Added `legacy_skills/` to `.gitignore` so archived skill variants can stay in the workspace without being tracked.
- Renamed the newer candidate skill file into the active root `anti-ai-detection-SKILL.md` path, which makes the drafting/style prompt loader use it immediately with no code-path change.
- Patched the humanized-writing pipeline plan doc so it no longer references the removed `updated-anti-ai-detection-SKILL.md` path.

Files changed:

- `.gitignore`
- `anti-ai-detection-SKILL.md`
- `docs/superpowers/plans/2026-04-21-humanized-writing-pipeline.md`
- `session-log.md`

Commands run:

```powershell
rg -n "updated-anti-ai-detection-SKILL\.md" README.md docs essay_writer tests backend
New-Item -ItemType Directory -Force legacy_skills
Move-Item -LiteralPath anti-ai-detection-SKILL.md -Destination legacy_skills\anti-ai-detection-SKILL.md
Move-Item -LiteralPath updated-anti-ai-detection-SKILL.md -Destination anti-ai-detection-SKILL.md
@'
from essay_writer.drafting.anti_ai_skill import ANTI_AI_SKILL_DOCUMENT
print(len(ANTI_AI_SKILL_DOCUMENT))
print(ANTI_AI_SKILL_DOCUMENT.splitlines()[0])
'@ | python -
git status --short anti-ai-detection-SKILL.md updated-anti-ai-detection-SKILL.md .gitignore docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
```

Results:

- `essay_writer.drafting.anti_ai_skill` now loads the promoted root skill document successfully.
- The previous root skill file is preserved locally at `legacy_skills\anti-ai-detection-SKILL.md`.
- No live repo references to `updated-anti-ai-detection-SKILL.md` remain outside session history.

Caveats:

- `updated-anti-ai-detection-SKILL.md` is removed from the tracked workspace path; the only preserved old version is the local ignored archive under `legacy_skills/`.

---

## 2026-04-27 - Codex - Added Writing Sample Library APIs and Frontend Selection UI

Summary:

- Added backend writing-sample library support with list and upload routes, plus auto-import of any files already present under `data/human_samples` so previously added samples appear in the UI immediately.
- Extended job creation to accept optional `writing_style_sample_ids`, resolve or generate cached `WritingStyleContent`, and attach the resulting style context to the job before the workflow runs.
- Updated the new-job frontend to fetch existing writing samples on load, let users upload more, select any subset for the job, and submit that selection along with the assignment and sources.
- Updated the pipeline frontend to show the new `tone_alignment` stage and to handle completion without an export more cleanly when another revision is still required.

Files changed:

- `backend/app.py`
- `backend/deps.py`
- `backend/routes/jobs.py`
- `backend/routes/writing_style.py`
- `backend/schemas.py`
- `backend/writing_style_support.py`
- `essay_writer/writing_style/service.py`
- `frontend/src/api.ts`
- `frontend/src/components/WritingSamplePicker.tsx`
- `frontend/src/pages/NewJob.tsx`
- `frontend/src/pages/PipelineView.tsx`
- `frontend/src/styles.css`
- `frontend/src/types.ts`
- `session-log.md`

Commands run:

```powershell
python -m compileall backend essay_writer\writing_style backend\routes frontend\src
pytest tests\writing_style tests\validation\test_service.py tests\workflow\test_mvp.py tests\jobs\test_workflow.py
npm run build
git diff --check
git status --short
```

Results:

- Backend and writing-style modules compiled successfully.
- Focused Python suite: 37 passed.
- Frontend production build passed with the new sample picker and tone stage UI.

Caveats:

- The frontend currently supports writing-sample selection at job creation time only; there is not yet a separate post-creation edit flow for changing the sample set on an existing job.
- Export/API payloads still do not surface a detailed tone-alignment report; the UI currently reflects tone alignment mainly through stage progression and revision gating.

---

## 2026-04-28 - Codex - Drafted Manual Reiteration And Draft History Plan

Summary:

- Wrote a review-first implementation plan for post-export editing, immutable draft/export history, saved user edits, and a manual reiteration loop with selectable lenses.
- The plan recommends keeping manual reiteration separate from the main job state machine and modeling it as versioned draft artifacts plus stored manual request/run artifacts.
- Captured API, storage, workflow, frontend, rollout, and acceptance-criteria details so implementation can begin cleanly after approval.

Files changed:

- `docs/superpowers/plans/2026-04-28-manual-reiteration-and-draft-history.md`
- `session-log.md`

Commands run:

```powershell
Get-ChildItem docs\superpowers\plans | Select-Object Name
Get-Content docs\superpowers\plans\2026-04-21-humanized-writing-pipeline.md
Get-ChildItem docs\superpowers\specs | Select-Object Name
Get-Content session-log.md -Tail 80
```

Results:

- Added a detailed draft plan for review before any code changes.
- No implementation code was changed and no tests were run.

Caveats:

- The plan includes open product questions around autosave, default lenses, and whether review-only should ship before manual revise.

---

## 2026-04-28 - Codex - Implemented Draft History, Saved User Edits, and Manual Reiteration

Summary:

- Added immutable draft provenance fields and history helpers so drafts can now be labeled and reopened as generated, style-pass, system-revision, user-edit, or manual-LLM-revision artifacts.
- Added a dedicated `essay_writer/manual_revision` subsystem with request/run storage plus a manual reiteration service that saves user edits, runs selected review lenses, stores the outputs, and optionally creates a new revised draft version.
- Fixed export handling so export routes now return real persisted export artifacts linked to their underlying draft content instead of treating the latest draft as the export.
- Added backend routes for draft history, export history/detail, saving user edits, and stored manual review/revise runs.
- Reworked the pipeline frontend into an artifact workspace with draft history, export history, a saved draft editor, selectable manual-review lenses, and stored run detail panels.

Files changed:

- `backend/app.py`
- `backend/deps.py`
- `backend/routes/drafts.py`
- `backend/routes/export.py`
- `backend/routes/jobs.py`
- `backend/schemas.py`
- `essay_writer/drafting/revision.py`
- `essay_writer/drafting/schema.py`
- `essay_writer/drafting/service.py`
- `essay_writer/drafting/storage.py`
- `essay_writer/drafting/style_revision.py`
- `essay_writer/exporting/storage.py`
- `essay_writer/manual_revision/__init__.py`
- `essay_writer/manual_revision/schema.py`
- `essay_writer/manual_revision/service.py`
- `essay_writer/manual_revision/storage.py`
- `frontend/src/api.ts`
- `frontend/src/components/EssayViewer.tsx`
- `frontend/src/pages/PipelineView.tsx`
- `frontend/src/styles.css`
- `frontend/src/types.ts`
- `tests/drafting/test_storage.py`
- `tests/exporting/test_service_storage.py`
- `tests/manual_revision/test_service.py`
- `tests/manual_revision/test_storage.py`
- `session-log.md`

Commands run:

```powershell
python -m compileall backend essay_writer\manual_revision essay_writer\drafting essay_writer\exporting
pytest tests\manual_revision tests\drafting\test_storage.py tests\exporting\test_service_storage.py tests\workflow\test_mvp.py tests\jobs\test_workflow.py
python -m compileall backend essay_writer frontend\src tests\manual_revision
npm run build
git diff --check
```

Results:

- Focused Python suite: 28 passed.
- Backend/manual-revision/frontend source trees compiled successfully.
- Frontend production build passed.
- `git diff --check` passed without patch-format issues.

Caveats:

- Manual review outputs are intentionally stored in dedicated manual-run artifacts rather than the main validation/tone stores, so the automatic workflow's latest-report assumptions stay intact.
- Manual user-edit and manual-revision drafts are persisted and reopenable from history, but they do not currently replace the job's primary pipeline draft/export pointers.
- The editor flow is explicit-save rather than autosave in this first implementation.

---

## 2026-05-09 - Codex - Documented Agent Harness MCP Plan

Summary:

- Rewrote `docs/agent-harness-implementation.md` from pasted chat notes into a structured MCP Agent Tool Mode implementation plan.
- Added the source-ingestion architecture: deterministic no-API materialization first, followed by harness-owned `prepare_source_card` / `commit_source_card`.
- Clarified that the frontend is optional for Agent Tool Mode v1 and that local-path MCP ingestion should be built first.
- Added tool categories, work packet shape, no-implicit-API enforcement, implementation phases, risks, and open decisions.

Files changed:

- `docs/agent-harness-implementation.md`
- `session-log.md`

Commands run:

```powershell
rg --files -g "*agent*"
Get-ChildItem -Force docs
git status --short
Get-Content docs\agent-harness-implementation.md
Get-Content essay_writer\sources\summary.py
Get-Content essay_writer\sources\schema.py
Get-Content essay_writer\sources\storage.py
git diff -- docs\agent-harness-implementation.md
```

Results:

- Documentation-only update.
- No tests were run because no implementation code changed.

Caveats:

- The worktree already contained unrelated modified and untracked files before this session.
- `docs/agent-harness-implementation.md` is currently untracked in git.

---

## 2026-05-09 - Codex - Added Subagent Strategy To Agent Harness Plan

Summary:

- Added a subagent strategy section to `docs/agent-harness-implementation.md`.
- Documented that subagent spawning should be a harness policy, not enforced by the MCP server.
- Added delegation metadata to the work packet shape, including `recommended`, `suggested_role`, `allowed_tools`, `return_contract`, and `subagent_prompt`.
- Listed good subagent stages: source cards, deep source reading, web research, topic feasibility, and validation/review lenses.
- Added poor-fit stages, read-only versus bounded-write subagent guidance, implementation hooks, risks, and open decisions.

Files changed:

- `docs/agent-harness-implementation.md`
- `session-log.md`

Commands run:

```powershell
Get-Content C:\Users\Apoorv\.codex\plugins\cache\openai-curated\superpowers\3c463363\skills\brainstorming\SKILL.md
Select-String -Path docs\agent-harness-implementation.md -Pattern "Work Packets|Serial Workflow|Implementation Phases|Risks" -Context 0,4
Get-Content docs\agent-harness-implementation.md
Get-Content session-log.md -Tail 55
Select-String -Path docs\agent-harness-implementation.md -Pattern "Subagent Strategy|Should Subagents Be Enforced|Good Subagent Stages|How To Tell" -Context 0,6
git diff -- docs\agent-harness-implementation.md
git diff --check -- docs\agent-harness-implementation.md
```

Results:

- Documentation-only update.
- `git diff --check -- docs\agent-harness-implementation.md` completed without whitespace errors.
- No tests were run because no implementation code changed.

Caveats:

- `docs/agent-harness-implementation.md` remains untracked in git.

## 2026-05-09 - Codex - Planned Agent Work Handoff Storage

Summary:

- Added AgentWorkStore planning to `docs/agent-harness-implementation.md`.
- Specified that every `prepare_*` tool should persist a work packet and return `work_packet_id`.
- Specified that subagent outputs should be stored as `WorkResult` artifacts, not arbitrary JSON files invented by subagents.
- Added `submit_work_result`, work packet/result list/get tools, commit links, and recovery flow.
- Clarified that the harness orchestrator should follow returned IDs instead of scanning folders or relying on chat transcript state.

Files changed:

- `docs/agent-harness-implementation.md`
- `session-log.md`

Commands run:

```powershell
Get-Content C:\Users\Apoorv\.codex\plugins\cache\openai-curated\superpowers\3c463363\skills\brainstorming\SKILL.md
Select-String -Path docs\agent-harness-implementation.md -Pattern "## Subagent Strategy|## Commit Validation|## Work Packets|## Implementation Phases|## Open Decisions" -Context 0,2
Get-Content docs\agent-harness-implementation.md -TotalCount 560 | Select-Object -Last 280
Select-String -Path docs\agent-harness-implementation.md -Pattern "Work Packet Persistence|Work Result Store|How The Orchestrator Finds Outputs|Lost Handoff State|AgentWorkStore" -Context 0,8
git diff -- docs\agent-harness-implementation.md
git diff --check -- docs\agent-harness-implementation.md
```

Results:

- Documentation-only update.
- `git diff --check -- docs\agent-harness-implementation.md` completed without whitespace errors.
- No tests were run because no implementation code changed.

Caveats:

- `docs/agent-harness-implementation.md` remains untracked in git.

---

## 2026-05-09 - Codex - Planned Context-Compaction Recovery For Agent Harness

Summary:

- Added `AgentRunStore` planning to `docs/agent-harness-implementation.md`.
- Added run-level recovery protocol for context compaction, interruption, and resume.
- Added `start_agent_run`, `get_agent_run_state`, `recover_agent_run`, `list_agent_runs`, and `checkpoint_agent_run` tool planning.
- Documented checkpoints, idempotency rules, lightweight leases for parallel subagent work, and human-approval recovery through `blocked_on`.
- Clarified that persisted run state should be authoritative and chat memory should be advisory.

Files changed:

- `docs/agent-harness-implementation.md`
- `session-log.md`

Commands run:

```powershell
Get-Content C:\Users\Apoorv\.codex\plugins\cache\openai-curated\superpowers\3c463363\skills\brainstorming\SKILL.md
Select-String -Path docs\agent-harness-implementation.md -Pattern "Work Packet Persistence|How The Orchestrator Finds Outputs|No-Implicit-API Enforcement|Implementation Phases|Risks|Open Decisions" -Context 0,3
Get-Content docs\agent-harness-implementation.md -TotalCount 720 | Select-Object -Last 220
Select-String -Path docs\agent-harness-implementation.md -Pattern "Agent Run Recovery|AgentRunStore|Recovery Protocol|Checkpointing|Idempotency|Leases|Human Approval Recovery|Lost Run State" -Context 0,6
git diff -- docs\agent-harness-implementation.md
git diff --check -- docs\agent-harness-implementation.md
```

Results:

- Documentation-only update.
- `git diff --check -- docs\agent-harness-implementation.md` completed without whitespace errors.
- No tests were run because no implementation code changed.

Caveats:

- `docs/agent-harness-implementation.md` remains untracked in git.

---

## 2026-05-09 - Codex - Planned Harness Instructions And LLM Isolation

Summary:

- Added a General Harness Instruction Prompt section to `docs/agent-harness-implementation.md`.
- Planned `docs/agent-tool-mode-instructions.md`, `get_harness_instructions`, and MCP prompt `essay_agent_tool_mode`.
- Documented that existing prompt instructions and JSON schemas should be reused in prepare packets rather than rewritten wholesale.
- Strengthened no-hidden-API enforcement with import-boundary checks, runtime `LLMClient.chat_json` guards, and explicit separation from API-backed Pipeline Mode tools.
- Added open decisions covering the need for a separate implementation spec, prompt/schema reuse, and harness instruction delivery.

Files changed:

- `docs/agent-harness-implementation.md`
- `session-log.md`

Commands run:

```powershell
Get-Content C:\Users\Apoorv\.codex\plugins\cache\openai-curated\superpowers\3c463363\skills\brainstorming\SKILL.md
Select-String -Path docs\agent-harness-implementation.md -Pattern "No-Implicit-API Enforcement|MCP Prompts|Implementation Phases|Open Decisions|Recommended First Vertical Slice" -Context 0,8
Get-Content docs\agent-harness-implementation.md -TotalCount 980 | Select-Object -Last 260
Select-String -Path docs\agent-harness-implementation.md -Pattern "General Harness Instruction Prompt|Prompt And Schema Reuse|No-Implicit-API Enforcement|implementation spec|agent-tool-mode-instructions|get_harness_instructions" -Context 0,8
git diff -- docs\agent-harness-implementation.md
git diff --check -- docs\agent-harness-implementation.md
```

Results:

- Documentation-only update.
- `git diff --check -- docs\agent-harness-implementation.md` completed without whitespace errors.
- No tests were run because no implementation code changed.

Caveats:

- `docs/agent-harness-implementation.md` remains untracked in git.

---

## 2026-05-09 - Codex - Created Agent Tool Mode MCP Implementation Plan

Summary:

- Created a separate Superpowers implementation plan for Agent Tool Mode MCP work.
- Planned file-level tasks for agent tool schemas, run/work stores, no-API source materialization, prepare/submit/commit cycles, recovery, subagent metadata, MCP server wrapping, docs, and tests.
- Captured no-hidden-API enforcement through import-boundary checks and runtime `LLMClient.chat_json` guard tests.
- Included source-ingestion, source-packet bundle storage, context-compaction recovery, and work-result handoff details.

Files changed:

- `docs/superpowers/plans/2026-05-09-agent-tool-mode-mcp-implementation.md`
- `session-log.md`

Commands run:

```powershell
Get-Content C:\Users\Apoorv\.codex\plugins\cache\openai-curated\superpowers\3c463363\skills\writing-plans\SKILL.md
Get-Content docs\agent-harness-implementation.md
Get-ChildItem -Recurse -File essay_writer | Select-Object -ExpandProperty FullName
Get-Content pyproject.toml
rg -n "class |def |chat_json|SourceIngestionService|build_source_card|SOURCE_CARD|RESPONSE_SCHEMA|PROMPT|schema" essay_writer\sources essay_writer\task_spec essay_writer\topic_ideation essay_writer\research essay_writer\research_planning essay_writer\outlining essay_writer\drafting essay_writer\validation essay_writer\jobs essay_writer\exporting essay_writer\manual_revision essay_writer\workflow
Get-Content essay_writer\sources\ingestion.py
Get-Content essay_writer\sources\storage.py
Get-Content essay_writer\sources\summary.py
Get-Content essay_writer\task_spec\parser.py
Get-Content essay_writer\task_spec\prompts.py
Get-Content essay_writer\task_spec\schema.py
Get-Content essay_writer\task_spec\storage.py
Get-Content essay_writer\task_spec\security.py
Get-Content essay_writer\topic_ideation\service.py
Get-Content essay_writer\topic_ideation\prompts.py
Get-Content essay_writer\topic_ideation\schema.py
Get-Content essay_writer\topic_ideation\context.py
Get-Content essay_writer\topic_ideation\storage.py
Get-Content essay_writer\research_planning\service.py
Get-Content essay_writer\research_planning\schema.py
Get-Content essay_writer\research\service.py
Get-Content essay_writer\research\prompts.py
Get-Content essay_writer\research\schema.py
Get-Content essay_writer\research\storage.py
Get-Content essay_writer\research_planning\storage.py
Get-Content essay_writer\outlining\service.py
Get-Content essay_writer\outlining\storage.py
Get-Content essay_writer\outlining\schema.py
Get-Content essay_writer\drafting\service.py
Get-Content essay_writer\drafting\prompts.py
Get-Content essay_writer\drafting\schema.py
Get-Content essay_writer\drafting\storage.py
Get-Content essay_writer\drafting\revision.py
Get-Content essay_writer\validation\service.py
Get-Content essay_writer\validation\prompts.py
Get-Content essay_writer\validation\schema.py
Get-Content essay_writer\validation\checks.py
Get-Content essay_writer\validation\storage.py
Get-Content essay_writer\jobs\schema.py
Get-Content essay_writer\jobs\storage.py
Get-Content essay_writer\jobs\workflow.py
Get-Content essay_writer\exporting\service.py
Get-Content essay_writer\sources\access.py
Get-Content backend\deps.py
Get-ChildItem -Recurse -File llm | Select-Object -ExpandProperty FullName
Get-Content llm\client.py
Get-Content llm\factory.py
Get-Content llm\logging_client.py
Get-ChildItem -Recurse -File tests | Select-Object -ExpandProperty FullName
Get-Content session-log.md
Get-Content README.md
Get-ChildItem -Force docs\superpowers\plans | Select-Object Name,Length,LastWriteTime
Get-Content tests\task_spec\_tmp.py
Get-Content tests\sources\test_ingestion.py
Get-Content tests\sources\test_summary.py
Get-Content tests\workflow\test_bootstrap.py
Get-Content essay_writer\sources\schema.py
Get-Content essay_writer\exporting\storage.py
Get-Content essay_writer\exporting\schema.py
git status --short
rg -n "mcp|MCP|agent_tool|agent_tools" .
rg -n "\.\.\.|TBD|TODO|implement later|appropriate|similar to|fill in|Fill with|NotImplementedError" docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md
git diff --check -- docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md
git diff --check -- docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md session-log.md
```

Results:

- Documentation-only update.
- Placeholder/red-flag scan completed with no matches after revisions.
- `git diff --check -- docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md` completed without whitespace errors.
- `git diff --check -- docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md session-log.md` completed without whitespace errors.
- No tests were run because no implementation code changed.

Caveats:

- The worktree already contained unrelated modified and untracked files before this session.
- The new implementation plan and existing `docs/agent-harness-implementation.md` are currently untracked in git.

## 2026-05-09 - Codex - Agent Tool Mode Task 1 Contract Layer

- Summary: Added the local-only `essay_writer.agent_tools` contract layer with dataclasses, deterministic JSON/hash/id helpers, atomic JSON IO, work packet/result/commit/source bundle storage, and agent run checkpoint/recovery storage. Added focused tests for schema roundtrips, work store behavior, and run recovery.
- Files changed: `essay_writer/agent_tools/__init__.py`, `essay_writer/agent_tools/config.py`, `essay_writer/agent_tools/schemas.py`, `essay_writer/agent_tools/json_io.py`, `essay_writer/agent_tools/id_utils.py`, `essay_writer/agent_tools/work_store.py`, `essay_writer/agent_tools/run_store.py`, `tests/agent_tools/__init__.py`, `tests/agent_tools/_tmp.py`, `tests/agent_tools/helpers.py`, `tests/agent_tools/test_schema_roundtrip.py`, `tests/agent_tools/test_work_store.py`, `tests/agent_tools/test_run_store.py`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_schema_roundtrip.py tests\agent_tools\test_work_store.py tests\agent_tools\test_run_store.py` (initial expected import failure, then 7 passed with known pytest cache permission warning); `python -m compileall essay_writer\agent_tools tests\agent_tools` (passed).
- Caveats/follow-ups: No LLM/backend/API-backed imports were added. Pytest still warns that `.pytest_cache` cannot be written in this Windows environment.

## 2026-05-09 - Codex - Agent Tool Mode Task 1 Review Fixes

- Summary: Addressed Task 1 review findings by adding direct `AgentToolConfig` defaults, freezing agent tool schema dataclasses, broadening schema roundtrip coverage, cleaning completed packet IDs from pending state when attaching results with packet IDs, using newer checkpoints for recovery when run records are stale, making result/commit persistence safer against traceability collisions, and adding focused tests for the collision/recovery edge cases.
- Files changed: `essay_writer/agent_tools/config.py`, `essay_writer/agent_tools/id_utils.py`, `essay_writer/agent_tools/json_io.py`, `essay_writer/agent_tools/schemas.py`, `essay_writer/agent_tools/work_store.py`, `essay_writer/agent_tools/run_store.py`, `tests/agent_tools/test_schema_roundtrip.py`, `tests/agent_tools/test_work_store.py`, `tests/agent_tools/test_run_store.py`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_schema_roundtrip.py tests\agent_tools\test_work_store.py tests\agent_tools\test_run_store.py` (13 passed; known pytest cache permission warning); `python -m compileall essay_writer\agent_tools tests\agent_tools` (passed); `rg -n "llm|backend\.deps|openai|claude|gemini|chat_json|requests|httpx|urllib" essay_writer\agent_tools tests\agent_tools` (only intentional `ExplodingLLMClient.chat_json` helper matched); `git diff --check -- essay_writer\agent_tools tests\agent_tools session-log.md` (passed with existing LF-to-CRLF notice for `session-log.md`).
- Caveats/follow-ups: Task 1 remains local-only; broader Agent Tool Mode tools are still pending in later implementation tasks.

## 2026-05-09 - Codex - Agent Tool Mode Task 2 Facade Bootstrap

- Summary: Added harness operating instructions, local store bundle wiring, and `AgentToolFacade` lifecycle/recovery methods for AgentRun bootstrap, state, listing, recovery, and checkpoints.
- Files changed: `docs/agent-tool-mode-instructions.md`, `essay_writer/agent_tools/stores.py`, `essay_writer/agent_tools/facade.py`, `essay_writer/agent_tools/__init__.py`, `tests/agent_tools/test_job_and_recovery_tools.py`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_job_and_recovery_tools.py` (initial expected missing-facade failure, then 5 passed with known pytest cache permission warning); `pytest tests\agent_tools\test_job_and_recovery_tools.py tests\agent_tools\test_run_store.py` (8 passed with known pytest cache permission warning); `python -m compileall essay_writer\agent_tools docs` (passed); `rg -n "llm|backend\.deps|openai|claude|gemini|chat_json|requests|httpx|urllib" essay_writer\agent_tools tests\agent_tools` (only `resolve_source_requests` tool name and existing `ExplodingLLMClient.chat_json` helper matched).
- Caveats/follow-ups: Facade remains local-only and exposes later workflow tool names as advertised but does not implement those later tools yet.

## 2026-05-09 - Codex - Agent Tool Mode Task 2 Review Fixes

- Summary: Addressed Task 2 review findings by returning `must_remember` from instruction/list tools, distinguishing planned workflow tools from currently callable bootstrap tools, allowing checkpoints to unblock previously blocked AgentRuns, using stable local `SourceAccessConfig()` during facade bootstrap, aligning validation store path with `validations`, and adding missing-run/error and bootstrap stability tests.
- Files changed: `docs/agent-tool-mode-instructions.md`, `docs/superpowers/plans/2026-05-09-agent-tool-mode-mcp-implementation.md`, `essay_writer/agent_tools/facade.py`, `essay_writer/agent_tools/stores.py`, `essay_writer/agent_tools/run_store.py`, `tests/agent_tools/test_job_and_recovery_tools.py`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_job_and_recovery_tools.py tests\agent_tools\test_run_store.py` (11 passed; known pytest cache permission warning); `pytest tests\agent_tools\test_schema_roundtrip.py tests\agent_tools\test_work_store.py tests\agent_tools\test_run_store.py tests\agent_tools\test_job_and_recovery_tools.py` (21 passed; known pytest cache permission warning); `python -m compileall essay_writer\agent_tools docs` (passed); `rg -n "backend\.deps|from llm|import llm|openai|claude|gemini|chat_json|requests|httpx|urllib" essay_writer\agent_tools tests\agent_tools` (only `resolve_source_requests` tool name and existing `ExplodingLLMClient.chat_json` helper matched); `git diff --check -- docs\agent-tool-mode-instructions.md docs\superpowers\plans\2026-05-09-agent-tool-mode-mcp-implementation.md essay_writer\agent_tools tests\agent_tools session-log.md` (passed with LF-to-CRLF notices for docs plan and session log).
- Caveats/follow-ups: Task 2 exposes only bootstrap/run lifecycle methods as callable; later workflow tools remain planned for following tasks.

## 2026-05-09 - Codex - Agent Tool Mode Task 3 Boundary Tests

- Summary: Added no-hidden-API guardrails for `essay_writer.agent_tools`, covering forbidden app-owned LLM/API imports, forbidden LLM-backed service call strings, and a non-vacuous scanned-module check. Marked Task 3 steps complete in the MCP implementation plan.
- Files changed: `tests/agent_tools/test_no_llm_boundary.py`, `docs/superpowers/plans/2026-05-09-agent-tool-mode-mcp-implementation.md`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_no_llm_boundary.py` (3 passed; known pytest cache permission warning); `pytest tests\agent_tools\test_no_llm_boundary.py tests\agent_tools\test_job_and_recovery_tools.py` (11 passed; known pytest cache permission warning); `python -m compileall tests\agent_tools essay_writer\agent_tools` (passed).
- Caveats/follow-ups: No production code changes were needed. The pytest cache warning is the known Windows `.pytest_cache` permission issue.

## 2026-05-09 - Codex - Agent Tool Mode Task 3 Review Fixes

- Summary: Tightened the import-boundary test so equivalent `from backend import deps`, `from llm import factory`, `from llm import logging_client`, `from llm import adapters`, and `from llm.adapters import claude` forms are detected. Updated the implementation plan expectation to match the expanded four-test boundary suite.
- Files changed: `tests/agent_tools/test_no_llm_boundary.py`, `docs/superpowers/plans/2026-05-09-agent-tool-mode-mcp-implementation.md`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_no_llm_boundary.py` (4 passed; known pytest cache permission warning); `pytest tests\agent_tools\test_no_llm_boundary.py tests\agent_tools\test_job_and_recovery_tools.py` (12 passed; known pytest cache permission warning); `pytest tests\agent_tools` (25 passed; known pytest cache permission warning); `python -m compileall tests\agent_tools essay_writer\agent_tools` (passed).
- Caveats/follow-ups: Boundary checks are intentionally blunt and scan production `essay_writer/agent_tools` files only.

## 2026-05-09 - Codex - Agent Tool Mode Task 4 Source Materialization

- Summary: Added no-API Agent Tool Mode source materialization, pending-card source storage methods, `ingest_source_file` facade wiring, materialization idempotency, unsupported suffix errors, and `ToolResult.next_suggested_tools`.
- Files changed: `essay_writer/sources/schema.py`, `essay_writer/sources/storage.py`, `essay_writer/agent_tools/source_materialization.py`, `essay_writer/agent_tools/facade.py`, `essay_writer/agent_tools/schemas.py`, `tests/agent_tools/test_source_materialization.py`, `docs/superpowers/plans/2026-05-09-agent-tool-mode-mcp-implementation.md`, `session-log.md`.
- Tests/commands run: `pytest tests\agent_tools\test_source_materialization.py` (initial RED: missing facade API, then 4 passed; known pytest cache permission warning); `pytest tests\sources\test_ingestion.py tests\agent_tools\test_source_materialization.py` (11 passed; known pytest cache permission warning); `pytest tests\agent_tools` (29 passed; known pytest cache permission warning); `python -m compileall essay_writer\sources essay_writer\agent_tools tests\agent_tools` (passed); `pytest tests\agent_tools\test_no_llm_boundary.py` (4 passed; known pytest cache permission warning).
- Caveats/follow-ups: `ToolResult` now has `next_suggested_tools`. Agent Tool Mode materialization creates text/index/source-map artifacts only; source-card generation remains pending for the later prepare/submit/commit flow.

## 2026-05-09 - Codex - Agent Tool Mode Task 4 Review Fixes

- Summary: Addressed Task 4 review findings by making materialization artifact refs only advertise existing manifests/maps, rejecting directory paths before extraction, validating `agent_run_id` before source artifact writes, adding `build_source_card` to the Agent Tool Mode boundary deny-list, and adding regression tests for those cases.
- Files changed: `essay_writer/agent_tools/facade.py`, `tests/agent_tools/test_no_llm_boundary.py`, `tests/agent_tools/test_source_materialization.py`, `session-log.md`.
- Tests/commands run: `pytest tests\sources\test_ingestion.py tests\agent_tools\test_source_materialization.py` (14 passed; known pytest cache permission warning); `pytest tests\agent_tools` (32 passed; known pytest cache permission warning); `pytest tests\agent_tools\test_no_llm_boundary.py` (4 passed; known pytest cache permission warning); `python -m compileall essay_writer\sources essay_writer\agent_tools tests\agent_tools` (passed).
- Caveats/follow-ups: No blocker remains. There is no dedicated test for omitting `source_map` from artifact refs because normal materialization creates a source map.
