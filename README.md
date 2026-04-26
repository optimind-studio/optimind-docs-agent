# Optimind Docs

Rebuild Word and PDF reports as fully branded Optimind documents. Source text, numbers, dates, and values are preserved verbatim — only the visual styling and structure are regenerated.

> **v0.5.0** — architecture rebuilt end-to-end.
> - **One command: `/optimind-docs:polish`.** Auto-detects `.docx` and `.pdf`.
> - **Five subagents, zero API key.** Intake, Auditor, Classifier, DS-Extender, and Renderer-QA run inside your Claude Code session — no `ANTHROPIC_API_KEY` needed.
> - **Self-extending design system.** Novel blocks are designed as new DS components, staged as committed Python renderers, and (for the plugin creator with Figma access) round-tripped to the Optimind Docs Kit Figma file.
> - **Auto-retry on QA failure** (up to 2 attempts per stage). No silent ships.
> - **HTML report** next to every output — summarises block counts, subagent decisions, DS extensions, audit findings, and any retries.

---

## Colleague installation

Run these two commands inside Claude Code (CLI, Desktop, or IDE extension):

```
/plugin marketplace add optimind-studio/optimind-docs-agent
/plugin install optimind-docs@optimind
```

That's it. After install, restart Claude Code so the skill and subagents are picked up. Confirm with `/plugin` → **Installed** tab.

**The command is `/optimind-docs:polish`.** Claude Code namespaces plugin skills by plugin name. If you want a shorter alias, add one line to `~/.claude/commands/polish.md`:

```
Run /optimind-docs:polish $ARGUMENTS
```

Then type `/polish` as usual.

### Getting updates

Updates are **automatic** — every commit pushed to `optimind-studio/optimind-docs-agent` is a new version. Claude Code picks it up at the start of your next session. You can also pull manually:

```
/plugin update optimind-docs@optimind
```

### Requirements

- **macOS, Windows, or Linux**
- **Python 3** (see platform notes below)
- **Claude Code** (CLI, Desktop app, or IDE extension) — `/polish` does not work in claude.ai web chat

**Python setup by platform:**

| Platform | What to do |
|----------|------------|
| **Windows** | Nothing — the plugin auto-downloads Python 3.12 from python.org on first run (per-user install, no admin needed). ~1–2 min once. |
| **macOS** | Usually pre-installed. If missing: `brew install python` |
| **Linux** | `sudo apt install python3 python3-venv` (or equivalent) |

On first session start, the plugin's `SessionStart` hook automatically creates a local Python venv and installs all dependencies (~30–60 s on first run). Nothing to run manually.

---

## How to use

### Polish a single file

```
/optimind-docs:polish ~/path/to/report.docx
/optimind-docs:polish ~/path/to/report.pdf
```

Or drop files in `~/OptimindDocs/input/` and run `/optimind-docs:polish` with no arguments.

Claude asks you to confirm the inferred title / client / period, then runs the full pipeline end-to-end.

### Batch mode (folder)

```
/optimind-docs:polish ~/OptimindDocs/input/
```

Runs the pipeline once per `.docx` / `.pdf` found in the folder. Each file gets its own `run-id`; you get a rollup summary at the end.

### Output files

Each run produces three files in `~/OptimindDocs/output/` (or your configured output directory):

```
report-polished-2026-04-24.docx
report-polished-2026-04-24.classification.json
report-polished-2026-04-24.report.html
```

Open `.report.html` first — it summarises everything in plain English.

### Folder layout

```
~/OptimindDocs/
  ├── input/           ← drop source files here
  ├── output/          ← polished copies + sidecars + HTML reports
  └── .polish-state/   ← per-run state bundles (safe to delete)
```

---

## Pipeline overview

| Stage | What it does |
|-------|-------------|
| **Intake** | Resolve path, detect format, infer cover metadata (title/client/period), confirm once |
| **Parse** | Ingest with python-docx / pdfplumber / pymupdf; flatten; normalize; tokenize |
| **Classify** | Rules fast-path; ambiguous blocks batched by shape signature → Classifier agent |
| **Refine** | Deterministic cleanup: neighbor merges, deduplication |
| **Chart extract** | Rules strategies; low-confidence escalated to Classifier |
| **DS-Extend** | Novel blocks → DS-Extender designs tokens + renderer; stages code artefacts |
| **Render** | Cover page + per-block branded renderers (static + dynamic dispatch) |
| **Audit** | Auditor samples every Nth page + all headings/tables/charts/callouts |
| **Renderer-QA** | Python verify + audit findings → diagnosis + retry decision (max 2/stage) |
| **Promote** | Atomically merge staged DS extensions into repo (or discard on QA fail) |
| **Report** | Write `.docx` + `.classification.json` + `.report.html` to output dir |

