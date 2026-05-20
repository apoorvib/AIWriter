# EssayWriter Agent Tool Mode Instructions

You are orchestrating EssayWriter through local Agent Tool Mode tools.

## Non-Negotiable Rules

1. Use only Agent Tool Mode tools for persisted essay workflow actions.
2. Do not call Pipeline Mode, backend API routes, provider adapters, or configured app LLM clients unless the user explicitly opts into API-backed Pipeline Mode.
3. Start or recover an AgentRun before doing stateful work.
4. Treat persisted AgentRun state as authoritative and chat memory as advisory.
5. For model-reasoning stages, call `prepare_*`, produce JSON matching `response_schema`, call `submit_work_result`, then call the named `commit_*` tool.
6. **For every `prepare_*` work packet, the `system_prompt` field returned by the tool IS the system message you MUST use when generating the JSON. Do not summarize it, skip it, paraphrase it, or substitute your own.** The `prompt_blocks` array contains the user message(s) in order. `response_schema` defines only the output shape. Skipping `system_prompt` silently bypasses the prompt engineering the workflow depends on — grounding rules, source-trust boundaries, anti-AI writing rules, and stage-specific output contracts. If you cannot or will not honor a packet's `system_prompt`, stop and report it instead of producing a result.
7. Prefer `work_result_id` for commits.
8. Never invent source IDs, page numbers, note IDs, packet IDs, work packet IDs, work result IDs, draft IDs, validation IDs, or export IDs.
9. If `blocked_on` is present, ask the user to resolve it before continuing.
10. If context was compacted or you are unsure what happened, call `recover_agent_run` before taking another state-changing action.
11. If a work packet has `delegation.recommended=true` and your harness supports subagents, delegate the packet unless the user disabled subagents or the packet is small enough to handle directly. When delegating, the subagent must also use the packet's `system_prompt` verbatim — pass it through, do not strip it.

## Normal Flow

This is the target workflow surface. During partial implementation, call only tools listed in `currently_callable_tools`; use `planned_workflow_tools` as the roadmap for later Agent Tool Mode capabilities.

1. `get_harness_instructions`
2. `start_agent_run` or `recover_agent_run`
3. `ingest_source_file`
4. `prepare_source_card`
5. produce source-card JSON
6. `submit_work_result`
7. `commit_source_card`
8. (recommended) `ingest_writing_style_sample` for each user writing sample
9. (recommended) `prepare_writing_style_content`
10. (recommended) produce writing-style-content JSON
11. (recommended) `submit_work_result`
12. (recommended) `commit_writing_style_content`
13. `prepare_task_spec`
14. produce task-spec JSON
15. `submit_work_result`
16. `commit_task_spec`
17. `create_job_from_artifacts`
18. (if writing-style content exists) `attach_writing_style_to_job`
19. `prepare_topics`
20. `submit_work_result`
21. `commit_topics`
22. ask the user to select or reject a topic
23. `select_topic` or `reject_topic`
24. `create_research_plan`
25. `resolve_source_requests`
26. `prepare_research_notes`
27. `submit_work_result`
28. `commit_research_notes`
29. `prepare_outline`
30. `submit_work_result`
31. `commit_outline`
32. `prepare_draft`
33. `submit_work_result`
34. `commit_draft`
35. `prepare_style_revision`
36. if the response includes `windowing.mode == "windowed"`: for each window
    index returned, call `prepare_style_revision_window`, `submit_work_result`,
    and collect the `work_result_id`s. Otherwise produce a single
    style-revision JSON and `submit_work_result`.
37. `commit_style_revision` (pass the single `work_result_id` for short
    drafts, or the ordered list of per-window `work_result_id`s for windowed
    drafts)
38. if `commit_style_revision` returns a hard-tier rejection, re-prepare and
    re-submit only the windows it names, then call `commit_style_revision`
    again with the updated `work_result_id`s
39. `prepare_validation`
40. `submit_work_result`
41. `commit_validation`
42. if `commit_validation` reports failure: `prepare_revision` →
    `submit_work_result` → `commit_revision`, then loop back to
    `prepare_validation`
43. `export_markdown`
44. after the user confirms the essay is good: optionally `cleanup_agent_run`

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
