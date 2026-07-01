# Anti-AI Audit: Per-Block Redesign (Un-brick the Audit Commit)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `commit_anti_ai_audit` submittable again by replacing the *per-skill-line* `line_audit` (one row for all 458 lines of `anti-ai-detection-SKILL.md`) with a *per-block* audit — one row per blank-line-separated block of the skill file (~191 blocks). This fixes the un-committable ~100K-token payload, unbricks the validation/export pipeline that depends on the audit commit, and refocuses the auditor's attention on applying guidance instead of hashing individual blank lines.

**Granularity decision (user, 2026-07-01):** one audit row per *paragraph/block* of the skill file, not per line. Blocks are cheap and robust to derive (split on blank lines — no `**Rule:**` regex parsing, so no drift risk), map 1:1 to the file's structure, keep a literal "you went through the whole file" coverage guarantee, and each block's own hash is the file-possession proof (so no separate line-hash challenge is needed).

## Context: one root cause, two bugs, and a quality regression

Discovered while running `/essay-write` (job `job-prov-agrun_601c680d781f_...`, draft `draft_55ddcf148ce1`):

1. **Bug — audit payload cannot be submitted.** `ANTI_AI_LINE_AUDIT_SCHEMA` (`anti_ai_audit.py:29`) + the coverage gate in `commit_anti_ai_audit` (`facade.py:8058-8107`) require exactly one `line_audit` row per manifest line (458), each with a 71-char `line_text_sha256`, `draft_evidence`, `whole_essay_evidence`, and `line_application`. The result is ~229 KB / ~60-100K tokens. `submit_work_result` (`facade.py:2028`) accepts `payload` as an **inline object only** — there is no file/ref path — so committing needs a single ~100K-token tool emission, which exceeds the model output cap and truncates to invalid JSON. This is the real cause of the original workflow's `[audit]` failure (the "session limit" message masked it).
2. **Bug (downstream) — export deadlock.** `phases.py:350` (`LEGAL_TRANSITIONS[PHASE_ANTI_AI_AUDIT]`) makes `commit_anti_ai_audit` the *only* exit from the `anti_ai_audit` phase. `prepare_validation` is phase-allowed there (`phases.py:254`) but refuses on the `anti_ai_audit_required` content gate; `export_markdown` requires phase `validation`+ (`phases.py:281`) and `allow_failed_validation` only bypasses the *validation-pass* check, not the phase. So an un-committable audit bricks the run with no legal escape. **This bug disappears once Bug 1 is fixed** — no separate phase change is required.
3. **Quality regression the per-line design caused.** The full skill *is* embedded verbatim in the auditor system prompt (`anti_ai_audit.py:170`, 458 lines / ~8K tokens) — it is NOT truncated and is read fine at the input level. But forcing ~450 boilerplate `context` rows spends the auditor's output budget on ceremony (hashing headings and blank lines) instead of reasoning about the prose. The mechanism meant to prove the skill was read actually crowds out the analysis. Per-block rows fix this too.

**Constraint to preserve:** the 2026-05-25 plan added per-line coverage specifically to stop the model skipping the skill and to bind the audit to exact skill + draft bytes. The redesign MUST keep those guarantees: (a) audit bound to exact `skill_sha256` + `draft_sha256`; (b) full block coverage (one row per block, not a self-selected subset); (c) each block row carries `block_sha256`, proving the auditor had the exact block bytes.

**Architecture:** Derive a deterministic *block manifest* from the skill file: split on blank lines into ordered blocks, each with `block_index`, `start_line`, `end_line`, `block_text_sha256`, and `is_structural` (heading / horizontal-rule / frontmatter fence vs. prose guidance). The audit returns one row per block. Rule-bearing (non-structural) blocks carry full `draft_evidence` + `whole_essay_evidence` + `block_application`; structural blocks carry a light `status:"context"` row. Coverage gate: the set of `block_index` values must exactly equal the manifest, and every `block_text_sha256` must match. Drop the 458-line `skill_line_manifest` from the packet body (also shrinks the ~145 KB `prepare_anti_ai_audit` output). Keep `skill_sha256` / `skill_line_count` as top-level bindings.

**Tech Stack:** Python dataclasses, JSON-schema dicts, pytest; existing Agent Tool Mode facade, phase gate, and drafting storage.

**Payload math (target):** ~191 block rows; structural rows (~140) ≈ 90-130 chars each, guidance rows (~50) ≈ 300-450 chars each → ~15-25 KB ≈ 5-8K tokens. Submittable inline with wide margin (~5-6× under the emission wall). Task 1 pins a hard size ceiling so it cannot silently re-bloat.

---

### Task 1: Regression tests (write first, expect failure)

