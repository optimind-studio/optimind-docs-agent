# Optimind Docs

Rebuild Word and PDF reports as fully branded Optimind documents. Source text, numbers, dates, and values are preserved verbatim — only the visual styling and structure are regenerated.

> **What's new in 0.5.0** — the architecture is rebuilt end-to-end.
> - **One command: `/polish`.** Auto-detects `.docx` and `.pdf`. The old `/polish-word` and `/polish-pdf` still exist as deprecation stubs that redirect here.
> - **Five subagents, zero API key.** Intake, Auditor, Classifier, DS-Extender, and Renderer-QA run **inside your Claude Code session** via a state-file + stdout-sentinel handoff protocol. `ANTHROPIC_API_KEY` is no longer required.
> - **Self-extending design system.** When a document contains an element that doesn't match any known DS component, DS-Extender designs the new component, stages a runtime-valid Python renderer, and pushes the component to the [Optimind Docs Kit Figma file](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit) via the `use_figma` MCP tool. Generated artefacts are committed to git, so every new component is reviewable as a normal diff.
> - **Auto-retry on QA failure** (up to 2 attempts), looping back to the stage diagnosed by the Renderer-QA agent. No silent ships.
> - **HTML report next to every output.** `report.html` summarises block counts, subagent decisions, DS extensions, audit findings, and any retries — human-readable, no JSON spelunking required.
> - **Scales to 200-page docs.** Auditor samples every Nth page plus every heading, table, chart, callout, and KPI strip; Classifier batches ambiguous blocks by shape signature (~50 → ~8 calls).

## What this plugin does

When installed, this plugin gives Claude a single skill:

- **`/polish`** — takes a `.docx`, `.pdf`, or a folder of them, and produces a fully branded Optimind report. Type the slash command or ask Claude in plain English ("polish this report", "apply Optimind branding to this file").

**Pipeline (stage machine, driven by the skill orchestrator):**

1. **Intake** — resolve the path, detect format, infer cover details (title / client / period), confirm with the user once.
2. **Parse** — ingest (python-docx / pdfplumber / pymupdf), flatten floating shapes, normalize, reconstruct, tokenize into a primitive block stream.
3. **Classify** — rules fast-path; ambiguous blocks are grouped by shape signature and handed to the Classifier agent in batches.
4. **Refine** — deterministic cleanup (neighbor merges, dedupe).
5. **Chart-data extraction** — rules strategies (adjacent data table; image word extraction); low-confidence blocks escalated to the Auditor/Classifier.
6. **DS-Extend** — novel blocks routed to DS-Extender, which looks up Figma first, designs the component, stages tokens + a runtime-valid renderer, and round-trips to Figma via `use_figma`.
7. **Render** — cover page + per-block branded renderers (static + dynamic dispatch), driven by the design-system tokens in `ui-kit.md` and `tokens_extensions.json`.
8. **Verify** — content preservation (word-level Counter match) + layout smoke → structured QADiagnosis.
9. **Promote** — atomically merge staged DS extensions into the repo if QA passed; discard otherwise.
10. **Report** — emit `<name>-polished-<date>.docx`, `.classification.json`, and `.report.html`.

**Source text is never altered.** The pipeline runs a word-level content-preservation check before emitting; if anything was dropped or changed, Renderer-QA routes back to the render stage with a narrower strategy. On exhaustion the document is emitted **marked "degraded"** in the HTML report with the exact defect surfaced — never silently shipped, never blocked.

**No OCR.** `/polish` still needs a PDF with a real text layer. Scanned documents and image-only PDFs will produce an empty block tree — re-export from the source application, or OCR first.

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

> Claude Code's plugin system is a two-step flow by design (add marketplace → install plugin).

After install, **restart Claude Code** so the skill and subagents are picked up. Confirm by opening `/plugin` → **Installed** tab, or by typing `/` and looking for `polish` in the slash-command picker.

Pull later updates:

```
/plugin marketplace update optimind
```

Restart Claude Code after updating.

### Option B — Install from `.plugin` file (offline / blocked networks)

1. Grab the latest `optimind-docs.plugin` from the repo's [Releases page](../../releases).
2. Claude Desktop → **Settings → Plugins → Install from file** → pick the downloaded file.
3. Restart Claude Code.

### Requirements

- **macOS, Windows, or Linux.**
- **Python 3.**
  - **Windows: nothing to install.** On first run, the plugin silently downloads Python 3.12 from python.org and does a per-user install (no admin required). Takes ~1–2 minutes on first run. If you already have Python 3 installed, it's detected and reused.
  - **macOS:** usually preinstalled. If not, `brew install python`.
  - **Linux:** use your package manager, e.g. `sudo apt install python3 python3-venv`.
