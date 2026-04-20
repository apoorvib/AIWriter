Goals

- Let the AI choose specific source spans for research and outlining.
- Preserve exact source traceability.
- Avoid confusion between physical PDF pages and printed page labels.
- Support PDFs, DOCX, Markdown, TXT, and Notes.
- Keep OCR lazy and page-level for PDFs.
- Keep current chunk/index behavior as a fallback during migration.
- Avoid dumping entire large sources into prompts.  


Non-Goals For First Version

- No unlimited full-document prompt stuffing.
- No live OCR tests in the default test suite.
- No mandatory embeddings dependency in the first cut.
- No provider-native tool calling required initially.
- No PDF rendering for DOCX pagination.  


———

Core Concept

Add a new source access layer:

source ingestion  
 -> source card  
 -> source map  
 -> source text units  
 -> source resolver/search  
 -> source packets for LLM stages

The LLM sees source cards and source maps first. It asks for source spans using structured locators. The app resolves  
 those locators into exact text packets.

———

New Data Model

Add something like:

essay_writer/sources/access_schema.py  
 essay_writer/sources/access.py  
 essay_writer/sources/map.py

Core dataclasses:

@dataclass(frozen=True)  
 class SourceUnit:  
 source_id: str  
 unit_id: str  
 unit_type: Literal["pdf_page", "pdf_page_range", "section", "chunk"]  
 title: str | None  
 heading_path: list[str]  
 pdf_page_start: int | None  
 pdf_page_end: int | None  
 printed_page_start: str | None  
 printed_page_end: str | None  
 char_count: int  
 text_quality: str  
 summary: str | None  
 preview: str

@dataclass(frozen=True)  
 class SourceMap:  
 source_id: str  
 source_type: str  
 units: list[SourceUnit]  
 warnings: list[str]

@dataclass(frozen=True)  
 class SourceLocator:  
 source_id: str  
 locator_type: Literal["pdf_pages", "section", "search", "chunk"]  
 pdf_page_start: int | None = None  
 pdf_page_end: int | None = None  
 printed_page_label: str | None = None  
 section_id: str | None = None  
 query: str | None = None  
 chunk_id: str | None = None  
 reason: str | None = None

@dataclass(frozen=True)  
 class SourceTextPacket:  
 source_id: str  
 locator: SourceLocator  
 text: str  
 pdf_page_start: int | None
pdf_page_end: int | None  
 printed_page_start: str | None  
 printed_page_end: str | None  
 heading_path: list[str]  
 extraction_method: str  
 text_quality: str  
 warnings: list[str]

Important rule: retrieval always uses pdf_page_number, not printed page labels. Printed labels are metadata for humans and
citations.

———

PDF Handling

For PDFs, store page-level source units:

unit_type = "pdf_page"  
 pdf_page_start = 17  
 pdf_page_end = 17  
 printed_page_start = "3"  
 printed_page_end = "3"

Use 1-based physical PDF page numbers everywhere.

If page labels are available from PDF metadata, store them. If not, leave them None.

Do not let the model request ambiguous “page 3” unless it specifies physical PDF page. If it gives a printed label, the  
 resolver can attempt lookup, but returned packets must include the physical page number.

Example model request:

{  
 "source_id": "src-abc",  
 "locator_type": "pdf_pages",  
 "pdf_page_start": 17,  
 "pdf_page_end": 20,  
 "reason": "Chapter section on the policy background"  
 }

Resolver returns:

{  
 "source_id": "src-abc",  
 "pdf_page_start": 17,  
 "pdf_page_end": 20,  
 "printed_page_start": "3",  
 "printed_page_end": "6",  
 "text": "..."  
 }

Lazy OCR rule

When resolving PDF pages:

1. Check stored page text.
2. If text exists and quality is readable, return it.
3. If missing or low quality, run OCR only for requested physical PDF pages.
4. Store page OCR output.
5. Return resolved packet.  


