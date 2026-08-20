# Hybrid Google Docs → Markdown pages (with Docs/PDF buttons)

**Date:** 2026-08-20
**Status:** Phase B done — awaiting full click-through before Phase C cleanup
**Branch:** `try-markdown-conversion` (build + review there; merge only after sign-off)

## Description

Replace the PDF.js iframe pages with real Markdown pages generated from the source
Google Docs, each topped with three buttons:

- **Open the Google Doc** — the doc's read-only `/preview` viewer (no editing
  chrome; the `/edit` share link is intentionally not exposed)
- **View PDF** — self-hosted PDF, plain same-tab link (no iframe); opens in the
  browser's native viewer and the back button returns to the page. (Google's own
  export URL can't be used for viewing: it sends `Content-Disposition: attachment`.)
- **Download PDF** — same hosted file with a `download` attribute (proper filename)

Why this works: every "PDF Link" in the sheets is just a Google Doc ID with
`export?format=pdf` appended. The same doc exports as Markdown via
`export?format=md` — verified on the ALD SOP (headings, tables, and anchors came
through cleanly; 17 images arrive as base64 data URIs to be decoded into files).

**Trust gate:** MD conversion fidelity is unproven at scale. Phase A converts only
the deposition SOPs and stops for a side-by-side review. Nothing is deleted and the
existing PDF pages stay on `main` untouched until final sign-off.

**Sources** (from existing scripts):

| Section | Sheet | Name column | Pages |
| --- | --- | --- | --- |
| Tool SOPs | `download_tool_pdfs.py` sheet | `Tool Name` (+ `Type (Category)` → folder) | `docs/tool_sops/<category>/<slug>.md` |
| Chemical hoods | `download_chem_pdfs.py` sheet | `Document Name` | `docs/chemicals/<hood>/index.md` |
| Policies | `download_policy_pdfs.py` sheet | `Document Name` | `docs/policy/<name>.md` |

`faq/` and `signup/` are hand-written — untouched.

## Steps

### Phase A — Pilot: sync script + deposition section only

- [x] `git checkout -b try-markdown-conversion` (done)
- [x] Write `scripts/sync_gdocs.py` (single script replacing the three copies, per DRY):
  - [x] Config table: sheet CSV URL, name column, section → output path rules
  - [x] Extract doc ID from `PDF Link`; derive share URL (`.../edit`) when the sheet
        has no `Share Link` column (tools sheet has one; chem/policy may not)
  - [x] Download `https://docs.google.com/document/d/<ID>/export?format=md`
  - [x] Post-process the exported Markdown:
    - [x] Strip Google's inline table-of-contents block (Material generates its own)
    - [x] Decode base64 image reference definitions into hash-named files in
          `img/` next to the pages (dedupes; idempotent re-runs)
    - [x] Strip Google's "AI-generated content may be incorrect" alt-text boilerplate
    - [x] Keep the existing page H1 (nav titles come from `.nav.yml`, unaffected)
    - [x] Strip empty heading lines (`# ` styling leftovers in the source docs)
  - [x] Prepend button row after the H1 using `{ .md-button }`
  - [x] Slugified names match existing filenames for all 7 deposition pages
        (chem/policy maps deferred to Phase B; script skips unmapped with warning)
  - [x] Idempotent + non-interactive; sections + `--category`/`--only` filters
- [x] Run for deposition only: `uv run python scripts/sync_gdocs.py tools --category Deposition`
      (7 pages written; 71 images, 7.1 MB)
- [x] `uv run mkdocs build --strict` passes
- [x] `ruff check` / `ruff format` clean on the new script (ruff added as dev dep;
      pre-existing lints in the three legacy scripts left — they're deleted in Phase C)

### Phase A review gate — STOP for sign-off

- [ ] `uv run mkdocs serve` and compare each deposition page against its Google Doc:
  - [ ] Headings/structure match
  - [ ] Tables render correctly (facility-info table, hazard tables)
  - [ ] All images present, legible, in the right places
  - [ ] Numbered procedure steps in order, no dropped text
  - [ ] Both buttons work (doc opens; PDF downloads)
  - [ ] Mobile viewport check (browser devtools)
- [ ] Decision: fidelity acceptable? If NO → stay on PDFs, delete branch, done.

### Phase B — Roll out remaining sections

- [x] Run sync for tool_sops (etch, lithography, metrology, packaging) — 21 pages;
      filename overrides added for ICP-Cl, ICP-Fl, Spinner, Elionix 100keV
- [x] Run sync for chemicals (5 hood index pages + 8 etch/clean SOPs)
- [x] Run sync for policy (four docs)
- [x] `uv run mkdocs build --strict` passes
- [x] Automated spot-checks: no pdfjs iframes left in any .md, no empty-heading
      artifacts, derived share links working for chem/policy
      (`wecas.md` is an empty stub with no source doc — left as is)
- [ ] Full click-through on `mkdocs serve` (nav, search now indexes SOP content)

### Phase C — Cleanup (only after Phase B sign-off)

- [ ] Keep `docs/assets/pdfs/` — the View PDF button links to these hosted files,
      refreshed by the sync script
- [ ] Delete `docs/assets/pdfjs/` (~21 MB) and the commented pdfjs line in `mkdocs.yml`
- [ ] Delete the three old `download_*_pdfs.py` scripts
- [ ] Revisit the deferred link cleanup from the awesome-nav plan (Step 4½) if page
      structure changed
- [ ] `uv run mkdocs build --strict` + final serve check

### Phase D — Ship

- [ ] Merge `try-markdown-conversion` → `main` after visual sign-off
- [ ] `./deploy.sh` and spot-check the live site

## Known limits / notes

- Google's MD export caps at 10 MB per doc (ALD was 2.2 MB — fine)
- ~~Images are re-compressed by Google~~ FIXED: the markdown export caps images at
  ~640px, so the script also downloads the docx export (original resolution) and
  swaps in originals when aspect ratio + pixel content confidently match and the
  original is meaningfully larger (Pillow-based comparison; cropped/unmatched
  images safely keep the markdown version). Site images: ~40 MB total
- Stray uncommitted PDFs once present in `docs/tool_sops/deposition/` were never
  in git (early script-test leftovers) and are already gone — no Phase C action
- Docs must stay link-shared for unauthenticated export; if sharing tightens later,
  switch the script to the Drive API with the service-account JSON (kept in GitHub
  Actions secrets, never committed)
- Complex nested tables or equations may not convert — the review gate exists to
  catch these; worst case a specific page keeps a PDF fallback
- GitHub Actions automation (nightly cron + manual trigger) is a separate follow-up
  plan once this display approach is trusted
