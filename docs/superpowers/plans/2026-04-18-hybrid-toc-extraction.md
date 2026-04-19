# Hybrid TOC Extraction - Superseded Plan

**Original date:** 2026-04-18
**Superseded:** 2026-04-19

This plan described a deterministic-first TOC/index extraction experiment.
It has been superseded.

Current direction:

- Layer 2 TOC/index extraction uses the LLM after candidate-page prefiltering.
- The old deterministic parser and CLI mode were removed because partial
  extraction is more dangerous than a clear LLM failure.
- Page-label and anchor-scan resolution remain deterministic after LLM entry
  extraction.
