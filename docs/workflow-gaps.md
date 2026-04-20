# Workflow Gaps

This file tracks known gaps in the essay-writer workflow. Check items off only when the code, artifact contracts, and tests make the fix real.

## High Priority

- [x] Add persisted-job orchestration and resume support.
  - Current gap: `MvpWorkflowRunner.run_after_topic_selection()` requires caller-provided `TaskSpecification`, `SelectedTopic`, and source index manifests.
  - Completion criteria: a job-id-driven runner loads required artifacts from stores, determines the current stage, resumes safely after restart, and has tests for at least one restart/resume path.

- [x] Add preflight contract validation before expensive LLM calls.
  - Current gap: the runner does not validate that task spec, selected topic, and source manifests match the job before retrieval/research/drafting.
  - Completion criteria: each stage validates job/artifact IDs before calling an LLM or writing artifacts, and rejects mismatches without persisting bad outputs.

- [x] Implement a real research planning artifact.
  - Current gap: `research_planning` is a workflow state, but there is no persisted `ResearchPlan`.
  - Completion criteria: selected topic produces a structured plan with source requirements, uploaded-source retrieval priorities, expected evidence categories, and optional external-search placeholders behind a permission gate.

- [x] Add thesis and outline artifacts before drafting.
  - Current gap: the workflow jumps from research notes directly to drafting.
  - Completion criteria: the system persists a thesis/outline artifact, draft generation consumes it, and drafts record the outline ID or equivalent linkage.

- [x] Gate drafting on evidence sufficiency.
  - Current gap: empty or inadequate retrieved evidence can still flow into drafting.
  - Completion criteria: insufficient evidence sets the job to `blocked` or requires explicit user override; tests cover no-evidence and weak-evidence cases.

- [x] Improve source ingestion for partial PDFs and empty indexes.
  - Current gap: only `low` text quality routes to OCR, so mixed/partial PDFs can skip OCR for missing pages; an empty chunk list can still be marked indexed.
  - Completion criteria: partial PDFs receive per-page or targeted OCR fallback where needed, empty indexes are not treated as usable indexes, and long unreadable sources fail with a clear error.

- [x] Block workflow progression on task-spec blocking questions.
  - Current gap: task specs can contain `blocking_questions`, but bootstrap still attaches them and can continue into topic ideation.
  - Completion criteria: blocking questions set the job to `blocked`, persist a user-facing reason, and clarification creates a new task-spec version before the job resumes.

- [x] Use `blocked` and `error` job states consistently.
  - Current gap: `EssayJobStatus` includes `blocked` and `error`, but stage failures are not recorded through workflow helpers.
  - Completion criteria: ingestion, parsing, topic generation, research, drafting, and validation failures update job state with `EssayJobErrorState`; tests cover partial failure behavior.

- [x] Make retries idempotent and version-aware.
  - Current gap: research, drafts, and validation are always written as version 1, so retries after partial failure can collide with existing artifacts.
  - Completion criteria: runners either load existing compatible artifacts or create the next version, and tests cover retry after each major stage.

## Medium Priority

- [x] Add a revision loop after failed validation.
  - Current gap: failed validation moves the job to `revision`, but no service consumes the validation report to create draft v2 and rerun checks.
  - Completion criteria: validation feedback can produce a revised draft version, rerun validation, and update job state.

- [x] Add final essay export artifacts.
  - Current gap: there is no final essay/export artifact after validation.
  - Completion criteria: the workflow can persist final output plus source map in at least Markdown, with DOCX/PDF left as optional later formats.

- [x] Strengthen citation metadata and citation verification.
  - Current gap: source metadata is mostly file-level, and citation checks are mostly LLM-judged.
  - Completion criteria: source ingestion stores structured citation metadata where available, drafts reference it, and validation can check bibliography candidates against known source metadata.

- [x] Add context-budget strategy for complete source manifests.
  - Current gap: topic ideation passes every manifest entry, which can become too large for many or huge sources.
  - Completion criteria: large manifests are paged, compressed, or selectively included while preserving deeper `index_path`/handle retrieval for full search.

- [x] Expand supported source/input types.
  - Current gap: `DocumentReader` supports PDF and DOCX only; broader plan mentions text files, links, notes, rubrics, and other source types.
  - Completion criteria: add first-class handling for plain text and at least one of notes/links/rubrics, with source cards and indexing behavior covered by tests.

- [x] Persist rejected topic state and user rejection reasons.
  - Current gap: topic rounds and selected topic are persisted, but rejected topics are not.
  - Completion criteria: rejected candidate IDs and reasons are stored and passed into later topic rounds so the UI can ask for more choices without repeating rejected directions.

## Notes

- External web/database research remains out of MVP unless explicitly enabled through an assignment/user permission gate.
- The drafting prompt and anti-AI-detection skill are intentionally not tracked here; prompt wording is product-owned separately.
