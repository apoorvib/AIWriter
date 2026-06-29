# Workflow Orchestration Layer — Design

Date: 2026-06-29
Status: Approved (brainstorming complete; implementation plan to follow)

## Problem

The Agent Tool Mode workflow is long (≈39 steps in
`docs/agent-tool-mode-instructions.md`). When a Claude Code harness drives it
turn-by-turn from that prose instruction set, the orchestrating model **skips
steps entirely** — it jumps ahead (e.g. draft → validation without the anti-AI
audit, or never ingests writing style). The existing MCP gates *reject* some
out-of-order calls, but rejection is negative enforcement: it punishes a wrong
call without guaranteeing forward progress through every required step, and it
does not cover steps the agent simply never attempts.

The root cause is that the plan lives in the model's context, where attention
tapers across a long linear sequence.

## Goal

Move the plan out of model context and into **deterministic code** using Claude
Code **Dynamic Workflows**, while keeping the existing MCP server unchanged as
the enforcement + persistence boundary. Guarantee that **every required step is
actually carried out** — verified against persisted server state, not the
subagent's self-report.

## Non-Goals

- Replacing or weakening the MCP server, its gates, or Pipeline Mode. The server
  stays exactly as-is except for **one additive read-only tool** and a
  refactor that extracts existing gate logic into reusable predicates.
- Harness portability. This layer is **Claude Code only** (Dynamic Workflows are
  a Claude Code feature). Codex and other MCP harnesses continue to drive the
  raw MCP tools manually, exactly as today. The MCP server remains portable; only
  the orchestration layer is Claude-specific.
- Bypassing the deliberate human-in-the-loop gates (topic selection, cleanup
  confirmation). These are preserved by segmenting the workflow.

## Key Decisions (from brainstorming)

1. **Observed failure mode:** steps skipped entirely. Fix = deterministic control
   flow so the model no longer decides what runs next.
2. **Portability:** Claude Code only is acceptable. Orchestrator = native Dynamic
   Workflow saved commands.
3. **Human gates:** split into segmented commands. A Dynamic Workflow cannot take
   mid-run user input, and `select_topic` requires `user_selection_evidence`.
4. **"Ensure each step" mechanism:** **Approach B (server completion ledger) as
   the spine, + targeted Approach C (independent verifier) on the two
   highest-stakes steps (anti-AI audit and final validation).**

## Architecture

```
.claude/workflows/essay-prep.js       deterministic control flow ("plan in code")
.claude/workflows/essay-write.js
        │  dispatches one fresh subagent per step (script has NO MCP access)
        ▼
agent() subagents                     the ONLY components that touch MCP
        │  prepare_* → submit_work_result → commit_*   AND   get_workflow_progress
        ▼
essaywriter MCP tools (unchanged) ──▶ domain stores (ground truth)
```

The Dynamic Workflow script holds the loop, branching, and intermediate IDs in
plain script variables. Each step is delegated to a fresh `agent()` subagent;
only the work inside each `agent()` call is model-powered. The orchestrator's
own context never carries the 39-step plan.

Because a Dynamic Workflow script has **no direct MCP/filesystem/shell access**,
every tool call happens inside a subagent. This means a subagent could *claim* a
step succeeded without persisting anything. The completion ledger closes that
loophole: after every step the script re-reads ground truth from the server.

## Component 1 — Server completion ledger (the new core)

### New module: `essay_writer/agent_tools/workflow_progress.py`

Pure functions that, given the agent run and the store bundle, derive which
required steps are done from **persisted state only**.

### New facade method + MCP tool: `get_workflow_progress(agent_run_id)`

Read-only. Added to `READ_ONLY_TOOLS` in `phases.py` (allowed in any phase, no
mutation, no gate). Returns:

```json
{
  "segment": "prep" | "write",
  "job_id": "job-... | null",
  "steps": [
    {
      "step_id": "anti_ai_audit",
      "tier": "required" | "recommended",
      "status": "done" | "pending" | "blocked" | "needs_human",
      "evidence": "draft-... | null",
      "blocked_by": ["draft"],
      "next_action": {
        "tool": "prepare_anti_ai_audit",
        "role": "anti_ai_auditor",
        "model_tier": "frontier",
        "commit_tool": "commit_anti_ai_audit"
      },
      "requires_human": false
    }
  ],
  "next_required_step": "anti_ai_audit | null",
  "all_required_done": false,
  "warnings": ["recommended step 'style_revision' was skipped"]
}
```

### Single-source-of-truth principle

The ledger must read the **same persisted facts the existing gates already
check**, never a parallel truth. The implementation therefore extracts the
boolean cores of current gate functions into reusable predicates that BOTH the
gate and the ledger call:

| Existing gate (facade.py)                       | Extracted predicate                          |
| ----------------------------------------------- | -------------------------------------------- |
| `_anti_ai_audit_freshness_error` (~8169)        | `is_anti_ai_audit_fresh(draft) -> bool`      |
| `_enforce_writing_style_gate` (~341)            | `writing_style_decision_made(job) -> bool`   |
| export `validation_not_passing` gate            | `latest_validation_passing(job) -> bool`     |

