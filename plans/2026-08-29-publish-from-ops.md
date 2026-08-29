# Publish NanoKnow from CI and a facility-ops Reload button

**Date:** 2026-08-29
**Status:** Phase B in progress
**Branch:** none yet

## Description

Staff edit Google Docs; the live site (`https://nanodocs.pages.dev`) only
updates after someone runs `scripts/sync_gdocs.py`, uploads changed PDFs to
R2, commits, and pushes `main`. That last mile is still a terminal. This
plan replaces it with a **publish pipeline in this repo** and a **control
plane in facility-ops** (`asrc-nanofab/facility-ops`).

Split, not a merge:

| Side | Owns | Does not own |
| --- | --- | --- |
| nanodocs GitHub Action | Sync, R2 put, commit of generated files, push `main` (Pages deploys) | Staff UI, Postgres, who clicked |
| facility-ops | Registry list, stale yes/no, Reload this / Reload all, audit | Conversion, git, Wrangler, `zensical` |

Do **not** run `sync_gdocs.py` inside Django. facility-ops already runs
ingest **in-process and synchronously** (`ops` Data Syncs). This job writes
another git tree and talks to R2; a full `tools chem policy` run can take
minutes. That is CI. The Reload button **dispatches** the Action the way a
Data Syncs slug selects a command — the browser never supplies a shell
string.

**Decided 2026-08-29:** the production path is an Actions poll every
**15 minutes**. Idle ticks must not commit. When a Google Doc’s export
hash changes, the job syncs, puts changed PDFs on R2, commits generated
files, and pushes `main` (Pages deploys). Expected load: at most one
doc in edit, for about an hour → about **four** production deploys in
that hour, then idle again. Repo is **public**, so Actions minutes are
free. `workflow_dispatch` / facility-ops Reload stay as “do it now”
(don’t wait for the next tick).

The August preview plans kept production fully manual so mid-drafts
never went live. That is relaxed here on purpose: a 15-minute tick can
publish an in-progress SOP. Acceptable for this lab’s edit pattern.

`--watch` and the unfinished preview server stay the **edit** loop. This
plan is the **production publish** loop.

### What already exists (do not redo)

- Sync is change-guarded: SHA-1 of the public Markdown export; PDFs
  re-export only when the cleaned body changed (Google’s PDF bytes are not
  stable). Idle re-runs write nothing.
- `--only` / `--category` already limit a run.
- A push to `main` already deploys Cloudflare Pages
  (`zensical build --strict && rm -rf site/assets/pdfs`).
- facility-ops has the button + audit pattern (`ops.actions`, `SyncRun`,
  overlap guard, `StaffRequiredMixin`) and public-sheet ingest
  (`onboarding`). Native Google Docs have **no** `md5Checksum`; Drive
  `files.get` often 404s for “anyone with the link” unless the service
  account is shared on the file. v1 staleness uses the **same unauthenticated
  export hash** the sync already computes.

### v1 defaults (change at a review gate, not in code)

| Decision | v1 | Why |
| --- | --- | --- |
| Production trigger | `schedule` every 15 minutes (`*/15 * * * *`) | Automatic; GitHub’s floor is 5 min and `*/15` is reliable enough |
| On-demand trigger | `workflow_dispatch` (GitHub UI, then facility-ops Reload) | Publish now, don’t wait for the next tick |
| Scheduled publish | On in Phase B, after an idle no-commit proof | This *is* the publish path, not a late backstop |
| Change detector | Persist export SHA-1 per doc id in a committed sidecar | No Google credentials; facility-ops can read it from `main` |
| Per-row Reload | Dispatch with `sections` + `only` | Same as today’s CLI |
| Reload all / Reload stale | One full `tools chem policy` dispatch | Unchanged docs are a no-op; no new `--only` list flag |
| New / unmapped docs | Visible as “not on the site”; Reload skips them | Chem/policy still need `CHEM_PAGE_MAP` / `POLICY_PAGE_MAP` and `nav:` |
| Commit scope | Generated pages, `docs/**/img/`, `docs/assets/pdfs/`, the sidecar | Never auto-commit `mkdocs.yml`, `scripts/`, `overrides/` |
| Idle run | Exit 0, no commit, no R2 | Empty commits are forbidden |
| Drive API / webhooks | Out of scope | Sharing and channel-renewal cost for no v1 gain |

### Affected areas

