# Hybrid TOC Extraction - Implementation Plan

## Goal

Refactor Layer 2 outline extraction so TOC parsing is deterministic-first in
default mode, with LLM extraction preserved as fallback and explicit mode.

## Task 1 - Rename the Deterministic Parser

Current function:

```text
extract_toc_entries_heuristic
```

Change to:

```text
extract_toc_entries_deterministic
```

Keep `extract_toc_entries_heuristic` as a compatibility alias during the
transition.

## Task 2 - Add Layer 2 Mode Selection

Add parameters to `extract_outline`:

```text
toc_extraction_mode = "auto"
deterministic_min_entries = 10
```

Allowed modes:

```text
auto
deterministic
llm
```

Behavior:

- `auto`: run deterministic first; skip LLM if deterministic entries >= threshold.
- `deterministic`: run deterministic only.
- `llm`: run LLM only.

If `auto` has a weak deterministic result and the LLM returns zero, use the
weak deterministic result rather than returning empty.

## Task 3 - Preserve Current LLM Logging

Keep per-chunk logs:

```text
Layer 2 LLM chunk X/Y: pages [...]
Layer 2 LLM chunk X/Y: is_toc=... entries=N
```

Add deterministic logs:

```text
Layer 2 deterministic: returned N raw TOC entries
Layer 2: using deterministic entries; skipping LLM
Layer 2: deterministic result below threshold; invoking LLM
```

## Task 4 - Add CLI Flags

Add:

```text
--toc-extraction-mode auto|deterministic|llm
--deterministic-min-toc-entries N
```

Defaults:

```text
auto
10
```

## Task 5 - Tests

Add or update tests for:

- deterministic parser still extracts OCR TOC rows
- `auto` skips LLM when deterministic result is strong
- `auto` falls through to LLM when deterministic result is weak
- `deterministic` mode does not call LLM
- `llm` mode calls LLM even if deterministic could extract entries
- CLI parses the new flags

## Task 6 - Verification

Run focused tests:

```powershell
python -m pytest --import-mode=importlib tests\outline\test_prefilter.py tests\outline\test_entry_extraction.py tests\outline\test_pipeline.py::test_extract_outline_sends_only_candidate_toc_window_to_llm tests\outline\test_pipeline.py::test_load_pages_text_parallel_calls_run_parallel_ocr
python -m pytest --import-mode=importlib tests\outline\test_page_text.py tests\outline\test_anchor_apply.py tests\outline\test_anchor_offset.py tests\outline\test_anchor_selection.py tests\outline\test_anchor_forward_scan.py tests\outline\test_label_resolve.py tests\outline\test_range_assignment.py
python -m pytest --import-mode=importlib tests\ocr_parallel tests\task_spec
python -m compileall pdf_pipeline\outline tests\outline
```

Full `tests\outline\test_pipeline.py` may still be blocked by the known Windows
`tmp_path` permission issue in this environment.
