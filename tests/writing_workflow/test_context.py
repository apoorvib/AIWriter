from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from essay_writer.writing.context import (
    UnsupportedWritingContextError,
    WritingContextLimitError,
    WritingContextService,
)
from essay_writer.writing.storage import WritingStores
from tests.agent_tools._tmp import LocalAgentTempDir


def test_inline_context_is_persisted_and_deduplicated() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        service = WritingContextService(stores.context)
        first = service.add_inline("run1", "Launch is July 10.", label="launch note")
        second = service.add_inline("run1", "Launch is July 10.", label="launch note")

        assert first.context_id == second.context_id
        assert stores.context.load_content(first) == "Launch is July 10."


def test_context_rejects_oversized_inline_text() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        service = WritingContextService(
            stores.context, max_item_chars=100, max_total_chars=200
        )
        with pytest.raises(WritingContextLimitError, match="100 characters"):
            service.add_inline("run1", "x" * 101, label="brief")


def test_context_rejects_total_character_overflow() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        service = WritingContextService(
            stores.context, max_item_chars=100, max_total_chars=120
        )
        service.add_inline("run1", "a" * 70, label="one")
        with pytest.raises(WritingContextLimitError, match="total context"):
            service.add_inline("run1", "b" * 60, label="two")


def test_plain_text_file_is_read_as_utf8() -> None:
    with LocalAgentTempDir() as tmp:
        source = Path(tmp) / "note.md"
        source.write_text("# Launch\n\nShip Friday.", encoding="utf-8")
        stores = WritingStores.from_data_dir(Path(tmp) / "data")
        service = WritingContextService(stores.context)

        item = service.add_file("run1", source, label="launch")

        assert item.kind == "file"
        assert item.source_path == str(source.resolve())
        assert stores.context.load_content(item).endswith("Ship Friday.")


def test_pdf_uses_injected_document_reader() -> None:
    class FakeReader:
        def extract(self, path: str):
            return SimpleNamespace(
                pages=[SimpleNamespace(text="Page one"), SimpleNamespace(text="Page two")]
            )

    with LocalAgentTempDir() as tmp:
        source = Path(tmp) / "source.pdf"
        source.write_bytes(b"not-a-real-pdf")
        stores = WritingStores.from_data_dir(Path(tmp) / "data")
        service = WritingContextService(stores.context, document_reader=FakeReader())

        item = service.add_file("run1", source, label="source")

        assert stores.context.load_content(item) == "Page one\n\nPage two"


def test_missing_and_unsupported_files_are_explicit_errors() -> None:
    with LocalAgentTempDir() as tmp:
        stores = WritingStores.from_data_dir(tmp)
        service = WritingContextService(stores.context)
        with pytest.raises(FileNotFoundError):
            service.add_file("run1", Path(tmp) / "missing.txt", label="missing")
        unsupported = Path(tmp) / "data.csv"
        unsupported.write_text("a,b", encoding="utf-8")
        with pytest.raises(UnsupportedWritingContextError, match=".csv"):
            service.add_file("run1", unsupported, label="unsupported")
