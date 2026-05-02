# Manual Reiteration And Draft History Implementation Plan

Date: 2026-04-28
Status: Draft for review. Do not implement before approval.

## Purpose

Add a post-pipeline editing and reiteration flow so users can:

- reopen prior LLM-produced essay outputs without copy-paste
- edit those outputs directly in the app
- save edited drafts as first-class artifacts
- ask the system to review or revise those edited drafts using selected lenses
- preserve every generated and user-authored version immutably

This feature is not another drafting pipeline. It is a human-in-the-loop layer on top of the existing workflow.

## Why This Is Needed

The current system already persists:

- draft versions in `DraftStore`
- final exports in `FinalExportStore`
- validation reports
- tone-alignment reports

But the product still behaves as if only the latest draft matters:

- the frontend does not expose draft or export history
- the export route returns the latest draft content rather than the persisted export artifact
- users cannot save post-export edits as new versions
- there is no structured way to rerun selected checks or request a constrained revision from a user-edited draft

That forces users back into copy-paste, which breaks provenance and makes the product behave like a throwaway generator instead of a collaborative writing tool.

## Product Goals

1. Persist every LLM-produced essay state and every user-edited essay state.
2. Expose draft and export history in the UI.
3. Let the user branch from any saved version.
4. Let the user choose whether they want:
   - review only
   - revise draft
   - later, review plus revise in one step if needed
5. Let the user choose which lenses to apply:
   - evidence
   - citations
   - assignment_fit
   - length
   - tone
   - anti_ai
6. Preserve the user's edited text as the source of truth for that iteration.
7. Keep tone alignment and anti-AI handling consistent with the current system:
   - tone beats anti-AI heuristics when they conflict
   - evidence, citation, and assignment failures still outrank tone

## Non-Goals

- Real-time collaborative editing.
- Google Docs style multi-user cursor sync.
- Arbitrary branch merging.
- Replaying the entire topic, research, and outline pipeline from a user edit.
- Replacing the current automatic pipeline with an open-ended agent loop.
- A full rich-text editor in the first version.

## Core Design Principles

### 1. Drafts Are Immutable Artifacts

Every meaningful text state is saved as a new version. Nothing is edited in place.

Examples:

- system-generated draft `v1`
- style-revised draft `v2`
- user-edited draft `v3`
- manual LLM revision from `v3` -> `v4`

### 2. User Text Outranks Prior Model Text

If the user edits a draft, that edited draft becomes the base document for all future manual review or revision requests. The system must not silently regenerate from an older model draft.

### 3. Manual Reiteration Is Separate From The Main Pipeline State Machine

The existing workflow state machine is optimized for the linear path:

- topic selection
- research
- outline
- draft
- validation
- tone alignment
- export

Manual reiteration should not mutate that state machine back to early stages. It should run as a sidecar flow that consumes existing artifacts and writes new draft versions plus new review-run artifacts.

### 4. Review And Revision Are Different Operations

- `review_only`: analyze and return findings without producing a new essay draft
- `revise`: produce a new draft version constrained by the selected lenses and the user's instruction

### 5. Lens-Based Checks Are Modular

The user must be able to select which checks matter for this iteration. The system should not always rerun everything.

## Current System Constraints

Relevant existing behavior:

- `EssayDraft` already stores versioned draft content.
- `FinalEssayExport` already stores persisted final export content.
- `EssayJob` points only to the latest `draft_id` and `final_export_id`.
- `backend/routes/export.py` currently serves the latest draft content, not a true export-history view.
- validation and tone alignment already run as separate logical services.
- tone alignment already outranks anti-AI heuristics when the conflict is about authentic voice.

This plan should build on those primitives rather than replacing them.

## Proposed User Experience

### Entry Points

Add a manual reiteration surface in the UI from:

- the final export view
- the latest draft view
- draft history rows
- export history rows

### User Flow

1. User opens a saved draft or export.
2. User chooses `Edit` or `Re-iterate`.
3. The app loads that text into an editor.
4. The user makes changes.
5. The user saves those changes as a new draft version.
6. The user optionally enters a free-form instruction.
7. The user selects one or more lenses.
8. The user chooses `Review only` or `Revise`.
9. The backend stores the request, runs the selected analysis steps, stores the outputs, and optionally stores a new revised draft version.
10. The UI shows:
    - the saved source draft
    - the selected lenses
    - the review outputs
    - the resulting revised draft if one was produced

