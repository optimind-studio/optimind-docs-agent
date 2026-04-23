# Development — Optimind Docs plugin

Maintainer notes for editing, testing, and releasing the **Optimind Docs** Claude plugin.

End-user documentation lives in [README.md](README.md). If you're here to *use* the plugin, start there.

## What this repo is

This repo is **both** a Claude plugin *and* a Claude marketplace that lists one plugin (this one). Two files under `.claude-plugin/` describe each role:

- `.claude-plugin/plugin.json` — the plugin manifest (identity, version).
- `.claude-plugin/marketplace.json` — the marketplace manifest that points `/plugin install` at the plugin.

Colleagues install with (two commands, in order, then restart Claude Code):

```
/plugin marketplace add lqxdesign/optimind-docs_polisher-agent
/plugin install optimind-docs@optimind
```

After install, restart Claude Code and one slash command surfaces: `/polish`. The old `/polish-word` and `/polish-pdf` remain as deprecation stubs that redirect.

## Repo layout (flat — Claude plugin spec)

The plugin follows the official spec at [code.claude.com/docs/en/plugins](https://code.claude.com/docs/en/plugins): `agents/`, `skills/`, `commands/`, `.mcp.json`, `settings.json` all sit at the plugin root — none of them are nested inside `.claude-plugin/`.

```
.
├── .claude-plugin/
│   ├── plugin.json                   ← plugin manifest (0.5.0)
│   └── marketplace.json              ← marketplace catalog
├── .mcp.json                         ← declares the Figma MCP
├── settings.json                     ← audit.sample_n, retry.max_attempts, figma.file_key, state.dir
├── agents/
│   ├── intake.md                     ← resolve path, infer cover metadata
│   ├── auditor.md                    ← sampling-based QA across the block stream
│   ├── classifier.md                 ← resolves ambiguous blocks (batched)
│   ├── ds-extender.md                ← designs + publishes new DS components
│   └── renderer-qa.md                ← diagnoses render defects, owns retry policy
├── commands/
│   └── polish.md                     ← slash-command shim
├── skills/
│   ├── polish/                       ← orchestrator (runs inside Claude Code)
│   │   ├── SKILL.md
│   │   └── references/
│   │       ├── ui-kit.md
│   │       ├── handoff-protocol.md   ← agent ↔ Python JSON schemas
│   │       ├── state-machine.md      ← stage transitions + exit codes
│   │       └── report-template.html  ← Jinja2 template
│   ├── polish-word/SKILL.md          ← deprecation stub → /polish
│   └── polish-pdf/SKILL.md           ← deprecation stub → /polish
├── scripts/
│   ├── polish/                       ← Python package: stage machine
│   │   ├── __main__.py               ← --stage / --state-dir / --resume
│   │   ├── state.py                  ← durable state bundle
│   │   ├── handoff.py                ← sentinel emit + pending queue + cache
│   │   ├── sample.py                 ← deterministic Auditor sampling
│   │   ├── html_report.py            ← Jinja2 HTML renderer
│   │   ├── model.py                  ← canonical dataclasses
│   │   ├── ingest/
│   │   ├── flatten.py / normalize.py / reconstruct.py / tokenize_blocks.py / refine.py
│   │   ├── classify.py               ← rules + pending queue
│   │   ├── chart_extract.py          ← rules + pending queue
│   │   ├── verify.py                 ← QADiagnosis (no raises)
│   │   ├── report.py                 ← sidecar + HTML writer
│   │   └── render/
│   │       ├── tokens.py + tokens_extensions.json
│   │       ├── docx_writer.py
│   │       ├── dynamic_dispatch.py   ← AST-validated generated-renderer loader
│   │       ├── dynamic/              ← DS-Extender-authored renderers
│   │       └── (heading / paragraph / list / table / kpi_strip / callout / chart / figure / cover)
│   ├── extract_text.py
│   ├── install_fonts.py
│   ├── run.sh / run.ps1
│   └── requirements.txt
├── assets/
│   ├── cover_template.docx
│   └── fonts/
├── README.md
├── DEVELOPMENT.md                    ← this file
├── CHANGELOG.md
├── LICENSE
└── .gitignore
```

## Pipeline architecture (0.5.0 — orchestrator-in-skill)

A Python subprocess cannot invoke a Claude Code agent. So the orchestrator lives in the skill. The Python pipeline is decomposed into named **stages** (`init → parse → classify → refine → chart_extract → ds_extend → render → verify → promote → report`) that read/write a durable **state bundle** on disk and exit with a sentinel on stdout when they need a decision.

```
User: /polish report.pdf
  └─ skills/polish/SKILL.md (the orchestrator)
       ├─ invokes agent: intake            → state.stage = "intake_complete"
       ├─ bash: python -m polish --stage init  --input <path> --title …
       ├─ bash: python -m polish --stage parse --state-dir <dir>
       ├─ bash: python -m polish --stage classify --state-dir <dir>
       │     └─ emits <<HANDOFF>> on stderr if ambiguous blocks, exits 10
       ├─ invokes agent: classifier (batched)  → writes resolutions/classify/*.json
       ├─ bash: python -m polish --stage classify --state-dir <dir> --resume
       ├─ (same for chart_extract, ds_extend as needed)
       ├─ bash: python -m polish --stage render
       ├─ invokes agent: auditor            → sampling-based QA on blocks
       ├─ invokes agent: renderer-qa        → final diagnosis
       │     └─ if fail & retries<2: loop back to the diagnosed stage
       └─ bash: python -m polish --stage report → writes .docx + .classification.json + .report.html
```

**Handoff protocol.** Python emits on stderr exactly one line `<<HANDOFF>>` followed by a JSON line listing pending files and the resume target. The skill parses it, invokes the right subagent, writes JSON replies into `resolutions/<kind>/<block_index>.json`, and re-runs Python with `--resume`. Exit codes: `0` = stage done, `10` = pending items, `20` = soft failure (QA diagnose), `2` = hard fail. Full schemas live at [skills/polish/references/handoff-protocol.md](skills/polish/references/handoff-protocol.md).

**State bundle.** Lives at `~/OptimindDocs/.polish-state/<run-id>/`. Contains `state.json`, one JSON per block under `blocks/`, pending/resolutions queues, `staged/` (DS extensions await promotion), `audit/` sample indices + findings, `cache/` (shared resolution cache keyed by content hash).

**Agent context is bounded.** Classifier and DS-Extender only ever see one block plus ≤8 neighbors. Auditor receives summaries + sampled-block file references. For ≥100-page docs the Auditor runs in chunks of ~30 blocks per call.

## Edit map

| Change | File |
|---|---|
| `/polish` orchestrator workflow | [skills/polish/SKILL.md](skills/polish/SKILL.md) |
| Handoff JSON schemas | [skills/polish/references/handoff-protocol.md](skills/polish/references/handoff-protocol.md) |
| Stage transitions + exit codes | [skills/polish/references/state-machine.md](skills/polish/references/state-machine.md) |
| HTML report template | [skills/polish/references/report-template.html](skills/polish/references/report-template.html) |
| Design-system tokens (colors, type, variants) | [skills/polish/references/ui-kit.md](skills/polish/references/ui-kit.md) |
| Subagent role cards | [agents/intake.md](agents/intake.md), [agents/auditor.md](agents/auditor.md), [agents/classifier.md](agents/classifier.md), [agents/ds-extender.md](agents/ds-extender.md), [agents/renderer-qa.md](agents/renderer-qa.md) |
| Figma MCP declaration | [.mcp.json](.mcp.json) |
| Tunables (sample_n, retry.max_attempts, figma.file_key, state.dir) | [settings.json](settings.json) |
| Stage machine CLI | [scripts/polish/__main__.py](scripts/polish/__main__.py) |
| Durable state bundle | [scripts/polish/state.py](scripts/polish/state.py) |
| Sentinel emit + pending queue + cache | [scripts/polish/handoff.py](scripts/polish/handoff.py) |
| Deterministic Auditor sampling | [scripts/polish/sample.py](scripts/polish/sample.py) |
| Jinja2 HTML report renderer | [scripts/polish/html_report.py](scripts/polish/html_report.py) |
| Canonical data model + DSExtension / RetryRecord | [scripts/polish/model.py](scripts/polish/model.py) |
| .docx ingest | [scripts/polish/ingest/docx_reader.py](scripts/polish/ingest/docx_reader.py) |
| .pdf ingest | [scripts/polish/ingest/pdf_reader.py](scripts/polish/ingest/pdf_reader.py) |
| Classifier (rules + pending queue) | [scripts/polish/classify.py](scripts/polish/classify.py) |
| Chart data extraction (rules + pending queue) | [scripts/polish/chart_extract.py](scripts/polish/chart_extract.py) |
| Brand tokens (colors, type, sizes) | [scripts/polish/render/tokens.py](scripts/polish/render/tokens.py) |
| Runtime token extensions (committed) | [scripts/polish/render/tokens_extensions.json](scripts/polish/render/tokens_extensions.json) |
| AST-validated dynamic renderer loader | [scripts/polish/render/dynamic_dispatch.py](scripts/polish/render/dynamic_dispatch.py) |
| DS-Extender-authored renderers | [scripts/polish/render/dynamic/](scripts/polish/render/dynamic/) |
| Per-block renderers (static) | [scripts/polish/render/](scripts/polish/render/) |
| QA diagnosis (no raises) | [scripts/polish/verify.py](scripts/polish/verify.py) |
| Sidecar + HTML writer | [scripts/polish/report.py](scripts/polish/report.py) |
| Cover detail inference | [scripts/extract_text.py](scripts/extract_text.py) |
| First-run font / venv bootstrap | [scripts/run.sh](scripts/run.sh), [scripts/run.ps1](scripts/run.ps1) |
| Cross-platform font installer | [scripts/install_fonts.py](scripts/install_fonts.py) |
| Plugin manifest + version | [.claude-plugin/plugin.json](.claude-plugin/plugin.json) |
| Marketplace manifest + version | [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json) |

## Test a local change

The plugin has a self-bootstrapping launcher. From the repo root, drive individual stages:

```bash
# 1. Create a run
scripts/run.sh -m polish --stage init \
  --input  "/path/to/some.pdf" \
  --title  "Q1 Marketing Performance Report" \
  --client "Acme Industries" \
  --period "1 Jan – 31 Mar, 2026"
# → prints {"run_id": "...", "state_dir": "…/.polish-state/<run-id>", …}

# 2. Parse (deterministic)
scripts/run.sh -m polish --stage parse --state-dir <state_dir>

# 3. Classify — may emit <<HANDOFF>> on stderr and exit 10 (pending items)
scripts/run.sh -m polish --stage classify --state-dir <state_dir>

# 4. If it paused: drop resolution JSON into resolutions/classify/<index>.json,
#    then re-run with --resume
scripts/run.sh -m polish --stage classify --state-dir <state_dir> --resume

# 5…10. refine → chart_extract → ds_extend → render → verify → promote → report
```

End-to-end driving is the skill orchestrator's job — the Python CLI is intentionally single-stage so tests can mock each subagent by hand-writing `resolutions/*.json`.

### Exit codes

| Code | Meaning |
|---|---|
| `0`  | Stage complete |
| `10` | Pending items — subagent dispatch required (see `<<HANDOFF>>` on stderr) |
| `20` | Soft failure — Renderer-QA returned a diagnosis with `retry_recommended: true` |
| `2`  | Hard failure (bad args, protocol violation, unrecoverable error) |
| `1`  | Bad input path |

### Useful env vars

- `OPTIMIND_POLISH_STATE_ROOT` — override the state bundle root (`~/OptimindDocs/.polish-state/`).
- `OPTIMIND_POLISH_OUTPUT_ROOT` — override the output root (`~/OptimindDocs/output/`).

`ANTHROPIC_API_KEY` is **no longer used** — classifier and chart inference now flow through the subagents, which run inside the user's Claude Code session.

### Tests

Under `scripts/polish/tests/` — unit tests for state round-trip, handoff sentinel emission, deterministic sampling, token extension merging, dynamic dispatch, and retry counter. Integration tests mock agent replies by writing canned JSON into `resolutions/` before running the dependent stage — this exercises the full handoff protocol without live agent calls. Fixtures (`simple_5page.docx`, `ambiguous_20page.docx`, `novel_styled_10page.pdf`, `chart_heavy_50page.pdf`, `200page.docx`, `broken_render.docx`) cover every code path.

Live-agent smoke tests (run manually on each release):

1. `/polish` on each fixture → verify HTML report visually.
2. DS-extension round-trip: synthetic unknown block → verify `use_figma` creates the component in `iYE9CtCoxRESvSGtTrfBhs`, verify `tokens_extensions.json` + `dynamic/<kind>.py` appear and are AST-valid, re-run → confirm deterministic classification on the second pass (the DS extension is persisted).
3. Forced render failure: temporarily break a renderer → confirm auto-retry → confirm clean hard-fail after 2 attempts with an annotated HTML report.
4. 200-page scale run: time budget, per-agent token usage snapshot, output fidelity spot-check.

## Release flow (GitHub-based)

1. Edit files under `agents/`, `skills/`, `scripts/`, `commands/`, `assets/`, or the root configs.
2. Bump `version` in **both** [.claude-plugin/plugin.json](.claude-plugin/plugin.json) and [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json) (keep them in sync — semver: `0.4.0` → `0.5.0` for breaking changes, `0.5.0` → `0.5.1` for fixes). The marketplace bumps `metadata.version` and the matching `plugins[0].version`.
3. Add a CHANGELOG entry describing the change.
4. Test locally (see above), including at least one live subagent smoke test.
5. Commit + push:
   ```bash
   git add -A
   git commit -m "polish: describe the change"
   git push
   ```
6. Tag the release:
   ```bash
   git tag -a v0.5.0 -m "v0.5.0 — one-line summary"
   git push --tags
   ```

Colleagues pull the new version by running `/plugin update optimind-docs` in Claude Desktop.

### Build a distributable zip (fallback for non-Git installs)

```bash
rm -rf dist && mkdir dist
zip -rq dist/optimind-docs.plugin \
  .claude-plugin .mcp.json settings.json agents skills commands scripts assets \
  README.md CHANGELOG.md LICENSE \
  -x "*.DS_Store" -x "*__pycache__/*" -x "*.pyc"
```

`dist/` is gitignored — a build output, regenerated on demand.

## Design system source of truth

Tokens mirror the Optimind Docs Kit Figma file: [Optimind Docs Kit](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit), reference frame node `2550:17` (Docx Demo — red-header variant).

If Figma tokens change, update **both**:
- [skills/polish/references/ui-kit.md](skills/polish/references/ui-kit.md) — what the subagents read at runtime.
- [scripts/polish/render/tokens.py](scripts/polish/render/tokens.py) — what the renderer actually applies.

Runtime-generated components land in [scripts/polish/render/tokens_extensions.json](scripts/polish/render/tokens_extensions.json) and [scripts/polish/render/dynamic/](scripts/polish/render/dynamic/). These are **committed to git** — every new component is reviewable as a normal diff. The DS-Extender subagent self-validates AST before staging, and [scripts/polish/render/dynamic_dispatch.py](scripts/polish/render/dynamic_dispatch.py) re-validates on import (second line of defense); committed-to-git review is the third.

## Content-preservation invariant

The polisher's load-bearing rule is: **never mutate source text, numbers, dates, or values.** [scripts/polish/verify.py](scripts/polish/verify.py) runs a word-level Counter match between the canonical `Document` and the rendered `.docx` before declaring success; if any word of length ≥ 3 appears fewer times in the output than in the source, verify returns a QADiagnosis with `retry_stage="render"` and the skill orchestrator re-runs render with narrower optimizations. On exhaustion (2 retries) the document is emitted **marked "degraded"** in the HTML report.

Chart blocks are a deliberate exception: the chart image embeds its own labels/values as pixels, not as Word text runs, so `_block_text` for a chart contributes only the chart title. Don't add more exceptions without updating the verify contract and thinking through what that enables.

If you add a new renderer or block kind (static **or** generated), make sure every word from the canonical block reaches the Word text layer (or deliberately account for why it shouldn't, as with charts).
