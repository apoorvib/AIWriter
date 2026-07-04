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
