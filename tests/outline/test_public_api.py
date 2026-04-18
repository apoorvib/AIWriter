def test_public_imports():
    from pdf_pipeline.outline import (
        DocumentOutline,
        OutlineEntry,
        OutlineStore,
        SectionLookupError,
        extract_outline,
        get_section,
        list_outline,
    )

    # Symbols loaded, namespaces wired.
    assert DocumentOutline.__name__ == "DocumentOutline"
    assert OutlineEntry.__name__ == "OutlineEntry"
    assert OutlineStore.__name__ == "OutlineStore"
    assert SectionLookupError.__name__ == "SectionLookupError"
    assert callable(extract_outline)
    assert callable(get_section)
    assert callable(list_outline)
