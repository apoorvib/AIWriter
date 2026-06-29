// /essay-prep — drives Agent Tool Mode prep segment to the topic gate.
//
// IMPORTANT: agent() call shape follows the plan skeleton; confirm against
// the installed Claude Code Dynamic Workflows runtime before first real run.
//
// The top-level async IIFE is required for `node --check` compatibility.
// The Claude Code Dynamic Workflows runtime evaluates this script in an async
// context with `args` and `agent` injected into scope; the IIFE wrapper can
// be removed if the runtime already provides a top-level async scope.
//
// args: {
//   source_paths: string[],                  // paths to source documents to ingest
//   writing_style_paths: string[] | "skip",  // writing style sample paths, or "skip"
//   assignment_text?: string,                // raw assignment text (optional)
//   assignment_path?: string,                // path to assignment file (optional)
// }
//
// Workflow:
//   1. Start agent run + read harness instructions.
//   2. Ingest source files (and writing-style samples if provided).
//   3. Driver loop: call get_workflow_progress, dispatch one subagent per
//      next_required_step until segment !== "prep" or all_required_done.
//   4. Present candidate topics and stop for the human topic-selection gate.
//
// Design note on writing_style_decision:
//   The ledger marks writing_style_decision "done" only when a job exists AND
//   has a writing-style decision recorded (content attached OR skip token set).
//   Because job_created is serial and blocked by writing_style_decision, the
//   writing_style_decision subagent is expected to ALSO call
//   create_job_from_artifacts — making both steps done in a single pass.
//   The job_created step as a standalone next_required_step will rarely appear.

