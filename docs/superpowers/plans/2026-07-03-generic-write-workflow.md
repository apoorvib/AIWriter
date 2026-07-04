# Generic `/write` Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one persistent `/write` command that can produce emails, text messages, LinkedIn posts, blog posts/articles, and general prose by selecting composable skill files, optionally researching, and adapting its review depth to `immediate` or `detailed` mode.

**Architecture:** Build a new `essay_writer.writing` domain beside the essay pipeline. A single `WritingRun` and a server-derived completion ledger are authoritative; do not add a second mutable phase machine. Claude's Dynamic Workflow asks the ledger for the next action, executes one bounded prepare/submit/commit step, and verifies completion before returning final text, selected skills, assumptions, and researched sources.

**Tech Stack:** Python 3.10+ dataclasses, existing atomic JSON helpers and `AgentWorkStore`, JSON Schema, MCP FastMCP, Claude Code Dynamic Workflows JavaScript, pytest.

---

## Locked product decisions

- One `/write` command handles new and resumed runs.
- Every invocation is persisted. Immediate runs store fewer artifacts; detailed runs store plan, research, review, and revision history.
- Mode precedence is: explicit `immediate`/`detailed` instruction, then model inference. Ask a question only when missing information would materially change the output.
- The anti-AI skill is selected by default and may be explicitly excluded. Format skills override only conflicting soft anti-AI guidance; factual integrity and explicit user constraints always win.
- Initial format skills are `email`, `text-message`, `linkedin`, `blog`, and `general`.
- Research policy is `auto` by default. `/write` may use web search when facts are current, uncertain, consequential, or central to a detailed piece. Users may require or forbid research.
- Research sources are always disclosed in output metadata. Inline citations appear only when the selected format calls for them or the user requests them.
- Immediate path: brief -> optional research -> draft with lightweight self-check -> finalize.
- Detailed path: brief -> optional research -> plan -> draft -> clean-context review -> bounded revision/re-review loop -> finalize.
- The returned response places finished text first, followed by selected skills, assumptions, sources, warnings, and `writing_run_id`.
- A Dynamic Workflow cannot pause. If clarification is required, persist `needs_input`, return the question and run ID, and resume through a later `/write continue <id> <answers>` call.

## State and precedence rules

Use this single precedence order when composing prompts or resolving conflicts:

1. Safety and factual integrity.
2. Explicit user instructions and explicit skill includes/excludes.
3. Requested deliverable format and platform constraints.
4. User voice profile or writing samples.
5. Format-skill hard requirements.
6. Anti-AI hard requirements unless explicitly skipped.
7. Format-skill and anti-AI soft guidance.
8. General-writing defaults.

The server validates selected skill IDs, versions, hashes, explicit exclusions, and required defaults. The model may recommend skills but cannot invent or silently substitute them.

## Persistence layout

```text
${ESSAY_DATA_DIR}/writing/
  runs/{writing_run_id}/run.json
  briefs/{writing_run_id}/brief_vNNN.json
  context/{writing_run_id}/{context_id}/metadata.json
  context/{writing_run_id}/{context_id}/content.txt
  research/{writing_run_id}/research_vNNN.json
  plans/{writing_run_id}/{deliverable_id}/plan_vNNN.json
  drafts/{writing_run_id}/{deliverable_id}/draft_vNNN.json
  reviews/{writing_run_id}/{deliverable_id}/review_vNNN.json
  outputs/{writing_run_id}/output.json
  agent_work/packets/*.json
  agent_work/results/*.json
  agent_work/commits/*.json
  subagent_tokens/*.json
```

One run may contain up to five deliverables so requests such as “turn this launch note into an email and LinkedIn post” share research and context while retaining separate skill stacks and drafts.

## File structure

Create:

- `essay_writer/writing/__init__.py` — public domain exports.
- `essay_writer/writing/schema.py` — persisted dataclasses and enums.
- `essay_writer/writing/storage.py` — atomic stores and version lookup.
- `essay_writer/writing/skills.py` — skill discovery, validation, selection resolution, and prompt composition.
- `essay_writer/writing/context.py` — bounded inline/file context ingestion.
- `essay_writer/writing/prompts.py` — system prompts and response schemas.
- `essay_writer/writing/progress.py` — pure completion-ledger derivation.
- `essay_writer/writing/facade.py` — writing-specific prepare/submit/commit tools.
- `essay_writer/writing/mcp.py` — thin FastMCP registration helper.
- `essay_writer/writing/skills/{general,email,text-message,linkedin,blog}/skill.json` — machine-readable manifests.
- `essay_writer/writing/skills/{general,email,text-message,linkedin,blog}/SKILL.md` — human-editable guidance.
- `.claude/workflows/write.js` — single new/resume Dynamic Workflow.
- `tests/writing_workflow/` — focused domain, facade, MCP, and workflow-contract tests.

Modify:

- `essay_writer/agent_tools/server.py` — register writing tools without growing the essay facade.
- `pyproject.toml` — package skill JSON/Markdown resources.
- `.claude/settings.json` — existing wildcard already covers the new tools; add no broader permission.
- `README.md` and `docs/agent-tool-mode-mcp.md` — document `/write`, modes, persistence, research, and recovery.
- `session-log.md` — record each implementation session.

Do not modify `EssayJob`, essay workflow phases, or `.claude/workflows/essay-*.js` as part of this feature.

---

### Task 1: Define the writing domain schema

**Files:**
- Create: `essay_writer/writing/__init__.py`
- Create: `essay_writer/writing/schema.py`
- Create: `tests/writing_workflow/__init__.py`
- Create: `tests/writing_workflow/test_schema.py`

- [ ] **Step 1: Write failing schema tests**

```python
from dataclasses import asdict
import pytest

from essay_writer.writing.schema import (
    DeliverableSpec, ResearchPolicy, SkillSelection, WriteMode, WritingBrief,
    WritingRun,
)


def test_writing_run_defaults_to_active_auto_mode():
    run = WritingRun(writing_run_id="wrun-1", raw_request="Write a launch email")
    assert run.status == "active"
    assert run.mode_hint is None
    assert run.research_policy == ResearchPolicy.AUTO


def test_brief_supports_multiple_bounded_deliverables():
    brief = WritingBrief(
        brief_id="wbrief-1", writing_run_id="wrun-1", version=1,
        mode=WriteMode.DETAILED, purpose="Announce launch", audience="customers",
        deliverables=[
            DeliverableSpec("d1", "email", "Launch email"),
            DeliverableSpec("d2", "linkedin", "Launch post"),
        ],
        selected_skills=[SkillSelection("anti-ai-detection", "1", "sha256:a")],
    )
    assert len(asdict(brief)["deliverables"]) == 2


def test_brief_rejects_more_than_five_deliverables():
    deliverables = [DeliverableSpec(str(i), "email", "Write email") for i in range(6)]
    with pytest.raises(ValueError, match="at most 5"):
        WritingBrief(
            brief_id="wbrief-1", writing_run_id="wrun-1", version=1,
            mode=WriteMode.IMMEDIATE, purpose="Send updates", audience="customers",
            deliverables=deliverables,
            selected_skills=[SkillSelection("email", "1", "sha256:a")],
        )
```

- [ ] **Step 2: Run the tests and verify the import failure**

Run: `pytest tests\writing_workflow\test_schema.py -q`

Expected: FAIL because `essay_writer.writing.schema` does not exist.

- [ ] **Step 3: Implement the persisted types**

Define string enums `WriteMode(IMMEDIATE, DETAILED)`, `ResearchPolicy(AUTO, REQUIRED, OFF)`, and run statuses `active`, `needs_input`, `blocked`, `complete`, `error`. Add frozen dataclasses:

```python
@dataclass(frozen=True)
class SkillSelection:
    skill_id: str
    version: str
    sha256: str
    reason: str = ""

@dataclass(frozen=True)
class DeliverableSpec:
    deliverable_id: str
    format: str
    objective: str
    audience: str | None = None
    constraints: list[str] = field(default_factory=list)
    selected_skill_ids: list[str] = field(default_factory=list)

@dataclass(frozen=True)
class WritingRun:
    writing_run_id: str
    raw_request: str
    status: str = "active"
    mode_hint: WriteMode | None = None
    research_policy: ResearchPolicy = ResearchPolicy.AUTO
    include_skill_ids: list[str] = field(default_factory=list)
    exclude_skill_ids: list[str] = field(default_factory=list)
    context_ids: list[str] = field(default_factory=list)
    brief_id: str | None = None
    research_id: str | None = None
    output_id: str | None = None
    blocked_on: list[str] = field(default_factory=list)
    revision_rounds: dict[str, int] = field(default_factory=dict)
    created_at: str = field(default_factory=utc_now_iso)
    updated_at: str = field(default_factory=utc_now_iso)
```

