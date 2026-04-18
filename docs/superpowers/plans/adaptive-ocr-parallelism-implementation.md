# Adaptive OCR Parallelism Implementation Plan

## Goal

Implement adaptive OCR parallelism for large PDFs and book batches.

The end state is a production-ready ingestion path that can:

- process multiple books concurrently
- process multiple pages within a book concurrently
- tune worker count based on machine resources
- optionally benchmark worker counts before full OCR
- store page-level OCR artifacts independently
- retry failed pages without redoing the whole book
- merge page artifacts into the current `DocumentExtractionResult` shape
- support future streaming indexing

This plan is based on the current codebase as of 2026-04-18.

## Current Codebase Findings

### Current Package Layout

Relevant existing files:

```text
pdf_pipeline/
  cli.py
  models.py
  modes.py
  ocr.py
  pipeline.py
  document_reader.py
  extractors/
    base.py
    ocr_common.py
    pypdf_extractor.py
    tesseract_extractor.py
    easyocr_extractor.py
    paddle_extractor.py
    word_doc_extractor.py
  outline/
    page_text.py
    pipeline.py
    storage.py
    tools.py

tests/
  test_ocr_pipeline.py
  test_pypdf_extractor.py
  test_word_doc_extractor.py
  outline/
```

Relevant existing models:

```text
PageText
DocumentExtractionResult
OcrConfig
OcrTier
ExtractionPipeline
```

Relevant current CLI shape:

```powershell
pdf-extract extract path.pdf --mode ocr_only --ocr-tier small
pdf-extract outline path.pdf --source-id ...
```

### Current OCR Behavior

`ExtractionPipeline` selects one extractor:

```text
TEXT_ONLY -> PyPdfExtractor
OCR_ONLY + small -> TesseractOcrExtractor
OCR_ONLY + medium -> EasyOcrExtractor
OCR_ONLY + high -> PaddleOcrExtractor
```

The small Tesseract extractor has already been improved to stream rasterization
page-by-page through `iter_rasterized_pdf_pages`, so it no longer rasterizes the
entire book before starting OCR.

However, it is still sequential:

```text
render page 1 -> OCR page 1
render page 2 -> OCR page 2
...
```

`EasyOcrExtractor` and `PaddleOcrExtractor` still use `rasterize_pdf_pages`,
which materializes all page images before OCR:

```text
all pages rendered to images -> OCR page 1 -> OCR page 2 -> ...
```

That is not suitable for large books.

### Current Outline Interaction

`pdf_pipeline.outline.page_text` has several relevant pieces:

- `PageTextSource`
- `PyPdfPageExtractor`
- `DocumentOcrPageExtractor`
- `LazyTesseractPageExtractor`
- `LazyPageTextMap`

Important issue:

`DocumentOcrPageExtractor` adapts a whole-document OCR extractor to a per-page
interface by running the entire OCR extractor once and caching every page.

That means the outline pipeline can accidentally trigger full-book OCR even when
it only needs a few pages.

There is already a `LazyTesseractPageExtractor` that OCRs one page on demand,
but `outline.pipeline._build_ocr_page_extractor` currently returns
`DocumentOcrPageExtractor`, not `LazyTesseractPageExtractor`.

This should be fixed early.

### Current Storage Pattern

`OutlineStore` provides a useful model:

- file-backed storage
- versioned artifacts
- JSON serialization
- atomic-ish write pattern
- source-id keyed directories

OCR page artifacts should get their own store instead of being forced into
`OutlineStore`, but the storage style can be reused.

### Current Dependency State

`pyproject.toml` currently includes:

- `pypdf`
- `python-dotenv`
- `ocr-small`
- `ocr-medium`
- `ocr-high`
- LLM extras
- outline extras

It does not currently include `psutil`, which is the cleanest way to detect CPU
and RAM stats. Add `psutil` as an optional OCR scheduling dependency or as a
base dependency if adaptive scheduling becomes a core feature.

## Implementation Strategy

Do not mutate the existing extractor API into a complicated job system all at
once.

