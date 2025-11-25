from __future__ import annotations

import json
import hashlib
import re
import sys
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Any

# Ensure project root is on sys.path when running as a script
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.chunking import chunk_text
from core.models import (
    AgentConfig,
    AgentReport,
    AgentTestimony,
    ClaimEvaluation,
    Document,
    JudgeDecision,
    TextChunk,
)
from core.openai_client import call_model, configure_model_limits
from core.tokens import estimate_total_tokens
from core.utils import ensure_dir, read_json, slugify, write_json
from ingestion.pdf_ingestor import IngestedDocument, PDFIngestor

DEFAULT_CONTEXT_LIMIT = 400_000
MODEL_CONTEXT_LIMITS: Dict[str, int] = {
    "gpt-5.1": 400_000,
    "gpt-4.1": 1_047_576,
    "gpt-5-mini": 400_000,
}


@dataclass
class LitReviewConfig:
    pdf_dir: Path
    research_focus: str
    chunk_model: str = "gpt-5.1"
    agent_model: str = "gpt-5.1"
    judge_model: str = "gpt-5.1"
    lit_review_model: str = "gpt-5.1"
    chunk_reasoning: str = "medium"
    chunk_max_output_tokens: int = 4000
    chunk_words: int = 2500
    chunk_overlap: int = 200
    agent_report_reasoning: str = "high"
    agent_report_tokens: int = 6000
    agent_testimony_tokens: int = 5000
    judge_reasoning: str = "high"
    judge_tokens: int = 7000
    lit_review_reasoning: str = "high"
    lit_review_text_verbosity: str = "high"
    lit_review_max_output_tokens: int = 20_000
    lit_review_context_budget: Optional[int] = None
    lit_review_context_safety_margin: int = 40_000
    lit_review_outline_first: bool = True
    model_limits: Optional[Dict[str, int]] = None
    output_dir: Path = Path("litrev_outputs")
    claim_eval_model: str = "gpt-5.1"
    claim_eval_reasoning: str = "medium"
    claim_eval_max_output_tokens: int = 3000
    chunk_subdir: str = "chunk_summaries"
    agent_report_subdir: str = "agent_reports"
    judge_opinion_subdir: str = "judge_opinions"
    metadata_subdir: str = "metadata"
    lit_review_output_path: Path = Path("lit_review.md")
    lit_review_outline_path: Path = Path("lit_review_outline.md")
    lit_review_cache_path: Path = Path("lit_review.progress.json")
    agents: List[AgentConfig] = field(default_factory=list)
    allow_pdf_ocr: bool = True
    use_llm_section_detection: bool = False
    section_detection_model: Optional[str] = None
    media_output_dir: Optional[Path] = None
    capture_media: bool = False
    describe_media: bool = False
    media_max_pages: int = 5
    media_zoom: float = 2.0
    allow_openai_vision: bool = False
    vision_model: Optional[str] = None
    vision_max_output_tokens: int = 900

    def __post_init__(self) -> None:
        if not self.agents:
            self.agents = default_agents(self.agent_model)


def default_agents(model_name: str) -> List[AgentConfig]:
    return [
        AgentConfig(
            agent_id="method",
            name="Justice Method (Referee A)",
            brief="Methodological referee auditing evidentiary and doctrinal machinery.",
            focus="Assess identification logic, sampling/case coverage, precedent alignment, and render a methods verdict.",
            style="formal, citation-led, skeptical",
            model=model_name,
            reasoning="high",
            text_verbosity="high",
        ),
        AgentConfig(
            agent_id="norm",
            name="Justice Norm (Referee B – Normative/Policy)",
            brief="Normative theorist and policy analyst mapping rights and governance tradeoffs.",
            focus="Trace equity/rights impacts, stakeholder winners/losers, and policy levers; render a normative verdict.",
            style="rights-forward, public-law, systems-aware",
            model=model_name,
            reasoning="high",
            text_verbosity="high",
        ),
        AgentConfig(
            agent_id="synthesis",
            name="Justice Synthesis (Editor/Survey Architect)",
            brief="Editor-like survey architect situating the work in the literature map.",
            focus="Locate debates/strands, map contributions (incremental vs transformative), and assign usage role/importance.",
            style="taxonomic, connective, literature-review voice",
            model=model_name,
            reasoning="high",
            text_verbosity="high",
        ),
        AgentConfig(
            agent_id="skeptic",
            name="Justice Skeptic (Hostile Reviewer)",
            brief="Adversarial robustness auditor stress-testing assumptions and failure modes.",
            focus="Find hidden premises, alternative explanations, fragilities; produce robustness verdict and killer objection.",
            style="concise, adversarial-but-fair, evidence-demanding",
            model=model_name,
            reasoning="medium",
        ),
    ]


