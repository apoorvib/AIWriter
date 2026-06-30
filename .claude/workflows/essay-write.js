export const meta = {
  name: 'essay-write',
  description:
    'EssayWriter Agent Tool Mode write segment: record the chosen topic, then research, outline, draft, anti-AI audit, validation (with revision loops), and Markdown export.',
  whenToUse:
    'Run after /essay-prep, once you have chosen a topic from the candidate list it printed.',
  phases: [
    { title: 'Recover', detail: 'recover run + read harness instructions' },
    { title: 'Select topic', detail: 'commit the human topic choice' },
    { title: 'Write', detail: 'ledger-driven research -> draft -> audit -> validation -> export' },
  ],
}

// args: {
//   agent_run_id: string,             // printed by /essay-prep
//   job_id: string,                   // printed by /essay-prep
//   round_number?: number,            // topic round (default 1)
//   topic_id: string,                 // the topic you chose
//   user_selection_evidence?: string, // one line on why (required by the server)
// }
const a = args || {}
const runId = a.agent_run_id
const jobId = a.job_id
if (!runId) throw new Error('args.agent_run_id is required (from /essay-prep)')
if (!jobId) throw new Error('args.job_id is required (from /essay-prep)')
if (!a.topic_id) throw new Error('args.topic_id is required (choose one from the prep topic list)')
const roundNumber = a.round_number || 1
const evidence = a.user_selection_evidence || 'User selected this topic from the prep candidate list.'

const PROGRESS_SCHEMA = {
  type: 'object',
  properties: {
    all_required_done: { type: 'boolean' },
    next_required_step: { type: ['string', 'null'] },
  },
  required: ['all_required_done', 'next_required_step'],
  additionalProperties: true,
}
const AUDIT_DISPATCH_SCHEMA = {
  type: 'object',
  properties: {
    work_packet_id: { type: 'string' },
    subagent_token: { type: 'string' },
  },
  required: ['work_packet_id', 'subagent_token'],
  additionalProperties: false,
}
const AUDIT_RESULT_SCHEMA = {
  type: 'object',
  properties: { audit_pass: { type: 'boolean' } },
  required: ['audit_pass'],
  additionalProperties: true,
}

phase('Recover')
await agent(
  `Call mcp__essaywriter__recover_agent_run(agent_run_id="${runId}") then ` +
    `mcp__essaywriter__get_harness_instructions(agent_run_id="${runId}"). Confirm you are oriented.`,
  { label: 'recover', phase: 'Recover' },
)

phase('Select topic')
await agent(
  `Commit the user's topic choice (the human gate that split prep from write). Call ` +
    `mcp__essaywriter__select_topic(job_id="${jobId}", round_number=${roundNumber}, ` +
    `topic_id="${a.topic_id}", user_selection_evidence=${JSON.stringify(evidence)}, ` +
    `agent_run_id="${runId}").`,
  { label: 'select-topic', phase: 'Select topic' },
)

phase('Write')
let lastStep = null
for (let i = 0; i < 60; i++) {
  const progress = await agent(
    `Call mcp__essaywriter__get_workflow_progress(agent_run_id="${runId}") and return ` +
      `all_required_done and next_required_step from its data.`,
    { schema: PROGRESS_SCHEMA, label: `progress-${i}`, phase: 'Write' },
  )
  if (!progress || progress.all_required_done) break
  const step = progress.next_required_step
  if (!step) break

  // If validation is the next step again right after we ran it, the latest
  // validation did not pass -> run a corrective revision (which resets the
  // draft's audit, so the loop will re-audit then re-validate).
  if (step === 'validation' && lastStep === 'validation') {
    await runRevisionStep('validation did not pass; revise against the failing diagnostics')
    lastStep = 'revision'
    continue
  }

  if (step === 'anti_ai_audit') {
    const auditPass = await runAuditStep()
    lastStep = 'anti_ai_audit'
    if (auditPass === false) {
      await runRevisionStep('the anti-AI audit did not pass; apply its revision_targets', 'anti_ai')
      lastStep = 'revision'
    }
    continue
  }

  await runWriteStep(step)
  lastStep = step
}

return (
  `Write segment complete for agent_run_id=${runId}, job_id=${jobId}. ` +
  `The validated essay was exported to Markdown. Review it (mcp__essaywriter__get_draft / ` +
  `the export under your data dir), then optionally run cleanup.`
)

