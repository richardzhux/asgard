import os
import sys
import time
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

from dotenv import load_dotenv
from openai import OpenAI
import openai  # for exception classes (RateLimitError, APIError, etc.)

# Optional: token counting
try:
    import tiktoken
except ImportError:
    tiktoken = None

load_dotenv()
if not os.getenv("OPENAI_API_KEY"):
    raise RuntimeError("OPENAI_API_KEY is not set in the environment.")
client = OpenAI()  # reads OPENAI_API_KEY from env


# ---------- Config ----------

MODEL_SUMMARY = "gpt-5.1"   # chunk analyst
MODEL_SYNTHESIS = "gpt-5.1"  # “director’s cut” synthesis (set to high reasoning in the call if desired)
# Explicit reasoning depth for each stage
CHUNK_REASONING = "medium"
SYNTHESIS_REASONING = "high"

MEMOIR_PATH = "/Users/rx/Desktop/memoirtest.md"
CHUNK_WORDS = 1500       # target "units" per chunk (English words or CJK chars)
CHUNK_OVERLAP = 150      # small overlap to avoid slicing scenes mid-thought
CHUNK_MAX_OUTPUT_TOKENS = 2000
OUTPUT_SUMMARIES_PATH = "memoir_chunk_summaries.md"
OUTPUT_FINAL_PATH = "memoir_analysis.md"
SYNTHESIS_MAX_OUTPUT_TOKENS = 30000  # sized for a 5k+ word dossier

SUMMARIES_DIR = Path("summaries")
INDEX_PATH = SUMMARIES_DIR / "index.json"
CHUNK_FILENAME_TEMPLATE = "chunk_{:04d}.md"

# Approximate per-model token-per-minute limits (YOU should set these from your dashboard!)
# If you leave tpm=None or 0, rate limiting is disabled for that model.
MODEL_LIMITS = {
    MODEL_SUMMARY:   {"tpm": 30000},  # example – adjust to your real quota
    MODEL_SYNTHESIS: {"tpm": 30000},  # example – adjust to your real quota
}


@dataclass
class MemoirChunk:
    text: str
    start_word: int  # really "unit index"
    end_word: int    # same
    idx: int


# ---------- Mixed-language tokenization (CJK-safe) ----------

# Basic CJK char detector: Han, Hiragana, Katakana, Hangul
CJK_CHAR_RE = re.compile(
    r"[\u4E00-\u9FFF"      # CJK Unified
    r"\u3400-\u4DBF"       # CJK Extension A
    r"\uF900-\uFAFF"       # CJK Compatibility Ideographs
    r"\u3040-\u309F"       # Hiragana
    r"\u30A0-\u30FF"       # Katakana
    r"\uAC00-\uD7AF]"      # Hangul syllables
)


def is_cjk_token(tok: str) -> bool:
    """Treat a token as CJK if it is a single CJK character."""
    return len(tok) == 1 and bool(CJK_CHAR_RE.match(tok))


def tokenize_mixed(text: str) -> List[str]:
    """
    Tokenize text into "units":
    - Western languages: whitespace-delimited chunks.
    - CJK: each CJK character is a separate unit.
    This avoids the "one giant word" problem for Chinese/Japanese/Korean.
    """
    tokens: List[str] = []
    buff: List[str] = []

    def flush_buff():
        nonlocal buff
        if buff:
            tokens.append("".join(buff))
            buff = []

    for ch in text:
        if ch.isspace():
            flush_buff()
            # keep spaces out of tokens; we'll reconstruct spacing later
        elif CJK_CHAR_RE.match(ch):
            flush_buff()
            tokens.append(ch)
        else:
            buff.append(ch)

    flush_buff()
    return tokens


def rebuild_text(tokens: List[str]) -> str:
    """
    Rebuild text from mixed tokens:
    - No spaces between consecutive CJK tokens.
    - Space between non-CJK tokens or CJK <-> non-CJK boundaries.
    This preserves CJK readability while keeping English words separated.
    """
    if not tokens:
        return ""

    out_parts: List[str] = []
    prev_is_cjk = is_cjk_token(tokens[0])
    out_parts.append(tokens[0])

    for tok in tokens[1:]:
        cur_is_cjk = is_cjk_token(tok)
        # Add space only if both sides are non-CJK
        if not (prev_is_cjk and cur_is_cjk):
            out_parts.append(" ")
        out_parts.append(tok)
        prev_is_cjk = cur_is_cjk

    return "".join(out_parts)


