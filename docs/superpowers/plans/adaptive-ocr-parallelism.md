# Adaptive OCR Parallelism Plan

## Purpose

Build an OCR scheduling layer that can process large PDFs and multiple books
efficiently by adapting concurrency to the underlying machine, OCR backend, and
document workload.

The current CLI-oriented OCR path is useful for correctness checks, but it is
not the right production shape for indexing multiple books. Production ingestion
should parallelize across books and across pages, store page artifacts
independently, and merge/index results asynchronously.

## Problem Statement

Large scanned PDFs are slow to OCR when processed sequentially:

```text
page 1 -> page 2 -> page 3 -> ... -> page N
```

This underuses many machines because one OCR process often does not saturate all
CPU cores. A workstation with 64GB RAM can still feel slow if the pipeline is
only running one OCR task at a time.

The bottleneck is usually a mix of:

- PDF rasterization
- image preprocessing
- OCR engine runtime
- subprocess startup overhead
- disk I/O
- Python orchestration overhead
- OCR engine internal threading
- CPU cache contention
- GPU saturation, if GPU-backed OCR is used

More RAM helps avoid memory pressure, but it does not make one sequential OCR
job use all available CPU.

## Core Principle

Parallelize OCR at the orchestration layer.

Do not rely on one OCR invocation to maximize machine utilization. Instead,
split the work into independently retryable page tasks and schedule those tasks
under a concurrency budget.

Recommended shape:

```text
Book-level parallelism:
  process multiple books at once

Page-level parallelism:
  process multiple pages from the same book at once
```

## Target Production Pipeline

```text
Document uploaded
  |
  v
Create document OCR job
  |
  v
Inspect PDF metadata and page count
  |
  v
Select OCR backend and DPI
  |
  v
Detect machine resources
  |
  v
Choose initial concurrency
  |
  v
Optionally run calibration benchmark
  |
  v
Enqueue page OCR tasks
  |
  v
Workers render and OCR pages
  |
  v
Store page artifacts
  |
  v
Chunk/index completed pages
  |
  v
Merge ordered document artifact
  |
  v
Mark document OCR/index complete
```

## Work Breakdown

### Document Job

A document job represents OCR/indexing for one uploaded PDF.

Fields:

- `document_id`
- `source_path`
- `source_hash`
- `page_count`
- `ocr_backend`
- `dpi`
- `languages`
- `status`
- `created_at`
- `updated_at`
- `started_at`
- `completed_at`
- `selected_worker_count`
- `calibration_profile_id`
- `error_state`

Recommended statuses:

- `queued`
- `inspecting`
- `calibrating`
- `page_tasks_queued`
- `ocr_running`
- `ocr_done`
- `indexing_running`
- `indexed`
- `complete`
- `failed`

### Page Job

A page job represents one page of one document.

Fields:

- `document_id`
- `page_number`
- `ocr_backend`
- `dpi`
- `languages`
- `status`
- `attempt_count`
- `worker_id`
- `started_at`
- `completed_at`
- `rasterization_ms`
- `ocr_ms`
- `normalization_ms`
- `char_count`
- `artifact_path`
- `error_message`

Recommended statuses:

- `queued`
- `rendering`
- `ocr_running`
- `ocr_done`
- `indexing_queued`
- `indexed`
- `failed`
- `retrying`

### Page Artifact

Store one artifact per page.

Example:

```json
{
  "document_id": "doc_123",
  "page_number": 42,
  "ocr_backend": "tesseract",
  "dpi": 300,
  "languages": ["eng"],
  "text": "...",
  "char_count": 1832,
  "rasterization_ms": 420,
  "ocr_ms": 1830,
  "created_at": "..."
}
```

Page artifacts should be idempotent and independently retryable.

The artifact key should include the OCR configuration:

```text
document_id + page_number + ocr_backend + dpi + languages
```

This prevents accidental reuse of OCR output generated with different settings.

## Parallelization Strategy

### Book-Level Parallelism

For multiple books, process more than one book at a time.

Example:

```text
Book A: page workers 1-4
Book B: page workers 5-8
Book C: page workers 9-12
```

This is usually better than letting one large book monopolize all workers.

Benefits:

- better fairness across uploads
- simpler failure isolation
- faster first result for multiple documents
- easier retry behavior
- prevents one huge document from blocking the queue

Initial default:

```text
max_concurrent_books = 2 or 3
page_workers_per_book = 2 to 4
```

Tune later based on hardware and benchmark data.

### Page-Level Parallelism

Within a book, pages are mostly independent.

Instead of:

```text
page 1 -> page 2 -> page 3 -> ... -> page 900
```

Use a dynamic page queue:

```text
worker 1: next available page
worker 2: next available page
worker 3: next available page
worker 4: next available page
```

