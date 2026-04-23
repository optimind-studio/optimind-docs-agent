# Optimind Docs UI Kit

The canonical design spec for Word-doc output produced by the `/polish-word` skill. Source of truth for tokens, text styles, frames, table variants, and callout styles.

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
| Titles/Sub | Bold, 12pt | — | H2 |
| Titles/Table | Bold, 10pt | — | Table column headers (Classic) |
| Text/Cover | Regular, 12pt | — | Cover body copy |
| Text/Main | Regular, 11pt | line-height 1.5 | Body paragraphs |
| Text/Table | Regular, 10pt | line-height 1.25 | Table cell body |
| Text/Disclaimer | Regular, 9pt | — | Footer confidentiality, captions, footnotes |
| Labels/Cover | SemiBold, 11pt | letter-spacing 1.32px, UPPER | Cover meta labels ("CLIENT", "REPORTING PERIOD") |
| Labels/Main | SemiBold, 10pt | letter-spacing 1.2px, UPPER | Header title, Minimal table header, callout label |

All labels that are "UPPER" should be rendered uppercase **via display (CSS text-transform / Word `w:caps`), not by mutating source text.**

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

---

## Table variants

### Classic — `2550:17` (default)

- Header row fill: `brand` (red `#F52C39`)
- Header text: `text/on-brand` (white), Titles/Table (Bold 10pt)
- Body rows: alternating `bg/page` / `bg/subtle`
- No outer borders; bottom-only divider in `border/default` on last row
- First column left-aligned, remaining columns centered
- Cell padding: ~100 twips vertical, ~120 twips horizontal

### Minimal — `2577:17`

- No fills anywhere
- Top rule + header-bottom rule + final-row bottom rule in `border/strong`
- Row dividers in `border/default`
- Header: Labels/Main (SemiBold 10pt, `text/secondary`, UPPER, tracking 1.2px)
- Numeric columns right-aligned, label columns left-aligned
- Use for dense numeric comparison tables

---

## Callout styles

Both variants render as a borderless single-cell table (no visible cell borders) with full-width fill. Label is display-uppercase via `w:caps` — never mutate source text.

### Key Insight (brand)

- Background: `bg/brand-subtle` `#FEECEE`
- Label color: `brand` red, Labels/Main (SemiBold 10pt, UPPER, tracking 1.2px)
- Body color: `text/primary` black, Text/Main (Regular 11pt)
- Vertical padding: 16pt top/bottom, 18pt left/right

### Next Steps (subtle)

- Background: `bg/subtle` `#F2F3F4`
- Label color: `text/primary` black, Labels/Main (SemiBold 10pt, UPPER, tracking 1.2px)
- Body color: `text/secondary` `#626567`, Text/Main (Regular 11pt)
- Vertical padding: 14pt top/bottom, 18pt left/right

Detection rule: callouts are identified by paragraph shading in the source doc. The shade color dictates the variant — `#FEECEE`/`#FEE`/`#FFE5E5`/`#FDDDE0` → brand; any other non-white shade → subtle.

---

## Header & footer (body pages, not cover)

**Header** — left-aligned line with the document title in Labels/Main style (SemiBold 10pt, `text/secondary`, UPPER, letter-spacing 1.2pt). Right tab stop with `PAGE <field>` in the same style. No bottom border on header — conflicts with H1 dividers near page top.

**Footer** — confidentiality disclaimer left-aligned in Text/Disclaimer (Regular 9pt, `text/secondary`). No top border.

**First page** — `different_first_page_header_footer = True`; cover has neither header nor footer.

---

## H1 divider rule

A single-pixel bottom border in `border/strong` is applied to the paragraph **preceding** each H1, with ~6pt space below the rule. Placing the border on the *previous* paragraph keeps the rule above the H1 regardless of page breaks — no clash with page-boundary lines.

---

## Rules of thumb for the polisher

1. **Never mutate source text.** Uppercase / small-caps / case transforms must use `w:caps` on the run properties, not `str.upper()` on the text.
2. **Font is Poppins everywhere**, including fallbacks (`w:ascii`, `w:hAnsi`, `w:cs`).
3. **Strip RTL (`w:rtl`) markers** from runs to prevent number/punctuation reordering in mixed-direction docs.
4. **Empty paragraphs collapse to 0pt before/after** and exact 1.0-line height, so they don't create phantom dividers.
5. **List paragraphs** get tight normalised indent: left = `360 + ilvl*360` twips, hanging = `180` twips.
6. **VML horizontal rules** from the source (decorative dividers) get stripped — we replace them with our own H1 border.
7. Cover detection priority: explicit page break → first numbered H1 → tiny-doc fallback.
8. Table-variant detection: `Classic` is the default; `Minimal` is an opt-in choice (pass `--table-style minimal` or `auto`).

---

## Implementation mirror

These tokens are mirrored in [scripts/polish_doc.py](scripts/polish_doc.py) as hardcoded `RGBColor` constants:

```
RED        = RGBColor(0xF5, 0x2C, 0x39)  # brand
TEXT_PRI   = RGBColor(0x00, 0x00, 0x00)  # text/primary
TEXT_SEC   = RGBColor(0x62, 0x65, 0x67)  # text/secondary
BG_SUBTLE  = RGBColor(0xF2, 0xF3, 0xF4)  # bg/subtle
BG_BRAND   = RGBColor(0xFE, 0xEC, 0xEE)  # bg/brand-subtle
BORDER_DEF = RGBColor(0xE5, 0xE7, 0xE9)  # border/default
BORDER_STR = RGBColor(0xD7, 0xDB, 0xDD)  # border/strong
WHITE      = RGBColor(0xFF, 0xFF, 0xFF)  # text/on-brand, bg/page
```

If a Figma token changes, update both this document and the constants above.
