# Session Log

Chronological log of agent sessions. Add a new entry whenever an agent changes code, tests, docs, dependencies, or configuration.

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
