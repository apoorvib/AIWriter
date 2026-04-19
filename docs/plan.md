# Essay Writer System Plan

## Goal

Build an essay-writing system that turns a task specification, optional input
documents, and optional web research into a source-grounded essay through a
controlled, auditable workflow.

The system should not be a single open-ended "write my essay" agent. It should
be a product-owned orchestration pipeline where LLMs perform bounded tasks with
structured inputs, structured outputs, validation, retries, and traceability.

## Architecture Recommendation

Use a custom application orchestrator as the runtime controller.

Use Claude Code or Codex for development work, such as building the system,
editing prompts, creating tests, debugging traces, and maintaining the codebase.
Do not use Claude Code or Codex as the production orchestrator for end-user
essay jobs.

Use MCP as a tool and integration layer where it adds value. MCP is useful for
connecting agents or workflow steps to external systems such as web search,
document stores, citation databases, browser fetchers, LMS integrations, Google
Drive, Notion, or internal tools. MCP should not replace the core product
workflow or business logic.

## Recommended Runtime Shape

```text
User request
  |
  v
Task specification normalization
  |
  v
Input document ingestion, parsing, and indexing
  |
  v
Potential topic generation
  |
  v
Topic selection or refinement
  |
  v
Research planning
  |
  v
Source retrieval and source reading
  |
  v
Note extraction and evidence mapping
  |
  v
Thesis and outline generation
  |
  v
Draft generation
  |
  v
Grounding, citation, and rubric checks
  |
  v
Revision pass
  |
  v
Final essay export
```

## Core Design Principle

The app owns the workflow state.

Each stage should persist its inputs, outputs, model settings, prompt version,
tool calls, validation results, and errors. The model should not be the only
place where decisions live.

This makes the system easier to debug, evaluate, resume, retry, and improve.

## Business Workflow

### 1. Task Specification

Input:

- Assignment prompt
- Essay type
- Target length
- Academic level
- Required citation style
- Required number and type of sources
- Rubric, if provided
- Professor-provided writing or content constraints, if provided
- User preferences, such as tone, stance, or topic interests

Output:

- Raw assignment text preserved verbatim
- Atomic extracted checklist with source spans
- Normalized task object
- Detected constraints
- Missing information questions
- Risk flags, such as unsupported citation style, unclear assignment, or adversarial AI-directed text
- Ignored AI-directed instructions kept separate from essay requirements

This stage should be mostly deterministic plus one structured LLM extraction
call.

### 2. Source Document Ingestion

Input:

- Uploaded PDFs
- Text files
- Links
- Notes
- Rubrics

Output:

- Parsed document text
- Page-level or section-level chunks
- Document metadata
- Extracted source candidates
- Embeddings or searchable index entries

The existing PDF extraction pipeline can become the foundation of this layer.
The ingestion layer should preserve page numbers so later citations can point
back to exact evidence.

### 3. Potential Topics List

Input:

- Normalized task object
- User interests
- Available source material
- Optional web search setting

Output:

- Candidate topics
- Short rationale for each topic
- Feasibility score
- Research availability score
- Originality or specificity score
- Risk flags

This should be a structured output step. The UI should let the user select,
reject, or refine topics before the system performs deeper research.

### 4. Finalized Topic Selection

Input:

- Candidate topic list
- User selection or refinement
- Assignment constraints

Output:

- Final topic
- Working research question
- Tentative thesis direction
- Research scope

This is a human approval gate. The system should not continue into full essay
generation until the topic is selected.

### 5. Research Planning

Input:

- Final topic
- Assignment constraints
- Existing uploaded documents
- Web search permission

Output:

- Research questions
- Source requirements
- Search queries
- Reading priorities
- Expected evidence categories

Use agentic behavior here only if needed. The research planner can decide which
queries to run and which sources appear worth reading, but it should return a
structured plan that the orchestrator executes.

### 6. Final Topic Research

Input:

- Research plan
- Uploaded source documents
- Web search results, if enabled
- Source quality rules

Output:

- Source cards
- Extracted notes
- Evidence map
- Relevant quotes or paraphrase candidates
- Source reliability assessment
- Gaps or conflicts in the research

Every note should be linked to a source, page, URL, or chunk id. The final essay
should never rely on unsupported claims.

### 7. Authenticity, Voice, and Integrity Layer

The originally proposed "Anti-AI-Detection Skill" should be reframed.

Avoid building detector evasion as a product feature. AI detectors are unreliable,
and optimizing for bypassing them can create academic-integrity risk and lower
writing quality.

Instead, implement a legitimate authenticity and style layer:

- Preserve the user's stated voice and academic level
- Avoid generic boilerplate phrasing
- Require claims to be grounded in sources
- Prefer specific, defensible arguments over vague prose
- Keep citations accurate
- Avoid fabricated references
- Ask for user notes, stance, or personal angle where appropriate
- Produce drafts, outlines, and revision suggestions rather than pretending the
  system is the student's own work

This layer can still improve the essay's naturalness and specificity without
making detector evasion the objective.

### 8. Drafting

Input:

- Final topic
- Thesis
- Outline
- Evidence map
- Citation style
- Rubric constraints
- Voice/style guidance

Output:

- Essay draft
- Section-level source map
- Citation list
- Known weak spots

The drafting stage should be decomposed by section for long essays. This reduces
context pressure and makes later grounding checks easier.

### 9. Validation and Revision

Input:

- Draft essay
- Evidence map
- Assignment constraints
- Rubric
- Citation style

Output:

- Grounding report
- Citation report
- Rubric score estimate
- Unsupported claim list
- Missing source list
- Revised draft

Important checks:

