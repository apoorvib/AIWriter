from __future__ import annotations

import shutil
from pathlib import Path

from essay_writer.agent_tools.id_utils import short_hash
from essay_writer.writing.schema import WritingContextItem, text_sha256
from essay_writer.writing.storage import WritingContextStore


class WritingContextLimitError(ValueError):
    pass


class UnsupportedWritingContextError(ValueError):
    pass


class WritingContextService:
    SUFFIXES = {".txt", ".md", ".markdown", ".pdf", ".docx"}

    def __init__(self, store: WritingContextStore, *, document_reader=None,
                 max_items=10, max_item_chars=50_000, max_total_chars=150_000):
        self.store, self.document_reader = store, document_reader
        self.max_items, self.max_item_chars = max_items, max_item_chars
        self.max_total_chars = max_total_chars

    def add_inline(self, writing_run_id: str, text: str, *, label: str):
        return self._save(writing_run_id, text, label, "inline", None)

    def add_answer(self, writing_run_id: str, text: str, *, label: str = "clarification-answer"):
        """Persist a human clarification answer as an immutable context item.

        Marked with ``kind="answer"`` so the completion ledger can detect that
        a blocking brief has since been answered and re-run the brief step."""
        return self._save(writing_run_id, text, label, "answer", None)

    def add_file(self, writing_run_id: str, path: str | Path, *, label: str):
        source = Path(path)
        if not source.exists():
            raise FileNotFoundError(source)
        suffix = source.suffix.lower()
        if suffix not in self.SUFFIXES:
            raise UnsupportedWritingContextError(f"unsupported writing context suffix {suffix!r}")
        if suffix in {".txt", ".md", ".markdown"}:
            text = source.read_text(encoding="utf-8")
        else:
            reader = self.document_reader or self._reader()
            result = reader.extract(str(source))
            text = "\n\n".join(str(p.text).strip() for p in result.pages if str(p.text).strip())
        item = self._save(writing_run_id, text, label, "file", str(source.resolve()))
        target = self.store.root / writing_run_id / item.context_id / f"original{suffix}"
        if not target.exists():
            shutil.copy2(source, target)
        return item

    def _save(self, run_id: str, text: str, label: str, kind: str,
              source_path: str | None):
        text = text.replace("\r\n", "\n").strip()
        if len(text) > self.max_item_chars:
            raise WritingContextLimitError(
                f"writing context item exceeds {self.max_item_chars} characters"
            )
        context_id = f"wctx-{short_hash([run_id, label, text])}"
        try:
            return self.store.load(run_id, context_id)
        except KeyError:
            pass
        existing = self.store.list(run_id)
        if len(existing) >= self.max_items:
            raise WritingContextLimitError(f"at most {self.max_items} context items")
        if sum(item.char_count for item in existing) + len(text) > self.max_total_chars:
            raise WritingContextLimitError(
                f"total context exceeds {self.max_total_chars} characters"
            )
        content_path = self.store.root / run_id / context_id / "content.txt"
        item = WritingContextItem(
            context_id=context_id, writing_run_id=run_id, label=label, kind=kind,
            content_path=str(content_path), content_sha256=text_sha256(text),
            char_count=len(text), source_path=source_path,
        )
        return self.store.save(item, text)

    @staticmethod
    def _reader():
        from pdf_pipeline.document_reader import DocumentReader
        return DocumentReader()


__all__ = ["UnsupportedWritingContextError", "WritingContextLimitError",
           "WritingContextService"]