Also define `WritingBrief`, `WritingContextItem`, `ResearchSource`, `ResearchFact`, `WritingResearch`, `WritingPlan`, `WritingDraft`, `ReviewIssue`, `WritingReview`, `WritingOutput`, and explicit `from_dict` methods for nested dataclasses. Enforce non-empty IDs, versions >= 1, at most five deliverables, and maximum two automatic revision rounds.

- [ ] **Step 4: Run schema tests**

Run: `pytest tests\writing_workflow\test_schema.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add essay_writer/writing tests/writing_workflow
git commit -m "feat: add generic writing workflow schemas"
```

### Task 2: Add discoverable format skill files

**Files:**
- Create: `essay_writer/writing/skills.py`
- Create: `essay_writer/writing/skills/*/skill.json`
- Create: `essay_writer/writing/skills/*/SKILL.md`
- Modify: `pyproject.toml`
- Test: `tests/writing_workflow/test_skills.py`

- [ ] **Step 1: Write failing registry and precedence tests**

```python
def test_registry_discovers_initial_format_skills_and_anti_ai_adapter():
    registry = WritingSkillRegistry.default()
    assert set(registry.ids()) >= {
        "general", "email", "text-message", "linkedin", "blog",
        "anti-ai-detection",
    }


def test_explicit_exclusion_removes_anti_ai_default():
    selected = resolve_skill_stack(
        registry=WritingSkillRegistry.default(), format_id="email",
        model_selected_ids=["email"], include_ids=[],
        exclude_ids=["anti-ai-detection"],
    )
    assert [item.skill_id for item in selected] == ["email"]


def test_unknown_skill_is_rejected_not_ignored():
    with pytest.raises(UnknownWritingSkillError):
        resolve_skill_stack(
            registry=WritingSkillRegistry.default(), format_id="email",
            model_selected_ids=["email"], include_ids=["invented-skill"],
            exclude_ids=[],
        )
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests\writing_workflow\test_skills.py -q`

Expected: FAIL because the registry does not exist.

- [ ] **Step 3: Create manifests and skill documents**

Each `skill.json` must use this shape:

```json
{
  "id": "email",
  "version": "1",
  "kind": "format",
  "description": "Write purpose-driven email for a named audience.",
  "formats": ["email"],
  "triggers": ["email", "reply", "follow-up", "introduction"],
  "priority": 100
}
```

Each `SKILL.md` must define purpose, required inputs, hard format constraints, soft guidance, research/citation behavior, and a pre-delivery checklist. Keep platform limits explicit: texts are concise and conversational; LinkedIn avoids invented performance claims and uses restrained hashtags; blogs distinguish sourced claims from opinion; email preserves subject/body/CTA semantics; general is the fallback only.

- [ ] **Step 4: Implement deterministic discovery and composition**

`WritingSkillRegistry.default()` loads packaged manifests with `importlib.resources`, validates unique IDs, reads each Markdown file, computes SHA-256, and adds an adapter for the existing root `anti-ai-detection-SKILL.md` without moving it. `resolve_skill_stack()` applies explicit include/exclude overrides, selects the format skill or `general`, adds anti-AI unless excluded, sorts by precedence, and records selection reasons.

- [ ] **Step 5: Package resources**

Add:

```toml
[tool.setuptools.package-data]
"essay_writer.writing" = ["skills/*/skill.json", "skills/*/SKILL.md"]
```

- [ ] **Step 6: Run registry and install-artifact tests**

Run: `pytest tests\writing_workflow\test_skills.py -q`

Expected: PASS, including a test that copies the built package to a temporary import path and still discovers skills.

- [ ] **Step 7: Commit**

