# Handoff protocol

Durable contract between the Python pipeline, the `/polish` skill orchestrator, and the five subagents. Every JSON shape below is stable across the 0.5.x series; Python validates malformed replies and exits with code `2` if a schema is violated.

## State bundle directory

```
~/OptimindDocs/.polish-state/<run-id>/
├── state.json
├── blocks/<index>.json
├── pending/
│   ├── classify/<index>.json
│   ├── chart_infer/<index>.json
│   ├── ds_extend/<index>.json
│   └── ds_extend/_groups.json
├── resolutions/
│   ├── classify/<index>.json
│   ├── chart_infer/<index>.json
│   └── ds_extend/<index>.json
├── staged/
│   ├── tokens_extensions.json
│   ├── ui-kit.md.patch
│   └── dynamic/<kind>.py
├── audit/
│   ├── sample_indices.json
│   └── findings.json
├── qa/verify-<attempt>.json
├── cache/<content-hash>.json
└── output/<basename>.docx
```

## state.json schema (v1)

```json
{
  "schema_version": "1.0",
  "run_id": "<UUID>",
  "mode": "single" | "batch",
  "input_path": "/abs/path/to/source",
  "format": "docx" | "pdf",
  "title": "...",
  "client": "...",
  "period": "...",
  "output_basename": "q1-report-polished-2026-04-24",
  "stage": "intake_complete" | "parse_complete" | "classify_complete" | "refine_complete" | "chart_extract_complete" | "ds_extend_complete" | "render_complete" | "audit_complete" | "qa_complete" | "promoted" | "reported",
  "retry_counter": { "classify": 0, "chart_extract": 0, "ds_extend": 0, "render": 0 },
  "qa_runs": [ /* QADiagnosis records per attempt */ ],
  "extensions": [ /* DSExtension records that were promoted */ ],
  "warnings": [ "..." ],
  "degraded": false
}
```

## Stage exit codes

| Code | Meaning | Skill action |
|---|---|---|
| `0`  | Stage complete | Advance to the next stage. |
| `10` | Pending items — subagent resolution required | Read `<<HANDOFF>>` JSON from stderr, invoke the right agent, write resolutions, re-run with `--resume`. |
| `20` | Soft failure — pipeline produced output but Renderer-QA should diagnose | Continue to audit/qa; do not retry directly. |
| `2`  | Hard failure — unrecoverable or protocol violation | Surface stderr verbatim to the user and stop. |

## `<<HANDOFF>>` sentinel

When Python exits `10`, the last two lines of stderr are:

```
<<HANDOFF>>
{ /* one-line JSON */ }
```

JSON schema:

```json
{
  "stage": "classify" | "chart_infer" | "ds_extend",
  "run_id": "<UUID>",
  "pending": ["pending/classify/42.json", "..."],
  "resume_with": ["resolutions/classify/"],
  "signature_groups": {
    "<group-key>": [42, 118, 204]
  }
}
```

`signature_groups` is only populated for `classify` and `chart_infer`. For `ds_extend` the skill should treat each pending file as its own group (one DS-Extender invocation per unknown signature).

## Per-agent payloads and replies

### Intake

Payload (from skill):
```json
{ "path": "<user-supplied>", "mode": "single" | "batch" }
```

Reply (on stdout):
```json
{
  "run_id": "<UUID>",
  "stage": "intake_complete",
  "mode": "single" | "batch",
  "files": [
    {
      "input_path": "/abs/...",
      "format": "docx" | "pdf",
      "title": "...",
      "client": "...",
      "period": "...",
      "output_basename": "<name>-polished-<YYYY-MM-DD>"
    }
  ]
}
```

### Classifier (batched)

Payload (one invocation per signature group):
```json
{
  "state_dir": "/abs/.../<run-id>",
  "batch_signature": "shading=#FEECEE|first_word=KEY|length_bucket=short",
  "items": [
    {
      "block_index": 42,
      "pending_file": "<state_dir>/pending/classify/42.json",
      "block_payload": { /* full pending block JSON, inlined */ },
      "neighbors_before": [
        { "block_index": 40, "kind": "paragraph", "text_preview": "..." }
      ],
      "neighbors_after": [
        { "block_index": 43, "kind": "paragraph", "text_preview": "..." }
      ]
    }
  ],
  "design_system_summary": "(ui-kit.md contents)"
}
```

Reply:
```json
{
  "stage": "classify_complete",
  "resolutions": [
    {
      "block_index": 42,
      "kind": "heading" | "paragraph" | "list" | "table" | "kpi_strip" | "callout" | "figure" | "chart" | "unknown",
      "variant": "insight" | "next_steps" | "warning" | "note",
      "level": 1 | 2 | 3,
      "label": "KEY INSIGHT",
      "style": "bulleted" | "numbered",
      "confidence": 0.92,
      "rationale": "≤30 words"
    }
  ]
}
```

Notes:
- Fields `variant`, `level`, `label`, `style` appear only when relevant to `kind`.
- `confidence < 0.6` MUST yield `kind: "unknown"` — the skill then routes to DS-Extender.

### Classifier — chart inference mode

Same payload/reply shape, with `kind` restricted to chart types (`bar`, `column`, `line`, `pie`, `donut`, `funnel`, `stacked`, `other`) plus categories/series arrays:

```json
{
  "stage": "chart_infer_complete",
  "resolutions": [
    {
      "block_index": 55,
      "kind": "bar",
      "categories": ["Q1", "Q2", "Q3", "Q4"],
      "series": [
        { "name": "Revenue", "values": [12.1, 14.3, 15.8, 17.2] }
      ],
      "confidence": 0.78
    }
  ]
}
```

### DS-Extender

Payload (one invocation per signature group):
```json
{
  "state_dir": "/abs/.../<run-id>",
  "block_index": 118,
  "pending_file": "<state_dir>/pending/ds_extend/118.json",
  "block_payload": { /* full pending block */ },
  "neighbors_before": [ ... ],
  "neighbors_after": [ ... ],
  "ui_kit": "(ui-kit.md)",
  "tokens": "(tokens.py)",
  "existing_extensions": "(tokens_extensions.json)",
  "figma_file_key": "iYE9CtCoxRESvSGtTrfBhs",
  "figma_target_page": "Doc",
  "figma_anchor_node_id": "2501:286"
}
```

Reply:
```json
{
  "stage": "ds_extend_complete",
  "block_index": 118,
  "status": "staged" | "staged_code_only",
  "extension": {
    "name": "timeline_row",
    "content_hash": "sha256:...",
    "added_at": "2026-04-24",
    "added_by_run": "<run-id>",
    "hex_tokens": { "TIMELINE_DOT": "#2E7D32" },
    "text_styles": {
      "TIMELINE_DATE": { "size_pt": 9, "bold": false, "color_token": "TEXT_SEC", "letter_spacing_px": 1.2, "uppercase": true }
    },
    "renderer_module": "dynamic.timeline_row",
    "figma_node_id": "2501:9981",
    "ui_kit_section": "### Timeline Row\n..."
  },
  "staged_files": [
    "<state_dir>/staged/tokens_extensions.json",
    "<state_dir>/staged/dynamic/timeline_row.py",
    "<state_dir>/staged/ui-kit.md.patch"
  ],
  "figma_error": null
}
```

If Figma push fails, `status: "staged_code_only"` and `figma_error` is a short string.

### Auditor

Payload (one invocation per chunk):
```json
{
  "state_dir": "/abs/.../<run-id>",
  "summary": {
    "total_blocks": 1483,
    "page_count": 212,
    "block_counts": { "heading": 34, "paragraph": 1201, "table": 22, "chart": 18, "callout": 5, "figure": 103, "list": 90, "kpi_strip": 10 },
    "warnings_so_far": [ "..." ],
    "extensions_applied": [ { "kind": "timeline_row", "figma_node_id": "2501:9981" } ]
  },
  "sample": {
    "chunk_index": 0,
    "block_indices": [0, 12, 47, ...],
    "block_files": ["<state_dir>/blocks/0000.json", "..."]
  },
  "design_system_summary": "(ui-kit.md)"
}
```

Reply:
```json
{
  "stage": "audit_complete",
  "chunk_index": 0,
  "findings": [
    {
      "block_index": 134,
      "severity": "high" | "medium" | "low",
      "issue": "≤140 chars",
      "recommended_action": "reclassify" | "extend_ds" | "rerender" | "ignore",
      "evidence": "first 80 chars of block text"
    }
  ],
  "sampled_count": 30,
  "coverage_summary": "..."
}
```

### Renderer-QA

Payload:
```json
{
  "state_dir": "/abs/.../<run-id>",
  "output_path": "<state_dir>/output/<name>-polished-<date>.docx",
  "sidecar_path": "<state_dir>/output/<name>-polished-<date>.classification.json",
  "retry_counter": { "render": 0, "classify": 1, "ds_extend": 0, "chart_extract": 0 },
  "attempt": 1,
  "audit_findings": [ ... ]
}
```

Reply:
```json
{
  "stage": "qa_complete",
  "attempt": 1,
  "passed": false,
  "should_retry": true,
  "hard_fail": false,
  "diagnosis": {
    "reason": "...",
    "severity": "high",
    "stage_to_retry": "render" | "classify" | "ds_extend" | "chart_extract",
    "affected_block_indices": [234, 235, 236],
    "retry_instructions": "..."
  }
}
```

If `passed: true`, omit `diagnosis`.

## Resolution file layout

The skill writes agent replies out as one JSON file per block-index so Python can resume cheaply:

- `resolutions/classify/<block_index>.json` — one entry from a Classifier `resolutions[]` array.
- `resolutions/chart_infer/<block_index>.json` — one entry from a chart-inference `resolutions[]` array.
- `resolutions/ds_extend/<block_index>.json` — the `extension` object (and nothing else) from a DS-Extender reply.

Python's `--resume` logic reads these and merges them into the canonical blocks / chart data / extension registry before continuing the stage.

## Cache

Resolutions are also mirrored under `<state_dir>/cache/<content-hash>.json` using the block content hash. Future runs check the cache before invoking agents, so re-polishing the same document costs zero subagent calls.

## Malformed-reply handling

Python validates every resolution on load. If any file is malformed:

- Log the specific schema violation in `state.json.warnings`.
- Skip that block (treat as unresolved — the stage will re-emit it on the next `--resume` cycle).
- If the same block is rejected twice, exit `2` (hard fail). The skill surfaces the error.

This prevents a bad agent reply from silently corrupting the output.
