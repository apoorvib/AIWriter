from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import asdict
from pathlib import Path

from essay_writer.writing_style.schema import (
    HumanWritingSample,
    PromptSampleText,
    StyleAnchorExcerpt,
    WritingStyleContent,
)


class HumanWritingSampleStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def sample_dir(self, sample_id: str) -> Path:
        return self.root / sample_id

    def exists(self, sample_id: str) -> bool:
        return (self.sample_dir(sample_id) / "sample.json").exists()

    def save(
        self,
        *,
        sample_id: str,
        title: str,
        source_path: str | Path,
        source_type: str,
        extracted_text: str,
        cleaned_text: str,
        cleaned_text_hash: str,
        page_count: int,
        extraction_method: str,
        word_count: int,
        warnings: list[str],
        normalizer_version: str,
    ) -> HumanWritingSample:
        dir_ = self.sample_dir(sample_id)
        dir_.mkdir(parents=True, exist_ok=True)
        source = Path(source_path)
        original_path = _persist_original_file(source, dir_)
        extracted_path = dir_ / "extracted_text.txt"
        cleaned_path = dir_ / "cleaned_text.txt"
        _write_text(extracted_path, extracted_text)
        _write_text(cleaned_path, cleaned_text)
        sample = HumanWritingSample(
            id=sample_id,
            title=title,
            source_filename=source.name,
            source_type=source_type,
            original_path=str(original_path),
            artifact_dir=str(dir_),
            extracted_text_path=str(extracted_path),
            cleaned_text_path=str(cleaned_path),
            cleaned_text_hash=cleaned_text_hash,
            page_count=page_count,
            extraction_method=extraction_method,
            char_count=len(cleaned_text),
            word_count=word_count,
            warnings=warnings,
            normalizer_version=normalizer_version,
        )
        _write_json(dir_ / "sample.json", asdict(sample))
        return sample

    def load(self, sample_id: str) -> HumanWritingSample:
        path = self.sample_dir(sample_id) / "sample.json"
        if not path.exists():
            raise KeyError(sample_id)
        return HumanWritingSample(**_read_json(path))

    def list_samples(self) -> list[HumanWritingSample]:
        samples: list[HumanWritingSample] = []
        for path in sorted(self.root.glob("*/sample.json")):
            samples.append(HumanWritingSample(**_read_json(path)))
        return samples

    def load_cleaned_text(self, sample_id: str) -> str:
        sample = self.load(sample_id)
        return Path(sample.cleaned_text_path).read_text(encoding="utf-8")

    def load_prompt_sample(self, sample_id: str) -> PromptSampleText:
        sample = self.load(sample_id)
        return PromptSampleText(
            sample_id=sample.id,
            title=sample.title,
            cleaned_text=Path(sample.cleaned_text_path).read_text(encoding="utf-8"),
            cleaned_text_hash=sample.cleaned_text_hash,
            warnings=sample.warnings,
        )

    def load_prompt_samples(self, sample_ids: list[str]) -> list[PromptSampleText]:
        return [self.load_prompt_sample(sample_id) for sample_id in sample_ids]


class WritingStyleContentStore:
    def __init__(self, root: str | Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    def save(self, content: WritingStyleContent) -> None:
        path = self._path(content.id)
        if path.exists():
            raise FileExistsError(f"writing style content already exists: {content.id}")
        _write_json(path, asdict(content))

    def load(self, content_id: str) -> WritingStyleContent:
        path = self._path(content_id)
        if not path.exists():
            raise KeyError(content_id)
        return _content_from_payload(_read_json(path))

    def load_by_fingerprint(self, sample_fingerprint: str) -> WritingStyleContent:
        return self.load(stable_writing_style_content_id(sample_fingerprint))

    def exists_for_fingerprint(self, sample_fingerprint: str) -> bool:
        return self._path(stable_writing_style_content_id(sample_fingerprint)).exists()

    def _path(self, content_id: str) -> Path:
        return self.root / f"{content_id}.json"


def stable_writing_style_content_id(sample_fingerprint: str) -> str:
    return f"style-{sample_fingerprint[:16]}"


def _content_from_payload(payload: dict) -> WritingStyleContent:
    payload = dict(payload)
    payload["anchor_excerpts"] = [
        StyleAnchorExcerpt(**item) for item in payload.get("anchor_excerpts", [])
    ]
    return WritingStyleContent(**payload)


def _persist_original_file(source_path: Path, dir_: Path) -> Path:
    suffix = source_path.suffix.lower() or ".txt"
    target = dir_ / f"original{suffix}"
    if source_path.resolve() != target.resolve():
        shutil.copy2(source_path, target)
    return target


def _write_json(path: Path, payload: dict) -> None:
    _write_text(path, json.dumps(payload, ensure_ascii=True, indent=2))


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent))
    tmp_path = Path(tmp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(tmp_path, path)
    finally:
        tmp_path.unlink(missing_ok=True)

