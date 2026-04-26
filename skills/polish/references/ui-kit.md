# Optimind Docs UI Kit

The canonical design spec for Word-doc output produced by the `/polish` skill. Source of truth for tokens, text styles, frames, table variants, and callout styles.

**Figma file:** [Optimind Docs Kit](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit?node-id=2501-286) — file key `iYE9CtCoxRESvSGtTrfBhs`, page `Doc`.

All colors on canvas MUST resolve through Semantic Color variables. Text MUST use named text styles. No hardcoded hex values on canvas.

---

## Colors

### Semantic tokens (used in the docx output)

| Token | Hex | Variable ID | Role |
|---|---|---|---|
| brand | `#F52C39` | `VariableID:2503:3` | Accent red — H1 rules, table headers (Classic), brand callout label |
| text/primary | `#000000` | `VariableID:2503:4` | Body text on light bg |
| text/secondary | `#626567` | `VariableID:2503:5` | Muted body, captions, disclaimer, table cells |
| text/on-brand | `#FFFFFF` | `VariableID:2503:6` | Text on red fills (Classic table header) |
| bg/page | `#FFFFFF` | `VariableID:2503:7` | Page background |
| bg/subtle | `#F2F3F4` | `VariableID:2503:8` | Alt rows, Next Steps callout bg |
| bg/brand-subtle | `#FEECEE` | (Red/50 alias) | Key Insight callout bg |
| border/default | `#E5E7E9` | `VariableID:2503:9` | Row dividers, light separators |
| border/strong | `#D7DBDD` | `VariableID:2503:10` | H1 underline, Minimal table top rule |
| bg/dark | — | `VariableID:2524:17` | Reserved for dark-surface use cases |

### Primitive ramp (hidden from canvas — `scopes=[]`)

Red 50–600, Neutral 50–950, White, Black. Semantic tokens alias these.

---

## Text styles (10 total — Poppins)

| Style | Weight / Size | Extra | Used for |
|---|---|---|---|
| Titles/Cover | Bold, 40pt | — | Cover title |
| Titles/Main | Bold, 16pt | — | H1 (body sections) |
| Titles/Sub | Bold, 13pt | — | H2 |
| Titles/Table | Bold, 9pt | — | Table column headers (Classic) |
| Text/Cover | Regular, 12pt | — | Cover body copy |
| Text/Main | Regular, 10pt | line-height 1.5 | Body paragraphs |
| Text/Table | Regular, 9pt | line-height 1.25 | Table cell body |
| Text/Disclaimer | Regular, 8pt | — | Footer confidentiality, captions, footnotes |
| Labels/Cover | SemiBold, 11pt | letter-spacing 1.32px | Cover meta labels |
| Labels/Main | SemiBold, 11pt | — | Header title, callout label, section label, action card number, comparison panel title |

Labels use **default casing** — no uppercase transform. Source text casing is always preserved as-is. The `w:caps` property is not applied to any style.

---

## Key frames (Doc page)

| Frame | ID |
|---|---|
| Cover | `2501:287` |
| Styled Elements | `2501:381` |
| Typography handoff | `2501:656` |
| Colors handoff | `2501:677` |
| Docx Demo (Classic / red-header style) | `2550:17` |
| Docx Demo — All Styles (Minimal / rule-based) | `2577:17` |

The DS-Extender agent anchors new components to the right of node `2501:286` on page `Doc`.

---

## Table variants

### Classic — `2550:17` (default)

- Header row fill: `brand` (red `#F52C39`)
- Header text: `text/on-brand` (white), Titles/Table (Bold 10pt)
- Body rows: alternating `bg/page` / `bg/subtle`
- No outer borders; bottom-only divider in `border/default` on last row
- First column left-aligned, remaining columns centered
- Cell padding: 6pt top/bottom, 8pt left/right

---

## Callout styles

Both variants render as a borderless single-cell table (no visible cell borders) with full-width fill. Label is rendered with default casing as-is from the source text.

### Key Insight (brand)

- Background: `bg/brand-subtle` `#FEECEE`
- Label color: `brand` red, Labels/Main (SemiBold 11pt)
- Body color: `text/primary` black, Text/Main (Regular 10pt)
- Vertical padding: 16pt top/bottom, 18pt left/right

### Next Steps (subtle)

- Background: `bg/subtle` `#F2F3F4`
- Label color: `text/primary` black, Labels/Main (SemiBold 11pt)
- Body color: `text/secondary` `#626567`, Text/Main (Regular 10pt)
- Vertical padding: 14pt top/bottom, 18pt left/right

Detection rule: callouts are identified by paragraph shading in the source doc. The shade color dictates the variant — `#FEECEE`/`#FEE`/`#FFE5E5`/`#FDDDE0` → brand; any other non-white shade → subtle.

---

## Header & footer (body pages, not cover)

**Header** — left-aligned line with the document title in Labels/Main style (SemiBold 11pt, `text/secondary`). Right tab stop with `PAGE <field>` in the same style. No bottom border on header — conflicts with H1 dividers near page top.

