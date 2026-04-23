---
name: polish
description: One command for rebuilding Word or PDF reports as fully branded Optimind documents. Auto-detects .docx vs .pdf, orchestrates five subagents (Intake, Auditor, Classifier, DS-Extender, Renderer-QA), extends the design system via Figma round-trip when novel elements appear, and auto-retries on QA failure. Source text, numbers, dates, and values are preserved verbatim. Trigger when the user asks to "polish", "brand", or "rebrand" a Word doc or PDF, or shares a .docx / .pdf and asks for formatting. Handles single files or folders.
---

# /polish — Optimind document polisher

You orchestrate a deterministic Python pipeline through five specialized subagents to polish a Word or PDF document into a branded Optimind report. You own the stage loop, handoff protocol, auto-retry policy, and final report surfacing. The Python pipeline is fast and deterministic; you invoke subagents only at well-defined handoff points.

## Before anything else — load the design system

Read `${CLAUDE_PLUGIN_ROOT}/skills/polish/references/ui-kit.md`. This is the source of truth for colors, text styles, table variants, KPI tiles, callouts, and chart rules. Every subagent you invoke also reads it. Do not skip.

Also read `${CLAUDE_PLUGIN_ROOT}/skills/polish/references/handoff-protocol.md` and `${CLAUDE_PLUGIN_ROOT}/skills/polish/references/state-machine.md` before your first handoff — these define the stage exit codes, sentinel format, and resolution JSON schemas you will produce.

## Drop-folder convention

User-facing files live under `~/OptimindDocs/`:

- `~/OptimindDocs/input/` — drop files here
- `~/OptimindDocs/output/` — polished `.docx` + `.classification.json` + `.report.html` land here
- `~/OptimindDocs/.polish-state/<run-id>/` — durable state bundle for each run (safe to delete after the run)

The first run of this skill creates these folders automatically. Absolute paths elsewhere on disk work too.

## Top-level flow

```
1. Ask for a path (or use $ARGUMENTS)          → Intake agent
2. python -m polish --stage parse              → canonical block model on disk
3. python -m polish --stage classify           → pending/classify/ may appear → Classifier agent
4. python -m polish --stage refine             → deterministic, no handoffs
5. python -m polish --stage chart_extract      → pending/chart_infer/ may appear → Classifier agent (batch)
6. pending/ds_extend/ may appear               → DS-Extender agent (one invocation per signature group)
7. python -m polish --stage render             → writes the .docx to staged output
8. Auditor agent                                → sampling-based QA findings
9. Renderer-QA agent                            → diagnosis + retry decision
10. If retry: loop back to the diagnosed stage (max 2 attempts/stage)
11. python -m polish --stage promote            → moves staged DS extensions into the repo
12. python -m polish --stage report             → writes .classification.json + .report.html
13. Final 3-line terminal summary to the user.
```

## Step 1 — Intake

If the user's initial request already includes a path (via `$ARGUMENTS` or a message like "polish ~/Downloads/q1.pdf"), pass it directly. Otherwise ask once:

> What's the path to the Word document or PDF you'd like to polish? (Drop it in `~/OptimindDocs/input/`, or pass a folder to polish every `.docx` / `.pdf` inside.)

Then invoke the **intake** agent with:

```json
{ "path": "<the path>", "mode": "single" }
```

Intake returns an `IntakeResult` JSON with a `run_id` and one entry per file. Create the state directory:

```bash
mkdir -p "$HOME/OptimindDocs/.polish-state/<run_id>"
```

Write the IntakeResult into `$HOME/OptimindDocs/.polish-state/<run_id>/state.json`.

For batch mode (folder input), run steps 2–13 once per file with a separate `run_id` each time, then emit a single rollup summary at the end.

## Step 2 — Parse

Run the Python pipeline's parse stage. It reads the source document and writes one block JSON per detected primitive under `blocks/`:

**macOS / Linux:**
```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage parse \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

**Windows (PowerShell):**
```powershell
powershell -ExecutionPolicy Bypass -File "${CLAUDE_PLUGIN_ROOT}/scripts/run.ps1" -m polish --stage parse --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

