export const meta = {
  name: 'essay-prep',
  description:
    'EssayWriter Agent Tool Mode prep: ingest sources, write source cards, commit a task spec, create the job, generate candidate topics, then stop at the human topic-selection gate.',
  whenToUse:
    'Run before /essay-write to prepare an essay from local source documents up to the topic choice.',
  phases: [
    { title: 'Setup', detail: 'start run + read harness instructions' },
    { title: 'Ingest', detail: 'ingest source files (+ writing-style samples)' },
    { title: 'Source cards', detail: 'one committed card per source' },
    { title: 'Writing style', detail: 'commit writing-style content (content path)' },
    { title: 'Task spec', detail: 'commit the task specification' },
    { title: 'Create job', detail: 'gated job creation' },
    { title: 'Topics', detail: 'generate and present candidate topics' },
  ],
}

// args: {
//   source_paths: string[],                  // paths to source documents to ingest
//   writing_style_paths?: string[] | "skip",  // writing-style sample paths, or "skip"
//   assignment_text?: string,                // raw assignment text
//   assignment_path?: string,                // OR a path to an assignment file
// }
const a = args || {}
const sourcePaths = Array.isArray(a.source_paths) ? a.source_paths : []
const skipStyle =
  a.writing_style_paths === 'skip' ||
  !a.writing_style_paths ||
  (Array.isArray(a.writing_style_paths) && a.writing_style_paths.length === 0)
const stylePaths = skipStyle || !Array.isArray(a.writing_style_paths) ? [] : a.writing_style_paths
const assignmentInstruction = a.assignment_text
  ? `The raw assignment text is:\n---\n${a.assignment_text}\n---\nUse it as the raw_text argument.`
  : a.assignment_path
    ? `Read the assignment from the file at ${a.assignment_path} (use a read tool) and use its content as raw_text.`
    : `No explicit assignment was provided; derive a reasonable task spec from the ingested source content.`

const RUN_SCHEMA = {
  type: 'object',
  properties: { agent_run_id: { type: 'string' } },
  required: ['agent_run_id'],
  additionalProperties: false,
}
const SOURCES_SCHEMA = {
  type: 'object',
  properties: { source_ids: { type: 'array', items: { type: 'string' } } },
  required: ['source_ids'],
  additionalProperties: false,
}
const CONTENT_SCHEMA = {
  type: 'object',
  properties: { content_id: { type: 'string' } },
  required: ['content_id'],
  additionalProperties: false,
}
const JOB_SCHEMA = {
  type: 'object',
  properties: { job_id: { type: 'string' } },
  required: ['job_id'],
  additionalProperties: false,
}

phase('Setup')
const setup = await agent(
  `You are bootstrapping an EssayWriter Agent Tool Mode run. Call the MCP tool ` +
    `mcp__essaywriter__start_agent_run with objective="Essay prep". Take the agent_run_id ` +
    `from its result and call mcp__essaywriter__get_harness_instructions with that ` +
    `agent_run_id. Return the agent_run_id.`,
  { schema: RUN_SCHEMA, label: 'start-run', phase: 'Setup' },
)
const runId = setup && setup.agent_run_id
if (!runId) throw new Error('start_agent_run did not return an agent_run_id')
// Provisional job id derived from the unique run id. The runtime forbids
// Date.now()/Math.random(), and a clockless subagent must not invent one.
const provisionalJobId = `job-prov-${runId}`

phase('Ingest')
const ingestPrompt =
  `For agent_run_id="${runId}", ingest the input files. ` +
  (sourcePaths.length
    ? `For EACH path in ${JSON.stringify(sourcePaths)} call ` +
      `mcp__essaywriter__ingest_source_file(document_path=<path>, agent_run_id="${runId}") ` +
      `and collect the source_id it returns, in order. `
    : `No source paths were provided. `) +
  (stylePaths.length
    ? `Also, for EACH path in ${JSON.stringify(stylePaths)} call ` +
      `mcp__essaywriter__ingest_writing_style_sample(sample_path=<path>, agent_run_id="${runId}"). `
    : ``) +
  `Return the full ordered list of ingested source_ids.`
const ingested = await agent(ingestPrompt, {
  schema: SOURCES_SCHEMA,
  label: 'ingest',
  phase: 'Ingest',
})
const sourceIds = (ingested && ingested.source_ids) || []
if (sourcePaths.length && sourceIds.length === 0) {
  throw new Error('ingestion returned no source_ids')
}

