"""Optimind Docs — stage-machine polish pipeline.

Stages (driven by the ``/polish`` skill orchestrator):
    1. init          — create the state bundle + output paths
    2. parse         — ingest → flatten → normalize → reconstruct → tokenize
    3. classify      — rules fast-path; ambiguous blocks → Classifier agent
    4. refine        — deterministic cleanup (neighbor merges, dedupe)
    5. chart_extract — recover data for chart blocks; low-conf → agent
    6. ds_extend     — DS-Extender stages new tokens + dynamic renderers
    7. render        — emit branded .docx and stash the Auditor sample
    8. verify        — content preservation + layout smoke → QADiagnosis
    9. promote       — atomically merge staged DS extensions into the repo
   10. report        — .classification.json + .report.html + output copy

Each stage reads/writes the durable state bundle at
``~/OptimindDocs/.polish-state/<run_id>/`` and exits with one of:
    0   stage complete
    10  pending items — orchestrator must dispatch a subagent
    20  soft failure  — QA diagnosis, retry recommended
    2   hard failure  — protocol or unrecoverable error

Run as a module:
    python -m polish --stage init --input path/to/file.docx \
                     --title "..." --client "..." --period "..."
    python -m polish --stage parse --state-dir <dir>
    ...
"""

__version__ = "0.5.0"