### First-Launch UI Scope

For v1, the editor can be plain text. Do not block the feature on a rich-text document editor.

## Artifact Model

Use immutable versioned artifacts, not mutable session blobs.

### 1. Extend `EssayDraft`

Add optional provenance fields to `essay_writer/drafting/schema.py`.

Proposed additions:

```python
DraftOrigin = Literal[
    "generated",
    "style_revision",
    "system_revision",
    "user_edit",
    "manual_llm_revision",
]


DraftActor = Literal["system", "user"]


DraftLens = Literal[
    "evidence",
    "citations",
    "assignment_fit",
    "length",
    "tone",
    "anti_ai",
]
```

Suggested new `EssayDraft` fields:

```python
origin: DraftOrigin = "generated"
created_by: DraftActor = "system"
parent_draft_id: str | None = None
parent_export_id: str | None = None
manual_request_id: str | None = None
user_instruction: str | None = None
selected_lenses: list[DraftLens] = field(default_factory=list)
```

Field meanings:

- `origin`: where this draft came from
- `created_by`: whether this text was produced by the system or supplied by the user
- `parent_draft_id`: prior draft version this one branched from
- `parent_export_id`: export artifact this draft was opened from, if any
- `manual_request_id`: request that produced this draft, if any
- `user_instruction`: instruction supplied for a manual revise action
- `selected_lenses`: lenses used when this draft was created by a manual revise request

Backward compatibility:

- all new fields should be optional or have defaults
- old stored draft JSON must continue to load

### 2. Keep `FinalEssayExport` Immutable

Do not turn exports into editable objects. If a user starts editing from an export, save a new `EssayDraft` with:

- `origin="user_edit"`
- `created_by="user"`
- `parent_export_id=<export_id>`

This preserves the difference between:

- exported presentation artifact
- editable draft artifact

### 3. Add `ManualRevisionRequest`

Create a new stored request artifact. This records the user's intent independently of the resulting draft.

Proposed shape:

```python
@dataclass(frozen=True)
class ManualRevisionRequest:
    id: str
    job_id: str
    source_draft_id: str
    mode: Literal["review_only", "revise"]
    instruction: str | None
    selected_lenses: list[DraftLens]
    preserve_user_edits: bool = True
    created_at: str = field(default_factory=utc_now_iso)
```

Purpose:

- stores exactly what the user asked for
- supports multiple reiteration requests against the same saved draft
- avoids overloading `EssayDraft` with request-only metadata

### 4. Add `ManualRevisionRun`

Create a stored result artifact for the combined review/revision execution.

Proposed shape:

```python
@dataclass(frozen=True)
class ManualRevisionRun:
    id: str
    request_id: str
    job_id: str
    source_draft_id: str
    validation_report_id: str | None = None
    tone_alignment_report_id: str | None = None
    anti_ai_summary: dict[str, object] | None = None
    change_summary: list[str] = field(default_factory=list)
    result_draft_id: str | None = None
    status: Literal["completed", "failed"] = "completed"
    created_at: str = field(default_factory=utc_now_iso)
```

Purpose:

- persists the outputs the user may want to reopen later
- allows the UI to show a saved run history
- decouples stored reviews from stored drafts

### 5. Add Lightweight Draft/Export History Summaries

Do not force the UI to pull full text for every history row.

Add response-model summaries with:

- id
- version
- origin
- created_by
- created_at
- parent ids
- preview snippet

## API Plan

### History Endpoints

Add:

- `GET /jobs/{job_id}/drafts`
- `GET /jobs/{job_id}/drafts/{version}`
- `GET /jobs/{job_id}/exports`
- `GET /jobs/{job_id}/exports/{export_id}`

Important fix:

- update the current export route so it can return the actual stored export artifact, not only the latest draft content

### User Edit Endpoints

Add:

- `POST /jobs/{job_id}/drafts/from-export`
- `POST /jobs/{job_id}/drafts/save-user-edit`

Recommended request shape for saving a user edit:

```json
{
  "base_draft_id": "draft_v003",
  "base_export_id": null,
  "content": "...edited essay text..."
}
```