async function runWriteStep(step) {
  return agent(
    `Execute exactly ONE EssayWriter write-segment step "${step}" for agent_run_id="${runId}", ` +
      `job_id="${jobId}".\n` +
      `Rules for any prepare_*/commit_* stage: call the step's prepare_* tool; read the returned ` +
      `system_prompt VERBATIM and use it to generate JSON matching its response_schema; copy the ` +
      `ATTENTION CHECK token from the system_prompt into a "notes" field (submit_work_result rejects ` +
      `payloads without it); call mcp__essaywriter__submit_work_result; then call the named commit_* ` +
      `tool. Never invent ids — read every id from a tool response.\n` +
      `Step map:\n` +
      `- research_plan: call mcp__essaywriter__create_research_plan(job_id="${jobId}", agent_run_id="${runId}") ` +
      `then mcp__essaywriter__resolve_source_requests(job_id="${jobId}", agent_run_id="${runId}").\n` +
      `- research_notes: prepare_research_notes -> submit -> commit_research_notes.\n` +
      `- outline: prepare_outline -> submit -> commit_outline.\n` +
      `- draft: prepare_draft -> submit -> commit_draft.\n` +
      `- style_revision: prepare_style_revision (if it returns a windowed plan, call ` +
      `prepare_style_revision_window for each window) -> submit -> commit_style_revision.\n` +
      `- validation: prepare_validation -> submit -> commit_validation.\n` +
      `- export: call mcp__essaywriter__export_markdown(job_id="${jobId}", agent_run_id="${runId}").\n` +
      `Use the matching mcp__essaywriter__ tools. Report what you committed.`,
    { label: `step:${step}`, phase: 'Write' },
  )
}

// The anti-AI audit packet is delegation_required + frontier-tier: prepare it,
// mint a one-use dispatch token, then run a fresh Opus auditor that consumes it.
async function runAuditStep() {
  const setup = await agent(
    `For job_id="${jobId}", agent_run_id="${runId}": call ` +
      `mcp__essaywriter__prepare_anti_ai_audit(job_id="${jobId}", agent_run_id="${runId}") and note its ` +
      `work_packet_id. Then call mcp__essaywriter__dispatch_subagent(work_packet_id=<that id>, ` +
      `role="anti_ai_auditor", model_tier="opus", agent_run_id="${runId}"). Return the work_packet_id ` +
      `and the subagent_token.`,
    { schema: AUDIT_DISPATCH_SCHEMA, label: 'audit-dispatch', phase: 'Write' },
  )
  if (!setup) return null
  const result = await agent(
    `You are a clean-context anti-AI auditor. Call ` +
      `mcp__essaywriter__get_work_packet(work_packet_id="${setup.work_packet_id}") and read its ` +
      `system_prompt VERBATIM — it contains ONLY the anti-AI writing skill. Produce the audit JSON ` +
      `matching the packet's response_schema: fill every required field, include one line_audit row ` +
      `per skill line, copy the skill and draft hashes from the packet, and copy the ATTENTION CHECK ` +
      `token into a "notes"/self_check_notes field. Call ` +
      `mcp__essaywriter__submit_work_result(work_packet_id="${setup.work_packet_id}", payload=<audit>, ` +
      `producer={ "type": "subagent", "role": "anti_ai_auditor", "subagent_token": "${setup.subagent_token}" }, ` +
      `agent_run_id="${runId}"); then call ` +
      `mcp__essaywriter__commit_anti_ai_audit(work_result_id=<id>, agent_run_id="${runId}"). ` +
      `Return audit_pass (true if the committed audit passed).`,
    { schema: AUDIT_RESULT_SCHEMA, model: 'opus', label: 'audit', phase: 'Write' },
  )
  return result ? result.audit_pass : null
}

async function runRevisionStep(reason, lens) {
  const lensClause = lens
    ? `Use selected_lenses=["${lens}"]. `
    : `Scope it to the failing validation diagnostics (call mcp__essaywriter__get_workflow_progress first to read them). `
  return agent(
    `${reason} for job_id="${jobId}". Run ONE corrective revision; the driver loop will re-audit and ` +
      `re-validate afterward. Call mcp__essaywriter__prepare_revision(job_id="${jobId}", agent_run_id="${runId}"). ` +
      `${lensClause}Read the returned system_prompt VERBATIM and generate JSON matching its ` +
      `response_schema (copy the ATTENTION CHECK token into a "notes" field). Call ` +
      `mcp__essaywriter__submit_work_result then mcp__essaywriter__commit_revision.`,
    { label: 'revision', phase: 'Write' },
  )
}
