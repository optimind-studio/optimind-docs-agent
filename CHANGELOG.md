# Changelog

All notable changes to the Optimind Docs plugin are logged here. The format follows [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.5.1] — 2026-04-26

PDF fidelity + layout fixes. The PDF flow now preserves table row data on first run (no more empty Sent/Delivered/Open Rate cells), section labels stop orphaning above their H1, action-card borders render as one continuous line, and table alignment matches the DS spec.

### Added
- **`explode_block_stream` stage.** New Python stage `python -m polish --stage explode_block_stream --state-dir <dir>` splits the classifier's `blocks/block_stream.json` (manifest_classify output) into per-block `blocks/<NNNNN>.json` files with the `{kind, content: {...}}` schema the renderer's loader expects. Without it the renderer iterated zero blocks and produced a cover-only docx for PDF inputs. No-op on docx flow. [scripts/polish/__main__.py](scripts/polish/__main__.py).
- **Positional pymupdf dump.** `audit_parse` for PDF now also writes `<state_dir>/pdf_text.txt` — every span with `(x, y)` coordinates — alongside `manifest.md`. The classifier reads both: manifest for structure, pdf_text for high-fidelity row/value pairing on tables that wrap or span pages. [scripts/polish/audit_parse.py:write_pdf_positional_text](scripts/polish/audit_parse.py).

### Changed
- **Classifier agent gets `Write, Edit` tools** (was `Read` only). Required for `manifest_classify` mode to actually write `block_stream.json` instead of silently emitting it as text. [agents/classifier.md](agents/classifier.md).
- **`section_label` renderer** now sets `pageBreakBefore` so each section starts a fresh page. [scripts/polish/render/section_label.py](scripts/polish/render/section_label.py).
- **`heading` renderer** skips its own H1 page break when the immediately preceding paragraph already has one. Fixes the orphan-section-label / blank-page-between-sections layout. [scripts/polish/render/heading.py](scripts/polish/render/heading.py).
- **`action_card` renderer** wraps title + body in a single 1-cell borderless table whose cell carries the brand-red left border, giving one continuous line instead of two disconnected paragraph borders separated by `space-after`. Also fixes a `'RGBColor' object has no attribute 'red'` crash on the previous border XML. [scripts/polish/render/action_card.py](scripts/polish/render/action_card.py).
- **Table alignment** follows the DS spec: first column left, all others centered (was right-aligning numeric body columns). [scripts/polish/render/table.py:_style_cell](scripts/polish/render/table.py).
- **`LABELS_COVER` and `LABELS_MAIN`** now have `titlecase=False` per ui-kit.md ("Labels use default casing — no uppercase transform"). Section labels and KPI card labels now preserve source casing instead of being silently title-cased. [scripts/polish/render/tokens.py](scripts/polish/render/tokens.py).
- **Renderer-QA diagnostic rule** added: empty cells in body rows are NOT a renderer bug. The agent now picks `stage_to_retry: "classify"` (with the affected `(y, x)` coordinates from `pdf_text.txt`) when values are missing in block files but present in the positional dump, and returns `should_retry: false, hard_fail: false` (degraded) when the data is in neither source. [agents/renderer-qa.md](agents/renderer-qa.md).
- **Skill orchestrator and state-machine reference** updated to wire `explode_block_stream` into the PDF flow between `manifest_classify` and `render`. [skills/polish/SKILL.md](skills/polish/SKILL.md), [skills/polish/references/state-machine.md](skills/polish/references/state-machine.md).

