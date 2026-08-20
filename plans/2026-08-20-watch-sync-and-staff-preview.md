# Add watch-mode sync and a staff live-preview site

**Date:** 2026-08-20
**Status:** Phases A–C done, README updated — awaiting Phase C review gate.
Phases D–E superseded by `2026-08-20-staff-preview-server.md`.
**Branch:** sync-watch-mode (off main after PR #1 merged the conversion work)

## Description

Staff edit Google Docs but don't run code, so "preview my edits" must not require
a local checkout, uv, or mkdocs. The preview *is* the site: a watcher polls the
registered docs, re-syncs on change, and publishes to a **staging copy** of the
site. A staff member edits their doc in one browser pane and watches the staging
page refresh (~1–2 min) in the other. No app, no login: the docs are link-shared,
so the whole pipeline stays credential-free.

Decisions made in planning (with the user):

- **Freshness target:** within ~1 minute of an edit is acceptable.
- **No access control:** the preview URL is open; the source docs are public anyway.
- **Preview shows the rendered site page only** (no raw-markdown view).
- **Publish to staging, not production.** A second GitHub Pages repo
  (`nanodocs-preview`) receives automatic deploys; production keeps today's
  manual `./deploy.sh` policy. Flipping to live-publish later is a one-line
  remote change; the reverse (clawing back auto-publish) is not, so staging first.
- **Runner:** the maintainer's machine runs the watcher during editing sessions
  (`--watch --deploy`); a scheduled GitHub Action is the eventually-consistent
  backstop (Actions cron is 5-min minimum and often delayed — too slow to be the
  primary mechanism).
- The same `--watch` flag doubles as the local dev loop alongside `mkdocs serve`.

Key implementation facts justifying the approach:

- `sync_row()` is the single pipeline; watch mode wraps it rather than forking it.
- Image files are content-hash named, so `path.exists()` proves bytes identical.
- Google's PDF export is not byte-stable (metadata churn), so PDF refresh must be
  gated on the markdown having changed, not on comparing PDF bytes.
- The markdown export *is* byte-stable for an unchanged doc, so a raw-export hash
  cached in memory lets idle watch cycles skip the docx download, Pillow matching,
  and PDF entirely.

## Steps

### Phase A — Change-guarded writes (applies to all runs, not just watch) (DONE 2026-08-20)

- [x] Page: build the page text as today, compare to the file on disk, write only
      when different (small `write_if_changed(path, text) -> bool` helper).
- [x] Images: skip `write_bytes` when the content-hash-named file already exists.
- [x] PDF: download only when the page content changed **or** the PDF file is
      missing (heals a fresh checkout without churning on every run).
- [x] Verify idempotence: run a full `tools chem policy` sync twice; the second
      run must leave `git status` and file mtimes untouched.
      (Verified: run 1 synced one real change in `pecvd.md`; run 2 wrote
      **zero** files — no fresh mtimes under `docs/`, `ruff` clean,
      `mkdocs build --strict` passes.)

### Phase B — Status reporting from the sync path (DONE 2026-08-20)

- [x] `sync_row` returns a status (`SYNCED` / `UNCHANGED` / `SKIPPED`) instead of
      `bool`; `sync_section` aggregates and returns counts
      (summary line: `synced 0, unchanged 4, skipped 0`).
- [x] Quiet the chatty per-doc prints ("downloading markdown ...") when a doc
      turns out unchanged; keep them (and the image-upgrade / dropped-image
      warnings) when something actually synced. (Each doc prints one result
      line — `name: unchanged` or `name: WROTE path` — so long one-shot runs
      still show progress; watch cycles will suppress these in Phase C.)
- [x] Redefine the exit-code rule: exit 1 only when nothing syncable matched
      the selection (verified: typo'd `--only` exits 1 with
      "No syncable documents matched."; unchanged runs exit 0).

### Phase C — `--watch` loop (DONE 2026-08-20)

- [x] `--watch [SECONDS]`: argparse `nargs="?"`, `const=20`, `default=None`
      (absent = one-shot, unchanged behavior). Floor the interval at 5 s so a
      typo can't hammer Google's export endpoints (verified: `--watch 1` runs
      at 5 s).
- [x] Loop: re-run the selected sections/filters, print one summary line per
      cycle, e.g. `[15:01:18] synced 0, unchanged 1, skipped 0`, sleep, repeat.
      Per-doc "unchanged" lines and section headers are suppressed in watch
      cycles; WROTE lines, upgrade notes, and warnings still show.
- [x] Idle-cycle fast path: cache the raw markdown-export hash per doc id
      (in memory); on a hash match (and page + PDF present on disk), report
      `UNCHANGED` without downloading the docx or PDF.
- [x] Re-fetch the registry CSV each cycle (cheap; picks up new sheet rows live).
- [x] Resilience: request errors print and retry next cycle. SIGINT/Ctrl+C
      prints "Stopped." and exits 0 (verified via `timeout --preserve-status`).
      A watch selection matching nothing exits 1 after the first cycle instead
      of looping forever.
- [x] `uv run ruff check .` / `uv run ruff format .` clean;
      `uv run mkdocs build --strict` passes.

### Phase C review gate — STOP for sign-off

- [ ] With `uv run mkdocs serve` running: `uv run python scripts/sync_gdocs.py
      tools --only AFM --watch`, edit the AFM doc, confirm the local page
      refreshes within a cycle.
- [ ] Confirm idle cycles do NOT trigger a `mkdocs serve` reload.
- [ ] Ctrl+C exits cleanly; one-shot runs behave exactly as before.
- [ ] Decision: proceed to staging publish / adjust / stop here (local-only
      watch is already useful on its own).

### Phases D–E — SUPERSEDED 2026-08-20

The staging-repo publish (`--deploy` to a `nanodocs-preview` Pages repo) and
the GitHub Actions backstop were replaced before implementation by an
interactive preview server — see `2026-08-20-staff-preview-server.md`. That
server gives staff a doc picker and ~10–20 s live preview instead of a ~1–2 min
auto-deployed staging site, and reuses the Phase A–C pipeline directly.

### Phase F — Documentation

- [x] README sync-script section: add the `--watch` example to the "Run it
      with" block, plus a note on change-guarded writes. (Done early,
      2026-08-20, alongside Phase C.)
- [x] Remaining items (staff-preview README section, final verification) moved
      to the preview-server plan, which now owns the staff-facing workflow.

## Known limits / notes

- **PDF freshness is tied to content changes:** a doc whose text is unchanged
  never re-exports its PDF. Acceptable — the PDF is derived from the same doc.
- **The watch cache is in-memory:** restarting the watcher re-downloads
  everything once, but writes nothing unless content changed.
- **Polling load:** an idle cycle costs one CSV GET per section plus one
  markdown GET per doc. Default 20 s suits `--only <doc>`; when watching all
  sections (the deploy scenario), use ~60 s.
- **Preview latency budget:** watch interval + gh-deploy build/push (~30–60 s)
  + Pages CDN propagation ≈ 1–2 min worst case at a 60 s interval.
- **Stale images accumulate** in `docs/**/img/` when docs change (true today
  as well) — out of scope; a future `--prune` could handle it.
- **Google occasionally re-encodes exported images** (observed 2026-08-20: the
  PECVD hazard pictogram came back with different bytes than an earlier export,
  flipping the content hash). Effect: a rare spurious "synced" cycle for an
  unedited doc, which immediately restabilizes. Harmless; not worth guarding.
- Mid-edit states appear on the preview site by design; that is what staging
  is for. Production remains manual until the Phase D gate decides otherwise.
