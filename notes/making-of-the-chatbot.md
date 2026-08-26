# Making of the NanoDocs chatbot

Personal build log, high level. The reader-facing explanation of how the
chat works is on the site (`docs/authoring/how_chat_works.md`); the full
decision trail with dates and review gates is in
`plans/2026-08-23-cloudflare-docs-agent.md`. This is the story version:
what was built at each step, and what is actually happening under the hood.

Built 2026-08-23, from AI Search instance to live deploy, in one day.

## The shape of the thing

Three Cloudflare products, one job each:

| Piece | Product | Job |
| --- | --- | --- |
| Search index | **AI Search** (instance `nanodocs`) | Crawls the published site, chunks and embeds every page, answers "which passages match this question?" |
| Model | **Workers AI** (`glm-4.7-flash`) | Reads the retrieved passages and writes the answer |
| Brain + memory | **Agents SDK** (`ChatAgent` Durable Object) | One conversation per visitor; holds messages, calls search as a tool, streams the reply |

One constraint decided the architecture early: the docs site is a
**Cloudflare Pages** project, and Pages cannot host a Durable Object. So
the chatbot is a **sibling Worker** (`agent/` in this repo, its own
deploy), and the site's widget talks to it cross-origin.

```text
Browser widget ── WebSocket ─▶ Worker (nanodocs-agent)
                                 └─ ChatAgent DO (one per conversation)
                                      ├─ messages in SQLite (survive refresh)
                                      ├─ tool: searchDocs ─▶ AI Search
                                      └─ GLM streams the answer back
```

## Step 1 — AI Search on the dashboard (no code)

Created the `nanodocs` AI Search instance pointing at a **website crawl
of nanodocs.pages.dev via the sitemap** (51 pages). What it does on its
own: fetches every page, splits it into chunks, embeds each chunk, and
serves **hybrid retrieval** — vector similarity and keyword (BM25) search
run in parallel and the ranks are fused. Verified in the dashboard
playground before writing any code: 51/51 pages indexed, answers looked
sane.

Re-syncs on a ~6-hour cycle, so doc edits reach the bot within a few
hours without anyone touching the index.

## Step 2 — Fixing what the crawler actually ate

First real test from code showed the classic website-crawl failure: the
top result for "sputtering deposition" was **page chrome** — nav sidebar,
"Skip to content", doctype — because every page carries the same
navigation tree and it matches everything. The fix was on the dashboard,
not in code: a **content selector** (`article.md-content__inner`) so only
the article body gets chunked, plus a bigger chunk size (768). Lesson
that kept repeating: when answers are bad, it's almost always an **index
problem, not a bot problem**.

## Step 3 — The agent Worker (`agent/`)

Scaffolded from Cloudflare's `agents-starter` template into `agent/` —
its own `package.json` and `wrangler.jsonc`, deployed separately from the
site. The heart is one class in `src/server.ts`:

- **`ChatAgent extends AIChatAgent`** — each conversation is one Durable
  Object instance (named by a browser-generated session id) with its own
  SQLite storage. Refresh the page, the messages are still there.
- **One tool: `searchDocs`** — calls AI Search's `search()` (retrieval
  only; generation stays with our model and our prompt).
- **The loop per question:** model thinks → searches → maybe searches
  once more with a tighter query → writes the answer from the chunks,
  citing page URLs. Hard caps in code, because the prompt alone doesn't
  hold: max 2 searches per turn, 4 model steps, 20 turns/minute, model
  sees only the last ~5 turns of history.
- **Model: `@cf/zai-org/glm-4.7-flash`** — cheap, handles tool calling
  and multi-turn. (This choice got interesting later — see headaches.)

## Step 4 — The widget

The site is Zensical/Material, not React, so the widget is **vanilla JS**
(`agent/widget/chat-widget.js`), bundled by esbuild into
`overrides/javascripts/chat-widget.js` (`npm run build:widget`) and
loaded on every page via `mkdocs.yml`. What it does:

- Floating chat button → panel; conversation id in `sessionStorage`, so
  the thread follows you across pages and survives refresh, and dies
  with the tab.
- Speaks the **Agents WebSocket protocol** directly: sends the message
  list, receives stream chunks, patches the streaming bubble in place
  per token.
- **Citation cards are parsed from the search tool's outputs, never from
  the model's prose** — the model omits or mangles URLs too often to
  trust. Later refinement: show only the pages the model actually cited
  in its answer (fall back to everything retrieved if it cited nothing).
- Live activity label next to the typing dots — "Thinking…" /
  "Searching: <query>" — because the model spends most of its time
  reasoning silently and it looked hung.
- Polish that only came from real click-throughs: don't yank the scroll
  down while the visitor reads upward mid-stream; attach citation cards
  only after the answer finishes so the text doesn't jump.

## Step 5 — The agent headache (a day of debugging in one afternoon)

Worth recording because every one of these looked like "the chat is
broken" and none of them were the same problem:

1. **The frozen site.** Chat "stopped working" — actually the local
   `zensical serve` had been suspended with Ctrl+Z, holding port 8000
   while answering nothing. The chat backend was fine.
2. **The phantom second server.** Chatting at `localhost:5174` seemed
   "smarter and faster" than the widget. There was no second server —
   5174 was Cursor's port-forward of the same Worker. The perceived
   difference was a fresh conversation (no piled-up history) plus the
   playground UI showing the model's reasoning stream. Led to two real
   fixes: cap the history sent to the model, show activity status in
   the widget.
