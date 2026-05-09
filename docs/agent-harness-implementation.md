# Agent Harness MCP Implementation Plan

## Purpose

Add an Agent Tool Mode that lets Claude Code, Codex, and other MCP-capable
harnesses drive the essay-writing system through local tools.

The current orchestrator should remain intact as Pipeline Mode. Agent Tool Mode
does not replace it. It exposes the same artifact stores and lower-level
services through a non-linear, harness-friendly interface.

The main reason for this mode is cost and flexibility:

- Pipeline Mode can continue to call configured LLM APIs.
- Agent Tool Mode should use the harness model for reasoning, so local MCP tools
  must not make hidden LLM API calls.
- The app should still own source artifacts, job state, validation, lineage, and
  export formats.

## Core Design Rule

MCP tools in Agent Tool Mode must not implicitly call the app LLM client.

Any step that needs model reasoning should be split into:

```text
prepare_*  -> app gathers bounded context, instructions, schema, artifact refs
agent      -> Claude Code / Codex generates structured output with its own model
commit_*   -> app validates, normalizes, persists, and updates workflow state
```

The harness owns reasoning. The app owns artifacts.

## Modes

### Pipeline Mode

Pipeline Mode is the existing behavior.

```text
frontend/API
  -> EssayWorkflow / MvpWorkflowRunner
  -> configured app LLM client
  -> persisted artifacts
```

This mode is useful for users who want one button to run the whole workflow and
are comfortable configuring provider API keys.

### Agent Tool Mode

Agent Tool Mode is the new behavior.

```text
Claude Code / Codex / MCP client
  -> local EssayWriter MCP tools
  -> deterministic app services and stores
  -> prepare packets returned to the harness
  -> commit tools persist harness-produced JSON
```

This mode is useful for local open-source usage where the user already has an
agent subscription and wants more control over the writing process.

## Source Ingestion

Source ingestion needs special handling because the current web ingestion path
does more than deterministic extraction. Today `SourceIngestionService.ingest`
extracts text, chunks/indexes the source, builds a source map, and then creates
a `SourceCard` through an LLM-backed source-card prompt.

Calling that service unchanged from MCP would violate the no-hidden-API rule.

Agent Tool Mode should split source ingestion into deterministic source
materialization plus harness-owned source-card generation.

### Recommended Agent Ingestion Flow

```text
1. ingest_source_file(path)
   -> deterministic extraction, OCR fallback if local OCR is configured,
      pages, chunks, source map, index, original-file persistence
   -> no source card LLM call
   -> source_card_status = "pending"

2. prepare_source_card(source_id)
   -> selected excerpts, source metadata, source-card instructions,
      SOURCE_CARD_SCHEMA, commit_tool = "commit_source_card"

3. harness writes source-card JSON

4. commit_source_card(source_id, payload)
   -> validates schema, truncates/bounds fields, saves source_card.json

5. create_job_from_artifacts(task_spec_id, source_ids)
   -> creates/updates EssayJob using already persisted task/source artifacts
```

This keeps the expensive reasoning in the harness while preserving the existing
artifact format that downstream services expect.

### Does Source Ingestion Need A Frontend?

No. A frontend is optional.

For Agent Tool Mode v1, the simplest and most flexible source-ingestion path is
an MCP tool that accepts a local file path:

```json
{
  "path": "C:/Users/Apoorv/Documents/source.pdf"
}
```

Claude Code and Codex already operate in a local workspace context, so a local
path is enough. The MCP server should validate that the path exists and that the
suffix is supported.

The existing frontend can still be useful for users who prefer uploading files
through the browser, but the current frontend upload path calls the API route
that creates LLM source cards. That is acceptable for Pipeline Mode, but not for
cost-relief Agent Tool Mode unless we add an explicit "agent/no-API ingestion"
route later.

Recommended order:

1. Build MCP local-path ingestion first.
2. Keep the existing frontend upload flow unchanged for Pipeline Mode.
3. Later, add an optional frontend Agent Mode upload that performs deterministic
   ingestion and leaves source cards pending for the harness to commit.

### Source Card Dependency

Downstream topic ideation expects source cards. Therefore a source is not fully
ready for agent-driven topic ideation until `commit_source_card` succeeds.

The MCP server should expose this clearly:

```json
{
  "source_id": "src-...",
  "ingestion_status": "text_ready",
  "source_card_status": "pending",
  "next_suggested_tools": ["prepare_source_card"]
}
```

If a user wants to skip source cards, the system may support a deterministic
placeholder later, but that should not be v1. Placeholder cards would weaken
topic ideation quality.

## MCP Surface

The MCP server should be a thin transport over an internal tool facade. Do not
wire MCP handlers directly into random services.

