from pathlib import Path

from pdf_pipeline.outline.schema import DocumentOutline, OutlineEntry
from pdf_pipeline.outline.storage import OutlineStore


def _outline(version: int, title: str = "Ch 1") -> DocumentOutline:
    return DocumentOutline(
        source_id="s1", version=version,
        entries=[OutlineEntry(
            id="e0", title=title, level=1, parent_id=None,
            start_pdf_page=1, end_pdf_page=10,
            printed_page="1", confidence=1.0, source="pdf_outline",
        )],
    )


def test_save_and_load_round_trips(tmp_path: Path):
    store = OutlineStore(root=tmp_path)
    outline = _outline(1)
    store.save(outline)

    loaded = store.load_latest("s1")
    assert loaded == outline


def test_save_rejects_version_overwrite(tmp_path: Path):
    import pytest

    store = OutlineStore(root=tmp_path)
    store.save(_outline(1))
    with pytest.raises(FileExistsError):
        store.save(_outline(1, title="Different"))


def test_load_latest_picks_highest_version(tmp_path: Path):
    store = OutlineStore(root=tmp_path)
    store.save(_outline(1, title="v1"))
    store.save(_outline(2, title="v2"))
    store.save(_outline(3, title="v3"))

    loaded = store.load_latest("s1")
    assert loaded.version == 3
    assert loaded.entries[0].title == "v3"


def test_load_latest_raises_when_missing(tmp_path: Path):
    import pytest

    store = OutlineStore(root=tmp_path)
    with pytest.raises(KeyError):
        store.load_latest("nope")