**On Windows always use run.ps1, even inside Git Bash** — run.ps1 auto-installs Python when missing; run.sh does not.

Expected exit code: `0`. If non-zero, read stderr and surface the error. Do not retry.

## Step 3 — Classify (may emit handoffs)

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage classify \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

**Exit code handling:**
- `0` — done, move to step 4.
- `10` — pending items exist. Read the `<<HANDOFF>>` JSON from stderr (the line immediately after `<<HANDOFF>>`). It lists pending file paths. Invoke the **classifier** agent **once per signature group** with the batch payload described in `handoff-protocol.md`. Write each reply's `resolutions[]` array entries into `<state_dir>/resolutions/classify/<block_index>.json`. Then re-run the same command with `--resume`:
  ```bash
  "${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
    --stage classify --resume \
    --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
  ```
  Loop until exit `0`.
- `20` — soft failure. Do not retry here; continue and Renderer-QA will diagnose.
- Non-zero other — hard fail. Surface the error.

**If classifier returns `unknown` for a block**, Python will move that block to `pending/ds_extend/` on the next stage invocation; you'll route it to DS-Extender in step 6.

## Step 4 — Refine

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage refine \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

Deterministic. Exit `0` expected.

## Step 5 — Chart extract

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage chart_extract \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

Same exit-code handling as step 3. On `10`, invoke the **classifier** agent with the chart-inference payload. Pass resolutions into `resolutions/chart_infer/` and re-run with `--resume`.

## Step 6 — DS extend (only if pending/ds_extend/ exists)

Before running `render`, check for `pending/ds_extend/`:

```bash
ls "$HOME/OptimindDocs/.polish-state/<run_id>/pending/ds_extend/" 2>/dev/null
```

If non-empty, Python has collected blocks the classifier returned as `unknown`. Python will also have grouped them by content signature in `pending/ds_extend/_groups.json`. For each group, invoke the **ds-extender** agent with the group's representative block. The agent stages tokens + renderer + ui-kit patch under `<state_dir>/staged/` and returns a `figma_node_id`.

Write each reply under `<state_dir>/resolutions/ds_extend/<block_index>.json`.

## Step 7 — Render

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage render \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

