from __future__ import annotations

import re
from typing import List

from .models import TextChunk

CJK_CHAR_RE = re.compile(
    r"[\u4E00-\u9FFF"
    r"\u3400-\u4DBF"
    r"\uF900-\uFAFF"
    r"\u3040-\u309F"
    r"\u30A0-\u30FF"
    r"\uAC00-\uD7AF]"
)


def is_cjk_token(tok: str) -> bool:
    return len(tok) == 1 and bool(CJK_CHAR_RE.match(tok))


def tokenize_mixed(text: str) -> List[str]:
    tokens: List[str] = []
    buff: List[str] = []

    def flush_buff() -> None:
        nonlocal buff
        if buff:
            tokens.append("".join(buff))
            buff = []

    for ch in text:
        if ch.isspace():
            flush_buff()
        elif CJK_CHAR_RE.match(ch):
            flush_buff()
            tokens.append(ch)
        else:
            buff.append(ch)

    flush_buff()
    return tokens


def rebuild_text(tokens: List[str]) -> str:
    if not tokens:
        return ""
    out_parts: List[str] = []
    prev_is_cjk = is_cjk_token(tokens[0])
    out_parts.append(tokens[0])
    for tok in tokens[1:]:
        cur_is_cjk = is_cjk_token(tok)
        if not (prev_is_cjk and cur_is_cjk):
            out_parts.append(" ")
        out_parts.append(tok)
        prev_is_cjk = cur_is_cjk
    return "".join(out_parts)


def chunk_text(text: str, max_units: int, overlap: int) -> List[TextChunk]:
    units = tokenize_mixed(text)
    step = max(max_units - overlap, 1)
    chunks: List[TextChunk] = []
    start = 0
    idx = 0
    total_units = len(units)
    while start < total_units:
        end = min(start + max_units, total_units)
        chunk_units = units[start:end]
        chunk_text = rebuild_text(chunk_units)
        chunks.append(TextChunk(text=chunk_text, start_unit=start + 1, end_unit=end, idx=idx))
        idx += 1
        start += step
    return chunks
