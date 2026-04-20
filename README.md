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
uvicorn backend.app:app --host 127.0.0.1 --port 8629 --reload
```

Run the frontend in another terminal:

```bash
cd frontend
npm run dev
```

The frontend runs at `http://127.0.0.1:3527` by default and proxies `/api`
requests to `http://127.0.0.1:8629`. Vite preview uses
`http://127.0.0.1:4627`.
The app supports source uploads for `.pdf`, `.docx`, `.txt`, `.md`,
`.markdown`, and `.notes` files. Assignment text can be pasted or extracted
from the same document types.

Source access budgets default high enough for broad research passes while still
preventing one model request from reading an entire book:

```bash
ESSAY_MAX_RESEARCH_ROUNDS=3
ESSAY_MAX_SOURCE_PACKETS=40
ESSAY_MAX_TOTAL_SOURCE_CHARS=200000
ESSAY_MAX_PDF_PAGES_PER_REQUEST=80
ESSAY_MAX_PDF_PAGES_TOTAL=240
ESSAY_MAX_CHARS_PER_PACKET=50000
ESSAY_OVERSIZED_SOURCE_REQUEST_POLICY=reject
ESSAY_LAZY_PDF_OCR_ENABLED=true
ESSAY_LAZY_OCR_TIER=small
ESSAY_LAZY_OCR_DPI=300
ESSAY_LAZY_OCR_LANGUAGES=en
```

PDF retrieval uses physical 1-based PDF page numbers for source access.
Printed page labels are stored separately when PDF metadata exposes them, and
are used for traceability rather than as the primary retrieval coordinate.

## End-to-End Application Logic

The web app is an essay-writing workflow built on top of the document extraction
pipeline. The main path is:

```text
assignment + uploaded sources
-> source ingestion
-> task specification
-> topic ideation
-> topic selection
-> research planning
-> source access resolution
-> final topic research
-> outline
-> draft
-> validation
-> optional revision
-> final Markdown export
```

### LLM Usage By Step

Most workflow steps are deterministic application code. LLM calls happen only
where a configured `LLMClient` is passed into the service.

| Step | Uses LLM? | Prompt/version | What the model receives |
| --- | --- | --- | --- |
| Source ingestion | Yes for source cards | `SOURCE_CARD_SYSTEM_PROMPT` | Source metadata plus selected uploaded-source excerpts. Missing LLM configuration raises an error. PDF OCR itself is not an LLM call. |
| Source maps and source access | No | None | The app builds maps, resolves locators, runs SQLite search, and may run OCR locally. |
| Assignment parsing | Yes | `task-spec-v1` / `TASK_SPEC_SYSTEM_PROMPT` | Raw assignment text. Missing LLM configuration raises an error. |
| Job creation | No | None | The app links task spec, source IDs, and workflow state. |
| Topic ideation | Yes | `topic-ideation-v1` / `TOPIC_IDEATION_SYSTEM_PROMPT` | Task spec, source cards, source maps, index manifests, previous candidates, rejected topics, and optional user instruction. |
| Topic selection | No | None | User action stored by the app. |
| Research planning | No today | `research-planning-v1` metadata only | The app deterministically validates selected-topic `source_requests`, source IDs, page ranges, sections, chunks, and budgets. No model call is made. |
| Source resolution | No | None | The app resolves validated requests into `SourceTextPacket` objects and may run lazy per-page OCR locally. |
| Final topic research | Yes | `final-topic-research-v1` / `FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT` | Task spec, selected topic, resolved source packets, and legacy chunks when present. |
| Outlining | Yes | `thesis-outline-v1` / `OUTLINE_SYSTEM_PROMPT` | Task spec, selected topic, research plan, evidence map, and source packets. Missing LLM configuration raises an error. |
| Drafting | Yes | `drafting-v1` / `DRAFTING_SYSTEM_PROMPT` | Task spec, selected topic, evidence map, outline, and resolved source packets/excerpts. |
| Validation | Yes | `validation-v1` / `VALIDATION_SYSTEM_PROMPT` | Draft, task spec, evidence notes, bibliography candidates, source-card metadata, metadata warnings, and deterministic style findings. |
| Revision | Yes | `drafting-revision-v1` / `DRAFTING_SYSTEM_PROMPT` | Prior draft, validation feedback, task spec, selected topic, outline, evidence map, and resolved source packets/excerpts. |
| Export | No | None | The app writes final Markdown from stored draft and validation data. |

### Prompt Inventory

The app uses structured JSON prompts. Each LLM call sends:

- a system prompt constant
- a JSON user payload built by the service
- a JSON schema that constrains the response shape
- an optional per-stage model override from settings/env