This writes the `.docx` to `<state_dir>/output/<name>-polished-<date>.docx` (staged — not yet in the user's output folder).

## Step 8 — Audit

Invoke the **auditor** agent. The payload comes from the Python `audit/sample_indices.json` that `refine` produced. Chunk the sampled blocks in batches of ~30 per invocation (the file `audit/sample_indices.json` is pre-chunked — one array entry per chunk). Invoke the auditor once per chunk; concatenate findings.

Write all findings to `<state_dir>/audit/findings.json`.

## Step 9 — QA

Invoke the **renderer-qa** agent with:

```json
{
  "state_dir": "$HOME/OptimindDocs/.polish-state/<run_id>",
  "output_path": "<staged output path>",
  "sidecar_path": "<staged sidecar>",
  "retry_counter": { "render": 0, "classify": 0, "ds_extend": 0, "chart_extract": 0 },
  "attempt": 1,
  "audit_findings": [ ... from step 8 ... ]
}
```

The agent internally runs `python -m polish --stage verify --state-dir <path>` to invoke the Python content-preservation + layout smoke checks, then returns a `QADiagnosis`.

## Step 10 — Retry loop

If `passed: false` AND `retry_counter[stage_to_retry] < 2`:

- Increment `retry_counter[stage_to_retry]` in `state.json`.
- Re-run the pipeline from the diagnosed stage (steps 3 / 5 / 6 / 7 as applicable).
- Re-run steps 8 and 9.

If `passed: false` AND `retry_counter[stage_to_retry] == 2`:

- Mark the run `degraded: true` in state.json.
- Proceed to steps 11–13 anyway — the user gets output plus a clearly labeled report.

If `passed: true`:

- Proceed to step 11.

## Step 11 — Promote

Atomic move of staged DS extensions into the repo (or discard if QA failed with DS-related diagnosis):

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage promote \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

This copies `<state_dir>/staged/tokens_extensions.json` into `scripts/polish/render/tokens_extensions.json` (merge), moves `staged/dynamic/*.py` into `scripts/polish/render/dynamic/`, and applies `staged/ui-kit.md.patch` to `skills/polish/references/ui-kit.md`.

If the run is `degraded: true`, skip promotion of staged DS extensions — they remain in the state dir for manual review.

## Step 12 — Report

```bash
"${CLAUDE_PLUGIN_ROOT}/scripts/run.sh" -m polish \
  --stage report \
  --state-dir "$HOME/OptimindDocs/.polish-state/<run_id>"
```

This writes the final three artifacts to `~/OptimindDocs/output/`:
- `<basename>.docx`
- `<basename>.classification.json`
- `<basename>.report.html`

## Step 13 — Terminal summary

Print exactly three lines to the user:

```
Polished <input-name> → <output-name>.docx
<N> blocks · <M> pages · <K> new DS components · <retries> retries · <status: clean|degraded>
Report: <path to report.html>
```

If `degraded: true`, add a fourth line listing the top-severity QA finding verbatim so the user knows what to review.

## Handoff protocol — how to parse `<<HANDOFF>>`

When Python exits with code `10`, it writes to stderr:

```
<<HANDOFF>>
{"stage":"classify","pending":["pending/classify/42.json","pending/classify/118.json"],"resume_with":["resolutions/classify/"],"signature_groups":{"sig_abc":[42,118]},"run_id":"..."}
```

Your job:
1. Parse the JSON after `<<HANDOFF>>`.
2. For each signature group in `signature_groups`, assemble one agent invocation. The group's block indices identify the pending files.
3. Read each pending file (`<state_dir>/pending/<kind>/<index>.json`) and include the full content in the agent payload under `items[].block_payload`.
4. Also include 2–4 neighbors per block (from `<state_dir>/blocks/`), as `neighbors_before` / `neighbors_after`.
5. Invoke the right agent. Receive its single JSON reply.
6. For each resolution, write a JSON file under `<state_dir>/resolutions/<kind>/<block_index>.json`.
7. Re-run Python with `--resume`. Loop on `<<HANDOFF>>` until Python exits `0`.

Full schemas for every handoff direction live in `references/handoff-protocol.md`. Match them exactly — malformed resolutions cause Python to exit with hard failure code `2`.

## Important rules

- **NEVER change source text, numbers, dates, or values.** The Python pipeline fails loudly if content preservation drops > 10%. The whole point is fidelity.
- **NEVER skip the Auditor or Renderer-QA steps.** They catch real issues. The retry loop exists so that hitting a QA failure once is not fatal.
- **If a subagent invocation errors** (not just returns a failed resolution — actually errors at the tool level), retry it once; if it errors again, surface the error to the user verbatim and stop. Do not fall back to hallucinating a resolution.
- **If `pending/ds_extend/` accumulates more than 10 groups** for a single document, something is likely wrong with the source file (not a design-system gap). Stop and ask the user before extending the DS ten times in one run.
- **On Windows, always use run.ps1.** Do not call `python` directly; do not call run.sh via Git Bash.
- **Do not touch the files under `~/OptimindDocs/.polish-state/<run_id>/`** except through the documented protocol — Python treats the state bundle as its durable truth.
- **On first run on a new machine** the plugin builds a local venv (~30 s on macOS/Linux, up to ~2 min on Windows if Python must be installed). Subsequent runs are instant. If the first run fails with a "Python 3 was not found" error: macOS `brew install python`; Linux `sudo apt install python3 python3-venv`; Windows re-run via run.ps1 in PowerShell.

## Batch mode

If Intake returned multiple files (folder input), run steps 2–12 once per file with a separate `run_id`. Accumulate the per-file outcomes and print a batch rollup at step 13:

```
Polished 5 of 5 inputs. 2 degraded. 1 new DS component across the batch.
See individual reports under ~/OptimindDocs/output/
```

If any file failed hard, list each with its error on its own line.
