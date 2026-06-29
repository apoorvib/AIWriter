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

Two saved workflows (in `.claude/workflows/`) drive the MCP tools
deterministically so no required step is skipped:

- `/essay-prep` — ingest → source cards → task spec → job → writing-style
  decision → topics, then stops for you to choose a topic.
- `/essay-write` — `select_topic` (your choice) → research → outline → draft →
  style revision → anti-AI audit → validation → export.

Both loop on `get_workflow_progress(agent_run_id)`, a read-only completion
ledger that reports which required steps are done from persisted state. The loop
acts only on the server's `next_required_step` and exits only when the server
reports `all_required_done`, so a step that did not actually persist its artifact
is re-attempted instead of skipped. Pre-allowlist `mcp__essaywriter__*` (see
`.claude/settings.json`) so background workflow subagents are not blocked by
mid-run permission prompts. These scripts are Claude Code only; other harnesses
drive the same MCP tools manually.
