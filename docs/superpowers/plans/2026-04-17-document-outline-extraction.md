# Document Outline Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Status (2026-04-18):** All 24 planned tasks executed and committed. 96 tests passing. 7 post-plan review fixes landed (commits `2d80c6e`, `0f848f7`, `dccf79d`, `6ee3997`, `af6e22c`, `12099a8`, plus the prompt/logging/dotenv changes on top). Live validation on `testpdfs/IntelTechniques-OSINT.pdf` recovered 47/47 chapters. Spec §12 tracks deferred sub-items (chunk-boundary TOC merge, multi-segment detection, OCR-tier escalation) — these are intentional gaps, not bugs introduced by the plan. This plan is preserved as a historical build log; new work should start a new plan rather than edit this one.

**Goal:** Build a document outline extractor that turns ingested PDFs into a canonical, versioned outline (chapters/sections with resolved `pdf_page` ranges) and exposes it as a `list_outline` / `get_section` tool surface for downstream LLM workflow stages.

**Architecture:** Four-layer pipeline. Layer 1 reads structural PDF metadata (`/Outlines`, `/PageLabels`) when present. Layer 2 uses an LLM to extract raw TOC entries from the first N pages (text-extraction first, OCR fallback per-page). Layer 3 resolves printed→pdf_page offsets deterministically via anchor-scan + fuzzy title matching + cross-validation — no per-entry LLM calls. Layer 4 assigns chapter end pages. A minimal multi-provider LLM shim (Claude / OpenAI / Gemini) ships as a prerequisite.

**Tech Stack:** Python 3.11+, `pypdf` (structural metadata), `pypdfium2` (already present), `rapidfuzz` (fuzzy matching), `anthropic` / `openai` / `google-generativeai` SDKs, `pytest`.

**Spec:** `docs/superpowers/specs/2026-04-17-document-outline-extraction-design.md`

---

## Prerequisites

- The repo is not yet a git repo. Before starting, run `git init` at the project root so the commit steps in this plan work.
- Python virtualenv with existing `pdf_pipeline` deps installed.
- Add new dependencies to `pyproject.toml` (see Task 1 for exact additions).
- API keys for the providers you want to use: `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, `GEMINI_API_KEY`. At least one must be set for live integration tests; all unit tests use a mock client and work without keys.

## File Structure

```
llm/
  __init__.py
  client.py                              # LLMClient protocol, ChatMessage, JsonSchema types
  mock.py                                # MockLLMClient for tests
  factory.py                             # make_client(provider) — env-driven
  adapters/
    __init__.py
    claude.py                            # ClaudeClient (anthropic SDK, tool-use JSON)
    openai_.py                           # OpenAIClient (response_format json_schema)
    gemini.py                            # GeminiClient (response_schema)

pdf_pipeline/outline/
  __init__.py                            # public exports
  schema.py                              # OutlineEntry, DocumentOutline, SourceType
  metadata.py                            # Layer 1: /Outlines + /PageLabels readers
  prefilter.py                           # heuristic TOC presence detection
  page_text.py                           # per-page text source (text-first, OCR fallback)
  entry_extraction.py                    # Layer 2: chunked LLM TOC extraction
  prompts.py                             # Layer 2 system prompt + JSON schema
  anchor_scan.py                         # Layer 3: offset resolution
  range_assignment.py                    # Layer 4: start→end page assignment
  pipeline.py                            # extract_outline(pdf, llm) orchestrator
  storage.py                             # versioned DocumentOutline store
  tools.py                               # list_outline, get_section

tests/
  llm/
    test_client.py
    test_mock.py
    test_factory.py
  outline/
    conftest.py                          # shared fixtures
    test_schema.py
    test_metadata.py
    test_prefilter.py
    test_page_text.py
    test_entry_extraction.py             # mocked LLM
    test_anchor_scan.py
    test_range_assignment.py
    test_pipeline.py
    test_storage.py
    test_tools.py
    fixtures/
      README.md                          # how to generate/refresh fixtures
      born_digital_with_outlines.pdf
      page_labels_only.pdf
      article_no_toc.pdf
      scanned_book_fragment.pdf
```

**Rationale:** LLM shim lives in its own top-level package because it's reused beyond this feature (task spec parsing, note extraction, etc. per plan.md). Outline code is a subpackage of the existing `pdf_pipeline` to sit alongside the baseline extractors.

---

## Part A — Multi-Provider LLM Shim

### Task 1: Project setup — deps and package skeletons

**Files:**
- Modify: `pyproject.toml`
- Create: `llm/__init__.py`
- Create: `llm/adapters/__init__.py`
- Create: `pdf_pipeline/outline/__init__.py`
- Create: `tests/llm/__init__.py`
- Create: `tests/outline/__init__.py`

- [ ] **Step 1: Add dependencies to `pyproject.toml`**

Under `[project.optional-dependencies]` (create the section if missing), add:

```toml
[project.optional-dependencies]
llm-claude = ["anthropic>=0.39.0"]
llm-openai = ["openai>=1.54.0"]
llm-gemini = ["google-generativeai>=0.8.0"]
llm-all = ["anthropic>=0.39.0", "openai>=1.54.0", "google-generativeai>=0.8.0"]
outline = ["rapidfuzz>=3.10.0", "pypdf>=5.0.0"]
```

Install: `pip install -e ".[llm-all,outline]"` (also installs any existing dev/test extras).

- [ ] **Step 2: Create empty package files**

Create these files with just a single-line module docstring:

```python
# llm/__init__.py
"""Minimal multi-provider LLM client shim."""
```

```python
# llm/adapters/__init__.py
"""Provider-specific LLM adapters."""
```

```python
# pdf_pipeline/outline/__init__.py
"""Document outline extraction pipeline."""
```

```python
# tests/llm/__init__.py
"""LLM shim tests."""
```

```python
# tests/outline/__init__.py
"""Outline extraction tests."""
```

- [ ] **Step 3: Verify package imports**

Run: `python -c "import llm, llm.adapters, pdf_pipeline.outline; print('ok')"`
Expected: `ok`

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml llm pdf_pipeline/outline tests/llm tests/outline
git commit -m "feat(outline): scaffold llm shim and outline package"
```

---

### Task 2: LLMClient protocol + shared types

**Files:**
- Create: `llm/client.py`
- Create: `tests/llm/test_client.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_client.py`:

```python
from llm.client import ChatMessage, LLMClient, LLMError


def test_chat_message_fields():
    msg = ChatMessage(role="user", content="hello")
    assert msg.role == "user"
    assert msg.content == "hello"


def test_llm_client_is_protocol_runtime_checkable():
    class StubClient:
        def chat_json(self, system, user, json_schema, max_tokens=4096):
            return {}

    assert isinstance(StubClient(), LLMClient)


def test_llm_client_rejects_non_conforming():
    class NotAClient:
        def send(self, x):
            return x

    assert not isinstance(NotAClient(), LLMClient)


def test_llm_error_is_exception():
    err = LLMError("boom")
    assert isinstance(err, Exception)
    assert str(err) == "boom"
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_client.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'llm.client'`

- [ ] **Step 3: Implement the module**

Create `llm/client.py`:

```python
"""LLMClient protocol and shared types for the multi-provider shim."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True)
class ChatMessage:
    role: str  # "system" | "user" | "assistant"
    content: str


class LLMError(Exception):
    """Raised when an LLM call fails or returns malformed output."""


@runtime_checkable
class LLMClient(Protocol):
    """Minimal provider-agnostic JSON-output client.

    Implementations enforce structured JSON output using their provider's
    native mechanism (Anthropic tool-use, OpenAI response_format json_schema,
    Gemini response_schema). The returned dict must conform to json_schema.
    """

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]: ...
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_client.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add llm/client.py tests/llm/test_client.py
git commit -m "feat(llm): LLMClient protocol and shared types"
```

---

### Task 3: MockLLMClient for testing

**Files:**
- Create: `llm/mock.py`
- Create: `tests/llm/test_mock.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_mock.py`:

```python
import pytest

from llm.client import LLMClient
from llm.mock import MockLLMClient


def test_mock_returns_queued_response():
    client = MockLLMClient(responses=[{"foo": 1}, {"foo": 2}])
    assert client.chat_json("s", "u", {}) == {"foo": 1}
    assert client.chat_json("s", "u", {}) == {"foo": 2}


def test_mock_records_calls():
    client = MockLLMClient(responses=[{"x": 1}])
    client.chat_json("sys-text", "user-text", {"type": "object"}, max_tokens=100)
    assert len(client.calls) == 1
    assert client.calls[0]["system"] == "sys-text"
    assert client.calls[0]["user"] == "user-text"
    assert client.calls[0]["max_tokens"] == 100


def test_mock_raises_when_exhausted():
    client = MockLLMClient(responses=[{"x": 1}])
    client.chat_json("s", "u", {})
    with pytest.raises(RuntimeError, match="ran out of responses"):
        client.chat_json("s", "u", {})


def test_mock_conforms_to_protocol():
    assert isinstance(MockLLMClient(responses=[]), LLMClient)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_mock.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.mock'`

- [ ] **Step 3: Implement MockLLMClient**

Create `llm/mock.py`:

```python
"""In-memory LLMClient for tests."""
from __future__ import annotations

from typing import Any


class MockLLMClient:
    """LLMClient stand-in that returns queued responses and records calls."""

    def __init__(self, responses: list[dict[str, Any]]) -> None:
        self._responses: list[dict[str, Any]] = list(responses)
        self.calls: list[dict[str, Any]] = []

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "system": system,
                "user": user,
                "json_schema": json_schema,
                "max_tokens": max_tokens,
            }
        )
        if not self._responses:
            raise RuntimeError("MockLLMClient ran out of responses")
        return self._responses.pop(0)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_mock.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add llm/mock.py tests/llm/test_mock.py
git commit -m "feat(llm): MockLLMClient for testing"
```

---

### Task 4: Claude adapter

**Files:**
- Create: `llm/adapters/claude.py`
- Create: `tests/llm/test_adapter_claude.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_adapter_claude.py`:

```python
from unittest.mock import MagicMock

import pytest

from llm.adapters.claude import ClaudeClient
from llm.client import LLMError


def _fake_response(tool_name: str, tool_input: dict) -> MagicMock:
    block = MagicMock()
    block.type = "tool_use"
    block.name = tool_name
    block.input = tool_input
    response = MagicMock()
    response.content = [block]
    return response


def test_claude_client_returns_tool_input_as_dict():
    sdk = MagicMock()
    sdk.messages.create.return_value = _fake_response(
        "return_result", {"answer": 42}
    )
    client = ClaudeClient(sdk=sdk, model="claude-opus-4-7")

    result = client.chat_json(
        system="be helpful",
        user="what's the answer",
        json_schema={"type": "object", "properties": {"answer": {"type": "integer"}}},
    )

    assert result == {"answer": 42}
    call = sdk.messages.create.call_args
    assert call.kwargs["model"] == "claude-opus-4-7"
    assert call.kwargs["system"] == "be helpful"
    assert call.kwargs["tool_choice"] == {"type": "tool", "name": "return_result"}
    assert call.kwargs["tools"][0]["name"] == "return_result"


def test_claude_client_raises_when_no_tool_use_block():
    sdk = MagicMock()
    text_block = MagicMock()
    text_block.type = "text"
    response = MagicMock()
    response.content = [text_block]
    sdk.messages.create.return_value = response
    client = ClaudeClient(sdk=sdk, model="claude-opus-4-7")

    with pytest.raises(LLMError, match="no tool_use block"):
        client.chat_json("s", "u", {"type": "object"})
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_adapter_claude.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.adapters.claude'`

- [ ] **Step 3: Implement ClaudeClient**

Create `llm/adapters/claude.py`:

```python
"""Claude adapter using Anthropic tool-use for JSON output."""
from __future__ import annotations

from typing import Any

from llm.client import LLMError


class ClaudeClient:
    """LLMClient implementation backed by Anthropic's messages API.

    JSON structured output is enforced by declaring a single tool with the
    required schema and forcing the model to call it.
    """

    _TOOL_NAME = "return_result"

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "claude-opus-4-7",
        sdk: Any = None,
    ) -> None:
        if sdk is not None:
            self._sdk = sdk
        else:
            import anthropic
            self._sdk = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        response = self._sdk.messages.create(
            model=self._model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
            tools=[
                {
                    "name": self._TOOL_NAME,
                    "description": "Return the structured result.",
                    "input_schema": json_schema,
                }
            ],
            tool_choice={"type": "tool", "name": self._TOOL_NAME},
        )
        for block in response.content:
            if getattr(block, "type", None) == "tool_use" and block.name == self._TOOL_NAME:
                return dict(block.input)
        raise LLMError("Claude response contained no tool_use block")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_adapter_claude.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add llm/adapters/claude.py tests/llm/test_adapter_claude.py
git commit -m "feat(llm): Claude adapter using tool-use for JSON"
```

