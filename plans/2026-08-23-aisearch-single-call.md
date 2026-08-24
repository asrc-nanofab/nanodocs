# Cut chat latency by moving answer generation into AI Search (one call)

**Date:** 2026-08-23
**Status:** Phase B in progress — both paths wired behind the `CHAT_MODE`
toggle and smoke-tested locally; next: A/B generation models via the
dashboard picker. (Phase A baseline was skipped by user decision — the
GLM latency was judged real enough to prototype now.)
**Branch:** none — the toggle makes an experiment branch unnecessary;
both paths coexist in `agent/src/server.ts`, production stays on
`CHAT_MODE=toolloop` until Phase B signs off.

## Description

The current chat turn is an agent loop: GLM reasons → `searchDocs` →
GLM reasons → optional second search → GLM writes the answer. That is
**three sequential model calls minimum** per question (plus reasoning
time before each), so even a healthy turn takes 12–25 s, and a degraded
model endpoint takes minutes. On 2026-08-23 the Workers AI GLM 4.7-flash
endpoint spent ~15 minutes at 1–2 minutes *per call*; AI Search retrieval
stayed fast the whole time. There is no drop-in model swap: Llama models
respond instantly through our pipeline but cannot produce valid
`searchDocs` tool calls with the AI SDK setup.

The alternative: AI Search's generation endpoint (`aiSearch()` on the
`DOCS_SEARCH` binding — the "chat completions" path) does query
rewriting, hybrid retrieval, and answer generation in **one call**,
streaming, using the **generation model configured on the AI Search
instance in the dashboard** (currently `@cf/meta/llama-3.3-70b-instruct-fp8-fast`,
"Smart default"). No function calling involved, which sidesteps exactly
what Llama fails at in the tool loop. Expected turn time: ~2–5 s with
sub-second first tokens.

