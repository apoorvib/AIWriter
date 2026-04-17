# Document Outline Extraction — Design Spec

**Date:** 2026-04-17
**Status:** Draft. Core algorithm is settled; parameter-tuning sub-questions and eval methodology remain open (see §8).
**Position in plan.md:** Document Pipeline (Stage 2) enhancement. Not an MVP prerequisite; Phase 2 of the build order. Designed now, shipped after MVP grounding loop is stable.

---

## 1. Purpose

Long source documents (academic books in particular) are too large to feed into an LLM wholesale. We want the LLM to be able to request a specific chapter or section on demand, keeping context windows small and grounding precise.

This feature extracts a canonical outline from each ingested source and exposes it as a retrieval index: the LLM calls a tool to enumerate the outline, picks a section, and calls another tool to get just that section's text.

The outline becomes first-class document metadata — it is stored, versioned per source, and consumed by later workflow stages (note extraction, citation, drafting, validation).

## 2. Non-Goals

- Back-of-book alphabetical index extraction. This spec is about the **front Table of Contents / document structure**, not subject indexes.
- Semantic search across the document. Section retrieval is ID-based; the LLM picks from `list_outline` and requests by `id`. Full-text / vector search is a separate concern.
- Detector evasion, content rewriting, or any non-retrieval use of outline data.
- Extracting figures, tables, or equation lists separately from the main outline. Out of scope for this iteration.

## 3. Output Schema

Each source document produces zero or one `DocumentOutline` made of `OutlineEntry` records.

```
OutlineEntry {
  id: str                        # stable within a document (e.g. "ch3", "ch3.2")
  title: str                     # canonical title text
  level: int                     # 1 = top-level chapter, 2 = section, 3 = subsection, ...
  parent_id: str | None          # None for top-level entries
  start_pdf_page: int            # inclusive, 1-indexed pdf page
  end_pdf_page: int              # inclusive, 1-indexed pdf page
  printed_page: str | None       # raw label as printed (e.g. "47", "iv"); preserved for citations
  confidence: float              # 0.0–1.0, reflects pdf_page resolution certainty
  source: "pdf_outline" | "page_labels" | "anchor_scan" | "unresolved"
}
```

Design notes:

- **Both `start_pdf_page` and `end_pdf_page` are required.** `get_section` slices a range, not a point. `end_pdf_page` is derived from the next same-or-higher-level entry's start minus 1, with the last entry ending at the last pdf page of the document.
- **`printed_page` is preserved verbatim as a string** (not coerced to int) so Roman numerals, hyphenated labels, and non-numeric schemes survive round-trip for citation rendering.
- **`confidence` is per-entry**, not per-document, because structural-metadata entries and anchor-scan entries may coexist in one outline (e.g. `/Outlines` supplies chapters, anchor scan supplies sections).
- **`source` tags the provenance** of each entry, which drives downstream trust decisions (e.g. validation may treat `pdf_outline` entries as ground truth and flag low-confidence `anchor_scan` entries for review).

## 4. Tool Surface

Two tools exposed to the orchestrator (and through it, to LLM workflow stages):

```
list_outline(source_id) -> list[OutlineEntry]
get_section(source_id, entry_id) -> str        # concatenated text of pages in range
```

MVP for this feature is ID-based lookup only. No fuzzy title matching, no semantic query. The LLM first calls `list_outline`, reasons about which entry is relevant, then calls `get_section` with the chosen `id`. Keeping the surface minimal prevents the LLM from accidentally substituting retrieval for reasoning.

## 5. Trigger Conditions

Outline extraction runs on a source document if **any** of:

1. The user explicitly requests it for that source.
2. The source has an embedded PDF outline (`/Outlines` — see §6 Layer 1). Always run in this case; it is free.
3. A cheap heuristic pre-filter (regex on first N pages for "Contents"/"Table of Contents" headings, dot-leader patterns like `\.{3,}\s*\d+\s*$`, or high density of short lines ending in integers) flags the document as TOC-bearing.

Page-count thresholds alone are insufficient and are not used as a trigger. A 20-page article can have no TOC; a 40-page scanned lecture-notes compilation might.

## 6. Algorithm

The algorithm is layered from cheapest/most-reliable to most-expensive. Layers 1–3 apply to both born-digital and OCR'd PDFs; §8 documents OCR-specific parameter tuning and quality escalation on top of this core.