Recommended package shape:

```text
essay_writer/agent_tools/
  __init__.py
  schemas.py
  facade.py
  run_store.py
  work_store.py
  source_tools.py
  prepare_tools.py
  commit_tools.py
  server.py
```

### Facade Responsibilities

The facade should:

- load the configured data directory
- call existing stores and deterministic services
- enforce Agent Tool Mode no-LLM rules
- return bounded structured tool results
- keep transport-specific MCP code out of business logic

### MCP Tools

Initial read/context tools:

```text
get_harness_instructions
start_agent_run
get_agent_run_state
list_agent_runs
recover_agent_run
get_job_summary
list_sources
get_source_card
list_drafts
get_draft
search_source
read_source_packet
list_work_packets
get_work_packet
list_work_results
get_work_result
```

Initial deterministic action tools:

```text
ingest_source_file
create_job_from_artifacts
select_topic
reject_topic
create_research_plan
resolve_source_requests
run_deterministic_checks
save_user_edit
export_markdown
submit_work_result
checkpoint_agent_run
```

Initial prepare tools:

```text
prepare_source_card
prepare_task_spec
prepare_topics
prepare_research_notes
prepare_outline
prepare_draft
prepare_validation
prepare_revision
```

Initial commit tools:

```text
commit_source_card
commit_task_spec
commit_topics
commit_research_notes
commit_outline
commit_draft
commit_validation
commit_revision
```

### MCP Resources

Resources should expose stable artifact handles for inspection, not mutate
state.

Potential resource URIs:

```text
essay://jobs/{job_id}
essay://sources/{source_id}/card
essay://sources/{source_id}/map
essay://sources/{source_id}/manifest
essay://drafts/{job_id}/{version}
essay://exports/{job_id}/{export_id}
```

Resources are useful once the tool facade is stable. They are not required for
the first implementation slice.

### MCP Prompts

Prompts can package recommended workflows for the user:

```text
essay_ingest_sources
essay_plan_from_sources
essay_write_from_existing_job
essay_validate_and_revise_draft
```

Prompts should be added after the tools work. They should guide the harness,
not replace validation in commit tools.

### General Harness Instruction Prompt

Agent Tool Mode needs one general instruction artifact that can be loaded into
the orchestrating harness context at the start of a run.

This should exist in three forms:

```text
docs/agent-tool-mode-instructions.md
MCP prompt: essay_agent_tool_mode
MCP tool: get_harness_instructions
```

The instruction should tell the harness:

- use Agent Tool Mode tools for all persisted workflow actions
- do not call Pipeline Mode/API-backed tools unless the user explicitly opts in
- call `start_agent_run` before beginning a new run
- call `recover_agent_run` after context compaction, resume, or uncertainty
- follow `prepare_* -> harness reasoning -> submit_work_result -> commit_*`
- prefer `work_result_id` for commits
- use subagents when `delegation.recommended=true` and the harness supports it
- treat persisted run state as authoritative and chat memory as advisory
- never invent source IDs, page numbers, note IDs, work packet IDs, or artifact
  IDs
- checkpoint user decisions and blocking questions
- stop and ask the user when `blocked_on` is present or state is ambiguous

This instruction is not a replacement for commit validation. It is the operating
manual for the harness.

Recommended minimal instruction skeleton:

```text
You are orchestrating EssayWriter in Agent Tool Mode.

Rules:
1. Use only Agent Tool Mode MCP tools for persisted actions.
2. Do not use API-backed Pipeline Mode unless the user explicitly asks.
3. Start or recover an AgentRun before doing work.
4. For model-reasoning stages, call prepare_*, produce JSON matching the
   response_schema, submit the JSON with submit_work_result, then call commit_*.
5. If delegation.recommended is true, delegate when possible and have the
   subagent return JSON according to return_contract.
6. Never rely on chat memory for state; recover from AgentRunStore after
   compaction or uncertainty.
7. If blocked_on is set, ask the user to resolve it before continuing.
```

`get_harness_instructions` should return the current instruction text plus
available tool names, mode warnings, and the no-hidden-API rule. MCP prompts can
wrap the same content for clients that support prompt discovery.

## Work Packets

Prepare tools should not return only a generic prompt string. They should return
a structured work packet:

```json
{
  "ok": true,
  "work_packet_id": "workpkt_job-123_outline_001",
  "stage": "outline",
  "instructions": "Create a source-grounded outline...",
  "response_schema": {},
  "context": {},
  "artifact_refs": {
    "job_id": "job-...",
    "research_plan_id": "research_plan_v001",
    "evidence_map_id": "evidence_map_v001"
  },
  "commit_tool": "commit_outline",
  "delegation": {
    "recommended": false,
    "reason": null,
    "suggested_role": null,
    "allowed_tools": [],
    "return_contract": null,
    "subagent_prompt": null
  },
  "warnings": [],
  "next_suggested_tools": ["commit_outline"]
}
```

