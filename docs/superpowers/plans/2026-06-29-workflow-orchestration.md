# Workflow Orchestration Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a server-computed completion ledger (`get_workflow_progress`) and two Claude Code Dynamic Workflow scripts that drive the existing Agent Tool Mode MCP tools so every required workflow step is verifiably carried out.

**Architecture:** Two `.claude/workflows/*.js` scripts hold the plan as deterministic control flow and dispatch one fresh subagent per step. Subagents are the only components that call MCP tools. After every step the script re-reads `get_workflow_progress(agent_run_id)`, which derives required-step completion purely from persisted store state — so a skipped or faked step leaves its ledger entry `pending` and the loop re-attempts it. The MCP server is unchanged except for one additive read-only tool and a refactor that extracts existing gate logic into shared predicates.

**Tech Stack:** Python 3 (dataclasses, pytest), Claude Code Dynamic Workflows (JavaScript), FastMCP.

## Global Constraints

- Agent Tool Mode no-hidden-API rule: code in `essay_writer/agent_tools/` must not import `llm.factory`, `llm.logging_client`, provider adapters, or `backend.deps`. The ledger is read-only over stores; it makes no model calls.
- `get_workflow_progress` is **read-only**: it must not mutate any store, run, packet, or job. It is added to `READ_ONLY_TOOLS` and bypasses the phase/stale gates.
- Single-source-of-truth: the ledger must decide "step done" from the **same persisted facts the existing gates check**, via shared predicates — never a parallel truth.
- Orchestration layer is **Claude Code only**. The MCP server stays harness-agnostic; Codex continues to drive raw tools.
- Follow existing facade conventions: tools return `ToolResult` (`ok`, `tool_name`, `mode="agent_tool_no_api"`, `data`, `error`, `warnings`, `next_suggested_tools`); errors via `_error_result` / `_error_result_with_next`.
- Tests live under `tests/agent_tools/` and run with `pytest`. The broad suite builds the facade with enforcement flags off via conftest; new tests follow existing patterns there.

---

### Task 1: Shared workflow predicates module

Extract the boolean cores the gates and the ledger will share. New module so both `facade.py` gates and `workflow_progress.py` import without a cycle.

**Files:**
- Create: `essay_writer/agent_tools/workflow_predicates.py`
- Test: `tests/agent_tools/test_workflow_predicates.py`

**Interfaces:**
- Consumes: `essay_writer.drafting.anti_ai_skill.anti_ai_skill_manifest`, `draft_sha256`; `EssayDraft`, `EssayJob`, `ValidationStore` (duck-typed).
- Produces:
  - `is_anti_ai_audit_fresh(draft) -> bool`
  - `writing_style_decision_made(job) -> bool`
  - `latest_validation_passing(validation_store, job) -> bool`

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_tools/test_workflow_predicates.py
from dataclasses import replace

from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    latest_validation_passing,
    writing_style_decision_made,
)
from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256
from essay_writer.drafting.schema import AntiAISelfCheck, EssayDraft


def _draft(content="Body paragraph one.\n\nBody paragraph two.", audit=None):
    return EssayDraft(
        id="draft-1", job_id="job-1", version=1,
        selected_topic_id="topic-1", content=content, anti_ai_self_check=audit,
    )


def test_audit_missing_is_not_fresh():
    assert is_anti_ai_audit_fresh(_draft(audit=None)) is False


def test_audit_matching_hashes_is_fresh():
    manifest = anti_ai_skill_manifest()
    content = "Body paragraph one.\n\nBody paragraph two."
    audit = AntiAISelfCheck(
        skill_sha256=str(manifest["sha256"]),
        skill_line_count=int(manifest["line_count"]),
        draft_sha256=draft_sha256(content),
    )
    assert is_anti_ai_audit_fresh(_draft(content=content, audit=audit)) is True


def test_audit_stale_draft_hash_is_not_fresh():
    manifest = anti_ai_skill_manifest()
    audit = AntiAISelfCheck(
        skill_sha256=str(manifest["sha256"]),
        skill_line_count=int(manifest["line_count"]),
        draft_sha256="sha256:deadbeef",
    )
    assert is_anti_ai_audit_fresh(_draft(audit=audit)) is False


def test_writing_style_decision_made_variants():
    class J:
        writing_style_content_id = None
        writing_style_skip_token = None
    assert writing_style_decision_made(J()) is False
    J.writing_style_content_id = "wsc-1"
    assert writing_style_decision_made(J()) is True
    J.writing_style_content_id = None
    J.writing_style_skip_token = "tok-1"
    assert writing_style_decision_made(J()) is True


class _StubValStore:
    def __init__(self, report):
        self._report = report
    def load_latest(self, job_id):
        if self._report is None:
            raise KeyError(job_id)
        return self._report


class _Job:
    id = "job-1"
    draft_id = "draft-1"


def test_validation_passing_true_when_passes_and_matches_draft():
    report = type("R", (), {"passes": True, "draft_id": "draft-1"})()
    assert latest_validation_passing(_StubValStore(report), _Job()) is True


def test_validation_passing_false_when_no_report():
    assert latest_validation_passing(_StubValStore(None), _Job()) is False


def test_validation_passing_false_when_draft_mismatch():
    report = type("R", (), {"passes": True, "draft_id": "other"})()
    assert latest_validation_passing(_StubValStore(report), _Job()) is False
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_tools/test_workflow_predicates.py -v`
Expected: FAIL with `ModuleNotFoundError: essay_writer.agent_tools.workflow_predicates`

- [ ] **Step 3: Write the module**

```python
# essay_writer/agent_tools/workflow_predicates.py
from __future__ import annotations

from essay_writer.drafting.anti_ai_skill import anti_ai_skill_manifest, draft_sha256


