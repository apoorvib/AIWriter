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
