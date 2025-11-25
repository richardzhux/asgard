from __future__ import annotations

import sys
from pathlib import Path

from pipelines.memoir_pipeline import MemoirPipeline, MemoirSettings

DEFAULT_MEMOIR_PATH = Path("/Users/rx/Desktop/memoirtest.md")
MODEL_LIMITS = {
    "gpt-5.1": 1_000_000,
}


def parse_args() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser().resolve()
    return DEFAULT_MEMOIR_PATH


def main() -> None:
    memoir_path = parse_args()
    settings = MemoirSettings(
        memoir_path=memoir_path,
        model_limits=MODEL_LIMITS,
    )
    pipeline = MemoirPipeline(settings)
    pipeline.run()


if __name__ == "__main__":
    main()
