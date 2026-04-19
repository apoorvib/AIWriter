# Parallel OCR for Outline Extraction — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Parallelize the Layer 2 TOC window OCR in the outline pipeline by delegating to `run_parallel_ocr` scoped to the first `max_toc_pages` pages, using a temp store discarded after the call.

**Architecture:** `_load_pages_text` gains `parallel_workers` and `calibrate` params; when set it calls a new `_parallel_ocr_pages` helper that invokes `run_parallel_ocr` with `max_pages=scan_pages` and a `tempfile.mkdtemp()` store, converts the result to `dict[int, str]`, and cleans up. `extract_outline` threads the new params down. CLI gets `--parallel-workers` and `--calibrate` on the `outline` subparser.

**Tech Stack:** Python stdlib `tempfile`/`shutil`, existing `run_parallel_ocr` / `ParallelOcrConfig` from `pdf_pipeline.ocr_parallel`.

---

## File Map

| File | Change |
|---|---|
| `pdf_pipeline/outline/pipeline.py` | Add `_parallel_ocr_pages` helper; add `parallel_workers`/`calibrate` params to `_load_pages_text` and `extract_outline`. |
| `pdf_pipeline/cli.py` | Add `--parallel-workers` and `--calibrate` to `outline` subparser; forward to `extract_outline` in `_cmd_outline`. |
| `tests/outline/test_pipeline.py` | Add two tests: one for `_load_pages_text` parallel branch, one for `extract_outline` signature passthrough. |
| `tests/test_cli.py` | New file. Add test for `outline` subparser arg parsing. |

---

## Task 1: `_parallel_ocr_pages` helper + updated `_load_pages_text`

**Files:**
- Modify: `pdf_pipeline/outline/pipeline.py`
- Test: `tests/outline/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/outline/test_pipeline.py`:

```python
def test_load_pages_text_parallel_calls_run_parallel_ocr(tmp_path, monkeypatch):
    from unittest.mock import MagicMock
    import pdf_pipeline.ocr_parallel as par_mod
    from pdf_pipeline.models import DocumentExtractionResult, PageText
    from pdf_pipeline.ocr import OcrConfig, OcrTier
    from pdf_pipeline.outline import pipeline as pipeline_mod

    fake_pages = [
        PageText(page_number=i, text=f"text {i}", char_count=6, extraction_method="ocr:small")
        for i in range(1, 4)
    ]
    fake_result = DocumentExtractionResult(source_path="x.pdf", page_count=10, pages=fake_pages)
    fake_summary = MagicMock()
    captured = {}

    def fake_run_parallel_ocr(pdf_path, config):
        captured["config"] = config
        return fake_summary, fake_result

    monkeypatch.setattr(par_mod, "run_parallel_ocr", fake_run_parallel_ocr)

    result = pipeline_mod._load_pages_text(
        "x.pdf",
        total_pages=10,
        max_pages=3,
        ocr_tier=OcrTier.SMALL,
        ocr_config=OcrConfig(languages=("en",), dpi=200),
        parallel_workers=2,
        calibrate=False,
    )

    assert result == {1: "text 1", 2: "text 2", 3: "text 3"}
    cfg = captured["config"]
    assert cfg.max_pages == 3
    assert cfg.workers == 2
    assert cfg.dpi == 200
    assert cfg.languages == ("en",)
    assert cfg.calibrate is False
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/outline/test_pipeline.py::test_load_pages_text_parallel_calls_run_parallel_ocr -v
```

Expected: `FAILED` — `_load_pages_text` doesn't have `parallel_workers` param yet.

- [ ] **Step 3: Add `_parallel_ocr_pages` and update `_load_pages_text` in `pipeline.py`**

Add the following import at the top of `pdf_pipeline/outline/pipeline.py` (keep lazy imports inside the helper):

No top-level import change needed — imports stay lazy inside `_parallel_ocr_pages`.

Replace the existing `_load_pages_text` signature and body in `pdf_pipeline/outline/pipeline.py`:

