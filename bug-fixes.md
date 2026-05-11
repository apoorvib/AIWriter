# Bug Fixes & Optimization Backlog

Findings from a workflow audit of the AI Essay Writer pipeline (task spec → topic ideation → research planning → research → outlining → drafting → validation → tone alignment → revision → export). Each item is a candidate fix; severity is a rough cut, not a release plan.

---

## Logic Flaws

### L1. `ResearchPlan` semantic constraints are advisory only, not enforced
- **Status:** ⏭️ Will most likely skip — not a strict logic flaw; more a missing guardrail on LLM compliance. Overlaps with Q1. Revisit only if outline quality regressions trace back to plan non-compliance.
- **Where:**
  - `essay_writer/research_planning/service.py:51` produces a plan with `source_requests` (validated `SourceLocator` objects), `expected_evidence_categories`, `source_requirements` (rubric-derived), and `uploaded_source_priorities`.
  - `essay_writer/research/service.py:41` (`FinalTopicResearchService.extract()`) takes no `research_plan` argument — research never sees the plan directly.
  - `essay_writer/outlining/service.py:170-186` passes the plan into the outline LLM prompt as soft context but never validates the LLM's output against it.
- **What actually works today:** The plan's `source_requests` are load-bearing through source resolution — they determine which `SourceTextPacket` objects research receives. So the plan does shape *what evidence exists*.
- **What is broken:** The plan's semantic output (`expected_evidence_categories`, `source_requirements`, `uploaded_source_priorities`) is shown to the outline LLM as advisory context only. Nothing checks that the outline:
  - covers every `expected_evidence_category` (e.g. plan expects a counterargument, outline omits one — no warning),
  - cites at least one note from each `priority="high"` source,
  - satisfies every item in `source_requirements` (e.g. "use 3 peer-reviewed sources").
  Drafting proceeds regardless.
- **Fix direction (minimal):** After the outline LLM returns, deterministically validate coverage against `expected_evidence_categories` (via `note.evidence_type`), priority sources, and `source_requirements`. On gap: re-prompt the outline LLM with the specific gap, or block the job.
- **Fix direction (stronger):** Also pass `research_plan` into `FinalTopicResearchService.extract()` so research can target the expected categories during note extraction, giving the post-outline validator real evidence to check against.

### L2. `section_source_map` note_ids and section_ids are never validated
- **Where:** `essay_writer/drafting/service.py:182` and `essay_writer/drafting/revision.py:295`.
- **Impact:** The LLM can emit `note_42` that doesn't exist in the evidence map, or `section_3` that isn't in the outline. Both get persisted as orphans, breaking traceability.
- **Fix direction:** On draft persistence, intersect emitted IDs against the canonical evidence map / outline; reject or repair on mismatch.

### L4. Revision is one-shot, not a convergent loop
- **Where:** `essay_writer/jobs/workflow.py:305` records `validation_complete` and routes to `revision`; `backend/routes/pipeline.py:58` runs revision exactly once.
- **Impact:** No iteration cap, no convergence check, no "revise until pass or N tries". If draft v2 still fails, the job sits in `revision`.
- **Fix direction:** Bounded loop with max N passes, exit on validation pass, persist intermediate versions.

### L5. Empty indexes are marked usable
- **Where:** `essay_writer/sources/ingestion.py:104` only checks `chunks` truthiness.
- **Impact:** Pages with zero extracted text (and failed OCR) still produce an "indexed" source. Downstream retrieval returns nothing — silently.
- **Fix direction:** Require non-empty chunk content; mark source as `unreadable` and surface to user before topic ideation.

### L6. Style revision regenerates prose but reuses the parent's `section_source_map`
- **Where:** `essay_writer/drafting/style_revision.py:97` (uses dataclass `replace()`).
- **Impact:** Citation lineage goes stale the moment style edits remove a quote. Validation still believes those notes were used.
- **Fix direction:** Re-derive `section_source_map` from the rewritten prose, or have the style-revision LLM emit an updated map.

### L7. Topic re-ideation has no structural dedup against rejected topics
- **Where:** `essay_writer/topic_ideation/service.py:92` enumerates `topic_001..N` per round; the prompt instructs "honor rejection reasons" without structural enforcement.
- **Impact:** Round 3 can regenerate semantically duplicate candidates (different wording, same idea) of rejected ones.
- **Fix direction:** Embed rejected topics with structured fields, add LLM-side dedup instruction with explicit similarity ban, optionally post-filter via embedding similarity against rejects.