Dynamic scheduling is better than statically assigning page ranges because some
pages take much longer than others. A dense page, image-heavy page, or noisy scan
can take significantly longer than a simple text page.

Final document order should be restored by sorting page artifacts by
`page_number`.

## Hardware Factors

Optimal concurrency depends on the machine.

Relevant machine stats:

- physical CPU cores
- logical CPU threads
- CPU model and generation
- CPU cache size
- available RAM
- disk type and throughput
- GPU availability
- GPU memory
- operating system
- OCR backend availability

Relevant workload stats:

- page count
- page size
- scan resolution
- selected OCR DPI
- language pack
- image noise
- text density
- tables/figures
- whether PDF already has embedded text

Relevant backend stats:

- Tesseract subprocess behavior
- OpenMP thread usage
- PyTorch thread usage for EasyOCR
- Paddle runtime thread usage
- GPU saturation behavior

## Static Hardware Heuristic

Use a safe default before calibration.

For CPU-backed Tesseract OCR:

```text
physical_cores = detected physical CPU cores
logical_cores = detected logical CPU threads
available_ram_gb = detected available RAM
configured_max_workers = user or deployment cap

memory_per_worker_gb = 1.0 to 1.5

default_workers = min(
  physical_cores,
  floor(available_ram_gb / memory_per_worker_gb),
  configured_max_workers
)
```

For a laptop or shared workstation, use a conservative cap:

```text
default_workers = min(max(1, physical_cores // 2), 8)
```

For a dedicated OCR server:

```text
default_workers = min(physical_cores, 16)
```

These are starting points, not guaranteed optima.

## Runtime Calibration

The system should optionally benchmark a small sample of pages and choose the
best worker count for the current machine/backend/DPI.

Calibration workflow:

```text
1. Pick representative sample pages.
2. Pick candidate worker counts.
3. Run OCR benchmark for each candidate.
4. Measure throughput and resource pressure.
5. Pick best stable worker count.
6. Cache the tuning result.
7. Use cached result for similar future jobs.
```

### Sample Page Selection

Sample pages should represent the document.

For a long book:

```text
sample_pages = [
  first useful content page,
  second useful content page,
  middle page,
  later middle page,
  last useful content page
]
```

Avoid only testing the cover page or blank pages. They can distort the result.

For books with many pages:

```text
sample_count = 5 to 10 pages
```

For short documents:

```text
sample_count = min(page_count, 5)
```

### Candidate Worker Counts

Candidate worker counts should be bounded by machine capacity.

Example:

```text
base_candidates = [1, 2, 4, 6, 8, 12, 16]
candidates = [c for c in base_candidates if c <= max_candidate_workers]
```

For shared machines:

```text
max_candidate_workers = min(physical_cores // 2, 8)
```

For dedicated OCR servers:

```text
max_candidate_workers = min(physical_cores, 16 or 24)
```

### Calibration Metrics

Measure:

- pages per second
- pages per minute
- seconds per page
- rasterization time
- OCR time
- normalization time
- CPU utilization
- memory usage
- disk read/write pressure
- OCR failures
- process crashes
- timeout count

Separate rasterization timing from OCR timing. Sometimes rasterization, not OCR,
is the real bottleneck.

### Scoring Function

Pick the worker count with the best stable throughput.

A simple scoring model:

```text
score = pages_per_minute

penalty if memory_usage > 85%
penalty if OCR failures > 0
penalty if timeout rate > 0
penalty if CPU pressure causes worse throughput
penalty if system is configured as shared/interactive
```

Do not always pick the highest worker count. The best value is usually the
throughput knee, where adding more workers no longer improves pages per minute.

## Tuning Profile Cache

Cache calibration results.

Fields:

- `profile_id`
- `machine_fingerprint`
- `ocr_backend`
- `dpi`
- `languages`
- `physical_cores`
- `logical_cores`
- `ram_gb`
- `gpu_name`
- `gpu_memory_gb`
- `candidate_results`
- `selected_worker_count`
- `measured_pages_per_minute`
- `created_at`
- `expires_at`

Machine fingerprint inputs:

- CPU model
- physical core count
- logical core count
- total RAM
- GPU model
- operating system
- OCR backend version

Invalidate or refresh the profile when:

- OCR backend changes
- DPI changes
- language changes
- CPU/RAM/GPU changes
- OCR package version changes
- measured throughput degrades significantly
- profile is older than a configured TTL

Suggested TTL:

```text
7 to 30 days
```

## Backend-Specific Guidance

### Tesseract

Tesseract is usually best parallelized by running multiple page workers.

Recommended:

```text
OMP_THREAD_LIMIT=1
process-based workers
start with physical_cores // 2
benchmark up to physical_cores
```

