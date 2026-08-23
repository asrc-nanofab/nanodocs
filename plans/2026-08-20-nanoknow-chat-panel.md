# Embed facility-scoped NanoKnow chat in NanoDocs and move to asrc.nanoknow.org

**Date:** 2026-08-20
**Status:** Superseded — 2026-08-23. NanoKnow-backed chat is deferred. Replacement:
[`2026-08-23-cloudflare-docs-agent.md`](2026-08-23-cloudflare-docs-agent.md)
(Cloudflare Agents + AI Search, no NanoKnow).
**Branch:** `nanoknow-chat` (nanodocs); nanoknow changes on its own branch in
`~/dev/nanoknow` (user manages that repo's git)

## Description

Add a NanoKnow chat side panel to the NanoDocs site, answering questions from
the ASRC NanoFab corpus with streaming answers and citations that link back to
NanoDocs pages. Then move the site to `asrc.nanoknow.org`, making NanoDocs the
canonical reading surface for ASRC documents across the whole NanoKnow
ecosystem (Browse page, chat citations, and the docs site all resolve to the
same page URLs).

This is the first concrete step of the federated architecture: per-facility
docs sites (`<facility>.nanoknow.org`) as the organized reading layer, NanoKnow
(`app.nanoknow.org`) as the cross-facility intelligence and discovery layer.

### Key facts discovered (2026-08-20 exploration of ~/dev/nanoknow)

- **The backend needs no retrieval changes.** `POST /retrieve`
  (pipelines, `app/api/retrieve.py`) is a streaming RAG endpoint: hybrid
  pgvector + FTS search, Cohere rerank, `gpt-5.4-mini` answer streamed over
  SSE with multi-turn `messages` support and inline citations.
- **Facility scoping already exists.** `RetrievalFilters`
  (`app/schemas/retrieval_filters.py`) accepts `facility_id: list[str]`;
  both `VectorSearchNode` and `FTSSearchNode` push it into
  `ChunkDBStore._apply_filters` (JSONB `doc_metadata["facility_id"]`).
  ASRC is `cuny-asrc`.
- **SSE protocol** (OpenAI Responses style, parsed today by the webapp's
  `chat-page.tsx`):
  `response.status` → `response.output_text.delta` tokens →
  `response.metadata` (full `CitationResponse` with renumbered answer +
  ordered sources) → `[DONE]`. Errors arrive as
  `{"type":"error","code":"stream_error"}`.
- **Auth today blocks a static site.** `/retrieve` requires HTTP Basic Auth
  with the single shared `BACKEND_API_KEY` (`app/api/deps.py`) — cannot ship
  in public page source. The webapp proxy (`/api/retrieve`) requires a
  BetterAuth session cookie and has **no CORS anywhere in the stack**.
- **Citations currently link to Google Docs.** Each NanoKnow source document
  has `metadata.provenance.viewing_url` (the user-facing link used by Browse
  and citations) and a canonical `source_key` of the form `gdoc:<id>`.
  `scripts/sync_gdocs.py` in this repo knows the same gdoc IDs → page paths,
  so a `source_key → NanoDocs URL` manifest is derivable, not new inference.

### Decisions (from 2026-08-20 discussion)

| Decision | Choice | Rationale |
| --- | --- | --- |
| Auth model (v1) | **Open access**: anonymous, rate-limited, facility-scoped public endpoint | Zero-friction chat for lab users without NanoKnow accounts; keeps the domain choice reversible (no cookie same-site dependency) |
| Session-cookie / OAuth auth | Deferred | Revisit when signed-in features (saved chats, cross-facility scope) are wanted; noted in follow-ups |
| Domain | Course set for **asrc.nanoknow.org** (network-first branding — "people love NanoKnow") | Facility-domain pressure exists but is unresolved; the open-endpoint choice makes a later domain switch an afternoon (DNS + CORS config + manifest re-run) |
| Widget technology | Vanilla JS/CSS in MkDocs `overrides/` + `extra_javascript` | No React needed; MkDocs stays. Extraction into a webapp-served shared widget is a follow-up once UX settles |
| Widget home (v1) | nanodocs repo | Fastest iteration; move to webapp-served script tag when templating for facility #2 |
| URL bridge timing | After the domain move (Phase F) | Avoid writing soon-to-change URLs into NanoKnow's `viewing_url` |

### Affected areas

| Repo | Area | Change |
| --- | --- | --- |
| nanoknow/pipelines | `app/api/` | New public endpoint (Phase B): no Basic Auth, forced facility scope, CORS, rate limiting |
| nanoknow/pipelines | config / env | CORS origin allowlist + rate-limit knobs as env vars (domain switch = config change) |
| nanodocs | `overrides/`, `docs/assets/` or `docs/javascripts/` | Chat panel JS + CSS (Phase C) |
| nanodocs | `mkdocs.yml` | `extra_javascript` / `extra_css` entries; later `site_url` change (Phase E) |
| nanodocs | `scripts/sync_gdocs.py` | Emit `source_key → page URL` manifest (Phase F) |
| nanoknow/pipelines | provenance update path | Apply manifest to `viewing_url` (Phase F; one-off script or admin endpoint — decide then) |
| DNS / GitHub Pages | `asrc.nanoknow.org` | CNAME + custom domain + HTTPS (Phase E) |

## Steps

### Phase A — Validate scoped retrieval (no code)

- [ ] From `~/dev/nanoknow/pipelines`, curl `POST /retrieve` (dev server or
      prod with `BACKEND_API_KEY` via Infisical) with
      `filters: {"facility_id": ["cuny-asrc"]}` and ~10 real ASRC questions
      spanning tools, chemicals, and policy (e.g. AJA sputter SOP steps, HF
      hood rules, after-hours access policy)
- [ ] Judge answer quality and correct scoping (no other facilities' content
      bleeding in; no ASRC content missing because of the filter)
- [ ] Coverage check: query the DB (`./scripts/psql`) to count ASRC source
      documents **missing** `metadata.facility_id` — the filter silently
      excludes them. List any gaps for backfill
- [ ] Capture one full raw SSE transcript and one `CitationResponse` payload
      (save under `plans/` notes or a scratch file) — these define the
      widget's parsing contract in Phase C
- [ ] Cross-check: are all synced NanoDocs docs (per registry sheets) present
      in NanoKnow (`source_key = gdoc:<id>`)? List any missing for ingestion

### Phase A review gate — STOP for sign-off

- [ ] Scoped answers are good enough to put in front of lab users
- [ ] Coverage gaps (missing `facility_id`, missing docs) are known and
      acceptable or backfilled
- [ ] Decision: proceed / tune retrieval first / abandon

### Phase B — Public docs-chat endpoint (nanoknow/pipelines)

Design notes: a new route (working name `POST /docs-chat`) alongside
`/retrieve`, not a modification of it — `/retrieve` stays key-gated for the
webapp. The new route reuses `StreamingRetrievalWorkflow` unchanged.

- [ ] New router: accepts `{query, messages, top_k?}`; **server forces**
      `filters.facility_id` — client-supplied filters ignored/rejected.
      Facility determined server-side from an env-configured
      origin → facility map (e.g. `DOCS_CHAT_ORIGINS =
      https://sng.github.io=cuny-asrc,https://asrc.nanoknow.org=cuny-asrc`),
      so one endpoint serves future facility sites and the domain switch is
      config-only
- [ ] No Basic Auth on this route; all other routes untouched
- [ ] Input caps to bound per-request cost: max query length, max `messages`
      count/size (server already truncates to `MAX_CONVERSATION_MESSAGES`),
      `top_k` clamped to a modest ceiling (e.g. ≤ 20)
- [ ] CORS middleware scoped to this route's needs: allowlist from the same
      env var, `POST` only, no credentials
- [ ] Per-IP rate limiting (e.g. slowapi or equivalent): a per-minute and a
      per-day cap, env-tunable. Confirm the reverse proxy in front of
      uvicorn forwards client IPs (`X-Forwarded-For`) and that the limiter
      trusts it — otherwise all users share one bucket
- [ ] Sanitized errors only (mirror `/retrieve`'s `stream_error` behavior);
      real exceptions to server logs / Langfuse as usual
- [ ] Basic logging of query volume per origin/IP (abuse visibility; also the
      first usage analytics for the docs site)
- [ ] Tests: forced-scope behavior (client can't widen the filter), input
      caps, rate-limit responses, CORS headers
- [ ] Repo gates in nanoknow: lint/format per that repo's standards
- [ ] **User action:** deploy pipelines to Hetzner (ssh + `systemctl restart
      nanoknow-pipelines` per its README)

### Phase B review gate — STOP for sign-off

- [ ] Curl the prod endpoint from a machine with no credentials: streaming
      answer arrives, scope is enforced, `top_k=100` gets clamped
- [ ] Hammer test: rate limit kicks in at the configured threshold and
      recovers
- [ ] Request from a non-allowlisted origin is refused by CORS (browser test,
      not curl — CORS is browser-enforced)
- [ ] Decision: abuse posture acceptable to leave running publicly?
      (Escalation path if not: Turnstile challenge — noted in follow-ups)

### Phase C — Chat panel widget (nanodocs, local)

Vanilla JS/CSS. Reference implementation for event handling:
`webapp/src/components/chat/chat-page.tsx` (port the logic, not the React).

- [ ] Panel UI: floating "Ask NanoKnow" button → right-side drawer with
      message list, input, and NanoKnow branding; closes/reopens without
      losing the conversation
- [ ] Transport: `fetch()` POST + `ReadableStream` SSE parsing (`EventSource`
      can't POST). Handle the four event types from the Phase A transcript:
      `response.status` (searching indicator), `response.output_text.delta`
      (append), `response.metadata` (swap streamed text for
      `citation.answer`, render source cards), `error` / `[DONE]`
- [ ] Multi-turn: maintain `messages` array (current turn last, matching
      `query` — the documented contract); persist conversation in
      `sessionStorage` so Material's **instant navigation** page swaps don't
      wipe the chat; mount the widget outside the swapped content region and
      re-attach via Material's `document$` observable
- [ ] Source cards from `CitationResponse.sources`: title + link
      (`viewing_url` — Google Docs until Phase F flips them to NanoDocs
      pages), citation numbers matching the inline `[N]` markers
- [ ] Theme integration: follow Material's light/dark scheme
      (`data-md-color-scheme`); usable on mobile viewports
- [ ] Config surfaced in one place (endpoint URL) — e.g. `extra` in
      `mkdocs.yml` injected into the page, so facility sites differ only in
      config
- [ ] Graceful failure states: endpoint down, rate-limited (friendly "try
      again in a minute"), empty results ("couldn't find anything" answer
      already comes from the backend)
- [ ] Local dev loop: `mkdocs serve` against the local pipelines dev server
      (dev-only permissive CORS or localhost in the allowlist)
- [ ] `uv run mkdocs build --strict` passes

### Phase C review gate — STOP for sign-off

- [ ] Click-through on `mkdocs serve`: ask, follow up, navigate mid-answer,
      toggle dark mode, resize to mobile, open citation links
- [ ] Streaming feels responsive; citations render correctly against the
      Phase A transcript
- [ ] Decision: UX good enough to ship on the live site?

### Phase D — Ship on the current domain

The widget goes live on the existing GitHub Pages URL first; the domain move
(Phase E) is independent and can slide without blocking this.

- [ ] Add the current production origin to the endpoint's origin → facility
      map (**user action:** config change + service restart on Hetzner)
- [ ] Point the widget config at `https://api.nanoknow.org`
- [ ] `uv run mkdocs build --strict`; **user action:** `./deploy.sh`
- [ ] Live smoke test from a clean browser (no dev state): full conversation,
      citations open, rate-limit message reachable
- [ ] Watch endpoint logs for the first days (volume, abuse, errors)

### Phase D review gate — STOP for sign-off

- [ ] Live chat works for an anonymous visitor on the real site
- [ ] No cost/abuse surprises in the first days of logs
- [ ] Decision: proceed to domain move

### Phase E — Move to asrc.nanoknow.org

- [ ] **User action:** DNS CNAME `asrc.nanoknow.org` → GitHub Pages
      (`<user>.github.io`)
- [ ] Set the custom domain on the GitHub repo (adds `CNAME` file to the
      Pages branch — ensure `deploy.sh` / the gh-pages flow preserves it);
      wait for HTTPS cert provisioning
- [ ] `mkdocs.yml`: `site_url: https://asrc.nanoknow.org/` (site now serves
      at the root — the `/nanodocs/` path-prefix quirk is retired; relative
      links in content are unaffected)
- [ ] Add `https://asrc.nanoknow.org` to the endpoint origin map; keep the
      old origin during transition, remove after confirmation
      (**user action:** config + restart)
- [ ] Verify GitHub's automatic redirect from the old
      `github.io/nanodocs/...` URLs to the custom domain covers existing
      bookmarks/shared links
- [ ] `uv run mkdocs build --strict`; **user action:** `./deploy.sh`;
      full click-through on the new domain including chat

### Phase E review gate — STOP for sign-off

- [ ] Site + chat fully working on `asrc.nanoknow.org`; old URLs redirect
- [ ] Decision: URLs are now permanent — safe to write them into NanoKnow

### Phase F — URL bridge: citations and Browse land on NanoDocs

- [ ] `sync_gdocs.py`: emit a manifest during sync — `source_key`
      (`gdoc:<id>`) → absolute NanoDocs page URL for every synced page
      (JSON; committed or published as a build artifact — decide at
      implementation)
- [ ] nanoknow side: apply the manifest to matching source documents'
      `metadata.provenance.viewing_url` (one-off script vs. small admin
      endpoint — decide then; must be idempotent and re-runnable so future
      domain/path changes are a re-run)
- [ ] Run it; verify in NanoKnow: Browse page cards for ASRC docs open
      NanoDocs pages; chat citations (both on NanoDocs and on
      app.nanoknow.org) link to NanoDocs pages
- [ ] Unmatched documents (in NanoKnow but not synced to NanoDocs) keep their
      Google Docs `viewing_url` — confirm nothing regressed
- [ ] Repo gates: `ruff check` / `ruff format` (nanodocs), nanoknow's own
      lint gates, `uv run mkdocs build --strict` if any docs/config touched

### Phase F review gate — final sign-off

- [ ] The loop is closed: browse, search, and chat all resolve to the same
      NanoDocs pages
- [ ] Re-run story confirmed (edit a page path, re-sync, re-apply manifest,
      link updates)
- [ ] Plan status → Complete

## Known limits / notes

- **Public endpoint = public cost.** Per-query cost is small (gpt-5.4-mini +
  embeddings + Cohere rerank) but nonzero; rate limits are the primary
  control. Escalation path if abused: Cloudflare Turnstile on the endpoint,
  or tighter per-IP caps. Cost visibility via Langfuse + Phase B logging.
- **No signed-in features in v1.** Saved conversations, cross-facility scope
  toggle, and higher limits for account holders all want auth. On
  `asrc.nanoknow.org`, cheap session-cookie reuse (same-site + CORS with
  credentials on the webapp proxy) becomes possible; on a facility domain it
  would need a bearer-token/OAuth flow (BetterAuth supports both). Deferred.
- **Domain politics unresolved.** Facility-domain pressure exists. The open
  endpoint + config-driven CORS + re-runnable manifest keep the switch cheap:
  DNS, one config value, one manifest re-run, 301 from the losing domain.
  Phases A–D are domain-agnostic; only E–F bake URLs in.
- **Widget extraction is the multi-facility enabler.** Once UX settles, move
  the widget into the nanoknow webapp and serve it as one script tag with
  `facility_id`/endpoint as config; facility sites (stanford.nanoknow.org,
  …) then differ only in a config block. Separate follow-up plan, along with
  templating `sync_gdocs.py` (engine vs. facility config) and sync
  automation (cron/CI — a human shouldn't be the scheduler for N facilities).
- **Section-level citations** (deep links to heading anchors on NanoDocs
  pages) become possible if NanoKnow ingests the synced markdown instead of
  capturing Google Docs separately — the "shared corpus" idea. Big follow-up;
  not in scope.
- **Streaming endpoint has no client-disconnect cancellation** (known
  pipelines limitation) — dropped connections leave the LLM call running.
  Acceptable at current traffic; inherited by the public endpoint, where rate
  limits bound the exposure.
- **`wecas.md`-style stubs** and any NanoDocs pages without a source gdoc
  simply won't be citable; fine.
- Cross-repo coordination: pipelines changes live in `~/dev/nanoknow` with
  its own git flow (user commits/deploys there too); this plan is the single
  tracking document for both sides.
