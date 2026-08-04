# Anti-AI Audit: Per-Rule Redesign (Block → Stable Rule IDs)

> Design spec. Successor to `docs/superpowers/plans/2026-07-01-anti-ai-audit-per-rule-redesign.md`
> (which, despite its filename, delivered the *per-block* audit that ships today).
> This spec takes the next step: from ~138 blank-line **blocks** to ~31 numbered
> **rules**, keyed on stable `R#` IDs, enabled by the consolidated skill draft at
> `anti-ai-detection-SKILL.v2.md`.

## Goal

Replace the *per-block* anti-AI audit (one row per blank-line-separated block of
`anti-ai-detection-SKILL.md`, ~138 rows today, ~140 of them low-value `context`
rows for headings and rules) with a *per-rule* audit: one row per canonical
numbered rule (`R1`…`R31`) in the redesigned skill file. This:

1. **Cuts audit ceremony to near-zero.** Every audit row is now a real,
   applicable prose rule. The ~140 structural `context` rows disappear because
   framing prose (Reality Check, Core Prose Standard) is no longer chopped into
   independently-hashed blocks.
2. **Gives audits, `unmet_requirements`, and `revision_targets` stable
   references.** A block index shifts the moment anyone edits a paragraph above
   it; `R9` stays `R9` across edits. Cross-run diagnostics and revision targeting
   become durable.
3. **Fixes agent comprehension.** ~31 discrete, deduplicated rules with one
   example each replace 339 lines of flowing prose the auditor and drafter must
   hold in attention at once (the [[anti-ai-audit-payload-bug]] motivation).

This is a **content + contract** change: it depends on adopting the consolidated
skill draft as the live `anti-ai-detection-SKILL.md`, which changes the file hash
and the audit-row shape. It cannot be shipped as a prompt-only edit.

## Non-goals

- No change to *when* the audit runs (still after draft assembly / style
  revision, before validation/export).
- No change to the dispatch model (still a blind Opus subagent via
  `dispatch_subagent` in `essay-write.js`).
- The `/write` workflow still treats anti-AI as an inline default quality skill
  (`skills.py:72`) with no per-rule audit; this redesign only touches the
  *essay* audit gate.
- No transport-layer payload-by-reference (still deferred, see the prior plan).

## Current state (what we are replacing)

Verified anchors in the shipping code:

- **Manifest.** `essay_writer/drafting/anti_ai_skill.py`
  - `anti_ai_block_manifest()` splits the raw file on blank lines into ordered
    blocks: `{block_index, start_line, end_line, text, block_text_sha256,
    is_structural}`. `_block_is_structural()` flags heading/`---`-only blocks.
  - `anti_ai_skill_manifest()` still provides `skill_sha256` + `skill_line_count`
    (whole-file bindings) and is used by the commit validator.
  - `ANTI_AI_SKILL_PATH` resolves to repo-root `anti-ai-detection-SKILL.md`;
    `ANTI_AI_SKILL_DOCUMENT` / `ANTI_AI_SKILL_SHA256` are computed at import.
- **Schema + prompt.** `essay_writer/drafting/anti_ai_audit.py`
  - `ANTI_AI_BLOCK_AUDIT_SCHEMA` — array of rows keyed on `block_index` +
    `block_text_sha256`, with `status ∈ {passed,failed,blocked,not_applicable,
    context}`, `draft_evidence[]` (`minItems:1`), `finding`, `block_application`,
    optional `whole_essay_evidence`.
  - `ANTI_AI_AUDIT_SELF_CHECK_SCHEMA` requires `skill_file, skill_sha256,
    skill_line_count, draft_sha256, block_audit, unmet_requirements,
    final_decision`.
  - `ANTI_AI_AUDIT_SYSTEM_PROMPT` embeds the full skill verbatim and instructs
    "exactly one `block_audit` row for every block".
  - `ANTI_AI_AUDIT_SCHEMA` top level: `{pass, anti_ai_self_check,
    revision_targets[]}` (`revision_targets` keyed on 1-indexed `paragraph`).