This should reuse the existing OCR parallel/page-worker concepts, but in first implementation can call a small page-level
extractor behind a resolver method.

No whole-document OCR fallback for source access.

———

DOCX / Markdown / TXT Handling

For non-PDF documents, build section-level maps.

Markdown sectioner:

- split by ATX headings: #, ##, ###
- preserve heading hierarchy
- include paragraphs/lists under each heading
- fallback to blank-line paragraph groups if no headings exist  


DOCX sectioner:

- use Word paragraph styles when available
- headings create sections
- tables become section blocks or attached blocks
- fallback to paragraph groups if no heading styles exist  


TXT / Notes sectioner:

- detect heading-like lines
- detect separators like ---, ===
- fallback to paragraph groups  


Each section gets:

unit_type = "section"  
 unit_id = "src-abc-sec-0004"  
 heading_path = ["Background", "Policy Debate"]  
 summary = "..."  
 preview = "..."

The model requests sections, not page numbers:

{  
 "source_id": "src-notes",  
 "locator_type": "section",  
 "section_id": "src-notes-sec-0004",  
 "reason": "Contains the strongest counterargument"  
 }

———

Embeddings

Use embeddings as phase 2, not the core first cut.

First cut:

- structure-aware source maps
- existing SQLite FTS
- exact page/section requests
- chunk fallback  


Second cut:

- optional embeddings index over SourceUnits
- embedding search returns SourceLocators
- resolver still returns text packets from stable units  


Embedding search should never be the provenance unit. It only helps choose source units.

———

LLM Workflow Changes

Current flow:

source cards + index manifests
-> topic ideation returns chunk_ids/search_queries  
 -> app retrieves chunks  
 -> research LLM sees chunks

New flow:

source cards + source maps  
 -> topic ideation returns candidate topics + recommended source locators  
 -> source resolver returns source text packets  
 -> research LLM creates evidence map  
 -> research LLM can request follow-up locators if gaps remain  
 -> outline gets evidence map + source packets

Topic Ideation

Topic ideation receives:

- task spec
- source cards
- compact source maps
- previous/rejected topics  


It returns:

{  
 "candidates": [  
 {  
 "title": "...",  
 "research_question": "...",  
 "source_requests": [
 {
 "source_id": "src-abc",
 "locator_type": "pdf_pages",
 "pdf_page_start": 12,
 "pdf_page_end": 16,
 "reason": "Relevant chapter section"
 }
 ],  
 "fallback_search_queries": [...]  
 }  
 ]  
 }

Keep chunk_ids temporarily for backward compatibility, but make source_requests the preferred path.

Research Planning

Upgrade research planning from “source priority list only” to “source request plan.”

It can remain deterministic initially:

- take selected topic’s source_requests
- validate source IDs and page ranges
- cap budgets
- create ResearchPlan  


Later it can become LLM-backed.

Final Topic Research

Research receives:

- task spec
- selected topic
- resolved SourceTextPackets
- citation metadata
- packet-level provenance  


It returns:

- evidence notes
- evidence groups
- conflicts
- gaps
- optional follow-up source requests  


Add bounded iterative research:

round 1 source packets  
 -> research result  
 -> if followup_source_requests and round < max_rounds:  
 resolve more packets  
 call research again

Suggested limits:

max_research_rounds = 2  
 max_source_packets = 20  
 max_total_source_chars = 60_000  
 max_pdf_pages_per_request = 20

Outlining

Outline should receive:

- task spec
- selected topic
- evidence map
- source packets used for evidence
- unresolved gaps/conflicts  


The outline model should not need arbitrary full source access, but it should receive enough raw text context to reason  
 about structure and evidence placement.

Drafting

Drafting can still mainly use evidence notes and outline, but for stronger grounding it should receive:

- evidence notes
- quotes/paraphrases
- section-source map
- optionally the source packets associated with outline sections  