---

### Task 5: OpenAI adapter

**Files:**
- Create: `llm/adapters/openai_.py`
- Create: `tests/llm/test_adapter_openai.py`

Note: file is named `openai_.py` (trailing underscore) to avoid shadowing the `openai` package.

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_adapter_openai.py`:

```python
import json
from unittest.mock import MagicMock

import pytest

from llm.adapters.openai_ import OpenAIClient
from llm.client import LLMError


def _fake_response(content: str) -> MagicMock:
    choice = MagicMock()
    choice.message.content = content
    response = MagicMock()
    response.choices = [choice]
    return response


def test_openai_client_parses_json_content():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response(json.dumps({"n": 7}))
    client = OpenAIClient(sdk=sdk, model="gpt-4o-2024-11-20")

    result = client.chat_json(
        system="sys",
        user="usr",
        json_schema={"type": "object", "properties": {"n": {"type": "integer"}}},
    )

    assert result == {"n": 7}
    kwargs = sdk.chat.completions.create.call_args.kwargs
    assert kwargs["model"] == "gpt-4o-2024-11-20"
    assert kwargs["response_format"]["type"] == "json_schema"
    assert kwargs["response_format"]["json_schema"]["name"] == "result"
    assert kwargs["messages"][0] == {"role": "system", "content": "sys"}
    assert kwargs["messages"][1] == {"role": "user", "content": "usr"}


def test_openai_client_raises_on_invalid_json():
    sdk = MagicMock()
    sdk.chat.completions.create.return_value = _fake_response("not json")
    client = OpenAIClient(sdk=sdk, model="gpt-4o-2024-11-20")

    with pytest.raises(LLMError, match="invalid JSON"):
        client.chat_json("s", "u", {"type": "object"})
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_adapter_openai.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.adapters.openai_'`

- [ ] **Step 3: Implement OpenAIClient**

Create `llm/adapters/openai_.py`:

```python
"""OpenAI adapter using chat completions with response_format=json_schema."""
from __future__ import annotations

import json
from typing import Any

from llm.client import LLMError


class OpenAIClient:
    """LLMClient implementation backed by OpenAI's chat completions API."""

    def __init__(
        self,
        api_key: str | None = None,
        model: str = "gpt-4o-2024-11-20",
        sdk: Any = None,
    ) -> None:
        if sdk is not None:
            self._sdk = sdk
        else:
            import openai
            self._sdk = openai.OpenAI(api_key=api_key)
        self._model = model

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        response = self._sdk.chat.completions.create(
            model=self._model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "result",
                    "schema": json_schema,
                    "strict": True,
                },
            },
        )
        content = response.choices[0].message.content
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LLMError(f"OpenAI returned invalid JSON: {exc}") from exc
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_adapter_openai.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add llm/adapters/openai_.py tests/llm/test_adapter_openai.py
git commit -m "feat(llm): OpenAI adapter using response_format json_schema"
```

---

### Task 6: Gemini adapter

**Files:**
- Create: `llm/adapters/gemini.py`
- Create: `tests/llm/test_adapter_gemini.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_adapter_gemini.py`:

```python
import json
from unittest.mock import MagicMock

import pytest

from llm.adapters.gemini import GeminiClient
from llm.client import LLMError


def _fake_response(text: str) -> MagicMock:
    response = MagicMock()
    response.text = text
    return response


def test_gemini_client_parses_json_text():
    model = MagicMock()
    model.generate_content.return_value = _fake_response(json.dumps({"v": "ok"}))
    client = GeminiClient(model_obj=model, model_name="gemini-2.5-pro")

    result = client.chat_json(
        system="sys",
        user="usr",
        json_schema={"type": "object", "properties": {"v": {"type": "string"}}},
    )

    assert result == {"v": "ok"}
    call = model.generate_content.call_args
    combined = call.args[0][0]
    assert "sys" in combined
    assert "usr" in combined
    cfg = call.kwargs["generation_config"]
    assert cfg["response_mime_type"] == "application/json"
    assert cfg["response_schema"] == {
        "type": "object",
        "properties": {"v": {"type": "string"}},
    }


def test_gemini_client_raises_on_invalid_json():
    model = MagicMock()
    model.generate_content.return_value = _fake_response("oops")
    client = GeminiClient(model_obj=model, model_name="gemini-2.5-pro")

    with pytest.raises(LLMError, match="invalid JSON"):
        client.chat_json("s", "u", {"type": "object"})
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_adapter_gemini.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.adapters.gemini'`

- [ ] **Step 3: Implement GeminiClient**

Create `llm/adapters/gemini.py`:

```python
"""Gemini adapter using generate_content with response_schema."""
from __future__ import annotations

import json
from typing import Any

from llm.client import LLMError


class GeminiClient:
    """LLMClient implementation backed by Google's generative AI SDK."""

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-pro",
        model_obj: Any = None,
    ) -> None:
        if model_obj is not None:
            self._model = model_obj
        else:
            import google.generativeai as genai
            genai.configure(api_key=api_key)
            self._model = genai.GenerativeModel(model_name)
        self._model_name = model_name

    def chat_json(
        self,
        system: str,
        user: str,
        json_schema: dict[str, Any],
        max_tokens: int = 4096,
    ) -> dict[str, Any]:
        combined = f"{system}\n\n{user}"
        response = self._model.generate_content(
            [combined],
            generation_config={
                "response_mime_type": "application/json",
                "response_schema": json_schema,
                "max_output_tokens": max_tokens,
            },
        )
        try:
            return json.loads(response.text)
        except json.JSONDecodeError as exc:
            raise LLMError(f"Gemini returned invalid JSON: {exc}") from exc
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_adapter_gemini.py -v`
Expected: 2 passed

- [ ] **Step 5: Commit**

```bash
git add llm/adapters/gemini.py tests/llm/test_adapter_gemini.py
git commit -m "feat(llm): Gemini adapter using response_schema"
```

---

### Task 7: Provider factory

**Files:**
- Create: `llm/factory.py`
- Create: `tests/llm/test_factory.py`

- [ ] **Step 1: Write the failing test**

Create `tests/llm/test_factory.py`:

```python
import pytest

from llm.adapters.claude import ClaudeClient
from llm.adapters.gemini import GeminiClient
from llm.adapters.openai_ import OpenAIClient
from llm.factory import make_client


def test_factory_selects_claude(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    client = make_client("claude")
    assert isinstance(client, ClaudeClient)


def test_factory_selects_openai(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = make_client("openai")
    assert isinstance(client, OpenAIClient)


def test_factory_selects_gemini(monkeypatch):
    monkeypatch.setenv("GEMINI_API_KEY", "sk-test")
    client = make_client("gemini")
    assert isinstance(client, GeminiClient)


def test_factory_reads_env_default(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    client = make_client()
    assert isinstance(client, OpenAIClient)


def test_factory_rejects_unknown_provider():
    with pytest.raises(ValueError, match="unknown provider"):
        make_client("bard")


def test_factory_errors_when_key_missing(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(KeyError, match="ANTHROPIC_API_KEY"):
        make_client("claude")
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/llm/test_factory.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'llm.factory'`

- [ ] **Step 3: Implement the factory**

Create `llm/factory.py`:

```python
"""Environment-driven factory for selecting an LLMClient implementation."""
from __future__ import annotations

import os

from llm.client import LLMClient


def make_client(provider: str | None = None) -> LLMClient:
    """Return an LLMClient for the given provider.

    Provider is selected in this order:
    1. Explicit `provider` argument.
    2. `LLM_PROVIDER` environment variable.
    3. Defaults to "claude".

    Raises:
        ValueError: if the provider name is not recognized.
        KeyError: if the required API key env var is not set.
    """
    name = (provider or os.environ.get("LLM_PROVIDER", "claude")).lower()

    if name == "claude":
        from llm.adapters.claude import ClaudeClient
        return ClaudeClient(api_key=os.environ["ANTHROPIC_API_KEY"])
    if name == "openai":
        from llm.adapters.openai_ import OpenAIClient
        return OpenAIClient(api_key=os.environ["OPENAI_API_KEY"])
    if name == "gemini":
        from llm.adapters.gemini import GeminiClient
        return GeminiClient(api_key=os.environ["GEMINI_API_KEY"])
    raise ValueError(f"unknown provider: {name}")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/llm/test_factory.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add llm/factory.py tests/llm/test_factory.py
git commit -m "feat(llm): provider factory (env + explicit selection)"
```

---

## Part B — Outline Schema and Storage

### Task 8: OutlineEntry and DocumentOutline schema

**Files:**
- Create: `pdf_pipeline/outline/schema.py`
- Create: `tests/outline/test_schema.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_schema.py`:

```python
import pytest

from pdf_pipeline.outline.schema import (
    DocumentOutline,
    OutlineEntry,
    SOURCE_TYPES,
)


def test_outline_entry_stores_fields():
    entry = OutlineEntry(
        id="ch1",
        title="Introduction",
        level=1,
        parent_id=None,
        start_pdf_page=17,
        end_pdf_page=32,
        printed_page="1",
        confidence=0.95,
        source="anchor_scan",
    )
    assert entry.id == "ch1"
    assert entry.title == "Introduction"
    assert entry.source == "anchor_scan"


def test_outline_entry_rejects_unknown_source():
    with pytest.raises(ValueError, match="unknown source"):
        OutlineEntry(
            id="x", title="x", level=1, parent_id=None,
            start_pdf_page=1, end_pdf_page=2,
            printed_page=None, confidence=1.0, source="made_up",
        )


def test_outline_entry_rejects_confidence_out_of_range():
    with pytest.raises(ValueError, match="confidence"):
        OutlineEntry(
            id="x", title="x", level=1, parent_id=None,
            start_pdf_page=None, end_pdf_page=None,
            printed_page=None, confidence=1.5, source="unresolved",
        )


def test_unresolved_entry_allows_null_pages():
    entry = OutlineEntry(
        id="ch3", title="Methods", level=1, parent_id=None,
        start_pdf_page=None, end_pdf_page=None,
        printed_page="47", confidence=0.0, source="unresolved",
    )
    assert entry.start_pdf_page is None


def test_document_outline_holds_entries():
    entry = OutlineEntry(
        id="ch1", title="A", level=1, parent_id=None,
        start_pdf_page=1, end_pdf_page=10,
        printed_page="1", confidence=1.0, source="pdf_outline",
    )
    outline = DocumentOutline(source_id="doc-42", version=1, entries=[entry])
    assert outline.source_id == "doc-42"
    assert outline.version == 1
    assert outline.entries == [entry]


def test_source_types_enumerated():
    assert "pdf_outline" in SOURCE_TYPES
    assert "page_labels" in SOURCE_TYPES
    assert "anchor_scan" in SOURCE_TYPES
    assert "unresolved" in SOURCE_TYPES
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.schema'`

- [ ] **Step 3: Implement the schema**

Create `pdf_pipeline/outline/schema.py`:

```python
"""Schema types for document outline extraction."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

SourceType = Literal["pdf_outline", "page_labels", "anchor_scan", "unresolved"]
SOURCE_TYPES: frozenset[str] = frozenset(
    {"pdf_outline", "page_labels", "anchor_scan", "unresolved"}
)


@dataclass(frozen=True)
class OutlineEntry:
    id: str
    title: str
    level: int
    parent_id: str | None
    start_pdf_page: int | None
    end_pdf_page: int | None
    printed_page: str | None
    confidence: float
    source: SourceType

    def __post_init__(self) -> None:
        if self.source not in SOURCE_TYPES:
            raise ValueError(f"unknown source: {self.source}")
        if not 0.0 <= self.confidence <= 1.0:
            raise ValueError(
                f"confidence must be in [0.0, 1.0], got {self.confidence}"
            )


@dataclass(frozen=True)
class DocumentOutline:
    source_id: str
    version: int
    entries: list[OutlineEntry] = field(default_factory=list)
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_schema.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/schema.py tests/outline/test_schema.py
git commit -m "feat(outline): OutlineEntry and DocumentOutline schema"
```

---

## Part C — Layer 1: Structural Metadata

### Task 9: /Outlines (bookmarks) reader

**Files:**
- Create: `pdf_pipeline/outline/metadata.py`
- Create: `tests/outline/test_metadata_outlines.py`
- Create: `tests/outline/fixtures/README.md`