3. **The real one: model endpoint degradation.** GLM 4.7-flash went from
   ~12 s per question to **1–2 minutes per model call** for ~15 minutes,
   then recovered on its own. Diagnosis showed AI Search stayed fast
   throughout — only the model calls stalled. And the obvious fix
   ("just swap models") turned out to be unavailable: Llama models
   respond instantly through the same pipeline but **cannot make our
   tool calls** — every `searchDocs` invocation errors. In this
   architecture, GLM is load-bearing. The escape hatch, if latency ever
   matters enough, is an architecture change — one `aiSearch()` call
   where AI Search does retrieval *and* generation (no tool calling at
   all) — parked in `plans/2026-08-23-aisearch-single-call.md`, gated on
   watching production first.

## Step 6 — Deploy

**2026-08-26:** this section was easy to forget. The runbook is now
`notes/deploying-the-chat.md`. Push updates Pages only; the model
changes only after `cd agent && npm run deploy`.

Two deploys, easy to conflate:

1. **The Worker**: `cd agent && npm run deploy` → live at
   `https://nanodocs-agent.nanofab.workers.dev`. Carries the DO
   migration and the AI + AI Search bindings. Smoke-tested with a curl
   to `/agents/chat-agent/smoke-test/get-messages` → `[]`.
2. **The site**: merge to `main` → Cloudflare Pages builds and deploys.
   The widget only renders on hostnames it knows (`AGENT_HOSTS` map in
   the widget source), so production needed one more commit adding
   `nanodocs.pages.dev → nanodocs-agent.nanofab.workers.dev`, plus the
   CORS allowlist on the Worker already naming the pages.dev origin.

Deploy-day gotchas, so future-me smiles knowingly: the PR merged on
GitHub while the local clone still thought `main` was weeks old (fetch
before panicking), and the production host wiring was sitting
uncommitted in the working tree while the "final" deploy built without
it.

## Step 7 — The two-mode switch (same evening)

The "escape hatch" from step 5 didn't stay parked. Rather than an
experiment branch, the Worker got a **`CHAT_MODE` toggle** — both answer
paths live in `src/server.ts` and one string picks at runtime:

| Mode | What happens per question |
| --- | --- |
| `toolloop` (production default) | The original agent loop: model reasons → `searchDocs` → maybe again → writes the answer. |
| `aisearch` | **One `chatCompletions()` call** on the AI Search binding: retrieval + generation in a single pass, generation model chosen in the **dashboard**, not in code. |

Flip it in `agent/wrangler.jsonc` (`vars.CHAT_MODE`) + redeploy; locally
in the gitignored `agent/.dev.vars` + dev-server restart. Notes from the
build:

- The legacy `aiSearch()` method is deprecated — on the new `ai_search`
  binding the one-call path is `chatCompletions()`. It streams the
  retrieved chunks *before* the answer tokens, so the Worker re-emits
  them as a synthetic `searchDocs` tool part in the exact
  `[n] url (score s)` format the widget already parses — **zero widget
  changes**, citation cards and persistence just work.
- The system prompt is NOT a dashboard setting: it rides along as a
  `role: "system"` message on every call, so prompt control stays in
  code for both modes.
- Measured on the HF-PPE question set: tool loop with GLM = **47 s to
  first token**; aisearch with Llama 3.3 fast = **2–4 s to first token,
  4–9 s total**, including a correct context-aware follow-up answer
  ("do I still need the face shield for a quick dip?").

## Step 7½ — Model roulette

The single-call architecture moves the model choice to the dashboard
picker, which triggered an evening of A/B:

- **GLM 4.7-flash** as aisearch generator: 27–90 s to first token —
  the degraded endpoint again, now isolated as purely a model problem
  (retrieval was ~4 s throughout).
- **Llama 3.3 70B fast**: the 2–4 s numbers above, but answer quality
  judged not good enough.
- **`gpt-oss-120b` in the tool loop** — notable: the first non-GLM
  model that drives `searchDocs` correctly, so GLM is no longer
  uniquely load-bearing. But 15–29 s per turn, one truncated answer,
  and `【2†L2-L5】`-style citation junk. Tool loop stays slow regardless
  of model — it's the call count.
- **External models (GPT-5.6 Luna / Gemini)**: AI Search reaches them
  through the **AI Gateway** connected to the instance — store the
  provider key in the gateway (BYOK), pick the model under Generation,
  billing goes to the provider key. The tool loop was also rewired to
  `@ai-sdk/openai` (`gpt-5.6-luna`), either direct (key in a Worker
  secret) or through the gateway (`OPENAI_BASE_URL` + a Cloudflare
  API token with AI Gateway Run permission).

## Where it stands / what's next

- Live on `https://nanodocs.pages.dev`, anonymous, rate-limited, no
  accounts. Answers only from published pages; says "I don't know"
  when retrieval comes back empty.
- Watching for: volume and cost, empty retrievals, abuse (escalation
  path: tighter caps, then Turnstile).
- **Production still runs `toolloop`**; the mode switch and model
  experiments are uncommitted local work. Current blocker on the
  external-model test: `AiSearchError: Internal Error` at generation —
  the Generation model must belong to a provider whose key is in the
  *connected* gateway (as of this writing the picker pointed at Gemini
  while only an OpenAI key was stored). Decision criteria and the full
  measurement table are in `plans/2026-08-23-aisearch-single-call.md`.