(async () => {

  const a = args || {};

  // -------------------------------------------------------------------------
  // 1. Start the run and read harness instructions.
  // -------------------------------------------------------------------------
  const setup = await agent({
    prompt: `Call mcp__essaywriter__start_agent_run with objective="Essay prep — source ingestion, task spec, writing-style decision, topic ideation". Then call mcp__essaywriter__get_harness_instructions with the agent_run_id from the start result. Return ONLY a raw JSON object (no markdown, no extra text): { "agent_run_id": "<id>" }`,
    tools: [
      "mcp__essaywriter__start_agent_run",
      "mcp__essaywriter__get_harness_instructions",
    ],
  });

  // Robustly extract a JSON object from an agent result string.
  function extractJson(raw) {
    if (!raw) throw new Error("Empty agent result");
    try { return JSON.parse(raw); } catch (_) {}
    const m = raw.match(/\{[\s\S]*\}/);
    if (!m) throw new Error("No JSON object found in agent result: " + raw);
    return JSON.parse(m[0]);
  }

  const runId = extractJson(setup.result).agent_run_id;
  if (!runId) throw new Error("start_agent_run did not return agent_run_id");

  // -------------------------------------------------------------------------
  // 2. Ingest sources (and writing-style samples if provided).
  //    Writing-style SKIP is deferred because skip_writing_style_calibration
  //    requires a job_id, which does not exist yet at this point.
  // -------------------------------------------------------------------------
  const wsIngestPrompt = a.writing_style_paths === "skip"
    ? "No writing-style ingestion needed — the user will skip calibration when the job is created."
    : a.writing_style_paths && a.writing_style_paths.length > 0
      ? `For each path in ${JSON.stringify(a.writing_style_paths)}, call mcp__essaywriter__ingest_writing_style_sample(sample_path=<path>, agent_run_id="${runId}").`
      : "No writing-style sample paths provided — skip writing-style ingestion.";

  const srcIngestPrompt = a.source_paths && a.source_paths.length > 0
    ? `For each path in ${JSON.stringify(a.source_paths)}, call mcp__essaywriter__ingest_source_file(document_path=<path>, agent_run_id="${runId}").`
    : "No source paths provided — skip source ingestion.";

  await agent({
    prompt: `You are ingesting source files and writing-style samples for agent_run_id="${runId}".

Source ingestion:
${srcIngestPrompt}

Writing-style ingestion:
${wsIngestPrompt}

Return JSON { "ok": true, "sources_ingested": <count>, "style_samples_ingested": <count> }.`,
    tools: [
      "mcp__essaywriter__ingest_source_file",
      "mcp__essaywriter__ingest_writing_style_sample",
    ],
  });

  // -------------------------------------------------------------------------
  // 3. Driver loop — one subagent per next_required_step.
  // -------------------------------------------------------------------------
  const MAX_ITERATIONS = 40;
  let guard = 0;

  while (guard++ < MAX_ITERATIONS) {
    const progressRaw = await agent({
      prompt: `Call mcp__essaywriter__get_workflow_progress(agent_run_id="${runId}") and return the tool result JSON verbatim, with no additional text or markdown wrapping.`,
      tools: ["mcp__essaywriter__get_workflow_progress"],
    });

    const progress = extractJson(progressRaw.result);

    // Exit when prep segment is complete or a different segment is active.
    if (progress.segment !== "prep" || progress.all_required_done) break;

    const step = progress.next_required_step;
    if (!step) break; // only needs_human or permanently blocked steps remain

    await runPrepStep(runId, step, a);
  }

  if (guard > MAX_ITERATIONS) {
    return (
      `WARNING: driver loop hit the ${MAX_ITERATIONS}-iteration guard without ` +
      `completing all prep steps. Inspect agent_run_id=${runId} via ` +
      `mcp__essaywriter__get_workflow_progress to diagnose.`
    );
  }

  // -------------------------------------------------------------------------
  // 4. Present candidate topics and stop for the human gate.
  // -------------------------------------------------------------------------
  const summary = await agent({
    prompt: `Using agent_run_id="${runId}":
1. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to obtain job_id.
2. Call mcp__essaywriter__get_job_summary(job_id=<job_id>).
3. List all candidate topics in a clear numbered format with each topic_id.
   The user must pick one to continue to essay writing.
Return the formatted topic list as readable text.`,
    tools: [
      "mcp__essaywriter__get_agent_run_state",
      "mcp__essaywriter__get_job_summary",
    ],
  });

  return (
    `Prep complete — agent_run_id: ${runId}\n\n` +
    `Please choose a topic below, then run /essay-write with the selected topic_id.\n\n` +
    summary.result
  );


  // -------------------------------------------------------------------------
  // Step dispatcher — one subagent per workflow step.
  // -------------------------------------------------------------------------
  async function runPrepStep(runId, step, a) {
    // Writing-style context for the writing_style_decision subagent.
    // NOTE: The writing_style_decision step also creates the job because the
    // ledger only marks writing_style_decision "done" once the job exists with
    // a decision recorded. This means job_created and writing_style_decision
    // are both satisfied in one subagent pass.
    const wsDecisionInstructions = a.writing_style_paths === "skip"
      ? `The user elected to SKIP writing-style calibration.
  a) Choose a deterministic provisional job_id (e.g. "job-prep-" + a short uuid or timestamp).
  b) Call mcp__essaywriter__skip_writing_style_calibration(job_id=<provisional_id>, reason="User chose to skip writing-style calibration for this prep run.", agent_run_id="${runId}") and save the returned skip_token.
  c) Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to get committed task_spec_id and source_ids from artifact_refs/committed_artifact_refs.
  d) Call mcp__essaywriter__create_job_from_artifacts(task_spec_id=<id>, source_ids=[<ids>], job_id=<provisional_id>, writing_style_skip_token=<token>, agent_run_id="${runId}").`
      : `Writing-style samples were ingested in the setup step.
  a) Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to get ingested sample_ids and committed task_spec_id/source_ids.
  b) Call mcp__essaywriter__prepare_writing_style_content(sample_ids=[<ids>], agent_run_id="${runId}"). Using the returned system_prompt VERBATIM, generate JSON matching response_schema (copy ATTENTION CHECK token into a "notes" field). Call mcp__essaywriter__submit_work_result, then mcp__essaywriter__commit_writing_style_content. Save the returned content_id.
  c) Call mcp__essaywriter__create_job_from_artifacts(task_spec_id=<id>, source_ids=[<ids>], agent_run_id="${runId}"). Save the returned job_id.
  d) Call mcp__essaywriter__attach_writing_style_to_job(job_id=<job_id>, content_id=<content_id>, agent_run_id="${runId}").`;

    // Assignment hint for the task_spec subagent.
    const assignmentHint = a.assignment_text
      ? `The raw assignment text is:\n---\n${a.assignment_text}\n---\nUse this as the raw_text argument.`
      : a.assignment_path
        ? `The assignment file is at: ${a.assignment_path}. Read its content and use it as raw_text.`
        : `No explicit assignment was provided. Derive the task spec from the ingested source content.`;

    return agent({
      prompt: `You are executing ONE workflow step: "${step}" for agent_run_id="${runId}".

General rules:
- For every prepare_* call, read the returned system_prompt VERBATIM and use it when generating the JSON result.
- Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your output JSON. mcp__essaywriter__submit_work_result rejects payloads missing this token.
- After generating the result, call mcp__essaywriter__submit_work_result, then the named commit_* tool.
- Never invent IDs — read all IDs from tool responses.

=== source_cards ===
1. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to list source_ids and check which already have committed source cards.
2. For EACH source without a committed card:
   a. Call mcp__essaywriter__prepare_source_card(source_id=<id>, agent_run_id="${runId}").
   b. Generate JSON matching response_schema using the packet's system_prompt VERBATIM (ATTENTION CHECK token → "notes").
   c. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
   d. Call mcp__essaywriter__commit_source_card(work_result_id=<id>, agent_run_id="${runId}").
3. Return { "ok": true, "step_id": "source_cards" }.

=== writing_style_decision ===
This step ALSO creates the job (both writing_style_decision and job_created become done after this step).
${wsDecisionInstructions}
Return { "ok": true, "step_id": "writing_style_decision", "job_id": "<job_id>" }.

=== task_spec ===
${assignmentHint}
1. Call mcp__essaywriter__prepare_task_spec(raw_text=<assignment_text>, agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_task_spec(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "task_spec", "task_spec_id": "<id>" }.

=== job_created ===
The job is typically already created during the writing_style_decision step.
1. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to check job_id.
2. If job_id is already present: return { "ok": true, "step_id": "job_created", "already_created": true }.
3. If not: call mcp__essaywriter__create_job_from_artifacts using committed task_spec_id and source_ids.
   ${a.writing_style_paths === "skip"
       ? "Pass writing_style_skip_token from skip_writing_style_calibration if available."
       : "Then call mcp__essaywriter__attach_writing_style_to_job if writing-style content_id is available."}
Return { "ok": true, "step_id": "job_created", "job_id": "<id>" }.

=== topics ===
1. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to get job_id.
2. Call mcp__essaywriter__prepare_topics(job_id=<job_id>, agent_run_id="${runId}").
3. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
4. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
5. Call mcp__essaywriter__commit_topics(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "topics" }.

=== (any other step) ===
Call the step's prepare_* tool, generate JSON using system_prompt VERBATIM (ATTENTION CHECK token → "notes"), call mcp__essaywriter__submit_work_result, then the commit_* tool.
Return { "ok": true, "step_id": "${step}" }.`,
      tools: [
        "mcp__essaywriter__get_agent_run_state",
        "mcp__essaywriter__get_work_packet",
        "mcp__essaywriter__prepare_source_card",
        "mcp__essaywriter__commit_source_card",
        "mcp__essaywriter__prepare_writing_style_content",
        "mcp__essaywriter__commit_writing_style_content",
        "mcp__essaywriter__attach_writing_style_to_job",
        "mcp__essaywriter__skip_writing_style_calibration",
        "mcp__essaywriter__prepare_task_spec",
        "mcp__essaywriter__commit_task_spec",
        "mcp__essaywriter__create_job_from_artifacts",
        "mcp__essaywriter__prepare_topics",
        "mcp__essaywriter__commit_topics",
        "mcp__essaywriter__submit_work_result",
      ],
    });
  }

})();