| Area | Repo | What changes |
| --- | --- | --- |
| `scripts/sync_gdocs.py` | nanodocs | Write/read a durable export-hash sidecar; keep CLI identical |
| `.github/workflows/` | nanodocs | First site workflow: sync → R2 → commit → push |
| GitHub secrets | nanodocs repo settings | Cloudflare token (+ account id if Wrangler needs it) |
| New Django app | facility-ops | Registry rows, freshness, Reload, home-page card |
| `ops.SyncRun` or sibling | facility-ops | Audit for dispatches (who, inputs, outcome) |
| README / runbook | both | 15-minute Action is the publish path; Reload / terminal are fallbacks |

## Steps

### Phase A — Durable export hashes (nanodocs)

The watch-mode cache is in-memory and dies with the process. CI and
facility-ops need the last **published** export SHA-1 on `main`.

- [x] Add a small committed sidecar at the repo root (e.g.
      `.sync-state.json`), **not** under `docs/` (Zensical must not serve
      it). Shape: doc id → `{section, name, export_sha1}`. Only rewrite a
      key when that doc’s export hash actually changed, so idle syncs do
      not dirty the file.
      Done 2026-08-29: `SYNC_STATE_PATH` in `scripts/sync_gdocs.py`;
      38 keys after a full `tools chem policy` (21 tools, 12 chem, 5
      policy). Two chem sheet names share one Google Doc id (see Known
      limits), so 39 processed rows collapse to 38 hashes.
- [x] Update the sidecar from `sync_row` after a successful pipeline
      (including `UNCHANGED` once the hash is known and the page+PDF exist).
      Seed missing keys on the first run after this lands.
- [x] CLI, `--watch`, and change-guarded writes stay byte-identical for
      pages/images/PDFs. The sidecar is the only new write.
      First run also rewrote many pages/PDFs (overdue sync / image
      re-export), which is existing sync behavior, not the sidecar.
- [x] `uv run ruff check .` and `uv run ruff format .`.
- [x] One local `tools chem policy` run writes the sidecar; a second run
      leaves it and the rest of the tree untouched.
      Verified: run 2 reported `unchanged` only (21+13+5), sidecar SHA-1
      and `git status` identical to post-run-1.

### Phase A review gate — STOP for sign-off

- [ ] Sidecar contents look right for a handful of known docs (tools +
      one chem + one policy).
- [ ] Decision: proceed to the Action / adjust the file shape / abandon.

### Phase B — Publish Action (nanodocs)

First time anything other than a person pushes generated content to
`main`. Secrets and a dry “idle” run come **before** a live content push.

- [x] Add `.github/workflows/sync-and-publish.yml`.
      Triggers: `workflow_dispatch` **and** `schedule: cron: "*/15 * * * *"`.
      Leave the schedule in the file from the start, but do not merge to
      `main` until the idle dispatch in the review gate has proven
      no-commit. Dispatch inputs: `sections` (default
      `tools chem policy`), `only` (optional, exact registry name).
      Scheduled runs always sync all three sections (no `only`).
      Done 2026-08-29: workflow + `scripts/ci_publish.sh`. Push target is
      `GITHUB_REF_NAME` (the branch the job ran on), not hardcoded
      `main`, so a dispatch from this branch cannot overwrite `main`.
      Cron still only fires once the file is on the default branch.
- [x] Job: checkout → `uv` → sync → `zensical build --strict` → R2 for
      changed PDFs only → commit generated paths + sidecar or print
      `unchanged`. `site/`, `.venv/`, Wrangler cache stay untracked.
- [ ] Permissions: `contents: write`. If branch protection on `main`
      blocks `GITHUB_TOKEN`, stop and use a fine-grained PAT stored as a
      secret — do not weaken protection in this plan.
- [ ] Secrets (user creates in the nanodocs repo; do not put values in
      git): Cloudflare API token that can write `nanodocs-pdfs`, plus
      `CLOUDFLARE_ACCOUNT_ID` if Wrangler requires it. Document the
      dashboard clicks in the README when this phase lands.
- [ ] Commit as `github-actions[bot]`. Message says why (e.g. “Sync
      Google Docs (policy: Safety Manual)”), not a dump of filenames.
- [ ] Do not commit `site/`, `.venv/`, or Wrangler cache.

### Phase B review gate — STOP for sign-off

User-run; this is the first production write from CI.

- [ ] Idle dispatch (no Google edits): job green, **no** commit, **no** R2
      put.