**Files:**
- Modify: `tests/agent_tools/helpers.py` (the full-payload builder)
- Modify: `tests/agent_tools/test_anti_ai_audit_facade.py`
- Modify: `tests/agent_tools/test_require_anti_ai_audit.py`
- Modify: `tests/drafting/test_anti_ai_audit.py`

- [ ] **Step 1: Add a `build_block_audit_payload(draft_content)` helper** in `helpers.py` that uses the new `anti_ai_block_manifest()` to build a valid per-block payload (one row per `block_index`, matching `block_text_sha256`, `skill_sha256`, `skill_line_count`, `draft_sha256`). Keep the old line-audit builder temporarily for red/green diffing, then delete it in Task 6.
- [ ] **Step 2: Add failing tests** asserting:
  - `commit_anti_ai_audit` ACCEPTS a per-block payload whose serialized size is < 40 KB (guards against re-bloat).
  - `commit_anti_ai_audit` REJECTS a payload missing any `block_index` (`anti_ai_block_audit_incomplete`) and one with an extra/unknown block.
  - `commit_anti_ai_audit` REJECTS a `block_text_sha256` that does not match the manifest (`anti_ai_block_audit_hash_mismatch`).
  - `commit_anti_ai_audit` still REJECTS mismatched `skill_sha256` / `draft_sha256`.
  - A failed/blocked block row must appear in `unmet_requirements` and force `pass=false` (port the existing `anti_ai_skill_line_audit_inconsistent` check to blocks).
  - `prepare_anti_ai_audit` output no longer contains the full 458-line manifest (size assertion on the packet).
- [ ] **Step 3: Run and confirm red:** `pytest tests\agent_tools\test_anti_ai_audit_facade.py tests\agent_tools\test_require_anti_ai_audit.py tests\drafting\test_anti_ai_audit.py -q`

### Task 2: Block manifest

**Files:**
- Modify: `essay_writer/drafting/anti_ai_skill.py`

- [ ] **Step 1: `anti_ai_block_manifest()`** — read the raw skill file, split into blank-line-separated blocks preserving order. For each block return `{block_index, start_line, end_line, text, block_text_sha256, is_structural}`. `is_structural` is true for blocks that are only headings (`#`/`##`/…), the `---` frontmatter fences / horizontal rules, or otherwise carry no `**Rule`/guidance sentence. Return `{skill_sha256, skill_line_count, block_count, blocks: [...]}`. Blocks are 1-indexed and contiguous; assert no gaps.
- [ ] **Step 2:** keep `anti_ai_skill_manifest()` (still the source of `skill_sha256` / `skill_line_count` and used elsewhere). `block_text_sha256` uses the same `_sha256_text` helper on the block's exact text (including internal newlines).
- [ ] **Step 3:** add `tests/drafting` unit tests: block count is stable, indices are contiguous 1..N, every `block_text_sha256` reproduces, and concatenating block texts with the blank-line separators round-trips to a superset of the file's non-blank content (catches a split bug).

### Task 3: Audit schema + system prompt

**Files:**
- Modify: `essay_writer/drafting/anti_ai_audit.py`

- [ ] **Step 1: Replace `ANTI_AI_LINE_AUDIT_SCHEMA` with `ANTI_AI_BLOCK_AUDIT_SCHEMA`** — array of objects: `block_index` (int ≥1), `block_text_sha256` (str), `status` (`passed|failed|blocked|not_applicable|context`), `draft_evidence` (array; `minItems 1`, same item shape as today), `finding` (str), `block_application` (block-specific reasoning), and `whole_essay_evidence` (kept, but see Step 2). Rename `line_audit` → `block_audit` in `ANTI_AI_AUDIT_SELF_CHECK_SCHEMA`; replace `skill_line_count`-only wording as needed but KEEP the `skill_line_count` binding field.
- [ ] **Step 2: Keep structural rows light.** In the schema, `whole_essay_evidence` and rich `draft_evidence` are only meaningful for non-`context` rows. Enforce in the commit validator (Task 4), not the JSON schema, so a `context` row can pass with `draft_evidence:[{kind:"not_applicable",…}]` and a short `finding`. This is what keeps the ~140 structural rows cheap.
- [ ] **Step 3: Rewrite `ANTI_AI_AUDIT_SYSTEM_PROMPT`** — drop "one `line_audit` row for every line"; instead: "the user message contains `block_manifest`: every blank-line block of the skill file with its index and `block_text_sha256`. Produce exactly one `block_audit` row per block. Use `status:"context"` for structural blocks (headings, rules, frontmatter). For each guidance block, apply that guidance to the whole draft and give concrete `draft_evidence` + `block_application`. Copy each block's `block_text_sha256` from the manifest." Keep the full skill embedded, the `skill_sha256`/`draft_sha256` binding instructions, and the `pass` criteria.

### Task 4: Facade — prepare + commit

**Files:**
- Modify: `essay_writer/agent_tools/facade.py`

