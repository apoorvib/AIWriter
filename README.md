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

Outline extraction (`pdf-extract outline`) needs the `outline` extra plus one
LLM provider extra, because it calls a model to read the table of contents:

```bash
pip install -e ".[outline,llm-claude]"  # or llm-openai / llm-gemini / llm-all
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
step sequence into scripts and are split at the mandatory topic-selection gate
(a workflow cannot pause for input mid-run). Prep uses a fixed, server-gated
prelude; the write segment uses the persisted completion ledger to choose its
next required step. This is the recommended way to run EssayWriter.

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

**Step 2 — pick a topic, then write (normally runs to export).** `/essay-write`
accepts `agent_run_id`, `job_id`, `round_number` (usually `1`), `topic_id` (the
one you picked), and `user_selection_evidence` (a sentence on why). Supply real
selection evidence whenever possible. If this field is omitted, the current
workflow adds a generic fallback marker so `select_topic` receives a non-empty
value. Type:

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

It records your topic selection, then runs research planning and source
resolution as one workflow action, followed by research notes → outline →
draft → anti-AI audit (in a fresh frontier subagent) → validation (with
revision loops) → Markdown export. The MCP layer supports an optional style
revision pass, but the current required-step driver does not select that
recommended step automatically.

The mental model: prep's inputs are *file paths + the assignment*; write's inputs
are *the three ids prep printed + your chosen `topic_id` + one line of reasoning*.
You never hand-write `args` — you say it in words and Claude fills the fields from
the script's header.

**How progression is enforced.** `/essay-prep` runs a fixed sequence for
ingestion, source cards, writing-style handling, task specification, job
creation, and topic generation. Server gates reject missing prerequisites.
`/essay-write` repeatedly reads `get_workflow_progress(agent_run_id)` and acts
on the server's `next_required_step`; an artifact that did not persist remains
pending on the next read. The current loop is bounded to 60 iterations and does
not perform a final completion assertion before formatting its success message,
so confirm the export or call `get_workflow_progress` after unusual failures.
Codex and other MCP harnesses drive the same tools manually (see
`docs/agent-tool-mode-instructions.md`).

> The workflow scripts are authored against the Dynamic Workflows runtime;
> confirm the `agent()` call shape for your Claude Code version on first run (see
> the header comment in each `.claude/workflows/*.js`). Python tests cover the
> MCP gates and completion ledger, but the workflow JavaScript itself requires a
> manual Claude Code runtime check.

## Generic writing (`/write`)

`/write` is a separate, single Dynamic Workflow for **short-form and everyday
writing that is not a cited academic essay** — emails, texts, LinkedIn posts,
blog posts, or general prose. It shares the same "the app never makes hidden LLM
calls" tool layer, but runs its own `essay_writer.writing` domain with its own
persistence and completion ledger. It does **not** touch `EssayJob` or the
`/essay-prep`/`/essay-write` pipeline; use those for grounded, source-cited
essays and `/write` for everything else.

```text
/write immediate friendly text declining dinner tomorrow
/write detailed LinkedIn post announcing a product launch; research current market context
/write email asking for a deadline extension; skip anti-AI
/write blog comparing two current products, include sources
/write turn this launch note into an email and LinkedIn post
```

**Two modes.** `immediate` is for quick, low-stakes messages (a text, a short
email): it routes brief → draft with an embedded self-check and finalizes.
`detailed` adds a plan, an independent clean-context review, and up to two
bounded revision rounds before finalizing. The workflow infers the mode from the
request; an explicit `immediate`/`detailed` in your prompt always wins (and
detailed facts can still trigger research even in immediate mode).

**Automatic clarification.** If the request is genuinely ambiguous in a way that
would change the output (e.g. an unclear audience), the brief persists at most
three targeted questions and the run pauses with `requires_human`. It does not
ask merely to confirm a safe inference.

**Research policy.** `auto` (default) lets the brief decide whether current facts
are needed; `required` always researches; `off` never browses. Say things like
"research current market context" (→ required) or "use only what I gave you"
(→ off). Research capture is bounded: every fact must map to a disclosed HTTP(S)
source with a title and dates, quotes are capped, and undated sources are flagged
rather than presented as current evidence. The MCP server itself never makes
network calls — your harness performs the search and submits disclosed sources.

**Skills and anti-AI.** Each deliverable gets its own format skill (`email`,
`text-message`, `linkedin`, `blog`, or `general` when no narrower format fits).
The `anti-ai-detection` skill is added by default; exclude it with "skip
anti-AI". You can also force skills in or out — the exclusion is recorded in the
output metadata, and an explicitly requested unknown skill is rejected with the
list of available IDs rather than silently ignored.

**Multiple deliverables.** One run can produce several deliverables (up to five)
that share the same context and research but get separate format skills and
drafts — e.g. "turn this launch note into an email and LinkedIn post".

**Persistence and recovery.** Every run is stored under
`${ESSAY_DATA_DIR}/writing/` (runs, briefs, context, research, plans, drafts,
reviews, outputs) and is identified by a `writing_run_id` (`wrun_…`). A single
server-derived ledger is authoritative, so an interrupted run resumes from
persisted state:

```text
/write continue wrun_20260706_abcd1234 audience is existing enterprise customers
```

**Output.** The final message returns the finished text first, then a metadata
footer: the selected skills (id/version/sha256), explicit assumptions, researched
sources, any warnings, and the `writing_run_id`.

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
documents.

### Supported input formats

| Extension | Handling | `extraction_method` |
| --- | --- | --- |
| `.pdf` | Text-native extraction via `pypdf`, or OCR | `pypdf`, `ocr:tesseract`, `ocr:easyocr`, `ocr:paddleocr` |
| `.docx` | Modern Word documents | `docx` |
| `.txt`, `.md`, `.markdown`, `.notes` | Read directly as UTF-8 text | `plain_text` |

`DocumentReader` dispatches on the file extension and handles all of the above,
and the essay pipeline accepts the same extension set when ingesting sources.
The `pdf-extract` CLI subcommands are PDF-only, so use `DocumentReader` from
Python for the other formats.

Legacy `.doc` files and any unrecognized extension raise `ValueError`.

### Why `pypdf`

`pypdf` is distributed under a permissive BSD-style license, which is commonly
compatible with both open-source and closed-source projects.

## CLI Usage

The `pdf-extract` command has three subcommands: `extract`, `ocr-parallel`, and
`outline`. A global `-v` flag enables INFO logging and `-vv` enables DEBUG:

```bash
pdf-extract -v extract path/to/file.pdf
```

All three subcommands take a PDF path. Other document types go through the
Python `DocumentReader` API instead — see
[Supported input formats](#supported-input-formats).

### `pdf-extract extract`

Single-process extraction from a text-native or scanned PDF.

```bash
pdf-extract extract path/to/file.pdf --mode text_only
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier small
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier medium --ocr-lang en --ocr-lang fr
pdf-extract extract path/to/file.pdf --mode ocr_only --ocr-tier high --ocr-gpu
pdf-extract extract path/to/file.pdf --mode ocr_only --start-page 5 --max-pages 20
```

| Flag | Default | Description |
| --- | --- | --- |
| `--mode` | `text_only` | `text_only`, `ocr_only`, or `auto` |
| `--ocr-tier` | `small` | `small`, `medium`, or `high`; used when `--mode ocr_only` |
| `--ocr-dpi` | `300` | Rasterization DPI for OCR modes |
| `--ocr-lang` | `en` | OCR language code; repeat the flag for multiple languages |
| `--ocr-gpu` | off | Enable GPU for backends that support it |
| `--start-page` | `1` | First PDF page to process |
| `--max-pages` | all | Maximum number of pages to process |

`--mode auto` is accepted by the argument parser but raises `NotImplementedError`
at runtime; it is reserved for a future text/OCR heuristic.

For Tesseract-backed small OCR, the pipeline maps `--ocr-lang en` to
Tesseract's `eng` language code automatically.

The command prints JSON with:
- source path
- page count
- page-wise text payloads

### `pdf-extract ocr-parallel`

Page-level parallel OCR. Only the Tesseract-backed `small` tier is parallelized —
passing `--ocr-tier medium` or `--ocr-tier high` raises a `ValueError`. Those
tiers stay available through `extract`, but are not yet parallelized because
EasyOCR/PaddleOCR need backend-specific worker handling, especially for GPU mode.

```bash
pdf-extract ocr-parallel path/to/file.pdf --ocr-tier small --workers auto --max-pages 10
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --workers 4 --store ./ocr_store
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --workers auto --calibrate --max-pages 20
pdf-extract -v ocr-parallel path/to/file.pdf --ocr-tier small --document-id my-book --resume
```

| Flag | Default | Description |
| --- | --- | --- |
| `--ocr-tier` | `small` | Only `small` is supported; other tiers raise at runtime |
| `--ocr-dpi` | `300` | Rasterization DPI |
| `--ocr-lang` | `en` | OCR language code; repeatable |
| `--ocr-gpu` | off | Reserved for GPU backends; ignored for Tesseract |
| `--start-page` | `1` | First PDF page to process |
| `--max-pages` | all | Maximum number of pages to process |
| `--workers` | `auto` | Worker count, or `auto` for planned concurrency |
| `--calibrate` | off | With `--workers auto`, benchmark sample pages and pick a measured worker count |
| `--store` | `./ocr_store` | Artifact store root |
| `--document-id` | derived | Stable id for artifact storage and `--resume` |
| `--max-attempts` | `2` | Attempts per page before recording a failure |
| `--timeout-seconds` | none | Reserved; no per-page timeout is enforced yet |
| `--json-summary` | off | Print only the run summary instead of merged page text |
| `--resume` | off | Reuse existing successful page artifacts for this document id |
| `--shared-machine` | on | Conservative worker planning for an interactive machine |
| `--dedicated-machine` | off | More aggressive worker planning for a dedicated OCR machine |
| `--omp-thread-limit` | `1` | OpenMP thread limit per Tesseract worker |

When `--document-id` is omitted it is derived from the file as
`{stem}-{sha1(path:size:mtime)[:12]}`. That fingerprint changes if the file is
modified or moved, which starts a fresh store directory, so pass an explicit
`--document-id` whenever you intend to `--resume`.

Artifacts are written under the store root:

```text
ocr_store/{document_id}/
  config.json              # resolved config + worker plan
  pages/{page:06d}.json    # one artifact per page
  merged/v1.json           # merged extraction result
  runs/{run_id}.json       # per-run summary
  calibration/latest.json  # written only with --calibrate
```

Worker planning also reads environment variables, which the CLI flags override:

| Variable | Default | Description |
| --- | --- | --- |
| `OCR_MAX_WORKERS` | unset | Fixed worker count, equivalent to `--workers N` |
| `OCR_SHARED_MACHINE` | `true` | `true` for conservative planning, `false` for dedicated |
| `OCR_OMP_THREAD_LIMIT` | `1` | OpenMP thread limit per worker |

With `--workers auto` and no override, the planner picks
`min(physical_cores // 2, 8)` workers on a shared machine and
`min(physical_cores, 16)` on a dedicated one. When the `ocr-scheduler` extra is
installed, that count is additionally capped at roughly one worker per 1.5 GB of
available RAM; without `psutil` the memory bound is skipped.

### `pdf-extract outline`

Extracts a hierarchical table of contents and maps each entry to real PDF page
numbers. It layers PDF bookmarks, an LLM pass over the front matter, `/PageLabels`
metadata, and a fuzzy anchor scan through the body text, so it needs the
`outline` extra, an LLM provider extra, and that provider's API key.

```bash
pdf-extract outline path/to/book.pdf --source-id my-book
pdf-extract outline path/to/book.pdf --source-id my-book --provider openai --llm-model gpt-4o
pdf-extract outline path/to/scan.pdf --source-id my-scan --ocr-tier small
pdf-extract -v outline path/to/scan.pdf --source-id my-scan --ocr-tier small --parallel-workers auto --calibrate
```

| Flag | Default | Description |
| --- | --- | --- |
| `--source-id` | **required** | Stable id used as the storage key |
| `--provider` | `LLM_PROVIDER`, else `claude` | `claude`, `openai`, or `gemini` |
| `--llm-model` | provider default | Model id for this run |
| `--store` | `./outline_store` | Outline store root |
| `--ocr-tier` | off | Enable OCR fallback for pages where `pypdf` returns no text |
| `--ocr-dpi` | `300` | Rasterization DPI for the OCR fallback |
| `--ocr-lang` | `en` | OCR language code; repeatable |
| `--ocr-gpu` | off | Enable GPU for backends that support it |
| `--parallel-workers` | sequential | `N` or `auto` to parallelize OCR of the TOC window |
| `--calibrate` | off | With `--parallel-workers auto`, benchmark before choosing |

OCR here is only a fallback, and its cost depends on the tier. With
`--ocr-tier small`, pages are OCR'd lazily and one at a time, only where `pypdf`
came back empty. The `medium` and `high` tiers OCR the whole document up front,
which is slow on large PDFs. `--parallel-workers` applies only to the
table-of-contents window, and only to the `small` tier; other tiers fall back to
sequential OCR.

The command prints one line per entry and saves an immutable versioned JSON
document to `{store}/{source_id}/v{version}.json`:

```text
[pdf_outline] lvl 1 pdf_page=12-44 printed=1 conf=1.00  Introduction
[anchor_scan] lvl 2 pdf_page=45-61 printed=34 conf=0.92  Methods
```

Each entry carries `id`, `title`, `level`, `parent_id`, `start_pdf_page`,
`end_pdf_page`, `printed_page`, `confidence`, and a `source` of `pdf_outline`,
`page_labels`, `anchor_scan`, or `unresolved`. Saving over an existing version
raises `FileExistsError`, so bump the version instead of overwriting.

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
  store stable page boundaries without rendering. Plain-text formats (`.txt`,
  `.md`, `.markdown`, `.notes`) are returned as one logical page for the same
  reason.
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

## License

EssayWriter is released under the MIT License — see `LICENSE`. You are free to
use, modify, and distribute it, and it is provided as is, without warranty of
any kind. The repository's creators and contributors are not liable for any
claim, damages, or other liability arising from its use.

## Third-Party Licenses

See `docs/THIRD_PARTY_LICENSES.md`.
