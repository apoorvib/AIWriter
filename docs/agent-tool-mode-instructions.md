# EssayWriter Agent Tool Mode Instructions

You are orchestrating EssayWriter through local Agent Tool Mode tools.

## Non-Negotiable Rules

1. Use only Agent Tool Mode tools for persisted essay workflow actions.
2. Do not call Pipeline Mode, backend API routes, provider adapters, or configured app LLM clients unless the user explicitly opts into API-backed Pipeline Mode.
3. Start or recover an AgentRun before doing stateful work, and pass its `agent_run_id` to every stateful tool. The server enforces this: stateful `prepare_*`/`commit_*`/`create_job_from_artifacts`/`submit_work_result`/`export_markdown`/`dispatch_subagent`/`select_topic`/etc. reject calls that omit `agent_run_id` with `agent_run_required`. Omitting the run id would silently bypass the phase, stale-harness, and writing-style gates, so it is not allowed.
4. Treat persisted AgentRun state as authoritative and chat memory as advisory.
5. For model-reasoning stages, call `prepare_*`, produce JSON matching `response_schema`, call `submit_work_result`, then call the named `commit_*` tool.
6. **For every `prepare_*` work packet, the `system_prompt` field returned by the tool IS the system message you MUST use when generating the JSON. Do not summarize it, skip it, paraphrase it, or substitute your own.** The `prompt_blocks` array contains the user message(s) in order. `response_schema` defines only the output shape. Skipping `system_prompt` silently bypasses the prompt engineering the workflow depends on — grounding rules, source-trust boundaries, anti-AI writing rules, and stage-specific output contracts. If you cannot or will not honor a packet's `system_prompt`, stop and report it instead of producing a result. **Proof of attention:** the system_prompt ends with an `ATTENTION CHECK` line containing a one-time token. You MUST copy that exact token into a free-text field of your output JSON (for example a `notes` or `self_check_notes` entry). `submit_work_result` rejects payloads that omit it with `system_prompt_not_honored`, because a missing token means the system_prompt was not read.
7. Prefer `work_result_id` for commits.
8. Never invent source IDs, page numbers, note IDs, packet IDs, work packet IDs, work result IDs, draft IDs, validation IDs, or export IDs.
9. If `blocked_on` is present, ask the user to resolve it before continuing.
10. If context was compacted or you are unsure what happened, call `recover_agent_run` before taking another state-changing action.
11. If a work packet has `delegation.recommended=true` and your harness supports subagents, delegate the packet unless the user disabled subagents or the packet is small enough to handle directly. When delegating, the subagent must also use the packet's `system_prompt` verbatim — pass it through, do not strip it.

## Common Failure Modes

These are the three drift patterns this build is engineered to catch. If a tool returns one of these error codes, you are inside the failure mode. Stop and resolve before continuing.

1. **Skipping writing-style ingestion before `create_job_from_artifacts`.** The anti-AI writing skill explicitly says voice calibration is the dominant defense against AI detectors. Generic anti-AI heuristics alone produce text that still resembles the average LLM output and gets flagged. The server enforces a `writing_style_required` gate at `create_job_from_artifacts` time. Before calling it, either ingest samples from `inputs/writing_style/` and attach a writing-style content_id to the job, or explicitly call `skip_writing_style_calibration(job_id, reason="…")` and pass the returned token. There is no silent default.

2. **Running stages inline when the packet has `delegation.recommended=true`.** Packets like `prepare_anti_ai_audit` are designed to be dispatched to a clean-context subagent. Running them in the main orchestrator pollutes the context with the audit's bespoke system prompt and degrades the quality of every subsequent stage. When the packet declares delegation, delegate.

3. **Not re-reading harness instructions after several stages.** If many stages have passed since you last called `get_harness_instructions`, your view of the workflow may be stale. Tools that are about to make irreversible commitments will warn or refuse if your last harness read is too old. Re-call `get_harness_instructions` when prompted; the cost is small.

## Normal Flow

