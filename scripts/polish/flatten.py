"""Flatten — de-anchor shapes, dissolve nested tables, drop VML rules.

Input:  iterable of tokens from ingest.*
Output: iterator of tokens with:
  - VML hr paragraphs dropped
  - Floating text-boxes lifted to inline paragraph tokens (source order preserved)
  - Floating images lifted to new image tokens
  - Nested tables lifted to standalone table tokens after their host table
  - Empty paragraphs with no text, images, or shapes dropped
"""
from __future__ import annotations

from typing import Iterable, Iterator


def flatten(tokens: Iterable[dict]) -> Iterator[dict]:
    out: list[dict] = []
    counter = 0
    # Each paragraph in the source yields one spatial-group id. Lifted shapes
    # from the same paragraph share that id so `reconstruct` can cluster them
    # together. Paragraphs with no floating content don't need a group.
    group_counter = 0
    for tok in tokens:
        kind = tok.get("kind")
        if kind == "paragraph":
            if tok.get("is_vml_hr"):
                continue
            # Pull floating shapes and inline images out before emitting
            floats = tok.get("floating_shapes") or []
            inlines = tok.get("inline_images") or []
            tok["floating_shapes"] = []
            tok["inline_images"] = []
            has_text = bool((tok.get("text") or "").strip())
            tok["source_index"] = counter

            group_id = None
            if floats or inlines:
                group_id = group_counter
                group_counter += 1

            # Keep the paragraph only if it carries real text (or we need it
            # as an anchor for an inline image with no text)
            if has_text:
                tok["spatial_group"] = group_id  # may be None when no floats
                out.append(tok)
                counter += 1

            # Promote each inline image to its own image token
            for img in inlines:
                lifted = _image_to_token(img, counter, group_id)
                if lifted is not None:
                    out.append(lifted)
                    counter += 1

            # Emit each floating shape (textbox or image) as its own token
            for shape in floats:
                lifted = _shape_to_token(shape, counter, group_id)
                if lifted is not None:
                    out.append(lifted)
                    counter += 1
        elif kind == "table":
            # Lift nested tables to siblings
            nested_queue: list[dict] = []
            _collect_nested(tok, nested_queue)
            tok["source_index"] = counter
            counter += 1
            out.append(tok)
            for nt in nested_queue:
                nt["is_nested"] = False
                nt["source_index"] = counter
                counter += 1
                out.append(nt)
        else:
            tok["source_index"] = counter
            counter += 1
            out.append(tok)
    yield from out


def _paragraph_has_content(tok: dict) -> bool:
    if tok.get("text", "").strip():
        return True
    if tok.get("inline_images"):
        return True
    if tok.get("has_page_break"):
        return False  # page breaks without content add nothing in our rebuild
    return False


def _image_to_token(img: dict, source_index: int, group_id: int | None) -> dict | None:
    blob = img.get("bytes")
    if not blob:
        return None
    return {
        "kind": "image",
        "source_index": source_index,
        "image_bytes": blob,
        "image_format": img.get("format", "png"),
        "lifted_from": "inline_image",
        "spatial_group": group_id,
        "anchor_x": None,
        "anchor_y": None,
        "anchor_cx": img.get("anchor_cx"),
        "anchor_cy": img.get("anchor_cy"),
    }


def _shape_to_token(shape: dict, source_index: int, group_id: int | None) -> dict | None:
    """Convert a lifted floating shape into a standalone token.

    Anchor position (`anchor_x`, `anchor_y`) and extent (`anchor_cx`,
    `anchor_cy`) in EMU are preserved for downstream reconstruct.
    """
    if shape.get("kind") == "textbox":
        text = shape.get("text", "").strip()
        if not text:
            return None
        return {
            "kind": "paragraph",
            "source_index": source_index,
            "text": text,
            "runs": [{"text": text, "bold": False, "italic": False}],
            "style_name": "",
            "heading_level_hint": None,
            "shading_hex": None,
            "numbering": None,
            "has_page_break": False,
            "inline_images": [],
            "floating_shapes": [],
            "is_vml_hr": False,
            "element": None,
            "lifted_from": "floating_textbox",
            "spatial_group": group_id,
            "anchor_x": shape.get("anchor_x"),
            "anchor_y": shape.get("anchor_y"),
            "anchor_cx": shape.get("anchor_cx"),
            "anchor_cy": shape.get("anchor_cy"),
            "anchor_relH": shape.get("anchor_relH"),
            "anchor_relV": shape.get("anchor_relV"),
        }
    if shape.get("kind") == "image":
        return {
            "kind": "image",
            "source_index": source_index,
            "image_bytes": shape.get("bytes"),
            "image_format": shape.get("format", "png"),
            "lifted_from": "floating_image",
            "spatial_group": group_id,
            "anchor_x": shape.get("anchor_x"),
            "anchor_y": shape.get("anchor_y"),
            "anchor_cx": shape.get("anchor_cx"),
            "anchor_cy": shape.get("anchor_cy"),
        }
    return None


def _collect_nested(table_tok: dict, out: list[dict]) -> None:
    """Walk table cells, pull out any nested tables into `out`, and mark their
    host cell so renderers know to skip (or show a placeholder)."""
    for row in table_tok.get("rows") or []:
        for cell in row:
            nested = cell.get("nested_tables") or []
            if nested:
                out.extend(nested)
                cell["nested_tables"] = []    # detach — they now live as siblings
