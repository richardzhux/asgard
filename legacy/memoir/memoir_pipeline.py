from __future__ import annotations

import hashlib
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional

# Ensure project root is on sys.path when running as a script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.chunking import chunk_text, tokenize_mixed
from core.models import TextChunk
from core.openai_client import call_model, configure_model_limits
from core.utils import ensure_dir, read_json, write_json


@dataclass
class MemoirSettings:
    memoir_path: Path
    summary_model: str = "gpt-5.1"
    synthesis_model: str = "gpt-5.1"
    chunk_reasoning: str = "medium"
    synthesis_reasoning: str = "high"
    chunk_words: int = 1500
    chunk_overlap: int = 150
    chunk_max_output_tokens: int = 2000
    synthesis_max_output_tokens: int = 16000
    summary_output_path: Path = Path("memoir_chunk_summaries.md")
    final_output_path: Path = Path("memoir_analysis.md")
    summaries_dir: Path = Path("summaries")
    chunk_filename_template: str = "chunk_{:04d}.md"
    model_limits: Optional[dict] = None


class MemoirPipeline:
    def __init__(self, settings: MemoirSettings) -> None:
        self.settings = settings
        ensure_dir(self.settings.summaries_dir)
        if self.settings.model_limits:
            configure_model_limits(self.settings.model_limits)

    # --------- Chunking ---------
    def load_text(self) -> str:
        with open(self.settings.memoir_path, "r", encoding="utf-8") as f:
            return f.read()

    def chunk_text(self, text: str) -> List[TextChunk]:
        return chunk_text(text, self.settings.chunk_words, self.settings.chunk_overlap)

    # --------- Index persistence ---------
    @property
    def index_path(self) -> Path:
        return self.settings.summaries_dir / "index.json"

    def _chunk_path(self, idx: int) -> Path:
        return self.settings.summaries_dir / self.settings.chunk_filename_template.format(idx + 1)

    def _compute_meta(self, full_text: str) -> dict:
        return {
            "memoir_path": str(self.settings.memoir_path.resolve()),
            "memoir_sha256": hashlib.sha256(full_text.encode("utf-8")).hexdigest(),
            "chunk_words": self.settings.chunk_words,
            "chunk_overlap": self.settings.chunk_overlap,
            "summary_model": self.settings.summary_model,
            "synthesis_model": self.settings.synthesis_model,
        }

    def load_or_init_index(self, chunks: List[TextChunk], full_text: str) -> dict:
        meta = self._compute_meta(full_text)
        if self.index_path.exists():
            data = read_json(self.index_path)
            if len(data.get("chunks", [])) != len(chunks):
                raise RuntimeError("Index length mismatch; delete summaries/index.json to restart.")
            if data.get("meta") != meta:
                raise RuntimeError(
                    "Index metadata mismatch (memoir, chunking, or model config changed)."
                )
            return data
        entries = []
        for chunk in chunks:
            entries.append(
                {
                    "idx": chunk.idx,
                    "start_unit": chunk.start_unit,
                    "end_unit": chunk.end_unit,
                    "status": "pending",
                    "path": str(self._chunk_path(chunk.idx)),
                    "duration_sec": None,
                }
            )
        data = {"meta": meta, "chunks": entries}
        write_json(self.index_path, data)
        return data

    def save_index(self, data: dict) -> None:
        write_json(self.index_path, data)

    def count_done(self, data: dict) -> int:
        return sum(1 for entry in data.get("chunks", []) if entry.get("status") == "done")

    # --------- Chunk analysis ---------
    CHUNK_SYSTEM_PROMPT = (
        "You are a meticulous field-notes analyst in narrative psychology, attachment theory,"
        " and life-course development. Extract specific, time-aware patterns without platitudes."
    )

    CHUNK_USER_TEMPLATE = """
You will be given a chunk of a long autobiographical memoir for ONE person.
For THIS chunk only, produce structured notes (concise but specific) using this schema:

- timeframe
- key_events
- emotions_conflicts
- coping_strategies
- social_patterns
- romantic_attachment
- work_identity
- behavioral_style
- tensions
- inflection_points
- narrator_stance
- notable_quotes
- chunk_title
- open_questions

---- CHUNK START ----
{chunk_header}
---- CHUNK END ----
"""

    def _chunk_user_prompt(self, chunk: TextChunk, total_chunks: int) -> str:
        header = f"(chunk {chunk.idx+1}, units {chunk.start_unit}-{chunk.end_unit})\n\n{chunk.text}"
        return self.CHUNK_USER_TEMPLATE.format(chunk_header=header)

    def analyze_chunk(self, chunk: TextChunk, total_chunks: int) -> str:
        user_prompt = self._chunk_user_prompt(chunk, total_chunks)
        text = call_model(
            model=self.settings.summary_model,
            system_prompt=self.CHUNK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=self.settings.chunk_max_output_tokens,
            reasoning=self.settings.chunk_reasoning,
            call_context=f"memoir-chunk-{chunk.idx+1}",
        )
        header = f"# Chunk {chunk.idx+1} (units {chunk.start_unit}-{chunk.end_unit})\n\n"
        return header + text.strip() + "\n"

    # --------- Synthesis ---------
    SYNTHESIS_SYSTEM_PROMPT = (
        "You are crafting a long-form (5k+ words) psychological and life-pattern dossier."
        " Integrate chunk summaries into a coherent, timeline-aware narrative."
    )

    SYNTHESIS_USER_TEMPLATE = """
You will receive chunk-by-chunk psychological summaries for ONE person (same individual across all chunks).

Using ONLY this material, write a deep integrative dossier (>=5,000 words; expand where helpful) with sections:
1) Chronological backbone by era: eras, settings, role transitions; emotional tone per era; major turning points; cite chunk numbers inline (e.g., [Chunk 03]).
2) Personality architecture: core traits, defenses/coping strategies, self-talk patterns; how they evolve; ground claims in chunk references.
3) Attachment / romantic scripts: pursuit/avoidance cycles, jealousy/trust themes, rupture-repair behaviors; how early episodes shape later ones; ground in chunks.
4) Friendship / social dynamics: loyalty, conflict resolution, status negotiation; mentor/authority relations; how care/support is sought and offered.
5) Work / study / identity arc: ambition vs burnout, risk/experimentation, competence/insecurity signals, pivots.
6) Conflict and coping: anger/shame/anxiety/sadness handling; withdrawal vs confrontation; somatic or behavioral tells if present; highlight coping strategies across eras.
7) Recurring loops (3-5): for each, map Trigger -> interpretation -> emotional reaction -> coping behavior -> short-term relief -> long-term cost; show how loops evolve between earlier and later chunks.
8) Tensions and contradictions: internal push-pulls (e.g., seeks intimacy but withdraws when criticized); note which persist, flip, or resolve.
9) Turning points and belief updates: concrete events that reroute direction; what beliefs or behaviors change afterward.
10) Current stance: how accumulated patterns shape present romantic pursuits, career choices, and day-to-day posture.
11) Recommendations / experiments: 5-10 precise interventions tied to loops/tensions. For each, include 1-2 behavioral experiments and 1-2 reflection prompts in the format "When X happens, instead of your usual Y, try Z."
12) Mirror paragraph: one honest, compassionate paragraph addressed directly to the person.

Guidance:
- Organize early sections chronologically by eras (childhood, moves, schooling, jobs); separate events from adaptations.
- Prefer because/therefore causal chains over bullet dumps; keep chunk references inline for grounding.
- Preserve distinctive language/phrases to retain voice; avoid platitudes, diagnoses, or speculation outside the summaries.
- Stay grounded in evidence from the provided chunks; do not invent new facts.
- Avoid brevity; use subsections and paragraphs rather than compressed bullets.

---- CHUNK SUMMARIES START ----
{chunk_summaries}
---- CHUNK SUMMARIES END ----
"""

    def _synthesis_user_prompt(self, chunk_bundle: str) -> str:
        return self.SYNTHESIS_USER_TEMPLATE.format(chunk_summaries=chunk_bundle)

    def synthesize(self, chunk_bundle: str) -> str:
        return call_model(
            model=self.settings.synthesis_model,
            system_prompt=self.SYNTHESIS_SYSTEM_PROMPT,
            user_prompt=self._synthesis_user_prompt(chunk_bundle),
            max_output_tokens=self.settings.synthesis_max_output_tokens,
            reasoning=self.settings.synthesis_reasoning,
            text_verbosity="high",
            call_context="memoir-synthesis",
        )

    # --------- Run pipeline ---------
    def run(self) -> None:
        pipeline_start = time.time()
        full_text = self.load_text()
        chunks = self.chunk_text(full_text)
        total_chunks = len(chunks)
        total_units = chunks[-1].end_unit if chunks else 0
        print(
            f"Loaded memoir with {total_units} units into {total_chunks} chunks (overlap {self.settings.chunk_overlap})."
        )
        index = self.load_or_init_index(chunks, full_text)
        done = self.count_done(index)

        def render_progress(done_chunks: int) -> None:
            percent = int((done_chunks / total_chunks) * 100) if total_chunks else 100
            bar_len = 30
            filled = int(bar_len * percent / 100)
            bar = "=" * filled + "." * (bar_len - filled)
            elapsed = time.time() - pipeline_start
            sys.stdout.write(f"\rProgress [{bar}] {percent:3d}% ({done_chunks}/{total_chunks}) | {elapsed:.1f}s")
            sys.stdout.flush()

        render_progress(done)
        for chunk in chunks:
            entry = index["chunks"][chunk.idx]
            chunk_path = Path(entry["path"])
            if entry["status"] == "done" and chunk_path.exists():
                duration = entry.get("duration_sec")
                note = f" (took {duration:.1f}s)" if duration is not None else ""
                print(f"\nChunk {chunk.idx+1}/{total_chunks} already done{note}; skipping.")
                render_progress(done)
                continue

            print(
                f"\nAnalyzing chunk {chunk.idx+1}/{total_chunks} (units {chunk.start_unit}-{chunk.end_unit})..."
            )
            start_time = time.time()
            summary_text = self.analyze_chunk(chunk, total_chunks)
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            chunk_path.write_text(summary_text, encoding="utf-8")
            duration = time.time() - start_time
            entry["status"] = "done"
            entry["duration_sec"] = duration
            self.save_index(index)
            done += 1
            print(f"Finished chunk {chunk.idx+1}/{total_chunks} | {duration:.1f}s (logged)")
            render_progress(done)
        print()

        if self.count_done(index) != total_chunks:
            raise RuntimeError("Not all chunks complete; cannot run synthesis.")

        # Assemble bundle
        summaries = []
        for entry in sorted(index["chunks"], key=lambda c: c["idx"]):
            path = Path(entry["path"])
            if not path.exists():
                raise RuntimeError(f"Missing summary file: {path}")
            summaries.append(path.read_text(encoding="utf-8"))
        bundle = "\n".join(summaries)
        self.settings.summary_output_path.write_text(bundle, encoding="utf-8")
        print(f"Wrote concatenated chunk summaries to {self.settings.summary_output_path}")
        final_report = self.synthesize(bundle)
        self.settings.final_output_path.write_text(final_report, encoding="utf-8")
        print(f"Wrote final analysis report to {self.settings.final_output_path}")
