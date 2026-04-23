---
name: polish-word
description: Deprecated in v0.5.0 — redirects to the unified /polish skill, which auto-detects .docx and .pdf. This stub only exists so users who still invoke /polish-word get pointed at the new command without errors.
---

# Deprecated — use `/polish`

As of v0.5.0 the Word and PDF pipelines are unified under a single `/polish` command that auto-detects the file type, orchestrates the subagent roles (Intake, Auditor, Classifier, DS-Extender, Renderer-QA), and writes an HTML report alongside every output.

## What to do

Tell the user: "The `/polish-word` command was retired in v0.5.0. Run `/polish` instead — it auto-detects `.docx` and `.pdf` and does everything this skill used to do (plus auto-retry on QA failure, a human-readable HTML report, and a self-extending design system)."

Then hand off to the [polish](../polish/SKILL.md) skill immediately. No other action is needed in this file — do not attempt to run the old v0.4 pipeline.

## Migration notes

- Output still lands under `~/OptimindDocs/output/`, now with a third file per run: `<name>-polished-<date>.report.html`.
- `ANTHROPIC_API_KEY` is no longer required — all LLM reasoning happens inside the user's Claude Code session via the bundled subagents.
- The `--no-review` / `--table-style` / `--batch` flags are gone. Batch mode is now a folder path handed to `/polish`; the orchestrator loops internally.
