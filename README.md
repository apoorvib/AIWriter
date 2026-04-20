# Document Extraction Pipeline

This repository contains a Python extraction pipeline for source documents used
by the essay writer system. It currently supports:

- text-native PDFs
- OCR extraction for PDFs
- modern Word `.docx` files

## Why `pypdf`

`pypdf` is distributed under a permissive BSD-style license, which is commonly
compatible with both open-source and closed-source projects.

## Install

```bash
pip install -e .
```

For development and tests:

```bash
pip install -e ".[dev]"
```

Install optional OCR extras as needed:

```bash
pip install -e ".[ocr-small]"   # Tesseract tier
pip install -e ".[ocr-medium]"  # EasyOCR tier
pip install -e ".[ocr-high]"    # PaddleOCR tier
pip install -e ".[ocr-small,ocr-scheduler]"  # Tesseract + parallel scheduler
```

Install the web API dependencies when running the local app:

```bash
pip install -e ".[web]"
```

Install the Vite frontend dependencies:

```bash
cd frontend
npm install
```

## Web App Usage

Run the API from the repository root:

```bash
uvicorn backend.app:app --reload
```

Run the frontend in another terminal:

```bash
cd frontend
npm run dev
```

The frontend dev server proxies `/api` requests to `http://localhost:8000`.
The app supports source uploads for `.pdf`, `.docx`, `.txt`, `.md`,
`.markdown`, and `.notes` files. Assignment text can be pasted or extracted
from the same document types.

## CLI Usage

```bash
pdf-extract extract path/to/file.pdf --mode text_only
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier small
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier medium --ocr-lang en --ocr-lang fr
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier high --ocr-gpu
```

For Tesseract-backed small OCR, the pipeline maps `--ocr-lang en` to
Tesseract's `eng` language code automatically.

For page-level parallel OCR with the Tesseract-backed small tier:

```bash
pdf-extract ocr-parallel path/to/file.pdf --ocr-tier small --workers auto --max-pages 10
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --workers 4 --store ./ocr_store
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --workers auto --calibrate --max-pages 20
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --document-id my-book --resume
```

The parallel command writes page artifacts and a merged result under `ocr_store`
by default. Use `--calibrate` with `--workers auto` to benchmark a few sample
pages and select a measured worker count. Use `--resume` with a stable
`--document-id` to reuse already-completed page artifacts after an interrupted
run. Medium and high OCR tiers remain sequential for now; they are kept
compatible but are not yet parallelized because EasyOCR/PaddleOCR need
backend-specific worker handling, especially for GPU mode.

The CLI prints JSON with:
- source path
- page count
- page-wise text payloads

## Python Usage

For generic document reading:

```python
from pdf_pipeline import DocumentReader

reader = DocumentReader()
result = reader.extract("path/to/assignment-or-source.docx")
print(result.pages[0].text)
```

For PDF-specific extraction modes:

```python
from pdf_pipeline.modes import ExtractionMode
from pdf_pipeline.ocr import OcrConfig, OcrTier
from pdf_pipeline.pipeline import ExtractionPipeline

pipeline = ExtractionPipeline(
    mode=ExtractionMode.OCR_ONLY,
    ocr_tier=OcrTier.MEDIUM,
    ocr_config=OcrConfig(languages=("en",), dpi=300, use_gpu=False),
)
result = pipeline.extract("path/to/file.pdf")
for page in result.pages:
    print(page.page_number, page.char_count, page.text[:80])
```

## Notes

- `ExtractionMode.AUTO` is intentionally not implemented yet.
- `.docx` files are returned as one logical page because Word documents do not
  store stable page boundaries without rendering.
- Legacy `.doc` files are not supported. Convert them to `.docx` first.
- OCR tiers:
  - `small`: Tesseract
  - `medium`: EasyOCR
  - `high`: PaddleOCR (PP-OCRv4)
- Encrypted PDFs raise `EncryptedPdfError`.
- Corrupt/unreadable PDFs raise `InvalidPdfError`.
- Missing optional OCR packages raise `MissingDependencyError`.

## OCR Prerequisites

- `ocr-small` requires the Tesseract binary installed on your system and
  available in PATH.
- `ocr-medium` and `ocr-high` may download model weights on first run.
- GPU behavior depends on backend/runtime installation (`torch`/`paddle`).

## Third-Party Licenses

See `docs/THIRD_PARTY_LICENSES.md`.
