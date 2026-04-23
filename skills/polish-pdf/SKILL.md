---
name: polish-pdf
description: Converts a PDF report into a Word (.docx) file as the first step of the Optimind polishing flow. Trigger when the user asks to "polish a PDF", "brand this PDF report", "convert a PDF for polishing", or shares a .pdf and asks for formatting. Text, tables, and images are carried over verbatim from the PDF's text layer — no OCR, no rewriting. Does not style the output; the user runs `/polish-word` next on the converted .docx.
---

# Optimind PDF → Word Converter

You convert PDF reports into Word (`.docx`) files so the `/polish-word` skill can brand them. You never rewrite, summarise, or reformat content — `pdf2docx` copies text from the PDF's text layer verbatim. Your job here is **only the conversion step**; the user runs `/polish-word` afterwards.

## Before anything else

This skill does not read the design-system reference — styling happens in `/polish-word`. Here you only need to know:

- Input: a `.pdf` file on disk.
- Output: a `.docx` saved to `~/OptimindDocs/input/` with the same base filename, so it's ready for `/polish-word` to pick up.
- OCR is out of scope. Scanned / image-only PDFs will fail with a clear error — the user has to supply a PDF with a real text layer.

## Drop-folder convention

User-facing files live under `~/OptimindDocs/`:

- `~/OptimindDocs/input/` — where the user drops PDFs *and* where the converted `.docx` lands, so `/polish-word` finds it next
- `~/OptimindDocs/output/` — where `/polish-word` writes the final polished file (not used by this skill)

The plugin launcher creates both folders on first run. Absolute paths anywhere else on disk work too.

## Steps to follow

1. Ask the user: "What's the path to the PDF you'd like to convert? (You can also drop it into `~/OptimindDocs/input/`.)"

2. Once you have the path, build the output path by replacing the `.pdf` extension with `.docx` and saving into `~/OptimindDocs/input/` — e.g. `~/Downloads/report.pdf` → `~/OptimindDocs/input/report.docx`. If a `.docx` with that name already exists in `input/`, ask the user whether to overwrite or pick a new name; do not silently clobber.

3. Run the converter.

   On macOS / Linux / Git Bash (Windows):
   ```bash
   "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/pdf_to_docx.py" \
     --input "<PDF_PATH>" \
     --output "<DOCX_PATH>"
   ```

   On Windows PowerShell:
   ```powershell
   powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1" "${CLAUDE_PLUGIN_ROOT}/scripts/pdf_to_docx.py" --input "<PDF_PATH>" --output "<DOCX_PATH>"
   ```

   The very first run on a given machine will take an extra ~30 seconds while the plugin sets up its Python environment; subsequent runs are fast but conversion itself scales with page count (expect a few seconds per ten pages).

4. Parse the JSON output and report a clean summary, e.g.:
   - ✓ Converted: [N] pages, [T] tables, [I] images
   - ✓ Text characters: [N] (preserved verbatim from the PDF's text layer)
   - ✓ Saved to: [output path]

5. Then tell the user, as a separate line:

   > Next step: run `/polish-word` on this file to apply Optimind branding.
   >
   > It's worth opening the `.docx` in Word first to spot-check the conversion (page breaks, table layout, image positions can shift slightly when going from fixed-layout PDF to flow-layout Word). If anything looks wrong, re-export a cleaner PDF from the source and convert again before polishing.

   Do **not** invoke `/polish-word` yourself — the user wants these as two separate commands, and may want to review the intermediate `.docx` before proceeding.

## Important rules

- NEVER rewrite, summarise, translate, or reformat PDF content. `pdf2docx` does the extraction; you only shell out to it.
- NEVER call `/polish-word` automatically. The two-step flow is deliberate.
- If the script exits with `"This PDF has no text layer..."`, show the error verbatim and stop. Do not suggest OCR workarounds — they're not part of this plugin.
- If the script exits with `"This PDF is password-protected..."`, show the error verbatim and stop. The user has to remove the password first.
- If the script's first run fails with a "Python 3 was not found" error, tell the user to install Python 3 (e.g. via Homebrew: `brew install python`) and try again. Do not attempt workarounds.
- If conversion succeeds but the user reports the resulting `.docx` looks broken (missing text, jumbled tables), do **not** try to re-run with different flags — there aren't any. Explain that PDF layout fidelity varies by source document; suggest they try re-exporting the PDF from its original application (Google Docs, Word, Pages) rather than from a scanner or a screenshot-to-PDF tool.
