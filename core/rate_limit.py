from __future__ import annotations

import sys
import time
from dataclasses import dataclass
from typing import Dict, Optional


@dataclass
class ModelRateLimit:
    tokens_per_minute: int


class TokenRateLimiter:
    def __init__(self, limit: ModelRateLimit):
        self.limit = limit
        self.allowance = limit.tokens_per_minute
        self.last_check = time.time()

    def wait_for(self, tokens: int) -> None:
        if self.limit.tokens_per_minute <= 0:
            return
        now = time.time()
        elapsed = now - self.last_check
        self.last_check = now
        self.allowance = min(
            self.limit.tokens_per_minute,
            self.allowance + elapsed * (self.limit.tokens_per_minute / 60.0),
        )
        if tokens <= self.allowance:
            self.allowance -= tokens
            return
        deficit = tokens - self.allowance
        wait_seconds = deficit / (self.limit.tokens_per_minute / 60.0)
        print(
            f"[rate-limit] Sleeping {wait_seconds:.1f}s for ~{self.limit.tokens_per_minute} tpm",
            file=sys.stderr,
        )
        time.sleep(wait_seconds)
        self.allowance = 0.0


class RateLimiterRegistry:
    def __init__(self) -> None:
        self._limits: Dict[str, ModelRateLimit] = {}
        self._limiters: Dict[str, TokenRateLimiter] = {}

    def register(self, model: str, tokens_per_minute: int) -> None:
        self._limits[model] = ModelRateLimit(tokens_per_minute=tokens_per_minute)

    def get(self, model: str) -> Optional[TokenRateLimiter]:
        limit = self._limits.get(model)
        if not limit:
            return None
        limiter = self._limiters.get(model)
        if not limiter:
            limiter = TokenRateLimiter(limit)
            self._limiters[model] = limiter
        return limiter


rate_limiter_registry = RateLimiterRegistry()