### L8. `select_topic` doesn't validate `source_leads` against `job.source_ids`
- **Where:** `essay_writer/jobs/workflow.py:202`.
- **Impact:** If ideation invented a source ID, it lands silently in the selected topic; research either skips it or warns without blocking.
- **Fix direction:** Validate every `source_lead.source_id ∈ job.source_ids` at selection; reject the candidate or strip the lead.

### L9. Export can be generated without a fresh validation report after manual edits
- **Where:** `backend/routes/drafts.py:52` saves user edits; `essay_writer/exporting/service.py:19` reuses the prior `validation_report_id`.
- **Impact:** The export's "validated" claim no longer reflects the exported text after a user edit.
- **Fix direction:** Hash the draft body; require a validation report whose `draft_hash` matches before export. Invalidate report on user edit.

### L10. Adversarial-prompt scanning runs twice with no reconciliation
- **Where:** Deterministic regex in `essay_writer/task_spec/parser.py:27` and an LLM check in the same parse call.
- **Impact:** If they disagree, no tiebreaker — flags can be inconsistent across runs.
- **Fix direction:** Define precedence (e.g., union of both, regex wins on overlap), reconcile in `_merge_adversarial_flags`.

### L11. No idempotency guard on manual revision
- **Where:** `essay_writer/manual_revision/service.py:143`.
- **Impact:** Two identical `create_run()` calls produce duplicate request/run IDs and burn LLM cost twice.
- **Fix direction:** Hash the request payload; return the existing run if a matching in-flight or recent one exists.

### L12. Research skips manifest-to-index consistency check
- **Where:** `essay_writer/topic_ideation/retrieval.py:149` calls `source_store.load_chunks()` without verifying chunk_ids exist in the manifest, then silently drops missing chunks at line 158.
- **Impact:** A stale manifest produces notes for outdated chunks; research thinks it cited something the user can't find.
- **Fix direction:** Validate chunk_id ∈ manifest before retrieval; surface missing-chunk warnings as a stage error.

### L13. `known_weak_spots` accumulates monotonically across style revisions
- **Status:** ✅ Fixed in `essay_writer/drafting/style_revision.py:99`. The append loop is replaced with `weak_spots = risks if risks else list(draft.known_weak_spots)` — the LLM's current assessment is treated as authoritative when non-empty (replaces parent list); when empty, the parent list is carried forward as a safety net for the "LLM failed to assess" case rather than silently dropping signal. Full revision (`revision.py:278`) already overwrites payload-driven, so styles are now consistent.
- **Where:** `essay_writer/drafting/style_revision.py:99`.
- **Impact:** Fixed weak spots never decay — list grows unbounded and misleads downstream stages and the user.
- **Fix direction:** Reconcile against current draft each pass; remove fixed entries.

---

## Cost / Performance

### P1. No Anthropic prompt caching anywhere
- **Status:** ✅ Fixed across the full pipeline.
  - **System prompt caching (Phase 1, automatic):** Claude adapter (`llm/adapters/claude.py`) wraps any system prompt ≥6000 chars in `cache_control={type:"ephemeral"}`. Drafting / revision / style-revision (each carrying the full ~26KB anti-AI skill doc) hit this automatically; smaller system prompts stay as plain strings to avoid the 1.25× write surcharge.
  - **User-block static/mutable split (Phase 2, per-stage):** `LLMClient.chat_json` accepts `user: str | list[UserBlock]` where `UserBlock(text, cacheable=True)` becomes a cache breakpoint when ≥6000 chars. Stages with the split:
    - `drafting/service.py` + `drafting/revision.py` — share `build_static_drafting_context_json` so the static prefix is byte-identical between drafting and revision (cache hits across both stages).
    - `topic_ideation/service.py` — static = task_spec + source_cards + manifests + maps; mutable = user instruction + previous candidates + rejected topics. Re-ideation rounds reuse the prefix.
    - `research/service.py` — static = job + task_spec + selected_topic + (deduped) retrieved chunks; mutable = instruction prelude + max_notes.
    - `outlining/service.py` — single cacheable static block (entire context) + small mutable instruction. Wins on outline regen.
    - `validation/service.py` — static = task_spec + evidence_map + known_source_metadata; mutable = bibliography + deterministic issues + draft text. Hits cache on every revision-loop validation pass.
    - `tone_alignment/prompts.py` — static = task spec snippet + writing_style samples; mutable = anti-AI signals + draft text. Same revision-loop benefit.
  - Cache-stability tests guard the byte-stable static prefixes (`test_research_static_block_is_byte_stable_for_cache_reuse`, `test_topic_ideation_static_block_is_byte_stable_across_rounds`, drafting/revision shared-prefix test).
  - Stages NOT split: `task_spec/parser.py` (one-shot per job), `writing_style/service.py` (one-shot per job), `sources/summary.py` (has its own content-hash cache via P4), `drafting/style_revision.py` (system prompt is cached via Phase 1; user-side split deferred — style revision rarely runs multiple times).