The harness reads the packet, produces JSON matching `response_schema`, then
calls the named commit tool.

This is better than trying to make a tool "paste a prompt" into the harness.
MCP tools return data into the model context. The model should continue from
that result.

### Work Packet Persistence

Every `prepare_*` tool should persist the work packet before returning it.

The harness should not rely on a long chat transcript or an ad hoc file path to
remember what a subagent was assigned. The tool result should include a stable
`work_packet_id`, and the app should write the packet under an internal
AgentWorkStore.

Recommended storage layout:

```text
data/
  agent_work/
    {job_id or global}/
      packets/
        {work_packet_id}.json
      results/
        {work_result_id}.json
      commits/
        {commit_id}.json
```

For source-scoped work before a job exists, use a global/source namespace:

```text
data/
  agent_work/
    sources/
      {source_id}/
        packets/
        results/
        commits/
```

The physical files are implementation details. The orchestrating harness should
track IDs returned by tools:

```text
prepare_source_card -> work_packet_id
subagent returns JSON
submit_work_result(work_packet_id, payload) -> work_result_id
commit_source_card(work_result_id) -> source_card_id/source_id
```

Do not ask subagents to invent filenames or write arbitrary JSON files. That
creates brittle handoff behavior and bypasses validation. Subagents should
return structured JSON to the harness, or call `submit_work_result` if the
work packet permits it.

### Work Result Store

Subagent outputs should be recorded as work results before or during commit.

Recommended result shape:

```json
{
  "work_result_id": "workres_job-123_source-card-src-abc_001",
  "work_packet_id": "workpkt_job-123_source-card-src-abc_001",
  "status": "submitted",
  "producer": {
    "type": "main_agent | subagent",
    "role": "source_card_writer",
    "name": null
  },
  "payload": {},
  "warnings": [],
  "created_at": "2026-05-09T..."
}
```

Commit tools should accept either direct payloads or `work_result_id`, but the
preferred path is `work_result_id`:

```text
commit_source_card(work_result_id="workres_...")
```

If a commit tool receives a direct payload, it should first create a work result
internally, then commit from that stored result. This keeps auditing consistent
even when no subagent was used.

### How The Orchestrator Finds Outputs

The main harness agent should not scan folders.

It should follow returned IDs and summary fields:

```text
prepare_* returns:
  work_packet_id
  expected_result_kind
  commit_tool

submit_work_result returns:
  work_result_id
  validation_preview
  next_suggested_tools

commit_* returns:
  domain artifact IDs
  linked work_packet_id
  linked work_result_id
```

If the harness loses context, it can call read/list tools:

```text
list_work_packets(job_id, status="prepared")
list_work_results(job_id, status="submitted")
get_work_packet(work_packet_id)
get_work_result(work_result_id)
```

This gives the system resumability without depending on the chat transcript.

## Agent Run Recovery

Work packet/result persistence is necessary but not sufficient. The main
harness agent also needs a run-level ledger that records the current objective,
mode, completed artifacts, pending work, user constraints, and next suggested
actions.

Without this, context compaction can cause subtle bugs:

- the agent may regenerate a source card that was already committed
- the agent may commit an old subagent result to the wrong source or job
- the agent may forget that Agent Tool Mode forbids hidden API-backed tools
- the agent may skip a human decision that was required before continuing
- the agent may continue from a stale draft or validation report

### AgentRunStore

Add an `AgentRunStore` alongside `AgentWorkStore`.

Recommended storage layout:

```text
data/
  agent_runs/
    {agent_run_id}/
      run.json
      checkpoints.jsonl
      events.jsonl
```

Recommended `run.json` shape:

```json
{
  "agent_run_id": "agentrun_20260509_001",
  "mode": "agent_tool_no_api",
  "status": "active",
  "job_id": "job-...",
  "objective": "Create a source-grounded essay draft from uploaded sources.",
  "current_phase": "source_cards",
  "user_constraints": [
    "Do not use app API credits",
    "Use subagents for source-card packets when useful"
  ],
  "artifact_refs": {
    "source_ids": ["src-..."],
    "task_spec_id": null,
    "selected_topic_id": null,
    "latest_draft_id": null
  },
  "pending_work_packet_ids": [],
  "submitted_work_result_ids": [],
  "committed_artifact_ids": [],
  "blocked_on": null,
  "next_suggested_tools": ["prepare_source_card"],
  "updated_at": "2026-05-09T..."
}
```