- **Facade.** `essay_writer/agent_tools/facade.py`
  - `prepare_anti_ai_audit` (~5808): builds `block_manifest`, puts
    `block_manifest["blocks"]` + `deterministic_findings` in the user payload.
  - `commit_anti_ai_audit` (~5979) → `_validate_anti_ai_audit_binding`
    (~7813-8026): checks skill basename, `skill_sha256`, `skill_line_count`,
    `draft_sha256`; requires the set of `block_index` to *exactly* equal the
    manifest (`anti_ai_block_audit_incomplete`); verifies each row's
    `block_text_sha256` (`anti_ai_block_audit_hash_mismatch`); runs
    reasoning / whole-essay / draft-evidence checks on non-`context` rows
    (`_anti_ai_block_reasoning_error` ~7660, `_anti_ai_block_whole_essay_error`
    ~7756, `_anti_ai_block_draft_evidence_error` ~7702); anti-boilerplate
    finding-diversity gate (~7978); failed/blocked rows must be in
    `unmet_requirements` and force `pass`/`final_decision` false (~8008).
- **Persistence + freshness.**
  - `essay_writer/drafting/schema.py`: `AntiAISkillBlockAudit`,
    `AntiAISelfCheck.block_audit`, `unmet_requirements`.
  - `essay_writer/drafting/storage.py:91` reads `block_audit` (tolerant of legacy
    `line_audit`).
  - `is_anti_ai_audit_fresh` (workflow predicates) keys on `skill_sha256` +
    `skill_line_count` + `draft_sha256` — unchanged by this redesign.

## Architecture

### 1. Rule manifest (the one genuinely new mechanism)

Add `anti_ai_rule_manifest()` alongside the block manifest. It parses the skill
file into **rule units** anchored on the canonical marker the redesigned file
introduces:

```
**R<n> — <title>.** <body...>
```

Derivation:

- A rule starts at any line matching `^\*\*R(\d+)\s+[—-]\s` and runs until the
  next such marker, the next `##` section heading, or the next `---` horizontal
  rule, whichever comes first. (The `---` boundary is required: without it the
  last rule before a section separator absorbs the `---` line into its hashed
  text — verified against `v2.md`, where R31 otherwise spanned into the pre-Self-
  Check separator.)
- Emit `{rule_id: "R<n>", ordinal: <n>, title, start_line, end_line, text,
  rule_text_sha256}` per rule, in file order.
- The **Self-Check** section is emitted as one additional unit
  `{rule_id: "self_check", …}` because it prescribes an action the auditor
  performs.
- All other prose (Reality Check, Core Prose Standard, How-to-use, category
  `##` headers) is **framing, not audited** — it is bound by the whole-file
  `skill_sha256` and needs no per-unit row. This is the source of the row-count
  collapse.

