from __future__ import annotations

from functools import lru_cache
from typing import Optional

try:
    import tiktoken
except ImportError:  # pragma: no cover
    tiktoken = None


@lru_cache(maxsize=32)
def _encoding_for_model(model: str):
    if tiktoken is None:
        return None
    try:
        return tiktoken.encoding_for_model(model)
    except Exception:
        return tiktoken.get_encoding("cl100k_base") if tiktoken else None


def estimate_tokens(text: str, model: str) -> int:
    if not text:
        return 0
    if tiktoken is None:
        return max(1, len(text) // 4)
    enc = _encoding_for_model(model)
    if enc is None:
        return max(1, len(text) // 4)
    return len(enc.encode(text))


def estimate_total_tokens(system_prompt: str, user_prompt: str, max_output_tokens: Optional[int], model: str) -> int:
    return estimate_tokens(system_prompt, model) + estimate_tokens(user_prompt, model) + (max_output_tokens or 0)