- [ ] One real `--only` (a doc you are willing to republish): sidecar
      and/or page/PDF update; R2 key matches
      `docs/assets/pdfs/<section>/…`; Pages build green; live page and
      View PDF match the doc.
- [ ] Confirm the commit touched only generated paths + sidecar.
- [ ] After that, merge so the 15-minute schedule is live. Watch the
      next few scheduled ticks: idle → green, no commit. Optional: edit
      one doc for a short stretch and confirm ≤ one deploy per tick
      (~4/hour), then idle again.
- [ ] Decision: leave `*/15` on / slow it down / disable schedule and
      keep dispatch only. facility-ops (C–D) can wait; the site already
      updates on its own.

### Phase C — Registry list + staleness (facility-ops)

Lives in `asrc-nanofab/facility-ops`. New source app, not another Data
Syncs card: this is a document table, not “run the Formstack ingest.”

- [ ] App name `nanodocs` (module), UI label **NanoKnow**. Card on the
      dashboard home under Data Sources. Architecture row + `docs/setup.md`
      naming stay consistent (hyphens on GitHub, module `nanodocs`).
- [ ] Model: one row per registry sheet row (section, name, category,
      doc id, mapped site path or empty, `export_sha1` last seen, 
      `published_sha1` last read from this repo’s sidecar on `main`,
      timestamps). Upsert-only ingest. No delete-on-missing-row in v1
      (same caution as other catalogs): skip or mark absent, do not
      destroy history.
- [ ] Connector, not views: public CSV of the three sheets (URLs can
      match `SECTIONS` in `scripts/sync_gdocs.py`; duplicate the URLs in
      facility-ops settings rather than importing this repo). A second
      small client GETs
      `https://raw.githubusercontent.com/asrc-nanofab/nanodocs/main/.sync-state.json`
      (or the sidecar path chosen in A).
- [ ] Commands: `sync_nanodocs_registry` (sheet → rows); 
      `check_nanodocs_freshness` (export SHA-1 per row + sidecar
      `published_sha1`; set stale when they differ). Both idempotent,
      counts-only stdout (ops panel convention).
- [ ] List page: django-tables2 like the other sources. Columns: name,
      section, category, on-site link (if mapped), stale, last checked.
      Unmapped chem/policy (and tools that need `TOOL_PAGE_OVERRIDES`)
      show **not on the site** — no Reload for those rows.
- [ ] Staff-only. No Reload yet. No GitHub token yet.
- [ ] Tests: anonymous redirect, staff 200, upsert, unmapped row has no
      publish action. ruff + `manage.py check`.

### Phase C review gate — STOP for sign-off

- [ ] Table matches the three sheets; a known mapped SOP links to the
      live page; a known unmapped-or-linkless row is labeled correctly.
- [ ] Freshness: after a local Google-invisible wait, hashes match for
      idle docs; a doc you edit in Google goes stale without publishing.
- [ ] Decision: proceed to Reload / adjust columns / abandon the app and
      keep Phase B as GitHub-UI-only.

### Phase D — Reload dispatches the Action (facility-ops)

- [ ] Settings: repo `asrc-nanofab/nanodocs`, workflow filename from
      Phase B, token from env (e.g. `NANODOCS_DISPATCH_TOKEN`). Token
      lives in `.env` only; never logged, never stored on `SyncRun.args`.
- [ ] Connector: GitHub
      `actions/workflows/<file>/dispatches` (and optionally a run lookup
      so the page can say “queued / failed”). Read-only except that
      dispatch.
- [ ] Buttons: per-row **Reload** (fixed `sections` + that row’s exact
      name as `only`); page-level **Reload all** (default sections, no
      `only`). Browser sends a row id or a slug from a server-side
      registry — same boundary as `ops/actions.py`.
- [ ] Audit: reuse `ops.SyncRun` **or** a sibling run table on this app
      if coupling to `ops` is uglier than a second model. Who, when,
      inputs (section/name only), GitHub run URL if known, success. Overlap
      guard so two Reloads of the same doc (or Reload all vs a row) do not
      stack blindly.
- [ ] POST is **not** `call_command(sync_gdocs)`. Dispatch and redirect
      (or short poll). Do not hold a WSGI worker for the full sync+Pages
      build.
- [ ] Optional: one Data Syncs button “Refresh NanoKnow registry /
      freshness” that runs the two management commands — registry ingest
      is a normal ops-shaped action. **Publish** stays on the NanoKnow
      page.
- [ ] Tests: unknown id 404, unmapped row 404, dispatch called with
      server-built inputs, token absent → ImproperlyConfigured / recorded
      failure, no 500.

