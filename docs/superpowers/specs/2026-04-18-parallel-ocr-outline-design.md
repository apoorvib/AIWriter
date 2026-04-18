# Parallel OCR for Outline Extraction — Design Spec

**Date:** 2026-04-18
**Status:** Approved

---

## Problem

The outline pipeline's Layer 2 OCR phase fetches the first `max_toc_pages` (default 40) pages
sequentially. For scanned books like Gray's Anatomy, each page takes ~1–3s under Tesseract, meaning
the TOC window alone takes 40–120s before the LLM even runs. The parallel OCR infrastructure
(`run_parallel_ocr`, `ProcessPoolExecutor`, worker planner, calibration) already exists but is
only wired to the standalone `ocr-parallel` CLI command.

---

## Goal

Parallelize the Layer 2 TOC window OCR inside the outline pipeline by reusing `run_parallel_ocr`
directly, scoped to the TOC page range. No parallel logic is duplicated. Layer 3 anchor scan
remains lazy and sequential (it probes only ~50–100 pages on demand and is already fast enough).

---

## Architecture

### Call stack

```
outline CLI
  → extract_outline()
      → _load_pages_text(parallel_workers=N)   ← change here
          → run_parallel_ocr(max_pages=scan_pages, store_path=tmpdir)
          → dict[int, str]                      ← same return type as today
      → [Layer 2, 1.5, 3, 4 unchanged]
```

The anchor scan still uses `LazyPageTextMap` backed by `PageTextSource` /
`LazyTesseractPageExtractor` — this path is untouched.

### What changes

| Location | Change |
|---|---|
| `pdf_pipeline/outline/pipeline.py` | `extract_outline` gains `parallel_workers: int \| str \| None` and `calibrate: bool = False`. `_load_pages_text` gains both params; when `parallel_workers` is set, calls `run_parallel_ocr` instead of sequential loop. |
| `pdf_pipeline/cli.py` | `outline` subparser gains `--parallel-workers` and `--calibrate`. |
| Nothing else | `run_parallel_ocr`, `PageTextSource`, `LazyTesseractPageExtractor`, all layers — unchanged. |

---

## Data Flow (parallel path)

1. `_load_pages_text` is called with `parallel_workers` set (int or `"auto"`).
2. Build `ParallelOcrConfig`:
   - `start_page=1`, `max_pages=scan_pages`
   - `workers=parallel_workers`, `calibrate=calibrate`
   - `store_path=tempfile.mkdtemp()`
   - `ocr_tier`, `dpi`, `languages`, `use_gpu` forwarded from existing `OcrConfig`
3. Call `run_parallel_ocr(pdf_path, config)` → `(summary, DocumentExtractionResult)`.
4. Convert to `dict[int, str]`: `{p.page_number: p.text for p in result.pages}`.
5. Cleanup temp dir in a `finally` block.
6. Return dict — identical type to the sequential path; all downstream code unchanged.

---

## CLI

Two new flags on the `outline` subparser:

```
--parallel-workers N|auto
    Worker count for parallel OCR of the TOC window (pages 1–max_toc_pages).
    Use 'auto' for automatic worker planning. Omit to use sequential OCR (default).

--calibrate
    When --parallel-workers is auto, benchmark sample pages first to select the
    optimal worker count. Ignored if --parallel-workers is a specific integer.
```

### Example

```bash
python -m pdf_pipeline.cli -vv outline testpdfs/anatomydescripti1858gray.pdf \
  --source-id greys-anatomy \
  --ocr-tier small \
  --parallel-workers auto \
  --calibrate \
  > outputs/greys_anatomy_outline.txt 2>&1
```

---

## Error Handling

- Pages that fail OCR in the parallel run come back as empty strings — identical to sequential
  Tesseract failure. The prefilter and LLM already tolerate sparse/empty pages.
- Temp dir is cleaned up in `finally`; never leaks even if extraction raises mid-run.
- If `--parallel-workers` is set without `--ocr-tier`, the CLI raises an argparse error
  (parallel OCR requires an OCR tier to be specified).

---

## What is NOT changing

- Layer 1 (embedded `/Outlines`): unchanged — still short-circuits before any OCR.
- Layer 1.5 (`/PageLabels` resolution): unchanged.
- Layer 3 (anchor scan): unchanged — lazy sequential Tesseract via `LazyPageTextMap`.
- Layer 4 (end page assignment): unchanged.
- `run_parallel_ocr`, `OcrArtifactStore`, `page_worker`, `planner`, `calibration`: all unchanged.
- `PageTextSource`, `LazyTesseractPageExtractor`, `PyPdfPageExtractor`: all unchanged.
- The `--parallel-workers` / `--calibrate` flags are NOT added to the `extract` subparser
  (out of scope for this change).

---

## Out of Scope

- Parallelizing Layer 3 anchor scan (deferred; sequential is fast enough for now).
- Persisting TOC window OCR results across runs (in-memory only; use `ocr-parallel` if caching needed).
- Medium/High OCR tiers in parallel mode (Tesseract/small only, matching current `ocr-parallel` constraint).
