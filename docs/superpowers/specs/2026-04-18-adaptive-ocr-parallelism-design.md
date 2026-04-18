# Adaptive OCR Parallelism — Design Spec

**Date:** 2026-04-18
**Status:** Draft, awaiting approval
**Position in plan.md:** Document Pipeline enhancement. This improves OCR throughput for source ingestion and enables practical indexing of large scanned books.
**Related docs:**

- `docs/superpowers/plans/adaptive-ocr-parallelism.md`
- `docs/superpowers/plans/adaptive-ocr-parallelism-implementation.md`
- `docs/superpowers/specs/2026-04-17-document-outline-extraction-design.md`

---

## 1. Purpose

Large scanned PDFs are too slow to OCR sequentially. This feature adds an
adaptive OCR scheduler that can process pages in parallel, tune concurrency to
the underlying machine, and preserve compatibility with the existing document
pipeline.

The practical target is to reduce wall-clock OCR time dramatically when ingesting
large books, especially when the user wants to OCR and index 5-6 books at once.

The feature must work with the current repo's capabilities:

- text-native PDF extraction via `pypdf`
- OCR tiers: Tesseract, EasyOCR, PaddleOCR
- `.docx` extraction
- outline extraction
- outline OCR fallback
- CLI commands
- page range flags
- future document indexing and retrieval

## 2. Problem

The current OCR path is fundamentally document-sequential:

```text
render page 1 -> OCR page 1
render page 2 -> OCR page 2
...
render page N -> OCR page N
```

Even on a high-RAM workstation, one OCR process may not use all CPU capacity.
For long books this creates poor throughput and a bad feedback loop:

- the CLI appears stuck because JSON is emitted only after the whole run
- a single book monopolizes the run
- page failures can force a full rerun
- outline extraction can become expensive on scanned books
- future indexing cannot start until OCR finishes

The current Tesseract path now streams pages rather than rasterizing the entire
PDF up front, but it is still sequential. EasyOCR and PaddleOCR still need to be
kept compatible and eventually optimized without accidentally overloading GPU or
model initialization costs.

## 3. Goals

### 3.1 Functional Goals

- Process pages of a single scanned PDF concurrently.
- Process multiple PDFs/books concurrently in a later phase.
- Preserve page order in final merged output.
- Store per-page OCR artifacts independently.
- Retry failed pages independently.
- Produce the existing `DocumentExtractionResult` shape for compatibility.
- Report run metadata such as worker count, failures, pages/minute, and timings.
- Support manual worker override.
- Support automatic worker selection based on CPU/RAM.
- Support optional calibration benchmark.
- Keep the existing `pdf-extract extract` command working.
- Add a new explicit parallel OCR command.
- Keep outline extraction compatible and avoid full-book OCR for small-tier outline fallback.
- Keep `.docx` reading untouched.

### 3.2 Performance Goals

- On multi-core CPU machines, Tesseract OCR should scale across multiple page workers.
- The scheduler should avoid CPU oversubscription by controlling worker count and Tesseract internal threading.
- The system should expose enough metrics to tune real-world throughput.
- For page-range smoke tests, the user should see fast completion and progress logs.

### 3.3 Reliability Goals

- One failed page should not fail a whole book by default.
- Re-running the same OCR job should be able to reuse existing successful page artifacts.
- Worker crashes should be isolated.
- Partial output should be explicit and auditable.
- Artifact writes should avoid corrupt partial JSON.

## 4. Non-Goals

- Do not build a full production queue service in the first implementation.
- Do not implement streaming vector indexing in this feature.
- Do not implement PageIndex/cloud OCR in this feature.
- Do not parallelize GPU EasyOCR/PaddleOCR by spawning one model process per page.
- Do not change the public `DocumentExtractionResult` model in a breaking way.
- Do not remove existing sequential extractors.
- Do not make calibration mandatory for CLI runs.
- Do not make `.docx` extraction page-aware. Word docs remain one logical page unless a later renderer is added.

## 5. Compatibility Requirements

This feature must be backward-compatible with existing behavior.

