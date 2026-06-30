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
//   3. Pre-job prelude (deterministic, ordered, before the ledger loop):
//      a. Source cards — for each source without a committed card:
//         prepare_source_card → generate JSON → submit → commit.
//      b. Writing-style content (content path only):
//         prepare_writing_style_content → generate JSON → submit → commit; save content_id.
//      c. Task spec:
//         prepare_task_spec → generate JSON → submit → commit.
//      d. Create job:
//         skip_writing_style_calibration (provisional job_id) → create_job_from_artifacts;
//         then attach_writing_style_to_job (content path only) to supersede the skip.
//   4. Driver loop: call get_workflow_progress, dispatch one subagent per
//      next_required_step until segment !== "prep" or all_required_done.
//      After the prelude, this loop typically starts at "topics".
//   5. Present candidate topics and stop for the human topic-selection gate.
//
// Design note on writing_style_decision (pre-job prelude approach):
//   The ledger (as of fix 4496675) always returns next_required_step="job_created" before
//   a job exists, because source_cards / task_spec / writing_style_decision cannot be
//   verified server-side until a job is present. These steps are instead driven as a
//   deterministic prelude enforced by the create_job_from_artifacts gate:
//     - Every source_id must have a committed source card.
//     - A task spec must be committed.
//     - create_job_from_artifacts REQUIRES a writing_style_skip_token at creation time
//       (writing-style CONTENT can only attach post-job via attach_writing_style_to_job).
//   Skip path:  skip_writing_style_calibration(provisional_job_id) → create_job_from_artifacts.
//   Content path: commit writing-style content first; then same skip-token flow;
//     then attach_writing_style_to_job to supersede the provisional skip with real content.
//   After the prelude the ledger sees job_created / source_cards / task_spec /
//   writing_style_decision all satisfied and reports next_required_step="topics".

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
  //    Writing-style SKIP is handled at job-creation time (prelude step d).
  // -------------------------------------------------------------------------
  const wsIngestPrompt = a.writing_style_paths === "skip"
    ? "No writing-style ingestion needed — the user will skip calibration when the job is created."
    : a.writing_style_paths && a.writing_style_paths.length > 0
      ? `For each path in ${JSON.stringify(a.writing_style_paths)}, call mcp__essaywriter__ingest_writing_style_sample(sample_path=<path>, agent_run_id="${runId}").`
      : "No writing-style sample paths provided — skip writing-style ingestion.";

  const srcIngestPrompt = a.source_paths && a.source_paths.length > 0
    ? `For each path in ${JSON.stringify(a.source_paths)}, call mcp__essaywriter__ingest_source_file(document_path=<path>, agent_run_id="${runId}").`
    : "No source paths provided — skip source ingestion.";

  const ingestRaw = await agent({
    prompt: `You are ingesting source files and writing-style samples for agent_run_id="${runId}".

Source ingestion:
${srcIngestPrompt}

Writing-style ingestion:
${wsIngestPrompt}

Collect the source_id returned by EACH ingest_source_file call, in order.
Return ONLY raw JSON { "ok": true, "source_ids": [<every ingested source_id, in order>], "style_samples_ingested": <count> }.`,
    tools: [
      "mcp__essaywriter__ingest_source_file",
      "mcp__essaywriter__ingest_writing_style_sample",
    ],
  });

  // The script holds the full ingested source_id list in a variable (bug_010):
  // AgentRun.artifact_refs dict-merges and keeps only the LAST source_id, so a
  // subagent reading the run state would commit a card for one source and drop
  // the rest. Thread the list explicitly instead.
  const sourceIds = extractJson(ingestRaw.result).source_ids || [];
  if (a.source_paths && a.source_paths.length > 0 && sourceIds.length === 0) {
    throw new Error("ingestion returned no source_ids");
  }

  // Mint the provisional job_id in the SCRIPT, not the clockless LLM (bug_004).
  // runId is unique per run, so this cannot collide with another prep run.
  const provisionalJobId = `job-prov-${runId}`;

  // -------------------------------------------------------------------------
  // 3a. Pre-job prelude — source cards.
  //     For each ingested source without a committed card:
  //     prepare_source_card → generate JSON → submit → commit.
  // -------------------------------------------------------------------------
  await agent({
    prompt: `You are executing the SOURCE CARDS prelude step for agent_run_id="${runId}".

The ingested source_ids are: ${JSON.stringify(sourceIds)}.
Commit a source card for EVERY one of those source_ids — do not skip any. For each:
   a. Call mcp__essaywriter__prepare_source_card(source_id=<id>, agent_run_id="${runId}").
   b. Read the returned system_prompt VERBATIM and use it to generate the JSON result.
   c. Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your JSON.
   d. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
   e. Call mcp__essaywriter__commit_source_card(work_result_id=<id>, agent_run_id="${runId}").
Return ONLY raw JSON: { "ok": true, "cards_committed": <count> }.`,
    tools: [
      "mcp__essaywriter__prepare_source_card",
      "mcp__essaywriter__submit_work_result",
      "mcp__essaywriter__commit_source_card",
      "mcp__essaywriter__get_work_packet",
    ],
  });

  // -------------------------------------------------------------------------
  // 3b. Pre-job prelude — writing-style content (content path only).
  //     prepare_writing_style_content → generate JSON → submit → commit.
  //     Save content_id for use in the create-job step (3d).
  //     Skip path defers to the skip_writing_style_calibration call in 3d.
  // -------------------------------------------------------------------------
  let contentId = null;
  if (a.writing_style_paths !== "skip" && a.writing_style_paths && a.writing_style_paths.length > 0) {
    const wsContentRaw = await agent({
      prompt: `You are executing the WRITING-STYLE CONTENT prelude step for agent_run_id="${runId}".

1. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to get the ingested writing-style sample_ids.
2. Call mcp__essaywriter__prepare_writing_style_content(sample_ids=[<ids>], agent_run_id="${runId}").
3. Read the returned system_prompt VERBATIM and use it to generate the JSON result.
4. Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your JSON.
5. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
6. Call mcp__essaywriter__commit_writing_style_content(work_result_id=<id>, agent_run_id="${runId}"). Note the returned content_id.
Return ONLY raw JSON: { "ok": true, "content_id": "<content_id>" }.`,
      tools: [
        "mcp__essaywriter__get_agent_run_state",
        "mcp__essaywriter__prepare_writing_style_content",
        "mcp__essaywriter__submit_work_result",
        "mcp__essaywriter__commit_writing_style_content",
        "mcp__essaywriter__get_work_packet",
      ],
    });
    contentId = extractJson(wsContentRaw.result).content_id;
    if (!contentId) throw new Error("commit_writing_style_content did not return content_id");
  }

  // -------------------------------------------------------------------------
  // 3c. Pre-job prelude — task spec.
  //     prepare_task_spec → generate JSON → submit → commit.
  // -------------------------------------------------------------------------
  const assignmentHint = a.assignment_text
    ? `The raw assignment text is:\n---\n${a.assignment_text}\n---\nUse this as the raw_text argument.`
    : a.assignment_path
      ? `The assignment file is at: ${a.assignment_path}. Read its content and use it as raw_text.`
      : `No explicit assignment was provided. Derive the task spec from the ingested source content.`;

  await agent({
    prompt: `You are executing the TASK SPEC prelude step for agent_run_id="${runId}".

${assignmentHint}

1. Call mcp__essaywriter__prepare_task_spec(raw_text=<assignment_text>, agent_run_id="${runId}").
2. Read the returned system_prompt VERBATIM and use it to generate the JSON result.
3. Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your JSON.
4. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
5. Call mcp__essaywriter__commit_task_spec(work_result_id=<id>, agent_run_id="${runId}").
Return ONLY raw JSON: { "ok": true, "task_spec_id": "<task_spec_id>" }.`,
    tools: [
      "mcp__essaywriter__prepare_task_spec",
      "mcp__essaywriter__submit_work_result",
      "mcp__essaywriter__commit_task_spec",
      "mcp__essaywriter__get_work_packet",
    ],
  });

  // -------------------------------------------------------------------------
  // 3d. Pre-job prelude — create job.
  //     create_job_from_artifacts REQUIRES a writing_style_skip_token at creation
  //     time regardless of path. skip_writing_style_calibration mints the token
  //     against a provisional job_id that is then passed to create_job_from_artifacts.
  //
  //     Skip path:  skip token is final — the skip warning remains on the job.
  //     Content path: skip token is provisional — attach_writing_style_to_job
  //       supersedes it with real content (clearing the skip warning).
  // -------------------------------------------------------------------------
  const createJobPrompt = contentId
    ? `You are executing the CREATE JOB prelude step (content path) for agent_run_id="${runId}".
Use these exact values — do NOT invent any IDs:
- provisional job_id: "${provisionalJobId}"
- source_ids: ${JSON.stringify(sourceIds)}
- writing-style content_id to attach after creation: "${contentId}"

1. Call mcp__essaywriter__skip_writing_style_calibration(job_id="${provisionalJobId}", reason="Provisional skip token for content path — will be superseded by attach_writing_style_to_job.", agent_run_id="${runId}"). Save the returned skip_token.
2. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to read the committed task_spec_id from artifact_refs/committed_artifact_refs.
3. Call mcp__essaywriter__create_job_from_artifacts(job_id="${provisionalJobId}", task_spec_id=<id>, source_ids=${JSON.stringify(sourceIds)}, writing_style_skip_token=<token>, agent_run_id="${runId}"). Save the returned job_id.
4. Call mcp__essaywriter__attach_writing_style_to_job(job_id=<job_id>, content_id="${contentId}", agent_run_id="${runId}") to supersede the provisional skip with real writing-style content.
Return ONLY raw JSON: { "ok": true, "job_id": "<job_id>" }.`
    : `You are executing the CREATE JOB prelude step (skip path) for agent_run_id="${runId}".
Use these exact values — do NOT invent any IDs:
- provisional job_id: "${provisionalJobId}"
- source_ids: ${JSON.stringify(sourceIds)}

1. Call mcp__essaywriter__skip_writing_style_calibration(job_id="${provisionalJobId}", reason="User chose to skip writing-style calibration for this prep run.", agent_run_id="${runId}"). Save the returned skip_token.
2. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to read the committed task_spec_id from artifact_refs/committed_artifact_refs.
3. Call mcp__essaywriter__create_job_from_artifacts(job_id="${provisionalJobId}", task_spec_id=<id>, source_ids=${JSON.stringify(sourceIds)}, writing_style_skip_token=<token>, agent_run_id="${runId}"). Save the returned job_id.
Return ONLY raw JSON: { "ok": true, "job_id": "<job_id>" }.`;

  const createJobTools = [
    "mcp__essaywriter__skip_writing_style_calibration",
    "mcp__essaywriter__get_agent_run_state",
    "mcp__essaywriter__create_job_from_artifacts",
  ];
  if (contentId) {
    createJobTools.push("mcp__essaywriter__attach_writing_style_to_job");
  }

  const createJobRaw = await agent({
    prompt: createJobPrompt,
    tools: createJobTools,
  });

  const jobId = extractJson(createJobRaw.result).job_id;
  if (!jobId) throw new Error("create_job_from_artifacts did not return job_id");

  // -------------------------------------------------------------------------
  // 4. Driver loop — remaining prep steps (typically starts at "topics").
  //    Source cards, task spec, job_created, and writing_style_decision are all
  //    satisfied by the prelude above. This loop is a safety net and drives the
  //    topics step (and any other steps the ledger reports after the prelude).
  // -------------------------------------------------------------------------
  const MAX_ITERATIONS = 20;
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

    await runPrepStep(runId, jobId, step);
  }

  if (guard > MAX_ITERATIONS) {
    return (
      `WARNING: driver loop hit the ${MAX_ITERATIONS}-iteration guard without ` +
      `completing all prep steps. Inspect agent_run_id=${runId} via ` +
      `mcp__essaywriter__get_workflow_progress to diagnose.`
    );
  }

  // -------------------------------------------------------------------------
  // 5. Present candidate topics and stop for the human gate.
  // -------------------------------------------------------------------------
  const summary = await agent({
    prompt: `Using job_id="${jobId}":
1. Call mcp__essaywriter__get_job_summary(job_id="${jobId}").
2. List all candidate topics in a clear numbered format with each topic_id.
   The user must pick one to continue to essay writing.
Return the formatted topic list as readable text.`,
    tools: [
      "mcp__essaywriter__get_job_summary",
    ],
  });

  return (
    `Prep complete — agent_run_id: ${runId}\n\n` +
    `Please choose a topic below, then run /essay-write with the selected topic_id.\n\n` +
    summary.result
  );


  // -------------------------------------------------------------------------
  // Remaining step dispatcher — handles topics and any other post-prelude steps.
  // Source cards, task spec, job_created, and writing_style_decision are fully
  // handled by the deterministic prelude above and will not appear here.
  // -------------------------------------------------------------------------
  async function runPrepStep(runId, jobId, step) {
    return agent({
      prompt: `You are executing ONE workflow step: "${step}" for agent_run_id="${runId}" and job_id="${jobId}".

General rules:
- For every prepare_* call, read the returned system_prompt VERBATIM and use it when generating the JSON result.
- Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your output JSON. mcp__essaywriter__submit_work_result rejects payloads missing this token.
- After generating the result, call mcp__essaywriter__submit_work_result, then the named commit_* tool.
- Never invent IDs — read all IDs from tool responses.

=== topics ===
1. Call mcp__essaywriter__prepare_topics(job_id="${jobId}", agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_topics(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "topics" }.

=== (any other step) ===
Call the step's prepare_* tool, generate JSON using system_prompt VERBATIM (ATTENTION CHECK token → "notes"), call mcp__essaywriter__submit_work_result, then the commit_* tool.
Return { "ok": true, "step_id": "${step}" }.`,
      tools: [
        "mcp__essaywriter__get_agent_run_state",
        "mcp__essaywriter__get_work_packet",
        "mcp__essaywriter__prepare_topics",
        "mcp__essaywriter__commit_topics",
        "mcp__essaywriter__submit_work_result",
      ],
    });
  }

})();