# ---------- Chunking ----------

def load_text(path: str) -> str:
    with open(path, "r", encoding="utf-8") as f:
        return f.read()


def chunk_text_by_words(text: str, max_words: int, overlap: int) -> List[MemoirChunk]:
    """
    Chunk by mixed-language "units" with slight overlap to preserve continuity.
    Units = English words (whitespace-delimited) OR individual CJK characters.
    Returns MemoirChunk objects with unit index ranges.
    """
    units = tokenize_mixed(text)
    chunks: List[MemoirChunk] = []

    step = max(max_words - overlap, 1)
    start = 0
    idx = 0
    total_units = len(units)

    while start < total_units:
        end = min(start + max_words, total_units)
        chunk_units = units[start:end]
        chunk_text = rebuild_text(chunk_units)
        chunks.append(
            MemoirChunk(
                text=chunk_text,
                start_word=start + 1,  # 1-based index for readability
                end_word=end,
                idx=idx,
            )
        )
        start += step
        idx += 1

    return chunks


# ---------- Persistence helpers ----------

def ensure_summaries_dir() -> None:
    SUMMARIES_DIR.mkdir(exist_ok=True)


def chunk_summary_path(idx: int) -> Path:
    return SUMMARIES_DIR / CHUNK_FILENAME_TEMPLATE.format(idx + 1)  # human-friendly 1-based naming