Every state-changing tool should append an event and update the run if an
`agent_run_id` is supplied. Prepare tools should attach created
`work_packet_id`s. `submit_work_result` should attach `work_result_id`s. Commit
tools should link committed domain artifacts back to their work result.

### Recovery Protocol

Harness instructions should require a recovery check at the start of any Agent
Tool Mode session and after any context compaction/resume.

Recommended protocol:

```text
1. If agent_run_id is known:
   call get_agent_run_state(agent_run_id)

2. If agent_run_id is unknown but job_id is known:
   call list_agent_runs(job_id, status="active")
   then get_agent_run_state for the most recent matching run

3. If neither is known:
   call list_agent_runs(status="active", limit=5)
   ask the user which run to resume if more than one is plausible

4. Reconstruct local context from:
   - run objective
   - current phase
   - user constraints
   - artifact refs
   - pending work packets
   - submitted work results
   - latest committed artifacts
   - blocked_on / next_suggested_tools

5. Continue only by calling the next tool listed by the recovered state or by
   asking the user to resolve ambiguity.
```

The MCP server should expose a `recover_agent_run` convenience tool that returns
a compact recovery packet for the harness:

```json
{
  "agent_run_id": "agentrun_...",
  "mode": "agent_tool_no_api",
  "objective": "...",
  "current_phase": "source_cards",
  "must_remember": [
    "Do not call Pipeline Mode tools",
    "Commit source cards from work_result_id, not raw chat text"
  ],
  "artifact_refs": {},
  "pending": [],
  "submitted_results": [],
  "next_suggested_tools": []
}
```

This packet should be short enough to fit comfortably into context.

### Checkpointing

The main harness agent should checkpoint after each meaningful decision or
state-changing tool call.

Recommended checkpoints:

- after source ingestion
- after each source-card result is submitted or committed
- after task spec commit
- after topic generation and user topic selection
- after research plan creation
- after evidence map commit
- after outline commit
- after draft commit
- after validation commit
- before asking the user a blocking question

Use `checkpoint_agent_run` for decisions that are not already captured by a
domain commit, such as:

```json
{
  "agent_run_id": "agentrun_...",
  "current_phase": "topic_selection",
  "decision": "User rejected topic_002 because it was too broad.",
  "next_suggested_tools": ["prepare_topics"]
}
```

### Idempotency And Duplicate Prevention

State-changing tools should be idempotent where practical.

Recommended rules:

- `prepare_*` may create a new work packet, but should include a
  `reuse_existing=true` option to return an existing compatible packet.
- `submit_work_result` should use a content hash and `work_packet_id` to detect
  duplicate submissions.
- `commit_*` should reject a `work_result_id` that was already committed unless
  `force_new_version=true` is explicitly supplied.
- commit responses should include `already_committed=true` when a retry repeats
  a successful commit.

This matters because after compaction or connection loss, the harness may retry
the last action. Retries should not silently create duplicate source cards,
topic rounds, drafts, or validation reports.

### Leases For Parallel Work

When subagents are used, work packets should support lightweight leases:

```json
{
  "work_packet_id": "workpkt_...",
  "status": "assigned",
  "assigned_role": "source_card_writer",
  "lease_expires_at": "2026-05-09T..."
}
```

The lease is advisory. It prevents the main agent from accidentally assigning
the same packet to multiple subagents, but expired leases should be recoverable
so a stuck subagent does not block the run forever.

### Human Approval Recovery

Any point that requires user input must be represented in `blocked_on`, not
only in chat.

Examples:

```text
blocked_on = "topic_selection"
blocked_on = "assignment_prompt_option"
blocked_on = "insufficient_evidence_upload_more_sources"
```

After compaction, the agent should see the block and ask the user the exact
pending question instead of inventing a continuation.

## Subagent Strategy

Agent Tool Mode should support subagents as a harness policy, not as a hard
requirement inside the MCP server.

The MCP server should make delegation easy by returning self-contained work
packets with explicit delegation hints. The main harness agent remains the
coordinator. Subagents are bounded workers for context-heavy or parallelizable
tasks.

Recommended mental model:

```text
main harness agent = coordinator, planner, final synthesizer
subagents          = source readers, source-card writers, scouts, reviewers
MCP tools          = persistence, validation, source access, artifact commits
```

### Should Subagents Be Enforced?

Do not enforce subagent spawning at the MCP-server level.

Reasons:

- MCP clients differ. Some harnesses have first-class subagents; others do not.
- Small jobs may not need delegation.
- Enforcing subagents would make the tools less portable.
- Debugging is easier when every delegated step also has a single-agent
  fallback.

Instead, prepare tools should return a `delegation` object:

```json
{
  "delegation": {
    "recommended": true,
    "reason": "This source-card packet contains 14,000 chars of excerpts and is independent of other sources.",
    "suggested_role": "source_card_writer",
    "allowed_tools": ["read_source_packet"],
    "return_contract": "Return JSON matching response_schema. Do not commit artifacts.",
    "subagent_prompt": "You are summarizing source src-abc for an essay workflow..."
  }
}
```

Harness instructions should say:

```text
When delegation.recommended is true, spawn a subagent if the harness supports
subagents and the user has not disabled delegation. Give the subagent only the
work packet, allowed tool list, and return contract. The main agent should
review the result and call the commit tool unless the work packet explicitly
allows a source-scoped commit.
```

This tells the orchestrating harness agent that it does not need to do the work
itself without making the app depend on a specific subagent mechanism.

### Good Subagent Stages

Use subagents for bounded, context-expensive, one-time, or parallel work.

#### Source Card Generation

Best first subagent use case.

```text
main agent:
  ingest_source_file for each uploaded source
  prepare_source_card for each source

parallel subagents:
  read one source-card work packet
  produce source-card JSON

main agent:
  review each JSON result
  commit_source_card for each source
```

Default policy:

- subagent recommended when a source-card packet exceeds a modest context
  threshold or when there are multiple sources
- subagent should return JSON only
- main agent should commit the source card in v1
- later, source-scoped `commit_source_card` can be allowed directly from a
  bounded write subagent

#### Deep Source Reading

Useful for long sources or many source packets.

```text
subagent A: inspect pages 1-30 for background and definitions
subagent B: inspect pages 31-60 for evidence and examples
subagent C: inspect pages 61-90 for counterarguments and limitations
```

Subagents return candidate notes with packet IDs and quote text. The main agent
or a strict commit tool validates quotes against source packets before
persistence.

#### Web Research

Use subagents for optional external research because search/fetch/evaluate work
is separable.

Each web-research subagent should return:

- URL
- captured text or excerpt source
- citation metadata
- reliability notes
- relevance notes
- warnings

The app should persist accepted web results as source artifacts before they can
influence evidence maps or drafts.

#### Topic Feasibility Checks

Candidate topics can be evaluated independently.

```text
subagent A: assess topic_001 evidence sufficiency
subagent B: assess topic_002 evidence sufficiency
subagent C: assess topic_003 evidence sufficiency
```

The main agent should compare the feasibility reports and either present
options to the user or select a topic only after an explicit user choice.

#### Validation And Review Lenses

Manual review lenses are naturally parallel:

```text
evidence reviewer
citation reviewer
assignment-fit reviewer
tone reviewer
anti-AI/style reviewer
```

The main agent should merge the findings into one revision plan. The app should
still store the final validation or manual-revision artifact through commit
tools.

### Poor Subagent Stages

Avoid subagents for global synthesis steps unless there is a very clear
ownership boundary.

The main harness agent should usually keep control of:

- final thesis choice
- final outline architecture
- final draft assembly
- final revision synthesis
- export
- job state transitions that affect the whole workflow

Subagents may draft individual sections later, but this is not a first-slice
feature. Section-level drafting risks voice inconsistency, duplicated claims,
and citation drift. If used, the main agent should perform a final unifying pass
before `commit_draft`.

### Read-Only And Bounded-Write Subagents

Harness instructions should distinguish two subagent types.

Read-only subagents:

```text
can call:
  get_source_card
  search_source
  read_source_packet
  prepare_*

cannot call:
  commit_*
  save_user_edit
  export_markdown
```

Bounded-write subagents:

```text
can call:
  commit_source_card for one assigned source_id
  future source-scoped web-source commit tools

cannot call:
  commit_draft
  commit_validation
  commit_revision
  export_markdown
```

V1 should default to read-only subagents. The main agent should call commit
tools after reviewing returned JSON.

### How To Tell The Main Harness Agent To Delegate

Use three layers:

1. MCP work packet metadata:

```json
{
  "delegation": {
    "recommended": true,
    "suggested_role": "source_card_writer",
    "subagent_prompt": "...",
    "return_contract": "Return JSON only; do not modify artifacts."
  }
}
```

2. MCP prompts and repository docs:

```text
If a work packet recommends delegation, the main agent should delegate unless
the user disabled subagents, the harness lacks subagent support, or the task is
small enough to handle directly.
```

3. Tool naming and packet size:

Prepare tools should have narrow names and source-scoped packet IDs, such as
`prepare_source_card(source_id)`, so the main agent can hand off one packet
without giving a subagent the whole job context.

This keeps delegation a strong default for expensive separable work while
preserving portability and user control.

## Commit Validation

Commit tools are the safety boundary.

