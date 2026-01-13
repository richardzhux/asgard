from __future__ import annotations

import json
import time
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from core.chunking import chunk_text
from core.models import Document, TextChunk
from core.openai_client import call_model
from core.utils import ensure_dir, slugify
from ingestion.pdf_ingestor import IngestedDocument, PDFIngestor


@dataclass
class CourseReviewConfig:
    pdf_dir: Path
    course_name: str
    chunk_model: str = "gpt-5.1"
    chunk_max_output_tokens: int = 1500
    chunk_words: int = 1500
    chunk_overlap: int = 120
    summary_model: str = "gpt-5.1"
    summary_tokens: int = 1500
    concepts_model: str = "gpt-5.1"
    concepts_tokens: int = 2400
    practice_model: str = "gpt-5.1"
    practice_tokens: int = 3600
    practice_count: int = 12
    cram_model: str = "gpt-5.1"
    cram_tokens: int = 4200
    output_dir: Path = Path("courserev_outputs")
    chunk_subdir: str = "chunk_summaries"
    doc_summary_subdir: str = "doc_summaries"
    metadata_subdir: str = "metadata"
    allow_pdf_ocr: bool = True
    allow_openai_vision: bool = False
    vision_model: Optional[str] = None
    vision_max_output_tokens: int = 900
    use_llm_section_detection: bool = False
    section_detection_model: Optional[str] = None
    capture_media: bool = False
    describe_media: bool = False
    media_output_dir: Optional[Path] = None
    media_max_pages: int = 5
    media_zoom: float = 2.0