The gate functions are refactored to call the predicate and wrap a `False`
result in their existing structured error. No gate behavior changes; the
predicate just becomes shared. Other step statuses come from straightforward
store reads (all `job.source_ids` have a committed source card; task spec
committed; topic selected; research plan exists; evidence map exists; outline
exists; draft exists; export exists).

A step is "done" only when its artifact actually exists in the store. A subagent
that claims it committed but did not leaves its ledger step `pending`, so the
loop re-attempts it instead of advancing. That is what makes "each step actually
carried out" a server-verified invariant.

### Step tiers

- **required** — the loop cannot exit until green. Mirrors the server's own hard
  gates: source cards, writing-style decision, task spec, job, topic selection,
  research plan, source resolution, research notes/evidence map, outline, draft,
  anti-AI audit (fresh for the latest draft), validation (passing), export.
- **recommended** — skippable with a surfaced warning, because a downstream hard
  gate will still enforce the underlying quality. Example: windowed
  style-revision. If skipped, the anti-AI audit gate will likely fail and force a
  revision anyway, so the ledger warns rather than blocks.

### Required-step list

Prep segment (pre/at job creation):
`source_cards`, `writing_style_decision`, `task_spec`, `job_created`, `topics`.

Write segment (post job, starts at the human topic gate):
`topic_selected`, `research_plan`, `source_resolution`, `research_notes`,
`outline`, `draft`, `anti_ai_audit`, `validation`, `export`.

`style_revision` is `recommended` in both the model and the ledger.

## Component 2 — The two segmented workflow scripts

Saved under `.claude/workflows/` (committed to the repo, shared with anyone who
clones). Each is a Dynamic Workflow JS script Claude wrote and we curated.

### Split point

The two segments are divided at the mandatory `select_topic` human gate:

- **`/essay-prep`** — `ingest_source_file` → source cards → writing-style
  ingestion/decision → task spec → `create_job_from_artifacts` → `prepare_topics`
  → `commit_topics`. Ends by **presenting the candidate topics to the user and
  stopping.** Uninterruptable and fully deterministic.
- **`/essay-write`** — begins after the user names a topic in chat. `select_topic`
  (with the user's evidence) → research plan → source resolution → research notes
  → outline → draft → style revision (recommended) → anti-AI audit → validation
  (+ revision loop) → export. Uninterruptable.

Final cleanup (`cleanup_agent_run`) stays a manual, user-initiated step outside
the workflow, per the existing instructions.

### Workflow args

- `/essay-prep` accepts `{ source_paths: [...], writing_style_paths: [...] | "skip",
  assignment_text | assignment_path }` via the `args` global.
- `/essay-write` accepts `{ agent_run_id, job_id, round_number, topic_id,
  user_selection_evidence }` — the topic choice the user made between segments.

### The driver loop (the "never skip" mechanism)

Both scripts share one pattern:

```
1. (setup subagent) start_agent_run / recover_agent_run; get_harness_instructions
   → capture agent_run_id.
2. loop:
     a. (read subagent) call get_workflow_progress(agent_run_id)
        → next_required_step, all_required_done.
     b. if all_required_done for this segment → break.
     c. if step.requires_human → stop the workflow and surface the prompt
        (segment boundary).
     d. dispatch the step subagent for next_required_step (see Component 3).
     e. go to (a)  ← re-reads ground truth; never trusts the subagent's claim.
3. report the final segment summary.
```

The loop exits only when the **server** says every required step for the segment
is done. The script cannot skip a step because it never chooses the next step
itself — it asks the ledger.

## Component 3 — Per-step subagent contract

Each `agent()` step subagent receives:

- The exact MCP call sequence for its `step_id`: `prepare_X(...)` → produce JSON
  matching the returned `response_schema` → `submit_work_result(...)` →
  `commit_X(...)`, threading `agent_run_id` and prior artifact IDs.
- A hard instruction to use the packet's `system_prompt` **verbatim** (the
  existing attention-challenge token already enforces this at
  `submit_work_result`).
- A **return contract**: `{ ok, step_id, artifact_id, work_result_id, error_code,
  notes }`. The script logs this but does **not** treat it as proof of
  completion — proof comes from the next `get_workflow_progress` read.

### Granularity

- **Source cards:** fan out — one subagent per source, in parallel (runtime cap
  16). Large packets already set `delegation_required=True`.
- **Most stages:** one subagent each.
- **Anti-AI audit (special):** the `prepare_anti_ai_audit` packet is
  `delegation_required=True`, `required_model_tier="frontier"`, and
  `submit_work_result` requires `producer.type == "subagent"` carrying a
  `subagent_token`. The workflow handles this in two `agent()` calls:
  1. a setup subagent calls `prepare_anti_ai_audit` then
     `dispatch_subagent(work_packet_id, role="anti_ai_auditor",
     model_tier="opus")` and returns `{ work_packet_id, subagent_token }`;
  2. a **fresh, clean-context auditor subagent on a frontier model (Opus)**
     reads the packet via `get_work_packet`, produces the audit JSON,
     `submit_work_result` with `producer.type="subagent"` +
     `subagent_token`, then `commit_anti_ai_audit`.
  The script holds `work_packet_id` + `subagent_token` in variables between the
  two calls. This preserves the clean-context guarantee the audit depends on.