Behavior:

- creates a new `EssayDraft`
- sets `origin="user_edit"`
- sets `created_by="user"`
- links back to the chosen base artifact

### Manual Reiteration Endpoints

Add:

- `POST /jobs/{job_id}/manual-revision-requests`
- `GET /jobs/{job_id}/manual-revision-runs`
- `GET /jobs/{job_id}/manual-revision-runs/{run_id}`

Recommended request payload:

```json
{
  "source_draft_id": "draft_v004",
  "mode": "revise",
  "instruction": "Keep my new paragraph 4, tighten the intro, and re-check citations.",
  "selected_lenses": ["evidence", "citations", "tone", "anti_ai"]
}
```

## Workflow Design

### High-Level Shape

Manual reiteration is a separate execution path:

1. load saved source draft
2. store the manual request
3. produce a deterministic change summary against the parent draft or export
4. run selected reviews in parallel where appropriate
5. store the combined run result
6. if `mode == "revise"`, run a constrained revision service on the user-edited draft
7. store the revised draft as a new version
8. optionally rerun the selected checks on the revised draft before returning

### Why This Should Not Reuse The Main Pipeline Runner

The main pipeline runner assumes:

- one selected topic
- one linear draft path
- one validation gate before export

Manual reiteration is branch-oriented and user-directed. It should not push the job back through `research_planning_ready`, `drafting_ready`, or `validation_ready`.

Instead, create a separate service, for example:

- `ManualRevisionService`
- `ManualRevisionStore`
- `ManualRevisionRunner`

These can reuse existing stage services internally.

## Selected Lens Semantics

Define each selected lens explicitly.

### `evidence`

Run core validation focused on unsupported claims and source grounding.

### `citations`

Run core validation focused on citation presence and plausibility.

### `assignment_fit`

Run core validation focused on meeting the assignment and rubric.

### `length`

Run core validation focused on target-length compliance.

### `tone`

Run tone alignment against:

- `WritingStyleContent`
- selected writing samples

Tone uses authentic user voice as the primary style target.

### `anti_ai`

Run deterministic anti-AI checks and anti-AI-skill-informed diagnostics as advisory style signals.

Important rule:

- `anti_ai` is never a hard factual gate
- if `tone` and `anti_ai` conflict, tone wins
- if `evidence` or `citations` fail, they still outrank both tone and anti-AI style preferences

## Review Execution Model

### Parallel Review

When selected, run independent reviews in parallel:

- core validation service
- tone alignment service
- deterministic anti-AI checks

Then merge those outputs into one stored `ManualRevisionRun`.

This preserves the design already used in the automatic workflow:

- validation and tone alignment are logically separate
- they are combined before revision

### Combined Revision Input

If the user requested `revise`, the revision prompt should receive:

- the user-edited source draft
- the user's instruction
- the deterministic change summary
- the selected review outputs
- the evidence map and source context already attached to the job
- the anti-AI skill
- the optional writing-style payload

Tone and anti-AI conflict policy should be restated explicitly:

- preserve authentic voice when it conflicts with generic anti-AI heuristics

## Change Summary Requirement

Before any manual review or revision call, generate a deterministic change summary between:

- parent draft and saved user edit, or
- export content and saved user edit

Purpose:

- lets the system see what the user actually changed
- reduces accidental rollback of user edits
- improves revision precision

The first implementation can use a lightweight paragraph/sentence diff summary. It does not need a complex visual diff UI in v1.

## Source Of Truth And Preservation Rules

Manual reiteration must follow these rules:

1. Revise the saved user draft, not the prior system draft.
2. Preserve user edits unless the user's instruction or selected lens requires touching that text.
3. Never overwrite a saved user draft with the model's next output.
4. Save any model-produced revision as a new draft version.
5. If the user opens a final export and edits it, that creates a new draft; the export artifact remains unchanged.

## Frontend Plan

### New UI Areas

Add:

- a `Draft History` panel
- an `Export History` panel
- a post-export editor view
- a `Manual Reiteration` panel with:
  - instruction box
  - selected-lens checkboxes
  - `Review only` and `Revise` actions

### Draft History Row Data

Each row should show:

- version number
- origin label
- created-by label
- timestamp
- parent reference
- short preview