For fixtures: committing PDF binaries into the repo is fine for small (<200KB) test samples. The README documents how each fixture was generated.

- [ ] **Step 1: Create fixture README**

Create `tests/outline/fixtures/README.md`:

```markdown
# Outline fixtures

Small PDFs used to test the outline extractor. Each fixture is checked in
because regeneration is cumbersome and the files are under ~200KB.

| File | How it was made |
|------|-----------------|
| `born_digital_with_outlines.pdf` | 30-page ReportLab PDF with 3 chapters, each registered via `canvas.bookmarkPage` + `canvas.addOutlineEntry`. See `make_fixtures.py` at the bottom of this README. |
| `page_labels_only.pdf` | Same content as above, but regenerated with `/PageLabels` set to 5 Roman + 25 Arabic pages, and outlines stripped. |
| `article_no_toc.pdf` | 10-page ReportLab PDF with body text only, no outline, no labels, no TOC page. |
| `scanned_book_fragment.pdf` | 8-page PDF of page-images from an out-of-copyright text (Federalist Papers no. 10, Project Gutenberg). Simulates a scanned book. |

## Regenerating

See `tests/outline/fixtures/make_fixtures.py` for the generator script. Run
`python tests/outline/fixtures/make_fixtures.py` to rebuild them.
```

(The `make_fixtures.py` generator is scoped to Task 23 — the fixture PDFs used in earlier unit tests can be minimal and generated inline in test setup via a small helper. See Step 2 of this task.)

- [ ] **Step 2: Write the failing test**

Create `tests/outline/test_metadata_outlines.py`:

```python
"""Tests for Layer 1: /Outlines reader.

These tests build tiny in-memory PDFs with pypdf so we don't need pre-built
fixture binaries for basic outline-parsing coverage.
"""
from __future__ import annotations

from pathlib import Path

import pytest
from pypdf import PdfWriter

from pdf_pipeline.outline.metadata import read_pdf_outlines


def _build_pdf_with_outline(tmp_path: Path, outline: list[tuple[str, int, list]]) -> Path:
    """Create a PDF with `outline` entries; each is (title, pdf_page_1idx, children)."""
    writer = PdfWriter()
    # Need enough pages to cover the deepest destination.
    max_page = 0
    def _collect_max(items: list[tuple[str, int, list]]) -> None:
        nonlocal max_page
        for title, page, children in items:
            max_page = max(max_page, page)
            _collect_max(children)
    _collect_max(outline)
    for _ in range(max_page):
        writer.add_blank_page(width=612, height=792)

    def _add(items: list[tuple[str, int, list]], parent=None) -> None:
        for title, page, children in items:
            bookmark = writer.add_outline_item(title, page - 1, parent=parent)
            if children:
                _add(children, parent=bookmark)

    _add(outline)
    path = tmp_path / "built.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_reads_flat_outline(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5, []), ("Chapter 2", 10, []), ("Chapter 3", 20, [])],
    )
    entries = read_pdf_outlines(str(pdf))
    assert len(entries) == 3
    assert [e.title for e in entries] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [e.start_pdf_page for e in entries] == [5, 10, 20]
    assert all(e.level == 1 for e in entries)
    assert all(e.parent_id is None for e in entries)
    assert all(e.source == "pdf_outline" for e in entries)
    assert all(e.confidence == 1.0 for e in entries)


def test_reads_nested_outline(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [
            ("Chapter 1", 5, [
                ("Section 1.1", 6, []),
                ("Section 1.2", 8, []),
            ]),
            ("Chapter 2", 10, []),
        ],
    )
    entries = read_pdf_outlines(str(pdf))
    assert len(entries) == 4
    titles = [e.title for e in entries]
    assert titles == ["Chapter 1", "Section 1.1", "Section 1.2", "Chapter 2"]
    levels = [e.level for e in entries]
    assert levels == [1, 2, 2, 1]
    ch1 = entries[0]
    s11 = entries[1]
    s12 = entries[2]
    assert s11.parent_id == ch1.id
    assert s12.parent_id == ch1.id


def test_returns_empty_when_no_outline(tmp_path: Path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / "plain.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    assert read_pdf_outlines(str(path)) == []


def test_ids_are_stable_and_unique(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5, [("Section 1.1", 6, [])]), ("Chapter 2", 10, [])],
    )
    entries = read_pdf_outlines(str(pdf))
    ids = [e.id for e in entries]
    assert len(ids) == len(set(ids))
    # Re-reading should produce identical IDs.
    entries_again = read_pdf_outlines(str(pdf))
    assert [e.id for e in entries_again] == ids
```

- [ ] **Step 3: Run test, expect failure**

Run: `pytest tests/outline/test_metadata_outlines.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.metadata'`

- [ ] **Step 4: Implement the reader**

Create `pdf_pipeline/outline/metadata.py`:

```python
"""Layer 1: read structural PDF metadata (/Outlines, /PageLabels)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from pypdf import PdfReader

from pdf_pipeline.outline.schema import OutlineEntry


def read_pdf_outlines(pdf_path: str | Path) -> list[OutlineEntry]:
    """Extract the embedded PDF outline (/Outlines) as OutlineEntry records.

    Returns an empty list if the PDF has no outline. End pages are left as
    None; Layer 4 (range_assignment) fills them in.
    """
    reader = PdfReader(str(pdf_path))
    outline_root = reader.outline
    if not outline_root:
        return []

    entries: list[OutlineEntry] = []
    _walk(outline_root, reader, entries, level=1, parent_id=None, path_prefix="o")
    return entries


def _walk(
    items: list[Any],
    reader: PdfReader,
    entries: list[OutlineEntry],
    level: int,
    parent_id: str | None,
    path_prefix: str,
) -> None:
    """Walk pypdf's nested outline list.

    pypdf represents the outline as a list where top-level entries are
    Destination-like objects and a nested list immediately following an entry
    contains that entry's children.
    """
    i = 0
    while i < len(items):
        item = items[i]
        if isinstance(item, list):
            # Children without a parent - skip defensively.
            i += 1
            continue

        entry_id = f"{path_prefix}{len(entries)}"
        title = str(getattr(item, "title", "")) or "(untitled)"
        try:
            page_idx = reader.get_destination_page_number(item)
        except Exception:
            i += 1
            continue
        pdf_page = page_idx + 1  # 1-indexed

        entry = OutlineEntry(
            id=entry_id,
            title=title,
            level=level,
            parent_id=parent_id,
            start_pdf_page=pdf_page,
            end_pdf_page=None,
            printed_page=None,
            confidence=1.0,
            source="pdf_outline",
        )
        entries.append(entry)

        if i + 1 < len(items) and isinstance(items[i + 1], list):
            _walk(items[i + 1], reader, entries, level + 1, entry.id, path_prefix)
            i += 2
        else:
            i += 1
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/outline/test_metadata_outlines.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/metadata.py tests/outline/test_metadata_outlines.py tests/outline/fixtures/README.md
git commit -m "feat(outline): Layer 1 /Outlines reader"
```

---

### Task 10: /PageLabels reader and printed→pdf_page resolver

**Files:**
- Modify: `pdf_pipeline/outline/metadata.py`
- Create: `tests/outline/test_metadata_page_labels.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_metadata_page_labels.py`:

```python
from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter
from pypdf.generic import (
    ArrayObject,
    DictionaryObject,
    NameObject,
    NumberObject,
)

from pdf_pipeline.outline.metadata import read_page_labels, resolve_printed_to_pdf_page


def _write_pdf(tmp_path: Path, labels_nums: list) -> Path:
    writer = PdfWriter()
    for _ in range(30):
        writer.add_blank_page(width=612, height=792)
    labels_dict = DictionaryObject({NameObject("/Nums"): ArrayObject(labels_nums)})
    writer._root_object[NameObject("/PageLabels")] = labels_dict
    path = tmp_path / "labelled.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_reads_arabic_labels(tmp_path: Path):
    # Pages 0..29 all arabic starting from 1.
    nums = [
        NumberObject(0),
        DictionaryObject({NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(1)}),
    ]
    pdf = _write_pdf(tmp_path, nums)
    labels = read_page_labels(str(pdf))
    assert labels[1] == "1"
    assert labels[10] == "10"
    assert labels[30] == "30"


def test_reads_roman_then_arabic_labels(tmp_path: Path):
    # Pages 0..4 roman (i-v), pages 5..29 arabic starting 1.
    nums = [
        NumberObject(0),
        DictionaryObject({NameObject("/S"): NameObject("/r")}),
        NumberObject(5),
        DictionaryObject({NameObject("/S"): NameObject("/D"), NameObject("/St"): NumberObject(1)}),
    ]
    pdf = _write_pdf(tmp_path, nums)
    labels = read_page_labels(str(pdf))
    assert labels[1] == "i"
    assert labels[5] == "v"
    assert labels[6] == "1"
    assert labels[30] == "25"


def test_returns_none_when_absent(tmp_path: Path):
    writer = PdfWriter()
    for _ in range(3):
        writer.add_blank_page(width=612, height=792)
    path = tmp_path / "nolabel.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    assert read_page_labels(str(path)) is None


def test_resolve_printed_to_pdf_page():
    labels = {1: "i", 2: "ii", 3: "iii", 4: "1", 5: "2", 6: "3"}
    assert resolve_printed_to_pdf_page("1", labels) == 4
    assert resolve_printed_to_pdf_page("iii", labels) == 3
    assert resolve_printed_to_pdf_page("99", labels) is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_metadata_page_labels.py -v`
Expected: FAIL — `ImportError: cannot import name 'read_page_labels'`

- [ ] **Step 3: Implement the readers**

Append to `pdf_pipeline/outline/metadata.py`:

```python
def read_page_labels(pdf_path: str | Path) -> dict[int, str] | None:
    """Return a mapping from pdf_page (1-indexed) to printed label string.

    Reads the PDF's /PageLabels dictionary per the PDF 1.7 spec §12.4.2.
    Returns None if /PageLabels is absent.
    """
    reader = PdfReader(str(pdf_path))
    root = reader.trailer["/Root"]
    if "/PageLabels" not in root:
        return None
    nums = root["/PageLabels"]["/Nums"]

    # /Nums is [start_idx1, dict1, start_idx2, dict2, ...] sorted ascending.
    segments: list[tuple[int, dict]] = []
    for i in range(0, len(nums), 2):
        start_idx = int(nums[i])
        segment_dict = nums[i + 1]
        segments.append((start_idx, dict(segment_dict)))

    page_count = len(reader.pages)
    labels: dict[int, str] = {}

    for seg_i, (start_idx, seg) in enumerate(segments):
        next_start = segments[seg_i + 1][0] if seg_i + 1 < len(segments) else page_count
        style = seg.get("/S")
        style_name = str(style) if style is not None else None
        prefix = str(seg.get("/P", ""))
        first_num = int(seg.get("/St", 1))

        for offset, page_idx_0 in enumerate(range(start_idx, next_start)):
            number = first_num + offset
            label = _render_label(style_name, number, prefix)
            labels[page_idx_0 + 1] = label  # 1-indexed

    return labels


def resolve_printed_to_pdf_page(printed: str, labels: dict[int, str]) -> int | None:
    """Return the pdf_page (1-indexed) for the given printed label, or None."""
    target = printed.strip().lower()
    for pdf_page, label in labels.items():
        if label.strip().lower() == target:
            return pdf_page
    return None


def _render_label(style: str | None, number: int, prefix: str) -> str:
    """Render a page label per /PageLabels style tokens."""
    if style is None:
        return f"{prefix}" if prefix else ""
    s = style.lstrip("/")
    if s == "D":
        return f"{prefix}{number}"
    if s == "R":
        return f"{prefix}{_to_roman(number).upper()}"
    if s == "r":
        return f"{prefix}{_to_roman(number).lower()}"
    if s == "A":
        return f"{prefix}{_to_alpha(number).upper()}"
    if s == "a":
        return f"{prefix}{_to_alpha(number).lower()}"
    return f"{prefix}{number}"


def _to_roman(n: int) -> str:
    vals = [
        (1000, "m"), (900, "cm"), (500, "d"), (400, "cd"),
        (100, "c"), (90, "xc"), (50, "l"), (40, "xl"),
        (10, "x"), (9, "ix"), (5, "v"), (4, "iv"), (1, "i"),
    ]
    out = []
    for v, s in vals:
        while n >= v:
            out.append(s)
            n -= v
    return "".join(out)


def _to_alpha(n: int) -> str:
    # 1->a, 26->z, 27->aa, 28->bb, ... per PDF spec.
    if n < 1:
        return ""
    letter = chr(ord("a") + (n - 1) % 26)
    repeat = (n - 1) // 26 + 1
    return letter * repeat
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_metadata_page_labels.py -v`
Expected: 4 passed

