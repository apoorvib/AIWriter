# EssayWriter

EssayWriter turns uploaded source documents and an assignment prompt into a
grounded, human-sounding academic essay. It runs a multi-stage pipeline —
source ingestion, topic ideation, research, outlining, drafting, an anti-AI
audit, validation with revision loops, and Markdown export — on top of a Python
document-extraction pipeline (text-native PDF, OCR, and `.docx`).

## Three ways to run EssayWriter

EssayWriter can be driven three ways. **Use the Dynamic Workflows path** — it is
the most stable and best-performing today. The other two are under active
development.

| Mode | What it is | Status |
| --- | --- | --- |
| **Dynamic Workflows** (`/essay-prep` → `/essay-write`) | Two saved Claude Code workflows that drive the whole pipeline end-to-end for you. | ✅ **Recommended — most stable** |
| **Agent Tool Mode (MCP, manual)** | The same pipeline exposed as local MCP tools, driven by hand (manual Claude Code, Codex, or other harnesses). | 🚧 Under development |
| **Web App / Orchestrator (Pipeline Mode)** | A FastAPI backend that owns workflow state and makes its *own* LLM API calls, with a Vite/React frontend. | 🚧 Under development |

The Dynamic Workflows and manual MCP paths share the same local MCP tool layer
(Agent Tool Mode): the app never makes hidden LLM calls; your harness reads
prepared work packets, produces JSON with its own model, and commits validated
artifacts back. The workflows just script that tool sequence so no required step
is skipped. The Orchestrator path is different — there the backend calls the LLM
itself.