Do not give the draft model all sources by default. Give it the packets selected during research and outline.

———

Source Resolver API

Add:

class SourceAccessService:  
 def get_source_map(self, source_id: str) -> SourceMap: ...

      def resolve_locators(
          self,
          locators: list[SourceLocator],
          *,
          max_total_chars: int,
      ) -> list[SourceTextPacket]: ...

      def search_source(
          self,
          source_id: str,
          query: str,
          *,
          limit: int = 5,
      ) -> list[SourceLocator]: ...


Resolver responsibilities:

- validate source exists
- validate locator belongs to source
- cap page ranges
- map printed labels to physical PDF pages when possible
- run lazy OCR for PDF pages if needed
- load section text for DOCX/Markdown/TXT
- deduplicate overlapping packets
- return warnings instead of silently failing

———

Storage Changes

Current source store writes:

source.json  
 pages.jsonl  
 chunks.jsonl  
 full_text.txt  
 source_card.json  
 index.sqlite  
 index_manifest.json

Add:

source_map.json  
 source_units.jsonl  
 page_text/  
 pdf_page_0001.json  
 pdf_page_0002.json

For non-PDF:

sections.jsonl

For PDF, pages.jsonl already exists but should be normalized into page text artifacts with physical page number and  
 printed label metadata.

———

Backward Compatibility

Keep current chunk path during migration.

Retrieval order should become:

1. Resolve explicit source_requests.
2. Resolve explicit chunk_ids if still present.
3. Run FTS search queries.
4. Later: run embedding search.
5. If nothing found, return a structured insufficient-evidence error.  


This lets existing tests and flows keep passing while source requests become the primary path.

———

Testing Plan

Unit tests:

- Markdown headings produce section source units.
- DOCX headings produce section source units.
- TXT fallback creates paragraph/section units.
- PDF source map keeps pdf_page_number and printed labels separate.
- Resolver rejects out-of-range physical page requests.
- Resolver does not treat printed label "3" as PDF page 3 unless explicitly mapped.
- Resolver returns exact requested PDF page range.
- Resolver caps oversized page ranges.
- Topic ideation context includes source maps.
- Research accepts SourceTextPackets.
- Follow-up source requests are bounded.  


Mock OCR tests:

- Missing PDF page text triggers lazy page OCR call.
- Existing readable page text does not trigger OCR.
- Low-quality page text triggers OCR for only requested pages.  


No default live OCR tests.

———

Implementation Phases

1. Source map schema and storage  
   Add SourceUnit, SourceMap, SourceLocator, SourceTextPacket.  
   Save/load maps in SourceStore.
2. Map builders  
   Add PDF page map builder.  
   Add Markdown/TXT section builders.  
   Add DOCX section builder using paragraph styles where possible.
3. Source access service  
   Implement get_source_map, resolve_locators, and search_source.  
   Keep chunk fallback.
4. Topic ideation schema update  
   Add source_requests to topic candidates.  
   Keep chunk_ids temporarily.
5. Research pipeline update  
   Resolve selected topic source requests before final research.  
   Pass SourceTextPackets instead of only retrieved chunks.
6. Follow-up retrieval loop  
   Let research return followup_source_requests.  
   Resolve them and run one more bounded research pass.
7. Optional embeddings  
   Add optional embeddings index over source units.  
   Use only as fallback search, not as the source provenance layer.  


———

Open Decisions

- Should source maps include per-page/section LLM summaries, deterministic previews, or both?
- What should the max page range per request be? I’d start with 20 physical PDF pages.
- Should outline get raw source packets directly, or only evidence notes plus packet references? I’d give outline the  
  packets used in research.
- Which embedding provider should be optional later: local sentence-transformers, OpenAI embeddings, or provider-agnostic
  adapter?
- Should source-request planning be a separate LLM call, or part of topic ideation? I’d start by adding it to topic  
  ideation, then split if prompts get too large.