Instead, add a parallel OCR subsystem beside the current simple extractors:

```text
simple extractors:
  ExtractionPipeline.extract(...)

parallel OCR:
  OcrDocumentRunner.run(...)
```

The simple path should continue to work for small files and tests.

The parallel path should reuse low-level page rendering and OCR logic where
possible, then normalize output back into `DocumentExtractionResult`.

## Proposed New Package

Create:

```text
pdf_pipeline/ocr_parallel/
  __init__.py
  schema.py
  system.py
  planner.py
  page_worker.py
  scheduler.py
  store.py
  calibration.py
  merge.py
```

This keeps scheduling and artifact concepts separate from the existing
extractor classes.

Do not put this inside `pdf_pipeline/extractors/`. Extractors should remain
backend adapters. Scheduling is a higher-level orchestration concern.

## Proposed Responsibilities

### `schema.py`

Define dataclasses for the parallel OCR system.

Needed types:

- `OcrBackend`
- `OcrPageTask`
- `OcrPageResult`
- `OcrPageError`
- `OcrDocumentJob`
- `OcrRunSummary`
- `SystemResources`
- `WorkerPlan`
- `CalibrationCandidateResult`
- `CalibrationProfile`

Recommended fields for `OcrPageTask`:

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

Recommended fields for `OcrPageResult`:

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
error_message
created_at
```

Recommended fields for `WorkerPlan`:

```text
backend
dpi
languages
physical_cores
logical_cores
total_ram_gb
available_ram_gb
max_workers
selected_workers
source
reason
omp_thread_limit
```

The `source` field should distinguish:

```text
manual_override
cached_calibration
static_heuristic
default
```

### `system.py`

Detect machine resources.

Tasks:

- detect logical CPU count with `os.cpu_count()`
- detect physical CPU count with `psutil.cpu_count(logical=False)` when available
- detect total RAM with `psutil.virtual_memory().total`
- detect available RAM with `psutil.virtual_memory().available`
- provide fallback behavior when `psutil` is unavailable
- expose a small immutable `SystemResources` object

Add dependency:

```toml
ocr-scheduler = ["psutil>=5.9.0"]
```

or include `psutil` in `ocr-small` if adaptive scheduling is considered part of
the OCR feature.

Preferred:

```toml
ocr-scheduler = ["psutil>=5.9.0"]
```

Then users can install:

```powershell
pip install -e ".[dev,ocr-small,ocr-scheduler]"
```

### `planner.py`

Choose initial worker count.

Inputs:

- `SystemResources`
- OCR backend/tier
- DPI
- language
- explicit CLI/env overrides
- whether machine is shared
- optional cached calibration profile

Environment variables to support:

```text
OCR_MAX_WORKERS
OCR_MAX_CONCURRENT_BOOKS
OCR_PAGE_WORKERS_PER_BOOK
OCR_OMP_THREAD_LIMIT
OCR_CALIBRATE
OCR_SHARED_MACHINE
```

Initial Tesseract heuristic:

```text
if OCR_MAX_WORKERS is set:
    selected_workers = OCR_MAX_WORKERS
