---
name: polish-pdf
description: Deprecated in v0.5.0 — redirects to the unified /polish skill, which auto-detects .pdf and .docx. This stub only exists so users who still invoke /polish-pdf get pointed at the new command without errors.
---

# Deprecated — use `/polish`

As of v0.5.0 the PDF and Word pipelines are unified under a single `/polish` command that auto-detects the file type, orchestrates the subagent roles (Intake, Auditor, Classifier, DS-Extender, Renderer-QA), and writes an HTML report alongside every output.

## What to do

Tell the user: "The `/polish-pdf` command was retired in v0.5.0. Run `/polish` instead — it auto-detects `.pdf` and `.docx` and does everything this skill used to do (plus auto-retry on QA failure, a human-readable HTML report, and a self-extending design system)."

Then hand off to the [polish](../polish/SKILL.md) skill immediately. No other action is needed in this file — do not attempt to run the old v0.4 pipeline.

## Migration notes

- Scanned / image-only PDFs still fail loudly — OCR is out of scope, same as before.
- Output still lands under `~/OptimindDocs/output/`, now with a third file per run: `<name>-polished-<date>.report.html`.
- `ANTHROPIC_API_KEY` is no longer required — all LLM reasoning happens inside the user's Claude Code session via the bundled subagents.
- The `--no-review` / `--table-style` / `--batch` flags are gone. Batch mode is now a folder path handed to `/polish`; the orchestrator loops internally.
