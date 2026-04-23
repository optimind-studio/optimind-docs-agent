"""
Extract text from a .docx file so Claude can infer document metadata
(title, client name, reporting period) without reading the binary file.

Usage: python extract_text.py <path/to/file.docx>
Output: plain text with heading level markers, printed to stdout
"""
import sys
from pathlib import Path
from docx import Document
from docx.oxml.ns import qn


def get_heading_level(paragraph) -> int | None:
    style_name = paragraph.style.name
    if style_name.startswith("Heading"):
        try:
            return int(style_name.split()[-1])
        except ValueError:
            pass
    # Also check outline level in paragraph XML
    pPr = paragraph._p.find(qn("w:pPr"))
    if pPr is not None:
        outlineLvl = pPr.find(qn("w:outlineLvl"))
        if outlineLvl is not None:
            val = outlineLvl.get(qn("w:val"))
            if val is not None:
                return int(val) + 1
    return None


def extract(path: str) -> None:
    doc = Document(path)
    lines = []
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
    print("\n".join(lines))


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python extract_text.py <path/to/file.docx>", file=sys.stderr)
        sys.exit(1)
    extract(sys.argv[1])