elif shared_machine:
    selected_workers = min(max(1, physical_cores // 2), 8)
else:
    selected_workers = min(physical_cores, 16)
```

Also bound by RAM:

```text
memory_per_worker_gb = 1.5 for Tesseract
ram_bound = floor(available_ram_gb / memory_per_worker_gb)
selected_workers = min(selected_workers, ram_bound)
```

Always return at least `1`.

For the first implementation, only Tesseract needs full worker planning. EasyOCR
and PaddleOCR can be guarded with conservative defaults until backend-specific
parallel work is implemented.

### `page_worker.py`

Implement one-page OCR workers.

The worker should do exactly one page:

```text
open PDF
render requested page
OCR requested page
normalize text
return OcrPageResult
```

Start with Tesseract only.

Why:

- Tesseract already works in the repo.
- Tesseract runs per page cleanly.
- It does not require a long-lived GPU model.
- It is the easiest backend to parallelize with process workers.

Needed low-level helper:

```text
render_pdf_page(pdf_path, page_number, dpi)
```

This should probably live in `extractors/ocr_common.py` because it is shared by
single-page OCR, lazy outline OCR, and future schedulers.

Current `iter_rasterized_pdf_pages` can support this behavior, but explicit
single-page rendering will make the worker easier to reason about and test.

Tesseract worker details:

- map `en` to `eng`
- call `pytesseract.image_to_string`
- record rasterization time separately from OCR time
- include `worker_pid`
- catch runtime errors and return structured page error or raise a wrapped
  exception that the scheduler records

Set process environment:

```text
OMP_THREAD_LIMIT=1
```

This should be set in the scheduler before workers are launched unless the user
overrides it.

### `scheduler.py`

Run page workers concurrently for one document.

Use:

```text
concurrent.futures.ProcessPoolExecutor
```

Responsibilities:

- inspect page count
- create `OcrPageTask` objects
- submit page tasks
- collect results as they complete
- preserve page numbers
- retry failed pages up to configured attempts
- write page artifacts as soon as each page completes
- emit progress logs
- return `OcrRunSummary`

Initial scope:

```text
one document
one OCR backend: Tesseract
one worker pool
manual or heuristic worker count
page artifacts written to disk
merged result returned at end
```

Later scope:

```text
multiple documents
global worker budget
fair scheduling across books
backend-specific GPU workers
```

Progress logging:

```text
completed 12/900 pages, failed 0, rate 4.2 pages/min, workers=6
```

Avoid printing one log line per page by default unless `-vv` is enabled.

### `store.py`

Create a page artifact store.

Recommended root:

```text
./ocr_store
```

Path layout:

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
```

`config.json` should include:

- source path or source hash
- backend
- DPI
- language
- created_at
- selected worker count

Each page JSON should include:

- page number
- text
- char count
- timings
- extraction method
- attempt count
- error if failed

Write behavior:

- write temp file first
- atomically replace or link into place
- avoid corrupt partial JSON if the process crashes

This can borrow style from `OutlineStore`, but it should be a separate class:

```text
OcrArtifactStore
```

### `merge.py`

Merge page artifacts into `DocumentExtractionResult`.

Tasks:

- load all successful page artifacts
- sort by `page_number`
- convert each artifact to `PageText`
- produce `DocumentExtractionResult`
- report missing/failed pages separately in `OcrRunSummary`

Important decision:

Do not silently claim `page_count` equals successful page count for a full
document if pages failed.

Use:

```text
document_page_count = actual PDF page count
successful_page_count = len(successful pages)
failed_page_count = len(failed pages)
```

The existing `DocumentExtractionResult` only has `page_count` and `pages`, so the
parallel runner should return both:

```text
OcrRunSummary
DocumentExtractionResult
```

The summary carries failures and run metadata.

### `calibration.py`

Benchmark worker counts on sample pages.

Initial implementation can be simple:

- choose sample pages
- run candidates `[1, 2, 4, 6, 8]` bounded by physical cores
- measure pages/minute
- pick best stable throughput
- return `CalibrationProfile`
- optionally persist profile in store

Sample page selection:

```text
first page
second page
middle page
later middle page
last page
```

Then improve by skipping blank/cover pages later.

Calibration should be optional:

```text
--calibrate-ocr
OCR_CALIBRATE=true
```

Do not run calibration by default in the CLI until it is fast and predictable.
Do enable it by default in production ingestion later.

## Existing Files To Modify

### `pyproject.toml`

Add optional dependency group:

```toml
ocr-scheduler = [
  "psutil>=5.9.0",
]
```

Consider whether `requires-python` should be tightened for OCR-high. The current
file says `>=3.10,<3.15`, but `paddlepaddle` availability may lag Python 3.14.
Do not solve that inside the parallelism feature unless install failures become
part of the task.

### `pdf_pipeline/ocr.py`

Add scheduler-related config only if it does not pollute the simple extractor
path.

Possible additions:

```text
max_workers
calibrate
store_path
max_attempts
timeout_seconds
```

But prefer a new `ParallelOcrConfig` in `ocr_parallel/schema.py` instead of
overloading `OcrConfig`.

`OcrConfig` should remain backend extraction settings:

```text
languages
dpi
use_gpu
start_page
max_pages
```

### `pdf_pipeline/extractors/ocr_common.py`

Add:

```text
get_pdf_page_count(pdf_path)
render_pdf_page(pdf_path, page_number, dpi)
iter_page_numbers(start_page, max_pages, total_pages)
```

Keep `rasterize_pdf_pages` for compatibility, but new code should prefer
streaming/single-page helpers.

### `pdf_pipeline/extractors/tesseract_extractor.py`

Keep current sequential extractor working.

Optionally refactor shared logic:

```text
ocr_pil_image_with_tesseract(image, languages)
normalize_tesseract_languages(languages)
```

Then both the sequential extractor and page worker can call the same logic.

This avoids duplicating the `en` -> `eng` alias logic.

### `pdf_pipeline/extractors/easyocr_extractor.py`

Do not parallelize immediately.

Short-term fix:

- switch from `rasterize_pdf_pages` to `iter_rasterized_pdf_pages`
- respect `start_page` and `max_pages`
- avoid materializing all pages before OCR

Medium-term:

- add one-page EasyOCR worker only for CPU mode
- be careful with GPU mode because one process per page can reload the model and
  hurt performance

### `pdf_pipeline/extractors/paddle_extractor.py`

Do not parallelize immediately.

Short-term fix:

- switch from `rasterize_pdf_pages` to `iter_rasterized_pdf_pages`
- respect `start_page` and `max_pages`
- avoid materializing all pages before OCR

Medium-term:

- add a long-lived worker model for GPU mode
- avoid spawning many PaddleOCR model instances unless benchmarked

### `pdf_pipeline/outline/page_text.py`

Replace or rewire the outline OCR fallback path.

Current issue:

```text
DocumentOcrPageExtractor -> whole-document OCR on first page request
```

Needed change:

- use lazy single-page OCR for small/Tesseract fallback
- add a generic per-page OCR interface for future backends
- remove or de-emphasize `DocumentOcrPageExtractor` for outline use

Immediate improvement:

```text
_build_ocr_page_extractor(small) -> LazyTesseractPageExtractor
```

This avoids full-book OCR during outline extraction.

For medium/high outline fallback:

- either keep whole-document behavior with a warning
- or do not enable medium/high lazy fallback until per-page workers exist

### `pdf_pipeline/outline/pipeline.py`

Update comments and wiring after `page_text.py` changes.

Current docstring says OCR extractor OCRs the whole document once. That should
not be true after the lazy fallback change.

Also consider using `LazyPageTextMap` for body page access to avoid eagerly
loading all pages in Layer 3. Some lazy mapping support exists already, but the
pipeline currently materializes dicts through `_load_pages_text`.

### `pdf_pipeline/cli.py`

Add a new subcommand rather than overloading `extract` too much.

Recommended:

```powershell
pdf-extract ocr-parallel path.pdf --ocr-tier small --workers auto --store ./ocr_store
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

Keep existing command working:

```powershell
pdf-extract extract ...
```

The existing `extract` command can later get a `--parallel` flag, but start with
a separate command so behavior is explicit.

## Testing Plan

### Unit Tests

Add tests under:

```text
tests/ocr_parallel/
```

Create:

```text
tests/ocr_parallel/__init__.py
tests/ocr_parallel/test_schema.py
tests/ocr_parallel/test_system.py
tests/ocr_parallel/test_planner.py
tests/ocr_parallel/test_page_worker.py
tests/ocr_parallel/test_store.py
tests/ocr_parallel/test_merge.py
tests/ocr_parallel/test_scheduler.py
tests/ocr_parallel/test_calibration.py
```

### Mocking Strategy

Do not require real Tesseract for unit tests.

Use mocks for:

- page rendering
- OCR image-to-string
- system resources
- process worker function

Test the scheduler with a fake page worker so tests are fast and deterministic.

### Tests Needed

`test_planner.py`:

- manual `OCR_MAX_WORKERS` wins
- shared-machine heuristic caps at half physical cores
- dedicated-machine heuristic caps at physical cores or 16
- RAM bound reduces selected workers
- selected workers never drops below 1

`test_page_worker.py`:

- one page task returns expected text
- language `en` maps to `eng`
- timings are populated
- failures produce structured errors or wrapped exceptions

`test_store.py`:

- saves page artifact
- loads page artifact
- writes merged result
- refuses corrupt partial writes
- preserves failed page artifacts

`test_scheduler.py`:

- submits all pages in requested range
- preserves final page order
- retries failed pages
- does not retry beyond max attempts
- returns summary with failed pages
- writes artifacts as pages complete

`test_calibration.py`:

- candidate list is bounded by resources
- best throughput wins
- failure candidates are penalized
- cached profile can be selected

`test_outline_page_text.py` additions:

- outline small OCR fallback uses lazy per-page extractor
- fallback does not run whole-document OCR
- repeated page access uses cache

### Integration Tests

Add optional integration tests marked with skip conditions:

- Tesseract installed
- `pypdfium2` installed
- sample PDF present

Example:

```text
pytest -m ocr_integration
```

Do not make live OCR integration tests part of the default suite unless they are
very small and reliable.

## CLI Acceptance Checks

After implementation, these should work:

Smoke test first 5 pages:

```powershell
pdf-extract ocr-parallel testpdfs\anatomydescripti1858gray.pdf --ocr-tier small --max-pages 5 --workers 2 --store ./ocr_store
```

Auto worker selection:

```powershell
pdf-extract ocr-parallel testpdfs\anatomydescripti1858gray.pdf --ocr-tier small --max-pages 10 --workers auto --store ./ocr_store
```

Calibration:

```powershell
pdf-extract ocr-parallel testpdfs\anatomydescripti1858gray.pdf --ocr-tier small --max-pages 20 --workers auto --calibrate --store ./ocr_store
```

Expected outputs:

- progress logs with selected workers
- page artifacts under `ocr_store`
- merged JSON result
- summary showing pages completed, failed, pages/minute

## Detailed Task List

### Task 1: Add OCR scheduler dependency group

Files:

- `pyproject.toml`

Do:

- add `ocr-scheduler = ["psutil>=5.9.0"]`
- document install command in README later

Acceptance:

- `pip install -e ".[dev,ocr-small,ocr-scheduler]"` installs scheduler deps

### Task 2: Create `ocr_parallel` package skeleton

Files:

- `pdf_pipeline/ocr_parallel/__init__.py`
- `pdf_pipeline/ocr_parallel/schema.py`
- `tests/ocr_parallel/__init__.py`

Do:

- create package
- define core dataclasses in `schema.py`
- export public types from `__init__.py`

Acceptance:

- `python -c "import pdf_pipeline.ocr_parallel"` works
- schema tests pass

### Task 3: Add system resource detection

Files:

- `pdf_pipeline/ocr_parallel/system.py`
- `tests/ocr_parallel/test_system.py`

Do:

- detect logical cores
- detect physical cores when possible
- detect total and available RAM when possible
- provide fallback behavior without `psutil`
- expose `detect_system_resources()`

Acceptance:

- mocked tests cover both psutil-present and fallback paths

### Task 4: Add worker planning

Files:

- `pdf_pipeline/ocr_parallel/planner.py`
- `tests/ocr_parallel/test_planner.py`

Do:

- read environment overrides
- implement Tesseract heuristic
- support shared vs dedicated machine mode
- apply RAM cap
- return `WorkerPlan`

Acceptance:

- manual override wins
- automatic plan is deterministic in tests
- invalid override values produce clear errors

### Task 5: Add single-page rendering helper

Files:

- `pdf_pipeline/extractors/ocr_common.py`
- `tests/test_ocr_pipeline.py` or `tests/ocr_parallel/test_page_worker.py`

Do:

- add `get_pdf_page_count`
- add `render_pdf_page`
- add page-number validation
- keep existing `rasterize_pdf_pages` and `iter_rasterized_pdf_pages`

Acceptance:

- helper renders only requested page
- invalid page numbers fail clearly
- existing OCR tests still pass

### Task 6: Extract shared Tesseract image OCR helper

Files:

- `pdf_pipeline/extractors/tesseract_extractor.py`
- `tests/test_ocr_pipeline.py`

Do:

- expose or internalize a helper for OCRing a PIL image
- reuse language alias mapping
- keep existing sequential extractor behavior unchanged

Acceptance:

- existing Tesseract mock test passes
- `en` still maps to `eng`

### Task 7: Add Tesseract page worker

Files:

- `pdf_pipeline/ocr_parallel/page_worker.py`
- `tests/ocr_parallel/test_page_worker.py`

Do:

- accept `OcrPageTask`
- render one page
- OCR one page with Tesseract
- return `OcrPageResult`
- record timings and process id
- return/raise structured failures

Acceptance:

- unit tests pass without real Tesseract through mocks

### Task 8: Add artifact store

Files:

- `pdf_pipeline/ocr_parallel/store.py`
- `tests/ocr_parallel/test_store.py`

Do:

- create `OcrArtifactStore`
- save/load page artifacts
- save/load run summaries
- save merged document result
- write atomically
- support failed page artifacts

Acceptance:

- page artifact round trips
- failed artifact round trips
- merged result round trips

### Task 9: Add document scheduler

Files:

- `pdf_pipeline/ocr_parallel/scheduler.py`
- `tests/ocr_parallel/test_scheduler.py`

Do:

- create page tasks for a document/range
- launch `ProcessPoolExecutor`
- set `OMP_THREAD_LIMIT` before launching Tesseract workers
- collect futures as complete
- retry failed pages
- write artifacts immediately
- return run summary and merged result

Acceptance:

- fake worker tests prove concurrency orchestration behavior
- final merged page order is correct
- failed pages appear in summary

### Task 10: Add merge logic

Files:

- `pdf_pipeline/ocr_parallel/merge.py`
- `tests/ocr_parallel/test_merge.py`

Do:

- convert page artifacts to `PageText`
- sort pages
- produce `DocumentExtractionResult`
- report missing pages separately

Acceptance:

- page order stable
- missing/failed pages not silently hidden in summary

### Task 11: Add CLI subcommand

Files:

- `pdf_pipeline/cli.py`
- CLI-focused tests if current test structure supports them

Do:

- add `ocr-parallel` subcommand
- parse worker controls
- parse calibration flag
- parse store/document-id/max-attempts
- call scheduler
- print JSON summary or merged JSON result

Acceptance:

- `pdf-extract ocr-parallel --help` works
- smoke command over `--max-pages 2` works locally

### Task 12: Wire outline fallback to lazy small OCR

Files:

- `pdf_pipeline/outline/page_text.py`
- `pdf_pipeline/outline/pipeline.py`
- `tests/outline/test_page_text.py`
- maybe `tests/outline/test_pipeline.py`

Do:

- change small OCR fallback to `LazyTesseractPageExtractor`
- update outdated docstrings
- ensure outline extraction does not invoke full-book OCR for small fallback
- decide medium/high behavior explicitly

Acceptance:

- tests prove only requested pages are OCRed
- outline path remains green

### Task 13: Stream EasyOCR/Paddle sequential extractors

Files:

- `pdf_pipeline/extractors/easyocr_extractor.py`
- `pdf_pipeline/extractors/paddle_extractor.py`
- `tests/test_ocr_pipeline.py`

Do:

- switch from eager `rasterize_pdf_pages` to `iter_rasterized_pdf_pages`
- respect `start_page` and `max_pages`
- maintain existing outputs and mock tests

Acceptance:

- no whole-PDF image list for medium/high sequential paths
- existing tests pass with updated mocks

### Task 14: Add calibration

Files:

- `pdf_pipeline/ocr_parallel/calibration.py`
- `tests/ocr_parallel/test_calibration.py`
- `pdf_pipeline/ocr_parallel/store.py`

Do:

- choose sample pages
- benchmark candidate worker counts
- compute pages/minute
- penalize failures
- persist calibration profile
- allow scheduler to use profile

Acceptance:

- mocked benchmarks select expected candidate
- failed candidates are not selected

### Task 15: Add documentation

Files:

- `README.md`
- `docs/superpowers/plans/adaptive-ocr-parallelism.md`
- this implementation plan, if task statuses are tracked

Do:

- document install command
- document `ocr-parallel` command
- document environment variables
- document Tesseract `OMP_THREAD_LIMIT`
- document expected performance tuning workflow

Acceptance:

- user can install and run a 5-page smoke test from README instructions

## Rollout Order

Recommended sequence:

1. Fix outline small OCR fallback to lazy per-page Tesseract.
2. Add single-page render helper.
3. Add OCR parallel schema/system/planner.
4. Add Tesseract page worker.
5. Add artifact store.
6. Add one-document scheduler.
7. Add CLI `ocr-parallel`.
8. Add merge and summary polish.
9. Stream EasyOCR/Paddle sequential paths.
10. Add calibration.
11. Add multi-book scheduler.
12. Add streaming indexing hooks.

Reasoning:

- Step 1 removes a known performance trap immediately.
- Steps 2-7 deliver practical parallel OCR for Tesseract quickly.
- Medium/high OCR require backend-specific care, so they should not block the
  first useful implementation.

## Multi-Book Scheduling Later

Do not implement multi-book scheduling before page-level artifacts and one-book
parallelism are solid.

After one-document scheduling works, add:

```text
DocumentQueue
GlobalWorkerBudget
FairDocumentScheduler
```

Responsibilities:

- run 2-3 books concurrently by default
- reserve a per-book page worker budget
- prevent one giant book from starving other books
- retry failed documents
- expose aggregate progress across all documents

This belongs above `OcrDocumentRunner`, not inside page workers.

## Future Indexing Hook

When page artifacts are written, emit an event or callback:

```text
on_page_ocr_complete(page_result)
```

Later this can trigger:

- chunking
- embeddings
- vector index writes
- source map updates

Do not build the full indexer in the OCR parallelism task. Just leave a clean
hook and artifact structure.

## Risk Areas

### Windows Process Spawning

`ProcessPoolExecutor` on Windows requires worker functions to be importable at
module top level.

Do not define process worker functions inside another function.

### Pickle Boundaries

Only pass simple dataclasses and primitive values into workers.

Do not pass:

- `PdfDocument`
- PIL images
- `pytesseract` modules
- model instances
- open file handles

### OCR Engine Thread Oversubscription

Set:

```text
OMP_THREAD_LIMIT=1
```

for Tesseract parallel workers unless overridden.

### GPU Backends

Do not parallelize EasyOCR/Paddle GPU mode with one process per page initially.
That can reload models repeatedly and exhaust GPU memory.

Use long-lived GPU workers later.

### Partial Failures

Large books should not fail completely because one page fails.

Page failures should be recorded and retried independently.

### Test Runtime

Do not add slow OCR tests to the default suite.

Use mocks for unit tests and optional markers for live OCR integration tests.

## Definition Of Done

The implementation is complete when:

- `pdf-extract ocr-parallel --help` exists
- Tesseract page-level parallel OCR works for a page range
- worker count can be manual or auto-selected
- OCR page artifacts are written independently
- failed pages are retried and reported
- final merged output preserves page order
- outline small OCR fallback no longer triggers full-document OCR
- EasyOCR/Paddle sequential extractors no longer eager-rasterize full PDFs
- unit tests cover planning, worker behavior, storage, merging, and scheduling
- README documents install and usage

Stretch goal:

- calibration can benchmark candidate worker counts and cache the selected plan

Do not block the first production-useful version on:

- multi-book queueing
- streaming embeddings
- PageIndex integration
- GPU worker pools
- full adaptive throttling
