"""Cover-page renderer — wraps the existing Jinja template flow.

We keep assets/cover_template.docx as the canonical cover design. This module
renders the template to a temporary .docx and returns the path; the top-level
writer (docx_writer) merges it in front of the body.
"""
from __future__ import annotations

import tempfile
from pathlib import Path

from docxtpl import DocxTemplate


ASSETS = Path(__file__).resolve().parent.parent.parent.parent / "assets"
COVER_TEMPLATE = ASSETS / "cover_template.docx"


def render_cover(title: str, client: str, period: str) -> Path:
    """Render the Jinja cover template and return the path to a temp .docx."""
    if not COVER_TEMPLATE.exists():
        raise FileNotFoundError(f"Cover template missing: {COVER_TEMPLATE}")

    tpl = DocxTemplate(str(COVER_TEMPLATE))
    tpl.render({"TITLE": title, "CLIENT": client, "PERIOD": period})

    tmp = tempfile.NamedTemporaryFile(suffix=".docx", delete=False)
    tmp.close()
    out = Path(tmp.name)
    tpl.save(str(out))
    return out