```powershell
git add pyproject.toml essay_writer/writing/skills.py essay_writer/writing/skills tests/writing_workflow/test_skills.py
git commit -m "feat: add composable writing skill registry"
```

### Task 3: Implement atomic writing persistence

**Files:**
- Create: `essay_writer/writing/storage.py`
- Test: `tests/writing_workflow/test_storage.py`

- [ ] **Step 1: Write failing persistence tests**

Cover run roundtrip, nested brief roundtrip, next-version behavior, idempotent output save, and isolation between deliverables.

```python
def test_draft_versions_are_isolated_by_deliverable(tmp_path):
    stores = WritingStores.from_data_dir(tmp_path)
    stores.drafts.save(_draft("run1", "email", version=1))
    stores.drafts.save(_draft("run1", "linkedin", version=1))
    assert stores.drafts.next_version("run1", "email") == 2
    assert stores.drafts.load_latest("run1", "linkedin").deliverable_id == "linkedin"
```

- [ ] **Step 2: Run and verify failure**

Run: `pytest tests\writing_workflow\test_storage.py -q`

Expected: FAIL because `WritingStores` does not exist.

- [ ] **Step 3: Implement focused stores**

Create `WritingRunStore`, `WritingBriefStore`, `WritingContextStore`, `WritingResearchStore`, `WritingPlanStore`, `WritingDraftStore`, `WritingReviewStore`, and `WritingOutputStore`. Use `write_json_atomic`; never overwrite a versioned artifact. `WritingRunStore.update()` may replace `run.json` atomically. `WritingOutputStore.save()` is idempotent only when the serialized payload hash matches.

- [ ] **Step 4: Run tests**

Run: `pytest tests\writing_workflow\test_storage.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add essay_writer/writing/storage.py tests/writing_workflow/test_storage.py
git commit -m "feat: persist generic writing runs and artifacts"
```

### Task 4: Add bounded context ingestion

**Files:**
- Create: `essay_writer/writing/context.py`
- Test: `tests/writing_workflow/test_context.py`

- [ ] **Step 1: Write failing tests for inline and file context**

Test UTF-8 text/Markdown, PDF/DOCX through `DocumentReader`, missing files, unsupported suffixes, duplicate hashes, and bounds.

```python
def test_context_rejects_oversized_inline_text(tmp_path):
    stores = WritingStores.from_data_dir(tmp_path)
    service = WritingContextService(stores.context, max_item_chars=100, max_total_chars=200)
    with pytest.raises(WritingContextTooLargeError):
        service.add_inline("run1", "x" * 101, label="brief")
```

- [ ] **Step 2: Implement `WritingContextService`**

Support `.txt`, `.md`, `.markdown`, `.pdf`, and `.docx`. Persist copied originals plus normalized text. Default limits: 10 items, 50,000 characters per item, and 150,000 total characters per run. Reject rather than silently truncate; return a structured instruction to split or summarize oversized context.

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests\writing_workflow\test_context.py -q`

```powershell
git add essay_writer/writing/context.py tests/writing_workflow/test_context.py
git commit -m "feat: add bounded writing context ingestion"
```

### Task 5: Define prompt and response contracts

**Files:**
- Create: `essay_writer/writing/prompts.py`
- Test: `tests/writing_workflow/test_prompts.py`

- [ ] **Step 1: Write failing prompt-contract tests**

Assert that the brief schema requires mode, purpose, audience, deliverables, research decision/reasons, assumptions, blocking questions, and selected skill IDs. Assert the draft prompt embeds exact selected skill documents and hashes but never embeds excluded skills.

- [ ] **Step 2: Implement schemas and prompt builders**

Define `WRITING_BRIEF_SCHEMA`, `WRITING_RESEARCH_SCHEMA`, `WRITING_PLAN_SCHEMA`, `WRITING_DRAFT_SCHEMA`, and `WRITING_REVIEW_SCHEMA`. The brief prompt must enforce:

```text
- Respect explicit immediate/detailed, research, use-skill, and exclude-skill directives.
- Infer only missing fields.
- Ask at most three concise blocking questions.
- A question is blocking only when different plausible answers materially change the output.
- Choose only IDs from available_skills.
- Do not claim research occurred; only decide whether it is needed.
```

The draft prompt must place user constraints before composed skills, separate facts from assumptions, and require a `self_check` for immediate mode. The review prompt must require issue severity (`blocker|major|minor`), exact location, violated skill ID, evidence, and actionable correction.

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests\writing_workflow\test_prompts.py -q`