class LitReviewPipeline:
    def __init__(self, config: LitReviewConfig, pdf_ingestor: Optional[PDFIngestor] = None) -> None:
        self.config = config
        self.pipeline_start: Optional[float] = None
        self.output_dir = config.output_dir
        self.chunk_dir = self.output_dir / config.chunk_subdir
        self.agent_dir = self.output_dir / config.agent_report_subdir
        self.judge_dir = self.output_dir / config.judge_opinion_subdir
        self.meta_dir = self.output_dir / config.metadata_subdir
        self.raw_response_dir = self.meta_dir / "raw_responses"
        self.lit_review_output_path = self.output_dir / config.lit_review_output_path
        self.lit_review_outline_path = self.output_dir / config.lit_review_outline_path
        self.lit_review_cache_path = self.output_dir / config.lit_review_cache_path
        self.telemetry: Dict[str, object] = {
            "estimated_tokens": 0,
            "actual_tokens": 0,
            "missing_usage_calls": 0,
            "calls": [],
        }
        for path in [
            self.output_dir,
            self.chunk_dir,
            self.agent_dir,
            self.judge_dir,
            self.meta_dir,
            self.raw_response_dir,
            self.lit_review_output_path.parent,
            self.lit_review_outline_path.parent,
            self.lit_review_cache_path.parent,
        ]:
            ensure_dir(path)
        if config.model_limits:
            configure_model_limits(config.model_limits)
        self.pdf_ingestor = pdf_ingestor or PDFIngestor(
            allow_ocr=config.allow_pdf_ocr,
            use_llm_sections=config.use_llm_section_detection,
            section_model=config.section_detection_model,
            media_output_dir=config.media_output_dir,
            capture_images=config.capture_media,
            describe_media=config.describe_media,
            media_max_pages=config.media_max_pages,
            media_zoom=config.media_zoom,
            allow_openai_vision=config.allow_openai_vision,
            vision_model=config.vision_model,
            vision_max_output_tokens=config.vision_max_output_tokens,
        )

    # ------ Document ingestion ------
    def load_documents(self) -> List[Document]:
        directory = self.config.pdf_dir
        if not directory.exists():
            raise FileNotFoundError(f"Source directory does not exist: {directory}")
        pdf_paths = sorted(p for p in directory.iterdir() if p.suffix.lower() == ".pdf")
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in {directory}")
        docs: List[Document] = []
        slug_counts: Dict[str, int] = {}
        for path in pdf_paths:
            print(f"Loading {path.name} ...")
            ingestion = self.pdf_ingestor.ingest(path)
            text = ingestion.text
            chunks = chunk_text(text, self.config.chunk_words, self.config.chunk_overlap)
            total_units = chunks[-1].end_unit if chunks else 0
            metadata = dict(ingestion.metadata)
            try:
                metadata["source_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
            except Exception:
                metadata["source_sha256"] = ""
            if ingestion.sections:
                metadata["sections"] = [
                    {"title": sec.title, "start": sec.start_index, "end": sec.end_index}
                    for sec in ingestion.sections
                ]
            if ingestion.media_assets:
                metadata["media_assets"] = [str(p) for p in ingestion.media_assets]
            title = metadata.get("title") or path.stem
            slug = slugify(title)
            if slug in slug_counts:
                slug_counts[slug] += 1
                slug = f"{slug}-{slug_counts[slug]}"
            else:
                slug_counts[slug] = 1
            metadata["slug"] = slug
            docs.append(
                Document(path=path, title=title, chunks=chunks, total_units=total_units, metadata=metadata)
            )
        return docs

    # ------ Chunk summarization ------
    CHUNK_SYSTEM_PROMPT = (
        "You are a legal research analyst distilling scholarly text into precise field notes."
        " Capture claims, methods, evidence, caveats, and citations without embellishment."
    )

    CHUNK_USER_TEMPLATE = """
Document: {doc_title}
Chunk {chunk_idx}/{chunk_count} (units {start_unit}-{end_unit})

Text:
----
{chunk_text}
----

Return Markdown with (aim for ~1200 tokens of output; hard cap 4000 tokens):
- timeframe_or_jurisdiction
- key_claims
- methods_or_sources
- evidence_citations
- limitations_questions
- doctrinal_tags
"""

    def _media_context_text(self, doc: Document, max_items: int = 3) -> str:
        descriptions = doc.metadata.get("media_descriptions") or []
        output_lines: List[str] = []
        for item in descriptions[:max_items]:
            if isinstance(item, dict):
                desc = item.get("description") or ""
                path = item.get("path") or ""
                if desc:
                    line = f"- {desc.strip()} (source: {Path(path).name if path else 'page image'})"
                    output_lines.append(line)
        return "\n".join(output_lines)

    def summarize_chunk(self, doc: Document, chunk: TextChunk) -> str:
        user_prompt = self.CHUNK_USER_TEMPLATE.format(
            doc_title=doc.title,
            chunk_idx=chunk.idx + 1,
            chunk_count=len(doc.chunks),
            start_unit=chunk.start_unit,
            end_unit=chunk.end_unit,
            chunk_text=chunk.text,
        )
        media_context = self._media_context_text(doc)
        if media_context:
            user_prompt += "\nMedia context (captured pages):\n" + media_context + "\n"
        header = f"# Chunk {chunk.idx+1:02d} (units {chunk.start_unit}-{chunk.end_unit})\n\n"
        caps = [self.config.chunk_max_output_tokens, self._bump_max_tokens(self.config.chunk_max_output_tokens)]
        text = ""
        usage: Optional[Dict[str, int]] = None
        for attempt_idx, cap in enumerate(caps):
            attempt_label = f"chunk {chunk.idx+1} attempt {attempt_idx+1}"
            estimated_tokens = self._assert_within_context(
                self.config.chunk_model,
                self.CHUNK_SYSTEM_PROMPT,
                user_prompt,
                cap,
                attempt_label,
            )
            self._announce_estimate(
                label=attempt_label,
                model=self.config.chunk_model,
                system=self.CHUNK_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                precomputed=estimated_tokens,
            )
            text, usage = call_model(
                model=self.config.chunk_model,
                system_prompt=self.CHUNK_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_output_tokens=cap,
                reasoning=self.config.chunk_reasoning,
                call_context=f"litrev-chunk-{doc.title}-{chunk.idx+1}-a{attempt_idx+1}",
                return_usage=True,
            )
            counted, estimated, actual = self._log_call(
                label=f"chunk-{chunk.idx+1}-a{attempt_idx+1}",
                model=self.config.chunk_model,
                system=self.CHUNK_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                usage=usage,
                estimated_tokens=estimated_tokens,
            )
            if actual is not None:
                print(f"[tokens] {attempt_label}: actual {actual} tokens (est {estimated})")
            else:
                print(f"[tokens] {attempt_label}: actual unavailable (est {estimated})")
            if self._needs_truncation_retry(usage, cap) and attempt_idx + 1 < len(caps):
                out = usage.get("output_tokens") if usage else None
                print(
                    f"[retry] chunk {chunk.idx+1}: output {out} near cap {cap}; retrying with {caps[attempt_idx+1]}."
                )
                continue
            break
        return header + text.strip() + "\n"

    def generate_chunk_summaries(self, doc: Document) -> List[str]:
        summaries: List[str] = []
        doc_slug = self._doc_slug(doc)
        chunk_dir = self.chunk_dir / doc_slug
        ensure_dir(chunk_dir)
        meta_path = chunk_dir / "_meta.json"
        current_fp = self._chunk_fingerprint(doc)
        invalidate_cache = False
        if meta_path.exists():
            try:
                meta = read_json(meta_path)
                invalidate_cache = meta.get("fingerprint") != current_fp
            except Exception:
                invalidate_cache = True
        else:
            invalidate_cache = True
        if invalidate_cache:
            print(f"[cache] Invalidating chunk summaries for {doc.title} (fingerprint mismatch).")
            for cached in chunk_dir.glob("chunk_*.md"):
                with suppress(Exception):
                    cached.unlink()
        for chunk in doc.chunks:
            output_path = chunk_dir / f"chunk_{chunk.idx+1:04d}.md"
            if output_path.exists() and not invalidate_cache:
                summaries.append(output_path.read_text(encoding="utf-8"))
                continue
            summary = self.summarize_chunk(doc, chunk)
            output_path.write_text(summary, encoding="utf-8")
            summaries.append(summary)
        write_json(
            meta_path,
            {
                "fingerprint": current_fp,
                "total_chunks": len(doc.chunks),
                "chunk_words": self.config.chunk_words,
                "chunk_overlap": self.config.chunk_overlap,
                "chunk_model": self.config.chunk_model,
            },
        )
        return summaries

    # ------ Agent stage ------
    AGENT_REPORT_TEMPLATE = """
We are reviewing a scholarly document for the project focus (write in an academic, citation-friendly tone):
{research_focus}

Document title: {doc_title}
Total chunks provided: {chunk_count}

Chunk summaries:
{chunk_summaries}

Media context (captured pages, if any):
{media_context}

Role-specific mandate and constraints:
{agent_guidance}

Input scope for you:
{agent_scope}

Tasks:
1. Build a detailed memorandum (>=1200 words) scoped to your role. Include sections:
   - Research question & context
   - Methods / legal sources evaluation
   - Findings & contributions
   - Critiques & failure modes
   - Relevance to overarching agenda
   - Follow-up questions / next experiments
2. Surface 3-5 concrete doctrinal reference points to remember (statutes, leading cases, or specific doctrinal labels). Name cases/sections explicitly.
3. Highlight 1-2 short example passages or quote-like paraphrases that capture the author's voice; reference chunk numbers.
4. Reference chunk numbers inline where helpful (e.g., [Chunk 03]) and ground claims with specific cases/statutes where applicable.
5. Explicitly answer your central question and provide the required role-specific verdict fields noted above.
6. Close with a short "Closure" block containing:
   - One-line mini-abstract of the article from your lens.
   - One-line recommendation for how to use this piece in our pack (e.g., core anchor / important strand / useful background / foil).
   - Your role-specific verdict fields (as instructed above).
"""

    AGENT_TESTIMONY_SYSTEM_PROMPT = "You are summarizing your memo for a judicial conference. Output JSON only."

    AGENT_TESTIMONY_TEMPLATE = """
Document: {doc_title}
Agent memo:
----
{memo_text}
----

Return a JSON object with keys:
- agent_id
- agent_name
- summary (<=200 words)
- verdict_score (0-3)
- confidence
- supporting_points (array)
- concerns (array)
- recommended_actions (array)
- citations (array referencing chunk numbers)
- doctrinal_refs (array of concrete case/statute/doctrinal labels to remember)
- example_passages (array of 1-2 short paraphrased phrases capturing the author's voice; include chunk refs)
- usage_role ("main_authority"|"foil"|"background")
- importance_within_cluster (int 1-5; higher = more central to the topic pack)
"""

    CLAIM_EVAL_SYSTEM_PROMPT = (
        "You are the Claim Evaluator. Produce ONLY a JSON object adhering to the required schema. "
        "No markdown, no prose outside JSON."
    )

    CLAIM_EVAL_TEMPLATE = """
Research focus: {research_focus}
Document: {doc_title}

Primary materials (already adjudicated by other agents):
- Agent testimonies (compressed): 
{testimony_context}
- Chief opinion summary: {chief_opinion_context}

Infer the article's primary claim from these materials and evaluate it using the STRICT JSON schema below.

JSON schema (strict; no additional fields):
{schema_text}

Rules:
- Output exactly one JSON object, nothing else.
- Ground references with chunk numbers and named cases/statutes where applicable.
- Keep strings concise and analytical (Nature/peer-review register).
"""

    AGENT_GUIDANCE: Dict[str, str] = {
        "method": """
Central question: "If this were a thesis chapter or Nature/Science article, is the evidentiary and doctrinal machinery strong enough to support the main claims?" End with verdict = {accept / minor revision / major revision / reject} (methods only).
Focus: identification strategy, data/case completeness, precedent alignment, and the weakest evidentiary link. Anchor every critique with chunk refs and named cases/statutes where applicable.
Do NOT opine on ethics or policy desirability except as they bear on validity. Avoid broad agenda-fit riffs.
Closure: include one-line mini-abstract from the methods lens + one-line recommendation on how to use this piece (e.g., evidentiary anchor vs cautionary foil).
""",
        "norm": """
Central question: "If taken seriously in policy or doctrine, who wins, who loses, and are those tradeoffs justifiable under standard rights/justice frameworks?" End with verdict = {normatively compelling / contested / problematic / dangerous}.
Focus: stakeholder impacts, equity/rights analysis (e.g., proportionality, due process, distributive justice), and concrete policy levers. Use chunk refs and explicit doctrinal/policy labels.
Do NOT audit identification strategy or sampling unless a glaring flaw undermines the normative claim; defer to Method on rigor.
Closure: include one-line mini-abstract from the normative lens + one-line recommendation on use (e.g., rights-forward anchor vs cautionary policy foil).
""",
        "synthesis": """
Central question: "Where does this article sit in the map of the field, and what incremental or transformative contribution does it actually make?" End with usage_role = {core anchor / important strand / useful background / foil} + importance 1–5.
Focus: placement in debates/strands, citation chaining, how it advances or repositions existing lines of thought, and what future work logically follows. Ground with chunk refs and named debates/authors/cases.
Do NOT re-litigate methods or ethics; assume Method and Norm already covered those.
Closure: include one-line mini-abstract from the synthesis lens + one-line recommendation on how to slot this into our pack (align with usage_role/importance).
""",
        "skeptic": """
Central question: "If this article’s main claims are wrong, where and how do they fail, and what is the best alternative explanation or framework?" End with robustness = {high / medium / low} + one killer objection.
Focus: hidden premises, alternative explanations, stress scenarios, falsification tests, and what evidence would change your mind. Cite chunks and any relevant counter-precedent.
Do NOT offer your own grand theory or policy program. Stick to failure modes and robustness.
Closure: include one-line mini-abstract from the skeptic lens + one-line recommendation on use (e.g., hostile foil vs fragile secondary source).
""",
    }

    def build_agent_report(self, agent: AgentConfig, doc: Document, chunk_summaries: List[str]) -> AgentReport:
        chunks_blob = "\n\n".join(chunk_summaries)
        media_context = self._media_context_text(doc, max_items=5)
        system_prompt = (
            f"You are {agent.name}, a justice with mandate: {agent.brief}."
            f" Focus: {agent.focus}. Voice: {agent.style}."
        )
        user_prompt = self.AGENT_REPORT_TEMPLATE.format(
            research_focus=self.config.research_focus,
            doc_title=doc.title,
            chunk_count=len(doc.chunks),
            chunk_summaries=chunks_blob,
            media_context=media_context or "(no captured media)",
            agent_guidance=self._agent_guidance(agent),
            agent_scope=self._agent_scope(agent, doc, chunk_summaries),
        )
        estimated_tokens = self._assert_within_context(
            agent.model,
            system_prompt,
            user_prompt,
            self.config.agent_report_tokens,
            f"agent report {agent.agent_id}",
        )
        self._announce_estimate(
            label=f"agent report {agent.agent_id}",
            model=agent.model,
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.config.agent_report_tokens,
            precomputed=estimated_tokens,
        )
        memo_text, usage = call_model(
            model=agent.model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self.config.agent_report_tokens,
            reasoning=agent.reasoning or self.config.agent_report_reasoning,
            text_verbosity=agent.text_verbosity,
            call_context=f"litrev-agent-report-{agent.agent_id}-{doc.title}",
            return_usage=True,
        )
        counted, estimated, actual = self._log_call(
            label=f"agent-report-{agent.agent_id}",
            model=agent.model,
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.config.agent_report_tokens,
            usage=usage,
            estimated_tokens=estimated_tokens,
        )
        if actual is not None:
            print(f"[tokens] agent report {agent.agent_id}: actual {actual} tokens (est {estimated})")
        else:
            print(f"[tokens] agent report {agent.agent_id}: actual unavailable (est {estimated})")
        doc_slug = self._doc_slug(doc)
        out_path = self.agent_dir / f"{doc_slug}__{agent.agent_id}.md"
        out_path.write_text(memo_text, encoding="utf-8")
        return AgentReport(agent=agent, document=doc, memo_text=memo_text)

    def parse_json_response(self, raw_text: str, context: str) -> Dict[str, object]:
        cleaned = str(raw_text).strip()
        decoder = json.JSONDecoder()

        def _strip_code_fence(text: str) -> str:
            if "```" not in text:
                return text
            match = re.search(r"```[a-zA-Z]*\s*(.*?)\s*```", text, re.DOTALL)
            return match.group(1).strip() if match else text

        def _try_load(text: str) -> Optional[Dict[str, object]]:
            with suppress(Exception):
                obj = json.loads(text)
                if isinstance(obj, dict):
                    return obj
            with suppress(Exception):
                obj, _ = decoder.raw_decode(text)
                if isinstance(obj, dict):
                    return obj
            return None

        candidates: List[str] = []
        fenced = _strip_code_fence(cleaned)
        if fenced:
            candidates.append(fenced)
        if cleaned and cleaned != fenced:
            candidates.append(cleaned)
        # Walk through each opening brace to allow trailing/preamble text
        for text in list(candidates):
            idx = text.find("{")
            while idx != -1:
                candidates.append(text[idx:])
                idx = text.find("{", idx + 1)

        for candidate in candidates:
            parsed = _try_load(candidate)
            if parsed is not None:
                return parsed

        dump_path = self._dump_unparsed_response(cleaned, context)
        raise ValueError(f"{context}: could not locate JSON object (saved raw to {dump_path})")

    def _dump_unparsed_response(self, text: str, context: str) -> Path:
        safe_ctx = slugify(context) or "context"
        timestamp = int(time.time())
        filename = f"{safe_ctx}-{timestamp}.txt"
        dump_path = self.raw_response_dir / filename
        with suppress(Exception):
            ensure_dir(dump_path.parent)
            dump_path.write_text(text, encoding="utf-8")
        return dump_path

    def build_agent_testimony(self, report: AgentReport) -> AgentTestimony:
        user_prompt = self.AGENT_TESTIMONY_TEMPLATE.format(
            doc_title=report.document.title,
            memo_text=report.memo_text,
        )
        caps = [self.config.agent_testimony_tokens, self._bump_max_tokens(self.config.agent_testimony_tokens)]
        raw = ""
        usage: Optional[Dict[str, int]] = None
        data: Optional[Dict[str, object]] = None
        parse_error: Optional[Exception] = None
        for attempt_idx, cap in enumerate(caps):
            attempt_label = f"testimony {report.agent.agent_id} attempt {attempt_idx+1}"
            estimated_tokens = self._assert_within_context(
                report.agent.model,
                self.AGENT_TESTIMONY_SYSTEM_PROMPT,
                user_prompt,
                cap,
                attempt_label,
            )
            self._announce_estimate(
                label=attempt_label,
                model=report.agent.model,
                system=self.AGENT_TESTIMONY_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                precomputed=estimated_tokens,
            )
            raw, usage = call_model(
                model=report.agent.model,
                system_prompt=self.AGENT_TESTIMONY_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_output_tokens=cap,
                call_context=f"litrev-agent-testimony-{report.agent.agent_id}-{report.document.title}-a{attempt_idx+1}",
                return_usage=True,
            )
            counted, estimated, actual = self._log_call(
                label=f"agent-testimony-{report.agent.agent_id}-a{attempt_idx+1}",
                model=report.agent.model,
                system=self.AGENT_TESTIMONY_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                usage=usage,
                estimated_tokens=estimated_tokens,
            )
            if actual is not None:
                print(f"[tokens] {attempt_label}: actual {actual} tokens (est {estimated})")
            else:
                print(f"[tokens] {attempt_label}: actual unavailable (est {estimated})")
            try:
                data = self.parse_json_response(raw, f"testimony {report.agent.agent_id}")
            except Exception as exc:
                parse_error = exc
                if attempt_idx + 1 < len(caps):
                    print(
                        f"[retry] testimony {report.agent.agent_id}: parse failed; retrying with cap {caps[attempt_idx+1]}."
                    )
                    continue
                raise
            if self._needs_truncation_retry(usage, cap) and attempt_idx + 1 < len(caps):
                out = usage.get("output_tokens") if usage else None
                print(
                    f"[retry] testimony {report.agent.agent_id}: output {out} near cap {cap}; retrying with {caps[attempt_idx+1]}."
                )
                parse_error = None
                data = None
                continue
            parse_error = None
            break
        if parse_error:
            raise parse_error
        assert data is not None
        self._require_keys(
            data,
            [
                "summary",
                "verdict_score",
                "confidence",
                "supporting_points",
                "concerns",
                "recommended_actions",
                "doctrinal_refs",
                "example_passages",
                "usage_role",
                "importance_within_cluster",
            ],
            f"testimony {report.agent.agent_id}",
        )
        return AgentTestimony(
            agent=report.agent,
            summary=str(data.get("summary", "")).strip(),
            verdict_score=int(data.get("verdict_score", 0)),
            confidence=str(data.get("confidence", "unknown")),
            supporting_points=[str(x) for x in data.get("supporting_points", [])],
            concerns=[str(x) for x in data.get("concerns", [])],
            recommended_actions=[str(x) for x in data.get("recommended_actions", [])],
            citations=[str(x) for x in data.get("citations", [])],
            doctrinal_refs=[str(x) for x in data.get("doctrinal_refs", [])],
            example_passages=[str(x) for x in data.get("example_passages", [])],
            usage_role=str(data.get("usage_role", "background")),
            importance_within_cluster=int(data.get("importance_within_cluster", 3)),
        )

    # ------ Claim evaluation ------
    def _claim_eval_schema_text(self) -> str:
        return json.dumps(
            {
                "type": "object",
                "properties": {
                    "claim_analysis": {"type": "string"},
                    "scholarly_consensus_label": {"type": "string"},
                    "scholarly_consensus_pct": {"type": "number"},
                    "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                    "counterarguments": {"type": "array", "items": {"type": "string"}},
                    "conclusion": {"type": "string"},
                    "recommendations": {"type": "array", "items": {"type": "string"}},
                    "overall_perspective": {"type": "string"},
                },
                "required": [
                    "claim_analysis",
                    "scholarly_consensus_label",
                    "scholarly_consensus_pct",
                    "supporting_evidence",
                    "counterarguments",
                    "conclusion",
                    "recommendations",
                    "overall_perspective",
                ],
                "additionalProperties": False,
            },
            indent=2,
        )

    def _build_claim_evaluation(
        self, doc: Document, testimonies: List[AgentTestimony], decision: JudgeDecision
    ) -> ClaimEvaluation:
        testimony_context = self._format_testimony_context(testimonies)
        chief_context = self._format_decision_context(decision)
        schema_text = self._claim_eval_schema_text()
        user_prompt = self.CLAIM_EVAL_TEMPLATE.format(
            research_focus=self.config.research_focus,
            doc_title=doc.title,
            testimony_context=testimony_context,
            chief_opinion_context=chief_context,
            schema_text=schema_text,
        )
        caps = [self.config.claim_eval_max_output_tokens, self._bump_max_tokens(self.config.claim_eval_max_output_tokens)]
        raw = ""
        usage: Optional[Dict[str, int]] = None
        data: Optional[Dict[str, object]] = None
        parse_error: Optional[Exception] = None
        for attempt_idx, cap in enumerate(caps):
            attempt_label = f"claim evaluation attempt {attempt_idx+1}"
            estimated_tokens = self._assert_within_context(
                self.config.claim_eval_model,
                self.CLAIM_EVAL_SYSTEM_PROMPT,
                user_prompt,
                cap,
                attempt_label,
            )
            self._announce_estimate(
                label=attempt_label,
                model=self.config.claim_eval_model,
                system=self.CLAIM_EVAL_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                precomputed=estimated_tokens,
            )
            raw, usage = call_model(
                model=self.config.claim_eval_model,
                system_prompt=self.CLAIM_EVAL_SYSTEM_PROMPT,
                user_prompt=user_prompt,
                max_output_tokens=cap,
                reasoning=self.config.claim_eval_reasoning,
                call_context=f"claim-evaluator-{doc.title}-a{attempt_idx+1}",
                return_usage=True,
            )
            counted, estimated, actual = self._log_call(
                label=f"claim-evaluation-a{attempt_idx+1}",
                model=self.config.claim_eval_model,
                system=self.CLAIM_EVAL_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                usage=usage,
                estimated_tokens=estimated_tokens,
            )
            if actual is not None:
                print(f"[tokens] {attempt_label}: actual {actual} tokens (est {estimated})")
            else:
                print(f"[tokens] {attempt_label}: actual unavailable (est {estimated})")
            try:
                data = self.parse_json_response(raw, "claim evaluation")
            except Exception as exc:
                parse_error = exc
                if attempt_idx + 1 < len(caps):
                    print(
                        f"[retry] claim evaluation: parse failed; retrying with cap {caps[attempt_idx+1]}."
                    )
                    data = None
                    continue
                raise
            if self._needs_truncation_retry(usage, cap) and attempt_idx + 1 < len(caps):
                out = usage.get("output_tokens") if usage else None
                print(
                    f"[retry] claim evaluation: output {out} near cap {cap}; retrying with {caps[attempt_idx+1]}."
                )
                parse_error = None
                data = None
                continue
            parse_error = None
            break
        if parse_error:
            raise parse_error
        assert data is not None
        self._validate_claim_evaluation(data)
        return ClaimEvaluation(
            claim_analysis=str(data.get("claim_analysis", "")).strip(),
            scholarly_consensus_label=str(data.get("scholarly_consensus_label", "")).strip(),
            scholarly_consensus_pct=float(data.get("scholarly_consensus_pct", 0) or 0),
            supporting_evidence=[str(x) for x in data.get("supporting_evidence", [])],
            counterarguments=[str(x) for x in data.get("counterarguments", [])],
            conclusion=str(data.get("conclusion", "")).strip(),
            recommendations=[str(x) for x in data.get("recommendations", [])],
            overall_perspective=str(data.get("overall_perspective", "")).strip(),
        )

    def _validate_claim_evaluation(self, data: Dict[str, object]) -> None:
        required = {
            "claim_analysis": str,
            "scholarly_consensus_label": str,
            "scholarly_consensus_pct": (int, float),
            "supporting_evidence": list,
            "counterarguments": list,
            "conclusion": str,
            "recommendations": list,
            "overall_perspective": str,
        }
        missing = [k for k in required if k not in data]
        if missing:
            raise ValueError(f"claim evaluation: missing required fields {missing}")
        for key, typ in required.items():
            if not isinstance(data.get(key), typ):
                raise ValueError(f"claim evaluation: field {key} has wrong type ({type(data.get(key))})")

    def _format_testimony_context(self, testimonies: List[AgentTestimony]) -> str:
        lines: List[str] = []
        for t in testimonies:
            short = self._shorten_testimony_dict(t)
            supporting = "; ".join(short.get("supporting_points", []))
            concerns = "; ".join(short.get("concerns", []))
            recs = "; ".join(short.get("recommended_actions", []))
            lines.append(
                f"- {t.agent.agent_id}/{t.agent.name} | verdict={short.get('verdict_score')} "
                f"conf={short.get('confidence')} role={short.get('usage_role')} imp={short.get('importance_within_cluster')} "
                f"| summary={short.get('summary')} | supporting={supporting} | concerns={concerns} | recs={recs}"
            )
        return "\n".join(lines) if lines else "(no testimonies)"

    def _format_decision_context(self, decision: JudgeDecision) -> str:
        parts = [
            f"vote={decision.final_vote}",
            f"confidence={decision.confidence}",
        ]
        if decision.majority_rationale:
            parts.append(f"majority={decision.majority_rationale}")
        if decision.consensus_points:
            parts.append("consensus=" + "; ".join(decision.consensus_points[:4]))
        if decision.dissenting_points:
            parts.append("dissent=" + "; ".join(decision.dissenting_points[:3]))
        return " | ".join(parts)

    # ------ Judge stage ------
    JUDGE_SYSTEM_PROMPT = (
        "You are the Chief Justice moderating a multi-agent review. Integrate testimonies,"
        " identify consensus vs disagreement, and issue a final vote. Surface dissent explicitly."
        " Write in an academic, footnote-ready tone with concrete doctrinal anchors."
    )

    JUDGE_USER_TEMPLATE = """
Document: {doc_title}
Research focus: {research_focus}

Agent testimonies (JSON records):
{testimony_json}

Return a JSON object with keys:
- document_title
- final_vote ("tier_1"|"tier_2"|"tier_3"|"exclude")
- confidence
- majority_rationale
- consensus_points
- dissenting_points
- unresolved_questions
- disagreements (array of {{\"issue\",\"agents\",\"summary\"}})
- agent_votes (map agent_id -> {{\"verdict_score\",\"confidence\"}})
- doctrinal_refs (array of 3-5 concrete case/statute/doctrinal labels to remember; include any citations provided by agents)
- example_passages (array of 1-2 quote-like paraphrases capturing the author's voice; can reuse agent snippets)
- usage_role ("main_authority"|"foil"|"background")
- importance_within_cluster (int 1-5; higher = more central relative to peer articles)

Important formatting rules:
- Respond with ONLY a single JSON object.
- Begin with '{{' and end with '}}'.
- No markdown, no prose, no code fences, no reasoning.
- Follow the schema exactly.
- Include at least one concrete phrase or quote-like paraphrase from the article.
"""

    # ------ Literature review synthesis stage ------
    LIT_REVIEW_SYSTEM_PROMPT = """
You are a legal scholar writing the literature review section of a law review or social science article.

Your job is to synthesize per-article evaluations into a coherent, academic literature review in polished prose.
You DO NOT mention agents, models, “judges,” “opinions,” or any internal deliberation. You write as a single human author.

Voice and style:
- Neutral, analytic, law-review / social-science style; prefer third-person (“scholars have argued…”).
- Use precise doctrinal/methodological language; avoid conversational tone.

Goals:
- Situate the set of articles within the broader research area: what problem they address, why it matters.
- Identify major themes, positions, and methodological approaches across the articles.
- Highlight convergences and fault lines; note gaps and directions for further research.
- Make it easy to understand “who says what, using which methods, about which aspect of the problem.”

You treat the inputs as authoritative notes; do not invent new findings or holdings. Generalize and compare, but stay within provided information.
"""

    LIT_REVIEW_USER_TEMPLATE = """
You will be given structured evaluations for multiple scholarly works that bear on a common research area.

Research focus: {research_focus}
Corpus size: {doc_count} works.

Corpus (JSON list; each item describes one work):
---- CORPUS JSON START ----
{documents_json}
---- CORPUS JSON END ----

Task: Write a cohesive literature review section that:
1) Defines scope/corpus (fields, time range, methods, jurisdictions) and relation to the research focus.
2) Organizes the literature into 2–4 major themes or sub-debates; attribute positions using titles/years/venues when available.
3) Summarizes contributions/methods per cluster; use doctrinal anchors and example passages provided.
4) Highlights convergences vs disagreements; outline competing positions.
5) Critically evaluates strengths, limitations, and open questions; surface gaps and blind spots.
6) Connects the literature back to the research focus; note which strands to build on, which are background/foil.

Constraints:
- Write polished academic prose, not bullets.
- Do NOT mention agents, models, “judge opinions,” or internal scoring (translate tiers into natural language).
- Refer to works using provided metadata (title/year/venue/method). Do not fabricate citations beyond given data.
- Use concrete doctrinal references and example passages where provided.
- Target length: ~4,000 tokens of output.
{outline_instruction}
"""

    def run_judge_panel(self, doc: Document, testimonies: List[AgentTestimony]) -> JudgeDecision:
        testimony_json = json.dumps([self._shorten_testimony_dict(t) for t in testimonies], indent=2)
        base_user_prompt = self.JUDGE_USER_TEMPLATE.format(
            doc_title=doc.title,
            research_focus=self.config.research_focus,
            testimony_json=testimony_json,
        )
        parse_error: Optional[Exception] = None
        raw = ""
        data: Optional[Dict[str, object]] = None
        user_prompt = base_user_prompt
        caps = [self.config.judge_tokens, self._bump_max_tokens(self.config.judge_tokens)]
        for attempt_idx, cap in enumerate(caps):
            estimated_tokens = self._assert_within_context(
                self.config.judge_model,
                self.JUDGE_SYSTEM_PROMPT,
                user_prompt,
                cap,
                f"judge decision attempt {attempt_idx+1} for {doc.title}",
            )
            self._announce_estimate(
                label=f"judge attempt {attempt_idx+1}",
                model=self.config.judge_model,
                system=self.JUDGE_SYSTEM_PROMPT,
                user=user_prompt,
                max_tokens=cap,
                precomputed=estimated_tokens,
            )
            try:
                raw, usage = call_model(
                    model=self.config.judge_model,
                    system_prompt=self.JUDGE_SYSTEM_PROMPT,
                    user_prompt=user_prompt,
                    max_output_tokens=cap,
                    reasoning=self.config.judge_reasoning if attempt_idx == 0 else None,
                    text_verbosity="high",
                    call_context=f"litrev-judge-{doc.title}-a{attempt_idx+1}",
                    return_usage=True,
                )
                counted, estimated, actual = self._log_call(
                    label=f"judge-{doc.title}-a{attempt_idx+1}",
                    model=self.config.judge_model,
                    system=self.JUDGE_SYSTEM_PROMPT,
                    user=user_prompt,
                    max_tokens=cap,
                    usage=usage,
                    estimated_tokens=estimated_tokens,
                )
                if actual is not None:
                    print(
                        f"[tokens] judge attempt {attempt_idx+1}: actual {actual} tokens (est {estimated})"
                    )
                else:
                    print(f"[tokens] judge attempt {attempt_idx+1}: actual unavailable (est {estimated})")
            except Exception as exc:
                parse_error = exc
                continue
            try:
                data = self.parse_json_response(raw, f"judge {doc.title}")
            except Exception as exc:
                parse_error = exc
                if attempt_idx + 1 < len(caps):
                    user_prompt = base_user_prompt + "\n\nReturn STRICT JSON only, no commentary."
                    print(
                        f"[retry] judge {doc.title}: parse failed; retrying with cap {caps[attempt_idx+1]}."
                    )
                    data = None
                    continue
                break
            if self._needs_truncation_retry(usage, cap) and attempt_idx + 1 < len(caps):
                out = usage.get("output_tokens") if usage else None
                print(
                    f"[retry] judge {doc.title}: output {out} near cap {cap}; retrying with {caps[attempt_idx+1]}."
                )
                data = None
                parse_error = None
                continue
            parse_error = None
            break
        if parse_error:
            # try a final repair pass with the broken text (if any)
            if raw:
                try:
                    data = self._repair_json_response(raw, doc.title)
                    parse_error = None
                except Exception:
                    pass
            if parse_error:
                raise parse_error
        if data is None:
            raise RuntimeError(f"judge {doc.title}: no parsed decision returned")
        self._require_keys(
            data,
            [
                "final_vote",
                "confidence",
                "majority_rationale",
                "consensus_points",
                "dissenting_points",
                "doctrinal_refs",
                "example_passages",
                "usage_role",
                "importance_within_cluster",
            ],
            f"judge {doc.title}",
        )
        decision = JudgeDecision(
            document_title=data.get("document_title", doc.title),
            final_vote=data.get("final_vote", "tier_3"),
            confidence=data.get("confidence", "medium"),
            majority_rationale=str(data.get("majority_rationale", "")).strip(),
            dissenting_points=[str(x) for x in data.get("dissenting_points", [])],
            consensus_points=[str(x) for x in data.get("consensus_points", [])],
            disagreements=[dict(x) for x in data.get("disagreements", [])],
            unresolved_questions=[str(x) for x in data.get("unresolved_questions", [])],
            agent_votes={k: dict(v) for k, v in data.get("agent_votes", {}).items()},
            doctrinal_refs=[str(x) for x in data.get("doctrinal_refs", [])],
            example_passages=[str(x) for x in data.get("example_passages", [])],
            usage_role=str(data.get("usage_role", "background")),
            importance_within_cluster=int(data.get("importance_within_cluster", 3)),
        )
        opinion_md = self._format_judge_markdown(decision)
        doc_slug = self._doc_slug(doc)
        out_path = self.judge_dir / f"{doc_slug}__chief_opinion.md"
        out_path.write_text(opinion_md, encoding="utf-8")
        return decision

    def _format_judge_markdown(self, decision: JudgeDecision) -> str:
        sections = [
            f"# Chief Opinion: {decision.document_title}",
            f"**Final vote:** {decision.final_vote} ({decision.confidence} confidence)",
            f"**Cluster importance:** {decision.importance_within_cluster} / 5 | usage_role: {decision.usage_role}",
            "",
            "## Doctrinal Reference Points",
        ]
        sections.extend(f"- {item}" for item in (decision.doctrinal_refs or ["(none)"]))
        sections.extend(
            [
                "",
                "## Example Passages (voice cues)",
            ]
        )
        sections.extend(f"- {item}" for item in (decision.example_passages or ["(none)"]))
        sections.extend(
            [
                "",
                "## Majority Rationale",
                decision.majority_rationale or "(not provided)",
                "",
                "## Consensus Points",
            ]
        )
        sections.extend(f"- {item}" for item in (decision.consensus_points or ["(none)"]))
        sections.extend(["", "## Dissenting / Skeptical Notes"])
        sections.extend(f"- {item}" for item in (decision.dissenting_points or ["(none)"]))
        sections.extend(["", "## Unresolved Questions"])
        sections.extend(f"- {item}" for item in (decision.unresolved_questions or ["(none)"]))
        return "\n".join(sections)

    # ------ Metadata ------
    def write_metadata(
        self,
        doc: Document,
        chunk_summaries: List[str],
        testimonies: List[AgentTestimony],
        decision: JudgeDecision,
        claim_eval: Optional[ClaimEvaluation] = None,
    ) -> None:
        doc_slug = self._doc_slug(doc)
        payload = {
            "document_title": doc.title,
            "path": str(doc.path),
            "total_chunks": len(doc.chunks),
            "total_units": doc.total_units,
            "chunk_dir": doc_slug,
            "document_metadata": doc.metadata,
            "agent_testimonies": [t.to_dict() for t in testimonies],
            "judge_decision": decision.to_dict(),
        }
        if claim_eval:
            payload["claim_evaluation"] = claim_eval.to_dict()
        out_path = self.meta_dir / f"{doc_slug}.json"
        write_json(out_path, payload)

    # ------ Orchestration ------
    def process_document(self, doc: Document) -> None:
        print(f"\n=== Processing: {doc.title} ===")
        doc_start = time.time()
        progress = self._load_progress(doc)
        stage_start = time.time()
        chunk_summaries = self.generate_chunk_summaries(doc)
        print(f"[time] chunking+summaries: {time.time() - stage_start:.1f}s elapsed")
        self._print_progress("chunks", doc_start)
        reports: List[AgentReport] = []
        testimonies: List[AgentTestimony] = []
        agents_done = 0
        for agent in self.config.agents:
            agent_start = time.time()
            print(f"[{agent.name}] drafting memo...")
            report = self._load_or_build_agent_report(agent, doc, chunk_summaries, progress)
            reports.append(report)
            print(f"[{agent.name}] generating testimony...")
            testimonies.append(self._load_or_build_testimony(report, progress))
            self._save_progress(doc, progress)
            print(f"[time] agent {agent.agent_id} memo+testimony: {time.time() - agent_start:.1f}s")
            agents_done += 1
            self._print_progress(
                f"agent {agent.agent_id}",
                doc_start,
                agents_done=agents_done,
                total_agents=len(self.config.agents),
            )
        if progress.get("judge_done"):
            print("Judge opinion already completed; skipping judge stage.")
            print(f"[time] document total: {time.time() - doc_start:.1f}s")
            self._print_progress(
                "judge (cached)",
                doc_start,
                agents_done=len(self.config.agents),
                total_agents=len(self.config.agents),
                judge_done=True,
            )
            return
        print("Running judge panel...")
        judge_start = time.time()
        decision = self.run_judge_panel(doc, testimonies)
        progress["judge_done"] = True
        claim_eval = self._load_or_build_claim_evaluation(doc, testimonies, decision, progress)
        self._save_progress(doc, progress)
        self.write_metadata(doc, chunk_summaries, testimonies, decision, claim_eval)
        print(
            f"Chief opinion: vote={decision.final_vote} | confidence={decision.confidence}"
        )
        print(f"[time] judge stage: {time.time() - judge_start:.1f}s")
        print(f"[time] document total: {time.time() - doc_start:.1f}s")
        self._print_progress(
            "judge",
            doc_start,
            agents_done=len(self.config.agents),
            total_agents=len(self.config.agents),
            judge_done=True,
        )

    def run(self) -> None:
        self.pipeline_start = time.time()
        documents = self.load_documents()
        for doc in documents:
            self.process_document(doc)
        est_tokens = int(self.telemetry.get("estimated_tokens", 0))
        actual_tokens = self.telemetry.get("actual_tokens")
        missing_usage_calls = int(self.telemetry.get("missing_usage_calls", 0) or 0)
        print(f"\nAll documents processed. Outputs written to {self.output_dir}.")
        if isinstance(actual_tokens, int) and actual_tokens > 0:
            if missing_usage_calls:
                print(
                    f"Total tokens across calls: {est_tokens:,} "
                    f"(actual where available; {missing_usage_calls} call(s) missing usage so estimates used there)"
                )
            else:
                print(f"Total tokens across calls: {actual_tokens:,} (actual)")
        else:
            print(f"Total tokens across calls: {est_tokens:,} (estimated; usage unavailable)")
        if isinstance(self.telemetry.get("calls"), list):
            print(f"Total model calls: {len(self.telemetry['calls'])}")
        print(f"Total wall time: {time.time() - self.pipeline_start:.1f}s")
        print("\nAll documents processed. Outputs written to", self.output_dir)
        # Final synthesis stage: literature review across documents
        self.run_lit_review_synthesis(documents)

    # ------ Helpers ------
    def _agent_guidance(self, agent: AgentConfig) -> str:
        guidance = self.AGENT_GUIDANCE.get(agent.agent_id) if isinstance(agent, AgentConfig) else None
        return guidance.strip() if guidance else "Follow your mandate; no extra constraints."

    def _agent_scope(self, agent: AgentConfig, doc: Document, chunk_summaries: List[str]) -> str:
        base_scope = [
            f"- Full chunk summaries provided ({len(chunk_summaries)} total); reference chunk numbers explicitly.",
            f"- Document metadata: total_units={doc.total_units}, chunk_words={self.config.chunk_words}, chunk_overlap={self.config.chunk_overlap}.",
            "- Use captured media context if present; otherwise ignore media.",
        ]
        role_overrides = {
            "method": [
                "- Prioritize methodological and doctrinal validity cues; ignore broad policy unless it affects validity.",
                "- You do NOT have access to other agents' opinions; decide rigor independently.",
            ],
            "norm": [
                "- Prioritize rights, equity, stakeholder impacts, and governance levers.",
                "- Do not re-audit sampling/identification unless it breaks the normative claim.",
            ],
            "synthesis": [
                "- Focus on mapping debates, citation chains, and contribution type (incremental vs transformative).",
                "- Assume rigor/ethics handled elsewhere; concentrate on placement and agenda fit.",
            ],
            "skeptic": [
                "- Hunt for failure modes, hidden premises, and alternative explanations.",
                "- Avoid proposing new grand theories or policy programs.",
            ],
        }
        extras = role_overrides.get(agent.agent_id, [])
        return "\n".join(base_scope + extras)

    def _doc_slug(self, doc: Document) -> str:
        return doc.metadata.get("slug") or slugify(doc.title)

    def _chunk_fingerprint(self, doc: Document) -> str:
        parts = [
            doc.metadata.get("source_sha256", ""),
            str(doc.total_units),
            str(len(doc.chunks)),
            str(self.config.chunk_words),
            str(self.config.chunk_overlap),
            self.config.chunk_model,
            self.config.chunk_reasoning or "",
            str(self.config.chunk_max_output_tokens),
            self.CHUNK_SYSTEM_PROMPT.strip(),
        ]
        joined = "||".join(parts)
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def _agent_signature(self, agent: AgentConfig) -> Dict[str, object]:
        return {
            "agent_id": agent.agent_id,
            "name": agent.name,
            "brief": agent.brief,
            "focus": agent.focus,
            "style": agent.style,
            "model": agent.model,
            "reasoning": agent.reasoning,
            "text_verbosity": agent.text_verbosity,
        }

    def _progress_fingerprint(self, doc: Document) -> str:
        payload = {
            "chunk_fp": self._chunk_fingerprint(doc),
            "agent_report_tokens": self.config.agent_report_tokens,
            "agent_report_reasoning": self.config.agent_report_reasoning,
            "agent_testimony_tokens": self.config.agent_testimony_tokens,
            "judge_tokens": self.config.judge_tokens,
            "judge_reasoning": self.config.judge_reasoning,
            "claim_eval_tokens": self.config.claim_eval_max_output_tokens,
            "claim_eval_reasoning": self.config.claim_eval_reasoning,
            "agents": [self._agent_signature(a) for a in self.config.agents],
            "agent_report_template": self.AGENT_REPORT_TEMPLATE,
            "agent_testimony_template": self.AGENT_TESTIMONY_TEMPLATE,
            "judge_system_prompt": self.JUDGE_SYSTEM_PROMPT,
            "judge_user_template": self.JUDGE_USER_TEMPLATE,
            "claim_eval_system_prompt": self.CLAIM_EVAL_SYSTEM_PROMPT,
            "claim_eval_template": self.CLAIM_EVAL_TEMPLATE,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _context_limit_for_model(self, model: str) -> int:
        return MODEL_CONTEXT_LIMITS.get(model, DEFAULT_CONTEXT_LIMIT)

    def _assert_within_context(
        self, model: str, system_prompt: str, user_prompt: str, max_output_tokens: int, label: str
    ) -> int:
        limit = self._context_limit_for_model(model)
        estimated = estimate_total_tokens(system_prompt, user_prompt, max_output_tokens, model)
        if estimated > limit:
            raise RuntimeError(
                f"{label}: estimated {estimated} tokens exceeds context window {limit} for model {model}. "
                "Reduce chunk size/count, swap to a larger-context model, or trim inputs."
            )
        return estimated

    def _announce_estimate(
        self,
        *,
        label: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        precomputed: Optional[int] = None,
    ) -> int:
        estimated = precomputed if precomputed is not None else estimate_total_tokens(system, user, max_tokens, model)
        print(f"[tokens] {label}: est ~{estimated} tokens (pre-call)")
        return estimated

    def _log_call(
        self,
        label: str,
        model: str,
        system: str,
        user: str,
        max_tokens: int,
        usage: Optional[Dict[str, int]] = None,
        estimated_tokens: Optional[int] = None,
    ) -> tuple[int, int, Optional[int]]:
        estimated = estimated_tokens if estimated_tokens is not None else estimate_total_tokens(
            system, user, max_tokens, model
        )
        actual = usage.get("total_tokens") if usage else None
        counted = actual if isinstance(actual, int) else estimated
        self.telemetry.setdefault("estimated_tokens", 0)
        self.telemetry["estimated_tokens"] = int(self.telemetry.get("estimated_tokens", 0)) + counted
        self.telemetry.setdefault("actual_tokens", 0)
        self.telemetry.setdefault("missing_usage_calls", 0)
        if isinstance(actual, int):
            self.telemetry["actual_tokens"] = int(self.telemetry.get("actual_tokens", 0)) + actual
        else:
            self.telemetry["missing_usage_calls"] = int(self.telemetry.get("missing_usage_calls", 0)) + 1
        calls = self.telemetry.get("calls")
        if isinstance(calls, list):
            calls.append(
                {
                    "label": label,
                    "model": model,
                    "estimated_tokens": estimated,
                    "actual_tokens": actual,
                    "counted_tokens": counted,
                }
            )
        # Track per-role token usage for better ETA
        if label.startswith("agent-report-"):
            aid = label.replace("agent-report-", "", 1)
            self.telemetry.setdefault("agent_tokens", {})
            agent_tokens = self.telemetry["agent_tokens"]
            if isinstance(agent_tokens, dict):
                agent_tokens.setdefault(aid, 0)
                agent_tokens[aid] = int(agent_tokens.get(aid, 0)) + counted
        if label.startswith("agent-testimony-"):
            aid = label.replace("agent-testimony-", "", 1)
            self.telemetry.setdefault("agent_tokens", {})
            agent_tokens = self.telemetry["agent_tokens"]
            if isinstance(agent_tokens, dict):
                agent_tokens.setdefault(aid, 0)
                agent_tokens[aid] = int(agent_tokens.get(aid, 0)) + counted
        return counted, estimated, actual

    def _needs_truncation_retry(
        self, usage: Optional[Dict[str, int]], max_tokens: int, threshold: float = 0.9
    ) -> bool:
        if not usage:
            return False
        output_tokens = usage.get("output_tokens")
        if output_tokens is None:
            return False
        return output_tokens >= int(max_tokens * threshold)

    def _bump_max_tokens(self, max_tokens: int, bump: float = 1.5) -> int:
        bumped = int(max_tokens * bump)
        return bumped if bumped > max_tokens else max_tokens + 1

    def _progress_path(self, doc: Document) -> Path:
        return self.meta_dir / f"{self._doc_slug(doc)}.progress.json"

    def _load_progress(self, doc: Document) -> Dict[str, object]:
        path = self._progress_path(doc)
        current_fp = self._progress_fingerprint(doc)
        if path.exists():
            try:
                data = read_json(path)
                stored_fp = data.get("fingerprint")
                if stored_fp == current_fp:
                    return data
                print(f"[cache] Invalidating progress for {doc.title} (fingerprint mismatch).")
            except Exception:
                print(f"[cache] Progress file unreadable for {doc.title}; resetting.")
        return {"fingerprint": current_fp}

    def _save_progress(self, doc: Document, data: Dict[str, object]) -> None:
        data["fingerprint"] = self._progress_fingerprint(doc)
        write_json(self._progress_path(doc), data)

    def _shorten_testimony_dict(self, testimony: AgentTestimony) -> Dict[str, object]:
        def trunc(text: str, limit: int) -> str:
            return (text or "")[:limit]

        def trunc_list(items: List[str], limit: int, item_limit: int = 4) -> List[str]:
            return [trunc(it, limit) for it in items[:item_limit]]

        data = testimony.to_dict()
        data["summary"] = trunc(str(data.get("summary", "")), 800)
        data["supporting_points"] = trunc_list([str(x) for x in data.get("supporting_points", [])], 240)
        data["concerns"] = trunc_list([str(x) for x in data.get("concerns", [])], 240)
        data["recommended_actions"] = trunc_list([str(x) for x in data.get("recommended_actions", [])], 240)
        data["citations"] = trunc_list([str(x) for x in data.get("citations", [])], 64, item_limit=6)
        data["doctrinal_refs"] = trunc_list([str(x) for x in data.get("doctrinal_refs", [])], 120)
        data["example_passages"] = trunc_list([str(x) for x in data.get("example_passages", [])], 160)
        return data

    def _repair_json_response(self, raw_text: str, doc_title: str) -> Dict[str, object]:
        repair_prompt = (
            "You will be given a model output that was supposed to be JSON following this schema:\n"
            "{"
            '"document_title": str, "final_vote": str, "confidence": str, "majority_rationale": str, '
            '"consensus_points": list, "dissenting_points": list, "unresolved_questions": list, '
            '"disagreements": list, "agent_votes": object, '
            '"doctrinal_refs": list, "example_passages": list, "usage_role": str, "importance_within_cluster": int'
            "}\n"
            "The output was invalid. Return ONLY the fixed JSON object. No prose, no markdown.\n\n"
            f"Broken output:\n{raw_text}"
        )
        repaired = call_model(
            model=self.config.judge_model,
            system_prompt="You repair JSON into valid JSON only.",
            user_prompt=repair_prompt,
            max_output_tokens=self.config.judge_tokens,
            reasoning=None,
            text_verbosity="low",
            call_context=f"litrev-judge-repair-{doc_title}",
        )
        return self.parse_json_response(repaired, f"judge repair {doc_title}")

    def _load_or_build_agent_report(
        self, agent: AgentConfig, doc: Document, chunk_summaries: List[str], progress: Dict[str, object]
    ) -> AgentReport:
        memo_map = progress.setdefault("memos", {})
        memo_path = None
        if isinstance(memo_map, dict):
            memo_path = memo_map.get(agent.agent_id)
        if memo_path:
            path = Path(memo_path)
            if path.exists():
                memo_text = path.read_text(encoding="utf-8")
                return AgentReport(agent=agent, document=doc, memo_text=memo_text)
        report = self.build_agent_report(agent, doc, chunk_summaries)
        memo_map[agent.agent_id] = str(self.agent_dir / f"{self._doc_slug(doc)}__{agent.agent_id}.md")
        progress["memos"] = memo_map
        return report

    def _load_or_build_testimony(
        self, report: AgentReport, progress: Dict[str, object]
    ) -> AgentTestimony:
        test_map = progress.setdefault("testimonies", {})
        cached = None
        if isinstance(test_map, dict):
            cached = test_map.get(report.agent.agent_id)
        if isinstance(cached, dict):
            try:
                return AgentTestimony(
                    agent=report.agent,
                    summary=str(cached.get("summary", "")),
                    verdict_score=int(cached.get("verdict_score", 0)),
                    confidence=str(cached.get("confidence", "")),
                    supporting_points=[str(x) for x in cached.get("supporting_points", [])],
                    concerns=[str(x) for x in cached.get("concerns", [])],
                    recommended_actions=[str(x) for x in cached.get("recommended_actions", [])],
                    citations=[str(x) for x in cached.get("citations", [])],
                    doctrinal_refs=[str(x) for x in cached.get("doctrinal_refs", [])],
                    example_passages=[str(x) for x in cached.get("example_passages", [])],
                    usage_role=str(cached.get("usage_role", "background")),
                    importance_within_cluster=int(cached.get("importance_within_cluster", 3)),
                )
            except Exception:
                pass
        testimony = self.build_agent_testimony(report)
        test_map[report.agent.agent_id] = testimony.to_dict()
        progress["testimonies"] = test_map
        return testimony

    def _load_or_build_claim_evaluation(
        self,
        doc: Document,
        testimonies: List[AgentTestimony],
        decision: JudgeDecision,
        progress: Dict[str, object],
    ) -> ClaimEvaluation:
        cached = progress.get("claim_evaluation")
        if isinstance(cached, dict):
            try:
                return ClaimEvaluation(
                    claim_analysis=str(cached.get("claim_analysis", "")),
                    scholarly_consensus_label=str(cached.get("scholarly_consensus_label", "")),
                    scholarly_consensus_pct=float(cached.get("scholarly_consensus_pct", 0) or 0),
                    supporting_evidence=[str(x) for x in cached.get("supporting_evidence", [])],
                    counterarguments=[str(x) for x in cached.get("counterarguments", [])],
                    conclusion=str(cached.get("conclusion", "")),
                    recommendations=[str(x) for x in cached.get("recommendations", [])],
                    overall_perspective=str(cached.get("overall_perspective", "")),
                )
            except Exception:
                pass
        evaluation = self._build_claim_evaluation(doc, testimonies, decision)
        progress["claim_evaluation"] = evaluation.to_dict()
        return evaluation

    def _require_keys(self, data: Dict[str, object], keys: List[str], context: str) -> None:
        missing = [k for k in keys if k not in data]
        if missing:
            raise ValueError(f"{context}: missing expected keys {missing}")

    def _print_progress(
        self,
        stage: str,
        doc_start: float,
        *,
        agents_done: int = 0,
        total_agents: int = 0,
        judge_done: bool = False,
    ) -> None:
        now = time.time()
        elapsed_doc = now - doc_start
        elapsed_pipeline = (
            (now - self.pipeline_start) if self.pipeline_start is not None else elapsed_doc
        )
        tokens = int(self.telemetry.get("estimated_tokens", 0))
        remaining = self._estimate_remaining_seconds(
            agents_done=agents_done,
            total_agents=total_agents,
            judge_done=judge_done,
        )
        remaining_str = f"{remaining:.1f}s" if remaining is not None else "n/a"
        print(
            f"[progress] stage={stage} | doc_elapsed={elapsed_doc:.1f}s | "
            f"pipeline_elapsed={elapsed_pipeline:.1f}s | tokens~{tokens} | est_remaining={remaining_str}"
        )

    def _estimate_remaining_seconds(
        self, *, agents_done: int, total_agents: int, judge_done: bool
    ) -> Optional[float]:
        chunks_time = 0.0  # chunk stage already finished when called
        agent_tokens = self.telemetry.get("agent_tokens", {})
        tokens_list = []
        if isinstance(agent_tokens, dict):
            tokens_list = [v for v in agent_tokens.values() if isinstance(v, int)]
        avg_tokens = (sum(tokens_list) / len(tokens_list)) if tokens_list else (
            self.config.agent_report_tokens + self.config.agent_testimony_tokens
        )
        # heuristic: ~5s per 1k tokens based on observed average
        per_agent_sec = 5.0 * (avg_tokens / 1000.0)
        agents_remaining = max(total_agents - agents_done, 0) if total_agents > 0 else 0
        agents_time = per_agent_sec * agents_remaining
        judge_time = 0.0 if judge_done else 10.0
        total = chunks_time + agents_time + judge_time
        return total

    # ------ Final literature review synthesis ------
    def _truncate_text(self, text: Optional[str], limit: int) -> str:
        return (text or "")[:limit]

    def _truncate_list(self, items: List[str], item_limit: int, item_len: int) -> List[str]:
        return [self._truncate_text(str(it), item_len) for it in items[:item_limit]]

    def _normalize_doc_payload(self, entry: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "id": entry.get("id", ""),
            "slug": entry.get("slug", ""),
            "title": self._truncate_text(entry.get("title", ""), 200),
            "authors": entry.get("authors", []) or [],
            "year": entry.get("year"),
            "venue": self._truncate_text(entry.get("venue", ""), 160),
            "method": self._truncate_text(entry.get("method", ""), 160),
            "topic_tags": entry.get("topic_tags", []) or [],
            "key_questions": self._truncate_list(entry.get("key_questions", []) or [], 4, 200),
            "contribution_summary": self._truncate_text(entry.get("contribution_summary", ""), 1200),
            "normative_position": self._truncate_text(entry.get("normative_position", ""), 600),
            "strengths": self._truncate_list(entry.get("strengths", []) or [], 6, 220),
            "limitations": self._truncate_list(entry.get("limitations", []) or [], 6, 220),
            "open_questions": self._truncate_list(entry.get("open_questions", []) or [], 6, 220),
            "doctrinal_refs": self._truncate_list(entry.get("doctrinal_refs", []) or [], 5, 160),
            "example_passages": self._truncate_list(entry.get("example_passages", []) or [], 3, 200),
            "judge_vote": entry.get("judge_vote", ""),
            "judge_confidence": entry.get("judge_confidence", ""),
            "usage_role": entry.get("usage_role", "background"),
            "importance_within_cluster": int(entry.get("importance_within_cluster", 3)),
        }

    def _doc_payload_from_metadata(self, doc: Document) -> Optional[Dict[str, Any]]:
        meta_path = self.meta_dir / f"{self._doc_slug(doc)}.json"
        if not meta_path.exists():
            print(f"[lit-review] metadata missing for {doc.title}; skipping.")
            return None
        try:
            data = read_json(meta_path)
        except Exception as exc:
            print(f"[lit-review] failed to read metadata for {doc.title}: {exc}")
            return None
        doc_meta = data.get("document_metadata") or {}
        decision = data.get("judge_decision") or {}
        testimonies = data.get("agent_testimonies") or []

        strengths = list(decision.get("consensus_points", []) or [])
        limitations = list(decision.get("dissenting_points", []) or [])
        open_questions = list(decision.get("unresolved_questions", []) or [])
        doctrinal_refs = list(decision.get("doctrinal_refs", []) or [])
        example_passages = list(decision.get("example_passages", []) or [])
        # Fold in testimony details
        for t in testimonies:
            strengths.extend([str(x) for x in t.get("supporting_points", [])])
            limitations.extend([str(x) for x in t.get("concerns", [])])
            open_questions.extend([str(x) for x in t.get("recommended_actions", [])])
            doctrinal_refs.extend([str(x) for x in t.get("doctrinal_refs", [])])
            example_passages.extend([str(x) for x in t.get("example_passages", [])])

        title = data.get("document_title", doc.title)
        vote = decision.get("final_vote", "")
        vote_to_importance = {"tier_3": 5, "tier_2": 4, "tier_1": 2}
        derived_importance = vote_to_importance.get(str(vote), 3)
        normative_position = (
            doc_meta.get("normative_position")
            or decision.get("summary")
            or decision.get("majority_rationale", "")
        )
        payload = {
            "id": doc_meta.get("slug") or self._doc_slug(doc),
            "slug": doc_meta.get("slug") or self._doc_slug(doc),
            "title": title,
            "authors": doc_meta.get("authors") or [],
            "year": doc_meta.get("year"),
            "venue": doc_meta.get("venue") or doc_meta.get("journal"),
            "method": doc_meta.get("method") or doc_meta.get("methodology"),
            "topic_tags": doc_meta.get("topics") or doc_meta.get("tags") or [],
            "key_questions": doc_meta.get("key_questions") or [],
            "contribution_summary": decision.get("summary") or decision.get("majority_rationale", ""),
            "normative_position": normative_position,
            "strengths": strengths,
            "limitations": limitations,
            "open_questions": open_questions,
            "doctrinal_refs": doctrinal_refs,
            "example_passages": example_passages,
            "judge_vote": decision.get("final_vote", ""),
            "judge_confidence": decision.get("confidence", ""),
            "usage_role": decision.get("usage_role", "background"),
            "importance_within_cluster": decision.get("importance_within_cluster", derived_importance),
        }
        return self._normalize_doc_payload(payload)

    def _build_lit_review_corpus(self, documents: List[Document]) -> tuple[List[Dict[str, Any]], List[str]]:
        entries: List[Dict[str, Any]] = []
        missing: List[str] = []
        for doc in documents:
            payload = self._doc_payload_from_metadata(doc)
            if payload:
                entries.append(payload)
            else:
                missing.append(self._doc_slug(doc))
        return entries, missing

    def _lit_review_fingerprint(self, corpus_entries: List[Dict[str, Any]]) -> str:
        payload = {
            "research_focus": self.config.research_focus,
            "model": self.config.lit_review_model,
            "max_output_tokens": self.config.lit_review_max_output_tokens,
            "context_budget": self.config.lit_review_context_budget,
            "outline_first": self.config.lit_review_outline_first,
            "lit_review_reasoning": self.config.lit_review_reasoning,
            "lit_review_text_verbosity": self.config.lit_review_text_verbosity,
            "system_prompt": self.LIT_REVIEW_SYSTEM_PROMPT,
            "user_template": self.LIT_REVIEW_USER_TEMPLATE,
            "docs": corpus_entries,
        }
        blob = json.dumps(payload, sort_keys=True)
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()

    def _outline_instruction_text(self) -> str:
        if not self.config.lit_review_outline_first:
            return ""
        return (
            'After planning, output first an outline labeled "OUTLINE:" (section headings + 1-2 sentences each), '
            'then the full prose labeled "LITERATURE REVIEW:".'
        )

    def _lit_review_user_prompt(self, corpus_entries: List[Dict[str, Any]]) -> str:
        documents_json = json.dumps(corpus_entries, indent=2)
        density_note = ""
        if len(corpus_entries) > 15:
            density_note = (
                "\nWhen referencing individual works, keep to 1-2 sentences each unless importance_within_cluster >= 4."
            )
        return self.LIT_REVIEW_USER_TEMPLATE.format(
            research_focus=self.config.research_focus,
            doc_count=len(corpus_entries),
            documents_json=documents_json,
            outline_instruction=self._outline_instruction_text() + density_note,
        )

    def _select_doc_to_drop(self, entries: List[Dict[str, Any]]) -> int:
        usage_rank = {"background": 0, "foil": 1, "main_authority": 2}
        scored = sorted(
            enumerate(entries),
            key=lambda pair: (
                pair[1].get("importance_within_cluster", 3),
                usage_rank.get(str(pair[1].get("usage_role", "background")), 0),
                len(str(pair[1])),
            ),
        )
        return scored[0][0] if scored else 0

    def _trim_corpus_to_budget(
        self, corpus_entries: List[Dict[str, Any]], system_prompt: str, budget: int
    ) -> tuple[List[Dict[str, Any]], List[str], int]:
        def tighten_entry(entry: Dict[str, Any]) -> Dict[str, Any]:
            # Preserve core anchors; tighten lower-priority fields first.
            entry = dict(entry)
            entry["doctrinal_refs"] = entry.get("doctrinal_refs", [])[:3]
            entry["example_passages"] = entry.get("example_passages", [])[:1]
            entry["strengths"] = entry.get("strengths", [])[:3]
            entry["limitations"] = entry.get("limitations", [])[:3]
            if int(entry.get("importance_within_cluster", 3)) <= 3:
                entry["open_questions"] = entry.get("open_questions", [])[:1]
            else:
                entry["open_questions"] = entry.get("open_questions", [])[:3]
            entry["contribution_summary"] = self._truncate_text(
                entry.get("contribution_summary", ""), 800
            )
            entry["normative_position"] = self._truncate_text(entry.get("normative_position", ""), 300)
            return entry

        entries = list(corpus_entries)
        dropped: List[str] = []
        if not entries:
            return entries, dropped, 0
        # First-pass tightening
        entries = [tighten_entry(e) for e in entries]
        while True:
            user_prompt = self._lit_review_user_prompt(entries)
            estimated = estimate_total_tokens(
                system_prompt,
                user_prompt,
                self.config.lit_review_max_output_tokens,
                self.config.lit_review_model,
            )
            if estimated <= budget or len(entries) <= 1:
                return entries, dropped, estimated
            drop_idx = self._select_doc_to_drop(entries)
            dropped_id = entries[drop_idx].get("id", f"doc{drop_idx}")
            print(
                f"[lit-review] trimming corpus to fit context budget; dropping lowest-priority doc {dropped_id}"
            )
            dropped.append(str(dropped_id))
            entries.pop(drop_idx)

    def _parse_outline_and_review(self, text: str) -> tuple[Optional[str], str]:
        if not self.config.lit_review_outline_first:
            return None, text.strip()
        marker = "LITERATURE REVIEW:"
        if marker in text:
            parts = text.split(marker, 1)
            outline = parts[0].strip()
            review = parts[1].strip()
            return outline, review
        return None, text.strip()

    def _compute_lit_review_budget(self) -> int:
        if self.config.lit_review_context_budget is not None:
            return self.config.lit_review_context_budget
        model_limit = self._context_limit_for_model(self.config.lit_review_model)
        margin = max(self.config.lit_review_context_safety_margin, 0)
        return max(
            0,
            model_limit - margin - self.config.lit_review_max_output_tokens,
        )

    def run_lit_review_synthesis(self, documents: List[Document]) -> None:
        corpus_entries, missing = self._build_lit_review_corpus(documents)
        if not corpus_entries:
            print("[lit-review] No corpus entries available; skipping final synthesis.")
            return
        system_prompt = self.LIT_REVIEW_SYSTEM_PROMPT
        budget = self._compute_lit_review_budget()
        corpus_entries, dropped_for_budget, estimated_pre = self._trim_corpus_to_budget(
            corpus_entries, system_prompt, budget
        )
        fingerprint = self._lit_review_fingerprint(corpus_entries)
        if self.lit_review_cache_path.exists():
            try:
                cache = read_json(self.lit_review_cache_path)
                if cache.get("fingerprint") == fingerprint and self.lit_review_output_path.exists():
                    print("[lit-review] Cached literature review matches current corpus; skipping regeneration.")
                    return
            except Exception:
                pass
        user_prompt = self._lit_review_user_prompt(corpus_entries)
        estimated_tokens = self._assert_within_context(
            self.config.lit_review_model,
            system_prompt,
            user_prompt,
            self.config.lit_review_max_output_tokens,
            "lit-review synthesis",
        )
        self._announce_estimate(
            label="lit-review synthesis",
            model=self.config.lit_review_model,
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.config.lit_review_max_output_tokens,
            precomputed=estimated_tokens,
        )
        output_text, usage = call_model(
            model=self.config.lit_review_model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            max_output_tokens=self.config.lit_review_max_output_tokens,
            reasoning=self.config.lit_review_reasoning,
            text_verbosity=self.config.lit_review_text_verbosity,
            call_context="lit-review-synthesis",
            return_usage=True,
        )
        _, estimated, actual = self._log_call(
            label="lit-review-synthesis",
            model=self.config.lit_review_model,
            system=system_prompt,
            user=user_prompt,
            max_tokens=self.config.lit_review_max_output_tokens,
            usage=usage,
            estimated_tokens=estimated_tokens,
        )
        if actual is not None:
            print(f"[tokens] lit-review synthesis: actual {actual} tokens (est {estimated})")
        else:
            print(f"[tokens] lit-review synthesis: actual unavailable (est {estimated})")
        outline, review = self._parse_outline_and_review(output_text)
        self.lit_review_output_path.write_text(review, encoding="utf-8")
        if outline is not None:
            self.lit_review_outline_path.write_text(outline, encoding="utf-8")
        cache_payload = {
            "fingerprint": fingerprint,
            "docs_used": [e.get("id") for e in corpus_entries],
            "dropped_for_budget": dropped_for_budget,
            "missing_metadata": missing,
            "estimated_tokens": estimated,
            "actual_tokens": actual,
        }
        write_json(self.lit_review_cache_path, cache_payload)
        print(f"[lit-review] Literature review written to {self.lit_review_output_path}")