### Fixed
- PDF tables with multi-page or two-column layouts no longer drop row values. The classifier reading `pdf_text.txt` can now pair country names with volumes, scenario names with revenues, and so on — values that the manifest had collapsed into adjacent paragraph blocks.
- Action cards no longer crash render with `AttributeError: 'RGBColor' object has no attribute 'red'`.
- Cover-only-output bug for PDF inputs (block stream existed but renderer couldn't see it).

## [0.5.0] — 2026-04-24

Ground-up architecture rebuild. **Breaking changes** across the install surface, the CLI contract, and the dependency list — upgrading 0.4.x users need to restart Claude Code, clear their cached venv, and re-read the migration notes below.

### Added
- **Single `/polish` command.** Auto-detects `.docx` and `.pdf`; batches folders internally. [commands/polish.md](commands/polish.md), [skills/polish/SKILL.md](skills/polish/SKILL.md).
- **Five subagent roles** — Intake, Auditor, Classifier, DS-Extender, Renderer-QA — under [agents/](agents/). All run inside the user's Claude Code session; no `ANTHROPIC_API_KEY` required.
- **Stage machine CLI.** `python -m polish --stage <name> --state-dir <dir> [--resume]` with exit codes `0` (done), `10` (pending items), `20` (QA soft failure), `2` (hard failure). [scripts/polish/__main__.py](scripts/polish/__main__.py).
- **Durable state bundle** at `~/OptimindDocs/.polish-state/<run-id>/` — stage transitions, per-block JSON, pending queues, resolutions, staged DS extensions, audit samples, QA diagnoses, and a content-hashed resolution cache that persists across runs. [scripts/polish/state.py](scripts/polish/state.py).
- **`<<HANDOFF>>` sentinel protocol** for agent ↔ Python handoff, documented in [skills/polish/references/handoff-protocol.md](skills/polish/references/handoff-protocol.md). [scripts/polish/handoff.py](scripts/polish/handoff.py).
- **Deterministic sampling** for the Auditor — every Nth page (N=3/5/10 by doc size) plus every heading, table, chart, callout, and KPI strip, chunked ≤30 blocks per Auditor call. Scales to 200-page docs. [scripts/polish/sample.py](scripts/polish/sample.py).
- **Self-extending design system.** DS-Extender designs new components for unknown block kinds, stages tokens + a runtime-valid Python renderer, and round-trips to Figma file `iYE9CtCoxRESvSGtTrfBhs` via the `use_figma` MCP tool. Staged artefacts are only promoted to the repo after QA passes. [agents/ds-extender.md](agents/ds-extender.md).
- **AST-validated dynamic renderer dispatch.** Generated renderers under `scripts/polish/render/dynamic/<kind>.py` are re-validated on import — strict function signature, allowlisted imports, denylisted modules, no `eval`/`exec`/`compile`/`__import__`, no shell escapes. [scripts/polish/render/dynamic_dispatch.py](scripts/polish/render/dynamic_dispatch.py).
- **Runtime token extension merge.** [scripts/polish/render/tokens.py](scripts/polish/render/tokens.py) reads [scripts/polish/render/tokens_extensions.json](scripts/polish/render/tokens_extensions.json) at import, merging new hex tokens and text styles into the module namespace without overwriting built-ins.
- **HTML report** next to every output — block counts, subagent decisions, DS extensions, audit findings, retries, degraded banner. [scripts/polish/html_report.py](scripts/polish/html_report.py), template at [skills/polish/references/report-template.html](skills/polish/references/report-template.html).
- **Auto-retry policy.** Renderer-QA returns a structured diagnosis (`retry_stage`, `severity`, `affected_block_indices`); the orchestrator loops back to the diagnosed stage up to 2 times, then ships a "degraded" output rather than blocking. [agents/renderer-qa.md](agents/renderer-qa.md), [scripts/polish/verify.py](scripts/polish/verify.py).
- **Classifier batching by shape signature** — ~50 ambiguous blocks fold into ~8 grouped calls, with each Classifier invocation receiving one group (~3–10 blocks) in a single prompt. [scripts/polish/classify.py](scripts/polish/classify.py).
- **Plugin-spec configs** — [.mcp.json](.mcp.json) declaring the Figma MCP, [settings.json](settings.json) with `audit.sample_n` / `retry.max_attempts` / `figma.file_key` / `state.dir`. Both live at the plugin root per [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins), not nested inside `.claude-plugin/`.
- New dataclasses on [scripts/polish/model.py](scripts/polish/model.py): `DSExtension`, `RetryRecord`, `StageCheckpoint`, plus a `HandoffProtocolError` exception.
- **CHANGELOG.md** (this file).
- Unified output naming: `<name>-polished-<YYYY-MM-DD>.docx` + `.classification.json` + `.report.html` under `~/OptimindDocs/output/`.

### Changed
- [skills/polish-word/SKILL.md](skills/polish-word/SKILL.md) and [skills/polish-pdf/SKILL.md](skills/polish-pdf/SKILL.md) are now **deprecation stubs** that redirect to `/polish`. The underlying canonical pipeline, the block model, and every static renderer are preserved unchanged.
- [scripts/polish/verify.py](scripts/polish/verify.py) now **returns a QADiagnosis dict** instead of raising `ContentPreservationError` / `UnclassifiedContentError`. Hard failures still surface; soft failures route to the retry loop.
- [scripts/polish/classify.py](scripts/polish/classify.py) and [scripts/polish/chart_extract.py](scripts/polish/chart_extract.py) dropped the direct Anthropic SDK fallback. Ambiguous blocks now emit pending queue items under `pending/<kind>/<index>.json`; the orchestrator dispatches the subagent.
- [scripts/polish/report.py](scripts/polish/report.py) emits the HTML report alongside the JSON sidecar.
- [scripts/polish/render/docx_writer.py](scripts/polish/render/docx_writer.py) routes unknown block kinds through the dynamic dispatcher with a paragraph fallback, instead of raising.
- [README.md](README.md) and [DEVELOPMENT.md](DEVELOPMENT.md) rewritten for the new architecture.

### Removed
- `scripts/polish/review.py` — the interactive block-tree preview gate. The new pipeline auto-accepts; the HTML report is the post-run surface for review.
- `--no-review` / `--table-style` / `--batch` / `--output-dir` CLI flags. The stage machine is single-stage-per-invocation; batch mode is a folder path handed to the orchestrator.
- `anthropic>=0.40` from [scripts/requirements.txt](scripts/requirements.txt). Added `jinja2>=3.1` for the HTML report.
- `ANTHROPIC_API_KEY` / `OPTIMIND_POLISH_CLAUDE_MODEL` env vars — no longer consulted.

### Migration notes (0.4.x → 0.5.0)
- Restart Claude Code after updating. The new agents/commands/settings surface only loads on fresh sessions.
- If you had scripts that shelled out to `python -m polish --input … --no-review`, they'll fail — the `--input` flag only applies to `--stage init` now, and downstream stages read from the state bundle. The skill orchestrator is the intended driver; call it via `/polish`.
- Old `.classification.json` files are forward-compatible (superset schema). Old output `.docx` files are untouched.
- The `.polish-state/` bundle is per-user per-run; safe to delete at any time.

### Known risks
- `use_figma` creation capability is unverified end-to-end — first live-agent smoke test of each release must prove it can create components inside `iYE9CtCoxRESvSGtTrfBhs`. If it can't, DS-Extender still produces the code-side artefacts (pipeline keeps working) and flags the Figma gap in the HTML report for manual designer import.
- Callout keyword detection ("warning", "next steps", "insight") is English-only; marked `# TODO(i18n)` in code.
- Figma rollback is best-effort — failed extensions get logged in the HTML report's "manual cleanup" section rather than guaranteed-undone.

## [0.4.0] — 2026-03

- Full pipeline rewrite: Parse → Canonical Model → Re-render.
- `/polish-pdf` polishes PDFs directly, no intermediate `.docx` step.
- New block kinds: KPI strips, native charts (bar / column / line / pie / donut / funnel / stacked).
- Folder input + `--batch` rollup.
- `.classification.json` sidecar next to every output.

## [0.3.0] — 2026-02

- Renamed `/polish-doc` → `/polish-word`; introduced `/polish-pdf` (via pdf2docx).
- Poppins font install step and first-run venv bootstrap.