### Layer 1 — Structural metadata (no LLM)

- **`/Outlines` (bookmarks).** If present, destinations are already pdf_page references. Extract titles, hierarchy levels, and start pages directly. Compute `end_pdf_page` from sibling ordering. `confidence = 1.0`, `source = "pdf_outline"`. Done.
- **`/PageLabels`.** Independent of outline presence. If `/PageLabels` exists, it provides an exact `pdf_page_index → printed_label` lookup table, resolving the Roman-front-matter / arabic-reset problem deterministically. Use as the mapping source of truth when present.

Most trade and academic books exported from LaTeX or Word have one or both. If `/Outlines` is present and matches the document's first-level structure, no LLM call is needed.

### Layer 2 — TOC entry extraction (LLM)

Triggered only when structural metadata is absent or insufficient and the heuristic pre-filter signals TOC presence.

- Restrict scan to the first **N** pages (config; default 40).
- Per-page: use text extraction first. OCR only for pages where extraction yields empty / garbage text.
- Chunk into size-**M** groups (config; default 5 pages), using `ceil(N/M)` chunks — last chunk may be short.
- Per chunk, send the LLM a JSON payload:
  ```json
  {"pages": [{"pdf_page": 8, "text": "..."}, ...]}
  ```
  with an instruction to identify TOC entries and return `pdf_page` only from the JSON, **never** from numbers appearing inside the page text. The LLM returns structured entries plus a boolean `is_toc_page` per input page.
- **Stopping rule:** after at least one `is_toc_page = true` has been seen, stop at the first chunk that contains zero TOC pages. This bounds cost and handles variable TOC length while tolerating front matter (copyright, dedication) preceding the TOC.
- **Hard cap:** if no TOC page is seen in the first N pages, stop and report no outline found (do not escalate).
- **Boundary handling:** merge contiguous TOC ranges across chunk boundaries before entry consolidation.

Output of this layer: a list of raw `{title, level, printed_page}` entries with no `pdf_page` yet.

### Layer 3 — Offset resolution via anchor scan (deterministic, no LLM)

The goal is to discover the offset between printed page numbers and pdf_page indices by finding one TOC entry's actual location in the document, then applying that offset to every other entry. The offset is always `≥ 0` — front matter only adds pages, never removes them — so the scan direction is forward from `printed_page` onward.

If `/PageLabels` is present, skip this layer entirely and invert the label table to resolve each entry's `printed_page` directly.

Otherwise:

1. **Pick anchor candidates.** From the Layer 2 entries, select the top-**K** most distinctive (default `K = 3`). Selection is an open sub-question (see §8); a reasonable starting heuristic is: title length ≥ 3 words, contains a chapter number or other identifying token, skews toward the first few chapters (offsets are most stable near the front-matter boundary), and is unique within the TOC.

2. **Forward scan per candidate.** For each anchor with `printed_page = P`, scan pdf_pages from `P` through `P + MAX_OFFSET` (default `MAX_OFFSET = 100`, configurable; may also be expressed as a fraction of total pages for very long works). On each pdf_page, test whether the page text contains the anchor title using:
   - exact normalized match (lowercase, punctuation stripped, whitespace squeezed), OR
   - fuzzy match via `fuzzywuzzy.partial_ratio ≥ 80` (threshold drawn from the HiPS paper; tunable).

3. **Two-pass matching.** Running headers on every chapter page will also match the title, so prefer the true chapter opening:
   - **Pass A (preferred):** accept only matches where the title appears as a heading-like line. What qualifies as "heading-like" is an open sub-question (see §8); candidate signals include: appears within the first few lines of the page, sits on its own line with whitespace above/below, shorter than average line length for the document.
   - **Pass B (fallback):** if Pass A finds no match within `MAX_OFFSET`, accept the first occurrence of a fuzzy match anywhere on the page. Even a running-header hit gives us a correct offset — the chapter opened on or before that pdf_page — and we can step backward to find the opening.

4. **Derive and cross-validate.** `offset = matched_pdf_page - printed_page`. Apply this offset to 2–3 other TOC entries and test whether their titles appear on `printed_page + offset` (again via fuzzy match). If at least two entries confirm, accept the offset globally and assign `start_pdf_page = printed_page + offset` to every entry.