- **Where:** All LLM call sites — `task_spec`, `topic_ideation`, `research`, `outlining`, `drafting`, `revision`, `validation`, `tone_alignment`. None set `cache_control`.
- **Specific high-value caches:**
  - Full `ANTI_AI_SKILL_DOCUMENT` (~20KB) inlined into drafting/revision/style-revision system prompts on every call.
  - Full `evidence_map` + `source_packets` re-serialized per revision pass.
  - `task_spec` and `source_card` summaries re-sent on every topic ideation round.
- **Impact:** Conservatively 50–80% input-token reduction across the pipeline.
- **Fix direction:** Mark static blocks with `cache_control: {type: "ephemeral"}`; structure prompts as `[cached system + cached context] + [mutable instruction]`.

### P2. Per-source sequential index queries
- **Status:** ✅ Fixed. `_retrieve()` now opens one `SQLiteChunkIndex` per source and reuses it across all queries within the call (closed in `finally`).
- **Where:** `essay_writer/topic_ideation/retrieval.py:117` opens a fresh `SQLiteChunkIndex` connection per query in a loop.
- **Impact:** 5 sources × 3 queries = 15 connection cycles per topic round.
- **Fix direction:** Reuse one connection per source; batch queries; consider an in-memory index for hot jobs.

### P4. Source card summary regenerated every ingestion
- **Status:** ✅ Fixed via `essay_writer/sources/source_card_cache.py`. New `SourceCardCache` keys cached LLM payloads by sha256 of (excerpt texts + summary char limit + model) so identical content hits cache regardless of `source_id`, file name, or which `SourceStore`. Default location: `<store.root>/_source_card_cache/`; injectable for shared global cache. Cache hit skips the LLM call entirely (and works without an LLM client present).
- **Where:** `essay_writer/sources/ingestion.py:142`.
- **Impact:** Even identical source content re-pays for the summary LLM call.
- **Fix direction:** Key the summary cache by content hash; one LLM call per unique source body, not per job.

### P5. Manual revision runs deterministic checks twice
- **Where:** `essay_writer/manual_revision/service.py:193, 215`.
- **Impact:** For 5K+ word essays, redundant deterministic parsing on both source and result drafts.
- **Fix direction:** Cache deterministic results keyed by draft hash.

### P6. Drafting is monolithic
- **Where:** `essay_writer/drafting/service.py` drafts the whole essay in one call. `docs/plan.md:246` explicitly recommends per-section decomposition.
- **Impact:** For 3000+ word essays, context pressure rises and a single section regression forces a full re-draft.
- **Fix direction:** Decompose by outline section; let sections be regenerated independently; assemble at the end.

### P7. Full source card context in every topic ideation call
- **Status:** ✅ Fixed. Split `build_topic_ideation_context` into `build_topic_ideation_static_context` (task spec + source cards + manifests + maps) and `build_topic_ideation_mutable_context` (user instruction + previous candidates + rejected topics). Service sends `[UserBlock(static, cacheable=True), UserBlock(mutable_suffix)]` so re-ideation rounds reuse the cached prefix. Verified byte-stable across rounds in `test_topic_ideation_static_block_is_byte_stable_across_rounds`.
- **Where:** `essay_writer/topic_ideation/context.py:34` embeds `source_card.to_context(max_chars=4000)` per source per call.
- **Impact:** 10 sources = 40KB static context retransmitted every ideation round.
- **Fix direction:** Cache via P1 (prompt caching) or compress per-round.

