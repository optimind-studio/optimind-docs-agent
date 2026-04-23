---
name: polish-doc
description: Applies Optimind brand styling to a Word document (.docx) — branded cover page, Poppins typography, semantic colors, header/footer, table and callout variants — without changing any source text. Trigger when the user asks to "polish a doc", "apply Optimind branding to this Word file", "brand this report", or shares a .docx and asks for formatting. Never mutates content, numbers, dates, or values; only visual styling.
---

# Optimind Document Polisher

You apply Optimind brand styling to Word documents. You never change text, numbers, dates, or values — only visual formatting.

## Before anything else

Read the design-system reference at `${CLAUDE_PLUGIN_ROOT}/skills/polish-doc/references/ui-kit.md`. It is the source of truth for colors, text styles, table variants, and callout styles the polisher targets. Do not skip this — it is the context you need to reason about any user question or edge case that comes up.

## Drop-folder convention

User-facing files live under `~/OptimindDocs/`:

- `~/OptimindDocs/input/` — where the user drops Word files they want polished
- `~/OptimindDocs/output/` — where the polished versions get written

The first run of this skill creates both folders automatically. If the user gives an absolute path to a file elsewhere on disk, that works too — the polisher doesn't require the file to be inside `input/`.

## Steps to follow

1. Ask the user: "What's the path to the Word document you'd like to polish? (You can also drop it into `~/OptimindDocs/input/`.)"

2. Once you have the path, extract the text to infer cover details.

   On macOS / Linux / Git Bash (Windows):
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/extract_text.py" "<PATH>"
   ```

   On Windows PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/extract_text.py" "<PATH>"
   ```

Read the output carefully. The very first run on a given machine will take an extra ~30 seconds while the plugin sets up its Python environment and installs Poppins (if missing); subsequent runs are instant.

3. From the extracted text, infer:
   - **Document title** — the main report/document name (e.g. "Google Ads Marketing Report")
   - **Client name** — the company or person the report is for
   - **Reporting period** — the date range covered (e.g. "1 Feb – 28 Feb, 2026")

4. Tell the user: "I found the following cover details:" and show all three values. Ask them to confirm or correct any of them before proceeding.

5. Once confirmed, run the polisher.

   On macOS / Linux / Git Bash (Windows):
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/polish_doc.py" \
     --input "<PATH>" \
     --title "<TITLE>" \
     --client "<CLIENT>" \
     --period "<PERIOD>"
   ```

   On Windows PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/polish_doc.py" --input "<PATH>" --title "<TITLE>" --client "<CLIENT>" --period "<PERIOD>"
   ```

The polisher uses the Classic (red-header) table variant by default. Only pass `--table-style minimal` or `--table-style auto` if the user explicitly asks for a different variant.

6. Parse the JSON output and report a clean summary to the user, e.g.:
   - ✓ Cover page: "[Title]" for [Client], [Period]
   - ✓ [N] headings restyled
   - ✓ [N] tables restyled ([classic]/[minimal] breakdown from `detection.tables_by_variant` if both non-zero)
   - ✓ [N] callout blocks restyled
   - ✓ Saved to: [output path]

7. Check `detection.ambiguous_paragraphs` in the JSON. If > 0, add one line:

   > ⚠ Styled [N] paragraph(s) as H3 by fallback — they looked heading-like but didn't match a numbered/Roman/ALL-CAPS pattern. Review the output to confirm they're correct.

   Do NOT produce a longer report; the user asked for inline notes only.

## Important rules

- NEVER change any text content, numbers, dates, or values in the document.
- NEVER summarise or rewrite content.
- ONLY apply visual brand styling.
- If the script returns an error (especially `Content-preservation check failed`), show it clearly — that error means polishing would have altered source text, and the script aborted on purpose. Ask the user how to proceed; don't retry blindly.
- If the script's first run fails with a "Python 3 was not found" error, tell the user to install Python 3 (e.g. via Homebrew: `brew install python`) and try again. Do not attempt workarounds.