```powershell
git add essay_writer/writing/prompts.py tests/writing_workflow/test_prompts.py
git commit -m "feat: define generic writing prompt contracts"
```

### Task 6: Implement the single completion ledger

**Files:**
- Create: `essay_writer/writing/progress.py`
- Test: `tests/writing_workflow/test_progress.py`

- [ ] **Step 1: Write table-driven failing tests**

Cover: new run -> brief; blocking brief -> needs input; immediate/no research -> draft; immediate/research -> research; detailed -> plan before draft; detailed draft -> review; blocking review -> revision; two failed revision rounds -> blocked; all deliverables complete -> finalize; output exists -> complete.

```python
@pytest.mark.parametrize((fixture_name, expected), [
    ("new", "brief"),
    ("immediate_ready", "draft"),
    ("detailed_researched", "plan"),
    ("detailed_drafted", "review"),
    ("complete_artifacts", "finalize"),
])
def test_next_required_step(request, fixture_name, expected):
    run, stores = request.getfixturevalue(fixture_name)
    assert build_writing_progress(run, stores)["next_required_step"] == expected
```

- [ ] **Step 2: Implement pure progress derivation**

The ledger reads persisted artifacts only. It returns `status`, per-deliverable steps, `next_required_step`, `next_deliverable_id`, `requires_human`, `all_required_done`, `warnings`, and exact `next_action`. It must never trust mutable `current_phase` or a subagent's report.

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests\writing_workflow\test_progress.py -q`

```powershell
git add essay_writer/writing/progress.py tests/writing_workflow/test_progress.py
git commit -m "feat: add writing completion ledger"
```

### Task 7: Build the writing tool facade and brief/clarification flow

**Files:**
- Create: `essay_writer/writing/facade.py`
- Test: `tests/writing_workflow/test_facade_brief.py`

- [ ] **Step 1: Write failing facade tests**

Test `start_writing_run`, `recover_writing_run`, `prepare_writing_brief`, schema-validated `submit_writing_result`, `commit_writing_brief`, and `answer_writing_questions`. Verify an invented skill ID is rejected, explicit mode/research overrides survive classification, and blocking questions persist `needs_input` without advancing.

- [ ] **Step 2: Implement a writing-specific facade**

Use `AgentWorkStore` with scope `writing:{run_id}`. Reuse `_validate_work_payload` by extracting it from `agent_tools/facade.py` into `agent_tools/schema_validation.py` with parity tests; do not copy the validator. Add a small shared attention-challenge helper so writing packets receive the same proof-of-prompt enforcement.

Expose:

```python
start_writing_run(raw_request, mode=None, research_policy="auto",
                  include_skill_ids=None, exclude_skill_ids=None)
recover_writing_run(writing_run_id)
get_writing_progress(writing_run_id)
prepare_writing_brief(writing_run_id)
submit_writing_result(work_packet_id, payload, producer=None)
commit_writing_brief(work_result_id)
answer_writing_questions(writing_run_id, answers)
```

`answer_writing_questions` appends an immutable context item, increments the brief version, clears `blocked_on`, and makes `brief` the next step.

- [ ] **Step 3: Run old and new validation tests**

Run: `pytest tests\agent_tools\test_attention_challenge.py tests\agent_tools\test_work_store.py tests\writing_workflow\test_facade_brief.py -q`

Expected: PASS with no essay-tool behavior changes.

- [ ] **Step 4: Commit**

```powershell
git add essay_writer/agent_tools/schema_validation.py essay_writer/agent_tools/facade.py essay_writer/writing/facade.py tests
git commit -m "feat: add writing run and brief tools"
```

### Task 8: Add autonomous web research capture

**Files:**
- Modify: `essay_writer/writing/facade.py`
- Test: `tests/writing_workflow/test_research_tools.py`

- [ ] **Step 1: Write failing research tests**

Test research skipped when policy is off, forced when required, auto-decision preservation, URL validation, duplicate source removal, unsupported-claim rejection, source disclosure, date-sensitive facts, and no full-page copyrighted text storage.

- [ ] **Step 2: Implement prepare/commit research tools**

`prepare_writing_research` creates a packet that instructs the harness to use web search and return concise facts with source URL/title/publisher/published/accessed dates and claim mappings. `commit_writing_research` rejects non-HTTP(S) URLs, facts with no source, quotes over 25 words from one source, and results that omit researched-source disclosure metadata.

The MCP server does not perform network calls. Claude's workflow agent owns web search and submits the bounded structured result.

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests\writing_workflow\test_research_tools.py -q`

