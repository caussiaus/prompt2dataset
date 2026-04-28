"""Normalize chunk/evidence text before it is sent to the LLM.

Docling and PDF parsers can emit control characters, odd whitespace, or
isolated NULs that waste tokens and confuse models. This module keeps the
payload readable without rewriting semantic content.
"""
from __future__ import annotations

import re

_CTRL_EXCEPT_NL_TAB = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
_WS_RUN = re.compile(r"[ \t]+")
_NL_RUN = re.compile(r"\n{4,}")


def sanitize_evidence_text(text: str, *, max_len: int | None = None) -> str:
    """Strip garbage characters and compress whitespace; optional hard cap.

    - Removes NUL and most C0 control characters (keeps \\n and \\t).
    - Collapses long runs of spaces/tabs; caps consecutive newlines.
    - Strips leading/trailing whitespace per line when cheap to do.
    """
    if not text:
        return ""
    s = str(text).replace("\x00", "")
    s = _CTRL_EXCEPT_NL_TAB.sub("", s)
    lines = []
    for line in s.splitlines():
        line = _WS_RUN.sub(" ", line).strip()
        if line:
            lines.append(line)
    s = "\n".join(lines)
    s = _NL_RUN.sub("\n\n\n", s)
    if max_len is not None and len(s) > max_len:
        s = s[: max_len - 1].rstrip() + "…"
    return s