def load_or_init_index(chunks: List[MemoirChunk]) -> dict:
    ensure_summaries_dir()
    if INDEX_PATH.exists():
        with open(INDEX_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Basic sanity check: lengths should match
        if len(data.get("chunks", [])) != len(chunks):
            raise RuntimeError(
                "Index length does not match current chunking. "
                "Delete summaries/index.json to re-run fresh."
            )
        return data

    data = {
        "chunks": [
            {
                "idx": chunk.idx,
                "start_word": chunk.start_word,
                "end_word": chunk.end_word,
                "status": "pending",
                "path": str(chunk_summary_path(chunk.idx)),
            }
            for chunk in chunks
        ]
    }
    save_index(data)
    return data


def save_index(data: dict) -> None:
    with open(INDEX_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)


def count_done(data: dict) -> int:
    return sum(1 for c in data.get("chunks", []) if c.get("status") == "done")


# ---------- Token estimation & rate limiting ----------

_token_enc_cache = {}
_rate_limiters = {}


def estimate_tokens(text: str, model: str) -> int:
    """
    Approximate token count using tiktoken if available, otherwise fallback
    to a simple char-based heuristic (len(text) / 4).
    """
    if not text:
        return 0

    if tiktoken is None:
        # crude approximation; good enough for throttling
        return max(1, len(text) // 4)

    enc = _token_enc_cache.get(model)
    if enc is None:
        try:
            enc = tiktoken.encoding_for_model(model)
        except KeyError:
            # fallback encoding
            enc = tiktoken.get_encoding("cl100k_base")
        _token_enc_cache[model] = enc

    return len(enc.encode(text))


def estimate_total_tokens_for_call(
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int],
    model: str,
) -> int:
    input_tokens = estimate_tokens(system_prompt, model) + estimate_tokens(user_prompt, model)
    return input_tokens + (max_output_tokens or 0)


class TokenRateLimiter:
    """
    Very simple per-model token-per-minute limiter (token bucket approximation).
    Not exact, but good enough to avoid hammering your TPM quota.
    """

    def __init__(self, tpm: int):
        self.tpm = tpm
        self.allowance = tpm
        self.last_check = time.time()

    def wait_for(self, tokens: int) -> None:
        if self.tpm is None or self.tpm <= 0:
            return

        now = time.time()
        elapsed = now - self.last_check
        self.last_check = now

        # refill allowance
        self.allowance += elapsed * (self.tpm / 60.0)
        if self.allowance > self.tpm:
            self.allowance = self.tpm

        if tokens <= self.allowance:
            self.allowance -= tokens
            return

        deficit = tokens - self.allowance
        wait_seconds = deficit / (self.tpm / 60.0)
        msg = f"[rate-limit] Sleeping {wait_seconds:.1f}s to respect ~{self.tpm} tpm"
        print(msg, file=sys.stderr)
        time.sleep(wait_seconds)
        self.allowance = 0.0


def get_rate_limiter(model: str) -> Optional[TokenRateLimiter]:
    cfg = MODEL_LIMITS.get(model)
    if not cfg:
        return None
    tpm = cfg.get("tpm")
    if not tpm:
        return None
    limiter = _rate_limiters.get(model)
    if not limiter:
        limiter = TokenRateLimiter(tpm)
        _rate_limiters[model] = limiter
    return limiter


# ---------- OpenAI helpers ----------

def call_model(
    model: str,
    system_prompt: str,
    user_prompt: str,
    max_output_tokens: Optional[int] = None,
    reasoning: Optional[str] = None,
    text_verbosity: Optional[str] = None,
    call_context: str = "call_model",
    max_retries: int = 5,
) -> str:
    """
    Wrapper around the Responses API with:
    - token estimation
    - simple token-per-minute rate limiting
    - robust retry on transient errors
    Returns plain text content.
    """
    reasoning_arg = {"effort": reasoning} if reasoning else None

    total_est_tokens = estimate_total_tokens_for_call(
        system_prompt,
        user_prompt,
        max_output_tokens,
        model,
    )
    limiter = get_rate_limiter(model)
    if limiter:
        limiter.wait_for(total_est_tokens)

    request_args = {
        "model": model,
        "max_output_tokens": max_output_tokens,
        "reasoning": reasoning_arg,
        "input": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ],
    }
    if text_verbosity:
        request_args["text"] = {"verbosity": text_verbosity}

    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = client.responses.create(**request_args)

            # Prefer SDK convenience property (handles reasoning-first outputs)
            text = getattr(resp, "output_text", None)
            if text:
                return str(text)

            # Fallback: search all outputs for the first text block
            if not getattr(resp, "output", None):
                raise RuntimeError(f"{call_context}: model returned no output items")

            for item in resp.output:
                content = getattr(item, "content", None) or []
                for block in content:
                    maybe_text = getattr(block, "text", None)
                    if maybe_text:
                        return str(maybe_text)

            raise RuntimeError(f"{call_context}: no text content found in response")

        except (openai.RateLimitError, openai.APIError, openai.APIConnectionError, TimeoutError) as e:
            last_exc = e
            # Backoff: exponential, capped
            backoff = min(2 ** attempt, 60)
            print(
                f"{call_context}: transient API error ({e!r}), retrying in {backoff:.1f}s "
                f"[attempt {attempt + 1}/{max_retries}]",
                file=sys.stderr,
            )
            time.sleep(backoff)
            continue
        except Exception as e:
            # For non-transient errors, we still try a couple of times just in case,
            # but if it keeps failing, bubble it up.
            last_exc = e
            backoff = min(2 ** attempt, 60)
            print(
                f"{call_context}: unexpected error ({e!r}), retrying in {backoff:.1f}s "
                f"[attempt {attempt + 1}/{max_retries}]",
                file=sys.stderr,
            )
            time.sleep(backoff)
            continue

    raise RuntimeError(f"{call_context}: giving up after {max_retries} retries; last error was: {last_exc!r}")


# ---------- Per-chunk analysis ----------

CHUNK_SYSTEM_PROMPT = """
You are a meticulous field-notes analyst in narrative psychology, attachment theory, and life-course development.
You extract specific, time-aware patterns from autobiographical text without platitudes or pathologizing.
Use concrete incidents, voiced language, and observed behaviors; avoid generic traits.
"""

