# Agent Tool Mode MCP Usage

Agent Tool Mode lets Claude Code, Codex, and other MCP clients run the essay workflow through local tools without using the app's configured LLM API clients.

## Install

```powershell
pip install -e ".[agent-tools]"
```

## Run

```powershell
$env:ESSAY_DATA_DIR = "./data"
python -m essay_writer.agent_tools.server
```

## MCP Client Config

Use `.mcp.example.json` as the starting point for local client configuration.

## Operating Rule

Start by calling `get_harness_instructions`. Then start or recover an agent run. For every model-reasoning stage, use the prepare, submit, and commit cycle.

The app prepares a local work packet, the harness model produces JSON with its own subscription/runtime, and the commit tool validates and persists the artifact. Agent Tool Mode tools must not call the app's LLM client methods for reasoning stages.

## Claude Code Dynamic Workflows

Two saved workflows in `.claude/workflows/` drive the MCP tools:

- `/essay-prep` — ingest → source cards → task spec → job → writing-style
  decision → topics, then stops for you to choose a topic.
- `/essay-write` — `select_topic` (your choice) → research planning + source
  resolution → research notes → outline → draft → anti-AI audit → validation
  → export.

`/essay-prep` is a fixed pre-job sequence whose endpoint is protected by server
gates. The pre-job completion ledger cannot independently scope source-card and
task-spec artifacts until a job exists. `/essay-write` loops on
`get_workflow_progress(agent_run_id)`, a read-only ledger derived from persisted
state, and acts on its `next_required_step`. Research planning and source
resolution are bundled into one workflow action. Style revision remains
available through the MCP tools but is marked recommended, so the required-step
loop does not select it automatically.

The write loop is bounded to 60 iterations and currently formats its completion
message without a final ledger assertion. After an unusual tool failure, verify
the export or call `get_workflow_progress` before treating the run as complete.
Pre-allowlist `mcp__essaywriter__*` (see `.claude/settings.json`) so background
workflow subagents are not blocked by mid-run permission prompts. These scripts
are Claude Code only and require manual runtime verification; the Python test
suite covers the MCP gates and ledger, not the Dynamic Workflow JavaScript.
Other harnesses drive the same MCP tools manually.

## Generic writing tools and `/write`

The same server also exposes a separate, self-contained surface for generic
short-form writing (emails, texts, LinkedIn posts, blogs, general prose). These
tools drive the `essay_writer.writing` domain and never touch `EssayJob` or the
essay tools above. Runs persist under `${ESSAY_DATA_DIR}/writing/` and are keyed
by a `writing_run_id` (`wrun_…`).

Registered tools (all prefixed `mcp__essaywriter__`):

- Lifecycle: `start_writing_run`, `recover_writing_run`, `get_writing_progress`,
  `list_writing_runs`, `get_writing_output`, `ingest_writing_context`.
- Brief + clarification: `prepare_writing_brief`, `submit_writing_result`,
  `commit_writing_brief`, `answer_writing_questions`.
- Research (optional, bounded): `prepare_writing_research`,
  `commit_writing_research`.
- Plan + draft (per deliverable): `prepare_writing_plan`, `commit_writing_plan`,
  `prepare_writing_draft`, `commit_writing_draft`.
- Detailed review + revision + finalize: `prepare_writing_review`,
  `dispatch_writing_reviewer`, `commit_writing_review`,
  `prepare_writing_revision`, `commit_writing_revision`, `finalize_writing_run`.

A single server-derived completion ledger (`get_writing_progress`) is
authoritative; there is no second mutable phase machine. Each call reads only
persisted artifacts and returns the next required step
(`brief` → optional `research` → per-deliverable `plan`/`draft`/`review`/`revision`
→ `finalize`) plus `requires_human` when the brief has blocking questions. The
`/write` Dynamic Workflow in `.claude/workflows/write.js` loops on this ledger
(bounded to 30 actions with a per-step retry cap of two), performs a final
`all_required_done` assertion, and returns the persisted output from
`get_writing_output`. `submit_writing_result` enforces the same attention-token
proof as the essay tools, and detailed review packets are `delegation_required`:
they must be produced by a subagent-typed producer carrying a token from
`dispatch_writing_reviewer`. See `docs/agent-tool-mode-instructions.md` for the
manual step sequence.
