"""
Extract text from a .docx or .pdf file so Claude can infer document metadata
(title, client name, reporting period) without reading the binary file.

Usage: python extract_text.py <path/to/file.docx|file.pdf>
Output: plain text with heading level markers, printed to stdout
"""
import sys
from pathlib import Path


def _extract_docx(path: str) -> str:
    from docx import Document
    from docx.oxml.ns import qn

    def get_heading_level(paragraph) -> int | None:
        style_name = paragraph.style.name
        if style_name.startswith("Heading"):
            try:
                return int(style_name.split()[-1])
            except ValueError:
                pass
        pPr = paragraph._p.find(qn("w:pPr"))
        if pPr is not None:
            outlineLvl = pPr.find(qn("w:outlineLvl"))
            if outlineLvl is not None:
                val = outlineLvl.get(qn("w:val"))
                if val is not None:
                    return int(val) + 1
        return None

    doc = Document(path)
    lines: list[str] = []
    for para in doc.paragraphs:
        text = para.text.strip()
        if not text:
            continue
        level = get_heading_level(para)
        if level:
            prefix = "#" * level
            lines.append(f"{prefix} {text}")
        else:
            lines.append(text)
    return "\n".join(lines)


def _extract_pdf(path: str) -> str:
    """Text-only extraction from the first few pages; sized for title/client/period inference."""
    import pdfplumber

    lines: list[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages[:3]:
            try:
                text = page.extract_text() or ""
            except Exception:
                continue
            for raw in text.splitlines():
                s = raw.strip()
                if s:
                    lines.append(s)
    return "\n".join(lines)


def extract(path: str) -> None:
    suffix = Path(path).suffix.lower()
    if suffix == ".docx":
        print(_extract_docx(path))
    elif suffix == ".pdf":
        print(_extract_pdf(path))
    else:
        print(f"Unsupported extension: {suffix}", file=sys.stderr)
        sys.exit(2)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_text.py <path/to/file.docx|file.pdf>", file=sys.stderr)
        sys.exit(1)
    extract(sys.argv[1])
