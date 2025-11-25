from __future__ import annotations

import os
import sys
import time
from typing import Dict, Optional

from dotenv import load_dotenv
from openai import OpenAI
import openai

from .rate_limit import rate_limiter_registry
from .tokens import estimate_total_tokens

load_dotenv()

_client: Optional[OpenAI] = None

OPENAI_TRANSIENT_ERRORS = tuple(
    exc
    for exc in [
        getattr(openai, "RateLimitError", None),
        getattr(openai, "APIError", None),
        getattr(openai, "APIConnectionError", None),
        getattr(openai, "APITimeoutError", None),
    ]
    if exc is not None
)

OPENAI_HARD_ERRORS = tuple(
    exc
    for exc in [
        getattr(openai, "BadRequestError", None),
        getattr(openai, "AuthenticationError", None),
        getattr(openai, "PermissionDeniedError", None),
        getattr(openai, "NotFoundError", None),
    ]
    if exc is not None
)


def configure_model_limits(model_limits: Dict[str, int]) -> None:
    for model_name, tpm in model_limits.items():
        rate_limiter_registry.register(model_name, tpm)


def get_client() -> OpenAI:
    """Lazily initialize the OpenAI client so imports don't fail without env configured."""
    global _client
    if _client is None:
        api_key = os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
        _client = OpenAI(api_key=api_key)
    return _client


def call_model(
    *,
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int] = None,
    reasoning: Optional[str] = None,
    text_verbosity: Optional[str] = None,
    call_context: str = "",
    max_retries: int = 5,
    return_usage: bool = False,
) -> str:
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
    reasoning_arg = {"effort": reasoning} if reasoning else None
    total_est = estimate_total_tokens(system_prompt, user_prompt, max_output_tokens, model)
    limiter = rate_limiter_registry.get(model)
    if limiter:
        limiter.wait_for(total_est)

    request_args = {
        "model": model,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
        "max_output_tokens": max_output_tokens,
        "reasoning": reasoning_arg,
    }
    if text_verbosity:
        request_args["text"] = {"verbosity": text_verbosity}

    last_exc: Optional[Exception] = None
    transient_errors = OPENAI_TRANSIENT_ERRORS + (TimeoutError,)
    client = get_client()
    for attempt in range(max_retries):
        try:
            resp = client.responses.create(**request_args)
            text = getattr(resp, "output_text", None)
            if not text and getattr(resp, "output", None):
                for item in resp.output:
                    for block in getattr(item, "content", []) or []:
                        maybe_text = getattr(block, "text", None)
                        if maybe_text:
                            text = str(maybe_text)
                            break
                    if text:
                        break
            if not text:
                raise RuntimeError(f"{call_context}: no text block in response")
            usage_payload = None
            usage_obj = getattr(resp, "usage", None)
            if usage_obj:
                usage_payload = {
                    "input_tokens": getattr(usage_obj, "input_tokens", None),
                    "output_tokens": getattr(usage_obj, "output_tokens", None),
                    "total_tokens": getattr(usage_obj, "total_tokens", None),
                }
            return (str(text), usage_payload) if return_usage else str(text)
        except OPENAI_HARD_ERRORS as exc:
            raise RuntimeError(f"{call_context}: non-retryable OpenAI error: {exc}") from exc
        except transient_errors as exc:
            last_exc = exc
            backoff = min(2 ** attempt, 60)
            print(
                f"{call_context}: transient error ({exc!r}); retrying in {backoff:.1f}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
            continue
        except Exception as exc:
            last_exc = exc
            backoff = min(2 ** attempt, 60)
            print(
                f"{call_context}: unexpected error ({exc!r}); retrying in {backoff:.1f}s",
                file=sys.stderr,
            )
            time.sleep(backoff)
            continue
    raise RuntimeError(f"{call_context}: failed after {max_retries} attempts ({last_exc!r})")