```powershell
git add essay_writer/writing/facade.py tests/writing_workflow/test_research_tools.py
git commit -m "feat: add optional web research stage for write"
```

### Task 9: Add planning and drafting tools

**Files:**
- Modify: `essay_writer/writing/facade.py`
- Test: `tests/writing_workflow/test_drafting_tools.py`

- [ ] **Step 1: Write failing mode and deliverable tests**

Assert immediate mode never requires a plan, detailed mode does, each deliverable receives its own format skill, all receive anti-AI unless excluded, researched facts carry source refs, assumptions are explicit, and retrying the same result is idempotent.

- [ ] **Step 2: Implement plan and draft prepare/commit pairs**

Add `prepare_writing_plan`, `commit_writing_plan`, `prepare_writing_draft`, and `commit_writing_draft`. Commit validation must enforce the run/deliverable IDs, exact selected-skill manifest, requested format, source IDs for researched claims, and a non-empty immediate `self_check`. Store every draft as a new immutable version.

- [ ] **Step 3: Run tests and commit**

Run: `pytest tests\writing_workflow\test_drafting_tools.py -q`

```powershell
git add essay_writer/writing/facade.py tests/writing_workflow/test_drafting_tools.py
git commit -m "feat: add adaptive writing plan and draft stages"
```

### Task 10: Add independent review, bounded revision, and finalization

**Files:**
- Modify: `essay_writer/writing/facade.py`
- Test: `tests/writing_workflow/test_review_revision.py`

- [ ] **Step 1: Write failing review-loop tests**

Cover clean-context delegation token enforcement, review against every selected skill, blocker vs warning behavior, stale-review detection by draft hash, one successful revision, two-round cap, and force-finalize refusal for unsupported factual claims.

- [ ] **Step 2: Implement detailed review and revision tools**

Add `prepare_writing_review`, `dispatch_writing_reviewer`, `commit_writing_review`, `prepare_writing_revision`, and `commit_writing_revision`. Reuse `SubagentTokenStore`. Bind reviews to exact draft and skill hashes. Require clean-context delegation for detailed reviews; immediate self-checks remain embedded in drafts.

Automatic revision stops after two rounds. Remaining style-only issues become output warnings. Remaining blockers involving facts, explicit requirements, wrong deliverable, or unsafe content set `needs_input` and prevent finalization.

- [ ] **Step 3: Implement deterministic finalization**

`finalize_writing_run` must re-read the ledger, refuse incomplete runs, persist one `WritingOutput`, set run status `complete`, and return:

```json
{
  "writing_run_id": "wrun_20260703_example",
  "deliverables": [{"format": "email", "content": "Subject: Product update\n\nHello Maya, the release is ready for review."}],
  "selected_skills": [{"id": "email", "version": "1", "sha256": "sha256:abc123"}],
  "assumptions": ["Recipient already knows the project"],
  "researched_sources": [{"title": "Primary product documentation", "url": "https://example.com/docs"}],
  "warnings": []
}
```

- [ ] **Step 4: Run tests and commit**

Run: `pytest tests\writing_workflow\test_review_revision.py -q`

```powershell
git add essay_writer/writing/facade.py tests/writing_workflow/test_review_revision.py
git commit -m "feat: add writing review revision and finalization"
```

### Task 11: Register a thin MCP surface

**Files:**
- Create: `essay_writer/writing/mcp.py`
- Modify: `essay_writer/agent_tools/server.py`
- Test: `tests/writing_workflow/test_mcp.py`