They should reject or repair invalid model output before anything is persisted.

Examples:

- `commit_source_card` validates required fields, size limits, and source ID.
- `commit_task_spec` merges deterministic adversarial flags and strips
  AI-directed instructions from checklist requirements.
- `commit_topics` validates source IDs and locator shapes.
- `commit_research_notes` verifies note chunk IDs and drops quotes not found in
  source packets.
- `commit_outline` validates note IDs and section shape.
- `commit_draft` validates selected topic, outline ID, section source map, and
  bibliography candidate type.
- `commit_validation` normalizes diagnostics and stores pass/fail state.

The agent can be flexible. The persisted artifact graph must stay strict.

## Prompt And Schema Reuse

Do not rewrite the entire prompt system from scratch.

The current service prompts already encode important product behavior:

- task-spec extraction guards adversarial assignment text
- source cards use uploaded excerpts only
- topic ideation prefers source maps and source requests
- final research validates grounded notes
- outlining preserves note/source traceability
- drafting carries anti-AI and source-grounding guidance
- validation returns structured diagnostics

Agent Tool Mode should reuse these instructions and JSON schemas as
prepare-packet assets, but it should not call the app LLM client to execute
them.

Recommended pattern:

```text
existing prompt constants / schema
  -> prepare_* work packet instructions and response_schema
  -> harness generates structured JSON
  -> commit_* uses existing payload-to-domain normalization and validation
```

Some refactoring will be needed because current services often combine:

```text
build prompt -> call llm_client.chat_json -> convert payload to dataclass
```

Agent Tool Mode needs those separated:

```text
build work packet -> external harness reasoning -> commit payload
```

Implementation should extract reusable pure functions where needed:

- prompt/context builders
- response schemas
- payload-to-domain converters
- deterministic validators

The app should keep Pipeline Mode working with the same prompts. Agent Tool Mode
just exposes those prompts and schemas instead of executing them with app API
credits.

## No-Implicit-API Enforcement

Agent Tool Mode should enforce no hidden model calls technically.

Recommended enforcement:

1. MCP server sets `ESSAY_AGENT_TOOL_MODE=1`.
2. Agent tool facade never imports `backend.deps.get_llm_client`,
   `LoggingLLMClient`, or `make_client`.
3. Agent-only ingestion uses a deterministic ingestion path that does not call
   `build_source_card` with an LLM client.
4. Tests monkeypatch LLM factory/client creation and fail if any MCP tool tries
   to instantiate one.
5. Tool results include a `mode` field:
6. Add import-boundary tests or static checks so `essay_writer.agent_tools`
   cannot import `llm.factory`, `llm.logging_client`, provider adapters, or
   `backend.deps`.
7. Add runtime guard objects for Agent Tool Mode tests: if `LLMClient.chat_json`
   is called inside any agent tool path, the test fails.
8. Keep API-backed Pipeline Mode tools out of the Agent Tool Mode MCP server
   namespace. If exposed later, name them explicitly, e.g.
   `pipeline_run_with_configured_api`.

```json
{
  "mode": "agent_tool_no_api"
}
```

Pipeline Mode can still exist with API-backed source cards and LLM calls. It
should just be clearly separate.

## Serial Workflow

The harness should run serial tasks explicitly rather than through one giant
`write_essay` tool.

Recommended full agent-driven sequence:

```text
ingest_source_file
prepare_source_card -> commit_source_card
prepare_task_spec -> commit_task_spec
create_job_from_artifacts
prepare_topics -> commit_topics
select_topic
create_research_plan
resolve_source_requests
prepare_research_notes -> commit_research_notes
prepare_outline -> commit_outline
prepare_draft -> commit_draft
prepare_validation -> commit_validation
export_markdown
```

The MCP server can return `next_suggested_tools`, but the harness decides what
to do next. This preserves the interactive benefit of Claude Code/Codex while
keeping every durable action inspectable.

## Frontend Relationship

The frontend should not be required for Agent Tool Mode v1.

Possible frontend roles later:

- show artifact history while the harness works
- upload files into deterministic pending-card ingestion
- display pending source cards, topic rounds, drafts, and validation reports
- provide manual edits that the harness can revise

For now, the MCP server should work from local paths and persisted artifacts.
This keeps the first implementation smaller and avoids mixing browser upload
state with harness control.

## Implementation Phases

### Phase 1: Internal Agent Tool Facade

Add the internal facade and schemas.

Deliverables:

- `docs/agent-tool-mode-instructions.md`
- `essay_writer/agent_tools/schemas.py`
- `essay_writer/agent_tools/facade.py`
- `essay_writer/agent_tools/run_store.py`
- `essay_writer/agent_tools/work_store.py`
- common `ToolResult`, `WorkPacket`, and artifact-ref models
- persisted agent run, checkpoint, and event models
- persisted work packet, work result, and commit-link models
- `get_harness_instructions`
- `start_agent_run`, `get_agent_run_state`, `recover_agent_run`,
  `list_agent_runs`, and `checkpoint_agent_run`
- `submit_work_result`, `get_work_packet`, `get_work_result`,
  `list_work_packets`, and `list_work_results`
- no MCP dependency required yet

Tests:

- facade can load configured stores
- errors are structured
- result payloads are bounded
- prepare tools persist a work packet and return `work_packet_id`
- direct-payload commit creates a work result internally before committing
- list/get work tools can recover pending packets and submitted results
- recovery tools reconstruct current phase, artifact refs, pending work, and
  next suggested tools from persisted state
- repeated submit/commit calls are idempotent or return clear duplicate errors
- LLM factory is not called
- agent tool package import-boundary checks reject provider/API-backed imports

### Phase 2: No-API Source Ingestion Slice

Add deterministic source ingestion for Agent Tool Mode.

Deliverables:

- `ingest_source_file`
- `prepare_source_card`
- `commit_source_card`
- support for saving source artifacts with pending/committed source-card state
- reuse existing pages/chunks/source-map/index artifact formats

Important implementation note:

The existing `SourceIngestionResult` requires `source_card`. We can either:

1. add a separate deterministic source-materialization result type, or
2. allow `SourceIngestionResult.source_card` to be optional after a planned
   schema migration.

Prefer option 1 for smaller blast radius:

```text
SourceMaterializationResult
  source
  pages
  chunks
  indexed
  full_text_available
  index_manifest
  source_map
  warnings
```

Then add a `SourceStore.save_materialized_source(...)` method that writes all
text/index/map artifacts but does not write `source_card.json`.

Tests:

- PDF/DOCX/TXT/MD ingestion does not call LLM
- source artifacts are readable after materialization
- source card is pending until committed
- committed source card is loadable by existing downstream code

### Phase 3: MCP Server Wrapper

Expose the facade through MCP stdio.

Deliverables:

- `essay_writer/agent_tools/server.py`
- project `.mcp.json` or documented setup command
- tool schemas generated from Pydantic models where possible

Tests:

- server starts
- tools list deterministically
- basic tool call works with a temp data directory
- no tool emits huge unbounded output

### Phase 4: Task Spec And Job Creation

Add harness-owned assignment parsing and job creation.

Deliverables:

- `prepare_task_spec`
- `commit_task_spec`
- `create_job_from_artifacts`

Tests:

- deterministic adversarial scan is applied during commit
- blocking questions are persisted
- job can be created from committed task spec and committed source cards

### Phase 5: Topic, Research, Outline, Draft

Add the main writing stages.

Deliverables:

- `prepare_topics` / `commit_topics`
- `create_research_plan`
- `resolve_source_requests`
- `prepare_research_notes` / `commit_research_notes`
- `prepare_outline` / `commit_outline`
- `prepare_draft` / `commit_draft`

Tests:

- invalid source IDs are rejected
- invalid page ranges are rejected
- quotes not present in source text are dropped or rejected
- outline note IDs must exist
- draft lineage is stored

### Phase 6: Validation, Revision, Export

Add quality-control tools.

Deliverables:

- `run_deterministic_checks`
- `prepare_validation` / `commit_validation`
- `prepare_revision` / `commit_revision`
- `save_user_edit`
- `export_markdown`

Tests:

- validation status updates job state
- revision creates a new draft version
- export links to draft and validation artifacts

### Phase 7: MCP Resources And Prompts

Add nicer harness ergonomics.

Deliverables:

- artifact resources
- workflow prompts
- MCP prompt `essay_agent_tool_mode` backed by
  `docs/agent-tool-mode-instructions.md`
- documentation for Claude Code and Codex usage
- harness instructions for delegation behavior
- reusable subagent prompt templates for source cards, deep source reading,
  topic feasibility, web research, and review lenses

Tests:

- resources are read-only
- prompt output references real tool names
- delegation metadata is present on large/source-scoped work packets
- subagent prompt templates include allowed tools and return contracts

## Recommended First Vertical Slice

Build this first:

```text
ingest_source_file
prepare_source_card
commit_source_card
get_source_card
search_source
read_source_packet
```

Reason:

- It proves the no-hidden-API rule at the most dangerous boundary.
- It answers the biggest practical question: how does a harness get sources
  into the system without using app credits?
- It creates reusable artifacts needed by every later stage.

After that, add:

```text
prepare_task_spec
commit_task_spec
create_job_from_artifacts
get_job_summary
```