Why set `OMP_THREAD_LIMIT=1`:

Tesseract may use OpenMP internally. If each worker spawns multiple internal
threads, running many workers can oversubscribe the CPU and reduce throughput.
Limiting internal threads often improves total page throughput when multiple OCR
workers run in parallel.

Initial worker ranges:

```text
local workstation: 4 to 8 total workers
dedicated server: 8 to 16 total workers
```

But always benchmark.

### EasyOCR

EasyOCR uses PyTorch. Its concurrency behavior depends on CPU/GPU setup.

CPU mode:

```text
start with 1 to 2 workers
benchmark carefully
watch PyTorch internal thread usage
```

GPU mode:

```text
usually 1 worker per GPU
prefer batching pages instead of many processes
```

Running many EasyOCR workers against one GPU can reduce throughput because the
workers compete for GPU memory and scheduling.

### PaddleOCR

PaddleOCR can run on CPU or GPU.

CPU mode:

```text
start with 2 to 4 workers
watch internal runtime threading
benchmark before increasing
```

GPU mode:

```text
usually 1 worker per GPU
use a queue feeding the GPU worker
batch where supported
```

For GPU-backed OCR, model loading time and GPU memory are important. Avoid
spawning many independent model processes unless the GPU can handle them.

### Cloud OCR / PageIndex

For cloud OCR providers, local CPU is not the main bottleneck.

Primary limits become:

- provider rate limits
- upload bandwidth
- document size
- per-page cost
- API latency
- retry/backoff behavior

Concurrency should be controlled by:

```text
max_concurrent_uploads
max_concurrent_pollers
provider_rate_limit
monthly/page credit budget
```

Do not apply local CPU worker heuristics to cloud OCR.

## Threads vs Processes

For CPU OCR, prefer process-based parallelism.

Use:

```text
ProcessPoolExecutor
```

Avoid relying on:

```text
ThreadPoolExecutor
```

Reasons:

- OCR is CPU-heavy.
- Python's GIL can interfere with CPU-bound Python code.
- OCR libraries often call native code and subprocesses.
- process isolation is more robust against memory leaks.
- per-page crashes are easier to contain.
- workers can be restarted cleanly.

For GPU OCR, a long-lived process per GPU is often better than spawning many
short-lived processes.

## Adaptive Throttling

Calibration picks a starting point. The scheduler should still monitor the
system during long runs.

Throttle down when:

- memory usage exceeds 85%
- OCR failures increase
- page timeouts increase
- disk queue becomes saturated
- CPU is pegged but throughput decreases
- the machine is marked as shared/interactive

Scale up when:

- CPU usage is low
- memory has headroom
- queue backlog is large
- failure rate is zero
- throughput improves in recent windows

Keep adaptive changes conservative:

```text
increase by 1 or 2 workers at a time
decrease faster on failures or memory pressure
```

Avoid rapid oscillation by using a cooldown period:

```text
cooldown = 30 to 120 seconds
```

## Manual Overrides

Auto-tuning should never be the only control.

Support environment variables:

```text
OCR_MAX_WORKERS=6
OCR_MAX_CONCURRENT_BOOKS=2
OCR_PAGE_WORKERS_PER_BOOK=3
OCR_OMP_THREAD_LIMIT=1
OCR_CALIBRATE=true
OCR_SHARED_MACHINE=true
```

Support config file settings:

```toml
[ocr]
max_workers = 6
max_concurrent_books = 2
page_workers_per_book = 3
omp_thread_limit = 1
calibrate = true
shared_machine = true
```

Manual settings should take precedence over calibration.

## Indexing Integration

Do not wait for a whole OCR job to complete before indexing starts.

Preferred streaming shape:

```text
page rendered
  -> page OCR complete
  -> page text normalized
  -> page artifact stored
  -> page chunked
  -> page embeddings generated
  -> page chunks indexed
```

This gives faster time-to-first-search and reduces memory pressure.

The final document reducer should:

```text
collect page artifacts
sort by page number
merge text
create document-level metadata
write final document artifact
mark OCR complete
```

## Failure Handling

Each page should be independently retryable.

Retry policy:

```text
max_attempts = 2 or 3
retry transient OCR failures
retry rasterization failures if backend-specific
do not retry deterministic unsupported-file errors
```

If a page repeatedly fails:

- mark page as failed
- preserve error message
- continue processing other pages
- mark document as partially complete
- allow manual retry or alternate backend

For production, avoid failing a 900-page book because one page failed.

## Observability

OCR needs detailed tracing because performance problems are common.

Log at document level:

- document id
- source path or object key
- page count
- OCR backend
- DPI
- language
- selected worker count
- calibration profile
- total runtime
- pages per minute
- failure count