```python
def _load_pages_text(
    pdf_path: str,
    total_pages: int,
    max_pages: int,
    *,
    source: PageTextSource | None = None,
    lazy: bool = False,
    ocr_tier: OcrTier | None = None,
    ocr_config: OcrConfig | None = None,
    parallel_workers: int | str | None = None,
    calibrate: bool = False,
) -> Mapping[int, str]:
    """Extract text for pages 1..max_pages. Overridable in tests.

    If `source` is not provided, builds one from `ocr_tier`/`ocr_config`.
    Reusing the same `source` across calls keeps the per-page OCR cache warm.

    If `lazy=True`, returns a LazyPageTextMap that fetches pages on demand
    (used for the anchor-scan body-pages phase, where only a small fraction
    of pages are typically probed). Otherwise returns an eager dict.

    If `parallel_workers` is set (and not lazy), delegates to `_parallel_ocr_pages`
    which runs `run_parallel_ocr` scoped to the TOC window using a temp store.
    """
    if parallel_workers is not None and not lazy:
        return _parallel_ocr_pages(
            pdf_path,
            total_pages,
            max_pages,
            ocr_tier=ocr_tier,
            ocr_config=ocr_config,
            parallel_workers=parallel_workers,
            calibrate=calibrate,
        )
    if source is None:
        source = _build_page_text_source(ocr_tier=ocr_tier, ocr_config=ocr_config)
    if lazy:
        return LazyPageTextMap(source, pdf_path, total_pages)
    upper = min(total_pages, max_pages)
    pages: dict[int, str] = {}
    for p in range(1, upper + 1):
        if p == 1 or p % 25 == 0 or p == upper:
            logger.info("  extracting text for page %d/%d", p, upper)
        pages[p] = source.get(pdf_path, p).text
    return pages
```

Then add `_parallel_ocr_pages` immediately after `_load_pages_text`:

```python
def _parallel_ocr_pages(
    pdf_path: str,
    total_pages: int,
    max_pages: int,
    *,
    ocr_tier: OcrTier | None,
    ocr_config: OcrConfig | None,
    parallel_workers: int | str,
    calibrate: bool,
) -> dict[int, str]:
    import shutil
    import tempfile

    import pdf_pipeline.ocr_parallel as par_mod
    from pdf_pipeline.ocr_parallel.schema import ParallelOcrConfig

    if ocr_tier is None:
        raise ValueError("parallel_workers requires ocr_tier to be set")
    config = ocr_config or OcrConfig()
    upper = min(total_pages, max_pages)
    tmp = tempfile.mkdtemp(prefix="outline_ocr_")
    try:
        par_config = ParallelOcrConfig(
            ocr_tier=ocr_tier,
            languages=config.languages,
            dpi=config.dpi,
            use_gpu=config.use_gpu,
            start_page=1,
            max_pages=upper,
            workers=parallel_workers,
            calibrate=calibrate,
            store_path=tmp,
        )
        logger.info(
            "Parallel OCR: fetching %d pages with workers=%s calibrate=%s",
            upper,
            parallel_workers,
            calibrate,
        )
        _, result = par_mod.run_parallel_ocr(pdf_path, config=par_config)
        return {p.page_number: p.text for p in result.pages}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
```

- [ ] **Step 4: Run the test to confirm it passes**

```
pytest tests/outline/test_pipeline.py::test_load_pages_text_parallel_calls_run_parallel_ocr -v
```

Expected: `PASSED`

- [ ] **Step 5: Run the full outline test suite to confirm no regressions**

```
pytest tests/outline/ -v
```

Expected: all previously passing tests still pass (existing tests use `**_` in monkeypatched lambdas so the new kwargs are silently accepted).

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/pipeline.py tests/outline/test_pipeline.py
git commit -m "feat(outline): parallel OCR path in _load_pages_text via run_parallel_ocr"
```

---

## Task 2: Wire `parallel_workers`/`calibrate` through `extract_outline`

**Files:**
- Modify: `pdf_pipeline/outline/pipeline.py`
- Test: `tests/outline/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Add this test to `tests/outline/test_pipeline.py`:

```python
def test_extract_outline_passes_parallel_params_to_load_pages_text(tmp_path, monkeypatch):
    from pypdf import PdfWriter
    from pdf_pipeline.outline import pipeline as pipeline_mod
    from llm.mock import MockLLMClient

    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "plain.pdf"
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    captured = {}

    def fake_load_pages_text(pdf_path_, total_pages, max_pages, **kwargs):
        captured.update(kwargs)
        return {i: "narrative body text here" for i in range(1, 6)}

    monkeypatch.setattr(pipeline_mod, "_load_pages_text", fake_load_pages_text)

    client = MockLLMClient(responses=[])
    pipeline_mod.extract_outline(
        str(pdf_path),
        llm_client=client,
        source_id="s",
        parallel_workers="auto",
        calibrate=True,
    )

    assert captured.get("parallel_workers") == "auto"
    assert captured.get("calibrate") is True
```

- [ ] **Step 2: Run test to confirm it fails**

```
pytest tests/outline/test_pipeline.py::test_extract_outline_passes_parallel_params_to_load_pages_text -v
```

Expected: `FAILED` — `extract_outline` doesn't accept `parallel_workers` yet.

- [ ] **Step 3: Update `extract_outline` signature and body in `pipeline.py`**

Replace the `extract_outline` signature:

```python
def extract_outline(
    pdf_path: str | Path,
    llm_client: LLMClient,
    source_id: str,
    version: int = 1,
    max_toc_pages: int = 40,
    chunk_size: int = 5,
    max_offset: int = 100,
    ocr_tier: OcrTier | None = None,
    ocr_config: OcrConfig | None = None,
    llm_model: str | None = None,
    parallel_workers: int | str | None = None,
    calibrate: bool = False,
) -> DocumentOutline:
```