**Footer** — confidentiality disclaimer left-aligned in Text/Disclaimer (Regular 8pt, `text/secondary`). No top border.

**First page** — `different_first_page_header_footer = True`; cover has neither header nor footer.

---

## H1 divider rule

A single-pixel bottom border in `border/strong` is applied to the paragraph **preceding** each H1, with ~6pt space below the rule. Placing the border on the *previous* paragraph keeps the rule above the H1 regardless of page breaks — no clash with page-boundary lines.

---

## H3 heading

- Style: Poppins Bold, 11pt, `text/primary` (`#000000`)
- Space before: 18pt, space after: 6pt, line-height 1.5
- No divider rule (H1 only)
- Use for sub-section titles within an H2 section

---

## Body paragraph

- Style: Text/Main — Poppins Regular, 11pt, `text/secondary` (`#626567`), line-height 1.5
- Space before: 0pt, space after: 8pt
- Inline **bold** uses Poppins Bold (weight 700), same size/color
- Inline *italic* uses Poppins Italic, same size/color
- Never mutate source text case — apply `w:b` / `w:i` run properties only

---

## Lists

### Bulleted list

- Bullet characters: `•` level 0, `◦` level 1, `▸` level 2
- Font: Poppins Regular, 11pt, `text/primary`
- No paragraph indent — glyph sits at left margin, tab stop at 200 twips snaps text start
- Hanging: 200 twips; body text starts at 200 twips (~0.14 in); nesting adds 240 twips per level
- Space before: 0pt, space after: 4pt per item

### Numbered list

- Format: `1.`, `2.`, `3.` (decimal, followed by period + tab)
- Font: Poppins Regular, 11pt, `text/primary`
- Same indent geometry as bulleted list — glyph column 16px keeps "4." from overflowing
- Nested levels restart numbering from `1.`

---

## Callout styles (complete set)

Both brand and subtle variants render as a borderless single-cell table with full-width fill. Label is rendered with default casing as-is from the source text.

### Key Insight (brand)
- Background: `bg/brand-subtle` `#FEECEE`
- Label color: `brand` red `#F52C39`, Labels/Main (SemiBold 11pt)
- Body color: `text/primary` black, Text/Main (Regular 10pt)
- Padding: 16pt top/bottom, 18pt left/right

### Next Steps (subtle)
- Background: `bg/subtle` `#F2F3F4`
- Label color: `text/primary` black, Labels/Main (SemiBold 11pt)
- Body color: `text/secondary` `#626567`, Text/Main (Regular 10pt)
- Padding: 14pt top/bottom, 18pt left/right

### Warning (brand — same fill as Key Insight)
- Background: `bg/brand-subtle` `#FEECEE`
- Label color: `brand` red `#F52C39`, Labels/Main (SemiBold 11pt)
- Body color: `text/primary` black, Text/Main (Regular 10pt)
- Padding: 16pt top/bottom, 18pt left/right
- Detection: paragraph with shading `#FEECEE` / `#FEE` / `#FFE5E5` and label starting with "WARNING" or "CAUTION"

### Note (subtle — same fill as Next Steps)
- Background: `bg/subtle` `#F2F3F4`
- Label color: `text/secondary` `#626567`, Labels/Main (SemiBold 11pt)
- Body color: `text/secondary` `#626567`, Text/Main (Regular 10pt)
- Padding: 14pt top/bottom, 18pt left/right
- Detection: paragraph with any non-white/non-brand shading and label starting with "NOTE" or "TIP"

**Detection rule summary:** shade color `#FEECEE`/`#FEE`/`#FFE5E5`/`#FDDDE0` → brand (Key Insight or Warning); any other non-white shade → subtle (Next Steps or Note). Classifier inspects the label text to choose between the two brand variants and the two subtle variants.

---

## Section label

Numbered section divider appearing before major H1 sections in PDF-sourced documents (e.g. "01 — OVERVIEW").

