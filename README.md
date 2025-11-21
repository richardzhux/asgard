# Memoir Analysis Pipeline

`memoir2.py` turns a long autobiographical manuscript into a structured dossier
in two stages:

1. **Chunk summaries** – the memoir is split into overlapping mixed-language
   chunks (English words or single CJK characters). Each chunk is sent to a
   psychological field-notes prompt to capture timeframes, key events, coping
   moves, tensions, etc.
2. **Global synthesis** – once every chunk is summarized, all chunk notes are
   merged into a 5k+ word analysis that walks through eras, attachment loops,
   work arcs, and recommendations.

The script is resumable, guards against stale summaries, and throttles OpenAI
calls so it can be run repeatedly while editing the memoir.

## Requirements

- Python 3.9+
- `python-dotenv` and `openai` (`pip install python-dotenv openai`)
- Optional: `tiktoken` for accurate token estimation
- `OPENAI_API_KEY` must be available (usually via `.env`)

Run the pipeline with:

```bash
python memoir2.py
```

## Configuration Highlights (see `memoir2.py`)

- `MODEL_SUMMARY` / `MODEL_SYNTHESIS`: models for chunk vs synthesis phases.
- `CHUNK_REASONING` / `SYNTHESIS_REASONING`: reasoning effort passed to the API.
- `MEMOIR_PATH`: absolute path to the source manuscript.
- `CHUNK_WORDS`, `CHUNK_OVERLAP`: chunk size and overlap applied to mixed
  CJK/Latin tokens.
- `CHUNK_MAX_OUTPUT_TOKENS` (2000) & `SYNTHESIS_MAX_OUTPUT_TOKENS` (16000):
  output limits sized for the prompts.
- `SUMMARIES_DIR`, `OUTPUT_SUMMARIES_PATH`, `OUTPUT_FINAL_PATH`: persistence.
- `MODEL_LIMITS`: per-model TPM ceilings enforced by `TokenRateLimiter`.

Tune these constants at the top of the script before running.

## Key Components

### Mixed-language chunking

- `tokenize_mixed(text)` splits the manuscript into “units” (words or single
  CJK characters) so Chinese/Japanese/Korean aren’t miscounted.
- `rebuild_text(tokens)` reintroduces spacing rules to reconstruct readable
  chunk text after token slicing.
- `chunk_text_by_words(text, max_words, overlap)` builds `MemoirChunk` objects
  with 1-based unit ranges and overlap for continuity.

### resumable persistence

- `summaries/` stores markdown summaries while `summaries/index.json` tracks
  status per chunk.
- `compute_index_meta(full_text)` fingerprints the memoir’s absolute path,
  SHA-256, chunk settings, and model names.
- `load_or_init_index(chunks, full_text)` refuses to reuse cached summaries if
  the text or config changed, forcing a clean rerun.

### Rate limiting & retries

- `estimate_tokens` + `estimate_total_tokens_for_call` approximate token usage
  using `tiktoken` when present.
- `TokenRateLimiter` enforces TPM ceilings per model.
- `call_model(...)` wraps the OpenAI Responses API, respecting TPM budgets,
  classifying transient vs hard errors, backing off with exponential retries,
  and extracting text even for reasoning-first responses.

### Analysis stages

- `analyze_chunk(chunk)` formats `CHUNK_USER_TEMPLATE`, calls the summary model,
  and writes `# Chunk N (units x-y)` headers.
- `synthesize_report(chunk_summaries_md)` feeds the concatenated summaries into
  the 12-section synthesis prompt and saves `memoir_analysis.md`.

### Main orchestration

`main()` wires the entire pipeline:

1. Load text, chunk it, and announce total units.
2. Load or initialize the index (with metadata guardrails).
3. Iterate over chunks with a CLI progress bar.
   - Skips already-finished chunks, showing their recorded `duration_sec`.
   - Analyzes remaining chunks, writes summaries, logs duration, and marks the
     index entry as done.
4. Concatenate all chunk summaries into `memoir_chunk_summaries.md`.
5. Run the global synthesis and save `memoir_analysis.md`.

## Resuming & Maintenance

- To resume after an interruption, rerun `python memoir2.py`. Completed chunks
  (with matching metadata) are skipped automatically.
- If you change the memoir file, chunk settings, or model names, delete
  `summaries/index.json` and the generated chunk files before rerunning.
- Monitor the console to ensure chunk durations and synthesis progress look
  reasonable; the script reports per-chunk runtime and overall progress.

This README captures the current “memoir2” feature set; adapt instructions if
you move the pipeline into another file name such as `memoir.py`.
