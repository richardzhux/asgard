from __future__ import annotations

import argparse
from pathlib import Path

from pipelines.litrev_pipeline import LitReviewConfig, LitReviewPipeline

DEFAULT_PDF_DIR = Path("/Users/rx/Downloads/ISCP")
DEFAULT_RESEARCH_FOCUS = (
    "Map methodological rigor, normative stakes, and doctrinal contributions across a folder"
    " of scholarly PDFs, surfacing consensus, dissent, and recommended follow-up work."
)

MODEL_LIMITS = {
    "gpt-5.1": 400_000,
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the literature review pipeline on a directory of PDFs.")
    parser.add_argument(
        "input_path",
        nargs="?",
        default=str(DEFAULT_PDF_DIR),
        help="Path to a directory containing PDFs (default: %(default)s)",
    )
    parser.add_argument(
        "--research-focus",
        default=DEFAULT_RESEARCH_FOCUS,
        help="Override the default research focus string used in prompts.",
    )
    parser.add_argument(
        "--allow-pdf-ocr",
        action="store_true",
        help="Enable Tesseract OCR fallback when native text extraction fails.",
    )
    parser.add_argument(
        "--allow-openai-vision",
        action="store_true",
        help="Enable OpenAI Vision OCR fallback (requires vision-capable model).",
    )
    parser.add_argument(
        "--vision-model",
        default="gpt-5-mini",
        help="Model to use for OpenAI Vision OCR / media descriptions (default: %(default)s).",
    )
    parser.add_argument(
        "--vision-max-output-tokens",
        type=int,
        default=900,
        help="Max tokens per Vision OCR response (default: %(default)s).",
    )
    parser.add_argument(
        "--use-llm-sections",
        action="store_true",
        help="Use an LLM to refine detected section boundaries.",
    )
    parser.add_argument(
        "--section-model",
        default="gpt-5.1",
        help="Model to use for LLM-based section detection (default: %(default)s).",
    )
    parser.add_argument(
        "--capture-media",
        action="store_true",
        help="Render the first N pages of each PDF to PNGs for downstream use.",
    )
    parser.add_argument(
        "--describe-media",
        action="store_true",
        help="Generate textual descriptions for captured media using the vision model.",
    )
    parser.add_argument(
        "--media-output-dir",
        type=Path,
        default=Path("media_assets"),
        help="Directory where captured page images will be stored (default: %(default)s).",
    )
    parser.add_argument(
        "--media-max-pages",
        type=int,
        default=5,
        help="Number of pages to capture per PDF when --capture-media is enabled (default: %(default)s).",
    )
    parser.add_argument(
        "--media-zoom",
        type=float,
        default=2.0,
        help="Zoom factor when rendering page images (default: %(default)s).",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_dir = Path(args.input_path).expanduser().resolve()

    config = LitReviewConfig(
        pdf_dir=pdf_dir,
        research_focus=args.research_focus,
        model_limits=MODEL_LIMITS,
        allow_pdf_ocr=args.allow_pdf_ocr,
        allow_openai_vision=args.allow_openai_vision,
        vision_model=args.vision_model if args.allow_openai_vision or args.describe_media else None,
        vision_max_output_tokens=args.vision_max_output_tokens,
        use_llm_section_detection=args.use_llm_sections,
        section_detection_model=args.section_model if args.use_llm_sections else None,
        capture_media=args.capture_media,
        describe_media=args.describe_media,
        media_output_dir=args.media_output_dir if args.capture_media else None,
        media_max_pages=args.media_max_pages,
        media_zoom=args.media_zoom,
    )

    pipeline = LitReviewPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