This revisits the Phase A / A4 decision of the parent plan ("Agent tool →
`search()`, not `aiSearch()`"), which was made for control over
multi-turn, citations, and "I don't know" — not for latency. New
evidence (production feel, the GLM incident, no viable model swap)
may outweigh that.

### The two model knobs (easy to confuse)

| Knob | Where set | Used today? |
| --- | --- | --- |
| Agent model (`MODEL` in `agent/src/server.ts`) | code, requires redeploy | Yes — GLM does reasoning **and** answers |
| AI Search generation model | dashboard → instance → Generation | **No** — only `aiSearch()` uses it; we only call `search()` |

After the switch, the dashboard picker becomes the only model decision —
swap models with no code change, no redeploy.

### What changes / what stays

| Piece | Fate |
| --- | --- |
| `ChatAgent` DO, WebSocket protocol, persistence, rate limit, page hint | Stays as is |
| `streamText` + `searchDocs` tool loop in `onChatMessage` | Replaced by one streaming `aiSearch()` call |
| System prompt (chunks-only, cite URLs, say "I don't know") | Moves to `aiSearch()`'s `system_prompt` option |
| Widget citation cards | Keep — `aiSearch()` returns retrieved chunks alongside the answer; adapt the tool-output format the widget parses (or attach citations as a data part) |
| Second refined search per turn | **Lost** — one retrieval pass per question |
| GLM reasoning over chunks | **Lost** — acceptable for docs Q&A, verify in A/B |

### Known trade-offs / risks

- Vague questions may retrieve worse with a single pass (no model-driven
  query refinement). Mitigation to test: AI Search query rewriting —
  but that adds its own model call; only enable if A/B shows it earns
  its latency.
- Multi-turn context: resolved — `chatCompletions()` accepts the full
  messages array; we send the recent window flattened to text-only
  turns. Verified with a bare follow-up question ("do I still need the
  face shield…?") answered correctly in context, first token 2.3 s.
  The DO still holds full history either way.
- Do **not** also enable reranking/similarity-cache while measuring —
  change one variable at a time.

## Steps

### Phase A — Baseline in production (blocked on parent Phase E)

- [ ] Current architecture live on nanodocs.pages.dev for a few days
- [ ] Record: typical end-to-end latency, first-token latency, answer
      quality on ~10 real lab questions (reuse the HF PPE / SU-8
      disposal / AJA sputter set), GLM endpoint stability
- [ ] Decision: is latency actually a problem for real users, or did
      the incident exaggerate it?

### Phase A review gate — STOP for sign-off

- [ ] User judges production latency acceptable → **abandon this plan**
      (record why), or annoying → proceed

### Phase B — Prototype the single-call path

- [x] Two-mode toggle instead of an experiment branch: `CHAT_MODE` var
      in `wrangler.jsonc` (`"toolloop"` default / `"aisearch"`), local
      override via gitignored `agent/.dev.vars` (read at dev-server
      start only — restart to flip). `onChatMessage` keeps the shared
      rate limit / page hint / history window, then dispatches to
      `#toolLoopTurn` (unchanged) or `#aiSearchTurn`.
- [x] `#aiSearchTurn` uses the new binding's `chatCompletions()` (the
      legacy `aiSearch()` is deprecated; we're on the new `ai_search`
      binding). System prompt goes per-request as a `role:"system"`
      message — **nothing to configure in the dashboard for prompts**.
      Query rewriting / reranking / cache left off. Model deliberately
      not passed → the dashboard Generation picker decides.
- [x] Citations: `chatCompletions({stream:true})` emits retrieved
      chunks as an SSE event before the answer; re-emitted as a
      synthetic `searchDocs` tool part in the existing
      `[n] url (score s)` format, so the widget's citation cards and
      the persistence layer work unchanged (verified: persisted parts
      `[step-start, tool-searchDocs, text]`).
- [x] Smoke test both modes locally (HF PPE question, one warm run
      each, GLM 4.7-flash on both paths):
      | | toolloop | aisearch |
      | --- | --- | --- |
      | retrieval done | ~6.7 s (1st of 2 searches) | **4.8 s** |
      | first answer token | 47.3 s | 90.7 s |
      | total | 50.0 s | 94.0 s |
      Retrieval + plumbing is fast; the single generation call *is*
      the remaining latency — and it sat on GLM 4.7-flash (the
      incident-degraded endpoint, set in the dashboard earlier today).
      Architecture verdict deferred until a fast model is A/B'd.
- [x] Generation-model A/B via the dashboard picker (no code changes
      between runs; `agent/scratch-chat-test.mjs` is the throwaway
      harness — delete after Phase B). GLM 4.7-flash: first token at
      90.7 s and 27.5 s on two runs (degraded, high variance). Llama
      3.3 70B fast: first token 3.9 s / 2.2 s, total 5.2 s / 4.3 s,
      correct answers, clean citations on both. **~12–20× faster to
      first token than the tool loop (47 s)**; user switched the
      dashboard model to Llama. Qwen3-30B untested — optional.

### Phase B review gate — STOP for sign-off

- [ ] Quality parity (or acceptable trade) on the question set,
      including one vague question and one follow-up question
- [ ] Latency win is real (expect ≥2× on total, ≥5× on first token)
- [ ] Decision: ship it / keep the tool loop / hybrid (e.g. tool loop
      only for follow-ups)

### Phase C — Ship (if Phase B wins)

- [ ] Merge, deploy Worker, update docs (`how_chat_works.md` explainer
      describes the tool loop — rewrite the flow diagram)
- [ ] Update parent plan's "Recommended defaults" table with the new
      answer path; record the reversal of decision A4 and why
- [ ] Watch production for a few days; plan status → Complete

## Known limits / notes

- ChatGPT-sourced suggestion (2026-08-23) contained a wrong premise —
  "switching the agent to Llama made it fast" never happened (Llama
  can't tool-call here) — but the architecture point stands on its own.
- Query rewriting and reranking are dashboard toggles that each add
  model calls. Start minimal; add only on measured retrieval wins.
- If AI Search's one-call generation proves too rigid (e.g. "I don't
  know" behavior can't be tuned via system prompt), the fallback is a
  middle path: keep the agent model but **one** mandatory `search()`
  before a **single** generation call (two calls, no tool loop).