### 5.1 Existing CLI

These commands must keep working:

```powershell
pdf-extract extract path.pdf --mode text_only
pdf-extract extract path.pdf --mode ocr_only --ocr-tier small
pdf-extract outline path.pdf --source-id source-1
```

The existing `extract` command may remain sequential. Parallelism should be added
through a new explicit command first.

### 5.2 Existing Python API

This should keep working:

```python
from pdf_pipeline.pipeline import ExtractionPipeline

result = ExtractionPipeline(...).extract("book.pdf")
```

No required caller changes.

### 5.3 Existing Models

`PageText` and `DocumentExtractionResult` remain valid output models.

Parallel OCR may introduce richer models, but final merged text must be
convertible to:

```text
DocumentExtractionResult(
  source_path: str,
  page_count: int,
  pages: list[PageText]
)
```

### 5.4 Outline Extraction

Outline extraction must remain compatible with:

- `extract_outline`
- `OutlineStore`
- `list_outline`
- `get_section`
- `LazyTesseractPageExtractor`
- `LazyPageTextMap`

Small-tier outline fallback must stay lazy and per-page. It must not regress to
whole-document OCR.

Medium/high outline fallback may remain whole-document temporarily, but this
must be explicit and logged until per-page backends exist.

### 5.5 DOCX Extraction

`.docx` extraction is not affected by OCR parallelism.

`DocumentReader` should continue routing:

```text
.pdf  -> PyPdfExtractor
.docx -> WordDocExtractor
.doc  -> unsupported
```

Later ingestion orchestration can decide to route scanned PDFs into parallel OCR,
but Word docs do not enter the OCR scheduler.

### 5.6 OCR Tier Compatibility

Small/Tesseract:

- first backend to support true page-level parallelism
- CPU-process workers are allowed
- `en` must continue mapping to Tesseract's `eng`

Medium/EasyOCR:

- must keep existing sequential behavior
- should stop eager-rasterizing full documents
- GPU mode must not spawn many model processes
- future page-level parallelism should be backend-specific

High/PaddleOCR:

- must keep existing sequential behavior
- should stop eager-rasterizing full documents
- GPU mode must not spawn many model processes
- future page-level parallelism should be backend-specific

## 6. Architecture

Add a new parallel OCR subsystem beside the current extractors:

```text
pdf_pipeline/ocr_parallel/
  schema.py
  system.py
  planner.py
  page_worker.py
  scheduler.py
  store.py
  merge.py
  calibration.py
```

Conceptual flow:

```text
PDF path
  |
  v
Inspect page count
  |
  v
Build OCR page tasks
  |
  v
Select worker count
  |
  v
Run page workers
  |
  v
Write page artifacts
  |
  v
Merge successful pages in page order
  |
  v
Return DocumentExtractionResult + OcrRunSummary
```

The scheduler sits above extractors. Extractors remain backend adapters.

## 7. Core Data Model

### 7.1 OCR Page Task

Represents one page to OCR.

Fields:

```text
document_id
source_path
page_number
ocr_tier
dpi
languages
use_gpu
attempt
timeout_seconds
```

### 7.2 OCR Page Result

Represents the result of one page worker.

Fields:

```text
document_id
source_path
page_number
text
char_count
extraction_method
rasterization_ms
ocr_ms
normalization_ms
worker_pid
attempt
created_at
error_message
```

If OCR fails, the page artifact should still record:

```text
page_number
attempt
error_message
failed_at
```

### 7.3 OCR Run Summary

Represents one full scheduler run.

Fields:

```text
run_id
document_id
source_path
page_count
requested_pages
successful_pages
failed_pages
ocr_tier
dpi
languages
selected_workers
worker_plan_source
started_at
completed_at
elapsed_seconds
pages_per_minute
failures
store_path
```

### 7.4 Worker Plan

Represents selected concurrency.

Fields:

```text
ocr_tier
physical_cores
logical_cores
total_ram_gb
available_ram_gb
selected_workers
max_workers
omp_thread_limit
source
reason
```

Allowed `source` values:

```text
manual_override
cached_calibration
static_heuristic
default
```

## 8. Artifact Storage

Add an OCR artifact store, separate from `OutlineStore`.

Default root:

```text
./ocr_store
```

Recommended layout:

```text
ocr_store/
  {document_id}/
    config.json
    pages/
      000001.json
      000002.json
      ...
    merged/
      v1.json
    runs/
      {run_id}.json
    calibration/
      latest.json
```

Page artifacts are first-class. They allow:

- retrying failed pages
- resuming interrupted jobs
- auditing OCR quality
- streaming future indexing
- merging in deterministic order

Writes should be atomic enough for local use:

```text
write temp file -> flush -> rename/link into final path
```

## 9. Worker Selection

The scheduler should support three modes:

```text
manual worker count
static auto heuristic
calibrated auto heuristic
```

### 9.1 Manual

User passes:

```powershell
--workers 6
```

or:

```text
OCR_MAX_WORKERS=6
```

Manual override wins over all automatic logic.

### 9.2 Static Auto

The system detects:

- physical CPU cores
- logical CPU threads
- total RAM
- available RAM

Tesseract default:

```text
if shared_machine:
  selected_workers = min(max(1, physical_cores // 2), 8)
else:
  selected_workers = min(physical_cores, 16)
```

Then apply RAM cap:

```text
memory_per_worker_gb = 1.5
ram_bound = floor(available_ram_gb / memory_per_worker_gb)
selected_workers = min(selected_workers, ram_bound)
```

Always return at least one worker.

### 9.3 Calibration

Optional mode:

```powershell
--calibrate
```

Calibration benchmarks candidate worker counts on sample pages.

Candidate worker counts:

```text
[1, 2, 4, 6, 8, 12, 16]
```

bounded by:

- physical cores
- configured max workers
- RAM bound

Sample pages:

```text
first content-ish page
second content-ish page
middle page
later middle page
last content-ish page
```

Initial implementation may use simpler sampling:

```text
[1, 2, middle, last]
```

Calibration picks the best stable throughput, not necessarily the largest worker
count.

## 10. Tesseract-Specific Rules

Tesseract is the first backend to get true page-level parallelism.

Requirements:

- Use process workers, not thread workers.
- Worker function must be module-level for Windows compatibility.
- Do not pass PIL images, `PdfDocument`, or open handles into workers.
- Each worker receives only primitive data/dataclasses.
- Each worker opens/renders/OCRs one page.
- Set `OMP_THREAD_LIMIT=1` by default before launching workers.
- Allow user override of `OMP_THREAD_LIMIT`.

Language handling:

```text
en -> eng
```

must remain consistent with current `TesseractOcrExtractor`.

## 11. EasyOCR and PaddleOCR Rules

EasyOCR and PaddleOCR must remain compatible but should not be naively
parallelized in the first implementation.

Immediate required change:

- avoid eager full-document rasterization
- use streaming page iteration
- respect `start_page` and `max_pages`

Future backend-specific work:

- CPU mode may use limited process workers
- GPU mode should use long-lived model workers or batching
- do not spawn one GPU model process per page

If user asks for parallel medium/high before backend-specific workers exist, the
CLI should fail clearly or run sequentially with a warning. It should not pretend
to be parallel.

## 12. CLI Surface

Add a new command:

```powershell
pdf-extract ocr-parallel path.pdf
```

Options:

```text
--ocr-tier small|medium|high
--ocr-dpi 300
--ocr-lang en
--ocr-gpu
--start-page 1
--max-pages N
--workers auto|N
--calibrate
--store ./ocr_store
--document-id optional
--max-attempts 2
--timeout-seconds 120
--json-summary
```

Initial support matrix:

```text
ocr-parallel + small  -> supported
ocr-parallel + medium -> sequential or explicit unsupported-for-parallel warning
ocr-parallel + high   -> sequential or explicit unsupported-for-parallel warning
```

Example:

```powershell
pdf-extract ocr-parallel testpdfs\anatomydescripti1858gray.pdf --ocr-tier small --workers auto --max-pages 20 --store ./ocr_store
```