Recommended labels:

- `Generated`
- `Style pass`
- `System revision`
- `Your edit`
- `AI revision from your edit`

### Editing Model

First version recommendation:

- load saved text into a plain editor
- explicit save button
- no hard dependency on autosave

Autosave can be added later, but it should not block the first implementation.

### Result Display

For a saved manual run, display:

- request metadata
- selected lenses
- stored review outputs
- linked source draft
- linked result draft, if created

## Storage Layout

Keep the repository's versioned-on-disk artifact pattern.

Suggested new roots under `data/`:

```text
manual_revision_requests/
  {job_id}/
    request_v001.json

manual_revision_runs/
  {job_id}/
    run_v001.json
```

Drafts and exports continue to use their existing stores.

## Backward Compatibility

### Draft Schema

All new `EssayDraft` fields must be optional or defaulted so older JSON still loads.

### Stores

Add listing helpers without breaking current callers:

- `DraftStore.list_versions(job_id)`
- `FinalExportStore.list_versions(job_id)`

Keep `load_latest(...)` unchanged.

### Routes

Do not break existing:

- job creation
- pipeline run
- current latest-export view

The new history and manual-reiteration endpoints should be additive.

## Recommended Rollout Order

### Phase 1: Draft And Export History

Implement:

- draft provenance fields
- history list/load endpoints
- frontend history panels
- export route fix so real export artifacts are available

This alone removes a large part of the copy-paste problem.

### Phase 2: Save User Edits

Implement:

- save-user-edit endpoint
- editor UI
- creation of `origin="user_edit"` drafts

At the end of this phase, users can reopen and save their own modified drafts even before manual LLM reiteration exists.

### Phase 3: Manual Review Runs

Implement:

- `ManualRevisionRequest`
- `ManualRevisionRun`
- selected-lens review execution
- stored review history
- review-only UI flow

This is the safest first LLM-assisted manual loop.

### Phase 4: Manual Revise

Implement:

- constrained manual revision prompt/service
- storage of new `manual_llm_revision` drafts
- optional post-revision selected-check rerun

## Test Plan

Focused backend tests:

- old draft JSON still loads with new optional fields
- draft history listing returns ordered versions
- export history listing returns stored export artifacts
- saving a user edit creates a new draft with correct provenance
- manual request and run stores save/load/list correctly
- selected review lenses trigger the expected services only
- validation and tone outputs are combined before manual revision
- tone beats anti-AI heuristics when both are selected
- evidence and citation failures still remain hard blockers in review outputs

Focused frontend tests:

- history panels render existing drafts and exports
- user can open a version into the editor
- saving an edit creates a new history row
- selected lenses are sent correctly
- saved run results can be reopened without copy-paste

Useful commands once implementation begins:

```powershell
pytest tests\drafting tests\exporting tests\validation tests\workflow
npm run build
```

## Acceptance Criteria

- Users can reopen prior saved essay outputs without copy-paste.
- The UI shows persisted draft and export history.
- User edits are stored as new immutable draft versions.
- Manual review requests are stored and can be reopened later.
- Manual revise requests produce new immutable draft versions.
- Validation and tone alignment results are combined before manual revision runs.
- Tone wins over anti-AI heuristics when the conflict is about authentic voice.
- Evidence, citation, assignment-fit, and length failures still surface clearly and are never hidden by tone success.
- Existing pipeline behavior remains intact for users who never touch manual reiteration.

## Open Questions For Review

1. Should the first UI ship with explicit save only, or do you want autosave in v1?
2. Should `review_only` and `revise` ship together, or should `review_only` land first?
3. Should export history be shown separately from draft history, or merged into one timeline view?
4. Should the default selected lenses be:
   - `tone + anti_ai`, or
   - `evidence + citations + tone`, or
   - no defaults?
5. Should post-manual-revision outputs automatically become the new "latest draft" for the existing export screen, or should the user explicitly choose which saved version to export next?

## Recommendation

Approve this feature in four phases, not one.

The highest-leverage first milestone is:

1. real draft/export history
2. saved user edits

That solves the copy-paste problem immediately and gives the reiteration loop a clean artifact base. After that, the manual review and manual revise flows can be added without fighting the storage model.