- [ ] **Step 1: `prepare_anti_ai_audit`** (`facade.py:5815`) — build `block_manifest = anti_ai_block_manifest()`. In `user_payload`: add `block_manifest["blocks"]` (index, text, block_text_sha256, is_structural), keep `skill_contract` (`skill_file`/`skill_sha256`/`skill_line_count`), and **remove the full `skill_line_manifest`** (the 458-line array). Keep `deterministic_findings`, `whole_draft_context`, `style_guidance_checklist`.
- [ ] **Step 2: Replace the coverage validator** (`facade.py:8033-8133`) — swap per-line coverage for per-block: `by_block` keyed on `block_index`; require `present_block_indices == manifest_block_indices` (`anti_ai_block_audit_incomplete`, listing missing/extra like today); verify each row's `block_text_sha256` against the manifest (`anti_ai_block_audit_hash_mismatch`). Keep the reasoning-quality, whole-essay, and draft-evidence checks but apply them **only to non-`context` rows** (rename helpers `_anti_ai_block_*`).
- [ ] **Step 3: Port the boilerplate + inconsistency gates** (`facade.py:8134-8212`) to block rows: non-`context` rows must have distinct reasoning (the anti-boilerplate check operating over guidance rows only); failed/blocked blocks must be in `unmet_requirements` and force `pass`/`final_decision` false.
- [ ] **Step 4:** keep the `skill_sha256` / `skill_line_count` / `draft_sha256` binding checks (`facade.py:8011-8031`) as-is.

### Task 5: Persistence + freshness predicate

**Files:**
- Modify: `essay_writer/drafting/schema.py`
- Modify: `essay_writer/drafting/storage.py`
- Modify: `essay_writer/agent_tools/workflow_predicates.py`

- [ ] **Step 1:** rename dataclass `AntiAISkillLineAudit` → `AntiAISkillBlockAudit` (fields: `block_index`, `block_text_sha256`, `status`, `draft_evidence`, `finding`, `block_application`, optional `whole_essay_evidence`); on `AntiAISelfCheck` rename `line_audit` → `block_audit`. Keep `skill_sha256`, `skill_line_count`, `draft_sha256`.
- [ ] **Step 2:** update `storage.py:91-141` to read/write `block_audit`. For backward compatibility, tolerate old persisted drafts that still carry `line_audit` (load into a legacy field or ignore) so existing jobs still deserialize.
- [ ] **Step 3:** `workflow_predicates.is_anti_ai_audit_fresh` (`workflow_predicates.py:24`) — no logic change needed; it keys off `skill_sha256` + `skill_line_count` + `draft_sha256`, all preserved. Add a test that a per-block audit registers as fresh.

### Task 6: Green + full suite + cleanup

- [ ] **Step 1:** delete the legacy line-audit helper from `helpers.py`; grep for stragglers: `grep -rn "line_audit" essay_writer tests` should only return the backward-compat read path in `storage.py`.
- [ ] **Step 2:** run focused: `pytest tests\agent_tools\test_anti_ai_audit_facade.py tests\agent_tools\test_require_anti_ai_audit.py tests\agent_tools\test_anti_ai_hard_tier_gates.py tests\drafting\test_anti_ai_audit.py -q` — all green.
- [ ] **Step 3:** run full suite: `pytest -q`. Fix fallout in `test_style_revision_windowing.py`, `test_outline_draft_validation_tools.py`, and `workflow_predicates` tests.
- [ ] **Step 4:** update docs that describe the per-line audit: `docs/agent-tool-mode-instructions.md`, `docs/agent-harness-implementation.md`, and the harness-instructions string in the facade (the "one `line_audit` row per skill line" wording → "one `block_audit` row per skill block").

### Task 7: Validate end-to-end on the stuck job (proof it un-bricks)

- [ ] **Step 1:** with the fix in place, re-run `prepare_anti_ai_audit` → dispatch Opus subagent → `submit_work_result` → `commit_anti_ai_audit` on `draft_55ddcf148ce1` (job `job-prov-agrun_601c680d781f_...`). Confirm the payload submits inline and the phase advances to `validation`.
- [ ] **Step 2:** `prepare_validation` → `commit_validation` → `export_markdown` (no `allow_failed_validation` needed). Confirm a clean in-tool export, proving the deadlock is gone.

---

## Out of scope / follow-ups

- **Transport-layer payload-by-reference** (a `payload_path`/artifact-ref on `submit_work_result`). Deferred per the chosen direction, but worth adding later as a general backstop so no future large packet can deadlock the pipeline.
- **Explicit audit-failure escape hatch.** Today a legitimately un-passable audit has no ship-anyway path other than `save_user_edit` looping. Consider an `override_anti_ai_audit(reason)` that advances the phase with a recorded, non-silent override.
