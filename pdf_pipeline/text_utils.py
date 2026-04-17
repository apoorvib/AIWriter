from __future__ import annotations

import re

_MULTI_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(raw_text: str) -> str:
    lines = [line.rstrip() for line in raw_text.replace("\r\n", "\n").replace("\r", "\n").split("\n")]
    text = "\n".join(lines).strip()
    return _MULTI_BLANK_LINES.sub("\n\n", text)