### P8. Index manifest preview data bloats topic-ideation context without steering behavior
- **Status:** ✅ Fixed (conservative trim, not full removal). Default `index_preview_chars` in both `build_topic_ideation_static_context` and `build_topic_ideation_context` lowered from 180 → 60. The preview is NOT informational-only — it's load-bearing for chunk_id selection (the LLM uses it to know what each `chunk_id` is about) — so removing it entirely would degrade lead quality. 60 chars + heading is enough to identify the chunk while cutting the per-chunk preview ~3×. With ~80 entries × 5 sources, this drops the manifest portion of the cacheable static prefix from ~70KB toward ~24KB; the remaining cost is amortized through P1 caching across re-ideation rounds.
- **Where:** `essay_writer/topic_ideation/context.py:41`.
- **Impact:** Preview is informational only; the LLM ignores it in favor of `source_requests`.
- **Fix direction:** Drop the preview from prompt context, or move it behind a "if asked, look here" pointer.

### P9. Full chunk text re-encoded in research note extraction
- **Status:** ✅ Fixed via dedup + cache-prefix split. Fix direction in original entry was wrong about feasibility — Anthropic API has no cross-request chunk handles, the LLM must see the text — so the implemented fix is:
  - **Content-hash dedup:** new `_dedupe_chunks_by_content()` removes chunks whose normalized text is identical. Catches the case where a `SourceTextPacket` derived from an explicit page locator and an FTS-retrieved chunk both cover the same page text under different `chunk_id` values; the duplicate text was up to ~25k extra input tokens on overlap-heavy retrievals.
  - **Phase 2 caching:** `extract()` now sends `[UserBlock(static, cacheable=True), UserBlock(mutable_suffix)]`. The static block contains the full job + task spec + selected topic + retrieved chunks (~80KB on a typical run). Re-runs of research on the same retrieval hit the prompt cache. Test `test_research_static_block_is_byte_stable_for_cache_reuse` verifies byte-stability.
  - Outlining (`outlining/service.py:188`) was also called out in this entry — that's covered separately as part of the P1 finishing work.
- **Where:** `essay_writer/research/service.py:85` JSON-encodes every `chunk.text` (line 133).
- **Impact:** 80 notes × 1KB chunks = 80KB serialized to JSON, then reparsed by the LLM, then rebuilt similarly in outline (`outlining/service.py:188`).
- **Fix direction:** Pass chunk handles + cached chunk-store on the LLM side; deduplicate references.

### P10. Bibliography metadata recomputed on every validation
- **Where:** `essay_writer/validation/citations.py:32` recalculates `_metadata_identifiers` per call with regex normalization.
- **Impact:** 5+ sources × 3 revisions = wasted CPU; trivial but accumulates.
- **Fix direction:** Memoize identifiers per source card.

### P11. Validation re-reads full essay + evidence per iteration
- **Where:** `essay_writer/validation/service.py:43`.
- **Impact:** Each revision pass re-runs deterministic checks and full LLM call with no cached input.
- **Fix direction:** Cache deterministic results; apply P1 caching to evidence + draft if unchanged sections exist.

### P12. No parallelization of independent revision checks
- **Where:** `essay_writer/manual_revision/service.py:318`.
- **Impact:** Validation, tone, and deterministic checks run partially serial when they could fan out.
- **Fix direction:** ThreadPoolExecutor across all three independent checks.

---

## Quality

### Q1. Required structure isn't enforced on the outline
- **Status:** ✅ Fixed (tier-1 fuzzy validator). New `validate_outline_coverage()` runs after the LLM returns and flags every `task_spec.required_structure` clause that no section heading + purpose plausibly satisfies. Match is fuzzy: substring containment, word-level overlap requiring majority of label words, plus a 5-char shared-prefix stem so "Methodology" matches "Methods Used / describe research methods" without flagging unrelated words like "math". Warnings flow into a new `ThesisOutline.warnings` list (schema field added with default `list`, backward compatible). Tier 2 (LLM-judge fallback) and tier 3 (re-prompt loop) intentionally deferred — tier 1 catches the common case for a fraction of the cost.
- **Where:** `essay_writer/task_spec/schema.py:86` defines `required_structure`; `essay_writer/outlining/service.py` includes it as context but never asserts coverage.
- **Impact:** An assignment requiring "literature review" + "methodology" can produce an outline with neither.
- **Fix direction:** Validate outline section labels against `required_structure`; reject or re-prompt on miss.

