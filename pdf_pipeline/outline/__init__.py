"""Document outline extraction pipeline."""
from pdf_pipeline.outline.pipeline import extract_outline
from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry, SourceType
from pdf_pipeline.outline.storage import OutlineStore
from pdf_pipeline.outline.tools import SectionLookupError, get_section, list_outline

__all__ = [
    "DocumentOutline",
    "OutlineEntry",
    "OutlineStore",
    "SectionLookupError",
    "SourceType",
    "extract_outline",
    "get_section",
    "list_outline",
]
