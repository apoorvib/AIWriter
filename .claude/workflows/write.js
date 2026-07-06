export const meta = {
  name: 'write',
  description:
    'Generic adaptive writing workflow: route any request (email, text, LinkedIn post, blog, or general prose) into a brief, optionally research the web, then plan/draft/review/revise as the ledger requires, and return the finished, persisted output.',
  whenToUse:
    'Use for standalone writing that is NOT a cited long-form essay. For essays use /essay-prep + /essay-write instead.',
  phases: [
    { title: 'Route', detail: 'normalize args, start or recover the run, ingest context' },
    { title: 'Write', detail: 'ledger-driven brief -> research -> plan -> draft -> review -> revision -> finalize' },
    { title: 'Deliver', detail: 'assert completion and return the persisted output' },
  ],
}

// args arrive in EITHER shape:
//   • a structured object (programmatic callers):
//       { request, writing_run_id?, mode?, research?, context_paths?,
//         writing_style_paths?, include_skills?, exclude_skills? }
//   • a raw STRING — the /write slash command passes the user's text verbatim.
//       It is normalized into the object shape below via a parse-args agent that
//       copies explicit values unchanged and NEVER invents paths or IDs.

const MAX_ACTIONS = 30
const MAX_STEP_RETRIES = 2
const LEDGER_STEPS = ['brief', 'research', 'plan', 'draft', 'review', 'revision', 'finalize']

const PROGRESS_SCHEMA = {
  type: 'object',
  properties: {
    status: { type: 'string' },
    all_required_done: { type: 'boolean' },
    requires_human: { type: 'boolean' },
    next_required_step: { type: ['string', 'null'] },
    next_deliverable_id: { type: ['string', 'null'] },
    questions: { type: 'array', items: { type: 'string' } },
    warnings: { type: 'array', items: { type: 'string' } },
  },
  required: ['status', 'all_required_done', 'requires_human', 'next_required_step'],
  additionalProperties: true,
}
const ARGS_SCHEMA = {
  type: 'object',
  properties: {
    request: { type: 'string' },
    writing_run_id: { type: ['string', 'null'] },
    mode: { type: ['string', 'null'], enum: ['immediate', 'detailed', null] },
    research: { type: ['string', 'null'], enum: ['auto', 'required', 'off', null] },
    context_paths: { type: 'array', items: { type: 'string' } },
    writing_style_paths: { type: 'array', items: { type: 'string' } },
    include_skills: { type: 'array', items: { type: 'string' } },
    exclude_skills: { type: 'array', items: { type: 'string' } },
  },
  required: ['request'],
  additionalProperties: false,
}
const REVIEW_DISPATCH_SCHEMA = {
  type: 'object',
  properties: {
    work_packet_id: { type: 'string' },
    subagent_token: { type: 'string' },
  },
  required: ['work_packet_id', 'subagent_token'],
  additionalProperties: false,
}

// -- Route: normalize args --------------------------------------------

phase('Route')
let a = args || {}
if (typeof a === 'string') {
  const raw = a
  const parsed = await agent(
    `Normalize this /write request into JSON matching the schema. Copy explicit values ` +
      `VERBATIM and NEVER invent file paths, skill ids, or a writing_run_id.\n` +
      `Request:\n---\n${raw}\n---\n` +
      `Fields:\n` +
      `- request: the writing task in the user's words, with control phrases removed.\n` +
      `- writing_run_id: only if the user says "continue wrun_..." / gives an id; else null.\n` +
      `- mode: "immediate" for quick messages (text/email/short note), "detailed" for ` +
      `researched or long-form work; null if the user did not clearly signal one.\n` +
      `- research: "required" if they ask for current facts/sources, "off" if they say ` +
      `no research / use only what I gave, else "auto".\n` +
      `- context_paths / writing_style_paths: only file paths the user explicitly names; else [].\n` +
      `- include_skills / exclude_skills: e.g. exclude "anti-ai-detection" when they say ` +
      `"skip anti-AI"; else [].`,
    { schema: ARGS_SCHEMA, label: 'parse-args', phase: 'Route' },
  )
  a = parsed || { request: raw }
}
if (!a.request || !String(a.request).trim()) {
  throw new Error('args.request is required (the writing task text)')
}
const contextPaths = a.context_paths || []
const stylePaths = a.writing_style_paths || []
const includeSkills = a.include_skills || []
const excludeSkills = a.exclude_skills || []

