# Cut chat latency by moving answer generation into AI Search (one call)

**Date:** 2026-08-23
**Status:** Draft — deliberately gated on Phase E of
[`2026-08-23-cloudflare-docs-agent.md`](2026-08-23-cloudflare-docs-agent.md):
deploy and evaluate the current tool-loop chat in production **before**
changing the architecture.
**Branch:** TBD (experiment branch when Phase B starts)

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
- Multi-turn context: confirm how much conversation history
  `aiSearch()` accepts (messages vs single query + our own condensing).
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

- [ ] Experiment branch. In `onChatMessage`: replace the `streamText`
      tool loop with one streaming `aiSearch()` call (system prompt via
      option; conversation history per the API's shape; stream tokens
      into the same UI-message protocol the widget already speaks)
- [ ] Emit retrieved chunks in a shape the widget's citation parser
      accepts (keep the prose-link filtering behavior)
- [ ] Local A/B against the tool loop: same question set, measure
      first-token + total latency, compare answer quality and citation
      accuracy side by side
- [ ] Try 2–3 generation models via the dashboard picker (Llama 3.3
      fast, GLM 4.7-flash, Qwen3-30B) — no code changes between runs

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