Integrity self-tests (mirror the block manifest's "assert no gaps"):

- `rule_id`s are contiguous `R1..RN` with no duplicates or gaps → else raise at
  load (fail loud, same philosophy as today).
- Every non-blank line that is not a heading and not framing falls inside exactly
  one rule span (catches a drift where a rule loses its marker).
- `rule_text_sha256` reproduces via the existing `_sha256_text` helper on the
  rule's exact text.

**Tradeoff acknowledged:** the 2026-07-01 plan deliberately chose blank-line
blocks to *avoid* `**Rule:**` regex parsing ("no drift risk"). Per-rule parsing
reintroduces a marker dependency. The mitigation is that `R#` is now a hard
structural contract of the file (not scattered `**Rule:**` bolds), and the
manifest builder raises on any deviation, so drift is a loud load-time failure,
never a silent miscount.

### 2. Row shape

`ANTI_AI_RULE_AUDIT_SCHEMA` — array of:

```
{ rule_id: "R\d+"|"self_check",
  rule_text_sha256: str,
  status: passed|failed|blocked|not_applicable,   # NOTE: no "context"
  draft_evidence: [ {kind, reference, explanation}, … ],   # minItems 1
  finding: str,
  rule_application: str,                            # was block_application
  whole_essay_evidence: {scope:"whole_essay", paragraph_count_reviewed, method, finding} }
```

Every row is now a guidance row, so `whole_essay_evidence`, `draft_evidence`, and
`rule_application` are required for **all** rows (no `context` carve-out). A rule
that genuinely does not apply to this draft uses `status:"not_applicable"` with a
one-line `finding` explaining why and a `draft_evidence` entry of
`kind:"not_applicable"` — the same escape the block schema already allows, but now
it is a deliberate per-rule judgement instead of ~140 rote heading rows.

`unmet_requirements` rows key on `rule_id` (was `block_index`);
`revision_targets` gains an optional `rule_id` alongside `paragraph` so a fix maps
to the specific rule it satisfies.

### 3. Coverage gate

Structurally identical to today, swapping the key:

- `present_rule_ids == manifest_rule_ids` exactly (`anti_ai_rule_audit_incomplete`,
  listing missing/extra).
- Each row's `rule_text_sha256` matches the manifest
  (`anti_ai_rule_audit_hash_mismatch`).
- Whole-file bindings unchanged: `skill_sha256`, `skill_line_count`,
  `draft_sha256`.
- Reasoning-diversity, whole-essay, and draft-evidence checks apply to every row
  (no `context` skip), renamed `_anti_ai_rule_*`.
- Failed/blocked rule IDs must appear in `unmet_requirements` and force
  `pass`/`final_decision` false — unchanged logic.

### Payload math (target)

~31 rule rows + 1 self-check row ≈ **32 rows**, each ~300-500 chars (all
substantive) → **~12-18 KB ≈ 4-6K tokens**. Comparable to today's ~15-25 KB but
with *zero* wasted ceremony rows, and the auditor spends its whole output budget
on real rule reasoning. Task 1 pins a size ceiling (<30 KB) to prevent re-bloat.

## Risks / migration

- **Adopting the draft skill changes `skill_sha256`.** `ANTI_AI_SKILL_SHA256`
  recomputes at import (safe), but every *stored* audit bound to the old hash goes
  stale and any in-flight draft must be re-audited. Land this together with
  swapping `anti-ai-detection-SKILL.draft.md` → `anti-ai-detection-SKILL.md`.
- **`line_audit` → `block_audit` → `rule_audit` naming.** Keep `storage.py`
  tolerant of both prior field names on read so historical drafts still
  deserialize; only the write path moves to `rule_audit`.
- **Any consumer of `block_index`** (revision targeting, progress surfacing) must
  move to `rule_id`. Grep `block_audit`, `block_index`, `block_text_sha256`
  before deleting.

## Implementation tasks

Test-first, mirroring the per-block plan's task shape.

### Task 0: Adopt the consolidated skill file
- [ ] Replace `anti-ai-detection-SKILL.md` with the content of
      `anti-ai-detection-SKILL.v2.md` (the `R1`–`R31` rule set). Delete the
      candidate file. Confirm `ANTI_AI_SKILL_SHA256` recomputes without error.

### Task 1: Regression tests (write first, expect red)
- [ ] `build_rule_audit_payload(draft_content)` helper in
      `tests/agent_tools/helpers.py` using the new `anti_ai_rule_manifest()`.
- [ ] Tests: commit ACCEPTS a per-rule payload < 30 KB; REJECTS a missing
      `rule_id` (`anti_ai_rule_audit_incomplete`) and an unknown `rule_id`;
      REJECTS a bad `rule_text_sha256` (`anti_ai_rule_audit_hash_mismatch`);
      still REJECTS mismatched `skill_sha256`/`draft_sha256`; a failed/blocked
      rule must be in `unmet_requirements` and force `pass=false`;
      `prepare_anti_ai_audit` packet no longer carries the block manifest.
- [ ] Run and confirm red.

### Task 2: Rule manifest
- [ ] `anti_ai_rule_manifest()` in `anti_ai_skill.py` per the derivation above,
      with the three integrity self-tests raising at load on drift.
- [ ] Keep `anti_ai_skill_manifest()` (whole-file bindings). Retain
      `anti_ai_block_manifest()` only if still referenced elsewhere; otherwise
      remove in Task 6.
- [ ] `tests/drafting`: contiguous `R1..RN`, stable count, hashes reproduce,
      every rule line is covered exactly once.

### Task 3: Audit schema + system prompt
- [ ] Replace `ANTI_AI_BLOCK_AUDIT_SCHEMA` with `ANTI_AI_RULE_AUDIT_SCHEMA`
      (`rule_id`, `rule_text_sha256`, `rule_application`, no `context` status).
      Rename `block_audit` → `rule_audit` in `ANTI_AI_AUDIT_SELF_CHECK_SCHEMA`;
      keep `skill_line_count`.
- [ ] Rewrite `ANTI_AI_AUDIT_SYSTEM_PROMPT`: "the user message contains
      `rule_manifest`: every numbered rule with its `rule_id` and
      `rule_text_sha256`. Produce exactly one `rule_audit` row per rule. Apply
      each rule to the whole draft with concrete `draft_evidence` +
      `rule_application`. Use `not_applicable` only when the rule truly cannot
      apply." Keep the full skill embedded and the `pass` criteria.

### Task 4: Facade prepare + commit
- [ ] `prepare_anti_ai_audit`: attach `rule_manifest["rules"]` (id, text,
      rule_text_sha256), drop the block manifest from the packet, keep
      `deterministic_findings` / `whole_draft_context` / `style_guidance_checklist`.
- [ ] `_validate_anti_ai_audit_binding`: swap per-block coverage for per-rule
      (`present_rule_ids == manifest_rule_ids`, per-row hash), apply
      reasoning/whole-essay/draft-evidence checks to all rows, rename helpers
      `_anti_ai_rule_*`, port the boilerplate + inconsistency gates to `rule_id`.
- [ ] Keep the `skill_sha256`/`skill_line_count`/`draft_sha256` binding block.

### Task 5: Persistence + freshness
- [ ] `schema.py`: `AntiAISkillBlockAudit` → `AntiAISkillRuleAudit`
      (`rule_id`, `rule_text_sha256`, `status`, `draft_evidence`, `finding`,
      `rule_application`, optional `whole_essay_evidence`); `AntiAISelfCheck.
      rule_audit`.
- [ ] `storage.py`: read/write `rule_audit`; tolerate legacy `block_audit` /
      `line_audit` on read.
- [ ] `is_anti_ai_audit_fresh`: no logic change (keys on preserved bindings);
      add a test that a per-rule audit registers fresh.

### Task 6: Green + cleanup
- [ ] Delete legacy helpers; `grep -rn "block_audit\|block_index" essay_writer
      tests` returns only the storage back-compat read path.
- [ ] Focused suite green, then `pytest -q` green.
- [ ] Update `docs/agent-tool-mode-instructions.md`,
      `docs/agent-harness-implementation.md`, and the facade harness-instructions
      string ("one `block_audit` row per skill block" → "one `rule_audit` row per
      numbered rule").

### Task 7: End-to-end proof
- [ ] Run `prepare_anti_ai_audit` → dispatch Opus → `submit_work_result` →
      `commit_anti_ai_audit` on a fresh essay draft; confirm the payload submits
      inline, the ~32-row audit commits, and the phase advances to `validation`
      → `export_markdown`.

## Out of scope / follow-ups

- Renumbering strategy: once `R#` IDs are the audit key, treat them as an append-
  only namespace (deprecate a rule rather than reusing its number) so historical
  `unmet_requirements` stay interpretable. Worth a short CONTRIBUTING note.
- Sharing the rule manifest with the `/write` inline path so short-form writing
  can surface which rules it self-checked (currently no audit there at all).
- The deferred `override_anti_ai_audit(reason)` escape hatch and payload-by-
  reference backstop from the prior plan still stand.
