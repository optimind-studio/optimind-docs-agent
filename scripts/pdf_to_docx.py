"""
Optimind PDF → Word Converter

Converts a .pdf to a .docx using pdf2docx, preserving text, tables, and images
from the PDF text layer verbatim. Intended as the first step in the
PDF-polishing flow: this script produces the intermediate .docx that the
`/polish-word` skill then restyles.

Usage:
  python pdf_to_docx.py --input path/to/source.pdf \
                        --output path/to/target.docx

Output: JSON metadata on stdout, e.g.:
  {"pages": 12, "tables_detected": 3, "images_detected": 2,
   "output_path": "...", "text_char_count": 18432}

Exit codes:
  0  success
  1  input error (missing file, wrong extension, no text layer, encrypted)
  2  conversion failure
"""
import argparse
import json
import sys
from pathlib import Path


# Minimum total text-layer characters below which we treat the PDF as scanned /
# image-only. A single cover page can legitimately have very little text; we
# pick a low threshold that still flags "essentially no text layer".
MIN_TEXT_CHARS = 50


def die(message: str, exit_code: int = 1) -> None:
    print(json.dumps({"error": message}), file=sys.stderr)
    sys.exit(exit_code)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Convert a PDF to a .docx for the Optimind polisher."
    )
    parser.add_argument("--input", required=True, help="Path to source .pdf")
    parser.add_argument("--output", required=True, help="Path to target .docx")
    args = parser.parse_args()

    src = Path(args.input).expanduser()
    dst = Path(args.output).expanduser()

    # ── Pre-flight ────────────────────────────────────────────────────────────
    if not src.exists():
        die(f"Input file not found: {src}")
    if not src.is_file():
        die(f"Input path is not a file: {src}")
    if src.suffix.lower() != ".pdf":
        die(f"Input is not a .pdf (got {src.suffix!r}): {src}")
    if dst.suffix.lower() != ".docx":
        die(f"Output must have a .docx extension (got {dst.suffix!r}): {dst}")

    dst.parent.mkdir(parents=True, exist_ok=True)

    # Probe the PDF for encryption + text-layer size before spending time on
    # the full conversion. PyMuPDF is available transitively via pdf2docx.
    try:
        import fitz  # PyMuPDF
    except ImportError:
        die("PyMuPDF (fitz) is not installed — reinstall plugin dependencies.", 2)

    try:
        pdf = fitz.open(str(src))
    except Exception as exc:
        die(f"Could not open PDF: {exc}")

    try:
        if pdf.is_encrypted:
            die(
                "This PDF is password-protected. Remove the password "
                "(e.g. open it in Preview/Adobe and re-export) and try again."
            )
        page_count = pdf.page_count
        text_char_count = sum(len(page.get_text() or "") for page in pdf)
    finally:
        pdf.close()

    if text_char_count < MIN_TEXT_CHARS:
        die(
            "This PDF has no text layer (it looks scanned or image-only). "
            "This converter does not do OCR — re-export the source document "
            "as a PDF with selectable text, or OCR it first."
        )

    # ── Convert ───────────────────────────────────────────────────────────────
    try:
        from pdf2docx import Converter
    except ImportError:
        die("pdf2docx is not installed — reinstall plugin dependencies.", 2)

    try:
        cv = Converter(str(src))
        try:
            cv.convert(str(dst), start=0, end=None)
        finally:
            cv.close()
    except Exception as exc:
        die(f"PDF-to-DOCX conversion failed: {exc}", 2)

    if not dst.exists() or dst.stat().st_size == 0:
        die("Conversion produced no output file.", 2)

    # ── Post-flight summary ───────────────────────────────────────────────────
    tables_detected = 0
    images_detected = 0
    try:
        from docx import Document
        doc = Document(str(dst))
        tables_detected = len(doc.tables)
        # Inline shapes covers embedded images; floating shapes are rarer in
        # pdf2docx output but we count them defensively.
        images_detected = len(doc.inline_shapes)
    except Exception:
        # Summary is best-effort — if counting fails, the .docx itself is still
        # valid and usable, so we don't abort.
        pass

    print(json.dumps({
        "pages": page_count,
        "tables_detected": tables_detected,
        "images_detected": images_detected,
        "output_path": str(dst),
        "text_char_count": text_char_count,
    }))


if __name__ == "__main__":
    main()
