import json

import jsonschema

from pdf_pipeline.outline.prompts import (
    TOC_EXTRACTION_SCHEMA,
    TOC_SYSTEM_PROMPT,
    build_user_message,
)


def test_system_prompt_instructs_not_to_trust_inline_numbers():
    assert "pdf_page" in TOC_SYSTEM_PROMPT
    assert "never" in TOC_SYSTEM_PROMPT.lower() or "only" in TOC_SYSTEM_PROMPT.lower()


def test_user_message_contains_pdf_pages_json():
    pages = [
        {"pdf_page": 8, "text": "Contents\nChapter 1 ... 1"},
        {"pdf_page": 9, "text": "Chapter 2 ... 15"},
    ]
    msg = build_user_message(pages)
    payload = json.loads(msg)
    assert payload == {"pages": pages}


def test_schema_accepts_valid_response():
    response = {
        "pages": [
            {"pdf_page": 8, "is_toc": True},
            {"pdf_page": 9, "is_toc": True},
        ],
        "entries": [
            {"title": "Chapter 1", "level": 1, "printed_page": "1"},
            {"title": "Chapter 2", "level": 1, "printed_page": "15"},
        ],
    }
    jsonschema.validate(response, TOC_EXTRACTION_SCHEMA)


def test_schema_rejects_missing_fields():
    bad = {"pages": [{"pdf_page": 8}]}
    try:
        jsonschema.validate(bad, TOC_EXTRACTION_SCHEMA)
    except jsonschema.ValidationError:
        return
    raise AssertionError("expected validation error")
