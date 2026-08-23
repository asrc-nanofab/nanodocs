# Add a site-wide docs chat via Cloudflare Agents and AI Search

**Date:** 2026-08-23
**Status:** Phase C in progress — drop Material nav from the crawl
**Branch:** none yet (no repo code until Phase B)

## Description

Put a chat window on NanoDocs that answers from the **whole published
corpus**, not the page the visitor happens to be reading. The conversation
lives in a Cloudflare Agent. Retrieval uses Cloudflare AI Search (hybrid
vector + keyword). NanoKnow is out of scope.

This replaces
[`2026-08-20-nanoknow-chat-panel.md`](2026-08-20-nanoknow-chat-panel.md).
Reuse its UX notes later (survive Material instant-nav, citations, mobile,
rate limits). Do not reuse its backend, auth, or domain-move phases.

### What the pieces actually are

Three products, one job each:

| Piece | Cloudflare product | Job |
| --- | --- | --- |
| Chat brain + memory | **Agents SDK** (`AIChatAgent` on a Durable Object) | One conversation per visitor session. Holds messages in SQLite, streams the reply, can call tools. |
| Model | **Workers AI** (v1 default) or an external model via **AI Gateway** | Writes the answer. The Agent calls it; the browser never talks to the model. |
| Search / index | **AI Search** (formerly AutoRAG), hybrid on | Chunks the corpus, embeds it, runs vector + BM25 keyword in parallel, fuses ranks. The Agent calls this as a tool. |

**Vectorize** is the raw vector database underneath-style product. Skip it
for v1. AI Search already chunks, embeds, stores, and (as of 2026-04)
hybrid-searches. Raw Vectorize is the path if we later need custom
embeddings or sub-hour index updates.

