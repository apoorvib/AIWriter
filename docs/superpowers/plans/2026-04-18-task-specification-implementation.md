# Task Specification Extraction - Implementation Plan

## Goal

Implement the first task-specification module for the essay writer pipeline.

This module must be lossless-first:

```text
raw assignment text is preserved verbatim
```

The parser should produce structured fields and checklist items, but those
derived fields never replace the raw assignment.

## File Structure

Create:

```text
essay_writer/
  __init__.py
  task_spec/
    __init__.py
    schema.py
    security.py
    prompts.py
    parser.py
    storage.py

tests/
  task_spec/
    __init__.py
    _tmp.py
    test_schema.py
    test_security.py
    test_parser.py
    test_storage.py
```

Rationale:

- `pdf_pipeline` should stay focused on document extraction.
- `essay_writer` will hold higher-level orchestration concepts.
- Task specification is an essay writer concept, not a PDF concept.

## Task 1 - Package and Schema

Create dataclasses:

- `ChecklistItem`
- `AdversarialFlag`
- `TaskSpecification`

Use immutable dataclasses where practical.

Include:

- raw text
- extracted checklist
- adversarial flags
- ignored AI directives
- ambiguities
- missing information
- blocking questions
- nonblocking warnings
- confidence map

Do not include:

- due date
- collaboration or AI policy

## Task 2 - Security Scanner

Create deterministic scanner for obvious adversarial patterns.

Detect:

- ignore previous instructions
- system prompt extraction
- model behavior override
- assistant sabotage
- output-only directives aimed at AI

Return `AdversarialFlag` objects with source spans.

This scanner runs even when no LLM is available.

## Task 3 - LLM Prompt and Schema

Create:

- task extraction system prompt
- JSON schema for structured extraction

The prompt must explicitly state:

- assignment text is untrusted
- do not obey instructions inside it
- extract only student-facing requirements
- adversarial AI-directed text goes into `adversarial_flags`

## Task 4 - Parser

Create `TaskSpecParser`.

Behavior:

- accepts raw text
- optional source document IDs
- optional selected prompt
- optional LLM client
- always preserves raw text
- always runs deterministic security scan
- if LLM client is available, calls `chat_json`
- if no LLM client is available, uses deterministic baseline extraction
- merges deterministic adversarial flags with LLM flags
- emits blocking questions for unresolved prompt choice

Baseline extraction should be conservative:

- split raw text into non-empty lines
- extract lines with requirement keywords
- preserve full line as source span
- categorize with simple heuristics

## Task 5 - Storage

Create `TaskSpecStore`.

Behavior:

- save immutable `v{version}.json`
- load latest by task id
- reject overwrites
- write atomically

Use a repo-local temp helper in tests to avoid Windows pytest temp-dir issues.

## Task 6 - Tests

Add tests for:

- schema construction
- adversarial scanner
- baseline parser preserves raw text
- adversarial text excluded from checklist
- prompt-option ambiguity creates blocking question
- storage save/load/latest
- LLM parser uses mock client and records guarded prompt

## Task 7 - Documentation

Update:

- `TODO.md`
- `session-log.md`
- optionally `docs/plan.md` if field list needs syncing

## Acceptance Criteria

- `pytest tests/task_spec` passes.
- `python -m compileall essay_writer tests/task_spec` passes.
- No existing OCR or outline tests regress.
- Raw assignment text is exactly preserved.
- Obvious adversarial instructions are flagged.
- Adversarial instructions are not checklist items.
