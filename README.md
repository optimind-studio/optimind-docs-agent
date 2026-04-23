# Optimind Docs

Apply Optimind brand styling to Word documents — branded cover page, Poppins typography, semantic colors, header/footer, table and callout variants — without changing any source content. PDFs are handled too, via a separate convert-first step.

> **What's new in 0.3.0**
> — `/polish-doc` has been renamed to **`/polish-word`** for symmetry. If you had muscle memory for the old command, use the new one.
> — New skill **`/polish-pdf`** converts a PDF into a `.docx` so you can then run `/polish-word` on it. Two explicit commands, one per input type. No auto-chain — you review the converted `.docx` before polishing.

## What this plugin does

When installed, this plugin gives Claude **two** skills:

- **`/polish-word`** — takes a `.docx` and applies Optimind brand styling. You can type the slash command or ask Claude in plain English ("polish a Word doc", "apply Optimind branding to this report").
- **`/polish-pdf`** — takes a `.pdf`, converts it to a `.docx` (carrying text, tables, and images over from the PDF's text layer verbatim), and saves it to `~/OptimindDocs/input/` so `/polish-word` can pick it up as the next step.

**Word flow** (`/polish-word`):
1. Read your `.docx` file.
2. Infer the document title, client, and reporting period and ask you to confirm them.
3. Produce a branded copy — new cover page, consistent typography, styled headings, tables, and callouts — saved to `~/OptimindDocs/output/`.

**PDF flow** (`/polish-pdf` → `/polish-word`):
1. Convert PDF → `.docx`. Output lands in `~/OptimindDocs/input/`.
2. Open it in Word to spot-check — PDF layout doesn't always survive the conversion cleanly (page breaks, table lines, image anchors can shift).
3. Run `/polish-word` on the converted file to apply the Optimind styling.

**Source text is never altered.** The Word polisher verifies content preservation before saving, and aborts if anything it was about to write would change the underlying text, numbers, or dates. The PDF converter does no rewriting — it copies text straight from the PDF text layer.

**No OCR.** `/polish-pdf` needs a PDF with a real text layer. Scanned documents and image-only PDFs will fail with a clear error — re-export from the source application, or OCR the PDF first with a dedicated tool.

## Installation

### Where this works

This plugin is a **Claude Code plugin**, so it only loads in surfaces that consume the Claude Code plugin system:

- **Claude Code** (CLI, Desktop, or IDE extension) — ✅ supported
- **Claude Cowork** — ✅ supported
- **Claude.ai web chat** — ❌ not supported (claude.ai doesn't load Claude Code plugins). The skill will not appear there.

### Option A — Install from this GitHub marketplace (recommended)

Run these **two** commands, in order, inside Claude Code / Cowork:

```
/plugin marketplace add lqxdesign/optimind-docs_polisher-agent
/plugin install optimind-docs@optimind
```

| Step | What it does |
| :--- | :--- |
| `/plugin marketplace add …` | Registers the catalog (one-time). On its own, this does **not** install anything — it only tells Claude where the plugin lives. |
| `/plugin install optimind-docs@optimind` | Installs the `optimind-docs` plugin from the registered marketplace. |

> Claude Code's plugin system is a two-step flow by design (add marketplace → install plugin). There is no single-command shortcut for third-party marketplaces; the `claude plugin install name@claude-plugins-official` pattern only works for Anthropic's official auto-loaded marketplace.

After install, **restart Claude Code** so the skills are picked up. Confirm they're there by opening `/plugin` → **Installed** tab, or by typing `/` and looking for `polish-word` and `polish-pdf` in the slash-command picker.

Pull later updates:

```
/plugin marketplace update optimind
```

Restart Claude Code after updating. It will refresh to the latest version on the repo's `main` branch.

### Option B — Install from `.plugin` file (offline / blocked networks)

1. Grab the latest `optimind-docs.plugin` from the repo's [Releases page](../../releases).
2. Claude Desktop → **Settings → Plugins → Install from file** → pick the downloaded file.
3. Restart Claude Code.

Once installed, the `/polish-word` and `/polish-pdf` skills are available.

### Requirements

- **macOS, Windows, or Linux.**
- **Python 3.**
  - **Windows: nothing to install.** On first run, the plugin silently downloads Python 3.12 from python.org and does a per-user install (no admin required). Takes ~1–2 minutes on first run. If you already have Python 3 installed, it's detected and reused.
  - **macOS:** usually preinstalled. If not, `brew install python`.
  - **Linux:** use your package manager, e.g. `sudo apt install python3 python3-venv`.

That's it. On first run the plugin:

1. (Windows only, if needed) downloads and silently installs Python 3.12 from python.org — per-user, no admin required.
2. Creates its own isolated Python environment and installs its libraries (`python-docx`, `docxtpl`, `lxml`, `pdf2docx`) — takes ~30 seconds.
3. Installs the **Poppins** font family into your user font folder **only if it's not already on your system** (checked across `~/Library/Fonts`, `/Library/Fonts`, and `/System/Library/Fonts` on macOS; `%LOCALAPPDATA%\Microsoft\Windows\Fonts` and `C:\Windows\Fonts` on Windows; `~/.local/share/fonts` and `/usr/share/fonts` on Linux). No admin rights needed.

Every run after that is instant (conversion itself scales with PDF page count, a few seconds per ten pages).

## How to use

### Polishing a Word file

1. In Claude, say something like:
   - "Polish this Word doc."
   - "Apply Optimind branding to `~/OptimindDocs/input/report.docx`."
   - "Brand the Google Ads report for MDC Group."
   - Or run `/polish-word` directly.

2. Claude will ask for the file path (or read it from `~/OptimindDocs/input/` if you've dropped one there) and confirm the cover details with you.

3. The polished file is written to `~/OptimindDocs/output/` with the same filename as the input.

### Polishing a PDF

PDFs go through a two-step flow — convert first, then polish. This is deliberate: PDF-to-Word conversion isn't perfect (layouts can shift), so you get to review the intermediate `.docx` before the branding pass locks it in.

1. Run `/polish-pdf` (or say "polish this PDF" / "convert this PDF for polishing"). Claude asks for the PDF path, or pulls one from `~/OptimindDocs/input/`.

2. The converter produces a `.docx` in `~/OptimindDocs/input/` with the same base filename and prints a summary:
   ```
   ✓ Converted: 12 pages, 3 tables, 2 images
   ✓ Saved to: ~/OptimindDocs/input/report.docx
   ```

3. Open that `.docx` in Microsoft Word and spot-check it — headings, data tables, anywhere numbers show up. If the conversion mangled something, re-export the source PDF more cleanly (ideally from the original app — Google Docs, Word, Pages — rather than from a scan or screenshot tool) and try again.

4. Once you're happy, run `/polish-word` on the converted file. The final branded output lands in `~/OptimindDocs/output/`.

**What won't work:** scanned or image-only PDFs. The plugin does not do OCR. `/polish-pdf` detects a missing text layer and exits with a clear error. Password-protected PDFs are also rejected — remove the password (e.g. open in Preview and re-export) first.

### Folder convention

```
~/OptimindDocs/
  ├── input/    ← drop Word files and PDFs here; converted .docx lands here too
  └── output/   ← polished copies appear here
```

Both folders are created the first time the plugin runs. You can also pass an absolute path to a file anywhere on disk — the input folder is a convenience, not a requirement.

Set the environment variable `OPTIMIND_DOCS_OUTPUT` to override the output location if you want polished files saved elsewhere.

## Table variants

The polisher ships with two table styles from the Optimind design system:

- **Classic** (default) — red header row, alternating zebra rows.
- **Minimal** — rule-based, no fills. Best for dense numeric comparison tables.

Ask Claude to use `--table-style minimal` or `--table-style auto` if you want a different variant. `auto` picks Minimal for mostly-numeric tables and Classic otherwise.

## What's inside the plugin

```
.
├── .claude-plugin/
│   ├── plugin.json                   ← plugin manifest
│   └── marketplace.json              ← marketplace catalog
├── skills/
│   ├── polish-word/
│   │   ├── SKILL.md                  ← the Word polisher workflow Claude follows
│   │   └── references/ui-kit.md      ← the design-system spec (colors, type, variants)
│   └── polish-pdf/
│       └── SKILL.md                  ← the PDF → Word converter workflow
├── scripts/
│   ├── polish_doc.py                 ← the core Word polisher
│   ├── pdf_to_docx.py                ← PDF → .docx converter (pdf2docx + PyMuPDF)
│   ├── extract_text.py               ← pulls cover details from a source .docx
│   ├── install_fonts.py              ← cross-platform Poppins installer (skip-if-exists)
│   ├── run.sh                        ← launcher (macOS / Linux / Git Bash)
│   ├── run.ps1                       ← launcher (Windows PowerShell)
│   └── requirements.txt
├── assets/
│   ├── cover_template.docx           ← Jinja template for the cover page
│   └── fonts/                        ← bundled Poppins (Regular / Bold / SemiBold)
├── README.md                         ← this file (end-user install + usage)
├── DEVELOPMENT.md                    ← maintainer notes
└── LICENSE
```

Contributors: see [DEVELOPMENT.md](DEVELOPMENT.md) for the edit / test / release flow.

## Design system source of truth

Colors, fonts, and spacing in the output all come from the Optimind Docs Kit Figma file:

- File: [Optimind Docs Kit](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit)
- Page: `Doc`

If tokens change in Figma, update both `skills/polish-word/references/ui-kit.md` and the matching `RGBColor` constants at the top of `scripts/polish_doc.py`.

## Troubleshooting

**"Python 3 was not found on this machine."**
The plugin couldn't locate `python3`. Install Python 3 (`brew install python` or download from [python.org](https://www.python.org/downloads/)) and try again.

**"Content-preservation check failed."**
The Word polisher detected that it was about to write a file whose text differed from the input. This is a safety guard — the script aborted on purpose. Re-ask Claude to run it, and if it keeps failing, open an issue with the input document (content stays local; don't share sensitive files).

**"This PDF has no text layer — it looks scanned or image-only."**
`/polish-pdf` cannot extract text from image-only PDFs (scans, photos of printed pages, PDFs exported from screenshot tools). The plugin does not do OCR. Fix: re-export the PDF from the original application (Google Docs, Word, Pages, the dashboard that generated the report), or OCR it first with a dedicated tool, then run `/polish-pdf` again.

**"This PDF is password-protected."**
`/polish-pdf` refuses encrypted PDFs. Open it in Preview (macOS) or Adobe Acrobat, re-export without a password, then try again.

**Fonts look wrong in the output (wrong typeface, odd spacing).**
The first run installs Poppins automatically into your user font folder, but Word/Pages sometimes needs to be restarted before it sees newly-installed fonts. Quit and reopen Word (or Pages), then reopen the polished document. Note: Apple Pages substitutes fonts more aggressively than Word — for the cleanest result, open the output in Microsoft Word or Google Docs. If Poppins still isn't picked up, check whether it actually landed:

- macOS: open Font Book and search for "Poppins".
- Windows: open **Settings › Personalization › Fonts** and search for "Poppins".

If it's missing, run the polisher again — the font-install step is idempotent.

## License

Private — Optimind internal tooling. See [LICENSE](LICENSE).