Then find the first `_load_pages_text` call inside `extract_outline` (the eager TOC scan call) and add the two new kwargs:

```python
    pages_text = _load_pages_text(
        str(pdf_path),
        total_pages,
        scan_pages,
        source=source,
        ocr_tier=ocr_tier,
        ocr_config=ocr_config,
        parallel_workers=parallel_workers,
        calibrate=calibrate,
    )
```

The second `_load_pages_text` call (the lazy anchor scan, `lazy=True`) does NOT get `parallel_workers` — leave it unchanged. `_parallel_ocr_pages` is already guarded by `not lazy`, but the anchor scan semantics are intentionally sequential.

- [ ] **Step 4: Run the test to confirm it passes**

```
pytest tests/outline/test_pipeline.py::test_extract_outline_passes_parallel_params_to_load_pages_text -v
```

Expected: `PASSED`

- [ ] **Step 5: Run the full outline test suite**

```
pytest tests/outline/ -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/pipeline.py tests/outline/test_pipeline.py
git commit -m "feat(outline): thread parallel_workers/calibrate through extract_outline"
```

---

## Task 3: CLI flags for `outline` subparser

**Files:**
- Modify: `pdf_pipeline/cli.py`
- Test: `tests/test_cli.py` (new file)

- [ ] **Step 1: Write the failing test**

Create `tests/test_cli.py`:

```python
from __future__ import annotations

import pytest
from pdf_pipeline.cli import _build_parser


def test_outline_parallel_workers_and_calibrate_parsed():
    parser = _build_parser()
    args = parser.parse_args([
        "outline", "doc.pdf",
        "--source-id", "my-doc",
        "--ocr-tier", "small",
        "--parallel-workers", "auto",
        "--calibrate",
    ])
    assert args.parallel_workers == "auto"
    assert args.calibrate is True


def test_outline_parallel_workers_integer_string():
    parser = _build_parser()
    args = parser.parse_args([
        "outline", "doc.pdf",
        "--source-id", "my-doc",
        "--parallel-workers", "4",
    ])
    assert args.parallel_workers == "4"
    assert args.calibrate is False


def test_outline_parallel_workers_defaults_to_none():
    parser = _build_parser()
    args = parser.parse_args(["outline", "doc.pdf", "--source-id", "my-doc"])
    assert args.parallel_workers is None
    assert args.calibrate is False
```

- [ ] **Step 2: Run tests to confirm they fail**

```
pytest tests/test_cli.py -v
```

Expected: all three `FAILED` — `--parallel-workers` not defined yet.

- [ ] **Step 3: Add flags to `outline` subparser in `cli.py`**

In `_build_parser`, add these two arguments to `outline_parser` (after the existing `--ocr-gpu` argument, before `outline_parser.set_defaults`):

```python
    outline_parser.add_argument(
        "--parallel-workers",
        default=None,
        dest="parallel_workers",
        metavar="N|auto",
        help=(
            "Worker count for parallel OCR of the TOC window. "
            "Use 'auto' for automatic worker planning. "
            "Omit for sequential OCR (default)."
        ),
    )
    outline_parser.add_argument(
        "--calibrate",
        action="store_true",
        help=(
            "When --parallel-workers is auto, benchmark sample pages "
            "to select the optimal worker count. Ignored when "
            "--parallel-workers is a specific integer."
        ),
    )
```

- [ ] **Step 4: Update `_cmd_outline` to forward the new params**

Replace the `extract_outline(...)` call in `_cmd_outline`:

```python
    outline = extract_outline(
        args.pdf_path,
        llm_client=client,
        source_id=args.source_id,
        ocr_tier=tier,
        ocr_config=config,
        llm_model=args.llm_model,
        parallel_workers=args.parallel_workers,
        calibrate=args.calibrate,
    )
```

- [ ] **Step 5: Run CLI tests**

```
pytest tests/test_cli.py -v
```

Expected: all three `PASSED`.

- [ ] **Step 6: Run full test suite**

```
pytest -v
```

Expected: all tests pass.

- [ ] **Step 7: Commit**

```bash
git add pdf_pipeline/cli.py tests/test_cli.py
git commit -m "feat(cli): add --parallel-workers and --calibrate to outline subcommand"
```

---

## Verification

After all tasks complete, run this command against Gray's Anatomy and confirm it exits cleanly:

```bash
python -m pdf_pipeline.cli -vv outline testpdfs/anatomydescripti1858gray.pdf \
  --source-id greys-anatomy \
  --ocr-tier small \
  --parallel-workers auto \
  --calibrate \
  > outputs/greys_anatomy_outline.txt 2>&1
```

Check `outputs/greys_anatomy_outline.txt` for outline entries and verify the debug log shows `"Parallel OCR: fetching N pages"`.
