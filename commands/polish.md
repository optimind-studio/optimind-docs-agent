---
description: Rebuild a Word or PDF report as a fully branded Optimind document. Auto-detects input format, orchestrates five subagents, extends the design system if new elements appear, and emits a .docx plus an HTML audit report.
argument-hint: [path-to-file-or-folder]
---

Invoke the `polish` skill from this plugin to polish `$ARGUMENTS`.

Follow the orchestration in `skills/polish/SKILL.md` exactly — including the five-subagent flow (Intake → parse → Classifier → DS-Extender → Auditor → render → Renderer-QA → report) and the auto-retry policy.

If `$ARGUMENTS` is empty, ask the user for a file or folder path before proceeding.