**Start here → [Dynamic Workflows](#dynamic-workflows-recommended).**

## Install

```bash
pip install -e .
```

For development and tests:

```bash
pip install -e ".[dev]"
```

Optional OCR extras:

```bash
pip install -e ".[ocr-small]"   # Tesseract tier
pip install -e ".[ocr-medium]"  # EasyOCR tier
pip install -e ".[ocr-high]"    # PaddleOCR tier
pip install -e ".[ocr-small,ocr-scheduler]"  # Tesseract + parallel scheduler
```

Agent Tool Mode (MCP) tools:

```bash
pip install -e ".[agent-tools]"
```

Web app (Orchestrator / Pipeline Mode) dependencies:

```bash
pip install -e ".[web]"
```

## Dynamic Workflows (recommended)

In Claude Code you can drive the whole Agent Tool Mode pipeline with two saved
[Dynamic Workflows](https://code.claude.com/docs/en/workflows) in
`.claude/workflows/` instead of calling the MCP tools by hand. They move the
step sequence into a script so no required step is skipped, and they are split
at the mandatory topic-selection gate (a workflow cannot pause for input
mid-run). This is the recommended way to run EssayWriter.

Prerequisites:

- Claude Code v2.1.154+ with Dynamic workflows enabled (toggle in `/config`).
- The `essaywriter` MCP server configured (copy `.mcp.example.json` to
  `.mcp.json`) and pointed at your `ESSAY_DATA_DIR`.
- `mcp__essaywriter__*` pre-allowlisted (already in `.claude/settings.json`) so
  the background workflow subagents are not blocked by mid-run permission
  prompts.
- Source documents on disk. Optionally, one or two short writing samples in your
  own voice (convention: `inputs/writing_style/`) for anti-AI voice calibration.

**How you pass inputs.** You do not type raw JSON. A Dynamic Workflow reads a
global called `args`; when you invoke the command you describe the inputs in
plain language and Claude maps your words onto the fields the script documents in
its header comment. The examples below show what you type and the `args` Claude
builds from it.

**Step 1 — prep (runs to the topic gate).** `/essay-prep` accepts
`source_paths` (list), `writing_style_paths` (list or `"skip"`), and
`assignment_text` **or** `assignment_path`. Type the command followed by a normal
sentence:

```text
/essay-prep Use these sources: ./inputs/sources/carbon-pricing.pdf and
./inputs/sources/ipcc-summary.pdf. My writing sample is at
./inputs/writing_style/my-old-essay.md. Assignment: Write a 1500-word
argumentative essay on whether carbon pricing is effective climate policy,
cite at least two sources, MLA format.
```

Claude turns that into:

```js
args = {
  source_paths: [
    "./inputs/sources/carbon-pricing.pdf",
    "./inputs/sources/ipcc-summary.pdf",
  ],
  writing_style_paths: ["./inputs/writing_style/my-old-essay.md"],
  assignment_text: "Write a 1500-word argumentative essay on whether carbon pricing...",
}
```

Variations: say "skip the writing style step" for `writing_style_paths: "skip"`;
point at a file ("the assignment is in `./inputs/assignment.txt`") to use
`assignment_path` instead of `assignment_text`.

The workflow ingests the sources, writes a source card for each, commits a task
spec, creates the job, then **stops and prints the candidate topics**, e.g.:

```text
Prep complete — agent_run_id: agrun_20260630_a1b2c3
Choose a topic, then run /essay-write:
  1. topic_001 — "Carbon pricing vs. cap-and-trade: ..."
  2. topic_002 — "Why revenue recycling determines carbon-tax effectiveness"
  3. topic_003 — ...
(job_id: job-prov-agrun_20260630_a1b2c3)
```

Copy the `agent_run_id`, the `job_id`, and the `topic_id` you want — those feed
step 2.

**Step 2 — pick a topic, then write (runs to export).** `/essay-write` accepts
`agent_run_id`, `job_id`, `round_number` (usually `1`), `topic_id` (the one you
picked), and `user_selection_evidence` (a sentence on why — this is required; the
server refuses a topic chosen with no reasoning). Type:

```text
/essay-write Continue agent_run_id agrun_20260630_a1b2c3, job_id
job-prov-agrun_20260630_a1b2c3, round 1. I'm picking topic_002 because it has
the strongest source evidence and directly matches the assignment's focus on
policy effectiveness.
```

Claude turns that into:

```js
args = {
  agent_run_id: "agrun_20260630_a1b2c3",
  job_id: "job-prov-agrun_20260630_a1b2c3",
  round_number: 1,
  topic_id: "topic_002",
  user_selection_evidence: "strongest source evidence; matches the assignment's focus on policy effectiveness",
}
```

It records your topic selection, then runs research → outline → draft → anti-AI
audit (in a fresh frontier subagent) → validation (with revision loops) →
Markdown export.

The mental model: prep's inputs are *file paths + the assignment*; write's inputs
are *the three ids prep printed + your chosen `topic_id` + one line of reasoning*.
You never hand-write `args` — you say it in words and Claude fills the fields from
the script's header.

**Why no step gets skipped.** Both scripts loop on the read-only
`get_workflow_progress(agent_run_id)` ledger, which derives from persisted state
which required steps are actually done, and act only on the server's
`next_required_step` until it reports `all_required_done`. A step whose artifact
did not really persist stays `pending` and is re-attempted rather than skipped.
Codex and other MCP harnesses drive the same tools manually (see
`docs/agent-tool-mode-instructions.md`).

> The workflow scripts are authored against the Dynamic Workflows runtime;
> confirm the `agent()` call shape for your Claude Code version on first run (see
> the header comment in each `.claude/workflows/*.js`).

## Agent Tool Mode (MCP, manual)

> 🚧 Under development. This is the raw MCP tool layer the recommended Dynamic
> Workflows run on top of. The tools themselves are what the workflows use;
> driving them *by hand* — or from other harnesses such as Codex — is still
> being stabilized. On Claude Code, prefer the workflows above.

Agent Tool Mode exposes the essay workflow as local MCP tools for harnesses such
as Claude Code and Codex. In this mode the app does not make hidden LLM API
calls for reasoning stages: the harness reads prepared work packets, produces
JSON with its own model, and commits validated artifacts back to the app.

Run the MCP server:

```bash
ESSAY_DATA_DIR=./data python -m essay_writer.agent_tools.server
```

See `docs/agent-tool-mode-mcp.md` and `.mcp.example.json` for configuration, and
`docs/agent-tool-mode-instructions.md` for the manual step sequence other
harnesses follow. Source-access bounds (max packets, pages, chars, lazy OCR) are
configured via `ESSAY_*` env vars; see
[docs/orchestrator-architecture.md](docs/orchestrator-architecture.md#configuration).

## Web App / Orchestrator (Pipeline Mode)

> 🚧 Under development. Here the FastAPI backend owns workflow state and makes
> its own LLM API calls end-to-end.

Run the API from the repository root:

```bash
uvicorn backend.app:app --host 127.0.0.1 --port 8629 --reload
```

Install and run the Vite frontend in another terminal:

```bash
cd frontend
npm install
npm run dev
```

The frontend runs at `http://127.0.0.1:3527` by default and proxies `/api`
requests to `http://127.0.0.1:8629`. Vite preview uses `http://127.0.0.1:4627`.

The full architecture — the stage-by-stage pipeline, human-in-the-loop gates,
per-step LLM usage, the prompt inventory, and configuration env vars — is
documented in
[docs/orchestrator-architecture.md](docs/orchestrator-architecture.md).

## Document Extraction Pipeline

Underneath the essay workflow is a Python extraction pipeline for source
documents. It supports:

- text-native PDFs
- OCR extraction for PDFs
- modern Word `.docx` files

### Why `pypdf`

`pypdf` is distributed under a permissive BSD-style license, which is commonly
compatible with both open-source and closed-source projects.

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
