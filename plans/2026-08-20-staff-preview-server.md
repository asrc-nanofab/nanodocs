# Build the staff preview server (pick a doc, edit live, watch it render)

**Date:** 2026-08-20
**Status:** Draft
**Branch:** sync-watch-mode (or a follow-up branch after A–C merge)

## Description

Staff need to preview their Google Doc edits as rendered site pages without a
repo, a terminal, or anyone deploying. This server gives them the full loop in
a browser: open the app, pick their document, click "Edit in Google Docs"
(opens the real editor — Google does not allow embedding it), and watch the
converted page auto-refresh beside it within ~10–20 s of each edit.

Decisions made with the user (2026-08-20):

- **Preview only.** Production stays on GitHub Pages, deployed manually via
  `./deploy.sh`. This server never touches production.
- **Hosting-agnostic.** Built to run anywhere Python runs (lab machine or a
  small VM); the host is chosen at deploy time (Phase 4 gate).
- **Supersedes** Phases D–E of `2026-08-20-watch-sync-and-staff-preview.md`
  (auto-deployed staging repo + Actions backstop). The server *is* the staff
  preview.
- No authentication: the docs and sheets are public ("anyone with link"), and
  the server only ever renders what is already public.

Why this is mostly assembled from existing parts (Phases A–C of the watch
plan): the sync pipeline is change-guarded and idempotent, reports
synced/unchanged per doc, and has a cheap unchanged-detection fast path
(markdown-export hash). The server wraps that in a web UI instead of a
terminal. `mkdocs build` takes ~1.5 s, so rebuilding the real site on every
change is affordable — the preview is pixel-identical to production because it
IS the same build.

Architecture (one process, ~200–300 lines on top of `sync_gdocs.py`):

| Piece | What it does |
| --- | --- |
| FastAPI app (`scripts/preview_server.py`) | Serves everything below on one port |
| Index page `/` | All registered docs grouped by section, from the registry sheets |
| Session page `/preview/{page-slug}` | "Edit in Google Docs" button + iframe of the built page + JS that polls and reloads the frame on change |
| Status API `/api/status/{page-slug}` | Returns the page's content hash; each poll marks the doc "active" |
| Static mount | The `mkdocs build` output (`site/`, already gitignored) |
| Watcher thread | The existing sync loop: all docs every ~60 s, docs with an active session every ~10 s; on any change, rebuild the site |

Key behaviors:

- Sessions are implicit and in-memory: a doc is "active" while its status
  endpoint has been polled in the last few minutes (i.e. someone has the
  session page open). No login, no state to persist, restarts are harmless.
- If a rebuild fails (e.g. a doc edit produces broken markdown), the server
  keeps serving the last good build and shows the error on the session page —
  a bad edit must never take the preview down.
- Doc identity in URLs is the page path slug (e.g. `tool_sops/metrology/afm`),
  which maps 1:1 to the built HTML.

## Steps

### Phase 1 — Make the sync pipeline importable (small refactor)

- [ ] Extract registry-CSV fetching from `sync_section` into a reusable
      `fetch_rows(section)` so the server can cache rows and call `sync_row`
      directly for fast per-doc polling.
- [ ] Confirm `sync_gdocs.py` imports cleanly as a module (no side effects at
      import time); keep the CLI behavior byte-identical.
- [ ] `uv run ruff check .` clean; one-shot and `--watch` behavior unchanged.

### Phase 2 — Server core

- [ ] `uv add fastapi uvicorn`.
- [ ] `scripts/preview_server.py`: app skeleton, static mount of `site/`,
      background watcher thread reusing the sync functions (global ~60 s
      interval), `mkdocs build` on any synced change, last-good-build
      protection.
- [ ] Index page: sections → doc names → session links, refreshed from the
      registry each watcher cycle. Clean, simple styling; no JS framework.

### Phase 3 — Live session view

- [ ] Session page per doc: "Edit in Google Docs" (the doc's `/edit` URL,
      opens a new tab) + iframed site page.
- [ ] `/api/status/{slug}`: page content hash + marks the doc active; active
      docs poll Google every ~10 s instead of ~60 s.
- [ ] Frame-reload JS: poll status every few seconds, reload the iframe when
      the hash changes. Show last-sync time and any conversion warnings.

### Phase 3 review gate — STOP for sign-off

- [ ] Run locally: `uv run python scripts/preview_server.py`, walk the real
      staff flow — index → pick doc → edit the Google Doc → page refreshes
      in ~10–20 s.
- [ ] Kill/restart the server mid-session; confirm graceful recovery.
- [ ] Break a doc deliberately; confirm the last good build keeps serving.
- [ ] Decision: UI/latency acceptable? Adjust before hosting.

### Phase 4 — Deployment (host decided here)

- [ ] Pick the host: lab machine on LAN (free, LAN-only) vs small cloud VM
      (~$5/mo, public URL).
- [ ] Write the run recipe for the chosen host (systemd unit or equivalent so
      it survives reboots); set the final staff URL.
- [ ] Confirm outbound access to docs.google.com from the host.

### Phase 5 — Documentation

- [ ] README: "Staff live preview" section — the URL, the workflow, and where
      the server runs; note production deploys remain manual.
- [ ] Update `2026-08-20-watch-sync-and-staff-preview.md`: mark D–E superseded
      by this plan (done at planning time), fold its Phase F leftovers in here.
- [ ] Final `uv run ruff check .` / `format .`, `uv run mkdocs build --strict`.
- [ ] User reviews and commits.

## Known limits / notes

- **Editing happens in Google Docs, not in our app** — Google forbids
  embedding its editor. The session page makes the two-pane workflow one click.
- **Preview latency** ≈ active-poll interval (10 s) + export/convert/build
  (~3–5 s): call it 10–20 s from pausing typing to the frame reloading.
- **Requires an always-on Python host** — static hosts (GitHub/Cloudflare
  Pages) cannot run this. Until Phase 4 lands, the server can run ad hoc on
  the maintainer's machine like `--watch` does today.
- One watcher thread serializes all syncs and builds: no races, and load on
  Google stays bounded regardless of how many staff have sessions open.
- The `--watch` CLI stays useful for repo-holders; the server reuses the same
  functions rather than replacing them.