## 13. Python API Surface

Expose a small public API from `pdf_pipeline.ocr_parallel`.

Expected shape:

```text
run_parallel_ocr(...)
```

Returns:

```text
OcrRunSummary
DocumentExtractionResult
```

The exact function/class naming can be finalized during implementation, but the
API must not require CLI-only code paths.

## 14. Outline Compatibility

Current outline behavior should remain:

```text
Layer 1: PDF outlines
Layer 1.5: page labels
Layer 2: LLM TOC extraction
Layer 3: anchor scan
Layer 4: range assignment
```

Specific requirements:

- `OcrTier.SMALL` fallback uses `LazyTesseractPageExtractor`.
- Lazy extractor OCRs only requested pages.
- `LazyPageTextMap` remains lazy for anchor scan.
- Cached page OCR results are reused across TOC scan and anchor scan.
- Medium/high whole-document fallback remains explicit until per-page backends exist.
- Parallel OCR artifacts may later be used by outline extraction, but the first
  implementation must not force outline extraction to depend on the OCR store.

Future integration:

```text
if OCR store already contains page artifacts:
  outline PageTextSource may read from store before invoking live OCR
```

This is a future optimization, not required for first implementation.

## 15. Text-Native PDF Compatibility

Parallel OCR is for OCR mode only.

Text-native PDFs should still use:

```text
PyPdfExtractor
```

Future `AUTO` mode may choose:

```text
if pypdf text quality is good:
  use text extraction
else:
  use OCR or parallel OCR
```

But `AUTO` is not required in this feature.

## 16. DOCX Compatibility

DOCX extraction is outside OCR parallelism.

No change required to:

```text
WordDocExtractor
DocumentReader
```

Future ingestion orchestration can place DOCX artifacts in the same broader
document store, but not in the OCR page scheduler.

## 17. Page Range Semantics

Existing OCR config has:

```text
start_page
max_pages
```

Parallel OCR must respect these exactly.

Rules:

- `start_page` is 1-indexed.
- `max_pages` is a count, not an end page.
- invalid `start_page < 1` fails clearly.
- invalid `max_pages < 1` fails clearly.
- requested range is clipped to document page count.

Example:

```text
start_page = 10
max_pages = 5
requested pages = 10, 11, 12, 13, 14
```

## 18. Failure Handling

Page-level failure policy:

- retry failed pages up to `max_attempts`
- record every final failure
- continue processing other pages
- return summary with failed page numbers
- final merged result includes successful pages only
- summary must make missing pages obvious

Document-level failure policy:

- invalid file -> fail whole run
- unsupported tier -> fail before starting
- missing dependency -> fail before starting where possible
- one page failure -> partial success unless strict mode is later added

Potential future option:

```text
--strict
```

would fail the whole run if any page fails. Not required now.

## 19. Observability

Logs should include:

- selected workers
- worker plan source
- OCR tier
- DPI
- language
- page range
- progress count
- pages per minute
- failures
- final summary

Verbose levels:

```text
-v  -> periodic progress
-vv -> per-page timings
```

Metrics recorded in summary:

- total elapsed time
- pages completed
- pages failed
- pages per minute
- average rasterization ms
- average OCR ms
- selected worker count

## 20. Install And Environment

Add optional scheduler dependency:

```toml
ocr-scheduler = ["psutil>=5.9.0"]
```

Recommended install for small parallel OCR:

```powershell
pip install -e ".[dev,ocr-small,ocr-scheduler]"
```

Environment variables:

```text
OCR_MAX_WORKERS
OCR_SHARED_MACHINE
OCR_OMP_THREAD_LIMIT
OCR_CALIBRATE
OCR_STORE
```

Tesseract binary still must be installed separately on Windows.

## 21. Security And Safety

OCR runs on local files.

Requirements:

- do not execute user-provided paths as commands
- pass paths as data, not shell strings
- avoid writing artifacts outside configured store root
- validate store paths before recursive cleanup, if cleanup is added later
- preserve source paths in summaries but avoid leaking them in user-facing logs
  in multi-tenant production later