#### Assignment Parsing Prompt

- File: `essay_writer/task_spec/prompts.py`
- System prompt: `TASK_SPEC_SYSTEM_PROMPT`
- User payload: `build_task_spec_user_message(raw_text)`
- Output schema: `TASK_SPEC_SCHEMA`
- Stored version: `task-spec-v1`

Purpose:

- Extract assignment requirements from untrusted assignment documents.
- Preserve details, classify real student-facing requirements, detect
  adversarial instructions, and avoid treating AI-directed instructions as
  checklist requirements.

#### Source Card Prompt

- File: `essay_writer/sources/summary.py`
- System prompt: `SOURCE_CARD_SYSTEM_PROMPT`
- User payload: `_build_source_card_user_message(source, excerpts, summary_char_limit)`
- Output schema: `SOURCE_CARD_SCHEMA`
- Stored version: none currently on `SourceCard`

Purpose:

- Create a compact card from uploaded-source excerpts only.
- Summarize key topics, topic-ideation usefulness, notable sections,
  limitations, citation metadata, and warnings.

#### Topic Ideation Prompt

- Files: `essay_writer/topic_ideation/prompts.py`,
  `essay_writer/topic_ideation/service.py`
- System prompt: `TOPIC_IDEATION_SYSTEM_PROMPT`
- User payload: `_build_user_message(context, max_candidates)`
- Output schema: `TOPIC_IDEATION_SCHEMA`
- Stored version: `topic-ideation-v1`

Purpose:

- Generate source-grounded candidate essay topics.
- Use source cards, source maps, and index manifests.
- Prefer `source_requests` using physical PDF pages or section IDs, with
  chunk/search leads as backward-compatible fallbacks.

#### Final Topic Research Prompt

- Files: `essay_writer/research/prompts.py`,
  `essay_writer/research/service.py`
- System prompt: `FINAL_TOPIC_RESEARCH_SYSTEM_PROMPT`
- User payload: `_build_user_message(...)` in `research/service.py`
- Output schema: `FINAL_TOPIC_RESEARCH_SCHEMA`
- Stored version: `final-topic-research-v1`

Purpose:

- Extract source-grounded research notes from resolved source packets/chunks.
- Prevent invented sources, page numbers, facts, and quotes.
- Build notes, evidence groups, gaps, conflicts, and warnings.

#### Outline Prompt

- File: `essay_writer/outlining/service.py`
- System prompt: `OUTLINE_SYSTEM_PROMPT`
- User payload: `_build_outline_user_message(...)`
- Output schema: `OUTLINE_SCHEMA`
- Stored version: `thesis-outline-v1`

Purpose:

- Create a detailed, source-grounded essay outline.
- Carry the core argument through thesis, section purposes, claims, evidence
  placement, counterarguments, and word-budget priorities.
- Preserve traceability through note IDs and source packet IDs.

#### Drafting Prompt

- Files: `essay_writer/drafting/prompts.py`,
  `essay_writer/drafting/service.py`,
  `anti-ai-detection-SKILL.md`
- System prompt: `DRAFTING_SYSTEM_PROMPT`
- User payload: `_build_user_message(...)` in `drafting/service.py`
- Output schema: `DRAFTING_SCHEMA`
- Stored version: `drafting-v1`

Purpose:

- Write an academic essay draft from task spec, selected topic, evidence map,
  outline, and resolved source packets.
- Use only evidence-map notes, record section-to-note/source mappings, and
  report weak spots instead of fabricating support.
- Use source packet text for accurate source detail, quotes, and citations.
- Include the full local `anti-ai-detection-SKILL.md` document directly in the
  system prompt and apply it during drafting, not as a cleanup pass.

#### Revision Prompt

- Files: `essay_writer/drafting/prompts.py`,
  `essay_writer/drafting/revision.py`,
  `anti-ai-detection-SKILL.md`
- System prompt: `DRAFTING_SYSTEM_PROMPT`
- User payload: `_build_revision_message(...)`
- Output schema: `DRAFTING_SCHEMA`
- Stored version: `drafting-revision-v1`

Purpose:

- Revise the prior draft using validation feedback while keeping every claim
  grounded in the supplied evidence.
- Reuses the same drafting system prompt and schema, but the user payload adds
  previous draft content, validation findings, weak spots, and revision
  suggestions.
- Receives the resolved source packets again, so revision can correct grounding
  issues against the actual excerpts instead of only the distilled evidence map.
- Because it reuses `DRAFTING_SYSTEM_PROMPT`, it also includes the full
  `anti-ai-detection-SKILL.md` document directly.

#### Validation Prompt

- Files: `essay_writer/validation/prompts.py`,
  `essay_writer/validation/service.py`