- **Figma MCP access** — only needed to auto-publish new DS components to the Optimind Docs Kit Figma file. Without it, DS-Extender still produces the code-side artefacts (pipeline keeps working) and flags the Figma gap in the HTML report for manual designer import — the degradation is graceful, not blocking.
- **No Anthropic API key** — subagents run inside your Claude Code session.

On first run the plugin:

1. (Windows only, if needed) downloads and silently installs Python 3.12 from python.org — per-user, no admin required.
2. Creates its own isolated Python environment and installs its libraries (`python-docx`, `docxtpl`, `lxml`, `pdfplumber`, `pymupdf`, `matplotlib`, `jinja2`, plus supporting numerics) — takes ~30–60 seconds.
3. Installs the **Poppins** font family into your user font folder **only if it's not already on your system**. No admin rights needed.

Every run after that is instant (polish time scales with document size — expect 30–90 s per report, more on ≥100-page docs).

## How to use

### Polishing a single file (Word or PDF)

1. In Claude, say something like:
   - "Polish this report."
   - "Brand this PDF."
   - "Apply Optimind branding to `~/OptimindDocs/input/report.pdf`."
   - Or run `/polish` directly.

2. Claude will ask for the file path (or read it from `~/OptimindDocs/input/`), extract the first few pages to infer title / client / period, and ask you to confirm.

3. The orchestrator runs the stage machine end-to-end. When a subagent is needed (Classifier / Chart inference / DS-Extender / Auditor / Renderer-QA), the skill invokes it with a bounded context window and writes the reply back into the run's state bundle. Python resumes from there.

4. The branded `.docx`, the classification sidecar, and the HTML report all land in `~/OptimindDocs/output/`.

### Polishing a folder (batch mode)

Hand `/polish` a folder path. The orchestrator confirms the shared cover details once, then loops the stage machine over every `.docx` and `.pdf` inside. Each run gets its own `run-id` under `~/OptimindDocs/.polish-state/`. You get:

- one `<name>-polished-<date>.docx` + `.classification.json` + `.report.html` per input, and
- a rollup summary in the terminal.

### Reviewing the output

Each run writes three files next to the output:

```
~/OptimindDocs/output/report-polished-2026-04-24.docx
~/OptimindDocs/output/report-polished-2026-04-24.classification.json
~/OptimindDocs/output/report-polished-2026-04-24.report.html
```

Open the `.report.html` first — it summarises block counts, retries, DS extensions, and any warnings in plain English. The `.classification.json` is the machine-readable ground truth if you need to audit a specific block.

### Folder convention

```
~/OptimindDocs/
  ├── input/           ← drop Word files and PDFs here
  ├── output/          ← polished copies + sidecars + HTML reports
  └── .polish-state/   ← durable per-run state bundles (safe to delete)
```

All three are created the first time the plugin runs. You can also pass an absolute path to a file anywhere on disk.

## Table variants

The polisher ships with two table styles from the Optimind design system:

- **Classic** (default) — red header row, alternating zebra rows.
- **Minimal** — rule-based, no fills. Best for dense numeric comparison tables.

Variant selection is automatic — the Classifier picks Minimal for mostly-numeric tables and Classic otherwise. New DS components added by DS-Extender may ship additional variants.

## What's inside the plugin