def is_anti_ai_audit_fresh(draft: object) -> bool:
    """True iff the draft carries a committed anti-AI audit whose skill and
    draft hashes match the current skill file and the exact draft text.

    Mirrors the cheap hash checks in facade `_anti_ai_audit_freshness_error`.
    The deeper binding validation stays in that gate; the ledger uses this
    predicate as the canonical "is the audit fresh for this draft" signal.
    """
    audit = getattr(draft, "anti_ai_self_check", None)
    if audit is None:
        return False
    skill_hash = getattr(audit, "skill_sha256", "")
    draft_hash = getattr(audit, "draft_sha256", "")
    if not skill_hash or not draft_hash:
        return False
    manifest = anti_ai_skill_manifest()
    if skill_hash != str(manifest["sha256"]):
        return False
    if int(getattr(audit, "skill_line_count", 0) or 0) != int(manifest["line_count"]):
        return False
    if draft_hash != draft_sha256(str(getattr(draft, "content", ""))):
        return False
    return True


def writing_style_decision_made(job: object) -> bool:
    """True iff the job has attached writing-style content OR recorded a skip
    token (the two outcomes the writing-style gate accepts)."""
    return bool(getattr(job, "writing_style_content_id", None)) or bool(
        getattr(job, "writing_style_skip_token", None)
    )


def latest_validation_passing(validation_store: object, job: object) -> bool:
    """True iff the job's latest validation report passes and is bound to the
    job's latest committed draft (matches the export gate's check)."""
    job_id = getattr(job, "id", None)
    if not job_id:
        return False
    try:
        report = validation_store.load_latest(job_id)
    except (KeyError, FileNotFoundError):
        return False
    return bool(getattr(report, "passes", False)) and getattr(
        report, "draft_id", None
    ) == getattr(job, "draft_id", None)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_tools/test_workflow_predicates.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add essay_writer/agent_tools/workflow_predicates.py tests/agent_tools/test_workflow_predicates.py
git commit -m "feat(agent_tools): add shared workflow predicates"
```

---

### Task 2: Route existing gates through the shared predicates

Make the three existing gates call the predicates so the ledger and the gates can never disagree. Behavior must not change.

**Files:**
- Modify: `essay_writer/agent_tools/facade.py` — `_enforce_writing_style_gate` (idempotent-retry branch), `_anti_ai_audit_freshness_error`, `export_markdown` validation-pass branch.
- Test: `tests/agent_tools/test_workflow_progress_gates_parity.py`

**Interfaces:**
- Consumes: predicates from Task 1.
- Produces: no new public symbols; gates now delegate their boolean decision.

- [ ] **Step 1: Write the failing parity test**

```python
# tests/agent_tools/test_workflow_progress_gates_parity.py
from essay_writer.agent_tools.workflow_predicates import is_anti_ai_audit_fresh
from essay_writer.agent_tools.facade import _anti_ai_audit_freshness_error
from essay_writer.drafting.schema import EssayDraft


def _draft(audit=None):
    return EssayDraft(
        id="draft-1", job_id="job-1", version=1,
        selected_topic_id="topic-1", content="Para one.\n\nPara two.",
        anti_ai_self_check=audit,
    )


def test_gate_errors_exactly_when_predicate_false_for_missing_audit():
    draft = _draft(audit=None)
    predicate_fresh = is_anti_ai_audit_fresh(draft)
    gate_error = _anti_ai_audit_freshness_error("prepare_validation", draft=draft)
    # When the predicate says "not fresh", the gate must raise its structured error.
    assert predicate_fresh is False
    assert gate_error is not None
    assert gate_error.error.code in {"anti_ai_audit_required", "anti_ai_audit_stale"}
```

- [ ] **Step 2: Run test to verify current behavior (it should already pass for missing-audit, then guard the refactor)**

Run: `pytest tests/agent_tools/test_workflow_progress_gates_parity.py -v`
Expected: PASS now (this test pins the invariant before the refactor; keep it green through Step 3-4).

- [ ] **Step 3: Refactor the gates to use the predicates**

In `facade.py`, add the import near the other agent_tools imports (around line 29):

```python
from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    latest_validation_passing,
    writing_style_decision_made,
)
```

In `_enforce_writing_style_gate`, replace the idempotent-retry content/skip checks (the two `getattr(existing, ...)` branches) with:

```python
            if existing is not None and writing_style_decision_made(existing):
                return None
```

In `_anti_ai_audit_freshness_error`, after the `audit is None` and empty-hash branches, replace the manual hash comparison block with a single predicate call that drives the `anti_ai_audit_stale` decision (keep the existing `anti_ai_audit_required` branches above it unchanged):

```python
    if not is_anti_ai_audit_fresh(draft):
        return _error_result_with_next(
            tool_name,
            code="anti_ai_audit_stale",
            message=(
                "The selected draft's anti-AI audit is stale. The audit must "
                "match the current anti-ai-detection-SKILL.md hash and the exact "
                "draft text hash."
            ),
            exc=ValueError("anti_ai_audit_stale"),
            next_suggested_tools=["prepare_anti_ai_audit"],
        )
    return _validate_anti_ai_audit_binding(
        {"anti_ai_self_check": asdict(audit)},
        source_draft=draft,
        tool_name=tool_name,
    )
```

In `export_markdown`, replace `if not validation.passes and not allow_failed_validation:` with a predicate-based check that preserves the exact override semantics:

```python
        if not allow_failed_validation and not latest_validation_passing(
            self.stores.validation_store, job
        ):