5. **Multi-segment detection.** If cross-validation fails consistently for a cluster of later entries (their derived offset differs from the global offset by a stable amount), the document has multiple numbering segments — common in multi-volume works, anthologies, and books with unnumbered plates. Re-run the anchor scan on a late-book entry to discover the second segment's offset. Store per-segment offsets and apply them by printed-page range.

6. **Resolution failure.** If no anchor candidate yields a validated offset, emit a **partial outline**: entries keep `title`, `level`, `parent_id`, and `printed_page`, but `start_pdf_page = null`, `end_pdf_page = null`, `confidence = 0`. `list_outline` returns these entries so the LLM still sees document structure; `get_section` refuses with a clear error. Better than silent wrong answers.

Confidence scoring:
- Exact match, offset cross-validated by ≥ 2 entries: `0.95`.
- Fuzzy match (Pass A), offset cross-validated: `0.85`.
- Pass B match (running-header fallback), offset cross-validated: `0.7`.
- Cross-validation failed for this entry but offset was accepted globally: `0.5`.
- Unresolved entry in partial outline: `0.0`.

`source = "anchor_scan"` for entries resolved this way. Layer 1 entries keep `source = "pdf_outline"` or `"page_labels"`.

### Layer 4 — Range assignment

Sort accepted entries by `start_pdf_page`. For each entry, `end_pdf_page = next_same_or_higher_level_entry.start_pdf_page - 1`. The final entry ends at the document's last pdf_page. Entries at deeper levels inherit their parent's end as an upper bound if no sibling follows. Unresolved entries (`start_pdf_page = null`) are skipped during range assignment and retain null ranges.

## 7. Storage

`DocumentOutline` is stored as a versioned artifact attached to the `source_id`. It is immutable per version; re-extraction creates a new version. The Document Pipeline exposes the latest version through `list_outline`. This mirrors plan.md's "each artifact should be immutable or versioned where possible."

## 8. OCR-Heavy Sources — Tuning and Open Sub-Questions

Niche-field academic books are frequently only available as scanned PDFs. These are exactly the documents where chapter-scoped retrieval matters most. The Layer 3 anchor-scan algorithm applies to OCR sources unchanged — fuzzy matching handles title distortion, and offset discovery doesn't depend on page-number OCR being reliable — so there is no separate "OCR algorithm." What changes is parameter tuning and OCR-quality escalation.

### OCR-specific considerations

- **Layer 1 is usually empty.** Scanned PDFs rarely carry `/Outlines` or `/PageLabels`, so we go straight to Layers 2–3.
- **Layer 2 entry extraction is more fragile under OCR.** Dot leaders become scattered dots, columns misalign, and printed page numbers may be garbled — which matters for `printed_page` but *not* for the offset-resolution algorithm, which finds ground truth by searching the body. Even if a TOC entry's `printed_page` is off by one due to OCR error, the anchor-scan title match still finds the real chapter start (and the real `start_pdf_page` can be used to back-correct the `printed_page` post-hoc).
- **OCR quality tier escalation.** If Layer 2 output is malformed (missing entries, implausibly many entries, broken `printed_page` values), rerun Layer 2 on the first N pages using the high-tier OCR backend before giving up. The tiered OCR pipeline already exists; this just wires it in as a conditional retry.
- **Fuzzy threshold tuning.** The default `partial_ratio ≥ 80` (from HiPS) is calibrated on born-digital text. For heavy OCR noise, a lower threshold may be needed. Treat the threshold as configurable and tune on the golden-file eval set.
- **Running-header false-positive risk is higher** because OCR makes titles less distinctive. Pass A (heading-like detection) is therefore more important for OCR sources than for born-digital ones.

### LLM usage summary

The LLM is used only for Layer 2 (TOC entry extraction). Layer 3 offset resolution is entirely deterministic (fuzzy string matching + arithmetic + cross-validation) in both born-digital and OCR cases. There is no per-entry LLM verification layer.

The only OCR-specific LLM interaction is the possibility of re-invoking Layer 2 on higher-tier OCR output if the first pass looks broken — still LLM-for-extraction, just with better input.

### Open sub-questions (to resolve before implementation)