Then move into topic/research/outline/draft.

## Risks

### Source Card Quality

Harness-generated source cards may vary more than app-generated source cards.
Commit validation can enforce shape, but not perfect judgment. The mitigation is
to keep source-card instructions explicit and include selected excerpts rather
than making the harness browse the whole source.

### Tool Output Size

MCP tool outputs can overload the harness context. Every read/prepare tool
needs budgets and pagination.

### Hidden API Regression

Future contributors may accidentally call LLM-backed services from Agent Tool
Mode. Tests and package boundaries need to make this hard.

### Artifact Compatibility

Existing downstream code expects `source_card.json`. Pending-card source
artifacts need clear status handling so downstream stages do not fail with
confusing file errors.

### Subagent Drift

Subagents may return inconsistent style, duplicate findings, or partially
overlapping evidence. The mitigation is to keep subagent tasks narrow, require
JSON return contracts, and let the main agent perform final synthesis and
commits.

### Lost Handoff State

If subagent outputs live only in the chat transcript, the main agent may lose
track of which result belongs to which work packet after context compaction or
an interrupted run. The mitigation is to persist every work packet and work
result in AgentWorkStore and pass IDs between tools.

### Lost Run State After Context Compaction

If the main harness agent loses its run-level memory, it may continue from the
wrong phase or repeat an already completed action. The mitigation is
AgentRunStore plus a required recovery protocol: call `get_agent_run_state` or
`recover_agent_run` before continuing after any resume/compaction.

### Duplicate Commits

Retries after interruption can duplicate source cards, topic rounds, drafts, or
validation reports. The mitigation is idempotency keys based on
`work_packet_id`, `work_result_id`, content hashes, and explicit
`force_new_version` flags for intentional new versions.

### Over-Delegation

If every small action becomes a subagent task, the workflow becomes slower and
harder to follow. Delegation should be recommended for context-heavy or
parallelizable work, not enforced universally.

## Open Decisions

1. Should `commit_source_card` reject weak cards, or save them with warnings?
   Recommendation: save with warnings unless required fields are missing.

2. Should Agent Tool Mode allow OCR during ingestion?
   Recommendation: yes, but only local OCR. OCR is compute cost, not LLM API
   cost. Keep it configurable.

3. Should the frontend get Agent Mode upload before full MCP writing stages?
   Recommendation: no. Build local-path MCP ingestion first.

4. Should a one-shot `agent_write_essay` MCP prompt exist?
   Recommendation: eventually yes as a prompt, not as a tool. It should guide
   the harness through explicit tool calls.

5. Should Agent Tool Mode update `EssayJob.status` exactly like Pipeline Mode?
   Recommendation: yes where possible, but allow additional pending statuses in
   tool results rather than expanding job statuses too early.

6. What threshold should trigger `delegation.recommended=true`?
   Recommendation: start with simple heuristics: multiple sources, source-card
   packets over 8,000 characters, deep source reading over 3 packets, or any
   web-research batch with multiple independent targets.

7. Should subagents be allowed to call commit tools?
   Recommendation: no in v1 except possibly future source-scoped commits. The
   main harness agent should review subagent output and call commits.

8. Should subagent outputs be stored as arbitrary JSON files?
   Recommendation: no. Store them as AgentWorkStore `WorkResult` artifacts with
   stable IDs. The physical JSON files are internal implementation details.

9. Should commit tools require `work_result_id` only?
   Recommendation: accept both direct payloads and `work_result_id`, but always
   persist a work result internally before committing so audit behavior is
   consistent.

10. Should the harness be trusted to remember run state after compaction?
    Recommendation: no. Require recovery from AgentRunStore. The harness should
    treat chat memory as advisory and persisted run state as authoritative.

11. Should state-changing tools update run state automatically?
    Recommendation: yes when `agent_run_id` is supplied. The main agent should
    not have to remember to checkpoint after every committed artifact, though
    `checkpoint_agent_run` remains available for decisions and user-facing
    blocks.

12. Is `docs/agent-harness-implementation.md` enough to implement from?
    Recommendation: no. Keep it as the architecture/design plan, then create a
    separate implementation spec or plan before coding with file-level tasks,
    migration steps, and focused tests.

13. Should Agent Tool Mode rewrite the existing LLM prompts?
    Recommendation: no. Reuse existing prompt instructions and schemas in
    prepare packets, but separate prompt construction from app-owned LLM
    execution.

14. How should the main harness receive operating instructions?
    Recommendation: add `docs/agent-tool-mode-instructions.md`,
    `get_harness_instructions`, and an MCP prompt named
    `essay_agent_tool_mode`. The instruction text should be loaded into the
    harness context at run start and after recovery when needed.