- [ ] **Step 5: Also run previous metadata tests to catch regressions**

Run: `pytest tests/outline/test_metadata_outlines.py tests/outline/test_metadata_page_labels.py -v`
Expected: 8 passed

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/metadata.py tests/outline/test_metadata_page_labels.py
git commit -m "feat(outline): Layer 1 /PageLabels reader and printed→pdf resolver"
```

---

## Part D — Layer 2: LLM TOC Extraction

### Task 11: Heuristic TOC pre-filter

**Files:**
- Create: `pdf_pipeline/outline/prefilter.py`
- Create: `tests/outline/test_prefilter.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_prefilter.py`:

```python
from pdf_pipeline.outline.prefilter import looks_like_toc


def test_detects_contents_heading():
    text = "Contents\n\nChapter 1 ....... 1\nChapter 2 ....... 15"
    assert looks_like_toc(text) is True


def test_detects_table_of_contents_heading():
    assert looks_like_toc("TABLE OF CONTENTS\n\nIntroduction ... 1") is True


def test_detects_dot_leader_lines():
    text = "\n".join(
        [
            "Preface ..................... 3",
            "Introduction ............... 7",
            "Chapter 1: Origins ......... 12",
            "Chapter 2: Methods ......... 45",
        ]
    )
    assert looks_like_toc(text) is True


def test_detects_many_short_lines_ending_in_numbers():
    lines = [f"Section {i}    {i * 3}" for i in range(1, 12)]
    text = "\n".join(lines)
    assert looks_like_toc(text) is True


def test_rejects_narrative_text():
    text = (
        "This chapter explores the nature of algorithms. We begin by "
        "considering the question of what it means for a computation to "
        "terminate and how we might measure its complexity."
    )
    assert looks_like_toc(text) is False


def test_rejects_empty_text():
    assert looks_like_toc("") is False
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_prefilter.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.prefilter'`

- [ ] **Step 3: Implement the pre-filter**

Create `pdf_pipeline/outline/prefilter.py`:

```python
"""Cheap heuristic to detect whether a page looks like part of a TOC."""
from __future__ import annotations

import re

_HEADING_PATTERN = re.compile(
    r"^\s*(table of contents|contents)\s*$",
    re.IGNORECASE | re.MULTILINE,
)
_DOT_LEADER_PATTERN = re.compile(r"\.{3,}\s*\d+\s*$", re.MULTILINE)
_SHORT_LINE_NUM_PATTERN = re.compile(r"^\s*\S.{0,60}?\s+\d+\s*$", re.MULTILINE)


def looks_like_toc(text: str) -> bool:
    """Heuristically decide whether `text` looks like TOC content.

    Triggers on any of: a "Contents"/"Table of Contents" heading, three or
    more dot-leader lines, or ten or more short lines that end in a number.
    """
    if not text or not text.strip():
        return False

    if _HEADING_PATTERN.search(text):
        return True

    if len(_DOT_LEADER_PATTERN.findall(text)) >= 3:
        return True

    if len(_SHORT_LINE_NUM_PATTERN.findall(text)) >= 10:
        return True

    return False
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_prefilter.py -v`
Expected: 6 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/prefilter.py tests/outline/test_prefilter.py
git commit -m "feat(outline): heuristic TOC pre-filter"
```

---

### Task 12: Per-page text source (text-first, OCR fallback)

**Files:**
- Create: `pdf_pipeline/outline/page_text.py`
- Create: `tests/outline/test_page_text.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_page_text.py`:

```python
from unittest.mock import MagicMock

from pdf_pipeline.outline.page_text import PageTextSource, PageTextRecord


def test_uses_text_when_present():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "hello world"
    ocr_extractor = MagicMock()

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=3)

    assert record == PageTextRecord(pdf_page=3, text="hello world", used_ocr=False)
    ocr_extractor.extract_page_text.assert_not_called()


def test_falls_back_to_ocr_when_text_empty():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = ""
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = "ocr said hi"

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=7)

    assert record == PageTextRecord(pdf_page=7, text="ocr said hi", used_ocr=True)


def test_falls_back_when_text_is_below_min_chars():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "x"
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = "full ocr text here"

    src = PageTextSource(
        text_extractor=text_extractor,
        ocr_extractor=ocr_extractor,
        min_chars=5,
    )
    record = src.get("some.pdf", pdf_page=2)
    assert record.used_ocr is True
    assert record.text == "full ocr text here"


def test_works_without_ocr_extractor_when_text_present():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = "enough text here"

    src = PageTextSource(text_extractor=text_extractor, ocr_extractor=None, min_chars=5)
    record = src.get("some.pdf", pdf_page=1)
    assert record.used_ocr is False
    assert record.text == "enough text here"


def test_returns_empty_record_when_both_fail():
    text_extractor = MagicMock()
    text_extractor.extract_page_text.return_value = ""
    ocr_extractor = MagicMock()
    ocr_extractor.extract_page_text.return_value = ""

    src = PageTextSource(text_extractor=text_extractor, ocr_extractor=ocr_extractor, min_chars=5)
    record = src.get("some.pdf", pdf_page=1)
    assert record == PageTextRecord(pdf_page=1, text="", used_ocr=True)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_page_text.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.page_text'`

- [ ] **Step 3: Implement PageTextSource**

Create `pdf_pipeline/outline/page_text.py`:

```python
"""Per-page text source with text-extraction first and OCR fallback."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class PageTextRecord:
    pdf_page: int
    text: str
    used_ocr: bool


class _SinglePageExtractor(Protocol):
    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str: ...


class PageTextSource:
    """Returns the best available text for a given pdf_page.

    Prefers text extraction; falls back to OCR when extracted text is empty
    or shorter than `min_chars`. If both yield nothing, returns an empty
    PageTextRecord so callers can continue without branching on None.
    """

    def __init__(
        self,
        text_extractor: _SinglePageExtractor,
        ocr_extractor: _SinglePageExtractor | None,
        min_chars: int = 20,
    ) -> None:
        self._text = text_extractor
        self._ocr = ocr_extractor
        self._min_chars = min_chars

    def get(self, pdf_path: str, pdf_page: int) -> PageTextRecord:
        text = self._text.extract_page_text(pdf_path, pdf_page) or ""
        if len(text.strip()) >= self._min_chars:
            return PageTextRecord(pdf_page=pdf_page, text=text, used_ocr=False)
        if self._ocr is None:
            return PageTextRecord(pdf_page=pdf_page, text=text, used_ocr=False)
        ocr_text = self._ocr.extract_page_text(pdf_path, pdf_page) or ""
        return PageTextRecord(pdf_page=pdf_page, text=ocr_text, used_ocr=True)
```

- [ ] **Step 4: Add a single-page text extractor shim**

The existing `PyPdfExtractor` extracts a whole document; we need a per-page helper. Check `pdf_pipeline/extractors/pypdf_extractor.py` for the current API. If it doesn't already expose per-page extraction, add a thin adapter (at the bottom of `pdf_pipeline/outline/page_text.py`):

```python
from pypdf import PdfReader


class PyPdfPageExtractor:
    """Minimal per-page text extractor wrapping pypdf directly."""

    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str:
        reader = PdfReader(pdf_path)
        return reader.pages[pdf_page - 1].extract_text() or ""
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/outline/test_page_text.py -v`
Expected: 5 passed

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/page_text.py tests/outline/test_page_text.py
git commit -m "feat(outline): per-page text source with OCR fallback"
```

---

### Task 13: Layer 2 prompts and JSON schema

**Files:**
- Create: `pdf_pipeline/outline/prompts.py`
- Create: `tests/outline/test_prompts.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_prompts.py`:

```python
import json

import jsonschema

from pdf_pipeline.outline.prompts import (
    TOC_EXTRACTION_SCHEMA,
    TOC_SYSTEM_PROMPT,
    build_user_message,
)


def test_system_prompt_instructs_not_to_trust_inline_numbers():
    assert "pdf_page" in TOC_SYSTEM_PROMPT
    assert "never" in TOC_SYSTEM_PROMPT.lower() or "only" in TOC_SYSTEM_PROMPT.lower()


def test_user_message_contains_pdf_pages_json():
    pages = [
        {"pdf_page": 8, "text": "Contents\nChapter 1 ... 1"},
        {"pdf_page": 9, "text": "Chapter 2 ... 15"},
    ]
    msg = build_user_message(pages)
    payload = json.loads(msg)
    assert payload == {"pages": pages}


def test_schema_accepts_valid_response():
    response = {
        "pages": [
            {"pdf_page": 8, "is_toc": True},
            {"pdf_page": 9, "is_toc": True},
        ],
        "entries": [
            {"title": "Chapter 1", "level": 1, "printed_page": "1"},
            {"title": "Chapter 2", "level": 1, "printed_page": "15"},
        ],
    }
    jsonschema.validate(response, TOC_EXTRACTION_SCHEMA)


def test_schema_rejects_missing_fields():
    bad = {"pages": [{"pdf_page": 8}]}
    try:
        jsonschema.validate(bad, TOC_EXTRACTION_SCHEMA)
    except jsonschema.ValidationError:
        return
    raise AssertionError("expected validation error")
```

- [ ] **Step 2: Ensure `jsonschema` is installed**

Run: `pip install jsonschema` (add it to the `outline` optional-dep in `pyproject.toml` if missing).

- [ ] **Step 3: Run test, expect failure**

Run: `pytest tests/outline/test_prompts.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.prompts'`

- [ ] **Step 4: Implement prompts and schema**

Create `pdf_pipeline/outline/prompts.py`:

```python
"""System prompt and JSON schema for Layer 2 TOC extraction."""
from __future__ import annotations

import json
from typing import Any

TOC_SYSTEM_PROMPT = """You extract Table of Contents entries from book pages.

You will receive a JSON object of the form:
  {"pages": [{"pdf_page": <int>, "text": <string>}, ...]}

Your job, for each input page:
  1. Decide whether the page is part of the Table of Contents (is_toc).
  2. If the overall set of pages contains TOC entries, list each entry with
     its title, hierarchy level (1 = chapter, 2 = section, 3 = subsection,
     ...), and the printed_page string exactly as written in the TOC.

Rules:
  - pdf_page values in your response MUST come from the JSON input. Never
    infer them from numbers that appear inside page text.
  - printed_page is the page-number label as printed in the TOC (e.g.
    "1", "iv", "A-3"). Preserve it verbatim as a string.
  - level is 1 for top-level chapters/parts, incrementing by 1 for each
    nested subsection.
  - If a page does not contain TOC content, mark is_toc = false.
  - If no TOC entries appear in any input page, return "entries": [].
"""

TOC_EXTRACTION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["pages", "entries"],
    "properties": {
        "pages": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["pdf_page", "is_toc"],
                "properties": {
                    "pdf_page": {"type": "integer"},
                    "is_toc": {"type": "boolean"},
                },
            },
        },
        "entries": {
            "type": "array",
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["title", "level", "printed_page"],
                "properties": {
                    "title": {"type": "string"},
                    "level": {"type": "integer", "minimum": 1},
                    "printed_page": {"type": "string"},
                },
            },
        },
    },
}


def build_user_message(pages: list[dict[str, Any]]) -> str:
    """Serialize the input pages payload as the user turn of the prompt."""
    return json.dumps({"pages": pages}, ensure_ascii=False)
```

- [ ] **Step 5: Run tests, expect pass**

Run: `pytest tests/outline/test_prompts.py -v`
Expected: 4 passed

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/prompts.py tests/outline/test_prompts.py pyproject.toml
git commit -m "feat(outline): Layer 2 system prompt and JSON schema"
```

---

### Task 14: Layer 2 chunked TOC extraction

**Files:**
- Create: `pdf_pipeline/outline/entry_extraction.py`
- Create: `tests/outline/test_entry_extraction.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_entry_extraction.py`:

```python
from __future__ import annotations

from pdf_pipeline.outline.entry_extraction import RawEntry, extract_toc_entries
from llm.mock import MockLLMClient


def _pages(start: int, count: int, text: str = "body") -> list[dict]:
    return [{"pdf_page": start + i, "text": text} for i in range(count)]