- [ ] **Step 1: Write an MCP registration test**

Verify the server exposes the writing tools and still builds without instantiating provider LLM clients.

- [ ] **Step 2: Implement `register_writing_tools(app, facade)`**

Register thin wrappers for all tools from Tasks 7-10 plus `list_writing_runs`, `get_writing_output`, and context ingestion. In `build_server`, instantiate `WritingToolFacade.from_data_dir(data_dir)` and call the registration helper. Keep tool names `start_writing_run`, not ambiguous `start_run`.

- [ ] **Step 3: Run no-hidden-LLM and MCP tests**

Run: `pytest tests\agent_tools\test_mcp_server.py tests\agent_tools\test_no_llm_boundary.py tests\writing_workflow\test_mcp.py -q`

- [ ] **Step 4: Commit**

```powershell
git add essay_writer/writing/mcp.py essay_writer/agent_tools/server.py tests/writing_workflow/test_mcp.py
git commit -m "feat: expose generic write MCP tools"
```

### Task 12: Implement the single `/write` Dynamic Workflow

**Files:**
- Create: `.claude/workflows/write.js`
- Create: `tests/writing_workflow/test_workflow_contract.py`

- [ ] **Step 1: Write static contract tests before the script**

The test must assert the script exists, supports raw-string and structured args, supports `writing_run_id` resume, calls `get_writing_progress`, handles `requires_human`, recognizes every ledger step, uses bounded loops, performs a final ledger assertion, and returns persisted output rather than an unconditional success string.

- [ ] **Step 2: Implement argument normalization**

Support:

```javascript
{
  request: string,
  writing_run_id?: string,
  mode?: 'immediate' | 'detailed',
  research?: 'auto' | 'required' | 'off',
  context_paths?: string[],
  writing_style_paths?: string[],
  include_skills?: string[],
  exclude_skills?: string[]
}
```

Raw text such as `/write detailed LinkedIn post announcing the July launch` is normalized by a parse agent. Explicit values are passed unchanged; the parser must not invent paths or IDs.

- [ ] **Step 3: Implement a ledger-driven loop**

Use a maximum of 30 actions and a per-step retry cap of two. Handle `brief`, `research`, `plan`, `draft`, `review`, `revision`, and `finalize`. On `requires_human`, return the exact questions and run ID. On web-search failure, retry once, then persist a warning and either continue without optional research or block required research.

After the loop, call `get_writing_progress` again. Throw if `all_required_done` is false. Then call `get_writing_output` and format finished text first, followed by skills, assumptions, sources, warnings, and run ID.

- [ ] **Step 4: Run contract tests**

Run: `pytest tests\writing_workflow\test_workflow_contract.py -q`

Expected: PASS.

- [ ] **Step 5: Manually verify representative Claude Code runs**

Run these cases and record run IDs in `session-log.md`:

```text
/write immediate friendly text declining dinner tomorrow
/write detailed LinkedIn post announcing a product launch; research current market context
/write email asking for a deadline extension; skip anti-AI
/write blog comparing two current products, include sources
/write turn this launch note into an email and LinkedIn post
/write continue wrun_<id> audience is existing enterprise customers
```

Expected: correct mode, skill stack, research behavior, persistence, final assertion, and metadata for each case.

- [ ] **Step 6: Commit**

```powershell
git add .claude/workflows/write.js tests/writing_workflow/test_workflow_contract.py session-log.md
git commit -m "feat: add persistent adaptive write workflow"
```

### Task 13: Document the workflow and run full regression verification

**Files:**
- Modify: `README.md`
- Modify: `docs/agent-tool-mode-mcp.md`
- Modify: `docs/agent-tool-mode-instructions.md`
- Modify: `session-log.md`

- [ ] **Step 1: Document user-facing behavior**

Include immediate/detailed examples, automatic clarification, research policy, skill includes/excludes, anti-AI default/skip, persistence path, recovery syntax, output metadata, and the distinction from `/essay-prep`/`/essay-write`.

- [ ] **Step 2: Run focused and regression suites**

```powershell
pytest tests\writing_workflow -q
pytest tests\agent_tools -q
pytest tests\workflow tests\jobs -q
python -m compileall essay_writer tests\writing_workflow
```

