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
