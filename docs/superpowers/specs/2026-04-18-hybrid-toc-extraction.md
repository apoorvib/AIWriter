# Hybrid TOC Extraction - Superseded Spec

**Original date:** 2026-04-18
**Superseded:** 2026-04-19
**Area:** `pdf_pipeline/outline`

This spec described a deterministic-first TOC/index extraction experiment.
It has been superseded.

Current direction:

- Candidate-page prefiltering remains useful for limiting LLM calls.
- Layer 2 entry extraction should rely on the LLM, one candidate page per call.
- Deterministic partial extraction should not be used as a fallback because it
  can silently omit large portions of dense indexes.
- Page-label resolution and anchor-scan mapping remain deterministic after the
  LLM has produced raw entries.