```

(The `job` object already has `draft_id` set to the committed draft, and the gate above already verified `validation.draft_id == draft.id`, so this is equivalent.)

- [ ] **Step 4: Run the full gate suites to confirm no behavior change**

Run: `pytest tests/agent_tools/test_workflow_progress_gates_parity.py tests/agent_tools/test_require_anti_ai_audit.py tests/agent_tools/test_writing_style_gate.py tests/agent_tools/test_export_tools.py -v`
Expected: PASS (all existing gate tests still green)

- [ ] **Step 5: Commit**

```bash
git add essay_writer/agent_tools/facade.py tests/agent_tools/test_workflow_progress_gates_parity.py
git commit -m "refactor(agent_tools): route gates through shared workflow predicates"
```

---

### Task 3: Workflow-progress step model and derivation

The ledger core: a step model plus a pure builder that derives status from the run, the job, and the stores.

**Files:**
- Create: `essay_writer/agent_tools/workflow_progress.py`
- Test: `tests/agent_tools/test_workflow_progress.py`

**Interfaces:**
- Consumes: `AgentRun` (`job_id`); `AgentStoreBundle` (`job_store`/`workflow`, `source_store`, `task_store`, `research_plan_store`, `research_store`, `outline_store`, `draft_store`, `validation_store`, `export_store`); predicates from Task 1.
- Produces:
  - `@dataclass WorkflowStep(step_id, tier, status, evidence, blocked_by, next_action, requires_human)`
  - `build_workflow_progress(run, stores) -> dict` with keys `segment, job_id, steps, next_required_step, all_required_done, warnings`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/agent_tools/test_workflow_progress.py
from essay_writer.agent_tools.schemas import AgentRun
from essay_writer.agent_tools.workflow_progress import build_workflow_progress


def test_no_job_reports_prep_segment_first_step(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    assert progress["segment"] == "prep"
    assert progress["all_required_done"] is False
    assert progress["next_required_step"] == "source_cards"
    step_ids = [s["step_id"] for s in progress["steps"]]
    assert "task_spec" in step_ids and "job_created" in step_ids


def test_step_status_is_pending_when_artifact_absent(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    stores = AgentStoreBundle.from_data_dir(tmp_path)
    run = AgentRun(agent_run_id="run-1", objective="x", job_id=None)
    progress = build_workflow_progress(run, stores)
    by_id = {s["step_id"]: s for s in progress["steps"]}
    assert by_id["task_spec"]["status"] == "pending"
    assert by_id["topics"]["blocked_by"]  # blocked by earlier prep steps
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_tools/test_workflow_progress.py -v`
Expected: FAIL with `ModuleNotFoundError: essay_writer.agent_tools.workflow_progress`

- [ ] **Step 3: Write the module**

```python
# essay_writer/agent_tools/workflow_progress.py
from __future__ import annotations

from dataclasses import asdict, dataclass, field

from essay_writer.agent_tools.workflow_predicates import (
    is_anti_ai_audit_fresh,
    latest_validation_passing,
    writing_style_decision_made,
)


@dataclass(frozen=True)
class WorkflowStep:
    step_id: str
    tier: str  # "required" | "recommended"
    status: str  # "done" | "pending" | "blocked" | "needs_human"
    next_action: dict
    requires_human: bool = False
    evidence: str | None = None
    blocked_by: list[str] = field(default_factory=list)


# Ordered step specs per segment. `done(ctx)` returns the evidence id (truthy)
# when the step is complete, else None. `requires_human`/`tier` are static.
def _prep_specs():
    return [
        ("source_cards", "required", False,
         {"tool": "prepare_source_card", "role": "source_card_writer",
          "commit_tool": "commit_source_card"},
         lambda c: c["source_cards_done"]),
        ("writing_style_decision", "required", False,
         {"tool": "ingest_writing_style_sample / skip_writing_style_calibration"},
         lambda c: "decided" if c["job"] is not None
                   and writing_style_decision_made(c["job"]) else None),
        ("task_spec", "required", False,
         {"tool": "prepare_task_spec", "commit_tool": "commit_task_spec"},
         lambda c: c["task_spec_id"]),
        ("job_created", "required", False,
         {"tool": "create_job_from_artifacts"},
         lambda c: c["job"].id if c["job"] is not None else None),
        ("topics", "required", False,
         {"tool": "prepare_topics", "commit_tool": "commit_topics"},
         lambda c: c["job"].topic_round_ids[-1]
                   if c["job"] is not None and c["job"].topic_round_ids else None),
    ]


def _write_specs():
    return [
        ("topic_selected", "required", True,
         {"tool": "select_topic"},
         lambda c: c["job"].selected_topic_id if c["job"] is not None else None),
        ("research_plan", "required", False,
         {"tool": "create_research_plan"},
         lambda c: c["job"].research_plan_id if c["job"] is not None else None),
        ("research_notes", "required", False,
         {"tool": "prepare_research_notes", "commit_tool": "commit_research_notes"},
         lambda c: c["job"].evidence_map_id if c["job"] is not None else None),
        ("outline", "required", False,
         {"tool": "prepare_outline", "commit_tool": "commit_outline"},
         lambda c: c["job"].outline_id if c["job"] is not None else None),
        ("draft", "required", False,
         {"tool": "prepare_draft", "commit_tool": "commit_draft"},
         lambda c: c["job"].draft_id if c["job"] is not None else None),
        ("style_revision", "recommended", False,
         {"tool": "prepare_style_revision", "commit_tool": "commit_style_revision"},
         lambda c: "revised" if c["draft"] is not None
                   and getattr(c["draft"], "origin", "") in
                   {"style_revision"} else None),
        ("anti_ai_audit", "required", False,
         {"tool": "prepare_anti_ai_audit", "role": "anti_ai_auditor",
          "model_tier": "frontier", "commit_tool": "commit_anti_ai_audit"},
         lambda c: c["draft"].id if c["draft"] is not None
                   and is_anti_ai_audit_fresh(c["draft"]) else None),
        ("validation", "required", False,
         {"tool": "prepare_validation", "commit_tool": "commit_validation"},
         lambda c: c["job"].validation_report_id if c["job"] is not None
                   and latest_validation_passing(c["validation_store"], c["job"])
                   else None),
        ("export", "required", False,
         {"tool": "export_markdown"},
         lambda c: c["job"].final_export_id if c["job"] is not None else None),
    ]


def _load_job(run, stores):
    if not run.job_id:
        return None
    try:
        return stores.workflow.load_job(run.job_id)
    except (KeyError, FileNotFoundError):
        return None


def _load_latest_draft(stores, job):
    if job is None or not getattr(job, "draft_id", None):
        return None
    try:
        return stores.draft_store.load_latest(job.id)
    except (KeyError, FileNotFoundError):
        return None


def _source_cards_done(stores, job):
    if job is None or not job.source_ids:
        return None
    if all(stores.source_store.has_source_card(sid) for sid in job.source_ids):
        return "all_source_cards"
    return None


def build_workflow_progress(run, stores) -> dict:
    job = _load_job(run, stores)
    draft = _load_latest_draft(stores, job)
    ctx = {
        "job": job,
        "draft": draft,
        "validation_store": stores.validation_store,
        "task_spec_id": getattr(job, "task_spec_id", None) if job else None,
        "source_cards_done": _source_cards_done(stores, job),
    }

    # The job_created step is the prep/write boundary marker, but the segment is
    # chosen by whether a topic has been selected: once a topic is committed the
    # run is in the write segment.
    in_write = bool(job is not None and job.selected_topic_id)
    specs = _write_specs() if in_write else _prep_specs()
    segment = "write" if in_write else "prep"

    steps: list[WorkflowStep] = []
    prior_required_pending: list[str] = []
    warnings: list[str] = []
    next_required_step = None
    all_required_done = True

    for step_id, tier, requires_human, next_action, done_fn in specs:
        evidence = done_fn(ctx)
        is_done = bool(evidence)
        if is_done:
            status = "done"
        elif prior_required_pending:
            status = "blocked"
        elif requires_human:
            status = "needs_human"
        else:
            status = "pending"
        steps.append(WorkflowStep(
            step_id=step_id, tier=tier, status=status,
            next_action=next_action, requires_human=requires_human,
            evidence=evidence if is_done else None,
            blocked_by=list(prior_required_pending),
        ))
        if tier == "required" and not is_done:
            all_required_done = False
            if next_required_step is None and not requires_human:
                next_required_step = step_id
            prior_required_pending.append(step_id)
        if tier == "recommended" and not is_done:
            warnings.append(f"recommended step '{step_id}' not done")

    return {
        "segment": segment,
        "job_id": run.job_id,
        "steps": [asdict(s) for s in steps],
        "next_required_step": next_required_step,
        "all_required_done": all_required_done,
        "warnings": warnings,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_tools/test_workflow_progress.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add essay_writer/agent_tools/workflow_progress.py tests/agent_tools/test_workflow_progress.py
git commit -m "feat(agent_tools): add workflow-progress completion ledger"
```

