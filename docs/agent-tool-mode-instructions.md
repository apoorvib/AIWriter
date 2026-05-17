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
8. `prepare_task_spec`
9. produce task-spec JSON
10. `submit_work_result`
11. `commit_task_spec`
12. `create_job_from_artifacts`
13. `prepare_topics`
14. `submit_work_result`
15. `commit_topics`
16. ask the user to select or reject a topic
17. `select_topic` or `reject_topic`
18. `create_research_plan`
19. `resolve_source_requests`
20. `prepare_research_notes`
21. `submit_work_result`
22. `commit_research_notes`
23. `prepare_outline`
24. `submit_work_result`
25. `commit_outline`
26. `prepare_draft`
27. `submit_work_result`
28. `commit_draft`
29. `prepare_style_revision`
30. `submit_work_result`
31. `commit_style_revision`
32. `prepare_validation`
33. `submit_work_result`
34. `commit_validation`
35. `export_markdown`

The `prepare_style_revision` → `commit_style_revision` pair is the prose-only anti-AI rewrite pass. Its `system_prompt` embeds the full anti-AI writing skill; skipping this step or generating the rewrite under your own system instructions will produce text that reads as machine-generated. Skip it only when the user has explicitly opted out (for example, a research note where the AI-flavored register is acceptable). If skipped, `commit_draft` is followed directly by `prepare_validation` against the unrevised draft.

## Subagents

Use subagents for source-card packets, deep source reading, web-research capture, topic feasibility checks, and independent validation lenses. Keep final synthesis, final thesis choice, draft commits, style-revision commits, validation commits, revision commits, and export under the main orchestrator unless a future bounded-write packet explicitly allows otherwise.