def test_chunk_math_ceil():
    # 13 pages, chunk_size 5 => 3 chunks (5, 5, 3).
    # Pre-seed 3 empty responses so the call count is bounded.
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(11, 14)], "entries": []},
    ]
    client = MockLLMClient(responses=responses)

    pages = _pages(1, 13)
    entries = extract_toc_entries(pages, client, chunk_size=5)

    assert entries == []
    assert len(client.calls) == 3


def test_stops_after_toc_block_ends():
    # chunk 1: no TOC. chunk 2: TOC with 2 entries. chunk 3: no TOC -> stop.
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {
            "pages": [
                {"pdf_page": 6, "is_toc": True},
                {"pdf_page": 7, "is_toc": True},
                {"pdf_page": 8, "is_toc": False},
                {"pdf_page": 9, "is_toc": False},
                {"pdf_page": 10, "is_toc": False},
            ],
            "entries": [
                {"title": "Chapter 1: Origins", "level": 1, "printed_page": "1"},
                {"title": "Chapter 2: Methods", "level": 1, "printed_page": "15"},
            ],
        },
        # Should NOT be called because the block ended within chunk 2.
    ]
    client = MockLLMClient(responses=responses)

    pages = _pages(1, 15)
    entries = extract_toc_entries(pages, client, chunk_size=5)

    assert len(entries) == 2
    assert entries[0] == RawEntry(title="Chapter 1: Origins", level=1, printed_page="1")
    assert len(client.calls) == 2


def test_spans_chunk_boundary():
    # chunk 1 ends with TOC. chunk 2 continues TOC and ends block.
    responses = [
        {
            "pages": [
                {"pdf_page": 1, "is_toc": False},
                {"pdf_page": 2, "is_toc": False},
                {"pdf_page": 3, "is_toc": True},
                {"pdf_page": 4, "is_toc": True},
                {"pdf_page": 5, "is_toc": True},
            ],
            "entries": [
                {"title": "Preface", "level": 1, "printed_page": "ix"},
                {"title": "Ch 1", "level": 1, "printed_page": "1"},
            ],
        },
        {
            "pages": [
                {"pdf_page": 6, "is_toc": True},
                {"pdf_page": 7, "is_toc": False},
                {"pdf_page": 8, "is_toc": False},
                {"pdf_page": 9, "is_toc": False},
                {"pdf_page": 10, "is_toc": False},
            ],
            "entries": [
                {"title": "Ch 2", "level": 1, "printed_page": "25"},
            ],
        },
    ]
    client = MockLLMClient(responses=responses)
    entries = extract_toc_entries(_pages(1, 10), client, chunk_size=5)

    titles = [e.title for e in entries]
    assert titles == ["Preface", "Ch 1", "Ch 2"]


def test_returns_empty_when_no_toc_ever_seen():
    responses = [
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(1, 6)], "entries": []},
        {"pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)], "entries": []},
    ]
    client = MockLLMClient(responses=responses)
    entries = extract_toc_entries(_pages(1, 10), client, chunk_size=5)
    assert entries == []
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_entry_extraction.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.entry_extraction'`

- [ ] **Step 3: Implement chunked extraction**

Create `pdf_pipeline/outline/entry_extraction.py`:

```python
"""Layer 2: LLM-driven TOC entry extraction with chunked, bounded scanning."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from llm.client import LLMClient
from pdf_pipeline.outline.prompts import (
    TOC_EXTRACTION_SCHEMA,
    TOC_SYSTEM_PROMPT,
    build_user_message,
)


@dataclass(frozen=True)
class RawEntry:
    title: str
    level: int
    printed_page: str


def extract_toc_entries(
    pages: list[dict[str, Any]],
    client: LLMClient,
    chunk_size: int = 5,
    max_tokens: int = 4096,
) -> list[RawEntry]:
    """Run chunked TOC extraction over the given pages.

    - Chunks the pages using ceil(len / chunk_size).
    - Stops at the first chunk containing zero TOC pages AFTER at least one
      TOC page has been seen in a prior chunk.
    - Returns the merged list of raw entries in chunk order.
    """
    if not pages:
        return []

    entries: list[RawEntry] = []
    seen_toc = False
    num_chunks = math.ceil(len(pages) / chunk_size)

    for i in range(num_chunks):
        chunk = pages[i * chunk_size : (i + 1) * chunk_size]
        response = client.chat_json(
            system=TOC_SYSTEM_PROMPT,
            user=build_user_message(chunk),
            json_schema=TOC_EXTRACTION_SCHEMA,
            max_tokens=max_tokens,
        )
        chunk_has_toc = any(p.get("is_toc") for p in response.get("pages", []))
        for raw in response.get("entries", []):
            entries.append(
                RawEntry(
                    title=str(raw["title"]),
                    level=int(raw["level"]),
                    printed_page=str(raw["printed_page"]),
                )
            )

        if seen_toc and not chunk_has_toc:
            break
        if chunk_has_toc:
            seen_toc = True

    return entries
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_entry_extraction.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/entry_extraction.py tests/outline/test_entry_extraction.py
git commit -m "feat(outline): Layer 2 chunked LLM TOC extraction"
```

---

## Part E — Layer 3: Anchor Scan

### Task 15: Anchor candidate selection

**Files:**
- Create: `pdf_pipeline/outline/anchor_scan.py`
- Create: `tests/outline/test_anchor_selection.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_anchor_selection.py`:

```python
from pdf_pipeline.outline.anchor_scan import pick_anchor_candidates
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str = "1", level: int = 1) -> RawEntry:
    return RawEntry(title=title, level=level, printed_page=pp)


def test_prefers_longer_titles_with_chapter_tokens():
    entries = [
        _e("Introduction", "1"),
        _e("Chapter 1: Origins of the Problem", "5"),
        _e("A", "7"),
        _e("Chapter 2: The Methods We Use", "25"),
        _e("Notes", "100"),
    ]
    picks = pick_anchor_candidates(entries, k=3)
    titles = [p.title for p in picks]
    assert "Chapter 1: Origins of the Problem" in titles
    assert "Chapter 2: The Methods We Use" in titles
    assert "A" not in titles


def test_drops_duplicate_titles():
    entries = [
        _e("Chapter 1: Introduction", "1"),
        _e("Chapter 1: Introduction", "50"),  # dup, different part
        _e("Chapter 2: Review", "10"),
    ]
    picks = pick_anchor_candidates(entries, k=3)
    titles = [p.title for p in picks]
    assert titles.count("Chapter 1: Introduction") <= 1


def test_returns_empty_when_no_entries():
    assert pick_anchor_candidates([], k=3) == []


def test_caps_at_k():
    entries = [_e(f"Chapter {i}: Topic {i} Longer Title", str(i * 10)) for i in range(1, 10)]
    picks = pick_anchor_candidates(entries, k=3)
    assert len(picks) == 3
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_anchor_selection.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.anchor_scan'`

- [ ] **Step 3: Implement selection**

Create `pdf_pipeline/outline/anchor_scan.py`:

```python
"""Layer 3: deterministic offset resolution via anchor scan."""
from __future__ import annotations

import re
from dataclasses import dataclass

from pdf_pipeline.outline.entry_extraction import RawEntry

_CHAPTER_TOKEN = re.compile(r"\b(chapter|part|section|book)\s*\d+", re.IGNORECASE)


def _score_anchor(entry: RawEntry) -> int:
    """Higher is more distinctive."""
    words = entry.title.split()
    score = len(words)
    if _CHAPTER_TOKEN.search(entry.title):
        score += 5
    # Penalize very short titles heavily.
    if len(words) < 3:
        score -= 5
    return score


def pick_anchor_candidates(entries: list[RawEntry], k: int = 3) -> list[RawEntry]:
    """Return up to k distinctive TOC entries to use as offset anchors.

    Selection heuristics: prefer longer titles with chapter/part/section
    tokens, drop duplicate titles, skip very short titles.
    """
    if not entries:
        return []

    seen_titles: set[str] = set()
    deduped: list[RawEntry] = []
    for e in entries:
        key = e.title.strip().lower()
        if key in seen_titles:
            continue
        seen_titles.add(key)
        deduped.append(e)

    ranked = sorted(deduped, key=_score_anchor, reverse=True)
    return ranked[:k]
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_anchor_selection.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/anchor_scan.py tests/outline/test_anchor_selection.py
git commit -m "feat(outline): anchor candidate selection (Layer 3 step 1)"
```

---

### Task 16: Forward scan with Pass A (heading-like) and Pass B (fallback)

**Files:**
- Modify: `pdf_pipeline/outline/anchor_scan.py`
- Create: `tests/outline/test_anchor_forward_scan.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_anchor_forward_scan.py`:

```python
from pdf_pipeline.outline.anchor_scan import (
    MatchResult,
    find_anchor_page,
    is_heading_like,
)
from pdf_pipeline.outline.entry_extraction import RawEntry


def _pages(mapping: dict[int, str]) -> dict[int, str]:
    return mapping


def test_finds_title_on_chapter_opening():
    pages = {
        1: "copyright notice\nall rights reserved",
        2: "dedication",
        3: "\n\nChapter 1: Origins of the Problem\n\nWe begin our study by ...",
        4: "Chapter 1: Origins of the Problem  continued body text here.",
    }
    anchor = RawEntry(title="Chapter 1: Origins of the Problem", level=1, printed_page="1")
    result = find_anchor_page(anchor, pages, max_offset=10)
    assert result == MatchResult(pdf_page=3, pass_=("A"))


def test_falls_back_to_pass_b_when_only_running_headers():
    pages = {
        1: "copyright",
        2: "dedication",
        # First occurrence is a running header, not an isolated chapter opening.
        3: "Chapter 1: Origins of the Problem    body that is long enough to fill the line",
        4: "Chapter 1: Origins of the Problem    more body body body body body body body",
    }
    anchor = RawEntry(title="Chapter 1: Origins of the Problem", level=1, printed_page="1")
    result = find_anchor_page(anchor, pages, max_offset=10)
    assert result.pdf_page == 3
    assert result.pass_ == "B"


def test_returns_none_when_not_found_in_range():
    pages = {1: "alpha", 2: "beta", 3: "gamma"}
    anchor = RawEntry(title="Chapter 9: Nowhere", level=1, printed_page="9")
    assert find_anchor_page(anchor, pages, max_offset=3) is None


def test_is_heading_like_detects_isolated_top_line():
    page = "\n\nChapter 1: Origins\n\nWe begin..."
    assert is_heading_like(page, "Chapter 1: Origins") is True


def test_is_heading_like_rejects_inline_occurrence():
    page = "This chapter, the famous 'Chapter 1: Origins', introduces the topic in detail and ..."
    assert is_heading_like(page, "Chapter 1: Origins") is False
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_anchor_forward_scan.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_anchor_page'`

- [ ] **Step 3: Append to anchor_scan.py**

Append to `pdf_pipeline/outline/anchor_scan.py`:

```python
from typing import Literal

from rapidfuzz import fuzz


@dataclass(frozen=True)
class MatchResult:
    pdf_page: int
    pass_: Literal["A", "B"]


_FUZZY_THRESHOLD_DEFAULT = 80


def is_heading_like(page_text: str, title: str) -> bool:
    """Return True if `title` appears as a heading on the page.

    Heuristic signals: title sits on its own line within the first 6 lines
    of the page, and that line is shorter than 1.5x the title length (ruling
    out matches embedded inside prose).
    """
    if not page_text or not title:
        return False
    lines = [line.strip() for line in page_text.splitlines() if line.strip()]
    for line in lines[:6]:
        if fuzz.partial_ratio(line.lower(), title.lower()) >= _FUZZY_THRESHOLD_DEFAULT:
            if len(line) <= int(len(title) * 1.5) + 5:
                return True
    return False


def find_anchor_page(
    anchor: RawEntry,
    pages_text: dict[int, str],
    max_offset: int = 100,
    fuzzy_threshold: int = _FUZZY_THRESHOLD_DEFAULT,
) -> MatchResult | None:
    """Scan forward from `anchor.printed_page` to find the anchor's pdf_page.

    Two-pass matching:
    - Pass A: prefer pages where the title appears as a heading-like line.
    - Pass B: fall back to the first fuzzy match anywhere on any page.

    Returns None if no match is found within max_offset pages.
    """
    try:
        printed_int = int(anchor.printed_page)
    except (ValueError, TypeError):
        return None

    start = printed_int
    end_exclusive = min(start + max_offset + 1, max(pages_text.keys(), default=0) + 1)

    # Pass A
    for pdf_page in range(start, end_exclusive):
        text = pages_text.get(pdf_page, "")
        if is_heading_like(text, anchor.title):
            return MatchResult(pdf_page=pdf_page, pass_="A")

    # Pass B
    for pdf_page in range(start, end_exclusive):
        text = pages_text.get(pdf_page, "")
        if fuzz.partial_ratio(anchor.title.lower(), text.lower()) >= fuzzy_threshold:
            return MatchResult(pdf_page=pdf_page, pass_="B")

    return None
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_anchor_forward_scan.py -v`
Expected: 5 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/anchor_scan.py tests/outline/test_anchor_forward_scan.py
git commit -m "feat(outline): forward scan with Pass A / Pass B matching"
```

---

### Task 17: Offset derivation and cross-validation

**Files:**
- Modify: `pdf_pipeline/outline/anchor_scan.py`
- Create: `tests/outline/test_anchor_offset.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_anchor_offset.py`:

```python
from pdf_pipeline.outline.anchor_scan import derive_offset
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str) -> RawEntry:
    return RawEntry(title=title, level=1, printed_page=pp)


