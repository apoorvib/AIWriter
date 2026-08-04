from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

WORKFLOW = Path(".claude/workflows/write.js")
LEDGER_STEPS = ("brief", "research", "plan", "draft", "review", "revision", "finalize")


@pytest.fixture(scope="module")
def script() -> str:
    assert WORKFLOW.exists(), f"missing workflow script: {WORKFLOW}"
    return WORKFLOW.read_text(encoding="utf-8")


def test_declares_write_workflow_meta(script: str) -> None:
    assert "export const meta" in script
    assert "name: 'write'" in script


def test_supports_raw_string_and_structured_args(script: str) -> None:
    # Raw slash-command string is normalized; structured callers pass an object.
    assert "typeof a === 'string'" in script
    assert "ARGS_SCHEMA" in script
    for field in ("request", "context_paths", "include_skills", "exclude_skills", "mode", "research"):
        assert field in script, f"args schema is missing {field!r}"


def test_parser_is_forbidden_from_inventing_paths_or_ids(script: str) -> None:
    assert "invent" in script.lower()


def test_supports_writing_run_id_resume(script: str) -> None:
    assert "writing_run_id" in script
    assert "recover_writing_run" in script
    # A resume path must not unconditionally start a fresh run.
    assert "a.writing_run_id" in script


def test_reads_the_completion_ledger(script: str) -> None:
    assert "get_writing_progress" in script


def test_handles_requires_human(script: str) -> None:
    assert "requires_human" in script
    assert "answer_writing_questions" in script


def test_recognizes_every_ledger_step(script: str) -> None:
    for step in LEDGER_STEPS:
        assert step in script, f"workflow does not handle ledger step {step!r}"
    # Detailed review must go through clean-context delegation.
    assert "dispatch_writing_reviewer" in script


def test_uses_bounded_loops_and_step_retry_cap(script: str) -> None:
    assert "MAX_ACTIONS = 30" in script
    assert "i < MAX_ACTIONS" in script
    assert "MAX_STEP_RETRIES = 2" in script


def test_research_step_has_web_search_retry_handling(script: str) -> None:
    lowered = script.lower()
    assert "retry once" in lowered
    assert "warning" in lowered


def test_performs_final_ledger_assertion(script: str) -> None:
    # all_required_done appears in the loop AND in a post-loop assertion that throws.
    assert script.count("all_required_done") >= 2
    assert "throw new Error" in script
    assert "did not reach completion" in script


def test_returns_persisted_output_not_unconditional_success(script: str) -> None:
    assert "get_writing_output" in script
    # The final return surfaces the fetched output, not a constant success string.
    assert "return String(output" in script


def test_script_is_valid_javascript() -> None:
    node = shutil.which("node")
    if node is None:
        pytest.skip("node is not installed")
    proc = subprocess.run(
        [node, "--check", str(WORKFLOW)],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