---

### Task 4: Anti-skip regression test (the core guarantee)

Prove that a "committed but artifact absent" situation keeps the step `pending`, so the driver loop would re-attempt rather than advance.

**Files:**
- Test: `tests/agent_tools/test_workflow_progress.py` (append)

**Interfaces:**
- Consumes: `build_workflow_progress`, `AgentStoreBundle`, the real draft/job stores.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/agent_tools/test_workflow_progress.py
def test_draft_present_but_audit_absent_keeps_audit_pending(tmp_path):
    from essay_writer.agent_tools.stores import AgentStoreBundle
    from essay_writer.agent_tools.schemas import AgentRun
    from essay_writer.drafting.schema import EssayDraft

    stores = AgentStoreBundle.from_data_dir(tmp_path)
    job = stores.workflow.create_job(task_spec_id="ts-1", source_ids=["src-1"])
    # Move the job into the write segment with a selected topic + a committed draft,
    # but no anti-AI audit on the draft.
    job = stores.job_store.load(job.id)
    draft = EssayDraft(id="draft-1", job_id=job.id, version=1,
                       selected_topic_id="topic-1", content="A.\n\nB.")
    stores.draft_store.save(draft)
    stores.job_store.save(__import__("dataclasses").replace(
        job, selected_topic_id="topic-1", draft_id="draft-1"))

    run = AgentRun(agent_run_id="run-1", objective="x", job_id=job.id)
    progress = build_workflow_progress(run, stores)
    by_id = {s["step_id"]: s for s in progress["steps"]}
    assert progress["segment"] == "write"
    assert by_id["anti_ai_audit"]["status"] == "pending"
    assert progress["next_required_step"] == "anti_ai_audit"
    assert progress["all_required_done"] is False
```

- [ ] **Step 2: Run test to verify it fails or reveals store API mismatches**

Run: `pytest tests/agent_tools/test_workflow_progress.py::test_draft_present_but_audit_absent_keeps_audit_pending -v`
Expected: FAIL initially; adjust the store calls (`create_job`/`save`/`load`) to the real `EssayWorkflow`/`DraftStore`/`EssayJobStore` signatures discovered while wiring (check `essay_writer/jobs/workflow.py` and `essay_writer/drafting/storage.py`). Do not change `workflow_progress.py` logic to pass — only fix the test's store setup.

- [ ] **Step 3: Make the test green by correcting store-setup calls**

Use the actual constructor/methods from `EssayWorkflow` and `DraftStore`. The assertion block (segment/status/next_required_step) must remain unchanged.

- [ ] **Step 4: Run the test**

Run: `pytest tests/agent_tools/test_workflow_progress.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add tests/agent_tools/test_workflow_progress.py
git commit -m "test(agent_tools): ledger keeps step pending when artifact absent"
```

---

### Task 5: Facade `get_workflow_progress` method

Wrap the ledger in a facade method returning a `ToolResult`.

**Files:**
- Modify: `essay_writer/agent_tools/facade.py` (add method on `AgentToolFacade`, near the other read-only methods such as `get_agent_run_state`)
- Test: `tests/agent_tools/test_workflow_progress_facade.py`

**Interfaces:**
- Consumes: `build_workflow_progress` (Task 3); `self.run_store.load_run`.
- Produces: `AgentToolFacade.get_workflow_progress(self, *, agent_run_id: str) -> ToolResult`.

- [ ] **Step 1: Write the failing test**

```python
# tests/agent_tools/test_workflow_progress_facade.py
from essay_writer.agent_tools.facade import AgentToolFacade