phase('Source cards')
await agent(
  `For agent_run_id="${runId}", write a source card for EVERY source_id in ` +
    `${JSON.stringify(sourceIds)} — do not skip any. For each source_id: ` +
    `(1) call mcp__essaywriter__prepare_source_card(source_id=<id>, agent_run_id="${runId}"); ` +
    `(2) read the returned system_prompt VERBATIM and generate JSON matching its ` +
    `response_schema, copying the ATTENTION CHECK token from the system_prompt into a ` +
    `"notes" field; (3) call mcp__essaywriter__submit_work_result(work_packet_id=<id>, ` +
    `payload=<json>, agent_run_id="${runId}"); (4) call ` +
    `mcp__essaywriter__commit_source_card(work_result_id=<id>, agent_run_id="${runId}"). ` +
    `Report how many cards you committed.`,
  { label: 'source-cards', phase: 'Source cards' },
)

let contentId = null
if (!skipStyle && stylePaths.length) {
  phase('Writing style')
  const ws = await agent(
    `For agent_run_id="${runId}", build writing-style content from the ingested samples. ` +
      `Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to find the ` +
      `ingested writing-style sample_ids. Call ` +
      `mcp__essaywriter__prepare_writing_style_content(sample_ids=[<ids>], agent_run_id="${runId}"); ` +
      `generate JSON using the returned system_prompt VERBATIM (copy the ATTENTION CHECK token ` +
      `into a "notes" field); call mcp__essaywriter__submit_work_result then ` +
      `mcp__essaywriter__commit_writing_style_content. Return the content_id.`,
    { schema: CONTENT_SCHEMA, label: 'writing-style', phase: 'Writing style' },
  )
  contentId = ws && ws.content_id
}

phase('Task spec')
await agent(
  `For agent_run_id="${runId}", commit the task specification. ${assignmentInstruction} ` +
    `Call mcp__essaywriter__prepare_task_spec(raw_text=<assignment text>, agent_run_id="${runId}"); ` +
    `generate JSON using the returned system_prompt VERBATIM (copy the ATTENTION CHECK token ` +
    `into a "notes" field); call mcp__essaywriter__submit_work_result then ` +
    `mcp__essaywriter__commit_task_spec. Report the task_spec_id.`,
  { label: 'task-spec', phase: 'Task spec' },
)

phase('Create job')
const createJobPrompt =
  `For agent_run_id="${runId}", create the essay job. Use these EXACT values — do not invent ids:\n` +
  `- provisional job_id: "${provisionalJobId}"\n` +
  `- source_ids: ${JSON.stringify(sourceIds)}\n` +
  (contentId ? `- writing-style content_id to attach after creation: "${contentId}"\n` : ``) +
  `Steps:\n` +
  `1. Call mcp__essaywriter__skip_writing_style_calibration(job_id="${provisionalJobId}", reason=${
    contentId
      ? '"Provisional skip token for content path; superseded by attach_writing_style_to_job."'
      : '"User chose to skip writing-style calibration for this prep run."'
  }, agent_run_id="${runId}") and keep the returned skip_token.\n` +
  `2. Call mcp__essaywriter__get_agent_run_state(agent_run_id="${runId}") to read the committed task_spec_id.\n` +
  `3. Call mcp__essaywriter__create_job_from_artifacts(job_id="${provisionalJobId}", task_spec_id=<id>, ` +
  `source_ids=${JSON.stringify(sourceIds)}, writing_style_skip_token=<token>, agent_run_id="${runId}").\n` +
  (contentId
    ? `4. Call mcp__essaywriter__attach_writing_style_to_job(job_id="${provisionalJobId}", content_id="${contentId}", agent_run_id="${runId}") to supersede the provisional skip with real content.\n`
    : ``) +
  `Return the job_id.`
const created = await agent(createJobPrompt, {
  schema: JOB_SCHEMA,
  label: 'create-job',
  phase: 'Create job',
})
const jobId = (created && created.job_id) || provisionalJobId

phase('Topics')
await agent(
  `For agent_run_id="${runId}" and job_id="${jobId}", generate candidate topics. Call ` +
    `mcp__essaywriter__prepare_topics(job_id="${jobId}", agent_run_id="${runId}"); generate JSON ` +
    `using the returned system_prompt VERBATIM (copy the ATTENTION CHECK token into a "notes" ` +
    `field); call mcp__essaywriter__submit_work_result then ` +
    `mcp__essaywriter__commit_topics. Report success.`,
  { label: 'topics', phase: 'Topics' },
)
const topicSummary = await agent(
  `Call mcp__essaywriter__get_job_summary(job_id="${jobId}") and list the committed candidate ` +
    `topics as a numbered list, each line showing the topic_id and the topic title/question. ` +
    `Return only that readable list.`,
  { label: 'present-topics', phase: 'Topics' },
)

return (
  `Prep complete.\n` +
  `  agent_run_id: ${runId}\n` +
  `  job_id: ${jobId}\n\n` +
  `Candidate topics:\n${topicSummary}\n\n` +
  `Choose one, then run /essay-write with: agent_run_id="${runId}", job_id="${jobId}", ` +
  `round 1, the chosen topic_id, and a one-line reason for your choice.`
)