Log at page level:

- page number
- rasterization time
- OCR time
- text char count
- worker id
- attempt count
- error message

Expose metrics:

- `ocr_pages_completed_total`
- `ocr_pages_failed_total`
- `ocr_seconds_per_page`
- `ocr_pages_per_minute`
- `ocr_queue_depth`
- `ocr_worker_count`
- `ocr_memory_usage_percent`
- `ocr_cpu_usage_percent`
- `ocr_rasterization_ms`
- `ocr_engine_ms`

## Local CLI Role

The CLI should remain useful for smoke tests and debugging.

Examples:

```powershell
pdf-extract -v extract testpdfs\book.pdf --mode ocr_only --ocr-tier small --max-pages 5
```

Production should not rely on one CLI command for full ingestion.

Production should call an OCR job system:

```text
create_document_job(book.pdf)
enqueue_page_jobs(document_id)
workers_process_pages()
store_page_artifacts()
merge_document_result()
index_document()
```

## Recommended Initial Implementation

### Phase 1: Page Range and Smoke Tests

Already started:

- support `--start-page`
- support `--max-pages`
- stream Tesseract page rasterization instead of rasterizing the whole PDF first
- add verbose logs per page

Next additions:

- expose page-level OCR function
- return page artifacts independently
- write one page artifact per processed page

### Phase 2: Local Page Worker Pool

Add a local scheduler for one document:

```text
input: document path, page range, backend, DPI, language, worker count
output: page artifacts + merged document artifact
```

Use:

```text
ProcessPoolExecutor
```

Start with Tesseract only.

Requirements:

- preserve page order in final output
- retry failed pages
- log per-page timings
- support max worker override
- set `OMP_THREAD_LIMIT=1` by default for Tesseract

### Phase 3: Hardware Detection

Detect:

- physical cores
- logical cores
- total RAM
- available RAM
- CPU model when available
- GPU availability when relevant

Potential Python packages:

- `psutil` for CPU/RAM/process metrics
- backend-specific GPU checks later

Use the static heuristic to choose default workers.

### Phase 4: Calibration

Add optional calibration mode:

```text
sample representative pages
benchmark candidate worker counts
pick best stable throughput
cache result
```

Start with candidates:

```text
[1, 2, 4, 6, 8]
```

Expand candidates only on larger dedicated machines.

### Phase 5: Multi-Book Scheduling

Add document-level queueing:

```text
max_concurrent_books
page_workers_per_book
global_worker_budget
```

Prevent one document from taking all workers.

Use fair scheduling:

```text
round-robin documents
or weighted fair queueing
```

### Phase 6: Streaming Indexing

As each page completes:

```text
chunk page text
generate embeddings
write index records
```

This makes large books searchable before the full OCR run finishes.

### Phase 7: Backend-Specific Optimization

Add separate tuning profiles for:

- Tesseract
- EasyOCR CPU
- EasyOCR GPU
- PaddleOCR CPU
- PaddleOCR GPU
- PageIndex/cloud OCR

Each backend should have separate concurrency rules.

## Initial Default Settings

For local Tesseract OCR:

```text
OMP_THREAD_LIMIT=1
calibrate=false by default in CLI
calibrate=true by default in production ingestion
max_workers=min(physical_cores // 2, 8)
max_concurrent_books=2
page_workers_per_book=2 to 4
```

For a dedicated OCR server:

```text
OMP_THREAD_LIMIT=1
calibrate=true
max_workers=min(physical_cores, 16)
max_concurrent_books=2 to 4
page_workers_per_book=4
```

## Open Questions

- Should production OCR run on the app server or a separate worker pool?
- Should OCR workers run in containers?
- Should page images be stored, or only text artifacts?
- How long should raw page artifacts be retained?
- Should failed pages block final indexing or produce a partial document?
- Which backend is the production default for scanned books?
- Should PageIndex be used automatically for complex scans or only manually?
- What is the maximum acceptable cost per indexed book?
- Should calibration run once per machine or per document batch?
- How should the system detect blank/cover/index pages for sampling?

## Recommendation

Build adaptive OCR parallelism in this order:

1. Page-level OCR artifacts.
2. Local Tesseract worker pool.
3. Static hardware-based worker heuristic.
4. Manual worker override.
5. Calibration benchmark.
6. Multi-book scheduling.
7. Streaming indexing.
8. Backend-specific tuning for EasyOCR, PaddleOCR, and PageIndex.

The end state should be:

```text
safe hardware heuristic
  + short benchmark calibration
  + manual override
  + adaptive throttling
```

That gives good defaults across laptops, desktops, and servers while still
allowing explicit control when running on unusual machines or cloud workers.