## Component 4 — Targeted independent verification (Approach C)

Applied to the two highest-stakes steps only; the server's hard gates already
validate shape elsewhere, so C focuses on substantive pass/fail and driving the
revision loop:

- **After `commit_anti_ai_audit`:** a read-only verifier subagent reads the draft
  (`get_draft`) and confirms `anti_ai_self_check` is populated and reports
  `audit_pass`. If `audit_pass == false`, the script routes to
  `prepare_revision(selected_lenses=["anti_ai"], user_instruction=<revision_targets>)`
  → commit, then loops back to the audit step. The ledger keeps `anti_ai_audit`
  `pending` until a fresh audit with `audit_pass == true` exists for the latest
  draft.
- **After `commit_validation`:** a read-only verifier confirms validation passed.
  On failure the script runs `prepare_revision` → `commit_revision` and loops
  back to validation. `export` stays `pending` in the ledger until
  `latest_validation_passing(job)` is true (matching the existing export gate).

These mirror the existing "review lens" philosophy without doubling cost on
steps the commit gates already validate hard.

## Error handling, idempotency, recovery

- **Per-step retry:** the driver retries a failed step up to 2 times. On a gate
  error it self-heals deterministically:
  - `harness_stale` / `harness_never_read` → dispatch a subagent that calls
    `get_harness_instructions(agent_run_id)`, then retry.
  - `out_of_order` → re-read `get_workflow_progress` and dispatch the real next
    step (the ledger is authoritative).
- **Hard blockers** (e.g. `insufficient_evidence_upload_more_sources`,
  `blocked_on` set) → abort the workflow and surface the exact blocker to the
  user, since a workflow cannot take mid-run input.
- **Idempotency:** existing commit idempotency (`already_committed`, content
  hashes, `work_result_id` dedup) plus the ledger make re-runs safe — a re-run
  resumes because already-done steps read as `done` and are skipped.
- **Recovery:** the workflow always begins with `recover_agent_run` /
  `get_workflow_progress`, so an interrupted segment (or a fresh session) resumes
  from the first undone required step rather than restarting.

## File-level change summary

New:
- `essay_writer/agent_tools/workflow_progress.py` — step model + ledger derivation.
- `.claude/workflows/essay-prep.js`, `.claude/workflows/essay-write.js`.
- Tests: `tests/agent_tools/test_workflow_progress.py`,
  `tests/agent_tools/test_workflow_progress_gates_parity.py`.

Changed:
- `essay_writer/agent_tools/facade.py` — add `get_workflow_progress`; extract
  `is_anti_ai_audit_fresh`, `writing_style_decision_made`,
  `latest_validation_passing` predicates and call them from both the existing
  gates and the ledger.
- `essay_writer/agent_tools/server.py` — register `get_workflow_progress` tool.
- `essay_writer/agent_tools/phases.py` — add `get_workflow_progress` to
  `READ_ONLY_TOOLS`.
- `docs/agent-tool-mode-instructions.md` — short note pointing Claude Code users
  at the `/essay-prep` and `/essay-write` workflows.
- `.mcp.json` / docs — ensure `mcp__essaywriter__*` tools are pre-allowlisted so
  background-running workflow subagents are not blocked by mid-run permission
  prompts.

## Testing

- **Ledger derivation:** for a run/job at each stage, `get_workflow_progress`
  reports the correct `next_required_step`, `status` per step, and
  `all_required_done`.
- **Gate-parity:** property test that each extracted predicate agrees with its
  original gate — when the predicate is `False`, the corresponding gate returns
  its structured error; when `True`, the gate passes. This guards against the
  ledger and the gates drifting apart.
- **Anti-skip:** simulate a subagent that returns `ok:true` but did not commit;
  assert the ledger keeps the step `pending` and the loop would re-dispatch
  (not advance).
- **Audit dispatch:** the two-call audit pattern (prepare+dispatch, then frontier
  auditor) round-trips and `commit_anti_ai_audit` succeeds; a non-subagent
  producer is rejected (existing gate).
- **Recommended-skip:** skipping `style_revision` yields a warning but does not
  block `all_required_done`, while a machine-flavored draft still fails the audit
  gate and forces a revision.
- **Resume:** running a segment twice is idempotent; the second run reports the
  segment already complete.
- The `.js` workflow scripts are validated manually via `/essay-prep` and
  `/essay-write` on a sample assignment (Dynamic Workflow scripts are not unit
  tested in CI).

## Open questions (resolve during planning)

1. Exact `recommended` set beyond `style_revision` (e.g. is `source_resolution`
   required when the topic needs no extra sources?). Lean: derive from the
   research plan — required only if the plan emitted unresolved source requests.
2. Retry count (default 2) and whether to make it a workflow arg.
3. Whether `get_workflow_progress` should also return a compact human-readable
   `summary` string for the final report, or leave formatting to the script.