CHUNK_USER_TEMPLATE = """
You will be given a chunk of a long autobiographical memoir for ONE person.
For THIS chunk only, produce structured notes (concise but specific) using this schema:

- timeframe: explicit years/ages/locations or contextual time clues.
- key_events: 4–8 bullets of concrete incidents (who/where/what).
- emotions_conflicts: dominant affects + inner dilemmas; show situations (not traits).
- coping_strategies: 2–4 coping moves under stress (withdraw, argue/prove, overwork/research, self-soothe, etc.) with situations.
- social_patterns: peers/family/authority dynamics; loyalty, conflict, trust, support.
- romantic_attachment: pursuits/avoidance, jealousy/trust themes, rupture/repair behaviors.
- work_identity: study/work themes, ambition vs fatigue, competence/insecurity signals.
- behavioral_style: repeated habits, avoidance/approach defaults, self-talk tone.
- tensions: 2–5 push-pulls (e.g., wants intimacy vs fears loss of control) grounded in incidents.
- inflection_points: moments that shift trajectory/beliefs in this chunk.
- narrator_stance: how the story is told here (defensive, self-blaming, ironic, detached, raw, analytical).
- notable_quotes: 2–4 short lines/phrases (paraphrase ok) capturing voice.
- chunk_title: a short, vivid title.
- open_questions: uncertainties or threads to revisit later.

Rules:
- Identify specific situations rather than generic traits (“when X happens, they do Y, feel Z”).
- Avoid vague labels unless anchored to examples (no “is anxious” without where/how it shows).
- Always include coping_strategies and tensions entries.
- Keep it specific to THIS chunk; do not generalize beyond it. Max ~550–650 tokens. Markdown headings are fine.

---- CHUNK START ----
{chunk}
---- CHUNK END ----
"""


def analyze_chunk(chunk: MemoirChunk) -> str:
    idx = chunk.idx
    chunk_header = f"(chunk {idx+1}, words {chunk.start_word}-{chunk.end_word})\n\n{chunk.text}"
    user_prompt = CHUNK_USER_TEMPLATE.format(chunk=chunk_header)
    print(f"Analyzing chunk {idx+1} (words {chunk.start_word}-{chunk.end_word})...")
    text = call_model(
        MODEL_SUMMARY,
        CHUNK_SYSTEM_PROMPT,
        user_prompt,
        max_output_tokens=CHUNK_MAX_OUTPUT_TOKENS,
        reasoning=CHUNK_REASONING,
        call_context=f"chunk {idx+1}",
    )
    header = f"# Chunk {idx+1} (words {chunk.start_word}-{chunk.end_word})\n\n"
    return header + text.strip() + "\n\n"


# ---------- Global synthesis ----------

SYNTHESIS_SYSTEM_PROMPT = """
You are crafting a long-form (5k+ words) psychological and life-pattern dossier for one person.
You integrate chunk summaries into a coherent, evidence-backed narrative. Avoid platitudes.
Anchor claims in incidents and voiced language. Be respectful, concrete, and timeline-aware.
"""

SYNTHESIS_USER_TEMPLATE = """
You will receive chunk-by-chunk psychological summaries for ONE person (same person across all chunks).

Using ONLY this information, write a deep integrative report (>=5,000 words; elaborate when needed) with sections:
1) Chronological backbone by era: eras, settings, role transitions; emotional tone per era; major turning points; cite chunk IDs (e.g., 03, 08, 14) inline.
2) Personality architecture: core traits, defenses/coping strategies, self-talk patterns; how they evolve; ground claims in chunk IDs.
3) Attachment / romantic scripts: pursuit/avoidance cycles, jealousy/trust themes, rupture-repair behaviors; how early episodes shape later ones; ground in chunks.
4) Friendship / social dynamics: loyalty, conflict resolution, status negotiation; mentor/authority relations; how care/support is sought and offered.
5) Work / study / identity arc: ambition vs burnout, risk/experimentation, competence/insecurity signals, pivots.
6) Conflict and coping: anger/shame/anxiety/sadness handling; withdrawal vs confrontation; somatic or behavioral tells if present; highlight coping strategies across eras.
7) Recurring loops (3–5): for each, map Trigger → interpretation → emotional reaction → coping behavior → short-term relief → long-term cost; show how each loop evolves between earlier and later chunks.
8) Tensions and contradictions: call out internal push-pulls (e.g., seeks closity but withdraws when criticized; wants autonomy but longs for authority); note which persist, flip, or resolve.
9) Turning points and belief updates: concrete events that reroute direction; what beliefs or behaviors change afterward.
10) Current stance: how accumulated patterns shape present romantic pursuits, career choices, and day-to-day posture.
11) Recommendations / experiments: 5–10 precise interventions tied to the loops/tensions identified. For each, include 1–2 behavioral experiments and 1–2 reflection prompts in the format “When X happens, instead of your usual Y, try Z.”
12) Mirror paragraph: one honest, compassionate paragraph addressed directly to the person.

Guidance:
- Organize early sections chronologically by major eras (e.g., childhood, early college, post-transfer); separate “what happened” from “how they adapted.”
- Prefer because/therefore causal chains over lists; use concrete examples.
- Keep ties to chunk IDs or eras in-line for grounding (no formal citations needed).
- Preserve distinctive language/phrases to retain voice.
- Avoid brevity; aim for at least 5,000 words with subsections and paragraphs; do not compress.

---- CHUNK SUMMARIES START ----
{summaries}
---- CHUNK SUMMARIES END ----
"""


