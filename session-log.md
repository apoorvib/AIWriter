# Session Log

Chronological log of agent sessions. Add a new entry whenever an agent changes code, tests, docs, dependencies, or configuration.

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