Source text is **never altered** — word-level content preservation is checked before output is emitted.

---

## Table variants

Two table styles ship with the design system:

- **Classic** (default) — red header row, alternating zebra rows
- **Minimal** — rule lines only, no fills; best for dense numeric comparison tables

Variant selection is automatic. DS-Extender may add new variants for novel layouts.

---

## Plugin structure

```
.
├── .claude-plugin/
│   ├── plugin.json                   ← plugin manifest
│   └── marketplace.json              ← marketplace catalog
├── hooks/
│   └── hooks.json                    ← SessionStart: auto-installs Python deps
├── skills/
│   ├── polish/                       ← orchestrator skill
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── ui-kit.md             ← design-system spec (colors, type, variants)
│   │       ├── handoff-protocol.md   ← JSON schemas for agent ↔ Python
│   │       ├── state-machine.md      ← stage transitions + exit codes
│   │       └── report-template.html  ← Jinja2 template for .report.html
│   ├── polish-word/SKILL.md          ← deprecation stub → /polish
│   └── polish-pdf/SKILL.md           ← deprecation stub → /polish
├── agents/
│   ├── intake.md
│   ├── auditor.md
│   ├── classifier.md
│   ├── ds-extender.md
│   └── renderer-qa.md
├── commands/
│   └── polish.md                     ← slash-command shim
├── scripts/
│   ├── polish/                       ← Python stage machine
│   │   ├── __main__.py               ← --stage / --state-dir / --resume entrypoint
│   │   ├── render/
│   │   │   ├── tokens.py             ← built-in tokens + extension merge
│   │   │   ├── tokens_extensions.json← committed DS extensions
│   │   │   ├── dynamic/              ← DS-Extender-authored renderers
│   │   │   └── (per-block renderers)
│   │   └── (classify / refine / verify / report / …)
│   ├── run.sh                        ← macOS/Linux launcher + venv bootstrap
│   ├── run.ps1                       ← Windows launcher + auto Python install
│   └── requirements.txt
├── assets/
│   ├── cover_template.docx
│   └── fonts/                        ← bundled Poppins
├── CLAUDE.md                         ← architecture reference for Claude sessions
├── DEVELOPMENT.md                    ← maintainer notes
├── CHANGELOG.md
├── settings.json                     ← tunable defaults (audit sample sizes, retry count, output dir)
├── .mcp.json.example                 ← creator-only: Figma MCP setup reference
└── settings.creator.json.example    ← creator-only: Figma file key reference
```

---

## Known limitations (v0.5)

**Images and charts are omitted.** All `figure` and `chart` blocks are parsed and logged but intentionally omitted from the output `.docx`. Each omission is listed in the HTML report under "Omitted Blocks". Chart and figure support will return in a future version.

**No OCR.** PDFs require a real text layer. Scanned documents will produce an empty block tree — re-export from the source application or OCR first.

---

## Troubleshooting

**"Python 3 was not found on this machine."**
Install Python 3 (`brew install python` on macOS, or from [python.org](https://www.python.org/downloads/)) and try again.

**Run is marked "degraded" in the HTML report.**
Renderer-QA exhausted 2 retries and shipped the best-effort output. Open `.report.html` → the "Degraded" banner names the block(s) and stage that failed.

**PDF produces an empty output.**
The PDF has no text layer (scanned / image-only). The plugin does not OCR. Re-export from the source application or OCR it first.

**Fonts look wrong (wrong typeface, odd spacing).**
The first run installs Poppins into your user font folder. Quit and reopen Word / Pages after the first run. For cleanest results use Microsoft Word or Google Docs to open the output.

**DS-Extender skipped the Figma step.**
The plugin degrades gracefully when the Figma MCP server isn't running — the Python renderer is still staged and committed. Only the Figma design file is missing the new component. This is expected for all colleagues; the Figma round-trip is a creator-only feature.

---

## For the plugin creator

See [DEVELOPMENT.md](DEVELOPMENT.md) for the edit / test / release workflow.

To enable Figma DS round-trip locally:
- Copy `.mcp.json.example` → `.mcp.json` (gitignored)
- Start the Figma desktop plugin (Dev Mode → MCP)
- Copy Figma keys from `settings.creator.json.example` into your local `settings.json`

---

## License

Private — Optimind internal tooling. See [LICENSE](LICENSE).