Expected: all commands exit 0; existing essay workflows remain backward-compatible.

- [ ] **Step 3: Verify package contents and diff hygiene**

```powershell
python -m build
git diff --check
git status --short
```

Inspect the built wheel and confirm every `skill.json` and `SKILL.md` is present. Do not commit generated `dist/` artifacts.

- [ ] **Step 4: Add the required session log entry and commit**

```powershell
git add README.md docs/agent-tool-mode-mcp.md docs/agent-tool-mode-instructions.md session-log.md
git commit -m "docs: document generic write workflow"
```

---

## Edge-case acceptance matrix

| Case | Required behavior |
| --- | --- |
| No explicit mode | Infer from complexity; do not ask merely to confirm the inference. |
| Explicit mode conflicts with inferred complexity | Explicit mode wins. Detailed facts may still trigger research. |
| Missing recipient/audience | Infer when low-risk; otherwise persist at most three targeted questions. |
| User asks for multiple formats | One run, shared context/research, separate deliverable skills and drafts; maximum five. |
| Format cannot be identified | Select `general`; disclose the assumption. |
| Unknown explicitly requested skill | Block with available IDs; never silently ignore it. |
| Anti-AI excluded | Omit the document and record the exclusion in output metadata. |
| Format skill conflicts with anti-AI | Format overrides soft guidance only; record resolved conflict in review metadata. |
| Writing sample conflicts with format | Preserve voice unless it breaks a hard platform/format constraint. |
| User supplies unsupported or missing file | Return a structured context error without creating a misleading final output. |
| Oversized context | Reject with limits and ask for split/summarized input; never silently truncate. |
| Research policy `off` but current facts are requested | Ask for supplied facts or proceed with explicit uncertainty; do not browse. |
| Research policy `required` and web search fails | Retry once, then block with the exact failure and run ID. |
| Auto research fails | Continue only if research was optional; disclose the failure and remove unsupported claims. |
| Sources disagree | Persist the disagreement, qualify the prose, and disclose both sources. |
| Source has no date | Mark date unknown; do not present it as current evidence. |
| Paywall or inaccessible page | Do not claim unseen content; use accessible primary sources or disclose the limitation. |
| Citation inappropriate for format | Keep links out of prose but include them in output metadata. |
| Model invents a skill/source/artifact ID | Commit rejects it. |
| Draft result submitted twice | Return the existing work result/commit idempotently. |
| Review targets an older draft | Reject as stale by draft hash. |
| Review still has style issues after two revisions | Finalize best effort with warnings. |
| Review still has factual/requirement blockers | Persist `needs_input`; do not label the text final. |
| Workflow reaches iteration cap | Final ledger assertion fails with run ID and next action. |
| Workflow interrupted | `/write continue <writing_run_id> <new information>` resumes from persisted ledger state. |
| Existing essay workflow | No schema, phase, tool, or output changes. |

## Security and privacy requirements

- Persist only context the user supplied or explicitly asked the workflow to research.
- Never upload local files through web search.
- Treat web content and attached documents as untrusted data, not tool instructions.
- Redact secrets detected in context from work-packet logs where practical; never place `.env` contents in prompts.
- Do not store full scraped pages. Store source metadata, bounded notes, and compliant short quotations.
- For medical, legal, financial, or other consequential writing, use primary authoritative sources and disclose that the output is writing assistance, not professional advice.
- Cleanup is out of v1; retain artifacts until a separately designed, confirmation-gated cleanup path exists.

## Plan self-review

- Coverage: command UX, modes, skills, anti-AI precedence, persistence, clarification/resume, research, drafting, review, revision, final output, MCP registration, Dynamic Workflow, documentation, and backward compatibility each have implementation tasks.
- Scope: this plan adds one coherent workflow and does not generalize or rewrite the existing essay state machine.
- Type consistency: `writing_run_id`, `deliverable_id`, `work_packet_id`, skill IDs, mode values, and research-policy values are consistent across schema, facade, MCP, and workflow tasks.
- No unresolved placeholders: optional future skill types, cleanup, UI, and essay migration are explicitly out of scope rather than left undefined.