1. **Anchor selection policy.** Pure title length, weighted by TOC position, or something more sophisticated? No decision yet. Starting default is the heuristic in Layer 3 step 1; tune on the eval set.
2. **"Heading-like" detection signals for Pass A.** Candidate signals: first N lines of page, isolated line (blank lines above/below), line length below document average, all-caps, font-size proxy via OCR line-height (if OCR backend exposes it). Which combination gives the best precision/recall? No decision yet.
3. **Malformed-Layer-2 detection rule.** What triggers OCR-tier escalation? Candidate heuristics: fewer than expected entries given document length, `printed_page` values non-monotonic, high fraction of entries with garbled titles (non-ASCII or single-letter). Needs an eval-driven rule.
4. **Eval methodology.** Hand-labeled ground truth for a small curated set of scanned academic books, scored on entry recall and `start_pdf_page` accuracy (off-by-one tolerance band). Exact set and tolerance are TBD.
5. **MAX_OFFSET sizing.** Default 100 works for most books. Reference works with extremely long front matter (introductions, translators' notes, author bios, glossaries of abbreviations) may need more. Consider making it a fraction of total pages with a floor.

These are the next brainstorming items. Implementation can begin with the defaults above, but the eval set needs to be assembled in parallel so parameter tuning has ground truth to optimize against.

## 9. Dependencies

This feature depends on:

- A **minimal multi-provider LLM shim** (not the full plan.md Model Gateway). A small `LLMClient` protocol with a single structured-output `chat(messages, response_format)` method, plus thin adapters for Claude, OpenAI, and Gemini. Provider is selected by config/env. Only Layer 2 (TOC entry extraction) uses the LLM; Layer 3 is entirely deterministic. Future Model Gateway features (prompt versioning, caching, retries, cost tracking) will layer on top of this interface without breaking callers.
- The existing PDF text extraction pipeline (Stage 2 baseline).
- The existing tiered OCR pipeline (small/medium/high), including the ability to re-run at a higher tier conditionally.
- A fuzzy string-matching library (e.g. `rapidfuzz` / `fuzzywuzzy`) for Layer 3 anchor matching.
- A heuristic pre-filter module (new, small; ships with this feature).

## 10. Testing

- **Unit:** structural metadata parsing (`/Outlines`, `/PageLabels`), heuristic pre-filter, anchor scan (forward search, Pass A / Pass B selection, offset derivation, cross-validation, multi-segment detection), range assignment, ID generation.
- **Integration with mocked LLM:** chunked TOC extraction with deterministic fake responses — verifies chunk math, stopping rule, boundary merge.
- **Golden-file:** a small set of real PDFs (born-digital book, LaTeX export with bookmarks, article with no TOC, scanned book, multi-segment book) with hand-verified expected outlines. Compare extracted outline to golden, score entry recall and `start_pdf_page` accuracy (within a small off-by-one tolerance).
- **Tool-surface tests:** `list_outline` and `get_section` behavior including null-range entries (partial outline), invalid `entry_id`, out-of-range pages.

Live LLM calls are not used in test suites; an eval harness (plan.md §Evaluation Harness) runs them separately on a curated set.

## 11. Decisions Recorded

- Feature is **document outline extraction**, not TOC-page labeling. Per-page `is_toc` flags are an intermediate, not an output.
- Output is **structured entries with resolved pdf_page ranges**, not boolean labels.
- **Structural metadata (`/Outlines`, `/PageLabels`) is always tried first** and preferred when sufficient. LLM only runs when structural metadata is absent or insufficient.
- **Tool surface is ID-based only** for MVP of this feature: `list_outline`, `get_section(id)`. No semantic search.
- **Triggers are explicit request, embedded outline presence, or heuristic TOC detection.** Page count alone is not a trigger.
- **Printed → pdf_page mapping is fully deterministic via anchor scan.** LLM is used only for Layer 2 (TOC entry extraction), never for offset resolution. This applies to both born-digital and OCR-heavy sources; OCR sources use the same algorithm with tuned parameters and optional OCR-tier escalation (§8).
- **Partial outlines are valid output.** If the anchor scan fails to validate an offset, entries are returned with null pdf_page ranges rather than silently guessed.
- **Multi-provider LLM support via a minimal shim.** A small `LLMClient` protocol with Claude, OpenAI, and Gemini adapters ships as step 1 of implementation. Full Model Gateway (caching, cost tracking, prompt versioning) is deferred and will layer on top of the same interface.
- **Feature is Phase 2** relative to plan.md MVP. Not blocking the first end-to-end essay pipeline.