### Q2. Citation verification is substring-match only
- **Where:** `essay_writer/validation/citations.py:32`.
- **Impact:** "Smith (2020)" vs "Smith, J., et al. (2020)" mismatches. No structured bibliography parsing, no LLM-judge fallback.
- **Fix direction:** Parse bibliography per citation style, or add LLM-judge as a second pass when string match fails.

### Q4. Evidence dedup is by `chunk_id` only
- **Status:** ✅ Fixed (literal + tuple tier). Original entry's premise was wrong — `_result_from_payload` had NO note-level dedup at all (chunk_id dedup only happened at the input chunk level via `_flatten_chunks`). Fix in `research/service.py`:
  - New `_claim_signature()` normalizes a claim (lowercase, collapse whitespace, strip trailing punctuation).
  - The note loop now keys a `seen_signatures: set[(chunk_id, claim_signature)]` and drops any note whose tuple has already been seen, with a warning naming the dropped chunk + claim prefix.
  - Catches: literal duplicates, capitalization-only variants, trailing-punctuation-only variants, same-chunk + same-claim emitted twice with different paraphrases.
  - Does NOT catch: cross-chunk semantic duplicates or word-order rephrasings — those require embeddings, intentionally deferred (tier 2).
  - Distinct claims drawn from the same chunk are preserved (multiple notes per chunk is normal and desirable).
  - Tests: 3 in `tests/research/test_service.py` covering literal dup, capitalization-variant dup, and the negative case (distinct claims same chunk preserved).
- **Where:** `essay_writer/research/service.py:261`.
- **Impact:** Two notes citing the same chunk with paraphrased quotes both survive into the outline; pads evidence count without adding signal.
- **Fix direction:** Add semantic similarity dedup (embedding cosine threshold) on top of chunk_id dedup.

### Q5. Anti-AI ban list vs. grounded attribution can deadlock
- **Where:** Anti-AI skill bans "experts," "scholars," "many"; grounded attribution sometimes requires them.
- **Impact:** LLM has no priority rule and resolves inconsistently.
- **Fix direction:** Allow banned attributions when wrapped in a real citation; encode the exception in the skill.

### Q6. Rejected topic feedback loop broken for `parent_topic_id` refinement
- **Status:** ✅ Fixed across all three layers the original entry undercounted:
  - **Schema:** `RejectedTopic` (topic_ideation/schema.py) gains `parent_topic_id: str | None = None`. Backward-compatible — old persisted rejections load with `None` default.
  - **Workflow:** `EssayWorkflow.reject_topic` (jobs/workflow.py:192) now copies `topic.parent_topic_id` from the looked-up candidate into the rejection record. Previously discarded.
  - **Prompt payload:** `_rejected_payload` (topic_ideation/context.py) includes `parent_topic_id`. Prompt instructions in `prompts.py` updated to teach the LLM to treat the parent as cautioned, the specific refinement angle as banned (rather than over-correcting and banning the parent direction outright).
  - Tests: 1 new in `tests/topic_ideation/test_context.py` (parent_topic_id reaches prompt payload), 1 new in `tests/jobs/test_workflow.py` (rejection record carries parent from candidate).
- **Where:** `essay_writer/topic_ideation/schema.py:27` defines `parent_topic_id`; `essay_writer/topic_ideation/context.py:_rejected_payload` only passes `topic_id`, `title`, `reason`.
- **Impact:** A user rejecting a refinement of `parent_001` doesn't inform the next round that the parent direction is also dispreferred.
- **Fix direction:** Include `parent_topic_id` in rejected payload; propagate parent-level dispreference.

### Q7. Outline sections can omit evidence for required structure clauses
- **Status:** ✅ Fixed alongside Q1 in `validate_outline_coverage()`. Two checks:
  - **Required source coverage:** computes `used_source_ids` (union across sections via `note_ids → evidence_map.notes`) and warns for every `research_plan.source_requests[i].source_id` not present.
  - **Priority='high' coverage:** separately warns when a `research_plan.uploaded_source_priorities` entry with `priority='high'` is silently dropped — this is a louder signal than a generic source_request miss.
  - Warnings flow into `ThesisOutline.warnings`. The original entry's title talked about "required structure clauses" but the body was about source coverage; the structure-clause concern is what Q1 covers, so Q7's fix is purely the source-coverage axis.
