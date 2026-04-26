# Optimind Docs — CLAUDE.md

This repo is both a Claude Code **plugin** (`optimind-docs`) and its own **marketplace** (`optimind`). The plugin exposes a single user-facing skill, `/optimind-docs:polish`, which rebuilds Word and PDF reports as fully branded Optimind documents.

## Architecture

```
User types /optimind-docs:polish <path>
        │
        ▼
skills/polish/SKILL.md        ← orchestrator (you, the session Claude)
        │
        ├── agents/intake.md          ← resolves path, infers cover metadata
        │
        ├── python -m polish          ← deterministic stage machine (scripts/polish/)
        │       ├── parse
        │       ├── audit_parse (PDF only)
        │       ├── classify          ← may pause → agents/classifier.md
        │       ├── refine
        │       ├── chart_extract     ← may pause → agents/classifier.md
        │       ├── ds_extend         ← may pause → agents/ds-extender.md
        │       ├── render
        │       ├── verify
        │       ├── promote
        │       └── report
        │
        ├── agents/auditor.md         ← sampling QA after render
        └── agents/renderer-qa.md    ← diagnosis + retry decision
```

## Stage machine

The Python pipeline (`scripts/polish/__main__.py`) is invoked one stage at a time via `scripts/run.sh` (macOS/Linux) or `scripts/run.ps1` (Windows). Exit codes:

| Code | Meaning |
|------|---------|
| `0` | Stage complete, proceed |
| `10` | Pending items — parse `<<HANDOFF>>` from stderr, invoke agent, `--resume` |
| `20` | Soft failure — continue to QA for diagnosis |
| `2` | Hard failure — surface stderr to user and stop |

Full protocol: `skills/polish/references/state-machine.md` and `skills/polish/references/handoff-protocol.md`.

## Key invariant

**Content preservation.** `verify.py` checks a word-level Counter match between source and output. A drop > 10% (excluding intentionally omitted figure/chart blocks) causes a hard QA fail. Never alter source text, numbers, dates, or values.

## Edit map

| You want to change… | Edit this file |
|---------------------|----------------|
| Orchestrator flow / step order | `skills/polish/SKILL.md` |
| Design system tokens, colors, text styles | `scripts/polish/render/tokens.py` + `skills/polish/references/ui-kit.md` |
| Block renderers | `scripts/polish/render/<kind>.py` |
| Audit rules | `agents/auditor.md` |
| Classification rules | `scripts/polish/classify.py` + `agents/classifier.md` |
| QA / retry policy | `agents/renderer-qa.md` |
| DS extension staging | `agents/ds-extender.md` |
| Python pipeline stages | `scripts/polish/__main__.py` |
| Handoff JSON schemas | `skills/polish/references/handoff-protocol.md` |
| Plugin metadata | `.claude-plugin/plugin.json` |
| Marketplace catalog | `.claude-plugin/marketplace.json` |
| Auto-install hook | `hooks/hooks.json` |

## Creator-only setup (Figma round-trip)

The DS-Extender agent can push new components to Figma when the Figma desktop plugin's MCP server is running. This is **not required** — colleagues never need it; the agent degrades to `staged_code_only` without it.

To enable:
1. Copy `.mcp.json.example` → `.mcp.json` (gitignored)
2. Start the Figma desktop plugin (Dev Mode → MCP)
3. Copy Figma keys from `settings.creator.json.example` into your local `settings.json`

## Running the pipeline locally (development)

```bash
# Install deps manually (or let the SessionStart hook do it)
bash scripts/run.sh --install-only

# Drive a single stage
bash scripts/run.sh -m polish --stage parse --state-dir ~/OptimindDocs/.polish-state/test-run-001

# Full end-to-end test
/optimind-docs:polish ~/path/to/test.docx
```

## Colleague installation

```
/plugin marketplace add optimind-studio/optimind-docs-agent
/plugin install optimind-docs@optimind
```

Updates are automatic — every commit to `main` on `optimind-studio/optimind-docs-agent` is a new version.
