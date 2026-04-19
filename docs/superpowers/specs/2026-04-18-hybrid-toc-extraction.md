# Hybrid TOC Extraction - Design Spec

**Date:** 2026-04-18
**Status:** Implementation approved
**Area:** `pdf_pipeline/outline`

## Problem

Layer 2 outline extraction currently treats the LLM as the primary parser for
TOC pages. This is brittle for scanned or OCR-heavy books with dense historical
tables of contents.

Gray's Anatomy 1858 is the concrete failure case:

- OCR finds the `CONTENTS` pages.
- Candidate-page selection isolates the correct TOC window.
- Claude marks the chunk as TOC content.
- Claude returns zero structured entries.
- The deterministic parser extracts hundreds of entries.
- Page-label resolution validates most of those entries.

This means the failure is not OCR or TOC detection. The failure is making the
LLM perform a high-volume mechanical parsing task in one structured call.

## Goals

- Make deterministic TOC parsing the first parser in default `auto` mode.
- Keep the LLM path available for comparison, repair, and difficult layouts.
- Avoid LLM calls when deterministic extraction is already strong.
- Preserve existing Layer 1, Layer 1.5, Layer 3, and Layer 4 behavior.
- Keep parallel OCR semantics explicit: `--parallel-workers` OCRs the TOC
  window and does not secretly switch to pypdf-first extraction.
- Add logging that makes the chosen parser and result count obvious.

## Non-Goals

- Do not remove the LLM parser.
- Do not implement full visual layout analysis.
- Do not implement semantic book indexing in this feature.
- Do not change the public outline data model.

## Modes

Layer 2 supports three modes:

```text
auto
deterministic
llm
```

### auto

Default mode.

Workflow:

```text
candidate TOC pages
  -> deterministic parser
  -> if entry count is strong, skip LLM
  -> otherwise call LLM
  -> if LLM returns entries, use LLM entries
  -> if LLM returns zero, use deterministic entries if any
```

### deterministic

Run only deterministic TOC parsing. No LLM call.

Use this for:

- OCR-heavy public-domain books
- cost-sensitive bulk indexing
- tests and debugging

### llm

Run only LLM extraction after candidate-page selection.

Use this for:

- prompt experiments
- comparing model behavior
- layouts the deterministic parser misses

## Deterministic Parser Responsibilities

The deterministic parser should extract likely TOC rows from text patterns:

```text
Title . 123
Title .... 123
Title 123
Left title . 12 | Right title . 34
Section heading.
Child row . 56
```

It should:

- ignore `CONTENTS`, `TABLE OF CONTENTS`, and `PAGE` headers
- split pipe-separated two-column rows
- preserve row order
- normalize obvious punctuation noise around titles and printed pages
- infer a section heading's printed page from the next child row when clear
- cap extraction with a configurable maximum to avoid runaway noise

## LLM Parser Responsibilities

The LLM parser remains useful when deterministic extraction is weak.

Future prompt improvements should:

- extract one or two pages at a time
- explicitly teach two-column splitting
- require rejected lines rather than silent drops
- avoid allowing `entries: []` when rows contain visible title-page pairs

## Acceptance Criteria

- `auto` mode skips the LLM when deterministic extraction returns a strong TOC.
- `llm` mode still calls the LLM.
- `deterministic` mode never calls the LLM.
- Existing outline resolution behavior remains compatible.
- Tests cover parser mode selection.
