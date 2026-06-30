# Anti-AI Audit Enforcement Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the EssayWriter Agent Tool Mode anti-AI stage prove line-level use of `anti-ai-detection-SKILL.md`, bind audits to exact draft text, and prevent stale/manual-edited drafts from validating or exporting.

**Architecture:** Add a deterministic skill manifest with SHA-256 hashes and line hashes, require anti-AI audit JSON to include a line-by-line coverage report, and validate that coverage during `commit_anti_ai_audit`. Treat every user edit as audit-invalidating by clearing inherited self-check metadata and routing the run back to the anti-AI audit phase.

**Tech Stack:** Python dataclasses, JSON schema dictionaries, pytest, existing Agent Tool Mode facade and phase gate.

---

### Task 1: Regression Tests For Stale And Draft-Bound Audits

**Files:**
- Modify: `tests/agent_tools/test_require_anti_ai_audit.py`

- [ ] **Step 1: Add a helper that builds a full line-audit payload**

Use `essay_writer.drafting.anti_ai_skill.anti_ai_skill_manifest()` and `essay_writer.agent_tools.facade.draft_sha256()` to produce an audit payload whose `line_audit` contains one entry per skill line.

- [ ] **Step 2: Add failing tests**

Add tests that assert:
- `save_user_edit` clears `anti_ai_self_check` on the new draft.
- `prepare_validation` rejects a user-edited draft even when the parent draft had a committed audit.
- `commit_anti_ai_audit` rejects missing line coverage.
- `prepare_anti_ai_audit` is allowed after a user edit from export phase.

- [ ] **Step 3: Run the focused tests and confirm they fail**

Run: `pytest tests\agent_tools\test_require_anti_ai_audit.py -q`

Expected before implementation: at least one failure showing the current stale-audit behavior.

### Task 2: Skill Manifest And Audit Schema

**Files:**
- Modify: `essay_writer/drafting/anti_ai_skill.py`
- Modify: `essay_writer/drafting/schema.py`
- Modify: `essay_writer/drafting/storage.py`
- Modify: `essay_writer/drafting/anti_ai_audit.py`

- [ ] **Step 1: Add deterministic skill manifest helpers**

Expose:
- `ANTI_AI_SKILL_PATH`
- `ANTI_AI_SKILL_SHA256`
- `anti_ai_skill_manifest()`
- `draft_sha256(text)`

- [ ] **Step 2: Extend persisted anti-AI self-check dataclasses**

Add optional fields for skill file, skill hash, skill line count, draft hash, line audit rows, unmet requirements, and final decision.

- [ ] **Step 3: Extend anti-AI audit response schema**

Require those fields in `commit_anti_ai_audit` payloads while keeping the regular drafting schema backward-compatible.

### Task 3: Facade Enforcement

**Files:**
- Modify: `essay_writer/agent_tools/facade.py`
- Modify: `essay_writer/agent_tools/phases.py`

- [ ] **Step 1: Include the skill manifest in `prepare_anti_ai_audit`**

The work packet should provide exact file hash, line count, and line hashes so the auditor can fill line-level JSON.

- [ ] **Step 2: Validate line audit coverage in `commit_anti_ai_audit`**

Reject the work result if:
- skill hash does not match the current file
- draft hash does not match the audited draft content
- any line number is missing
- any line hash does not match

- [ ] **Step 3: Make validation/export require a fresh audit for the exact draft**

Validation and export should reject drafts whose `anti_ai_self_check` is missing or whose stored hashes do not match current skill text and draft content.

- [ ] **Step 4: Fix `save_user_edit`**

Clear inherited `anti_ai_self_check`, route next tools to `prepare_anti_ai_audit`, and checkpoint the run into `anti_ai_audit` so post-export edits can be audited.

- [ ] **Step 5: Fix the phase gate**

Allow `save_user_edit` and `prepare_anti_ai_audit` from export/validation states so edited exported drafts can re-enter the audit loop.

### Task 4: Clean Export

**Files:**
- Modify: `essay_writer/exporting/service.py`
- Modify: `tests/agent_tools/test_export_tools.py`

- [ ] **Step 1: Change markdown export content**

Make exported markdown contain only the title and essay prose by default. Keep structured source map data in the export object, not in the submission text.

- [ ] **Step 2: Add/adjust tests**

Assert `## Source Map` and `## Validation` are absent from exported markdown content.

### Task 5: Verification And Session Log

**Files:**
- Modify: `session-log.md`

- [ ] **Step 1: Run focused tests**

Run: `pytest tests\agent_tools\test_require_anti_ai_audit.py tests\agent_tools\test_export_tools.py -q`

- [ ] **Step 2: Run compile check**

Run: `python -m compileall essay_writer tests\agent_tools`

- [ ] **Step 3: Update session log**

Add a concise dated entry listing files changed, tests run, and caveats.