- System prompt: `VALIDATION_SYSTEM_PROMPT`
- User payload: `_build_user_message(...)` in `validation/service.py`
- Output schema: `VALIDATION_SCHEMA`
- Stored version: `validation-v1`

Purpose:

- Judge grounding, citations, assignment fit, length, rubric alignment, and
  higher-level style.
- Deterministic style checks run before this call; the prompt tells the model
  not to re-check those findings and instead use them as supplied data.

### 1. Source Ingestion

Users upload source documents through the web UI. Supported source types are:

- `.pdf`
- `.docx`
- `.txt`
- `.md`
- `.markdown`
- `.notes`

Ingestion uses `DocumentReader` for document text extraction:

- PDFs use `PyPdfExtractor` for text-native extraction.
- DOCX files use `WordDocExtractor`.
- TXT/Markdown/Notes files are read as UTF-8 plain text.
- Low-quality PDF text can fall back to OCR during ingestion.

Each ingested source produces persisted artifacts under the configured data
directory:

```text
source.json
original.<ext>
pages.jsonl
chunks.jsonl
full_text.txt
source_card.json
source_map.json
source_units.jsonl
index.sqlite
index_manifest.json
```

Not every source will have every artifact. For example, `index.sqlite` and
`index_manifest.json` are only present when indexing succeeds. Uploaded
originals are copied into the source artifact directory so later source access
can re-read specific PDF pages when OCR is needed.

### 2. Source Cards

Every successfully ingested source gets a source card. A source card is a
compact summary used by topic ideation and later validation metadata checks.

The source-card builder sends selected source excerpts to the model. If no LLM
client is configured, ingestion raises a configuration error instead of creating
a lower-quality deterministic card.

The source card includes:

- title
- brief summary
- key topics
- topic-ideation hints
- notable sections
- limitations
- citation metadata
- warnings

### 3. Source Maps And Source Access

The source access layer is the preferred interface between LLM stages and source
text.

For PDFs, the source map is page-based:

```text
source_id
unit_id
unit_type = pdf_page
pdf_page_start / pdf_page_end
printed_page_start / printed_page_end
text preview
text quality
```

Important: source access uses physical 1-based PDF page numbers. Printed page
labels are stored separately for citation and traceability.

For DOCX, Markdown, TXT, and Notes, the source map is section-based:

```text
source_id
unit_id
unit_type = section
heading_path
text preview
text quality
```

Markdown sections are built from headings when available. DOCX/TXT/Notes use
heading-like lines and paragraph grouping as fallback structure.

The source resolver accepts `SourceLocator` requests:

```text
pdf_pages: source_id + physical pdf_page_start/pdf_page_end
section: source_id + section_id
search: source_id + query
chunk: source_id + chunk_id
```

It returns `SourceTextPacket` objects with exact text and provenance.

### 4. Assignment Parsing

The user can paste assignment text or extract it from a supported document type.
`TaskSpecParser` turns that assignment into a `TaskSpecification`.

The task specification includes:

- assignment title and raw text
- essay type and academic level when available
- target length and citation style
- prompt options and selected prompt
- required sources/materials/structure
- rubric and grading criteria
- extracted checklist items
- adversarial text flags
- blocking questions and warnings

If multiple prompt options are detected and no selected prompt is provided, the
job can be marked blocked until the user resolves the ambiguity.

### 5. Job Creation

An `EssayJob` links:

- task spec ID
- uploaded source IDs
- topic rounds
- selected topic
- research plan
- evidence map
- outline
- draft
- validation report
- final export

The job state machine records progress through stages such as
`topic_selection`, `research_planning`, `drafting`, `validation`, `revision`,
and `complete`.

### 6. Topic Ideation

Topic ideation is an LLM stage. It receives:

- task specification
- source cards
- source maps
- source index manifests
- previous topic candidates
- rejected topic directions
- optional user instruction for another round

It returns candidate topics with:

- title
- research question
- tentative thesis direction
- rationale
- fit/evidence/originality scores
- risk flags and missing evidence
- legacy source leads using `chunk_ids` and source-index search queries
- preferred `source_requests` using PDF pages, section IDs, searches, or chunks

The user selects one topic or rejects directions with reasons. Rejected topics
are stored and passed into later topic rounds so the model can avoid repeating
them.

### 7. Research Planning

Research planning is deterministic in the current implementation.

It receives the selected topic, source maps, index manifests, task spec, and
source access config. It validates the selected topic's `source_requests`:

- source IDs must belong to the job
- source maps must exist
- physical PDF page ranges must be valid
- section IDs must exist
- search requests must include a query
- chunk requests must include a chunk ID
- PDF requests must fit configured per-request bounds