def test_get_workflow_progress_returns_ledger(tmp_path):
    facade = AgentToolFacade.from_data_dir(
        tmp_path, enforce_attention_challenge=False,
        require_agent_run=False, require_anti_ai_audit=False,
    )
    start = facade.start_agent_run(objective="essay")
    run_id = start.data["agent_run_id"]
    result = facade.get_workflow_progress(agent_run_id=run_id)
    assert result.ok is True
    assert result.tool_name == "get_workflow_progress"
    assert result.data["segment"] == "prep"
    assert result.data["next_required_step"] == "source_cards"


def test_get_workflow_progress_missing_run(tmp_path):
    facade = AgentToolFacade.from_data_dir(tmp_path)
    result = facade.get_workflow_progress(agent_run_id="nope")
    assert result.ok is False
    assert result.error.code == "missing_run"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/agent_tools/test_workflow_progress_facade.py -v`
Expected: FAIL with `AttributeError: 'AgentToolFacade' object has no attribute 'get_workflow_progress'`

- [ ] **Step 3: Add the method and import**

Add import near the top of `facade.py` (with the other agent_tools imports):

```python
from essay_writer.agent_tools.workflow_progress import build_workflow_progress
```

Add the method on `AgentToolFacade` (e.g. right after `get_agent_run_state`):

```python
    def get_workflow_progress(self, *, agent_run_id: str) -> ToolResult:
        """Read-only completion ledger derived from persisted store state.

        Returns which required workflow steps are done and the first undone
        required step. Drives Dynamic Workflow orchestration: the script loops
        on next_required_step until all_required_done. No mutation, no gate.
        """
        try:
            run = self.run_store.load_run(agent_run_id)
        except (KeyError, FileNotFoundError) as exc:
            return _missing_run_result("get_workflow_progress", agent_run_id, exc)
        progress = build_workflow_progress(run, self.stores)
        next_step = progress["next_required_step"]
        next_tools = []
        if next_step is not None:
            for step in progress["steps"]:
                if step["step_id"] == next_step:
                    tool = step["next_action"].get("tool")
                    if tool:
                        next_tools = [tool.split(" ")[0]]
                    break
        return ToolResult(
            ok=True,
            tool_name="get_workflow_progress",
            data={**progress, "must_remember": list(MUST_REMEMBER)},
            warnings=list(progress["warnings"]),
            next_suggested_tools=next_tools,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/agent_tools/test_workflow_progress_facade.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add essay_writer/agent_tools/facade.py tests/agent_tools/test_workflow_progress_facade.py
git commit -m "feat(agent_tools): add get_workflow_progress facade method"
```

---

### Task 6: Register the MCP tool and mark it read-only

Expose the method over MCP and ensure the phase gate treats it as read-only.

**Files:**
- Modify: `essay_writer/agent_tools/server.py` (add `@app.tool()` wrapper)
- Modify: `essay_writer/agent_tools/phases.py` (add to `READ_ONLY_TOOLS`)
- Modify: `essay_writer/agent_tools/facade.py` (`CURRENTLY_CALLABLE_TOOLS` list)
- Test: `tests/agent_tools/test_workflow_progress_facade.py` (append a phase-gate test)

**Interfaces:**
- Consumes: `facade.get_workflow_progress`.
- Produces: MCP tool `get_workflow_progress(agent_run_id)`.

- [ ] **Step 1: Write the failing test**

```python
# append to tests/agent_tools/test_workflow_progress_facade.py
from essay_writer.agent_tools.phases import READ_ONLY_TOOLS


def test_get_workflow_progress_is_read_only():
    assert "get_workflow_progress" in READ_ONLY_TOOLS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/agent_tools/test_workflow_progress_facade.py::test_get_workflow_progress_is_read_only -v`
Expected: FAIL (`get_workflow_progress` not in `READ_ONLY_TOOLS`)

- [ ] **Step 3: Make the edits**

In `phases.py`, add `"get_workflow_progress",` to the `READ_ONLY_TOOLS` frozenset.

In `facade.py`, add `"get_workflow_progress",` to the `CURRENTLY_CALLABLE_TOOLS` list (near the other read tools).

In `server.py`, add the wrapper alongside the other read tools (e.g. after `get_agent_run_state`):

```python
    @app.tool()
    def get_workflow_progress(agent_run_id: str) -> dict[str, object]:
        """Read-only completion ledger: which required workflow steps are done,
        and the first undone required step. Drives Dynamic Workflow loops."""
        return result(facade.get_workflow_progress(agent_run_id=agent_run_id))
```

- [ ] **Step 4: Run the test and the broad agent-tools suite**

Run: `pytest tests/agent_tools/test_workflow_progress_facade.py tests/agent_tools/test_phases.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add essay_writer/agent_tools/server.py essay_writer/agent_tools/phases.py essay_writer/agent_tools/facade.py tests/agent_tools/test_workflow_progress_facade.py
git commit -m "feat(agent_tools): register get_workflow_progress MCP tool"
```

---

### Task 7: Author the `/essay-prep` Dynamic Workflow script

A curated Dynamic Workflow script (not CI unit-tested; verified manually). Drives the prep segment to the topic gate.

**Files:**
- Create: `.claude/workflows/essay-prep.js`

**Interfaces:**
- Consumes: MCP tools `start_agent_run`, `get_harness_instructions`, `get_workflow_progress`, `ingest_source_file`, `prepare_source_card`/`commit_source_card`, writing-style tools, `prepare_task_spec`/`commit_task_spec`, `create_job_from_artifacts`, `prepare_topics`/`commit_topics`.
- Produces: a saved `/essay-prep` command.

- [ ] **Step 1: Write the script**

Create `.claude/workflows/essay-prep.js` implementing the driver loop. Use the project's Dynamic Workflow `agent()` API. Skeleton (adapt `agent()` call shape to the runtime's actual signature when authoring via `ultracode`):

```javascript
// /essay-prep — drives Agent Tool Mode prep segment to the topic gate.
// args: { source_paths: string[], writing_style_paths: string[] | "skip",
//         assignment_text?: string, assignment_path?: string }
const a = args || {};

// 1. Start the run and read harness instructions (one setup subagent).
const setup = await agent({
  prompt: `Call start_agent_run(objective="Essay prep"). Then call
get_harness_instructions(agent_run_id=<the new id>). Return JSON
{ "agent_run_id": "<id>" } and nothing else.`,
  tools: ["mcp__essaywriter__start_agent_run",
          "mcp__essaywriter__get_harness_instructions"],
});
const runId = JSON.parse(setup.result).agent_run_id;

// 2. Ingest sources + writing style + assignment via one ingestion subagent.
await agent({
  prompt: `Using agent_run_id="${runId}":
- For each path in ${JSON.stringify(a.source_paths || [])} call
  ingest_source_file(document_path=path, agent_run_id="${runId}").
- Writing style: ${a.writing_style_paths === "skip"
    ? `call skip_writing_style_calibration after the job exists (handled later); for now do nothing.`
    : `for each path in ${JSON.stringify(a.writing_style_paths || [])} call
       ingest_writing_style_sample(path, agent_run_id="${runId}").`}
Return JSON { "ok": true }.`,
  tools: ["mcp__essaywriter__ingest_source_file",
          "mcp__essaywriter__ingest_writing_style_sample"],
});

// 3. Driver loop: ask the ledger for the next required step, do exactly that.
let guard = 0;
while (guard++ < 40) {
  const progressRaw = await agent({
    prompt: `Call get_workflow_progress(agent_run_id="${runId}") and return its
JSON data verbatim.`,
    tools: ["mcp__essaywriter__get_workflow_progress"],
  });
  const progress = JSON.parse(progressRaw.result);
  if (progress.segment !== "prep" || progress.all_required_done) break;
  const step = progress.next_required_step;
  if (!step) break; // only human/blocked steps remain
  await runPrepStep(runId, step, a);
}

// 4. Present topics and stop (human gate).
const topics = await agent({
  prompt: `Call get_job_summary for the job on run "${runId}" and list the
committed candidate topics with their ids for the user to choose. Return a
readable summary.`,
  tools: ["mcp__essaywriter__get_agent_run_state",
          "mcp__essaywriter__get_job_summary"],
});
return `Prep complete. Choose a topic, then run /essay-write.\n\n${topics.result}`;

async function runPrepStep(runId, step, a) {
  // One subagent per step. Each prepares, produces JSON using the packet's
  // system_prompt verbatim, submits, and commits, threading agent_run_id.
  return agent({
    prompt: `You are executing ONE workflow step: "${step}" for
agent_run_id="${runId}". Follow the Agent Tool Mode prepare→submit→commit cycle:
call the step's prepare_* tool, generate JSON matching the returned
response_schema USING THE PACKET'S system_prompt VERBATIM (copy the ATTENTION
CHECK token into a notes field), call submit_work_result, then the named
commit_* tool. For source cards, do every uncarded source. For the
writing-style decision, either commit writing-style content and
attach_writing_style_to_job, or call skip_writing_style_calibration and pass the
token to create_job_from_artifacts. Return JSON
{ ok, step_id, artifact_id, work_result_id, error_code }.`,
    tools: ["mcp__essaywriter__prepare_source_card",
            "mcp__essaywriter__commit_source_card",
            "mcp__essaywriter__prepare_writing_style_content",
            "mcp__essaywriter__commit_writing_style_content",
            "mcp__essaywriter__attach_writing_style_to_job",
            "mcp__essaywriter__skip_writing_style_calibration",
            "mcp__essaywriter__prepare_task_spec",
            "mcp__essaywriter__commit_task_spec",
            "mcp__essaywriter__create_job_from_artifacts",
            "mcp__essaywriter__prepare_topics",
            "mcp__essaywriter__commit_topics",
            "mcp__essaywriter__submit_work_result",
            "mcp__essaywriter__get_work_packet"],
  });
}
```

- [ ] **Step 2: Verify the script loads as a command**

Run (manual): in Claude Code, `/essay-prep` appears in `/` autocomplete after the file is saved. Confirm `mcp__essaywriter__*` tools are allowlisted (Task 9) so background subagents are not blocked.

- [ ] **Step 3: Commit**

```bash
git add .claude/workflows/essay-prep.js
git commit -m "feat(workflows): add /essay-prep dynamic workflow"
```

---

### Task 8: Author the `/essay-write` Dynamic Workflow script

Drives the write segment from the user's topic choice through export, with the anti-AI audit two-call dispatch and targeted verification on audit + validation.

**Files:**
- Create: `.claude/workflows/essay-write.js`

**Interfaces:**
- Consumes: `recover_agent_run`, `get_harness_instructions`, `get_workflow_progress`, `select_topic`, `create_research_plan`, `resolve_source_requests`, research/outline/draft/style-revision tools, `prepare_anti_ai_audit` + `dispatch_subagent` + `commit_anti_ai_audit`, `prepare_revision`/`commit_revision`, `prepare_validation`/`commit_validation`, `get_draft`, `export_markdown`.
- Produces: a saved `/essay-write` command.

- [ ] **Step 1: Write the script**

Create `.claude/workflows/essay-write.js`. Key differences from `/essay-prep`: it begins by recovering the run and committing the user's topic choice, then loops the write segment, with special handling for the audit step and verifier-driven revision loops.

```javascript
// /essay-write — drives Agent Tool Mode write segment to export.
// args: { agent_run_id, job_id, round_number, topic_id, user_selection_evidence }
const a = args || {};
const runId = a.agent_run_id;

await agent({
  prompt: `Call recover_agent_run(agent_run_id="${runId}") then
get_harness_instructions(agent_run_id="${runId}"). Return { ok: true }.`,
  tools: ["mcp__essaywriter__recover_agent_run",
          "mcp__essaywriter__get_harness_instructions"],
});

// Commit the human topic choice (the gate that forced segmentation).
await agent({
  prompt: `Call select_topic(job_id="${a.job_id}", round_number=${a.round_number},
topic_id="${a.topic_id}", user_selection_evidence=${JSON.stringify(a.user_selection_evidence)},
agent_run_id="${runId}"). Return { ok: true }.`,
  tools: ["mcp__essaywriter__select_topic"],
});

let guard = 0;
while (guard++ < 60) {
  const progress = JSON.parse((await agent({
    prompt: `Call get_workflow_progress(agent_run_id="${runId}") and return data verbatim.`,
    tools: ["mcp__essaywriter__get_workflow_progress"],
  })).result);
  if (progress.all_required_done) break;
  const step = progress.next_required_step;
  if (!step) break;

  if (step === "anti_ai_audit") {
    await runAuditStep(runId, a.job_id);
  } else {
    await runWriteStep(runId, step);
  }

  // Targeted verification (Approach C) after audit and validation.
  if (step === "anti_ai_audit") await verifyAuditOrRevise(runId, a.job_id);
  if (step === "validation") await verifyValidationOrRevise(runId, a.job_id);
}

return `Write segment complete. Export ready. Review, then optionally run cleanup.`;

async function runWriteStep(runId, step) {
  return agent({
    prompt: `Execute ONE workflow step "${step}" for agent_run_id="${runId}"
via prepare→submit→commit, using the packet's system_prompt VERBATIM and copying
the ATTENTION CHECK token into a notes field. For research_plan call
create_research_plan then resolve_source_requests. Return
{ ok, step_id, artifact_id, work_result_id, error_code }.`,
    tools: ["mcp__essaywriter__create_research_plan",
            "mcp__essaywriter__resolve_source_requests",
            "mcp__essaywriter__prepare_research_notes",
            "mcp__essaywriter__commit_research_notes",
            "mcp__essaywriter__prepare_outline",
            "mcp__essaywriter__commit_outline",
            "mcp__essaywriter__prepare_draft",
            "mcp__essaywriter__commit_draft",
            "mcp__essaywriter__prepare_style_revision",
            "mcp__essaywriter__prepare_style_revision_window",
            "mcp__essaywriter__commit_style_revision",
            "mcp__essaywriter__prepare_validation",
            "mcp__essaywriter__commit_validation",
            "mcp__essaywriter__export_markdown",
            "mcp__essaywriter__submit_work_result",
            "mcp__essaywriter__get_work_packet"],
  });
}

// The audit is delegation_required + frontier. Two calls: setup mints the token,
// then a fresh frontier auditor consumes it.
async function runAuditStep(runId, jobId) {
  const setup = JSON.parse((await agent({
    prompt: `Call prepare_anti_ai_audit(job_id="${jobId}", agent_run_id="${runId}").
Then call dispatch_subagent(work_packet_id=<that packet id>, role="anti_ai_auditor",
model_tier="opus", agent_run_id="${runId}"). Return JSON
{ work_packet_id, subagent_token }.`,
    tools: ["mcp__essaywriter__prepare_anti_ai_audit",
            "mcp__essaywriter__dispatch_subagent"],
  })).result);

  await agent({
    model: "opus",
    prompt: `You are a clean-context anti-AI auditor. Call
get_work_packet(work_packet_id="${setup.work_packet_id}"). Apply ONLY the
anti-AI skill in the packet's system_prompt. Produce the audit JSON matching the
response_schema (every line_audit row, copy the ATTENTION CHECK token). Call
submit_work_result(work_packet_id="${setup.work_packet_id}", payload=<audit>,
producer={ type:"subagent", role:"anti_ai_auditor",
subagent_token:"${setup.subagent_token}" }, agent_run_id="${runId}"). Then
commit_anti_ai_audit(work_result_id=<id>, agent_run_id="${runId}"). Return
{ ok, audit_pass }.`,
    tools: ["mcp__essaywriter__get_work_packet",
            "mcp__essaywriter__submit_work_result",
            "mcp__essaywriter__commit_anti_ai_audit"],
  });
}

async function verifyAuditOrRevise(runId, jobId) {
  const v = JSON.parse((await agent({
    prompt: `Read-only verifier. Call get_draft(job_id="${jobId}"). Confirm
anti_ai_self_check is populated and report final_decision. Return
{ audit_pass: <bool>, revision_targets: [...] }.`,
    tools: ["mcp__essaywriter__get_draft"],
  })).result);
  if (v.audit_pass === false && (v.revision_targets || []).length) {
    await agent({
      prompt: `Run an anti-AI revision: prepare_revision(job_id="${jobId}",
selected_lenses=["anti_ai"], user_instruction=${JSON.stringify(v.revision_targets.join("; "))},
agent_run_id="${runId}"), submit_work_result, commit_revision. Use the packet's
system_prompt verbatim. Return { ok: true }.`,
      tools: ["mcp__essaywriter__prepare_revision",
              "mcp__essaywriter__commit_revision",
              "mcp__essaywriter__submit_work_result",
              "mcp__essaywriter__get_work_packet"],
    });
  }
}

async function verifyValidationOrRevise(runId, jobId) {
  const v = JSON.parse((await agent({
    prompt: `Read-only verifier. Call get_workflow_progress(agent_run_id="${runId}").
If the "validation" step is not done, return { passing: false }, else
{ passing: true }.`,
    tools: ["mcp__essaywriter__get_workflow_progress"],
  })).result);
  if (v.passing === false) {
    await agent({
      prompt: `Validation did not pass. Run prepare_revision(job_id="${jobId}",
agent_run_id="${runId}") scoped to the failing diagnostics, submit_work_result,
commit_revision, then prepare_validation→submit→commit_validation again. Use each
packet's system_prompt verbatim. Return { ok: true }.`,
      tools: ["mcp__essaywriter__prepare_revision",
              "mcp__essaywriter__commit_revision",
              "mcp__essaywriter__prepare_validation",
              "mcp__essaywriter__commit_validation",
              "mcp__essaywriter__submit_work_result",
              "mcp__essaywriter__get_work_packet"],
    });
  }
}
```

- [ ] **Step 2: Verify the script loads as a command**

Run (manual): confirm `/essay-write` appears in `/` autocomplete and that the audit subagent uses a frontier model (`model: "opus"`).

- [ ] **Step 3: Commit**

```bash
git add .claude/workflows/essay-write.js
git commit -m "feat(workflows): add /essay-write dynamic workflow"
```

---

### Task 9: Allowlist MCP tools and update docs

Pre-allowlist the MCP tools so background workflow subagents are not blocked by mid-run permission prompts, and document the two workflows.

**Files:**
- Modify: `.mcp.json` (or `.claude/settings.json` permissions) — allowlist `mcp__essaywriter__*`
- Modify: `docs/agent-tool-mode-instructions.md` — add a short "Claude Code: /essay-prep and /essay-write" note
- Modify: `docs/agent-tool-mode-mcp.md` — document the two workflows and `get_workflow_progress`

- [ ] **Step 1: Add the allowlist entry**

In `.claude/settings.json` (create the `permissions.allow` array if absent), add:

```json
{
  "permissions": {
    "allow": ["mcp__essaywriter__*"]
  }
}
```

- [ ] **Step 2: Document the workflows**

Append to `docs/agent-tool-mode-mcp.md`:

```markdown
## Claude Code Dynamic Workflows

Two saved workflows drive the MCP tools deterministically so no required step is
skipped:

- `/essay-prep` — ingest → source cards → writing style → task spec → job →
  topics, then stops for you to choose a topic.
- `/essay-write` — `select_topic` (your choice) → research → outline → draft →
  anti-AI audit → validation → export.

Both loop on `get_workflow_progress(agent_run_id)`, a read-only completion ledger
that reports which required steps are done from persisted state. The loop exits
only when the server reports `all_required_done`.
```

- [ ] **Step 3: Commit**

```bash
git add .claude/settings.json docs/agent-tool-mode-instructions.md docs/agent-tool-mode-mcp.md
git commit -m "docs(workflows): document /essay-prep and /essay-write and allowlist MCP tools"
```

---

### Task 10: Full-suite regression

Confirm the whole agent-tools suite is green after all changes.

**Files:** none (verification only)

- [ ] **Step 1: Run the full agent-tools suite**

Run: `pytest tests/agent_tools -q`
Expected: PASS (all existing + new tests)

- [ ] **Step 2: Run the workflow-progress and parity tests specifically**

Run: `pytest tests/agent_tools/test_workflow_progress.py tests/agent_tools/test_workflow_predicates.py tests/agent_tools/test_workflow_progress_facade.py tests/agent_tools/test_workflow_progress_gates_parity.py -v`
Expected: PASS

- [ ] **Step 3: Commit any test fixups**

```bash
git add -A
git commit -m "test(agent_tools): green full suite for workflow orchestration"
```

---

## Self-Review

**Spec coverage:**
- Server completion ledger → Tasks 3, 5, 6.
- Reuse gate predicates (single source of truth) → Tasks 1, 2 + parity test.
- Step tiers (required/recommended) → Task 3 (`tier` field; `style_revision` recommended).
- Two segmented workflow scripts split at topic gate → Tasks 7, 8.
- Per-step subagent contract + return contract → Tasks 7, 8 (`runPrepStep`/`runWriteStep`).
- Anti-AI audit two-call dispatch (delegation_required + frontier) → Task 8 (`runAuditStep`).
- Targeted verification on audit + validation → Task 8 (`verifyAuditOrRevise`, `verifyValidationOrRevise`).
- Anti-skip guarantee (ledger keeps step pending) → Task 4.
- Error handling / recovery / idempotency → Task 8 loop guards + `recover_agent_run`; ledger-driven resume is inherent (already-done steps read `done`).
- Allowlist for background subagents → Task 9.
- Docs → Task 9.

**Placeholder scan:** Task 4 Step 2/3 intentionally defer exact store-setup signatures to the implementer with a clear instruction to read `essay_writer/jobs/workflow.py` and `essay_writer/drafting/storage.py`; this is store-API discovery, not a logic placeholder. The `.js` `agent()` call shape is adapted to the runtime when authored via `ultracode` (Dynamic Workflow scripts are authored, not hand-written from scratch); the orchestration logic is fully specified.

**Type consistency:** `build_workflow_progress(run, stores) -> dict` keys (`segment`, `job_id`, `steps`, `next_required_step`, `all_required_done`, `warnings`) are consumed identically in Task 5 and the `.js` loops. Predicate signatures (`is_anti_ai_audit_fresh(draft)`, `writing_style_decision_made(job)`, `latest_validation_passing(validation_store, job)`) match between Task 1 definitions and Task 2/3 call sites.

## Open Questions (carry from spec; resolve during execution)

1. Exact `recommended` set beyond `style_revision` — e.g. make `source_resolution` required only when the research plan emitted unresolved source requests (derive in `_write_specs`).
2. Retry count per step (currently the loop guard caps total iterations; per-step retry can be added in the `.js` if a step's ledger entry stays `pending` after one attempt).
3. Whether `get_workflow_progress` should also emit a human-readable `summary` string for the final report.