def test_derives_offset_from_first_validated_anchor():
    entries = [
        _e("Chapter 1: Origins and Beginnings", "1"),
        _e("Chapter 2: Methods Explained Clearly", "25"),
        _e("Chapter 3: Results and Discussion", "60"),
    ]
    # Offset = 16 (front matter = 16 pages of romans etc.)
    pages = {
        1: "copyright", 2: "dedication", 3: "preface",
        # chapter opens
        17: "\n\nChapter 1: Origins and Beginnings\n\nbody",
        41: "\n\nChapter 2: Methods Explained Clearly\n\nbody",
        76: "\n\nChapter 3: Results and Discussion\n\nbody",
    }
    result = derive_offset(entries, pages, max_offset=100)
    assert result is not None
    assert result.offset == 16
    assert result.validated_count >= 2


def test_returns_none_when_no_anchor_matches():
    entries = [_e("Nonexistent Chapter Title Goes Here", "1")]
    pages = {1: "alpha", 2: "beta", 3: "gamma"}
    assert derive_offset(entries, pages, max_offset=10) is None


def test_rejects_offset_when_validators_disagree():
    entries = [
        _e("Chapter 1: Origins and Beginnings", "1"),
        _e("Chapter 2: Not Actually Anywhere", "25"),
        _e("Chapter 3: Also Not Present Here", "60"),
    ]
    # Only chapter 1 appears where expected; others don't exist in body.
    pages = {
        17: "\n\nChapter 1: Origins and Beginnings\n\nbody",
    }
    assert derive_offset(entries, pages, max_offset=100) is None
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_anchor_offset.py -v`
Expected: FAIL — `ImportError: cannot import name 'derive_offset'`

- [ ] **Step 3: Append to anchor_scan.py**

Append to `pdf_pipeline/outline/anchor_scan.py`:

```python
@dataclass(frozen=True)
class OffsetResult:
    offset: int
    anchor: RawEntry
    match: MatchResult
    validated_count: int


def derive_offset(
    entries: list[RawEntry],
    pages_text: dict[int, str],
    max_offset: int = 100,
    min_validators: int = 2,
) -> OffsetResult | None:
    """Discover the printed→pdf_page offset by anchor scan + cross-validation.

    For each top-K candidate, try find_anchor_page; compute an offset;
    validate by checking whether 2+ other entries appear at their predicted
    pdf_page. Returns the first offset that passes validation, or None.
    """
    candidates = pick_anchor_candidates(entries, k=3)

    for anchor in candidates:
        match = find_anchor_page(anchor, pages_text, max_offset=max_offset)
        if match is None:
            continue
        try:
            anchor_printed = int(anchor.printed_page)
        except (ValueError, TypeError):
            continue
        offset = match.pdf_page - anchor_printed

        validators = [e for e in entries if e is not anchor]
        confirmed = 0
        for v in validators:
            try:
                predicted = int(v.printed_page) + offset
            except (ValueError, TypeError):
                continue
            text = pages_text.get(predicted, "")
            if fuzz.partial_ratio(v.title.lower(), text.lower()) >= _FUZZY_THRESHOLD_DEFAULT:
                confirmed += 1
                if confirmed >= min_validators:
                    break

        if confirmed >= min_validators:
            return OffsetResult(
                offset=offset,
                anchor=anchor,
                match=match,
                validated_count=confirmed,
            )

    return None
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_anchor_offset.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/anchor_scan.py tests/outline/test_anchor_offset.py
git commit -m "feat(outline): offset derivation with cross-validation"
```

---

### Task 18: Apply offset, confidence scoring, and partial-outline fallback

**Files:**
- Modify: `pdf_pipeline/outline/anchor_scan.py`
- Create: `tests/outline/test_anchor_apply.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_anchor_apply.py`:

```python
from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import RawEntry


def _e(title: str, pp: str, level: int = 1) -> RawEntry:
    return RawEntry(title=title, level=level, printed_page=pp)


def test_resolved_entries_get_pdf_pages_and_confidence():
    entries = [
        _e("Chapter 1: Origins of the Problem", "1"),
        _e("Chapter 2: Methods Explained Fully", "25"),
    ]
    pages = {
        17: "\n\nChapter 1: Origins of the Problem\n\nbody",
        41: "\n\nChapter 2: Methods Explained Fully\n\nbody",
    }
    resolved = resolve_entries(entries, pages, max_offset=100)

    assert len(resolved) == 2
    ch1, ch2 = resolved
    assert ch1.start_pdf_page == 17
    assert ch2.start_pdf_page == 41
    assert ch1.source == "anchor_scan"
    assert ch2.source == "anchor_scan"
    assert ch1.confidence > 0.5


def test_unresolved_entries_when_no_offset_found():
    entries = [_e("Nonexistent Chapter", "1")]
    pages = {1: "alpha", 2: "beta"}
    resolved = resolve_entries(entries, pages, max_offset=10)
    assert len(resolved) == 1
    assert resolved[0].start_pdf_page is None
    assert resolved[0].end_pdf_page is None
    assert resolved[0].source == "unresolved"
    assert resolved[0].confidence == 0.0


def test_low_confidence_for_entry_that_doesnt_cross_validate():
    entries = [
        _e("Chapter 1: Origins of the Problem", "1"),
        _e("Chapter 2: Also Here", "25"),
        _e("Chapter 3: Broken Reference", "50"),  # Doesn't exist at predicted page
    ]
    pages = {
        17: "Chapter 1: Origins of the Problem\n\nbody",
        41: "Chapter 2: Also Here\n\nbody",
        66: "Totally different content here nothing to match",
    }
    resolved = resolve_entries(entries, pages, max_offset=100)
    # Chapter 3 should still get a pdf_page from the global offset (66) but
    # with lower confidence since its title doesn't appear there.
    ch3 = resolved[2]
    assert ch3.start_pdf_page == 66
    assert ch3.confidence <= 0.6
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_anchor_apply.py -v`
Expected: FAIL — `ImportError: cannot import name 'resolve_entries'`

- [ ] **Step 3: Append to anchor_scan.py**

Append to `pdf_pipeline/outline/anchor_scan.py`:

```python
from pdf_pipeline.outline.schema import OutlineEntry


_CONFIDENCE_EXACT_A = 0.95
_CONFIDENCE_FUZZY_A = 0.85
_CONFIDENCE_B = 0.70
_CONFIDENCE_GLOBAL_ONLY = 0.50


def resolve_entries(
    entries: list[RawEntry],
    pages_text: dict[int, str],
    max_offset: int = 100,
) -> list[OutlineEntry]:
    """Turn raw TOC entries into OutlineEntry records with resolved pdf_pages.

    Discovers the offset once via anchor scan; applies it to all entries;
    cross-checks each entry individually and drops confidence if its own
    title doesn't appear at the predicted page.

    Entries whose pdf_page cannot be resolved at all are emitted with
    start_pdf_page = end_pdf_page = None, confidence = 0.0, source =
    "unresolved".
    """
    offset_result = derive_offset(entries, pages_text, max_offset=max_offset)
    resolved: list[OutlineEntry] = []

    if offset_result is None:
        for i, raw in enumerate(entries):
            resolved.append(
                _to_unresolved(raw, idx=i)
            )
        return resolved

    offset = offset_result.offset

    for i, raw in enumerate(entries):
        try:
            printed_int = int(raw.printed_page)
        except (ValueError, TypeError):
            resolved.append(_to_unresolved(raw, idx=i))
            continue
        pdf_page = printed_int + offset
        text = pages_text.get(pdf_page, "")

        if raw is offset_result.anchor:
            if offset_result.match.pass_ == "A":
                confidence = _CONFIDENCE_EXACT_A
            else:
                confidence = _CONFIDENCE_B
        else:
            score = fuzz.partial_ratio(raw.title.lower(), text.lower())
            if score >= 95:
                confidence = _CONFIDENCE_EXACT_A
            elif score >= _FUZZY_THRESHOLD_DEFAULT:
                confidence = _CONFIDENCE_FUZZY_A
            else:
                confidence = _CONFIDENCE_GLOBAL_ONLY

        resolved.append(
            OutlineEntry(
                id=f"a{i}",
                title=raw.title,
                level=raw.level,
                parent_id=None,  # wired up later in orchestrator
                start_pdf_page=pdf_page,
                end_pdf_page=None,
                printed_page=raw.printed_page,
                confidence=confidence,
                source="anchor_scan",
            )
        )

    return resolved


def _to_unresolved(raw: RawEntry, idx: int) -> OutlineEntry:
    return OutlineEntry(
        id=f"u{idx}",
        title=raw.title,
        level=raw.level,
        parent_id=None,
        start_pdf_page=None,
        end_pdf_page=None,
        printed_page=raw.printed_page,
        confidence=0.0,
        source="unresolved",
    )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_anchor_apply.py -v`
Expected: 3 passed

- [ ] **Step 5: Run the full anchor_scan suite to catch regressions**

Run: `pytest tests/outline/test_anchor_selection.py tests/outline/test_anchor_forward_scan.py tests/outline/test_anchor_offset.py tests/outline/test_anchor_apply.py -v`
Expected: all previous passes preserved

- [ ] **Step 6: Commit**

```bash
git add pdf_pipeline/outline/anchor_scan.py tests/outline/test_anchor_apply.py
git commit -m "feat(outline): apply offset + confidence scoring + partial fallback"
```

---

## Part F — Layer 4, Orchestration, Storage, Tools

### Task 19: Layer 4 — range assignment

**Files:**
- Create: `pdf_pipeline/outline/range_assignment.py`
- Create: `tests/outline/test_range_assignment.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_range_assignment.py`:

```python
from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import OutlineEntry


def _entry(id_: str, title: str, level: int, start: int | None, parent: str | None = None) -> OutlineEntry:
    return OutlineEntry(
        id=id_, title=title, level=level, parent_id=parent,
        start_pdf_page=start, end_pdf_page=None, printed_page=None,
        confidence=1.0, source="pdf_outline" if start else "unresolved",
    )


def test_top_level_ranges_are_derived_from_next_sibling():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("c2", "Ch 2", 1, 20),
        _entry("c3", "Ch 3", 1, 40),
    ]
    out = assign_end_pages(entries, total_pages=60)
    assert out[0].end_pdf_page == 19
    assert out[1].end_pdf_page == 39
    assert out[2].end_pdf_page == 60


def test_subsection_end_is_next_sibling_minus_one():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("s11", "1.1", 2, 5, parent="c1"),
        _entry("s12", "1.2", 2, 10, parent="c1"),
        _entry("c2", "Ch 2", 1, 20),
    ]
    out = assign_end_pages(entries, total_pages=30)
    # section 1.1 ends before 1.2
    assert out[1].end_pdf_page == 9
    # section 1.2 ends at chapter 2 - 1 (parent's effective end)
    assert out[2].end_pdf_page == 19
    # chapter 1 spans 5..19
    assert out[0].end_pdf_page == 19


def test_unresolved_entries_keep_null_ranges():
    entries = [
        _entry("c1", "Ch 1", 1, 5),
        _entry("c2", "Ch 2", 1, None),  # unresolved
        _entry("c3", "Ch 3", 1, 40),
    ]
    out = assign_end_pages(entries, total_pages=60)
    assert out[0].end_pdf_page == 39  # skips unresolved
    assert out[1].end_pdf_page is None
    assert out[2].end_pdf_page == 60
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_range_assignment.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.range_assignment'`

- [ ] **Step 3: Implement assign_end_pages**

Create `pdf_pipeline/outline/range_assignment.py`:

```python
"""Layer 4: fill in end_pdf_page for each resolved entry."""
from __future__ import annotations

from dataclasses import replace

from pdf_pipeline.outline.schema import OutlineEntry


def assign_end_pages(entries: list[OutlineEntry], total_pages: int) -> list[OutlineEntry]:
    """Return a new list with end_pdf_page filled in for resolved entries.

    For each entry at level L with start S, end = (start of next entry
    with level <= L) - 1. If there is no such following entry, end =
    total_pages. Unresolved entries (start_pdf_page is None) are left
    untouched.
    """
    result: list[OutlineEntry] = []
    for i, entry in enumerate(entries):
        if entry.start_pdf_page is None:
            result.append(entry)
            continue

        end = total_pages
        for j in range(i + 1, len(entries)):
            nxt = entries[j]
            if nxt.start_pdf_page is None:
                continue
            if nxt.level <= entry.level:
                end = nxt.start_pdf_page - 1
                break

        result.append(replace(entry, end_pdf_page=end))

    return result
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_range_assignment.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/range_assignment.py tests/outline/test_range_assignment.py
git commit -m "feat(outline): Layer 4 range assignment"
```

---

### Task 20: Pipeline orchestrator

**Files:**
- Create: `pdf_pipeline/outline/pipeline.py`
- Create: `tests/outline/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_pipeline.py`:

```python
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

from pypdf import PdfWriter

from llm.mock import MockLLMClient
from pdf_pipeline.outline.pipeline import extract_outline
from pdf_pipeline.outline.schema import DocumentOutline


def _build_pdf_with_outline(tmp_path: Path, outline: list[tuple[str, int]]) -> Path:
    writer = PdfWriter()
    max_page = max((p for _, p in outline), default=1)
    for _ in range(max_page):
        writer.add_blank_page(width=612, height=792)
    for title, page in outline:
        writer.add_outline_item(title, page - 1)
    path = tmp_path / "x.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def test_uses_pdf_outline_when_present(tmp_path: Path):
    pdf = _build_pdf_with_outline(
        tmp_path,
        [("Chapter 1", 5), ("Chapter 2", 20), ("Chapter 3", 50)],
    )
    client = MockLLMClient(responses=[])  # must not be called

    outline = extract_outline(str(pdf), llm_client=client, source_id="s1")

    assert isinstance(outline, DocumentOutline)
    assert outline.source_id == "s1"
    assert outline.version == 1
    assert len(outline.entries) == 3
    assert [e.title for e in outline.entries] == ["Chapter 1", "Chapter 2", "Chapter 3"]
    assert [e.start_pdf_page for e in outline.entries] == [5, 20, 50]
    assert all(e.source == "pdf_outline" for e in outline.entries)
    assert [e.end_pdf_page for e in outline.entries] == [19, 49, 50]
    assert client.calls == []


def test_falls_back_to_llm_when_no_outline(tmp_path: Path, monkeypatch):
    # Plain PDF with no bookmarks, no page labels.
    writer = PdfWriter()
    for _ in range(20):
        writer.add_blank_page(width=612, height=792)
    pdf_path = tmp_path / "plain.pdf"
    with pdf_path.open("wb") as fh:
        writer.write(fh)

    # Stub the page text source so the orchestrator sees TOC-looking text on
    # page 3 and body text matching the TOC titles on later pages.
    fake_pages = {
        1: "front matter",
        2: "dedication",
        3: "Contents\n\nChapter 1: Origins ........ 1\nChapter 2: Methods ........ 10\n",
        4: "further TOC\nChapter 3: Results ....... 15",
        5: "\n\nChapter 1: Origins\n\nbody starts here",
        14: "\n\nChapter 2: Methods\n\nbody",
        19: "\n\nChapter 3: Results\n\nbody",
    }
    from pdf_pipeline.outline import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "_load_pages_text", lambda pdf_path_, total_pages, max_pages: fake_pages
    )

    client = MockLLMClient(
        responses=[
            # chunk 1: pages 1..5 - TOC entries extracted
            {
                "pages": [{"pdf_page": p, "is_toc": (p in (3, 4))} for p in range(1, 6)],
                "entries": [
                    {"title": "Chapter 1: Origins", "level": 1, "printed_page": "1"},
                    {"title": "Chapter 2: Methods", "level": 1, "printed_page": "10"},
                    {"title": "Chapter 3: Results", "level": 1, "printed_page": "15"},
                ],
            },
            # chunk 2: pages 6..10 - no TOC -> stop
            {
                "pages": [{"pdf_page": p, "is_toc": False} for p in range(6, 11)],
                "entries": [],
            },
        ]
    )

    outline = extract_outline(str(pdf_path), llm_client=client, source_id="s2", max_toc_pages=10, chunk_size=5)
    assert len(outline.entries) == 3
    assert all(e.source == "anchor_scan" for e in outline.entries)
    assert [e.start_pdf_page for e in outline.entries] == [5, 14, 19]


def test_returns_empty_outline_when_no_toc_and_no_metadata(tmp_path: Path, monkeypatch):
    writer = PdfWriter()
    for _ in range(5):
        writer.add_blank_page(width=612, height=792)
    pdf = tmp_path / "plain.pdf"
    with pdf.open("wb") as fh:
        writer.write(fh)

    from pdf_pipeline.outline import pipeline as pipeline_mod
    monkeypatch.setattr(
        pipeline_mod, "_load_pages_text",
        lambda pdf_path_, total_pages, max_pages: {i: "narrative body" for i in range(1, 6)},
    )

    client = MockLLMClient(responses=[])  # prefilter should short-circuit; client never called

    outline = extract_outline(str(pdf), llm_client=client, source_id="s3", max_toc_pages=5)
    assert outline.entries == []
    assert client.calls == []
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.pipeline'`

- [ ] **Step 3: Implement the orchestrator**

Create `pdf_pipeline/outline/pipeline.py`:

```python
"""End-to-end outline extraction orchestrator."""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader

from llm.client import LLMClient
from pdf_pipeline.outline.anchor_scan import resolve_entries
from pdf_pipeline.outline.entry_extraction import extract_toc_entries
from pdf_pipeline.outline.metadata import read_page_labels, read_pdf_outlines
from pdf_pipeline.outline.page_text import PageTextSource, PyPdfPageExtractor
from pdf_pipeline.outline.prefilter import looks_like_toc
from pdf_pipeline.outline.range_assignment import assign_end_pages
from pdf_pipeline.outline.schema import DocumentOutline


def extract_outline(
    pdf_path: str | Path,
    llm_client: LLMClient,
    source_id: str,
    version: int = 1,
    max_toc_pages: int = 40,
    chunk_size: int = 5,
    max_offset: int = 100,
) -> DocumentOutline:
    """Extract a DocumentOutline from `pdf_path`.

    Layer 1 (structural metadata) is tried first. If it yields entries, they
    are used directly. Otherwise Layer 2 extracts TOC entries via the LLM,
    and Layer 3 resolves pdf_pages via anchor scan. Layer 4 assigns end
    pages.
    """
    reader = PdfReader(str(pdf_path))
    total_pages = len(reader.pages)

    # Layer 1
    pdf_outline = read_pdf_outlines(pdf_path)
    if pdf_outline:
        finalized = assign_end_pages(pdf_outline, total_pages=total_pages)
        return DocumentOutline(source_id=source_id, version=version, entries=finalized)

    # Load text for the first max_toc_pages (capped at total_pages).
    scan_pages = min(max_toc_pages, total_pages)
    pages_text = _load_pages_text(str(pdf_path), total_pages, scan_pages)

    # Prefilter: is there a TOC to extract at all?
    combined = "\n".join(pages_text.get(p, "") for p in range(1, scan_pages + 1))
    if not looks_like_toc(combined):
        return DocumentOutline(source_id=source_id, version=version, entries=[])

    # Layer 2
    pages_payload = [
        {"pdf_page": p, "text": pages_text.get(p, "")} for p in range(1, scan_pages + 1)
    ]
    raw = extract_toc_entries(pages_payload, llm_client, chunk_size=chunk_size)
    if not raw:
        return DocumentOutline(source_id=source_id, version=version, entries=[])

    # Layer 3 - need body text over a wider range to locate anchors.
    body_pages = _load_pages_text(str(pdf_path), total_pages, total_pages)
    resolved = resolve_entries(raw, body_pages, max_offset=max_offset)

    # Optional: use /PageLabels to backfill printed_page sanity (future work).
    _ = read_page_labels(pdf_path)

    finalized = assign_end_pages(resolved, total_pages=total_pages)
    return DocumentOutline(source_id=source_id, version=version, entries=finalized)


def _load_pages_text(pdf_path: str, total_pages: int, max_pages: int) -> dict[int, str]:
    """Extract text for pages 1..max_pages. Overridable in tests."""
    source = PageTextSource(text_extractor=PyPdfPageExtractor(), ocr_extractor=None)
    return {
        p: source.get(pdf_path, p).text for p in range(1, min(total_pages, max_pages) + 1)
    }
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_pipeline.py -v`
Expected: 3 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/pipeline.py tests/outline/test_pipeline.py
git commit -m "feat(outline): end-to-end orchestrator"
```

---

### Task 21: Versioned storage

**Files:**
- Create: `pdf_pipeline/outline/storage.py`
- Create: `tests/outline/test_storage.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_storage.py`:

```python
from pathlib import Path

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore


def _outline(version: int, title: str = "Ch 1") -> DocumentOutline:
    return DocumentOutline(
        source_id="s1", version=version,
        entries=[OutlineEntry(
            id="e0", title=title, level=1, parent_id=None,
            start_pdf_page=1, end_pdf_page=10,
            printed_page="1", confidence=1.0, source="pdf_outline",
        )],
    )


def test_save_and_load_round_trips(tmp_path: Path):
    store = OutlineStore(root=tmp_path)
    outline = _outline(1)
    store.save(outline)

    loaded = store.load_latest("s1")
    assert loaded == outline


def test_save_rejects_version_overwrite(tmp_path: Path):
    import pytest

    store = OutlineStore(root=tmp_path)
    store.save(_outline(1))
    with pytest.raises(FileExistsError):
        store.save(_outline(1, title="Different"))


def test_load_latest_picks_highest_version(tmp_path: Path):
    store = OutlineStore(root=tmp_path)
    store.save(_outline(1, title="v1"))
    store.save(_outline(2, title="v2"))
    store.save(_outline(3, title="v3"))

    loaded = store.load_latest("s1")
    assert loaded.version == 3
    assert loaded.entries[0].title == "v3"


def test_load_latest_raises_when_missing(tmp_path: Path):
    import pytest

    store = OutlineStore(root=tmp_path)
    with pytest.raises(KeyError):
        store.load_latest("nope")
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.storage'`

- [ ] **Step 3: Implement OutlineStore**

Create `pdf_pipeline/outline/storage.py`:

```python
"""Versioned, immutable file-backed storage for DocumentOutlines."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry


class OutlineStore:
    """Simple versioned store keyed by source_id.

    Each outline is written to {root}/{source_id}/v{version}.json and is
    immutable — attempting to overwrite raises FileExistsError. load_latest
    picks the highest version number present.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._root.mkdir(parents=True, exist_ok=True)

    def save(self, outline: DocumentOutline) -> None:
        dir_ = self._root / outline.source_id
        dir_.mkdir(parents=True, exist_ok=True)
        path = dir_ / f"v{outline.version}.json"
        if path.exists():
            raise FileExistsError(f"outline version already exists: {path}")
        payload = {
            "source_id": outline.source_id,
            "version": outline.version,
            "entries": [asdict(e) for e in outline.entries],
        }
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")

    def load_latest(self, source_id: str) -> DocumentOutline:
        dir_ = self._root / source_id
        if not dir_.exists():
            raise KeyError(source_id)
        versions = sorted(
            (int(p.stem.lstrip("v")) for p in dir_.glob("v*.json")),
            reverse=True,
        )
        if not versions:
            raise KeyError(source_id)
        path = dir_ / f"v{versions[0]}.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries = [OutlineEntry(**e) for e in payload["entries"]]
        return DocumentOutline(
            source_id=payload["source_id"],
            version=payload["version"],
            entries=entries,
        )
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_storage.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/storage.py tests/outline/test_storage.py
git commit -m "feat(outline): versioned outline storage"
```

---

### Task 22: Tool surface — list_outline and get_section

**Files:**
- Create: `pdf_pipeline/outline/tools.py`
- Create: `tests/outline/test_tools.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_tools.py`:

```python
from pathlib import Path

import pytest
from pypdf import PdfWriter

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore
from pdf_pipeline.outline.tools import SectionLookupError, get_section, list_outline


def _write_blank_pdf(path: Path, n_pages: int) -> None:
    writer = PdfWriter()
    for i in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with path.open("wb") as fh:
        writer.write(fh)


def _entry(id_: str, start: int | None, end: int | None) -> OutlineEntry:
    return OutlineEntry(
        id=id_, title=f"e-{id_}", level=1, parent_id=None,
        start_pdf_page=start, end_pdf_page=end,
        printed_page=None, confidence=1.0,
        source="pdf_outline" if start else "unresolved",
    )


def _seed_outline(store: OutlineStore, source_id: str, entries: list[OutlineEntry]) -> None:
    store.save(DocumentOutline(source_id=source_id, version=1, entries=entries))


def test_list_outline_returns_entries(tmp_path: Path):
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 5), _entry("b", 6, 10)])
    entries = list_outline("s1", store=store)
    assert [e.id for e in entries] == ["a", "b"]


def test_get_section_returns_concatenated_text(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 10)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 3), _entry("b", 4, 10)])

    # Fake per-page extractor so we don't need real text.
    class FakeExtractor:
        def extract_page_text(self, p: str, n: int) -> str:
            return f"page-{n}"

    text = get_section("s1", "b", pdf_path=str(pdf_path), store=store, extractor=FakeExtractor())
    assert text == "page-4\npage-5\npage-6\npage-7\npage-8\npage-9\npage-10"


def test_get_section_rejects_unresolved_entry(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 5)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("u", None, None)])

    with pytest.raises(SectionLookupError, match="unresolved"):
        get_section("s1", "u", pdf_path=str(pdf_path), store=store)


def test_get_section_rejects_unknown_entry(tmp_path: Path):
    pdf_path = tmp_path / "s1.pdf"
    _write_blank_pdf(pdf_path, 5)
    store = OutlineStore(root=tmp_path / "store")
    _seed_outline(store, "s1", [_entry("a", 1, 5)])

    with pytest.raises(SectionLookupError, match="not found"):
        get_section("s1", "missing", pdf_path=str(pdf_path), store=store)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'pdf_pipeline.outline.tools'`

- [ ] **Step 3: Implement the tools**

Create `pdf_pipeline/outline/tools.py`:

```python
"""Tool surface: list_outline, get_section."""
from __future__ import annotations

from typing import Protocol

from pdf_pipeline.outline.page_text import PyPdfPageExtractor
from pdf_pipeline.outline.schema import OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore


class SectionLookupError(Exception):
    """Raised when get_section cannot return text for the requested entry."""


class _PageExtractor(Protocol):
    def extract_page_text(self, pdf_path: str, pdf_page: int) -> str: ...


def list_outline(source_id: str, store: OutlineStore) -> list[OutlineEntry]:
    return store.load_latest(source_id).entries


def get_section(
    source_id: str,
    entry_id: str,
    pdf_path: str,
    store: OutlineStore,
    extractor: _PageExtractor | None = None,
) -> str:
    outline = store.load_latest(source_id)
    for e in outline.entries:
        if e.id == entry_id:
            if e.start_pdf_page is None or e.end_pdf_page is None:
                raise SectionLookupError(f"entry {entry_id!r} is unresolved (no pdf_page range)")
            ext = extractor or PyPdfPageExtractor()
            pages = [
                ext.extract_page_text(pdf_path, p)
                for p in range(e.start_pdf_page, e.end_pdf_page + 1)
            ]
            return "\n".join(pages)
    raise SectionLookupError(f"entry_id not found: {entry_id!r}")
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_tools.py -v`
Expected: 4 passed

- [ ] **Step 5: Commit**

```bash
git add pdf_pipeline/outline/tools.py tests/outline/test_tools.py
git commit -m "feat(outline): list_outline / get_section tool surface"
```

---

### Task 23: Public exports and CLI integration

**Files:**
- Modify: `pdf_pipeline/outline/__init__.py`
- Modify: `pdf_pipeline/cli.py`
- Create: `tests/outline/test_public_api.py`

- [ ] **Step 1: Write the failing test**

Create `tests/outline/test_public_api.py`:

```python
def test_public_imports():
    from pdf_pipeline.outline import (
        DocumentOutline,
        OutlineEntry,
        OutlineStore,
        SectionLookupError,
        extract_outline,
        get_section,
        list_outline,
    )

    # Symbols loaded, namespaces wired.
    assert DocumentOutline.__name__ == "DocumentOutline"
    assert OutlineEntry.__name__ == "OutlineEntry"
    assert OutlineStore.__name__ == "OutlineStore"
    assert SectionLookupError.__name__ == "SectionLookupError"
    assert callable(extract_outline)
    assert callable(get_section)
    assert callable(list_outline)
```

- [ ] **Step 2: Run test, expect failure**

Run: `pytest tests/outline/test_public_api.py -v`
Expected: FAIL — `ImportError: cannot import name 'DocumentOutline'`

- [ ] **Step 3: Update `pdf_pipeline/outline/__init__.py`**

Replace contents of `pdf_pipeline/outline/__init__.py`:

```python
"""Document outline extraction pipeline."""
from pdf_pipeline.outline.pipeline import extract_outline
from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry, SourceType
from pdf_pipeline.outline.storage import OutlineStore
from pdf_pipeline.outline.tools import SectionLookupError, get_section, list_outline

__all__ = [
    "DocumentOutline",
    "OutlineEntry",
    "OutlineStore",
    "SectionLookupError",
    "SourceType",
    "extract_outline",
    "get_section",
    "list_outline",
]
```

- [ ] **Step 4: Run tests, expect pass**

Run: `pytest tests/outline/test_public_api.py -v`
Expected: 1 passed

- [ ] **Step 5: Add a CLI subcommand for outline extraction**

Open `pdf_pipeline/cli.py`. Add a new `outline` subcommand alongside the existing commands. The exact wiring depends on the current argparse structure — locate the main parser's `add_subparsers` call and add:

```python
outline_parser = subparsers.add_parser("outline", help="Extract a document outline")
outline_parser.add_argument("pdf_path", help="Path to PDF")
outline_parser.add_argument("--source-id", required=True)
outline_parser.add_argument("--provider", default=None, help="LLM provider (claude/openai/gemini)")
outline_parser.add_argument("--store", default="./outline_store", help="Storage root")
outline_parser.set_defaults(func=_cmd_outline)
```

And the handler (add at module level in `cli.py`):

```python
def _cmd_outline(args) -> int:
    from llm.factory import make_client
    from pdf_pipeline.outline import OutlineStore, extract_outline

    client = make_client(args.provider)
    store = OutlineStore(root=args.store)
    outline = extract_outline(args.pdf_path, llm_client=client, source_id=args.source_id)
    store.save(outline)
    for entry in outline.entries:
        print(
            f"[{entry.source}] lvl {entry.level} "
            f"pdf_page={entry.start_pdf_page}-{entry.end_pdf_page} "
            f"printed={entry.printed_page} "
            f"conf={entry.confidence:.2f}  {entry.title}"
        )
    return 0
```

- [ ] **Step 6: Smoke-test the CLI wiring (no live LLM)**

Run (fixture PDF must exist from Task 9's tests — regenerate with pypdf if needed):

```bash
python -c "from pdf_pipeline.cli import main; import sys; sys.exit(main(['outline', '--help']))"
```

Expected: usage text including `outline` flags, exit code 0.

- [ ] **Step 7: Commit**

```bash
git add pdf_pipeline/outline/__init__.py pdf_pipeline/cli.py tests/outline/test_public_api.py
git commit -m "feat(outline): public exports and CLI subcommand"
```

---

### Task 24: Golden-file integration test

**Files:**
- Create: `tests/outline/fixtures/make_fixtures.py`
- Create: `tests/outline/test_golden.py`

This task validates the full pipeline end-to-end against generated fixture PDFs. It uses the mock LLM with responses calibrated to the fixtures so the test is deterministic and fast.

- [ ] **Step 1: Create the fixture generator**

Create `tests/outline/fixtures/make_fixtures.py`:

```python
"""Regenerate the outline fixture PDFs.

Run: python tests/outline/fixtures/make_fixtures.py
"""
from __future__ import annotations

from pathlib import Path

from pypdf import PdfWriter


HERE = Path(__file__).parent


def make_born_digital_with_outlines() -> Path:
    writer = PdfWriter()
    for _ in range(30):
        writer.add_blank_page(width=612, height=792)
    writer.add_outline_item("Chapter 1: Origins", 4)  # pdf_page 5
    writer.add_outline_item("Chapter 2: Methods", 14)  # pdf_page 15
    writer.add_outline_item("Chapter 3: Results", 24)  # pdf_page 25
    path = HERE / "born_digital_with_outlines.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


def make_article_no_toc() -> Path:
    writer = PdfWriter()
    for _ in range(10):
        writer.add_blank_page(width=612, height=792)
    path = HERE / "article_no_toc.pdf"
    with path.open("wb") as fh:
        writer.write(fh)
    return path


if __name__ == "__main__":
    for fn in [make_born_digital_with_outlines, make_article_no_toc]:
        out = fn()
        print(f"wrote {out}")
```

- [ ] **Step 2: Generate the fixtures**

Run: `python tests/outline/fixtures/make_fixtures.py`
Expected: two lines `wrote .../<name>.pdf`.

- [ ] **Step 3: Write the golden test**

Create `tests/outline/test_golden.py`:

```python
from pathlib import Path

from llm.mock import MockLLMClient
from pdf_pipeline.outline import extract_outline


FIXTURES = Path(__file__).parent / "fixtures"


def test_born_digital_with_outlines_uses_layer_1():
    """PDF with /Outlines should not call the LLM."""
    client = MockLLMClient(responses=[])
    outline = extract_outline(
        str(FIXTURES / "born_digital_with_outlines.pdf"),
        llm_client=client,
        source_id="golden-1",
    )
    assert [e.title for e in outline.entries] == [
        "Chapter 1: Origins",
        "Chapter 2: Methods",
        "Chapter 3: Results",
    ]
    assert [e.start_pdf_page for e in outline.entries] == [5, 15, 25]
    assert [e.end_pdf_page for e in outline.entries] == [14, 24, 30]
    assert all(e.source == "pdf_outline" for e in outline.entries)
    assert client.calls == []


def test_article_no_toc_returns_empty_outline():
    """Article with no outline and no TOC should produce an empty outline."""
    client = MockLLMClient(responses=[])
    outline = extract_outline(
        str(FIXTURES / "article_no_toc.pdf"),
        llm_client=client,
        source_id="golden-2",
    )
    assert outline.entries == []
    assert client.calls == []  # prefilter short-circuited
```

- [ ] **Step 4: Run the golden tests**

Run: `pytest tests/outline/test_golden.py -v`
Expected: 2 passed

- [ ] **Step 5: Run the full test suite to verify nothing regressed**

Run: `pytest tests/ -v`
Expected: all tests pass (count: ~55 tests across llm/ and outline/).

- [ ] **Step 6: Commit**

```bash
git add tests/outline/fixtures/make_fixtures.py tests/outline/fixtures/born_digital_with_outlines.pdf tests/outline/fixtures/article_no_toc.pdf tests/outline/test_golden.py
git commit -m "test(outline): golden-file fixtures and end-to-end tests"
```

---

## Wrap-Up

After all tasks pass:

- Run the full suite one more time: `pytest tests/ -v` — should be green.
- Manual smoke test with a live LLM provider: set the appropriate API key and run:
  ```bash
  python -m pdf_pipeline.cli outline tests/outline/fixtures/born_digital_with_outlines.pdf --source-id smoke-1
  ```
  This should print three chapters sourced from `pdf_outline` without making any LLM calls.
- Update the spec's status to reflect that Phase 2 implementation has started (append a note: "Implementation begun 2026-04-17, core pipeline delivered").

## Open Sub-Questions That Implementation Leaves Open

From spec §8, these were deliberately deferred and should be revisited during early usage:

1. **Anchor selection policy** — current heuristic in `anchor_scan.pick_anchor_candidates` is a starting point; tune on the eval set once one exists.
2. **Heading-like detection signals** — current implementation uses "first 6 lines, fuzzy match on short line"; richer signals (layout-aware, font-size proxies) may be needed for scanned sources.
3. **Malformed-Layer-2 detection rule** — the current pipeline does not auto-escalate OCR tier. Adding that is a future task after observing real failures.
4. **Eval methodology** — a curated golden set with hand-verified outlines needs to be assembled to drive parameter tuning.
5. **MAX_OFFSET sizing for reference works** — current default of 100 is fine for trade/academic books but may need to grow for encyclopedias.
