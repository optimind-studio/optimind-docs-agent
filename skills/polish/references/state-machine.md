# Stage machine

The Python pipeline decomposes into named stages. The skill drives the machine; Python executes one stage per invocation and exits with a status code.

## Stages

```
intake               (handled by the Intake subagent — no Python run)
  ↓
parse                python -m polish --stage parse --state-dir <dir>
  ↓
audit_parse          (PDF only) python -m polish --stage audit_parse --state-dir <dir>
                     emits manifest.md + pdf_text.txt
  ↓
manifest_classify    (PDF only) skill invokes Classifier in manifest_classify mode
                     — agent reads manifest.md + pdf_text.txt, writes blocks/block_stream.json
  ↓
explode_block_stream (PDF only) python -m polish --stage explode_block_stream --state-dir <dir>
                     — splits block_stream.json into per-block <NNNNN>.json files
  ↓
classify             (docx only) python -m polish --stage classify --state-dir <dir>
  ↓ (may emit handoffs — skill loops classify with --resume)
refine               (docx only) python -m polish --stage refine --state-dir <dir>
  ↓
chart_extract        (docx only) python -m polish --stage chart_extract --state-dir <dir>
  ↓ (may emit handoffs — skill loops)
ds_extend            (skill invokes DS-Extender for anything in pending/ds_extend/)
  ↓
render               python -m polish --stage render --state-dir <dir>
  ↓
audit                (skill invokes Auditor)
  ↓
qa                   (skill invokes Renderer-QA; Renderer-QA internally runs python -m polish --stage verify)
  ↓ (if retry: loop back to render | classify | ds_extend | chart_extract | explode_block_stream)
promote              python -m polish --stage promote --state-dir <dir>
  ↓
report               python -m polish --stage report --state-dir <dir>
```

## Exit codes

| Code | Semantics |
|---|---|
| `0`  | Stage completed successfully; no subagent resolution required. |
| `10` | Stage paused with pending items in `pending/<kind>/`. Skill must invoke the appropriate subagent, write resolutions, and re-run the same stage with `--resume`. The pending kind is declared on stderr via the `<<HANDOFF>>` sentinel. |
| `20` | Stage produced output but flagged a soft failure (e.g. chart extraction confidence low across the board). Skill continues; Renderer-QA will diagnose. |
| `2`  | Hard failure — unrecoverable or protocol violation. Skill surfaces stderr verbatim and stops. Never retry. |

## --resume flag

Every stage accepts `--resume`. Semantics:

- Load all resolutions from `<state_dir>/resolutions/<kind>/` that belong to this stage.
- Merge them into the canonical blocks / chart data / extension registry.
- Retry the stage's work on the remaining items.
- Return `0` when no items remain pending.

## Retry counter

`state.json.retry_counter[stage]` tracks how many times a stage has been re-run by the Renderer-QA retry loop. Max 2 per stage. The skill increments before re-invoking.

When a counter reaches 2 and QA still fails, the skill:

1. Sets `state.json.degraded = true`.
2. Proceeds through `promote` (skipping staged DS extensions if the failure was DS-related) and `report` anyway.
3. Emits the output with a "degraded" banner on the HTML report and a 4th terminal line listing the top-severity finding.

## Resume safety

The state bundle is designed to be resumable after a crash:

- Every stage writes back to `state.json` before exiting.
- Blocks are stored one-per-file, so a partial write corrupts one block at worst, not the whole run.
- Re-running a stage from the last successful stage should be idempotent (stages check `state.stage` on entry).

## Batch mode

Not a stage — a mode flag. The skill runs the whole machine once per input file, each with its own `<run_id>` / state dir. Python never sees the batch boundary.