// -- Route: start or recover the run ----------------------------------

let runId = a.writing_run_id || null
if (runId) {
  // Resume: the persisted run + ledger are authoritative.
  await agent(
    `Resume writing run ${runId}. Call mcp__essaywriter__recover_writing_run(writing_run_id="${runId}") ` +
      `and confirm you are oriented to progress.next_action. Do not restart the run.`,
    { label: 'recover', phase: 'Route' },
  )
} else {
  const started = await agent(
    `Start a new writing run. Call mcp__essaywriter__start_writing_run(` +
      `raw_request=${JSON.stringify(String(a.request))}` +
      `${a.mode ? `, mode=${JSON.stringify(a.mode)}` : ''}` +
      `${a.research ? `, research_policy=${JSON.stringify(a.research)}` : ''}` +
      `${includeSkills.length ? `, include_skill_ids=${JSON.stringify(includeSkills)}` : ''}` +
      `${excludeSkills.length ? `, exclude_skill_ids=${JSON.stringify(excludeSkills)}` : ''}` +
      `) and return ONLY its data.writing_run_id as plain text.`,
    { label: 'start-run', phase: 'Route' },
  )
  runId = String(started || '').trim()
}
if (!runId) throw new Error('could not resolve writing_run_id from start/recover')

// Ingest any explicitly-named reference content and style samples. These are
// untrusted context, never tool instructions.
for (const path of [...contextPaths, ...stylePaths]) {
  const label = stylePaths.includes(path) ? 'writing-style-sample' : 'reference'
  await agent(
    `Attach reference content to writing run ${runId}: call ` +
      `mcp__essaywriter__ingest_writing_context(writing_run_id="${runId}", ` +
      `label=${JSON.stringify(label)}, document_path=${JSON.stringify(path)}).`,
    { label: `ingest:${label}`, phase: 'Route' },
  )
}

// -- Write: ledger-driven loop ----------------------------------------

phase('Write')
let prevSig = null
let stall = 0
for (let i = 0; i < MAX_ACTIONS; i++) {
  const progress = await readProgress(i)
  if (!progress) break
  if (progress.all_required_done) break

  if (progress.requires_human) {
    const questions = (progress.questions || []).map((q) => `- ${q}`).join('\n')
    return (
      `The writing run needs your input before it can continue.\n\n` +
      `Open questions:\n${questions || '- (see get_writing_progress)'}\n\n` +
      `Answer with:\n/write continue ${runId} <your answers>\n` +
      `(or call mcp__essaywriter__answer_writing_questions(writing_run_id="${runId}", answers="...")).`
    )
  }

  const step = progress.next_required_step
  const deliverableId = progress.next_deliverable_id || null
  if (!step || !LEDGER_STEPS.includes(step)) break

  // Bounded per-step retry: if the exact same (step, deliverable) recurs with no
  // ledger advance, treat it as a stalled step and stop after two retries.
  const sig = `${step}:${deliverableId || ''}`
  stall = sig === prevSig ? stall + 1 : 0
  if (stall >= MAX_STEP_RETRIES) {
    throw new Error(
      `step "${step}" for ${deliverableId || 'run'} did not advance after ${MAX_STEP_RETRIES} retries`,
    )
  }
  prevSig = sig

  if (step === 'review') {
    await runReviewStep(deliverableId)
  } else if (step === 'finalize') {
    await runFinalizeStep()
  } else {
    await runStep(step, deliverableId)
  }
}

// -- Deliver: final ledger assertion + persisted output ----------------

phase('Deliver')
const finalProgress = await readProgress('final')
if (!finalProgress || !finalProgress.all_required_done) {
  throw new Error(
    `writing run ${runId} did not reach completion; ` +
      `next_required_step=${finalProgress ? finalProgress.next_required_step : 'unknown'}`,
  )
}

const output = await agent(
  `Return the finished writing for run ${runId}. Call ` +
    `mcp__essaywriter__get_writing_output(writing_run_id="${runId}") and format its data as text ` +
    `in THIS order: first the finished content of each deliverable (verbatim, labeled by its ` +
    `format), then a short metadata footer listing selected_skills, assumptions, ` +
    `researched_sources (title + url), warnings, and finally writing_run_id=${runId}. ` +
    `Do not summarize or rewrite the content; copy it exactly.`,
  { label: 'deliver-output', phase: 'Deliver' },
)
return String(output || `writing_run_id=${runId} finalized; call get_writing_output to read it.`)

