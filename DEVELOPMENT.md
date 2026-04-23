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

(`optimind` is the marketplace name; `optimind-docs` is the plugin name inside it.) After install, restart Claude Code and the two skills surface as `/polish-word` and `/polish-pdf`.

## Repo layout (flat — Claude plugin spec)

```
.
├── .claude-plugin/
│   ├── plugin.json                   ← plugin manifest
│   └── marketplace.json              ← marketplace catalog (lists this plugin)
├── skills/
│   ├── polish-word/                  ← /polish-word skill (was /polish-doc before 0.3.0)
│   │   ├── SKILL.md                  ← workflow Claude follows when invoked
│   │   └── references/ui-kit.md      ← design-system spec (colors, type, variants)
│   └── polish-pdf/                   ← /polish-pdf skill (new in 0.3.0)
│       └── SKILL.md                  ← PDF-to-Word conversion workflow
├── scripts/
│   ├── polish_doc.py                 ← core Word polisher (filename unchanged across rename)
│   ├── pdf_to_docx.py                ← PDF → .docx converter (pdf2docx + PyMuPDF)
│   ├── extract_text.py               ← cover-detail inference (from a .docx)
│   ├── install_fonts.py              ← cross-platform Poppins installer
│   ├── run.sh                        ← launcher (macOS / Linux / Git Bash on Windows)
│   ├── run.ps1                       ← launcher (Windows PowerShell)
│   └── requirements.txt
├── assets/
│   ├── cover_template.docx           ← Jinja template for the cover page
│   └── fonts/                        ← bundled Poppins (Regular / Bold / SemiBold)
├── README.md                         ← end-user install + usage
├── DEVELOPMENT.md                    ← this file
├── LICENSE
└── .gitignore
```

> **Heads-up — skill folder rename.** In 0.3.0 `skills/polish-doc/` became `skills/polish-word/` so the slash command (`/polish-word`) pairs cleanly with the new `/polish-pdf`. The underlying polisher script keeps its historical filename (`polish_doc.py`) — it's an internal detail only referenced from inside this repo, and renaming it would just add churn.

Everything above is the plugin. No nested `optimind-docs/` folder — the manifest lives at the repo root, which is what `/plugin install github:…` expects.

## Edit map

| Change | File |
|---|---|
| `/polish-word` workflow Claude follows | [skills/polish-word/SKILL.md](skills/polish-word/SKILL.md) |
| `/polish-pdf` workflow Claude follows | [skills/polish-pdf/SKILL.md](skills/polish-pdf/SKILL.md) |
| Design-system tokens (colors, type, variants) | [skills/polish-word/references/ui-kit.md](skills/polish-word/references/ui-kit.md) |
| Polisher logic (.docx transformations) | [scripts/polish_doc.py](scripts/polish_doc.py) |
| PDF → .docx conversion logic | [scripts/pdf_to_docx.py](scripts/pdf_to_docx.py) |
| Cover detail inference (from a .docx) | [scripts/extract_text.py](scripts/extract_text.py) |
| First-run font / venv bootstrap | [scripts/run.sh](scripts/run.sh) and [scripts/run.ps1](scripts/run.ps1) |
| Cross-platform font installer | [scripts/install_fonts.py](scripts/install_fonts.py) |
| Plugin manifest + version | [.claude-plugin/plugin.json](.claude-plugin/plugin.json) |
| Marketplace manifest + version | [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json) |

## Test a local change

The plugin has a self-bootstrapping launcher. From the repo root:

**Word polisher:**
```bash
scripts/run.sh scripts/polish_doc.py \
  --input  "/path/to/some.docx" \
  --title  "Q1 Marketing Performance Report" \
  --client "Acme Industries" \
  --period "1 Jan – 31 Mar, 2026"
```

**PDF → .docx converter:**
```bash
scripts/run.sh scripts/pdf_to_docx.py \
  --input  "/path/to/source.pdf" \
  --output "$HOME/OptimindDocs/input/source.docx"
# Prints JSON: {pages, tables_detected, images_detected, output_path, text_char_count}
```

First call creates a private venv under `.venv/` (~30 s) and installs Poppins into your user font folder if missing; later calls are instant. Polisher output lands in `~/OptimindDocs/output/`; converter output lands wherever `--output` points (convention: `~/OptimindDocs/input/` so `/polish-word` picks it up next).

On Windows PowerShell, use `scripts\run.ps1` instead.

## Release flow (GitHub-based)

Colleagues install the plugin by pointing Claude Desktop at this repo — no zip hand-off. Updates flow through `git push`.

### Ship an update

1. Edit files under `skills/`, `scripts/`, or `assets/`.
2. Bump `version` in **both** [.claude-plugin/plugin.json](.claude-plugin/plugin.json) and [.claude-plugin/marketplace.json](.claude-plugin/marketplace.json) (keep them in sync — semver: `0.2.0` → `0.3.0` for features, `0.2.0` → `0.2.1` for fixes). The marketplace bumps `metadata.version` and the matching `plugins[0].version`.
3. Test locally (see above).
4. Commit and push:
   ```bash
   git add -A
   git commit -m "polish_doc: describe the change"
   git push
   ```
5. Tag the release:
   ```bash
   git tag -a v0.3.0 -m "v0.3.0 — one-line summary"
   git push --tags
   ```

Colleagues pull the new version by running `/plugin update optimind-docs` in Claude Desktop.

### Build a distributable zip (fallback for non-Git installs)

For colleagues on networks that block GitHub, or on older Claude Desktop versions, publish the `.plugin` zip as a **GitHub Release** attachment:

```bash
# Clean build — explicit inclusion list, no dev scaffolding
rm -rf dist && mkdir dist
zip -rq dist/optimind-docs.plugin \
  .claude-plugin skills scripts assets README.md LICENSE \
  -x "*.DS_Store" -x "*__pycache__/*" -x "*.pyc"
```

Then in GitHub → **Releases** → *Draft a new release* → pick tag `v0.3.0` → attach `dist/optimind-docs.plugin`.

`dist/` is gitignored — it's a build output, regenerated on demand.

## Design system source of truth

Tokens mirror the Optimind Docs Kit Figma file:
[Optimind Docs Kit](https://www.figma.com/design/iYE9CtCoxRESvSGtTrfBhs/Optimind-Docs-Kit), page `Doc`.

If Figma tokens change, update **both**:
- [skills/polish-word/references/ui-kit.md](skills/polish-word/references/ui-kit.md) — what Claude reads at runtime.
- The `RGBColor` constants at the top of [scripts/polish_doc.py](scripts/polish_doc.py) — what the polisher actually applies.

Keep them in sync; Claude uses the markdown to reason about edge cases, and the Python constants for rendering.

## Content-preservation invariant

The polisher's load-bearing rule is: **never mutate source text, numbers, dates, or values.** [scripts/polish_doc.py](scripts/polish_doc.py) runs `verify_text_preserved(...)` before every save; if the post-polish document's text would differ from the input (beyond cover/header/footer strings it intentionally adds), the script aborts with `Content-preservation check failed` and no output is written.

If you add a new transformation, convince yourself it only changes *styling* (font, size, color, spacing, display-only uppercase via `<w:caps/>`, borders, fills). Any change that rewrites `run.text` will trip the verifier.