```
.
├── .claude-plugin/
│   ├── plugin.json                   ← plugin manifest (0.5.0)
│   └── marketplace.json              ← marketplace catalog
├── .mcp.json                         ← declares the Figma MCP (design-system round-trip)
├── settings.json                     ← audit.sample_n, retry.max_attempts, figma.file_key, state.dir
├── agents/
│   ├── intake.md                     ← resolves path, infers cover metadata
│   ├── auditor.md                    ← sampling-based QA across the full block stream
│   ├── classifier.md                 ← resolves ambiguous blocks (batched)
│   ├── ds-extender.md                ← designs + publishes new DS components
│   └── renderer-qa.md                ← diagnoses render defects, owns retry policy
├── commands/
│   └── polish.md                     ← slash-command shim that invokes the skill
├── skills/
│   ├── polish/                       ← the orchestrator
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── ui-kit.md             ← design-system spec (colors, type, variants)
│   │       ├── handoff-protocol.md   ← JSON schemas for agent ↔ Python
│   │       ├── state-machine.md      ← stage transitions + exit codes
│   │       └── report-template.html  ← Jinja2 template for .report.html
│   ├── polish-word/SKILL.md          ← deprecation stub → /polish
│   └── polish-pdf/SKILL.md           ← deprecation stub → /polish
├── scripts/
│   ├── polish/                       ← Python package: stage machine
│   │   ├── __main__.py               ← --stage / --state-dir / --resume entrypoint
│   │   ├── state.py                  ← durable state bundle
│   │   ├── handoff.py                ← sentinel emit, pending queue, cache
│   │   ├── sample.py                 ← deterministic Auditor sampling
│   │   ├── html_report.py            ← Jinja2 HTML renderer
│   │   ├── model.py                  ← Block / Table / Chart / DSExtension / RetryRecord / …
│   │   ├── ingest/                   ← docx_reader.py + pdf_reader.py
│   │   ├── flatten.py / normalize.py / reconstruct.py / tokenize_blocks.py / refine.py
│   │   ├── classify.py               ← rules fast-path + pending queue
│   │   ├── chart_extract.py          ← 2-strategy chart extraction + pending queue
│   │   ├── verify.py                 ← QADiagnosis (no raises)
│   │   ├── report.py                 ← sidecar + HTML report writer
│   │   └── render/
│   │       ├── tokens.py             ← built-in tokens + runtime extension merge
│   │       ├── tokens_extensions.json← committed DS extensions (starts empty)
│   │       ├── docx_writer.py        ← static + dynamic renderer dispatch
│   │       ├── dynamic_dispatch.py   ← AST-validated generated renderer loader
│   │       ├── dynamic/              ← DS-Extender-authored renderers (committed)
│   │       └── (heading / paragraph / list / table / kpi_strip / callout / chart / figure / cover)
│   ├── extract_text.py               ← cover-detail inference
│   ├── install_fonts.py              ← cross-platform Poppins installer
│   ├── run.sh / run.ps1              ← launchers
│   └── requirements.txt
├── assets/
│   ├── cover_template.docx
│   └── fonts/                        ← bundled Poppins
├── README.md                         ← this file
├── DEVELOPMENT.md                    ← maintainer notes
├── CHANGELOG.md
└── LICENSE
```

Contributors: see [DEVELOPMENT.md](DEVELOPMENT.md) for the edit / test / release flow.

## Design system source of truth

Colors, fonts, spacing, and component geometry in the output all come from the Optimind Docs Kit Figma file:

- File: [Optimind Docs Kit](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit)
- Reference frame: node `2550:17` (Docx Demo — red-header variant)

If tokens change in Figma, update both `skills/polish/references/ui-kit.md` and the `T.*` constants in `scripts/polish/render/tokens.py`. New components added by DS-Extender at runtime land in `scripts/polish/render/tokens_extensions.json` + `scripts/polish/render/dynamic/<kind>.py` — all committed to git so every extension is reviewable as a normal diff.

## Troubleshooting

**"Python 3 was not found on this machine."**
The plugin couldn't locate `python3`. Install Python 3 (`brew install python` or download from [python.org](https://www.python.org/downloads/)) and try again.

**Run is marked "degraded" in the HTML report.**
The Renderer-QA agent exhausted 2 retries and the orchestrator shipped the best-effort output with the exact defect surfaced. Open `.report.html` → the "Degraded" banner names the block(s) and stage that failed. Common causes: a DS extension produced invalid output (reviewable in `scripts/polish/render/dynamic/`), chart extraction couldn't reach 0.7 confidence, or a complex floating shape broke the flatten step.

**PDF produces an empty output.**
The PDF likely has no text layer (scanned document, screenshot-to-PDF). The plugin does not OCR. Re-export from the source application (Google Docs, Word, Pages, Looker, Tableau) or OCR it first with a dedicated tool.

**Fonts look wrong in the output (wrong typeface, odd spacing).**
The first run installs Poppins automatically into your user font folder, but Word/Pages sometimes needs to be restarted before it sees newly-installed fonts. Quit and reopen Word (or Pages), then reopen the polished document. Apple Pages substitutes fonts more aggressively than Word — for the cleanest result, open the output in Microsoft Word or Google Docs.

**DS-Extender didn't publish to Figma.**
The `use_figma` MCP call failed (common on fresh installs before Figma MCP auth). The code-side artefacts still land (`tokens_extensions.json` + `dynamic/<kind>.py`), so the pipeline keeps working — only the Figma side needs manual import. The HTML report lists the affected components in its "manual cleanup" section.

## License

Private — Optimind internal tooling. See [LICENSE](LICENSE).