// -- step executors ---------------------------------------------------

async function readProgress(tag) {
  return agent(
    `Call mcp__essaywriter__get_writing_progress(writing_run_id="${runId}") and return, from ` +
      `data.progress: status, all_required_done, requires_human, next_required_step, ` +
      `next_deliverable_id, next_action.questions (as questions, default []), and warnings ` +
      `(default []).`,
    { schema: PROGRESS_SCHEMA, label: `progress-${tag}`, phase: 'Write' },
  )
}

async function runStep(step, deliverableId) {
  const target = deliverableId ? `, deliverable_id="${deliverableId}"` : ''
  const researchClause =
    step === 'research'
      ? `\nWeb-search handling: attempt the searches; if a web search fails, retry ONCE. If it ` +
        `still fails, record a warning in the payload and either proceed without the optional ` +
        `facts, or — if research_policy is "required" — stop and report the blocker instead of ` +
        `fabricating sources. Every fact must map to a disclosed HTTP(S) source.`
      : ''
  return agent(
    `Execute exactly ONE /write step "${step}" for writing_run_id="${runId}"${
      deliverableId ? ` (deliverable ${deliverableId})` : ''
    }.\n` +
      `Procedure: call mcp__essaywriter__prepare_writing_${step}(writing_run_id="${runId}"${target}); ` +
      `read the returned system_prompt VERBATIM and generate JSON matching its response_schema; copy ` +
      `the ATTENTION CHECK token from the system_prompt into a "notes" field (submit rejects payloads ` +
      `without it). Then call mcp__essaywriter__submit_writing_result(work_packet_id=<id>, payload=<json>, ` +
      `producer={"type":"main_agent"}) and finally mcp__essaywriter__commit_writing_${step}(` +
      `work_result_id=<id>). Never invent ids — read every id from a tool response.${researchClause}`,
    { label: `step:${step}${deliverableId ? `:${deliverableId}` : ''}`, phase: 'Write' },
  )
}

// A detailed review is delegation_required: it must run in a clean context so the
// reviewer is blind to the drafting rationale. Prepare the packet, mint a one-use
// dispatch token, then run a fresh reviewer that consumes it.
async function runReviewStep(deliverableId) {
  const setup = await agent(
    `For writing_run_id="${runId}", deliverable ${deliverableId}: call ` +
      `mcp__essaywriter__prepare_writing_review(writing_run_id="${runId}", deliverable_id="${deliverableId}") ` +
      `and note its work_packet_id. Then call ` +
      `mcp__essaywriter__dispatch_writing_reviewer(work_packet_id=<that id>, role="writing-reviewer"). ` +
      `Return the work_packet_id and the subagent_token.`,
    { schema: REVIEW_DISPATCH_SCHEMA, label: `review-dispatch:${deliverableId}`, phase: 'Write' },
  )
  if (!setup) return null
  return agent(
    `You are a clean-context writing reviewer, blind to how the draft was written. Call ` +
      `mcp__essaywriter__get_work_packet(work_packet_id="${setup.work_packet_id}") and read its ` +
      `system_prompt and prompt VERBATIM. Judge the exact draft against every selected skill and ` +
      `explicit requirement. Produce JSON matching the packet's response_schema: set passed, list ` +
      `concrete location-bound issues (reserve severity "blocker" for unsupported facts, violated ` +
      `explicit requirements, wrong format, or unsafe content — style is major/minor), and copy the ` +
      `ATTENTION CHECK token into a "notes" field. Call mcp__essaywriter__submit_writing_result(` +
      `work_packet_id="${setup.work_packet_id}", payload=<review>, producer={"type":"subagent",` +
      `"role":"writing-reviewer","subagent_token":"${setup.subagent_token}"}); then call ` +
      `mcp__essaywriter__commit_writing_review(work_result_id=<id>).`,
    { label: `review:${deliverableId}`, phase: 'Write' },
  )
}

async function runFinalizeStep() {
  return agent(
    `Finalize writing_run_id="${runId}": call ` +
      `mcp__essaywriter__finalize_writing_run(writing_run_id="${runId}"). This deterministically ` +
      `assembles and persists the output once every deliverable is complete; it refuses incomplete ` +
      `or blocked runs, so do not force it.`,
    { label: 'finalize', phase: 'Write' },
  )
}