- Style: Labels/Main — Poppins SemiBold, 11pt, `text/secondary` (#626567)
- Letter-spacing: 1.2px
- Space before: 24pt, space after: 2pt, line-height 1.0
- Format: `"NN — SECTION NAME"` if number present, else just the text
- No divider rule, no border

---

## Action card

Numbered recommendation card. Appears in recommendation sections of polished reports (e.g. "April 2026 Recommendations").

- **Number + title** (single paragraph):
  - Number: Poppins SemiBold 10pt, brand red (#F52C39), UPPER via `w:caps`
  - Title: Poppins Bold 11pt, `text/primary`, same paragraph
  - Left paragraph border: ~2.25pt solid brand red (#F52C39)
  - Space before: 12pt, space after: 3pt
- **Body** (next paragraph, same left border):
  - Poppins Regular 11pt, `text/secondary` (#626567)
  - Left indent: 360 twips (matches the number/title)
  - Space before: 0, space after: 8pt, line-height 1.3

---

## Comparison panel

Two-column layout panel for "What Worked / What Needs Improvement" sections.

- Rendered as a 1-row, 2-column borderless table at 100% page width
- **Left column** (positive / "what worked"):
  - Fill: `bg/brand-subtle` (#FEECEE)
  - Label: brand red (#F52C39), Labels/Main (SemiBold 11pt), space after 6pt
  - Items: `•` bullets, Poppins Regular 11pt, `text/primary`, space after 3pt per item
  - Padding: 14pt all sides
- **Right column** (negative / "what needs improvement"):
  - Fill: `bg/subtle` (#F2F3F4)
  - Label: `text/primary` (#000000), Labels/Main (SemiBold 11pt), space after 6pt
  - Items: `•` bullets, Poppins Regular 11pt, `text/primary`, space after 3pt per item
  - Padding: 14pt all sides
- No outer borders, no dividers between cells

---

## Table status badge cells

Tables from performance reports often contain short sentiment labels in body cells (e.g. "Strong", "Average", "Top Performer"). These render as **bold text** in the cell with color by sentiment:

- **Positive** (`"Strong"`, `"Top Performer"`, `"Good"`, `"Excellent CTR"`, `"Best in program"`, `"Scale up"`, `"Top Opener"`): bold, `text/primary` (#000000)
- **Negative** (`"Underperforming"`, `"Low open rate"`): bold, `brand` red (#F52C39)
- **Neutral** (`"Average"`, `"Solid"`, `"Core market"`, `"Increase volume"`, `"Mixed"`): bold, `text/secondary` (#626567)

Detection: strip and lowercase the full cell text; if it exactly matches a badge word from the set above, apply badge styling. Otherwise render as normal body cell.

---

## Images and charts (v0.5 omission policy)

In v0.5, **all `figure` and `chart` blocks are intentionally omitted from the output `.docx`**. They are parsed and classified normally but not rendered. Each omitted block is logged in `state.warnings` and appears in the HTML report under "Omitted Blocks".

- The Auditor must **not** flag missing figures/charts as content-preservation failures.
- The Renderer-QA must **not** fail or retry due to absent figure/chart blocks.
- The Python `verify` stage excludes figure/chart word counts from its content-preservation check.
- If > 30% of source blocks are figure/chart, both Auditor and Renderer-QA should emit a note so the user can review the HTML report.

---

## Rules of thumb for the polisher

1. **Never mutate source text.** Apply bold/italic via run properties only. No case transforms — render text exactly as it appears in the source document.
2. **Font is Poppins everywhere**, including fallbacks (`w:ascii`, `w:hAnsi`, `w:cs`).
3. **Strip RTL (`w:rtl`) markers** from runs to prevent number/punctuation reordering in mixed-direction docs.
4. **Empty paragraphs collapse to 0pt before/after** and exact 1.0-line height, so they don't create phantom dividers.
5. **List paragraphs** get tight normalised indent: left = `360 + ilvl*360` twips, hanging = `180` twips.
6. **VML horizontal rules** from the source (decorative dividers) get stripped — we replace them with our own H1 border.
7. Cover detection priority: explicit page break → first numbered H1 → tiny-doc fallback.
8. Table-variant detection: `Classic` is the default; `Minimal` is an opt-in choice.

---

## Implementation mirror

These tokens are mirrored in [scripts/polish/render/tokens.py](../../../scripts/polish/render/tokens.py) as the single source of truth the renderer consumes:

```
T.RED        = RGBColor(0xF5, 0x2C, 0x39)  # brand
T.TEXT_PRI   = RGBColor(0x00, 0x00, 0x00)  # text/primary
T.TEXT_SEC   = RGBColor(0x62, 0x65, 0x67)  # text/secondary
T.BG_SUBTLE  = RGBColor(0xF2, 0xF3, 0xF4)  # bg/subtle
T.BG_BRAND   = RGBColor(0xFE, 0xEC, 0xEE)  # bg/brand-subtle
T.BORDER_DEF = RGBColor(0xE5, 0xE7, 0xE9)  # border/default
T.BORDER_STR = RGBColor(0xD7, 0xDB, 0xDD)  # border/strong
T.WHITE      = RGBColor(0xFF, 0xFF, 0xFF)  # text/on-brand, bg/page
```

## Runtime extensions

When the DS-Extender subagent designs a new component at polish time, its tokens are written to [scripts/polish/render/tokens_extensions.json](../../../scripts/polish/render/tokens_extensions.json) and the corresponding renderer lands in [scripts/polish/render/dynamic/](../../../scripts/polish/render/dynamic/). `tokens.py` merges the extension tokens into its namespace at import, so generated renderers can reference them as `T.<TOKEN>` like any built-in. New components are added to the sections above on promotion — they should feel native, not bolted-on.

If a Figma token changes, update both this document and `tokens.py`. Runtime extensions keep the Figma round-trip honest: every extension records the Figma `node_id` of the materialized component, linked from the `.report.html` sidecar.