**AI Search `aiSearch()`** is the "search + answer in one call" shortcut.
v1 should use **`search()` as an Agent tool** instead, so the Agent (not
AI Search's built-in one-shot generator) owns multi-turn chat, citations,
and "I don't know."

### How a question actually flows

```text
Browser chat window
  └─ WebSocket ─▶ Worker ─▶ routeAgentRequest
                              └─ Agent instance (Durable Object, named by session id)
                                   ├─ this.messages  (SQLite, survives refresh)
                                   ├─ tool: searchDocs ─▶ AI Search.search()  (hybrid)
                                   └─ streamText(model, messages + retrieved chunks)
                                        └─ tokens stream back over the same WebSocket
```

The panel is **not** "explain this page." Current URL may be sent as a
hint ("the visitor is reading the AJA SOP") but retrieval is corpus-wide.
The Agent instance name is a browser-generated session id, not a page
path, so navigating the docs does not start a new brain.

### Hard constraint: Pages cannot host the Agent

This repo is a **Cloudflare Pages** project (`wrangler.jsonc` +
`functions/assets/pdfs/` + `pages_build_output_dir`). Pages can *bind to*
a Durable Object that already exists on a Worker. It **cannot define or
deploy** the Agent class itself.

v1 is therefore a **sibling Worker** (new `wrangler` project, own deploy).
The docs site stays Pages. The widget talks to the Worker.

Do **not** migrate the whole site to Workers + Assets in this plan. That
is a later cleanup if same-origin `/agents/...` becomes worth it.

### Recommended defaults (change at a review gate, not in code)

| Decision | v1 default | Why |
| --- | --- | --- |
| Retrieval | AI Search hybrid (`vector` + `keyword`, fusion `rrf`) | Matches "CF's own search"; tool names and error strings survive better than vector-only |
| Index source, first probe | **Website crawl** of `https://nanodocs.pages.dev` with parse type **sitemap** | Live sitemap exists (51 URLs). Sitemap crawl is the clean page list; discover is the fallback. |
| Index source, if crawl quality is poor | **R2 corpus** of synced `docs/**/*.md` (not the PDF bucket) | Clean markdown chunks; filename → site path for citations. PDFs in `nanodocs-pdfs` duplicate the pages and some may exceed AI Search's 4 MB file cap. |
| Answer path | Agent tool → `search()` → model writes | Real agent; multi-turn; we control the system prompt |
| Model | Workers AI `@cf/zai-org/glm-4.7-flash` | Tool calling + instruction-following at the lowest hosted price. Escalate only if answers are weak (see model pick below). |
| Worker home | Sibling Worker, cross-origin from the Pages site | Required by Pages + DO. Isolated blast radius. |
| Auth | Anonymous + rate limit | Same posture as the old plan; no NanoKnow accounts |
| UI | Site-global window (drawer/modal), vanilla JS via `AgentClient` | Site is Zensical/Material, not React. `useAgentChat` is the React-app path. |
| NanoKnow / `asrc.nanoknow.org` | Deferred | Explicitly out of this plan |

### Model pick (Workers AI hosted, Aug 2026)

This is the **chat** model the Agent calls after search. The embedding
model inside AI Search is separate and stays on the instance defaults.

The job is: call `searchDocs`, stay inside retrieved chunks, cite the
page, say you don't know. That wants **function calling** and tight
instruction-following. It does **not** want a coding model, a 1M-context
model, or a reasoning model that spends tokens "thinking" about an SOP.

| Role | Model | ~price (in / out per M tokens) | Notes |
| --- | --- | --- | --- |
| **v1 default (A4: chosen)** | `@cf/zai-org/glm-4.7-flash` | $0.06 / $0.40 | Cloudflare-pinned. Dialogue, instruction-following, multi-turn tools. 131k context. No extra paid-model gate. Playground bake-off 2026-08-23. |
| If answers are thin | `@cf/openai/gpt-oss-120b` | $0.35 / $0.75 | Stronger general model, still tools, still no special billing gate. May emit reasoning tokens (slower). |
| If you want the "smart" names | `@cf/deepseek-ai/deepseek-v4-flash-0731` | $0.44 / $1.32 | Best DeepSeek on the catalog for this. Tools + agentic. **Workers Paid** (or AI Gateway credits) required. |
| Skip for v1 | `@cf/moonshotai/kimi-k2.6` | $0.95 / $4.00 | Frontier and good at tools, ~10× GLM Flash on output. Overkill until Flash/gpt-oss fail. |
| Skip | `@cf/moonshotai/kimi-k2.7-code` | same as K2.6 | Code-specialized. Wrong job. |
| Skip | `@cf/moonshotai/kimi-k2.5` | — | Deprecated. |
| Skip | Kimi K3 (unified catalog) | third-party | Not a `@cf/` Workers AI model. Different billing/path. |
| Skip | `@cf/deepseek-ai/deepseek-v4-pro-0813`, `@cf/zai-org/glm-5.2` | $1.32–1.40 / ~$4 | Long-horizon / coding flagships. We are not writing code. |
| Skip | `@cf/deepseek-ai/deepseek-r1-distill-qwen-32b` | $0.50 / $4.88 | Reasoning distill, **no function calling** in the catalog. |

Llama 4 Scout (`@cf/meta/llama-4-scout-17b-16e-instruct`, $0.27 / $0.85)
is a fine fallback if GLM Flash's tool calls are flaky — the Agents
examples used it — but it is not the first pick on price or recency.

Try the default vs gpt-oss-120b in the Workers AI playground during
Phase A with the same lab questions. Do not start on Kimi.

### Known fact that affects Phase A

`https://nanodocs.pages.dev/sitemap.xml` is live (HTTP 200, 51 `<loc>`s:
homepage, 5 policy, 27 tool_sops, 14 chemicals, plus signup / authoring /
faq). `robots.txt` already points at it. A docs-fetch tool got HTTP 500
on that URL (bot-ish client); a normal GET does not. Use AI Search parse
type **sitemap**. Fall back to **discover** only if the dashboard cannot
read the sitemap.

### Affected areas (nothing lands until Phase B+)

| Area | Change |
| --- | --- |
| New sibling Worker (location TBD at Phase B) | Agent class, `routeAgentRequest`, AI + AI Search bindings, rate limit |
| Cloudflare dashboard | AI Search instance; later Worker deploy |
| `overrides/` + `mkdocs.yml` extra JS/CSS | Chat window (Phase D) |
| Optional later | R2 corpus bucket + upload step after `sync_gdocs.py` if website crawl quality is poor |

## Steps

### Phase A — Learn the products (no nanodocs code)

Goal: you can explain the three pieces and have seen each one work, before
we write anything in this repo.

- [x] **A1. AI Search in the dashboard.** Instance `nanodocs` (namespace
      `default`). Website crawl of `nanodocs.pages.dev`, sitemap parse,
      static HTML, images off, hybrid on, RRF, Porter/AND, chunk 512 /
      10% overlap, similarity cache off. Playground Search and Chat both
      judged good (2026-08-23).
- [x] **A2. Confirm crawl coverage.** 51/51 sitemap URLs indexed, 0
      errors, 552 vectors, keyword index initialized. Built-in storage
      empty (correct). No Public URL enabled.
- [x] **A3. Agents quick start, throwaway.** `cloudflare/agents-starter`
      via C3 as `agents-playground` (sibling of this repo, not inside
      it). Local `npm run dev` only; persist-on-refresh and
      `/agents/<name>/<instance>` seen. Not deployed, not bound to AI
      Search. Folder can be deleted later.
- [x] **A4. Paper-connect the two, pick a model.** Winner:
      `@cf/zai-org/glm-4.7-flash` (Workers AI playground, 2026-08-23).
      gpt-oss-120b not used. Contract unchanged: Agent calls AI Search
      `search()`, then this model answers from chunks plus
      `this.messages`.

### Phase A review gate — STOP for sign-off

- [x] Hybrid search in the dashboard is good enough to build on (51/51
      crawl; Playground Search/Chat judged good). R2 markdown only if
      that later proves noisy.
- [x] You have seen an Agent conversation persist on an instance name
      (A3 playground)
- [x] Defaults kept: website crawl index, `@cf/zai-org/glm-4.7-flash`,
      Agent tool → `search()` (not `aiSearch()`)
- [x] Decision: proceed to a real Worker (2026-08-23)

### Phase B — Sibling Worker + Agent, no site widget

Isolated Worker. Playground or `wrangler tail` is the UI. Does not touch
`overrides/` or `mkdocs.yml`.

- [x] New Worker project at **`agent/`** in this repo (C3 from
      `cloudflare/agents-starter`, git No, deploy No). Own `package.json` /
      `wrangler.jsonc`; not `~/agents-playground`. `nodejs_compat`, SQLite
      DO migration `v1`, Workers AI `AI` + AI Search instance binding
      `DOCS_SEARCH` → `nanodocs` (`remote: true`). Compat date pinned to
      **`2026-07-28`** (local workerd in wrangler 4.125 maxes there;
      `2026-08-23` crashed Miniflare).
- [x] `AIChatAgent` with `searchDocs` → `this.env.DOCS_SEARCH.search()`.
      Model `@cf/zai-org/glm-4.7-flash`. System prompt: chunks only, cite
      URLs, don't invent.
- [x] `routeAgentRequest(..., { cors: true })` for the local playground.
      Tighten to `127.0.0.1:8000` + `nanodocs.pages.dev` in Phase D/E.
- [x] Caps: query 500 chars, 8 results, 40 persisted messages, 20
      turns/minute **per Agent instance** (not per IP — good enough for
      the playground; per-IP if we see abuse after the widget ships).
- [x] Manual two-turn test against the Phase A index (2026-08-23). Vite
      logs: `searchDocs ... chunks=8` twice. Turn 1 cited
      `https://nanodocs.pages.dev/chemicals/hf_pirahna_hood/` for HF PPE.
      Turn 2 followed up on glove splash using the same SOP (also
      retrieved a gold-etch accident chunk). Citation URLs sometimes
      append heading-slug junk after the path — model, not retrieval.
- [x] `oxfmt` / `oxlint` / `tsc --noEmit` on `src/server.ts`. Do not use
      bare `npx wrangler` from this repo: it walks up to the Pages
      `wrangler.jsonc`. Use `npm run types` / `./node_modules/.bin/wrangler`
      inside `agent/`.

Local UI: `cd agent && npm run dev` → http://localhost:5173/ . Do not
deploy.

### Phase B review gate — STOP for sign-off

- [x] Answers cite real NanoDocs pages and do not invent SOPs (HF PPE
      test). Citations sometimes grow heading-slug junk on the URL.
- [x] Multi-turn follow-up uses prior messages (not a fresh one-shot)
- [x] Decision: **not good enough for the site window yet.** Playground
      query `sputtering deposition process` (2026-08-23, local `:5173`)
      returned Material chrome first: `/tool_sops/` at score 1.000 is
      mostly nav + `<!doctype html>` + Skip to content; PECVD / gold
      sputter / deposition index / silicon etch chunks are the same
      nav tree. Real AJA SOP body is in results 2 and 7. GLM then
      reworded and searched twice. This is the known website-crawl
      chrome problem, not a Worker bug. **Go to Phase C** (content
      selectors on the existing sitemap crawl). Skip R2 unless
      selectors still leave index pages dominating generic queries.

### Phase C — Index quality

Website crawl coverage (51/51) is fine. Chunk *contents* are not.

- [x] Dashboard: content selector `**` → `article.md-content__inner`,
      chunk size 768 / 10% overlap. Recrawl 2026-08-23; three pages
      lagged on Workers AI capacity then retried.
- [x] Re-run AJA/sputter query: hit 1 is AJA tool operation (score
      1.000), not the nav. Evaporator SOPs still appear as weaker
      neighbors (~0.47). One leftover chrome chunk
      (`/tool_sops/deposition/` with doctype) — Worker now drops
      chunks that look like full-page HTML. GLM was doing two
      searches; capped at two searches and four model steps
      (`stepCountIs(4)`), including thinking.
- [ ] Source-doc noise (not the crawl): Gold Sputter Coater Google
      Doc still has SOP Title “Manual Operation of the AJA Orion 8
      Sputter Tool” and Gold abbreviated **Cr**. Fix the Doc, then
      wait for the next crawl — do not hand-edit the generated page.
- [ ] Record the choice in this plan (selectors vs R2)

Skip R2 markdown unless the selector recrawl still ranks index pages
over SOP body for generic tool questions.

### Phase C review gate — STOP for sign-off

- [ ] Coverage and citation links are acceptable for lab users
- [ ] Decision: proceed to the on-site window

### Phase D — Chat window on NanoDocs (local)

- [ ] Vanilla JS/CSS in `overrides/` / `extra_javascript` / `extra_css`.
      Floating control opens a **site-global** window (not a per-page
      TOC companion). Conversation id in `sessionStorage`; mount outside
      Material's swapped content and re-attach on `document$`
- [ ] Transport: `AgentClient` to the Worker `host` (local wrangler URL
      in dev, workers.dev or custom host later). Streaming tokens +
      citation cards from tool results
- [ ] Current page URL sent as optional context only — must not scope
      search to that page
- [ ] Theme (light/dark), mobile, failure states (Worker down, rate
      limited, empty retrieval)
- [ ] `uv run zensical build --strict` passes

### Phase D review gate — STOP for sign-off

- [ ] Local click-through: ask, follow up, navigate mid-answer, dark
      mode, mobile, open a citation
- [ ] Decision: UX good enough to ship?

### Phase E — Ship on nanodocs.pages.dev

- [ ] Deploy the Worker (user-run `wrangler deploy`)
- [ ] Point the widget at the production Worker host; CORS allowlist
      includes the live origin
- [ ] Watch logs for a few days (volume, empty retrieval, abuse)
- [ ] Escalation path if abused: tighter caps, then Turnstile — do not
      build Turnstile until we see abuse

### Phase E review gate — final sign-off

- [ ] Anonymous visitor on the live site can finish a real conversation
- [ ] Plan status → Complete

## Known limits / notes

- **NanoKnow is deferred, not discarded.** Facility-scoped NanoKnow
  retrieval, `asrc.nanoknow.org`, and citation `viewing_url` rewrites stay
  in the old plan if we ever want that ecosystem again.
- **Pages + Agents stay split.** A future "one Worker serves `site/` +
  Agent + PDF binding" migration would make the widget same-origin. Not
  v1.
- **Index freshness is ~6 hours** (AI Search cycle; Force Sync is
  dashboard-only, 30s rate limit). Fine for SOPs. Not fine if we promise
  "synced 5 minutes ago."
- **Website crawl will index chrome** (nav, footer, search UI) unless we
  add content selectors or switch to markdown-in-R2.
- **Public chat is public cost.** Workers AI + AI Search are cheap per
  query but unbounded if scraped. Rate limits are the v1 control.
- **No saved accounts in v1.** Closing the tab (or clearing
  `sessionStorage`) drops the thread. The Agent instance may linger unused
  on Cloudflare; acceptable at this traffic.
- **Do not hand-edit generated SOP pages** to "help" the bot. Fix the
  Google Doc or the index source.
- **Local wrangler types:** always `cd agent && npm run types`. Bare
  `npx wrangler types` from this monorepo can bind the parent Pages
  `wrangler.jsonc` and emit an `Env` with only `PDFS`.
- **GLM Flash citations:** answers cite real pages, but the model
  sometimes appends heading text onto the URL. Fine for Phase B; watch
  in the widget.
