# Future Upgrades

## PageIndex OCR and Document Intelligence

PageIndex should be considered as an optional cloud document-intelligence backend
for the essay writer ingestion and research pipeline.

It should not replace the local extraction pipeline. Instead, it should sit
beside the existing local providers and be used when higher-quality structure,
page citations, or long-document reasoning are worth the external API dependency
and per-page cost.

## Why PageIndex Could Help

The current local OCR pipeline is mostly page-oriented:

```text
PDF page image -> OCR text per page
```

That is useful, but essay research often needs richer document structure:

- section headings
- subsection hierarchy
- tables
- references
- figure captions
- page-level evidence
- source-grounded retrieval

PageIndex OCR is designed around long-document understanding. Its documented
outputs include page-level Markdown OCR as well as hierarchical document tree
results. That maps well to a source-grounded essay workflow because the system
needs to preserve where evidence came from, not just extract raw text.

## Where PageIndex Fits

Recommended provider stack:

```text
DocumentReader
  -> PDF text-native: pypdf
  -> DOCX: local docx reader
  -> OCR local small: Tesseract
  -> OCR local medium: EasyOCR
  -> OCR local high: PaddleOCR
  -> OCR cloud structured: PageIndex
```

PageIndex is most useful for:

- scanned PDFs where `pypdf` has little or no embedded text
- long academic PDFs
- books or chapters with many sections
- source documents where page citations matter
- documents with complex layout, tables, figures, or references
- retrieval over source documents before drafting
- building a source map for essay claims

Local OCR is still better for:

- development without API keys
- offline workflows
- privacy-sensitive documents
- cheap bulk OCR
- simple scanned documents
- avoiding vendor lock-in
- avoiding per-page processing costs

## Integration Shape

Use PageIndex as a separate extraction provider behind the same document
extraction interface.

PageIndex OCR page results can be normalized into the existing result model:

```python
DocumentExtractionResult(
    source_path="...",
    page_count=page_count,
    pages=[
        PageText(
            page_number=page["page_index"],
            text=page["markdown"],
            char_count=len(page["markdown"]),
            extraction_method="pageindex:ocr",
        )
    ],
)
```

The system should also persist PageIndex-specific artifacts separately:

```text
pageindex_doc_id
raw_ocr_json
tree_json
node_json
retrieval_ready
processed_at
```

These artifacts are valuable for later research, citations, and traceability.

## REST API vs MCP

Start with the PageIndex REST API for ingestion.

Ingestion is a straightforward backend workflow:

```text
Upload PDF
  -> receive doc_id
  -> poll processing status
  -> fetch OCR results
  -> fetch tree results
  -> normalize into local artifacts
```

Use MCP later when an agent needs to query the already-indexed documents during
research.

Recommended split:

```text
Ingestion pipeline: REST API
Research agent/tool layer: MCP optional
```

MCP would be useful for agentic research tasks such as:

- find evidence for a claim
- retrieve relevant pages about a topic
- compare two source documents
- return cited supporting passages
- inspect document sections by hierarchy

## Expected API Capabilities

The PageIndex documentation describes:

- uploading documents for processing
- retrieving OCR output
- retrieving hierarchical tree output
- page-level references and citations
- API and MCP access

The OCR result formats include:

- page format
- node format
- raw concatenated Markdown

Page-level OCR results include a page index and Markdown content, which makes
them a reasonable fit for the current `PageText` abstraction.

## Product Caveat

There appears to be some product/documentation variation around supported input
types. Some PageIndex product material mentions PDF, Markdown, and DOCX, while
the developer document-processing endpoint reviewed during research explicitly
described PDF upload. Markdown also has a separate endpoint.

Assume PDF is the safest first integration target until the API is tested.

For `.docx`, keep the local Word reader as the primary path unless PageIndex's
developer API is confirmed to support DOCX uploads reliably.

## Cost and Privacy Considerations

PageIndex is a cloud service. Before using it as a default ingestion path, decide:

- whether user documents may be uploaded to a third-party service
- whether opt-in consent is required per document
- whether documents should be deleted after processing
- whether enterprise/private deployment is needed
- what per-page budget is acceptable
- how to handle documents that exceed plan limits

The pricing model reviewed during research was page-credit based, with indexing
charged per page. This means large books or long scanned PDFs can become costly
relative to local OCR.

## Recommendation

Add PageIndex as an optional provider, not the default provider.

Initial priority:

1. Keep `pypdf` for text-native PDFs.
2. Keep the local `.docx` reader for Word task specifications and source docs.
3. Keep Tesseract, EasyOCR, and PaddleOCR for local OCR tiers.
4. Add PageIndex for structured cloud OCR and long-document understanding.
5. Later expose PageIndex through MCP for research-agent retrieval.

The best use of PageIndex in this project is not merely "better OCR." It is a
structured source-understanding layer that can improve downstream research,
evidence extraction, citation mapping, and essay grounding.