### Phase D review gate — STOP for sign-off

- [ ] Reload one mapped doc from the facility-ops page; Phase B job
      runs; live site updates; audit row is right.
- [ ] Reload all with nothing stale: Action no-ops; no junk commit.
- [ ] Unmapped row has no working publish path.
- [ ] Decision: Reload is a useful “now” button / skip D and keep
      GitHub UI + the 15-minute poll.

### Phase E — Docs

- [ ] nanodocs `README.md` Deploying / “After a Google Doc changes”:
      wait up to 15 minutes (or Run workflow / Reload). Terminal `sync`
      + wrangler + push remains the fallback. New-doc steps (maps,
      `nav:`, first R2 key) unchanged.
- [ ] `notes/updating-a-google-doc.md` and `AGENTS.md`: same order.
- [ ] facility-ops `docs/architecture.md`, `docs/commands.md`, dashboard
      copy: NanoKnow app, which commands exist, Reload is a dispatch not
      an in-process convert.
- [ ] This plan’s Status → Complete when the user says the runbooks
      match what they actually click.

## Known limits / notes

- **New pages are still a nanodocs code change.** Reload cannot add
  `CHEM_PAGE_MAP` / `POLICY_PAGE_MAP` or a `nav:` entry. The list must
  show that instead of failing opaquely.
- **Chat index** (Cloudflare AI Search) recrawls the live site on its
  own schedule. Publish ≠ instant RAG freshness.
- **Google export jitter** (rare image re-encode) can mark a doc synced
  with no author edit. Harmless; already noted in the watch plan.
- **Pages build budget:** Free is 500 builds/month. Idle ticks do not
  count. One hour of editing one doc ≈ 4 builds. A few such sessions a
  week stays far under 500. A sidecar or export bug that dirties every
  tick would burn the cap — idle no-commit is load-bearing.
- **GitHub cron is best-effort.** `*/15` can drift to 20–30 minutes
  under load. Do not treat it as a metronome.
- **Google export load:** ~39 markdown GETs per tick, 96 ticks/day.
  If Google 429s, skip that tick; do not tighten to `*/5` without
  watching this.
- **Duplicate registry doc ids (found Phase A):** `RCA Clean SOP` and
  `Piranha Clean SOP` both resolve to Google Doc
  `1K4aSGcPMeBPrMqDWhkOVNtJZhjbr77MOZ8vOJRbYkpg`. The sidecar is keyed
  by id, so one hash covers both names (last sheet row wins the
  `name` field). Fix the sheet or the page map; do not fork the
  sidecar key. The live `rca_clean.md` body also looks like the
  Piranha SOP — worth a human look.
- **PDF-only R2 vs Pages:** a body change still needs both the R2 put
  and the markdown commit. The Action must not skip R2 when the PDF
  changed.
- **facility-ops is local `runserver` today.** Reload only needs outbound
  HTTPS to `api.github.com`. No inbound webhook in v1.
- **Token blast radius.** Dispatch token: `actions: write` on
  `asrc-nanofab/nanodocs` only. Cloudflare token: R2 write on
  `nanodocs-pdfs` only. Neither belongs in this git tree.
- **Staff preview server**
  ([`2026-08-20-staff-preview-server.md`](2026-08-20-staff-preview-server.md))
  stays a separate draft. Do not fold preview into this publish path.
- **Do not add** Celery, Redis, FastAPI, or a nanodocs clone inside
  Django.

## Out of scope

- Auto-nav / auto-map for brand-new documents.
- Drive push notifications or `modifiedTime` polling.
- Running `zensical` or Wrangler on the facility-ops machine.
- Changing Cloudflare Pages build command or the R2 binding.
- NanoKnow chat Worker deploy (other plans).
- Git commit/push/amend by the agent; the user commits both repos.

## Open questions

1. **App label.** Plan uses module `nanodocs` and UI “NanoKnow.” Rename
   at the Phase C gate if the home-page card should say “Docs site.”
2. **`SyncRun` vs a dedicated publish-run table.** Prefer reuse if the
   row shape fits; otherwise a small model on the new app. Decide in
   Phase D, not A.
3. **Branch protection on `main`.** Unknown until the first Action push.
   If `GITHUB_TOKEN` is rejected, a PAT is the fix — not force-push and
   not disabling checks.

Poll interval is **15 minutes** (decided 2026-08-29). Not `*/5`.