The output `ResearchPlan` contains:

- research question
- uploaded source priorities
- validated source requests
- source requirements from the assignment
- expected evidence categories
- optional external search queries if external search is allowed
- warnings

### 8. Source Resolution

Before final topic research, the workflow resolves validated source requests
into source text packets.

Resolution order is:

1. Preferred `source_requests` from the selected topic and research plan.
2. Legacy explicit `chunk_ids`.
3. SQLite full-text search using suggested source search queries.

Resolved packets are bounded by:

- max research rounds
- max source packets
- max total source characters
- max PDF pages per request
- max PDF pages total
- max characters per packet
- oversized request policy

For PDFs, the resolver first uses stored page text from ingestion. If requested
physical pages are missing readable text, or only have low/partial text, it can
run lazy per-page OCR against the stored original PDF and refresh
`pages.jsonl`, `full_text.txt`, `source_map.json`, and `source_units.jsonl`
before returning the packet. Lazy OCR uses physical 1-based PDF page numbers,
not printed page labels.

Relevant source access environment variables:

```text
ESSAY_MAX_RESEARCH_ROUNDS
ESSAY_MAX_SOURCE_PACKETS
ESSAY_MAX_TOTAL_SOURCE_CHARS
ESSAY_MAX_PDF_PAGES_PER_REQUEST
ESSAY_MAX_PDF_PAGES_TOTAL
ESSAY_MAX_CHARS_PER_PACKET
ESSAY_OVERSIZED_SOURCE_REQUEST_POLICY
ESSAY_LAZY_PDF_OCR_ENABLED
ESSAY_LAZY_OCR_TIER
ESSAY_LAZY_OCR_DPI
ESSAY_LAZY_OCR_LANGUAGES
```

### 9. Final Topic Research

Final topic research is an LLM stage. It receives:

- task specification
- selected topic
- resolved source text packets
- legacy retrieved chunks when present

The model turns source text into an evidence map:

- research notes
- grounded claims
- quotes when directly found in source text
- paraphrases
- relevance explanations
- evidence groups
- gaps
- conflicts
- warnings

The service validates model output against supplied source text. For example,
quotes that are not found in the packet/chunk are dropped with warnings.

### 10. Outlining

Outlining is a major LLM-backed content-planning step. The outline service
receives:

- task specification
- selected topic
- research plan
- evidence map
- resolved source packets

It returns:

- working thesis
- section headings
- section purposes
- key points
- note IDs to use in each section
- target word counts when applicable

If no LLM client is configured, outlining raises a configuration error.

### 11. Drafting

Drafting is an LLM stage. It receives:

- task specification
- selected topic
- evidence notes
- evidence groups
- gaps and conflicts
- outline
- resolved source text packets

The draft response includes:

- essay content
- section-to-source map
- bibliography candidates
- known weak spots

The draft model receives the resolved source packets selected during research
planning/source resolution. These packets include source IDs, packet IDs, page
ranges, printed page labels when known, headings, extraction metadata, text
quality, warnings, and the excerpt text.

### 12. Validation

Validation combines deterministic checks and an LLM judgment.

Deterministic checks look for style and structure issues such as:

- em dash count
- overused high-level vocabulary
- conclusion opener problems
- participial phrase rate
- repetitive signposting
- sentence similarity runs

The LLM validation stage receives:

- draft text
- task specification
- evidence map
- bibliography candidates
- known source metadata from source cards
- deterministic findings

It returns:

- unsupported claims
- citation issues
- rubric scores
- assignment-fit judgment
- length check
- style issues
- revision suggestions
- overall quality score

### 13. Revision Loop

If validation fails, the workflow can run a revision pass.

The revision service receives:

- prior draft
- validation report
- task spec
- selected topic
- evidence map
- outline
- resolved source text packets

It creates the next draft version, then validation runs again. If the revised
draft passes, the workflow can export.

### 14. Export

When validation passes, `FinalExportService` creates a Markdown export with:

- final essay content
- bibliography candidates
- section source map
- validation summary

The web UI can display the final essay and download it as Markdown.

### Current Limitations

- Lazy PDF OCR depends on the stored original PDF and installed OCR
  dependencies. Existing source artifacts created before original-file
  persistence may need to be re-ingested before lazy OCR can run.
- Embedding search is not yet implemented.
- Follow-up research rounds are configurable but not yet wired into a
  multi-round source-request loop.
- DOCX page numbers are not stable without rendering, so DOCX access is
  section-based rather than page-based.
- The extraction CLI and web app share lower-level document extraction code, but
  the CLI does not run the full essay workflow.

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