## 22. Testing Requirements

### 22.1 Unit Tests

Add:

```text
tests/ocr_parallel/test_schema.py
tests/ocr_parallel/test_system.py
tests/ocr_parallel/test_planner.py
tests/ocr_parallel/test_page_worker.py
tests/ocr_parallel/test_store.py
tests/ocr_parallel/test_merge.py
tests/ocr_parallel/test_scheduler.py
tests/ocr_parallel/test_calibration.py
```

Tests should mock:

- system resources
- page rendering
- Tesseract OCR
- worker results

Do not require real Tesseract in default unit tests.

### 22.2 Existing Tests

These must remain passing:

```text
tests/test_ocr_pipeline.py
tests/test_pypdf_extractor.py
tests/test_word_doc_extractor.py
tests/outline/
```

Known local caveat:

Some pytest runs on this Windows sandbox hit temp-directory permission errors.
That is an environment issue, not an acceptable product regression.

### 22.3 Integration Tests

Add optional integration tests with skip markers:

- requires `pypdfium2`
- requires `pytesseract`
- requires `tesseract` executable
- requires sample PDF

Integration tests should use small page ranges:

```text
--max-pages 2 or 3
```

## 23. Acceptance Criteria

The feature is accepted when:

1. `pdf-extract ocr-parallel --help` works.
2. `ocr-parallel` supports Tesseract small-tier page-level parallelism.
3. Worker count supports manual and auto modes.
4. Page artifacts are written independently.
5. Failed pages are retried and reported.
6. Final merged output preserves page order.
7. `DocumentExtractionResult` compatibility is maintained.
8. Existing `pdf-extract extract` behavior still works.
9. Existing outline behavior still works.
10. Small-tier outline OCR fallback remains lazy per-page.
11. EasyOCR/PaddleOCR sequential paths no longer eager-rasterize all pages.
12. README documents install and usage.
13. Unit tests cover scheduler, planner, store, worker, and merge behavior.

Performance acceptance for local validation:

- On a multi-core machine, running Tesseract small-tier with multiple workers on
  a 20-page scanned range should complete faster than the sequential path.
- The exact target speedup is hardware-dependent and should be reported in the
  run summary rather than hard-coded in tests.

## 24. Migration Plan

No migration required for existing artifacts.

This feature adds new artifacts under `ocr_store`.

Existing outputs such as:

```text
wonderfulwizard_ocr.json
greys_anatomy_ocr.json
outline_store/
```

remain valid.

## 25. Rollout Plan

Phase 1:

- add Tesseract parallel OCR for one document
- add artifact store
- add CLI command
- keep medium/high sequential

Phase 2:

- add calibration
- add resume support
- stream EasyOCR/Paddle sequential page iteration
- improve logs and summaries

Phase 3:

- add multi-book scheduling
- add OCR-store-backed outline text source
- add indexing callback hook

Phase 4:

- backend-specific EasyOCR/Paddle parallel workers
- GPU-aware scheduling
- optional PageIndex/cloud OCR integration

## 26. Open Questions

- Should `ocr-parallel` print the merged `DocumentExtractionResult` by default,
  or print a summary and write merged JSON to the store?
- Should partial page failures produce a nonzero exit code?
- Should page artifacts include raw OCR confidence where backend supports it?
- Should the OCR store identify documents by path hash, content hash, or user
  supplied `document_id`?
- Should calibration be cached per machine globally or per store/document?
- Should `extract --mode ocr_only` eventually delegate to `ocr-parallel` when
  `--parallel` is passed?

## 27. Recommendation

Approve implementation with this initial scope:

- Tesseract small-tier parallel OCR only
- explicit `ocr-parallel` CLI
- one-document scheduler
- page artifact store
- worker auto-planning
- no mandatory calibration yet
- no multi-book scheduler yet
- no PageIndex yet
- keep all existing APIs and commands compatible

This gives the project a large OCR speed improvement without destabilizing the
outline pipeline, DOCX support, or medium/high OCR backends.
