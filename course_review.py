from __future__ import annotations

import argparse
from pathlib import Path

from pipelines.course_pipeline import CourseReviewConfig, CourseReviewPipeline

DEFAULT_PDF_DIR = Path("/Users/rx/Downloads/course-materials")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the course review pipeline on a directory of PDFs.")
    parser.add_argument("input_path", nargs="?", default=str(DEFAULT_PDF_DIR), help="Path to a directory containing PDFs.")
    parser.add_argument("--course-name", default="Course Review", help="Name of the course for prompts.")
    parser.add_argument("--allow-pdf-ocr", action="store_true", help="Enable Tesseract OCR fallback.")
    parser.add_argument("--allow-openai-vision", action="store_true", help="Enable OpenAI Vision OCR.")
    parser.add_argument("--vision-model", default="gpt-5-mini", help="Model to use for OpenAI Vision OCR/media descriptions.")
    parser.add_argument("--vision-max-output-tokens", type=int, default=900, help="Max tokens per Vision OCR response.")
    parser.add_argument("--chunk-words", type=int, default=900, help="Units per chunk (default: %(default)s).")
    parser.add_argument("--chunk-overlap", type=int, default=80, help="Overlap between chunks (default: %(default)s).")
    parser.add_argument("--practice-count", type=int, default=8, help="How many practice questions to generate.")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    pdf_dir = Path(args.input_path).expanduser().resolve()
    config = CourseReviewConfig(
        pdf_dir=pdf_dir,
        course_name=args.course_name,
        allow_pdf_ocr=args.allow_pdf_ocr,
        allow_openai_vision=args.allow_openai_vision,
        vision_model=args.vision_model if args.allow_openai_vision else None,
        vision_max_output_tokens=args.vision_max_output_tokens,
        chunk_words=args.chunk_words,
        chunk_overlap=args.chunk_overlap,
        practice_count=args.practice_count,
    )
    pipeline = CourseReviewPipeline(config)
    pipeline.run()


if __name__ == "__main__":
    main()