class CourseReviewPipeline:
    """Exam-focused review pipeline for mixed course materials."""

    CHUNK_SYSTEM_PROMPT = "You are a course assistant producing concise study notes from raw text."
    CHUNK_USER_TEMPLATE = """
Course: {course_name}
Document: {doc_title}
Chunk {chunk_idx}/{chunk_count} (units {start_unit}-{end_unit})

Text:
----
{chunk_text}
----

Return a compact note with:
- key concepts or sections
- definitions or formulas
- examples (if present)
- pitfalls or common confusions
"""

    DOC_SUMMARY_SYSTEM = "You summarize course materials for exam prep. Be concise and structured."
    DOC_SUMMARY_USER = """
Course: {course_name}
Document: {doc_title}

Chunk notes:
{chunk_notes}

Write a tight summary (bullets allowed) covering:
- main ideas and sections
- definitions/formulas
- examples or cases mentioned
- pitfalls or common misconceptions
Target length: ~500 tokens; avoid fluff.
"""

    CONCEPT_SYSTEM = "You extract course concepts into clean JSON."
    CONCEPT_USER = """
Course: {course_name}

Use the document summaries below to extract key concepts.
Return a JSON array of objects with:
- term (string)
- definition (string)
- example (string, can be blank if none)
- common_pitfall (string, can be blank)
- source (string: document title or filename)

Document summaries:
{doc_summaries}
"""

    PRACTICE_SYSTEM = "You create exam-style practice questions with answers."
    PRACTICE_USER = """
Course: {course_name}

Based on the document summaries below, write {count} practice questions with answers.
Return a JSON array of objects:
- question (string)
- answer (string)
- difficulty (easy|medium|hard)
- type (conceptual|applied|calculation)
- source (string: document title or filename)

Document summaries:
{doc_summaries}
"""

    CRAM_SYSTEM = "You write a crisp exam cram sheet."
    CRAM_USER = """
Course: {course_name}

Use the document summaries plus the concept and practice sets to write a one-pager cram sheet.
Format: Markdown with sections:
- Overview (2-3 sentences)
- Key concepts (bullets; include formulas/defs)
- Examples or cases (bullets)
- Pitfalls (bullets)
- Quick practice (2-3 Q&A in-line)

Document summaries:
{doc_summaries}

Concepts (JSON):
{concepts_json}

Practice (JSON):
{practice_json}
"""

    def __init__(self, config: CourseReviewConfig) -> None:
        self.config = config
        self.chunk_dir = self.config.output_dir / self.config.chunk_subdir
        self.doc_summary_dir = self.config.output_dir / self.config.doc_summary_subdir
        self.meta_dir = self.config.output_dir / self.config.metadata_subdir
        self.raw_response_dir = self.meta_dir / "raw_responses"
        for path in [self.config.output_dir, self.chunk_dir, self.doc_summary_dir, self.meta_dir, self.raw_response_dir]:
            ensure_dir(path)
        self.pdf_ingestor = PDFIngestor(
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

    # ------------------------------------------------------------------
    # Main entry
    # ------------------------------------------------------------------
    def run(self) -> None:
        docs = self.load_documents()
        doc_summaries: Dict[str, str] = {}
        all_chunk_notes: Dict[str, List[str]] = {}
        for doc in docs:
            notes = self.generate_chunk_summaries(doc)
            all_chunk_notes[doc.metadata["slug"]] = notes
            summary = self.build_doc_summary(doc, notes)
            doc_summaries[doc.metadata["slug"]] = summary
            self._write_doc_summary(doc, summary)
        concepts = self.build_concepts(doc_summaries)
        practice = self.build_practice(doc_summaries)
        self._write_json(self.config.output_dir / "concepts.json", concepts)
        self._write_json(self.config.output_dir / "practice.json", practice)
        cram = self.build_cram_sheet(doc_summaries, concepts, practice)
        (self.config.output_dir / "exam_cram.md").write_text(cram, encoding="utf-8")
        print(f"Done. Outputs under {self.config.output_dir}")

    # ------------------------------------------------------------------
    # Ingestion and chunking
    # ------------------------------------------------------------------
    def load_documents(self) -> List[Document]:
        directory = self.config.pdf_dir
        if not directory.exists():
            raise FileNotFoundError(f"Source directory does not exist: {directory}")
        pdf_paths = sorted(p for p in directory.rglob("*.pdf"))
        if not pdf_paths:
            raise FileNotFoundError(f"No PDF files found in {directory}")
        docs: List[Document] = []
        slug_counts: Dict[str, int] = {}
        for path in pdf_paths:
            print(f"[ingest] {path}")
            ingestion = self.pdf_ingestor.ingest(path)
            text = ingestion.text
            chunks = chunk_text(text, self.config.chunk_words, self.config.chunk_overlap)
            total_units = chunks[-1].end_unit if chunks else 0
            metadata = dict(ingestion.metadata)
            metadata["source_path"] = str(path)
            title = metadata.get("title") or path.stem
            slug = slugify(title)
            if slug in slug_counts:
                slug_counts[slug] += 1
                slug = f"{slug}-{slug_counts[slug]}"
            else:
                slug_counts[slug] = 1
            metadata["slug"] = slug
            docs.append(Document(path=path, title=title, chunks=chunks, total_units=total_units, metadata=metadata))
        return docs

    def _chunk_header(self, chunk: TextChunk) -> str:
        return f"# Chunk {chunk.idx+1:02d} (units {chunk.start_unit}-{chunk.end_unit})\n\n"

    def summarize_chunk(self, doc: Document, chunk: TextChunk) -> str:
        user_prompt = self.CHUNK_USER_TEMPLATE.format(
            course_name=self.config.course_name,
            doc_title=doc.title,
            chunk_idx=chunk.idx + 1,
            chunk_count=len(doc.chunks),
            start_unit=chunk.start_unit,
            end_unit=chunk.end_unit,
            chunk_text=chunk.text,
        )
        text = call_model(
            model=self.config.chunk_model,
            system_prompt=self.CHUNK_SYSTEM_PROMPT,
            user_prompt=user_prompt,
            max_output_tokens=self.config.chunk_max_output_tokens,
            reasoning="medium",
            call_context=f"courserev-chunk-{doc.title}-{chunk.idx+1}",
        )
        return self._chunk_header(chunk) + text.strip() + "\n"

    def generate_chunk_summaries(self, doc: Document) -> List[str]:
        summaries: List[str] = []
        doc_dir = self.chunk_dir / doc.metadata["slug"]
        ensure_dir(doc_dir)
        for chunk in doc.chunks:
            chunk_path = doc_dir / f"chunk_{chunk.idx+1:02d}.md"
            if chunk_path.exists():
                summaries.append(chunk_path.read_text(encoding="utf-8"))
                continue
            note = self.summarize_chunk(doc, chunk)
            summaries.append(note)
            chunk_path.write_text(note, encoding="utf-8")
        return summaries

    # ------------------------------------------------------------------
    # Doc summary
    # ------------------------------------------------------------------
    def build_doc_summary(self, doc: Document, chunk_notes: List[str]) -> str:
        blob = "\n".join(chunk_notes)
        user_prompt = self.DOC_SUMMARY_USER.format(
            course_name=self.config.course_name,
            doc_title=doc.title,
            chunk_notes=blob,
        )
        summary = call_model(
            model=self.config.summary_model,
            system_prompt=self.DOC_SUMMARY_SYSTEM,
            user_prompt=user_prompt,
            max_output_tokens=self.config.summary_tokens,
            reasoning="medium",
            call_context=f"courserev-doc-summary-{doc.title}",
        )
        return summary.strip()

    def _write_doc_summary(self, doc: Document, summary: str) -> None:
        path = self.doc_summary_dir / f"{doc.metadata['slug']}.md"
        path.write_text(summary, encoding="utf-8")

    # ------------------------------------------------------------------
    # Concepts / practice / cram
    # ------------------------------------------------------------------
    def build_concepts(self, doc_summaries: Dict[str, str]) -> List[Dict[str, object]]:
        summary_text = self._format_doc_summaries(doc_summaries)
        user_prompt = self.CONCEPT_USER.format(course_name=self.config.course_name, doc_summaries=summary_text)
        raw = call_model(
            model=self.config.concepts_model,
            system_prompt=self.CONCEPT_SYSTEM,
            user_prompt=user_prompt,
            max_output_tokens=self.config.concepts_tokens,
            call_context="courserev-concepts",
        )
        parsed = self.parse_json_response(raw, "course concepts")
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "concepts" in parsed:
            val = parsed.get("concepts")
            return val if isinstance(val, list) else []
        return []

    def build_practice(self, doc_summaries: Dict[str, str]) -> List[Dict[str, object]]:
        summary_text = self._format_doc_summaries(doc_summaries)
        user_prompt = self.PRACTICE_USER.format(
            course_name=self.config.course_name,
            doc_summaries=summary_text,
            count=self.config.practice_count,
        )
        raw = call_model(
            model=self.config.practice_model,
            system_prompt=self.PRACTICE_SYSTEM,
            user_prompt=user_prompt,
            max_output_tokens=self.config.practice_tokens,
            call_context="courserev-practice",
        )
        parsed = self.parse_json_response(raw, "course practice")
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict) and "practice" in parsed:
            val = parsed.get("practice")
            return val if isinstance(val, list) else []
        return []

    def build_cram_sheet(
        self, doc_summaries: Dict[str, str], concepts: List[Dict[str, object]], practice: List[Dict[str, object]]
    ) -> str:
        summary_text = self._format_doc_summaries(doc_summaries)
        concepts_json = json.dumps(concepts[:20], indent=2)
        practice_json = json.dumps(practice[: min(10, len(practice))], indent=2)
        user_prompt = self.CRAM_USER.format(
            course_name=self.config.course_name,
            doc_summaries=summary_text,
            concepts_json=concepts_json,
            practice_json=practice_json,
        )
        cram = call_model(
            model=self.config.cram_model,
            system_prompt=self.CRAM_SYSTEM,
            user_prompt=user_prompt,
            max_output_tokens=self.config.cram_tokens,
            call_context="courserev-cram-sheet",
        )
        return cram.strip()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _format_doc_summaries(self, doc_summaries: Dict[str, str]) -> str:
        parts: List[str] = []
        for slug, text in doc_summaries.items():
            parts.append(f"### {slug}\n{text}\n")
        return "\n".join(parts)

    def _write_json(self, path: Path, payload: object) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    def parse_json_response(self, raw_text: str, context: str) -> object:
        """Best-effort JSON extraction, adapted from litrev pipeline."""

        def _strip_code_fence(text: str) -> str:
            text = text.strip()
            if text.startswith("```"):
                end_idx = text.rfind("```")
                if end_idx != -1:
                    inner = text[text.find("\n") + 1 : end_idx]
                    return inner.strip()
            return text

        cleaned = raw_text.strip()
        decoder = json.JSONDecoder()

        def _try_load(text: str) -> Optional[dict]:
            with suppress(Exception):
                obj = json.loads(text)
                return obj
            with suppress(Exception):
                obj, _ = decoder.raw_decode(text)
                return obj if isinstance(obj, (dict, list)) else None
            return None

        candidates: List[str] = []
        fenced = _strip_code_fence(cleaned)
        if fenced:
            candidates.append(fenced)
        if cleaned and cleaned != fenced:
            candidates.append(cleaned)
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