def synthesize_report(chunk_summaries_md: str) -> str:
    user_prompt = SYNTHESIS_USER_TEMPLATE.format(summaries=chunk_summaries_md)
    print("Running global synthesis...")
    return call_model(
        MODEL_SYNTHESIS,
        SYNTHESIS_SYSTEM_PROMPT,
        user_prompt,
        max_output_tokens=SYNTHESIS_MAX_OUTPUT_TOKENS,
        reasoning=SYNTHESIS_REASONING,
        text_verbosity="high",
        call_context="synthesis",
    )


# ---------- Main ----------

def main():
    # Two-step analysis pipeline: (1) chunk summaries, (2) global synthesis.
    pipeline_start = time.time()
    # 1) Load and chunk
    full_text = load_text(MEMOIR_PATH)
    chunks = chunk_text_by_words(full_text, CHUNK_WORDS, CHUNK_OVERLAP)
    total_units = len(tokenize_mixed(full_text))
    total_chunks = len(chunks)
    print(f"Loaded memoir with {total_units} units into {total_chunks} chunks (overlap {CHUNK_OVERLAP}).")

    index_data = load_or_init_index(chunks)
    done_so_far = count_done(index_data)

    def render_progress(done: int, total: int) -> None:
        percent = int((done / total) * 100) if total else 100
        bar_len = 30
        filled = int(bar_len * percent / 100)
        bar = "=" * filled + "." * (bar_len - filled)
        elapsed = time.time() - pipeline_start
        sys.stdout.write(f"\rProgress [{bar}] {percent:3d}% ({done}/{total}) | {elapsed:.1f}s")
        sys.stdout.flush()

    # 2) Analyze each chunk with resumability
    render_progress(done_so_far, total_chunks)
    for chunk in chunks:
        entry = index_data["chunks"][chunk.idx]
        summary_path = Path(entry["path"])
        if entry["status"] == "done" and summary_path.exists():
            print(f"Chunk {chunk.idx+1}/{total_chunks} already done; skipping.")
            continue

        start_time = time.time()
        print(f"Analyzing chunk {chunk.idx+1}/{total_chunks} (words {chunk.start_word}-{chunk.end_word})...")
        summary_md = analyze_chunk(chunk)
        summary_path.parent.mkdir(parents=True, exist_ok=True)
        summary_path.write_text(summary_md, encoding="utf-8")

        entry["status"] = "done"
        save_index(index_data)

        done_so_far += 1
        duration = time.time() - start_time
        print(f"Finished chunk {chunk.idx+1}/{total_chunks} | {duration:.1f}s")
        render_progress(done_so_far, total_chunks)
    print()  # newline after progress bar

    # verify completion
    if count_done(index_data) != total_chunks:
        raise RuntimeError("Not all chunks are complete; cannot run synthesis.")

    # 3) Assemble summaries bundle
    all_summaries_md = []
    for entry in sorted(index_data["chunks"], key=lambda c: c["idx"]):
        path = Path(entry["path"])
        if not path.exists():
            raise RuntimeError(f"Missing summary file: {path}")
        all_summaries_md.append(path.read_text(encoding="utf-8"))

    bundle = "\n".join(all_summaries_md)
    with open(OUTPUT_SUMMARIES_PATH, "w", encoding="utf-8") as f:
        f.write(bundle)
    print(f"Wrote concatenated chunk summaries to {OUTPUT_SUMMARIES_PATH}")

    # 4) Global synthesis
    final_report_md = synthesize_report(bundle)

    with open(OUTPUT_FINAL_PATH, "w", encoding="utf-8") as f:
        f.write(final_report_md)
    print(f"Wrote final analysis report to {OUTPUT_FINAL_PATH}")


if __name__ == "__main__":
    main()
