from __future__ import annotations

import base64
import io
import json
import re
from contextlib import suppress
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

from core.openai_client import call_model, get_client
from core.utils import ensure_dir

SECTION_HEADINGS = [
    r"abstract",
    r"introduction",
    r"background",
    r"literature review",
    r"framework",
    r"methods",
    r"methodology",
    r"analysis",
    r"discussion",
    r"case study",
    r"results",
    r"findings",
    r"policy",
    r"conclusion",
    r"appendix",
]


@dataclass
class Section:
    title: str
    start_index: int
    end_index: int
    text: str


@dataclass
class IngestedDocument:
    text: str
    metadata: Dict[str, str]
    sections: List[Section] = field(default_factory=list)
    media_assets: List[Path] = field(default_factory=list)
    media_descriptions: List[Dict[str, str]] = field(default_factory=list)


class PDFExtractionError(RuntimeError):
    pass


class PDFIngestor:
    """Multi-stage PDF ingestion pipeline with layered extractors and optional LLM section detection.

    The ingestion flow:
        1. Try structured extractors (PyMuPDF, pdfminer).
        2. Optionally fall back to OCR or OpenAI Vision for scanned/image-heavy PDFs.
        3. Normalize whitespace + merge broken lines.
        4. Detect sections via regex anchors, optionally refined by an LLM call.
        5. Emit text + metadata for downstream chunking.

    Image extraction hooks are stubbed so we can later pass page images to multimodal models.
    """

    def __init__(
        self,
        *,
        allow_ocr: bool = True,
        use_llm_sections: bool = False,
        section_model: Optional[str] = None,
        media_output_dir: Optional[Path] = None,
        capture_images: bool = False,
        describe_media: bool = False,
        media_max_pages: int = 5,
        media_zoom: float = 2.0,
        allow_openai_vision: bool = False,
        vision_model: Optional[str] = None,
        vision_max_output_tokens: int = 900,
    ) -> None:
        self.allow_ocr = allow_ocr
        self.use_llm_sections = use_llm_sections
        self.section_model = section_model
        self.media_output_dir = media_output_dir
        self.capture_images = capture_images and media_output_dir is not None
        self.describe_media = describe_media and self.capture_images
        self.media_max_pages = max(1, media_max_pages)
        self.media_zoom = max(1.0, media_zoom)
        self.allow_openai_vision = allow_openai_vision
        self.vision_model = vision_model
        self.vision_max_output_tokens = vision_max_output_tokens
        if self.media_output_dir:
            ensure_dir(self.media_output_dir)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def ingest(self, pdf_path: Path) -> IngestedDocument:
        if not pdf_path.exists():
            raise FileNotFoundError(pdf_path)

        raw_text, extractor_name = self._extract_text_with_fallback(pdf_path)
        normalized_text = self._normalize_text(raw_text)
        sections = self._detect_sections(normalized_text)
        metadata = self._derive_metadata(normalized_text, pdf_path, extractor_name)
        media_assets: List[Path] = []
        media_descriptions: List[Dict[str, str]] = []
        if self.capture_images:
            media_assets = self._capture_media_assets(pdf_path)
            if self.describe_media and media_assets:
                media_descriptions = self._describe_media_assets(media_assets)
        if media_assets:
            metadata["media_assets"] = [str(p) for p in media_assets]
        if media_descriptions:
            metadata["media_descriptions"] = media_descriptions
        return IngestedDocument(
            text=normalized_text,
            metadata=metadata,
            sections=sections,
            media_assets=media_assets,
            media_descriptions=media_descriptions,
        )

    # ------------------------------------------------------------------
    # Extraction
    # ------------------------------------------------------------------
    def _extract_text_with_fallback(self, pdf_path: Path) -> Tuple[str, str]:
        errors: List[str] = []
        staged_extractors: Sequence[Tuple[str, callable]] = [
            ("pymupdf", self._extract_with_pymupdf),
            ("pdfminer", self._extract_with_pdfminer),
        ]

        for name, extractor in staged_extractors:
            try:
                text = extractor(pdf_path)
                if text and text.strip():
                    return text, name
            except Exception as exc:  # pragma: no cover - extractor availability varies
                errors.append(f"{name}: {exc}")

        if self.allow_ocr:
            try:
                text = self._extract_with_ocr(pdf_path)
                if text and text.strip():
                    return text, "ocr"
            except Exception as exc:  # pragma: no cover
                errors.append(f"ocr: {exc}")

        if self.allow_openai_vision:
            try:
                text = self._extract_with_openai_vision(pdf_path)
                if text and text.strip():
                    return text, "vision"
            except Exception as exc:  # pragma: no cover
                errors.append(f"vision: {exc}")

        raise PDFExtractionError(
            f"Failed to extract text from {pdf_path} after trying all extractors:\n" + "\n".join(errors)
        )

    def _extract_with_pymupdf(self, pdf_path: Path) -> str:
        import fitz  # type: ignore

        doc = fitz.open(pdf_path)
        try:
            pages = [page.get_text("text") for page in doc]
            return "\n".join(pages)
        finally:
            with suppress(Exception):
                doc.close()

    def _extract_with_pdfminer(self, pdf_path: Path) -> str:
        from io import StringIO

        from pdfminer.high_level import extract_text_to_fp  # type: ignore

        output = StringIO()
        with open(pdf_path, "rb") as f:
            extract_text_to_fp(f, output)
        return output.getvalue()

    def _extract_with_ocr(self, pdf_path: Path) -> str:
        try:
            import fitz  # type: ignore
            from PIL import Image
            import pytesseract
        except ImportError as exc:  # pragma: no cover - optional dep
            raise PDFExtractionError("OCR dependencies (PyMuPDF, Pillow, pytesseract) are missing.") from exc

        doc = fitz.open(pdf_path)
        parts: List[str] = []
        try:
            for page_idx in range(doc.page_count):
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(dpi=300)
                img = Image.open(io.BytesIO(pix.tobytes("png")))
                text = pytesseract.image_to_string(img)
                parts.append(text)
            return "\n\n".join(parts)
        finally:
            with suppress(Exception):
                doc.close()

    def _extract_with_openai_vision(self, pdf_path: Path) -> str:
        if not self.vision_model:
            raise PDFExtractionError("Vision OCR requested but no vision_model configured.")
        try:
            import fitz  # type: ignore
            from PIL import Image
        except ImportError as exc:  # pragma: no cover
            raise PDFExtractionError("PyMuPDF/Pillow required for vision OCR.") from exc

        doc = fitz.open(pdf_path)
        parts: List[str] = []
        try:
            for page_idx in range(doc.page_count):
                page = doc.load_page(page_idx)
                pix = page.get_pixmap(dpi=300)
                image_bytes = pix.tobytes("png")
                text = self._vision_extract_text(image_bytes)
                parts.append(text)
            return "\n\n".join(parts)
        finally:
            with suppress(Exception):
                doc.close()

    # ------------------------------------------------------------------
    # Normalization + metadata
    # ------------------------------------------------------------------
    def _normalize_text(self, text: str) -> str:
        # Merge line wraps where the PDF inserted mid-sentence breaks while preserving paragraph breaks.
        paragraphs = re.split(r"\n\s*\n", text)
        normalized_paragraphs: List[str] = []
        for para in paragraphs:
            para = re.sub(r"(?<![.?!])\n(?=[a-z0-9])", " ", para)
            para = re.sub(r"[ \t]+", " ", para).strip()
            if para:
                normalized_paragraphs.append(para)
        return "\n\n".join(normalized_paragraphs)

    def _derive_metadata(self, text: str, pdf_path: Path, extractor_name: str) -> Dict[str, str]:
        metadata: Dict[str, str] = {
            "source_path": str(pdf_path),
            "extractor": extractor_name,
        }
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        raw_title = lines[0][:256] if lines else ""
        if raw_title:
            metadata["raw_title"] = raw_title
        metadata["title"] = pdf_path.stem
        year_match = re.search(r"(19|20)\d{2}", text)
        if year_match:
            metadata["year"] = year_match.group(0)
        return metadata

    # ------------------------------------------------------------------
    # Section detection
    # ------------------------------------------------------------------
    def _detect_sections(self, text: str) -> List[Section]:
        sections = self._regex_sections(text)
        if self.use_llm_sections and self.section_model:
            llm_sections = self._llm_sections(text)
            if llm_sections:
                sections = self._merge_sections(sections, llm_sections)
        return sections

    def _regex_sections(self, text: str) -> List[Section]:
        matches: List[Tuple[int, str]] = []
        for heading in SECTION_HEADINGS:
            pattern = re.compile(rf"^(?P<title>{heading})\b.*$", re.IGNORECASE | re.MULTILINE)
            for match in pattern.finditer(text):
                matches.append((match.start(), match.group().strip()))
        matches.sort(key=lambda x: x[0])
        sections: List[Section] = []
        if not matches:
            return sections
        for idx, (start, title) in enumerate(matches):
            end = matches[idx + 1][0] if idx + 1 < len(matches) else len(text)
            sections.append(
                Section(title=title, start_index=start, end_index=end, text=text[start:end].strip())
            )
        return sections

    def _llm_sections(self, text: str) -> List[Section]:
        prompt = (
            "You detect major sections in legal or academic PDF text. "
            "Return JSON array [{\"title\": str, \"excerpt\": str}]."
        )
        truncated = text[:30_000]  # limit tokens for detection
        try:
            raw = call_model(
                model=self.section_model,
                system_prompt="You label sections.",
                user_prompt=f"Text:\n{truncated}\n\nDetect sections as JSON.",
                max_output_tokens=600,
                call_context="pdf-section-detector",
            )
            data = json.loads(raw.strip())
        except Exception:
            return []
        sections: List[Section] = []
        for item in data:
            title = str(item.get("title", "")).strip()
            excerpt = str(item.get("excerpt", "")).strip()
            if not title or not excerpt:
                continue
            pos = text.find(excerpt)
            if pos == -1:
                continue
            sections.append(
                Section(title=title, start_index=pos, end_index=pos + len(excerpt), text=excerpt)
            )
        return sections

    def _merge_sections(self, base: List[Section], llm_sections: List[Section]) -> List[Section]:
        if not llm_sections:
            return base
        combined = {sec.title.lower(): sec for sec in base}
        for sec in llm_sections:
            key = sec.title.lower()
            if key not in combined:
                combined[key] = sec
            else:
                current = combined[key]
                if len(sec.text) > len(current.text):
                    combined[key] = sec
        return sorted(combined.values(), key=lambda s: s.start_index)

    # ------------------------------------------------------------------
    # Media capture (stub for future multimodal support)
    # ------------------------------------------------------------------
    def _capture_media_assets(self, pdf_path: Path) -> List[Path]:
        if not self.media_output_dir:
            return []
        import fitz  # type: ignore

        doc = fitz.open(pdf_path)
        media_paths: List[Path] = []
        try:
            for idx in range(min(self.media_max_pages, doc.page_count)):
                page = doc.load_page(idx)
                matrix = fitz.Matrix(self.media_zoom, self.media_zoom)
                pix = page.get_pixmap(matrix=matrix)
                output_path = self.media_output_dir / f"{pdf_path.stem}_page_{idx+1:03d}.png"
                pix.save(output_path)
                media_paths.append(output_path)
            return media_paths
        finally:
            with suppress(Exception):
                doc.close()

    def _describe_media_assets(self, media_assets: List[Path]) -> List[Dict[str, str]]:
        if not media_assets or not self.vision_model:
            return []
        descriptions: List[Dict[str, str]] = []
        for asset_path in media_assets:
            try:
                with open(asset_path, "rb") as f:
                    image_bytes = f.read()
                text = self._vision_describe_image(image_bytes)
                descriptions.append({"path": str(asset_path), "description": text})
            except Exception:
                continue
        return descriptions

    def _vision_extract_text(self, image_bytes: bytes) -> str:
        prompt = (
            "Extract all readable text from this page image. Return the text in natural reading order. "
            "Ignore page numbers/headers when obvious."
        )
        return self._vision_image_request(prompt, image_bytes)

    def _vision_describe_image(self, image_bytes: bytes) -> str:
        prompt = (
            "Provide a concise description (2-4 sentences) of this legal/academic page image, noting charts, "
            "tables, or notable visual elements."
        )
        return self._vision_image_request(prompt, image_bytes)

    def _vision_image_request(self, prompt: str, image_bytes: bytes) -> str:
        if not self.vision_model:
            raise PDFExtractionError("Vision model not configured.")
        data_url = "data:image/png;base64," + base64.b64encode(image_bytes).decode("utf-8")
        client = get_client()
        resp = client.responses.create(
            model=self.vision_model,
            input=[
                {
                    "role": "user",
                    "content": [
                        {"type": "input_text", "text": prompt},
                        {"type": "input_image", "image_url": data_url},
                    ],
                }
            ],
            max_output_tokens=self.vision_max_output_tokens,
        )
        text = getattr(resp, "output_text", None)
        if text:
            return str(text).strip()
        outputs = getattr(resp, "output", None) or []
        for item in outputs:
            for block in getattr(item, "content", []) or []:
                maybe_text = getattr(block, "text", None)
                if maybe_text:
                    return str(maybe_text).strip()
        return ""
