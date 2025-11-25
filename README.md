# Research Pipelines

Reusable infrastructure for high-context document analysis workflows (memoir synthesis,
legal literature reviews, upcoming exam-pack analyzers, etc.). The repo is structured
so new pipelines plug into a shared foundation instead of duplicating API glue.

## Repository Layout

```
core/
  chunking.py        # mixed-language tokenization + chunk builder
  models.py          # dataclasses: TextChunk, Document, AgentConfig, AgentReport/Testimony, JudgeDecision, ClaimEvaluation
  openai_client.py   # env loading, per-model TPM registry, retries, reasoning/text verbosity support
  rate_limit.py      # token-bucket limiter registry keyed by model
  tokens.py          # token estimation (tiktoken optional)
  utils.py           # filesystem helpers (ensure_dir, slugify, JSON IO)
pipelines/
  memoir_pipeline.py # chunk/summarize/synthesize a single memoir (resumable)
  litrev_pipeline.py # multi-agent “Supreme Court” literature review for PDF folders
memoir2.py           # CLI entry point for MemoirPipeline
litrev_test.py       # CLI entry point for LitReviewPipeline (PDF extraction still stubbed)
```

Every pipeline composes the `core` modules and exposes a `run()` method. Entry scripts simply
instantiate a config, register per-model rate limits, and call `pipeline.run()`; a future webapp
can import the same classes.

## Core Concepts

- **OpenAI client** (`core/openai_client.py`): wraps the Responses API, centralizes environment
  loading, reasoning/text-verbosity arguments, and per-model token-per-minute throttling via
  `configure_model_limits({"model": tpm})`.
- **Mixed-language chunking** (`core/chunking.py`): handles Western words + single CJK chars,
  rebuilds readable text after slicing, and returns `TextChunk` objects with 1-based unit ranges.
- **Dataclasses** (`core/models.py`): common structures for documents, agents, reports, testimonies,
  and judge decisions so pipelines can serialize/hand off data consistently.
- **Utilities** (`core/utils.py`): directory creation, slugging names into filenames, JSON helpers.

Any new workflow should import from these modules to stay aligned on rate limiting, chunking rules,
And data shapes.

## Memoir Pipeline (`memoir2.py`)

`pipelines/memoir_pipeline.py` encapsulates the two-stage memoir analysis:

1. **Chunking** – read a `.md`/`.txt` manuscript, split by mixed-language “units”, and store a resumable
   `summaries/index.json` with chunk metadata + SHA-256 fingerprint of the source + model names.
2. **Chunk summaries** – call the chunk prompt per slice, write each summary to
   `summaries/chunk_XXXX.md`, and log duration for resume reporting.
3. **Global synthesis** – concatenate chunk markdown (saved to `memoir_chunk_summaries.md`) and run
   the long-form dossier prompt, writing `memoir_analysis.md`.

The CLI `memoir2.py` sets defaults (model names/limits, chunk size) and accepts an optional memoir path:

```bash
python memoir2.py /path/to/memoir.md
```

## Literature Review Pipeline (`litrev_test.py`)

`pipelines/litrev_pipeline.py` generalizes the “Supreme Court of models” workflow for a directory of PDFs:

1. **Ingestion** – iterate over a folder of PDFs, pass each file through the configurable `PDFIngestor`, and
   turn the normalized text into a `Document` of `TextChunk`s. The ingestor now supports PyMuPDF/pdfminer,
   optional Tesseract OCR, optional OpenAI Vision OCR, section detection (regex + optional LLM), and page
   capture/description so downstream prompts know about figures/slides.
2. **Chunk notes** – cache field-note summaries under `litrev_outputs/chunk_summaries/<doc>/` so reruns skip
   completed chunks.
3. **Agent memos** – for each document, run multiple `AgentConfig`s (Method, Norm, Synthesis, Skeptic by
   default) to produce 1200+ word memos referencing chunk IDs. Memos are stored in
   `litrev_outputs/agent_reports/`.
4. **Agent testimonies** – compress each memo into a structured JSON record (verdict score, confidence,
   supporting points, concerns, recommended actions, citations). These are fed verbatim to the judge.
5. **Judge decision** – aggregate testimonies via a Chief Justice prompt that outputs majority rationale,
   consensus vs dissent bullet points, unresolved questions, and per-agent vote metadata. Markdown opinions
   land in `litrev_outputs/judge_opinions/`, and structured metadata (including testimonies + decision) is
   stored under `litrev_outputs/metadata/`.
6. **Claim evaluation (structured 7-part JSON)** – a fifth evaluator consumes the testimonies + chief opinion
   and emits a strict schema object (`ClaimEvaluation`) summarizing claim analysis, consensus labeling, evidence,
   counterarguments, conclusion, recommendations, and overall perspective. Saved alongside other metadata.

Default agents are disciplined “justices” with non-overlapping mandates: Method (methods referee with an
accept/minor/major/reject verdict), Norm (rights/policy tradeoffs with a normative verdict), Synthesis
(literature-map editor assigning usage_role + importance), and Skeptic (robustness audit with killer objection).
The Claim Evaluator is separate: it does not alter judge opinions or memos; it produces one structured JSON
per document for downstream consumption.

The current CLI (`litrev_test.py`) wires the config, PDF directory, and model limits, then defers all
extraction/normalization to the ingestor:

```bash
python litrev_test.py /path/to/pdf_dir \
  --allow-pdf-ocr --use-llm-sections --section-model gpt-5.1 \
  --capture-media --describe-media --media-output-dir media/
```

### PDF ingestion layer

`ingestion/pdf_ingestor.py` implements a best-practice extraction + normalization chain:

- **Layered extraction** – attempts PyMuPDF and pdfminer first, then optional Tesseract OCR or OpenAI Vision
  hooks for scanned/image-heavy PDFs. Each document records which extractor succeeded.
- **Normalization** – merges broken line wraps, collapses whitespace, and derives basic metadata such as
  inferred title, year, and source path. Results feed directly into the shared chunker.
- **Section detection** – regex anchors for headings (Abstract, Introduction, Methods, Discussion, etc.)
  with optional LLM refinement (enable via `use_llm_section_detection=True` + `section_detection_model`).
- **Media capture + descriptions** – optional rendering of the first N pages to PNG (`capture_media=True`). If
  `describe_media=True` and a vision model is configured, the ingestor will call the vision model to create
  short textual descriptions so chunk/agent prompts understand those visuals. Both paths and descriptions live
  in `Document.metadata`.

`LitReviewPipeline` wires this ingestor automatically; each `Document` now carries normalized text, inferred
sections, and optional media metadata/descriptions before chunking. Toggle OCR, OpenAI Vision OCR, LLM
sections, or media capture via `LitReviewConfig` (exposed by CLI flags in `litrev_test.py`).

## Extending the System

To add new pipelines (e.g., exam review, curriculum digests):

1. Create a config dataclass describing sources, prompts, model selections, and token budgets.
2. Compose the shared helpers (chunking, `call_model`, dataclasses) in a pipeline class that exposes
   `run()` and, if needed, overridable ingestion hooks (e.g., `extract_pdf_text`).
3. Define role/persona prompts in structured config so they can be edited without touching code.
4. Register per-model token-per-minute limits once via `configure_model_limits` in your entry script.
5. Keep outputs in predictable subdirectories (chunks, agent reports, judge opinions, metadata) so a CLI,
   background worker, or future web frontend can monitor progress and consume results consistently.

Because API access, rate limiting, and prompt scaffolding live in `core/`, adding new models is just a
matter of extending the `MODEL_LIMITS` map and updating config fields. The same infrastructure can scale
up to additional OpenAI models or other providers as needed.

## Requirements

- Python 3.9+
- `OPENAI_API_KEY` available in the environment (e.g., `.env` file)
- Tesseract binary installed if you plan to use OCR (macOS: `brew install tesseract`, Ubuntu: `sudo apt install tesseract-ocr`)

### Workspace initialization

```bash
# 1) Create a virtualenv (optional but recommended)
python3 -m venv .venv
source .venv/bin/activate

# 2) Install Python dependencies
pip install -r requirements.txt

# 3) Configure environment (copy .env.example -> .env and set OPENAI_API_KEY)
```

Then run the desired pipeline via its CLI entry point (see usage snippets in the sections above).

## Full-stack control panel (Vercel + Supabase + Render)

- **Database + storage (Supabase):** `infra/supabase/schema.sql` defines profiles, presets, jobs, job_events, and artifacts with RLS keyed to `user_id`. Enable Google OAuth in Supabase; expose `NEXT_PUBLIC_SUPABASE_URL`/`NEXT_PUBLIC_SUPABASE_ANON_KEY` to the UI and `SUPABASE_SERVICE_ROLE_KEY` to API/worker.
- **Frontend (Vercel):** `frontend/` is a minimal Next.js app (shadcn-lite, Nordic/Japanese palette). Pages: dashboard (`/`), new job (`/jobs/new`), job detail (`/jobs/[id]`), presets (`/presets`). Auth controls use Supabase Google OAuth. API route `/api/jobs` validates configs (zod) and enqueues jobs into Supabase with hard caps for JSON-returning stages.
- **Worker (Render):** `worker/worker.py` polls Supabase for `queued` jobs, marks them `running`, builds a `LitReviewConfig` from `config`, and runs `LitReviewPipeline`. Status/errors stream into `job_events`; job rows updated to `completed`/`failed`.
- **Config schema:** `frontend/lib/configSchema.ts` centralizes defaults, recommended ranges, and hard caps for tokens per stage. Presets (`fast`, `balanced`, `deep`) are defined there and surfaced in the UI.
- **Deploy sketch:** Vercel hosts the Next app (env: `NEXT_PUBLIC_SUPABASE_URL`, `NEXT_PUBLIC_SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY`, optional `DEFAULT_USER_ID`). Render runs a Python service with `SUPABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, and the usual OpenAI/OCR env vars. Supabase handles auth, logging, and storage; no Redis required.

### Local dev quick start

Frontend (`frontend/`):

```bash
cd frontend
npm install
cp .env.local.example .env.local  # create with SUPABASE keys
npm run dev
```

Worker (`worker/`):

```bash
export SUPABASE_URL=... SUPABASE_SERVICE_ROLE_KEY=... OPENAI_API_KEY=...
python worker/worker.py
```

Use Supabase Auth (Google) to sign in via the UI header; job submissions hit `/api/jobs` and land in the `jobs` table for the worker to pick up.