This is the target workflow surface. During partial implementation, call only tools listed in `currently_callable_tools`; use `planned_workflow_tools` as the roadmap for later Agent Tool Mode capabilities.

1. `get_harness_instructions`
2. `start_agent_run` or `recover_agent_run`
3. `ingest_source_file`
4. `prepare_source_card`
5. produce source-card JSON
6. `submit_work_result`
7. `commit_source_card`
8. **REQUIRED** before `create_job_from_artifacts`: either ingest writing-style samples OR explicitly skip with a reason.
   - First check the conventional location `inputs/writing_style/`. Files there (`.md`, `.txt`, `.pdf`, `.docx`) are the user's writing samples; ingest them.
   - If no samples are available and you intend to proceed without voice calibration, call `skip_writing_style_calibration(job_id, reason="…")` and pass the returned `skip_token` to `create_job_from_artifacts(writing_style_skip_token=...)`. The server enforces this gate and will return `error.code="writing_style_required"` if you skip the decision.
   - The error response includes any samples already present in `inputs/writing_style/` so you do not need to be told they exist.
9. `ingest_writing_style_sample` for each user writing sample
10. `prepare_writing_style_content`
11. produce writing-style-content JSON
12. `submit_work_result`
13. `commit_writing_style_content`
14. `prepare_task_spec`
15. produce task-spec JSON
16. `submit_work_result`
17. `commit_task_spec`
18. `create_job_from_artifacts` (the server's writing-style gate fires here)
19. (if writing-style content exists) `attach_writing_style_to_job`
20. `prepare_topics`
21. `submit_work_result`
22. `commit_topics`
23. show the returned `candidate_topics` to the user and ask them to select or reject a topic
24. `select_topic` with `user_selection_evidence` or `reject_topic`
25. `create_research_plan`
26. `resolve_source_requests`
27. `prepare_research_notes`
28. `submit_work_result`
29. `commit_research_notes`
30. `prepare_outline`
31. `submit_work_result`
32. `commit_outline`
33. `prepare_draft`
34. `submit_work_result`
35. `commit_draft`
36. `prepare_style_revision`
37. if the response includes `windowing.mode == "windowed"`: for each window
    index returned, call `prepare_style_revision_window`, `submit_work_result`,
    and collect the `work_result_id`s. Otherwise produce a single
    style-revision JSON and `submit_work_result`.
38. `commit_style_revision` (pass the single `work_result_id` for short
    drafts, or the ordered list of per-window `work_result_id`s for windowed
    drafts)
39. if `commit_style_revision` returns a hard-tier rejection, re-prepare and
    re-submit only the windows it names, then call `commit_style_revision`
    again with the updated `work_result_id`s
40. `prepare_anti_ai_audit` (bounded single-skill audit on the assembled draft). REQUIRED: `prepare_validation` refuses with `anti_ai_audit_required` until a block-bound anti-AI audit has been committed for the exact draft being validated. A job-level older audit is not enough.
41. `submit_work_result` (produce the `anti_ai_self_check` JSON)
42. `commit_anti_ai_audit`
43. if the audit returns `audit_pass: false` with `revision_targets`, prefer
    `prepare_revision` with `selected_lenses=["anti_ai"]` and pass the
    `revision_targets` in `user_instruction`, then loop back to
    `prepare_anti_ai_audit`
44. `prepare_validation`
45. `submit_work_result`
46. `commit_validation`
47. if `commit_validation` reports failure: `prepare_revision` →
    `submit_work_result` → `commit_revision`, then loop back to
    `prepare_validation`. This loop is enforced: `export_markdown` refuses
    a draft whose latest validation did not pass (`validation_not_passing`)
    unless you pass `allow_failed_validation=True` deliberately.
48. `export_markdown`
49. after the user confirms the essay is good: optionally `cleanup_agent_run`

### Anti-AI audit stage (steps 39-42)

`prepare_anti_ai_audit` exists because the anti-AI writing skill is a soft-tier
contract that gets ignored when it lives inside a multi-goal drafting prompt.
The audit's system prompt contains ONLY the anti-AI skill. The response schema
forces the auditor to fill the seven self-check fields, grade each
writing-style guidance bullet, copy the current skill-file hash and draft hash,
and produce one `block_audit` row for every blank-line block (paragraph) of
`anti-ai-detection-SKILL.md` (~191 blocks, not the ~458 lines — block coverage
keeps the committed payload small enough to submit inline). Empty arrays,
missing block coverage, mismatched block hashes, stale skill hashes,
draft-evidence rows that do not point to the audited draft, missing
whole-essay review evidence for any guidance block, generic block-application
reasoning, or a draft hash that does not match the audited draft fail the
audit. Structural blocks (headings, rules) may use a light `status:"context"`
row.

The packet's `delegation.recommended=true` and `suggested_role="anti_ai_auditor"`.
It also declares `required_model_tier="frontier"`. Dispatch it with
`dispatch_subagent(..., model_tier="frontier")` in Codex, or with a
provider-specific frontier alias such as `model_tier="opus"` in Claude.
Lower tiers such as Haiku are rejected before a token is issued. A clean-context
frontier/highest-reasoning subagent with a single skill in its prompt produces
better audits than the main orchestrator carrying eight other concerns.

A committed audit produces a NEW draft version whose `anti_ai_self_check` field
is populated. The audit does not rewrite the prose; it only scores it. If
`audit_pass` is false, the orchestrator should use `revision_targets` to scope
a `prepare_revision` call before running validation.

Manual edits invalidate the audit. `save_user_edit` creates a new draft with
`anti_ai_self_check=None` and routes the run back to `prepare_anti_ai_audit`.
After any user edit, including edits made after export, re-run and commit the
anti-AI audit before validation or export.

### Topic selection

`commit_topics` returns `candidate_topics`, `requires_user_topic_selection=true`,
and a `selection_contract`. The orchestrator must present those options to the
user before selecting one. `select_topic` rejects calls that omit
`user_selection_evidence`, because otherwise an agent can silently choose a
topic without exposing the alternatives.

### Writing-style ingestion (voice calibration)

The anti-AI writing skill explicitly requires that the rewrite match the user's
authentic voice rather than a generic "human-sounding" target. If the user has
not provided writing samples, ask for one or two short samples (a paragraph
each from a different context — a different class, a personal email, a
journal entry) before drafting.

Where the user should put the files:

- `ingest_writing_style_sample(path)` accepts any absolute or relative path,
  so the user can keep samples anywhere the process can read.
- Recommended convention: `<repo-root>/inputs/writing_style/` (mirrors the
  pattern used for source documents). Not enforced.
- Supported formats: PDF, DOCX, TXT, MD.
- The original file is copied into the app's data directory on ingest, so
  the user can move or delete the source after a successful ingest.
- Samples are stored under `${ESSAY_DATA_DIR}/writing_style/samples/` and
  survive across jobs. A user who ingested a sample for a previous job does
  not need to re-ingest it.

Run `ingest_writing_style_sample` for each sample, then
`prepare_writing_style_content` + `commit_writing_style_content`, then
`attach_writing_style_to_job` after `create_job_from_artifacts`. Once a job
has attached writing-style content, every subsequent `prepare_draft`,
`prepare_style_revision`, `prepare_style_revision_window`, and
`prepare_revision` packet will carry the rendered style block in its
`prompt_blocks`. If no sample is available, proceed anyway and warn the user
that the anti-AI pass will run without voice calibration.

### Windowed style revision (long drafts)

`prepare_style_revision` automatically switches to a windowed flow for drafts
above the configured length threshold (currently ~1200 words). The response
will contain `windowing.mode == "windowed"` plus a `windowing.windows` array
describing each window's paragraph range and word count. You must call
`prepare_style_revision_window` for every window index in that array — do not
skip any. Each window packet carries the full anti-AI skill in its
`system_prompt`, the window prose, transition paragraphs on either side
(when present), and a window-level deterministic check result. Generate one
JSON object per window matching `STYLE_REVISION_SCHEMA`, submit each via
`submit_work_result`, and then pass the ordered list of resulting
`work_result_id`s to `commit_style_revision`.

For short drafts the response will not contain a windowing plan; treat
`prepare_style_revision` as a single packet exactly like the older flow.

### Hard-tier rejection at commit

`commit_style_revision` and `commit_revision` run hard-tier deterministic
checks against the assembled output before persisting a new draft. If any
of the following are present, commit rejects:

- em dashes (U+2014)
- decorative en-dash or hyphen pauses
- tier-1 flagged vocabulary (delve, leverage, robust, utilize, foster, etc.)
- bad conclusion openers ("In conclusion," "In summary," "Overall,")
- signposting phrases ("Having examined…", "Let's now turn to…", etc.)
- triplet + contrastive-negation combos

A hard-tier rejection response includes the offending counts and (for windowed
revisions) the window indices that produced them, plus
`next_suggested_tools`. Fix the flagged patterns in the relevant window(s)
only and re-submit; do not re-do windows that were already accepted.

The `prepare_style_revision` → `commit_style_revision` pair is the prose-only
anti-AI rewrite pass. Its `system_prompt` embeds the full anti-AI writing
skill; skipping this step or generating the rewrite under your own system
instructions will produce text that reads as machine-generated. Skip it only
when the user has explicitly opted out (for example, a research note where the
AI-flavored register is acceptable). If skipped, `commit_draft` is followed
directly by `prepare_validation` against the unrevised draft.

## Cleanup after a successful run

After `export_markdown` returns and the user has explicitly confirmed the essay is acceptable, you MAY offer to delete the verbose workflow logs. Treat cleanup as user-initiated, never automatic, and follow this sequence exactly:

1. Ask the user to confirm the essay is acceptable and that they want to free disk space. Do not assume.
2. Call `cleanup_agent_run` with `confirm=False` first. This is a dry-run that returns counts and byte totals per category under `would_delete` and `preserved`. Show the preview to the user verbatim.
3. Only after the user explicitly approves the specific scope and counts in the preview, call `cleanup_agent_run` again with the same `scope` and `confirm=True`. The second call performs the deletion.
4. If the user is unsure, default to `scope="workflow_logs"` (the safest tier). Never default to `"all_except_export"` without an explicit user choice.

Scopes:
- `workflow_logs` (default): deletes agent-run events, agent-run checkpoints, work packets, work results, work commits, and source-packet bundles for this run. Preserves the agent-run record, the job, all drafts, all exports, validation reports, outlines, research, topics, task specs, uploaded source files, and ingested writing-style samples plus their derived writing-style content.
- `intermediate_artifacts`: also deletes research plans, topics, evidence maps / research reports, outlines, validation reports, and older draft versions. Preserves the latest draft, exports, task specs, sources, the job record, and the agent-run record.
- `all_except_export`: also deletes all drafts, the job record, and the agent-run record. Preserves exports, task specs, and uploaded sources. Use only when the user explicitly says they only want to keep the final exported markdown.

If `cleanup_agent_run` returns `cleanup_blocked_active_run`, the agent run still has pending work packets. Resolve or commit them first, or pass `force=True` only if the user explicitly accepts losing the in-flight work.

## Subagents

Use subagents for source-card packets, deep source reading, web-research capture, topic feasibility checks, and independent validation lenses. Keep final synthesis, final thesis choice, draft commits, style-revision commits, validation commits, revision commits, export, and cleanup under the main orchestrator unless a future bounded-write packet explicitly allows otherwise.

## Claude Code: /essay-prep and /essay-write

In Claude Code you can drive this workflow deterministically with two saved
Dynamic Workflows in `.claude/workflows/`: `/essay-prep` (runs to the topic
gate, then stops for the user to choose a topic) and `/essay-write` (commits the
chosen topic, then runs to export). Both loop on the read-only
`get_workflow_progress(agent_run_id)` ledger and act only on its
`next_required_step`, so no required step is skipped. Other harnesses (Codex,
etc.) drive the same tools manually as described above.