- **Where:** `essay_writer/outlining/service.py:_sections_from_payload` validates note_ids against `evidence_map.notes` but doesn't validate that section note_ids map back to sources selected in `research_plan.source_requests`.
- **Impact:** Required source from the plan can be skipped without warning.
- **Fix direction:** Cross-validate section coverage against `source_requests`.

### Q8. OCR can mask silent degradation
- **Status:** ✅ Fixed.
  - New `essay_writer/sources/text_quality.py` provides `text_signal_score()` (combines word-like-token rate, common-word density, and clean-character composition) and `is_better_extraction()` (replacement rule: empty never wins; missing/empty current always loses; otherwise candidate must score >= current, and ties break on length).
  - `ingestion._merge_partial_ocr_pages` and `access._merge_lazy_ocr_pages` both replaced their bare `char_count > current.char_count` comparison with `is_better_extraction()`. A longer-but-noisier OCR page no longer overwrites cleaner text-layer extraction.
  - Lazy-OCR replacement is the higher-blast-radius path (results persist to disk via `save_text_artifacts`); the score gate prevents silent corruption there.
  - Tests: 7 in `tests/sources/test_text_quality.py` covering clean-vs-noisy separation, the longer-but-noisier OCR rejection case, and recovery from garbled text-layer extraction.
- **Where:** `essay_writer/sources/ingestion.py:77` and `access.py:330` merge OCR by `char_count` comparison.
- **Impact:** OCR longer-but-wrong text replaces correct shorter extraction.
- **Fix direction:** Add a quality heuristic beyond char_count (e.g., dictionary hit rate or confidence score from OCR).

### Q9. Empty pages masked by "low" quality label
- **Status:** ✅ Fixed.
  - Added `text_quality="empty"` as a distinct bucket in `essay_writer/sources/map.py:_page_quality`. A page with no `text.strip()` is now `"empty"`, separate from low-but-present `"low"`/`"partial"`.
  - `access._resolve_pdf_pages` no longer returns a packet whose `pdf_page_start/end` claims pages that contributed no text. The packet's range narrows to the bounding box of actually-included readable pages; if every requested page is empty, a warning packet is returned instead.
  - `access._resolve_section` and `access._resolve_chunk` now reject empty-text units with a warning packet rather than emitting a hollow citation.
  - `access._combined_quality` propagates `"empty"` upward; `_pages_requiring_ocr` now includes `"empty"` so lazy OCR triggers on these pages.
  - Tests: 3 new in `tests/sources/test_source_access.py` covering middle-page-empty range narrowing, all-empty rejection, and quality bucket distinction.
- **Where:** `essay_writer/sources/map.py:200`; lazy OCR in `access.py:215`.
- **Impact:** A user citing "page 5" can get an empty packet if both extraction methods returned nothing on that page; warning is logged but page stays in source map as if usable.
- **Fix direction:** Mark fully-empty pages explicitly; exclude from citation packets.

### Q10. Writing style payload applied inconsistently
- **Where:** Three places call `build_writing_style_prompt_block()`: `drafting/service.py:147`, `revision.py:258`, `style_revision.py:226`.
- **Impact:** No merging or conflict resolution if both `writing_style_payload` and tone-alignment conflicts are present.
- **Fix direction:** Single composition function that resolves writing-style + tone + anti-AI in one structured block with explicit precedence.

### Q11. Convergence not measurable on revision
- **Where:** `essay_writer/manual_revision/service.py:211`.
- **Impact:** No automatic loop; user must re-trigger; no convergence metric reported.
- **Fix direction:** Track per-pass deltas (unsupported claims count, anti-AI hit count) and surface convergence (or lack of) to the user.

---

## Top 5 to Fix First

1. **Wire prompt caching** on the anti-AI skill, evidence map, source packets, and task spec. Single highest ROI change. (P1)
2. **Make `ResearchPlan` actually constrain research** — enforce `expected_evidence_categories`, retry on shortfall — or delete the stage. (L1)
3. **Validate `section_source_map` IDs** against the evidence map at draft persistence. (L2)
4. **Define explicit precedence between anti-AI rules and tone alignment** in the system prompt; stop letting `prefer_tone` re-introduce banned patterns. (L3)
5. **Make revision a bounded loop** (max N passes, exit when validation passes), and require export to consume the *latest* validation report covering the *current* draft text hash. (L4 + L9)