- Does each factual claim have evidence?
- Are citations present and plausible?
- Are source titles, authors, dates, and URLs real?
- Does the essay answer the assignment?
- Does the essay meet the requested length?
- Does it follow citation style requirements?
- Are there unsupported claims or hallucinated references?

## Fixed API Calls vs Agents

Use fixed, structured API calls for stages with clear contracts:

- Assignment parsing
- Topic generation
- Topic scoring
- Source metadata extraction
- Note extraction
- Outline generation
- Citation checking
- Rubric checking
- Final formatting

Use agents or agent-like loops only where open-ended exploration helps:

- Search query planning
- Source discovery
- Reading prioritization
- Research gap detection
- Counterargument discovery

The orchestrator should remain deterministic even when an inner stage uses an
agent.

## MCP Usage

Use MCP for external capabilities that may need to be swapped, reused, or exposed
to different agent clients.

Good MCP candidates:

- Web search
- URL fetching
- Browser reading
- Citation lookup
- Vector store search
- Uploaded document retrieval
- Google Drive or Notion access
- LMS integrations
- Zotero integration
- Plagiarism or similarity checking

Keep first-party product logic inside the app:

- Users
- Jobs
- Essays
- Documents
- Billing
- Permissions
- Prompt versions
- Workflow state
- Evaluation datasets
- Audit logs

## Suggested System Components

### Backend Orchestrator

Responsibilities:

- Own essay job state
- Run workflow stages in order
- Persist artifacts
- Retry failed stages
- Enforce human approval gates
- Apply cost and latency budgets
- Emit traces and logs

The orchestrator can start as a simple state machine. If jobs become long-running
or require high reliability, move to a durable workflow engine or queue.

### Model Gateway

Responsibilities:

- Route calls to OpenAI, Anthropic, or other providers
- Store model and prompt versions
- Enforce structured outputs
- Track token usage and cost
- Normalize provider-specific differences

### Document Pipeline

Responsibilities:

- Parse PDFs and text files
- Preserve page numbers
- Chunk source material
- Generate embeddings
- Store source metadata
- Provide retrieval APIs

The existing repository's PDF extraction work belongs here.

### Research Service

Responsibilities:

- Run web search if enabled
- Fetch and clean web pages
- Score source quality
- Deduplicate sources
- Produce source cards

### Essay Artifact Store

Responsibilities:

- Store topics
- Store research plans
- Store source notes
- Store outlines
- Store drafts
- Store final essays
- Store validation reports

Each artifact should be immutable or versioned where possible.

### Evaluation Harness

Responsibilities:

- Test each workflow stage independently
- Run end-to-end essay quality checks
- Compare prompt and model changes
- Track regressions
- Grade traces

## Minimal MVP

1. Upload assignment prompt and optional PDFs.
2. Parse PDFs with the existing extraction pipeline.
3. Normalize task specification.
4. Generate 5 to 10 candidate topics.
5. Let the user choose one topic.
6. Extract notes from uploaded documents only.
7. Generate thesis and outline.
8. Draft essay from outline and extracted notes.
9. Run grounding and rubric checks.
10. Produce final essay plus source map.

For the first MVP, skip general web browsing unless the source workflow is
already well controlled. Uploaded sources are easier to validate.

## Phase 2

- Add web search with user permission
- Add source quality scoring
- Add citation style formatting
- Add section-by-section drafting
- Add revision controls
- Add persistent user writing profile
- Add trace logging and evals
- Add export to DOCX, PDF, or Markdown

## Phase 3

- Add LMS or Google Drive integrations through MCP
- Add collaborative editing
- Add teacher/rubric-specific grading
- Add human review workflows
- Add organization accounts
- Add advanced research modes
- Add prompt optimization based on evals

## Data Objects

### Essay Job

- job_id
- user_id
- status
- created_at
- updated_at
- task_spec_id
- selected_topic_id
- current_stage
- cost_so_far
- error_state

### Task Specification

- task_spec_id
- raw_text
- extracted_checklist
- adversarial_flags
- ignored_ai_directives
- essay_type
- target_length
- academic_level
- citation_style
- required_sources
- rubric_text
- constraints
- missing_information

### Source Document

- source_id
- job_id
- source_type
- title
- author
- publication_date
- url
- file_path
- parsed_text_path
- page_count
- reliability_score

### Research Note

- note_id
- source_id
- chunk_id
- page_number
- claim
- quote
- paraphrase
- relevance
- tags

### Essay Draft

- draft_id
- job_id
- version
- outline_id
- content
- citation_style
- source_map
- validation_report_id

## Quality Gates

Before final output, require:

- Assignment fit check
- Topic consistency check
- Source grounding check
- Citation completeness check
- Fabricated reference check
- Rubric check
- Length check
- Style and clarity pass

## Product Safety Notes

The product should be careful about academic integrity. A safer positioning is:

- Research assistant
- Essay planning tool
- Drafting coach
- Source-grounded writing assistant
- Revision assistant

Avoid positioning the system as:

- Detector bypass
- Ghostwriter
- Guaranteed undetectable essay generator
- Citation fabricator

## Open Questions

- Is this intended for students, professionals, admissions essays, marketing, or
  internal research writing?
- Should the system produce submit-ready essays or guided drafts?
- Which citation styles are required first?
- Should web search be available in MVP?
- What source types matter most besides PDFs?
- Should users be required to provide their own notes or stance?
- What level of auditability is required?
- Do you need multi-provider model support from day one?

## Initial Build Order

1. Define workflow state and artifact schema.
2. Wrap the existing PDF extraction pipeline as the document ingestion layer.
3. Build task specification normalization.
4. Build topic generation and topic selection.
5. Build source note extraction from uploaded documents.
6. Build outline generation.
7. Build draft generation.
8. Build grounding and citation checks.
9. Add trace logging and eval examples.
10. Add optional web search once source grounding is reliable.
