// /essay-write — drives Agent Tool Mode write segment to export.
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
//   agent_run_id: string,              // from /essay-prep run
//   job_id: string,                    // from /essay-prep run
//   round_number: number,              // topic round number (usually 1)
//   topic_id: string,                  // the topic the user selected
//   user_selection_evidence: string,   // user's reasoning or confirmation text
// }
//
// Workflow:
//   1. Recover agent run + read harness instructions.
//   2. Commit the user's topic choice via select_topic.
//   3. Driver loop: call get_workflow_progress, dispatch one subagent per
//      next_required_step until all_required_done.
//      - Anti-AI audit step uses a two-call frontier dispatch (setup + opus auditor).
//      - Targeted verifiers (Approach C) run after audit and validation steps.
//   4. Return export-ready confirmation.

(async () => {

  const a = args || {};
  const runId = a.agent_run_id;
  const jobId = a.job_id;

  if (!runId) throw new Error("args.agent_run_id is required");
  if (!jobId) throw new Error("args.job_id is required");
  if (!a.topic_id) throw new Error("args.topic_id is required");

  // Robustly extract a JSON object from an agent result string.
  function extractJson(raw) {
    if (!raw) throw new Error("Empty agent result");
    try { return JSON.parse(raw); } catch (_) {}
    const m = raw.match(/\{[\s\S]*\}/);
    if (!m) throw new Error("No JSON object found in agent result: " + raw);
    return JSON.parse(m[0]);
  }

  // -------------------------------------------------------------------------
  // 1. Recover the run and read harness instructions.
  // -------------------------------------------------------------------------
  await agent({
    prompt: `Call mcp__essaywriter__recover_agent_run(agent_run_id="${runId}") then call mcp__essaywriter__get_harness_instructions(agent_run_id="${runId}"). Return ONLY raw JSON (no markdown, no extra text): { "ok": true }.`,
    tools: [
      "mcp__essaywriter__recover_agent_run",
      "mcp__essaywriter__get_harness_instructions",
    ],
  });

  // -------------------------------------------------------------------------
  // 2. Commit the human topic choice (the gate that forced segmentation).
  // -------------------------------------------------------------------------
  await agent({
    prompt: `Call mcp__essaywriter__select_topic(job_id="${jobId}", round_number=${a.round_number || 1}, topic_id="${a.topic_id}", user_selection_evidence=${JSON.stringify(a.user_selection_evidence || "")}, agent_run_id="${runId}"). Return ONLY raw JSON: { "ok": true }.`,
    tools: ["mcp__essaywriter__select_topic"],
  });

  // -------------------------------------------------------------------------
  // 3. Driver loop — one subagent per next_required_step.
  // -------------------------------------------------------------------------
  const MAX_ITERATIONS = 60;
  let guard = 0;

  while (guard++ < MAX_ITERATIONS) {
    const progressRaw = await agent({
      prompt: `Call mcp__essaywriter__get_workflow_progress(agent_run_id="${runId}") and return the tool result JSON verbatim, with no additional text or markdown wrapping.`,
      tools: ["mcp__essaywriter__get_workflow_progress"],
    });

    const progress = extractJson(progressRaw.result);

    if (progress.all_required_done) break;

    const step = progress.next_required_step;
    if (!step) break; // only needs_human or permanently blocked steps remain

    if (step === "anti_ai_audit") {
      // Two-call frontier dispatch: setup mints the token, then the opus auditor consumes it.
      await runAuditStep(runId, jobId);
      // Targeted verifier: confirm anti_ai_self_check populated, revise if needed.
      await verifyAuditOrRevise(runId, jobId);
    } else {
      await runWriteStep(runId, step);
      // Targeted verifier: confirm validation passed, revise + re-validate if needed.
      if (step === "validation") {
        await verifyValidationOrRevise(runId, jobId);
      }
    }
  }

  if (guard > MAX_ITERATIONS) {
    return (
      `WARNING: driver loop hit the ${MAX_ITERATIONS}-iteration guard without ` +
      `completing all write steps. Inspect agent_run_id=${runId} via ` +
      `mcp__essaywriter__get_workflow_progress to diagnose.`
    );
  }

  return `Write segment complete for agent_run_id=${runId}. Export ready. Review the exported essay, then optionally run cleanup.`;


  // -------------------------------------------------------------------------
  // General write step dispatcher — prepare → submit → commit.
  // -------------------------------------------------------------------------
  async function runWriteStep(runId, step) {
    return agent({
      prompt: `You are executing ONE workflow step: "${step}" for agent_run_id="${runId}" and job_id="${jobId}".

General rules:
- For every prepare_* call, read the returned system_prompt VERBATIM and use it when generating the JSON result.
- Copy the ATTENTION CHECK token from system_prompt into a "notes" field in your output JSON. mcp__essaywriter__submit_work_result rejects payloads missing this token.
- After generating the result, call mcp__essaywriter__submit_work_result, then the named commit_* tool.
- Never invent IDs — read all IDs from tool responses.

=== research_plan ===
1. Call mcp__essaywriter__create_research_plan(job_id="${jobId}", agent_run_id="${runId}").
2. Call mcp__essaywriter__resolve_source_requests(job_id="${jobId}", agent_run_id="${runId}") to resolve any source fetch requests.
Return { "ok": true, "step_id": "research_plan" }.

=== research_notes ===
1. Call mcp__essaywriter__prepare_research_notes(job_id="${jobId}", agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_research_notes(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "research_notes" }.

=== outline ===
1. Call mcp__essaywriter__prepare_outline(job_id="${jobId}", agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_outline(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "outline" }.

=== draft ===
1. Call mcp__essaywriter__prepare_draft(job_id="${jobId}", agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_draft(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "draft" }.

=== style_revision ===
1. Call mcp__essaywriter__prepare_style_revision(job_id="${jobId}", agent_run_id="${runId}").
   If the server returns a window-based packet, also call mcp__essaywriter__prepare_style_revision_window as directed.
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_style_revision(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "style_revision" }.

=== validation ===
1. Call mcp__essaywriter__prepare_validation(job_id="${jobId}", agent_run_id="${runId}").
2. Generate JSON using the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
4. Call mcp__essaywriter__commit_validation(work_result_id=<id>, agent_run_id="${runId}").
Return { "ok": true, "step_id": "validation" }.

=== export ===
1. Call mcp__essaywriter__export_markdown(job_id="${jobId}", agent_run_id="${runId}").
Return { "ok": true, "step_id": "export" }.

=== (any other step) ===
Call the step's prepare_* tool, generate JSON using system_prompt VERBATIM (ATTENTION CHECK token → "notes"), call mcp__essaywriter__submit_work_result, then the commit_* tool.
Return { "ok": true, "step_id": "${step}" }.`,
      tools: [
        "mcp__essaywriter__create_research_plan",
        "mcp__essaywriter__resolve_source_requests",
        "mcp__essaywriter__prepare_research_notes",
        "mcp__essaywriter__commit_research_notes",
        "mcp__essaywriter__prepare_outline",
        "mcp__essaywriter__commit_outline",
        "mcp__essaywriter__prepare_draft",
        "mcp__essaywriter__commit_draft",
        "mcp__essaywriter__prepare_style_revision",
        "mcp__essaywriter__prepare_style_revision_window",
        "mcp__essaywriter__commit_style_revision",
        "mcp__essaywriter__prepare_validation",
        "mcp__essaywriter__commit_validation",
        "mcp__essaywriter__export_markdown",
        "mcp__essaywriter__submit_work_result",
        "mcp__essaywriter__get_work_packet",
      ],
    });
  }

  // -------------------------------------------------------------------------
  // Anti-AI audit — delegation_required + frontier.
  // Two calls: setup mints the dispatch token; a fresh opus auditor consumes it.
  // -------------------------------------------------------------------------
  async function runAuditStep(runId, jobId) {
    const setupRaw = await agent({
      prompt: `Call mcp__essaywriter__prepare_anti_ai_audit(job_id="${jobId}", agent_run_id="${runId}"). Save the returned work_packet_id. Then call mcp__essaywriter__dispatch_subagent(work_packet_id=<that packet id>, role="anti_ai_auditor", model_tier="opus", agent_run_id="${runId}"). Return ONLY raw JSON (no markdown): { "work_packet_id": "<id>", "subagent_token": "<token>" }.`,
      tools: [
        "mcp__essaywriter__prepare_anti_ai_audit",
        "mcp__essaywriter__dispatch_subagent",
      ],
    });

    const setup = extractJson(setupRaw.result);

    await agent({
      model: "opus",
      prompt: `You are a clean-context anti-AI auditor operating with a pre-minted dispatch token.

1. Call mcp__essaywriter__get_work_packet(work_packet_id="${setup.work_packet_id}") to fetch your packet. Read the system_prompt VERBATIM — it contains the full anti-AI detection skill instructions.
2. Apply ONLY the anti-AI detection skill described in the system_prompt. Produce the audit JSON that matches the response_schema in the packet (every line_audit row populated, copy the ATTENTION CHECK token into a "notes" field).
3. Call mcp__essaywriter__submit_work_result(work_packet_id="${setup.work_packet_id}", payload=<audit json>, producer={ "type": "subagent", "role": "anti_ai_auditor", "subagent_token": "${setup.subagent_token}" }, agent_run_id="${runId}"). Save the returned work_result_id.
4. Call mcp__essaywriter__commit_anti_ai_audit(work_result_id=<id>, agent_run_id="${runId}").
Return ONLY raw JSON: { "ok": true, "audit_pass": <true|false> }.`,
      tools: [
        "mcp__essaywriter__get_work_packet",
        "mcp__essaywriter__submit_work_result",
        "mcp__essaywriter__commit_anti_ai_audit",
      ],
    });
  }

  // -------------------------------------------------------------------------
  // Verifier: confirm anti_ai_self_check is populated; revise if needed.
  // -------------------------------------------------------------------------
  async function verifyAuditOrRevise(runId, jobId) {
    const vRaw = await agent({
      prompt: `Read-only verifier. Call mcp__essaywriter__get_draft(job_id="${jobId}"). Inspect the returned draft object for the anti_ai_self_check field — confirm it is populated (non-null, non-empty) and report its final_decision. Return ONLY raw JSON: { "audit_pass": <true|false>, "revision_targets": ["<target1>", ...] }. Set audit_pass to false and populate revision_targets if anti_ai_self_check is missing or indicates issues requiring revision.`,
      tools: ["mcp__essaywriter__get_draft"],
    });

    const v = extractJson(vRaw.result);

    if (v.audit_pass === false && (v.revision_targets || []).length > 0) {
      await agent({
        prompt: `An anti-AI revision is required. Flagged targets: ${JSON.stringify((v.revision_targets || []).join("; "))}.

1. Call mcp__essaywriter__prepare_revision(job_id="${jobId}", selected_lenses=["anti_ai"], user_instruction=${JSON.stringify((v.revision_targets || []).join("; "))}, agent_run_id="${runId}").
2. Read the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Call mcp__essaywriter__get_work_packet(work_packet_id=<id>) if needed for additional packet details.
4. Generate revised content matching the response_schema.
5. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
6. Call mcp__essaywriter__commit_revision(work_result_id=<id>, agent_run_id="${runId}").
Return ONLY raw JSON: { "ok": true }.`,
        tools: [
          "mcp__essaywriter__prepare_revision",
          "mcp__essaywriter__commit_revision",
          "mcp__essaywriter__submit_work_result",
          "mcp__essaywriter__get_work_packet",
        ],
      });
    }
  }

  // -------------------------------------------------------------------------
  // Verifier: confirm validation passed; revise + re-validate if needed.
  // -------------------------------------------------------------------------
  async function verifyValidationOrRevise(runId, jobId) {
    const vRaw = await agent({
      prompt: `Read-only verifier. Call mcp__essaywriter__get_workflow_progress(agent_run_id="${runId}"). Inspect the steps array for the "validation" step — check if its status is "done" or equivalent to passing. Return ONLY raw JSON: { "passing": <true|false> }.`,
      tools: ["mcp__essaywriter__get_workflow_progress"],
    });

    const v = extractJson(vRaw.result);

    if (v.passing === false) {
      // Run ONLY the corrective revision here. Do NOT inline re-validation: a
      // revision resets the new draft's anti-AI audit, and the
      // require_anti_ai_audit gate refuses prepare_validation until that draft
      // is re-audited (bug_014). Returning lets the outer driver loop re-run the
      // anti_ai_audit step (which is now pending) and then validation, in order.
      await agent({
        prompt: `Validation did not pass for job_id="${jobId}". Run ONE corrective revision; the driver loop will re-audit and re-validate afterward.

1. Call mcp__essaywriter__get_workflow_progress(agent_run_id="${runId}") to identify the failing validation diagnostics.
2. Call mcp__essaywriter__prepare_revision(job_id="${jobId}", agent_run_id="${runId}") scoped to those failing diagnostics.
   Read the returned system_prompt VERBATIM (ATTENTION CHECK token → "notes").
3. Generate revised content matching the response_schema.
4. Call mcp__essaywriter__submit_work_result(work_packet_id=<id>, payload=<json>, agent_run_id="${runId}").
5. Call mcp__essaywriter__commit_revision(work_result_id=<id>, agent_run_id="${runId}").
Return ONLY raw JSON: { "ok": true }.`,
        tools: [
          "mcp__essaywriter__get_workflow_progress",
          "mcp__essaywriter__prepare_revision",
          "mcp__essaywriter__commit_revision",
          "mcp__essaywriter__submit_work_result",
          "mcp__essaywriter__get_work_packet",
        ],
      });
    }
  }

})();
