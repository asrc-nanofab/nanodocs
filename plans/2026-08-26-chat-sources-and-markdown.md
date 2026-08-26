# Choose how Ask NanoDocs cites pages and renders markdown

**Date:** 2026-08-26
**Status:** Draft — options written; awaiting a pick before implementation
**Branch:** none
**Supersedes:** the marked-only draft in git history as
`plans/2026-08-26-chat-widget-marked.md` (removed; this file is the
source of truth)

## How it works today (read this first)

Nothing Cloudflare returns is HTML. The Worker streams **JSON**. The
site widget (`agent/widget/chat-widget.js`) rebuilds a `UIMessage`
list from those frames, then **on the client** harvests URLs, strips
them from the visible text, runs a tiny markdown scanner, and draws
cards. The Durable Object later persists the same `UIMessage[]` (with
URLs still in the text). Harvest is display-only; it does not rewrite
what the model stored.

```text
Browser widget                    Worker (ChatAgent DO)
     |                                    |
     |  WebSocket JSON                    |
     |  cf_agent_use_chat_request ------->|  searchDocs / aisearch
     |                                    |  model writes markdown
     |  cf_agent_use_chat_response <------|  one stream chunk per frame
     |    .body = stringified chunk       |
     |                                    |
     |  GET .../get-messages  ------------>|  persisted UIMessage[]
     |  (after the turn; authoritative)   |
     v                                    v
  local messages[]  -->  harvest  -->  strip  -->  renderMarkdown
                              \                   -->  end cards
                               \--> cited ∩ retrieved
```

### What the widget sends

One WebSocket text frame. `messages` is the full local `UIMessage[]`
(user + assistant turns, including prior tool parts). `page` is only
a hint for the prompt.

```json
{
  "type": "cf_agent_use_chat_request",
  "id": "<uuid>",
  "init": {
    "method": "POST",
    "body": "{\"messages\":[...],\"page\":\"http://127.0.0.1:8000/signup/\"}"
  }
}
```

A user turn looks like:

```json
{
  "id": "<uuid>",
  "role": "user",
  "parts": [{ "type": "text", "text": "How do I get cleanroom access?" }]
}
```

### What comes back (two layers of JSON)

**Layer 1 — Agents WebSocket frame** (parsed by `handleFrame`):

```json
{
  "type": "cf_agent_use_chat_response",
  "body": "<string — see layer 2>",
  "done": false
}
```

`body` is **a string** that must be `JSON.parse`d again. When
`done: true`, the turn is finished and cards may attach.

Other frames we care about:

| `type` | Meaning |
| --- | --- |
| `cf_agent_use_chat_response` | Stream chunk (`body`) or error; `done` ends the turn |
| `cf_agent_chat_messages` | Authoritative persisted list (ignored while a turn is in flight) |
| `cf_agent_message_updated` | Replace one message by `id` |
| `cf_agent_stream_resuming` | Reconnect mid-stream; widget ACKs |

After `done`, the widget also `GET /agents/chat-agent/<conversationId>/get-messages`,
which returns a JSON **array** of `UIMessage` (same shape as below).
That replaces the locally assembled turn so the next request matches
the server.

**Layer 2 — UIMessage stream chunk** (`applyChunk` on `JSON.parse(frame.body)`):

The Worker does not send the whole assistant message at once. It
sends AI-SDK stream events. The widget **accumulates** them onto
`streamingMsg.parts`.

| `chunk.type` | What the widget does |
| --- | --- |
| `start-step` / `reasoning-start` | Status: “Thinking…” |
| `tool-input-start` | Status: “Searching the docs…” |
| `tool-input-available` | Push a tool part (`type: "tool-searchDocs"`, `input.query`) |
| `tool-output-available` | Set that part’s `state` + `output` (the chunk list string) |
| `text-start` | Push `{ type: "text", text: "", _sid }` |
| `text-delta` | Append `chunk.delta` to that text part |
| `error` | Surface `errorText` |

Typical tool-output chunk (what search looks like on the wire):

```json
{
  "type": "tool-output-available",
  "toolCallId": "call_abc",
  "output": "[1] https://nanodocs.pages.dev/signup/ (score 0.812)\nApproval takes 7–10 days…\n\n[2] https://nanodocs.pages.dev/policy/safety/ (score 0.701)\n…"
}
```

That `output` string is **exactly** `formatChunks()` in
`agent/src/server.ts`: one block per retrieved passage, chrome
chunks dropped. The widget never sees the raw AI Search JSON array
— only this text. `extractCitations` later regexes
`^[n] https://… (score` on that string.

Typical token chunk:

```json
{
  "type": "text-delta",
  "id": "msg-text-1",
  "delta": "Source: /signup/\n"
}
```

Deltas concatenate in order. The finished prose is one (sometimes
several) `type: "text"` parts joined with `""`.

### What a finished assistant message looks like

This is the object harvest and cards run on — either the locally
built `streamingMsg` after `done`, or the persisted copy from
`get-messages`.

```json
{
  "id": "<uuid>",
  "role": "assistant",
  "parts": [
    {
      "type": "tool-searchDocs",
      "toolCallId": "call_abc",
      "state": "output-available",
      "input": { "query": "cleanroom access onboarding" },
      "output": "[1] https://nanodocs.pages.dev/signup/ (score 0.812)\n…\n\n[2] https://nanodocs.pages.dev/policy/safety/ (score 0.701)\n…"
    },
    {
      "type": "text",
      "text": "1. **Submit the ASRC New User Form:**\nApproval takes **7–10 days**.\nSource: /signup/\n\n1. **Apply for a Badger account:**\n[Download Badger](https://nanodocs.pages.dev/signup/Download-Badger)\n"
    }
  ]
}
```

Two different URL lists live on this one message:

| List | Function | Source | Example |
| --- | --- | --- | --- |
| **Retrieved** | Pages search actually returned | `extractCitations(msg)` — parse `tool-*` `output` | `/signup/`, `/policy/safety/`, … (up to 8) |
| **Cited in prose** | Pages the model mentioned while writing | `citedInProse(msg)` — parse **raw** `text` parts, before strip | `/signup/`, sometimes `/signup/Download-Badger` |

### How the model is told to cite

Both system prompts (`SYSTEM_PROMPT`, `AISEARCH_SYSTEM_PROMPT`) say:
answer only from retrieved chunks; **copy the source URL exactly**
for each claim; cite only pages you used. The model is not given a
structured cite tool. It invents whatever markdown it wants:
`Source: /signup/`, a bare `https://…`, a `[label](url)`, or a
path with a fake heading suffix. That string is the **only**
used-page signal.

`aisearch` mode still emits a synthetic `tool-searchDocs` part in
this same `[n] url (score s)` shape so the widget’s parser does not
care which mode ran.

### Harvest → strip → cards (client only)

Runs in `render()`, and **cards only after the stream ends**
(`msg !== streamingMsg`) so the bubble does not jump.

1. **Harvest (signal, uses raw text).** `citedInProse` collects:
   markdown links `[label](url)`, bare `https://…`, lines
   `Source: <token>`, and lines that are only `/some/path`.
   `normalizeCite` / `cleanDocsUrl` turn those into pathnames
   (`https://nanodocs.pages.dev/signup/` → `/signup/`) and drop
   `?` / `#`. Junk suffixes are **kept** here (`/signup/Download-Badger`)
   so they can still prefix-match a search row.

2. **Intersect.**
   `cardHrefs = retrieved.filter(href => cited.some(c => c === href || c.startsWith(href + "/")))`.
   The card’s `href` is the **search row** (`/signup/`), not the
   model’s copy. No match → no card. No fallback to the unused
   retrieved hits.

3. **Strip (display only).** `stripCitationsForDisplay` deletes
   cite-only lines and in-line URL tokens, then squeezes blank
   lines between adjacent list lines. The stored `parts[].text` is
   unchanged. Leftover punctuation (`Download Badger:`) is this
   step, not the stream.

4. **Render.** `renderMarkdown` turns the stripped string into
   HTML (headings, `ol`/`ul`, fences, bold, code). Any non-list
   line closes the current `<ol>`, which is why procedures still
   show `1. 1. 1.` after harvest.

5. **Cards.** One `.ndc-cite` link per `cardHrefs` entry, under
   the bubble. Label is the last path segment title-cased
   (`signup` → “Signup”).

Worked example from the message JSON above:

```text
retrieved:  /signup/   /policy/safety/   (and up to 6 more unused)
cited:      /signup/   /signup/Download-Badger
match:      /signup/  (prefix match on the junk path)
cards:      one card, href="/signup/"
visible:    "1. Submit…  1. Apply… Download Badger:"   (URLs gone)
```

If the model cites nothing that matches a search row, the answer
still shows and the card row is empty.

### What is not parsed

- The widget does not read AI Search’s native chunk JSON, only
  `formatChunks` text.
- It does not use Cloudflare citation / `url_citation` objects.
- It does not ask the model for a structured source list.
- Mid-stream, `citedInProse` is skipped (no cards until `done`).

## Description


Two separate problems landed in the same bubble. They have different
fixes. Mixing them is why harvest felt like “the” bug.

**1. Used-page cards.** We want cards only for pages the model actually
used, not all ~8 `searchDocs` hits, and we do not want dead inline
links. Today the prompt says “copy the source URL into the answer,”
then the widget **harvests** those URLs from prose, intersects them
with search rows, hides the inline cites, and draws end cards.

**2. Numbered lists.** After harvest, signup-style answers still render
`1. 1. 1. 2. 1.` The stream is not scrambled. The widget’s ~50-line
`renderMarkdown` closes an `<ol>` on any paragraph or bullet, so the
browser restarts at 1. Consecutive `1.` lines (the case harvest was
built for) already number correctly.

Cloudflare’s native payload is a markdown string in the UIMessage
stream. There is no pre-rendered HTML. Zensical’s markdown runs at
build time and cannot parse live chat. The Vite playground uses
Streamdown (React) and is out of scope unless we later port cards
there.

This plan lists every viable way to get **used links** and every
viable way to **render** the answer, then stops for a pick.

### Constraints we already have

| Constraint | Why it matters |
| --- | --- |
| Used-only cards, not all 8 retrieved | Ruled out “just card every search hit” (2026-08-26) |
| Working hrefs | Model often appends heading-slug junk; the **search row** is the real URL |
| Site widget is vanilla JS | Zensical `extra_javascript`; do not pull React / Streamdown into the bundle |
| Two Worker modes | `CHAT_MODE=toolloop` has tools; `aisearch` does not — a cite **tool** is tool-loop only unless we add a parallel convention |
| Cite-the-URL prompt is the current used-page signal | Changing the prompt without a replacement signal loses “used vs merely retrieved” |
| User commits / deploys | Widget → Pages; prompt or tools → `cd agent && npm run deploy` |

---

## Options — used-page signal

How the widget learns which retrieved URLs to card. Independent of
which markdown parser we use.

### S0 — Harvest from prose (current)

Leave the prompt (“copy the URL exactly”). Before display, scrape
`Source: …`, bare URLs, markdown links, and path-only lines; hide
them; intersect with `searchDocs` rows; card the matches. No
fallback to unused hits.

| | |
| --- | --- |
| **Pros** | Already shipped. No new tool. Works in tool-loop and aisearch (both write URLs into text). Search-row hrefs already fixed. |
| **Cons** | Prompt and UI fight: write URLs, then delete them. Leftover punctuation (`Download Badger:`). Cite lines between `1.` items were the original list-killer; strip logic is now load-bearing. Model still pollutes the markdown. |
| **Touch** | None if we keep it. Widget-only if we only tidy the stripper. |
| **Verdict** | Works as a signal. Wrong place for the signal. |

### S1 — `citePages` tool (or `data-sources` stream part)

Prompt: **do not put URLs in the answer.** After writing, call
`citePages` with URLs copied exactly from the last `searchDocs`
output (or `writer.write({ type: "data-sources", data: { urls } })`).
Widget reads that part the same way it already reads search hits,
intersects, cards. Delete harvest.

| | |
| --- | --- |
| **Pros** | Answer markdown stays clean. Used-page signal is structured and persisted on the message. Same card UI. No prose regex. |
| **Cons** | Extra tool step on every turn (latency, another thing to cap). Model can skip the call → no cards that turn. **Tool-loop only** unless aisearch gets a footer or index convention as well. |
| **Touch** | `agent/src/server.ts` (tool + both prompts), widget (read tool part, delete harvest), Worker redeploy. |
| **Verdict** | Cleanest “used, not retrieved” for tool-loop. Needs an aisearch twin if that mode stays live. |

### S2 — Cite by search index (`[1]`, `[2]`)

Chunks already arrive as `[n] url (score s)`. Prompt: cite claims as
`[1]` / `[2]` only — never paste the URL. Widget maps `[n]` to
`extractCitations()[n-1]`. Strip leftover `[n]` from display if we
do not want footnote chips in the bubble.

| | |
| --- | --- |
| **Pros** | Tiny. No second tool. Search-row URL is authoritative (index → row). Works in **both** modes (aisearch uses the same `[n] url` format). Much less likely to kill a list than `Source: https://…`. |
| **Cons** | Still a bit of prose scraping. Model can invent `[9]` or reuse the wrong n. Need a clear rule: `[n]` is a cite marker, not a numbered step. |
| **Touch** | Both prompts, widget mapper, delete most of harvest. Worker redeploy. |
| **Verdict** | Best lean option if we want one convention for tool-loop **and** aisearch. |

### S3 — Trailing sources block

Prompt: no URLs in the body. Last lines are a machine footer, e.g.

```text
<!-- sources
https://nanodocs.pages.dev/signup/
https://nanodocs.pages.dev/policy/safety/
-->
```

Widget strips that one block and intersects with search rows.

| | |
| --- | --- |
| **Pros** | Cannot land *between* list items if the model obeys. One strip, not per-line harvest. Both modes. |
| **Cons** | Model may still inline-cite, omit the footer, or put URLs in the body anyway — then we are back to harvest as a fallback. Footer is still markdown we must not show. |
| **Touch** | Both prompts, widget footer parser. Worker redeploy. |
| **Verdict** | Simpler than S1, sloppier than S2. Fine as an aisearch twin to S1, weak as the only plan. |

### S4 — No model signal (retrieval-only cards)

Card some or all `searchDocs` URLs. Variants: all hits (up to 8);
top-k by score; drop signup / index / authoring unless they are the
only hits.

| | |
| --- | --- |
| **Pros** | Delete harvest and the cite-the-URL prompt. Cards always have real hrefs. Zero model cooperation. |
| **Cons** | Not “used.” Retrieval likes `/signup/`. Already rejected “show all 8.” Top-k / downrank is a product compromise, not attribution. |
| **Touch** | Prompt (stop asking for URLs), widget (`cardHrefs = extractCitations` + optional filter). Worker redeploy if the prompt changes. |
| **Verdict** | Only if we give up “used vs retrieved.” |

### S5 — Lexical overlap / attribution

After the answer finishes, score each retrieved chunk against the
answer text (token overlap, etc.) and card the chunks above a
threshold.

| | |
| --- | --- |
| **Pros** | No inline URLs, no extra tool, both modes. |
| **Cons** | Heuristic: short answers and shared lab words (“gloves”, “HF”) mis-attribute. Tuning in production. More code than S2. |
| **Touch** | Widget or Worker post-pass. Prompt can drop URL cites. |
| **Verdict** | Research-y. Not lean enough for this widget. |

### S6 — Second model call (“which pages did you use?”)

After generation, a cheap structured call returns `{ urls: [...] }`.
Cards from that JSON.

| | |
| --- | --- |
| **Pros** | Structured, both modes, body can be URL-free. |
| **Cons** | Extra latency and cost on every turn — the opposite of the aisearch-latency plan. Can still hallucinate URLs (must intersect with search rows). |
| **Touch** | Worker always; widget reads a data part. |
| **Verdict** | Do not do this unless S1/S2 fail in production. |

### Used-signal comparison

| | Used-only? | URLs out of the body? | Tool-loop | Aisearch | Extra model/tool step | Lean? |
| --- | --- | --- | --- | --- | --- | --- |
| **S0 harvest** | Yes | Hide, not stop | Yes | Yes | No | Already built |
| **S1 citePages** | Yes | Yes | Yes | No (needs twin) | Yes | Medium |
| **S2 `[n]` cites** | Yes | Yes (markers only) | Yes | Yes | No | Yes |
| **S3 footer** | If obeyed | Yes | Yes | Yes | No | Yes |
| **S4 retrieval cards** | No | Yes | Yes | Yes | No | Yes |
| **S5 overlap** | Approximate | Yes | Yes | Yes | No | No |
| **S6 second call** | Yes | Yes | Yes | Yes | Yes | No |

---

## Options — markdown renderer

How `parts[].text` becomes HTML in the Ask NanoDocs panel. Independent
of the used-page signal, except that a dirty body (S0) is harder for
every parser.

### R0 — Keep the hand-rolled scanner (current)

`renderMarkdown` + `renderInline`: headings, `1.` / `-` lists,
fences, `**bold**`, `` `code` ``. Closes the list on blank lines,
paragraphs, and list-kind changes.

| | |
| --- | --- |
| **Pros** | No new dependency. Predictable subset. |
| **Cons** | Cannot keep one `<ol>` across a following sentence or nested bullets. This is the leftover `1. 1. 1.` bug. |
| **Verdict** | Not enough if we care about procedures. |

### R1 — `marked` + sanitize (`DOMPurify`)

Vanilla CommonMark. Bundle with the existing `npm run build:widget`
esbuild step. Harvest or S1–S3 run **before** parse. Disable
autolink and HTML passthrough.

CommonMark keeps `1.` / blank / `1.` as one list and lazy-continues
a same-block paragraph onto the item, so the browser numbers 1, 2,
3 even when the model writes `1.` every time. An **unindented** `-`
between steps still starts a new list (the spec).

| | |
| --- | --- |
| **Pros** | Small, no React, already a transitive dep via mermaid. Matches “LLM markdown” better than R0. |
| **Cons** | Not stream-aware (same as today: re-parse the full string per token). Incomplete `**` / fences look off until closed. Unindented nested bullets still split the list. |
| **Touch** | `agent/package.json`, widget, CSS tweaks, rebuild bundle. Pages only. |
| **Verdict** | Right renderer for this site widget. |

### R2 — `markdown-it` (+ GFM plugin)

Same idea as R1, more plugins (tables, etc.).

| | |
| --- | --- |
| **Pros** | Familiar if we later want GFM tables in answers. |
| **Cons** | Heavier than we need. The model rarely emits tables. |
| **Verdict** | Only if R1 is missing something we actually see. |

### R3 — Streamdown in the site widget

What `agent/src/app.tsx` uses. Streaming-aware, GFM, React.

| | |
| --- | --- |
| **Pros** | Best mid-stream look. Already a dependency of the Worker app. |
| **Cons** | Pulls React into every docs page. Wrong fit for Zensical extra_javascript. |
| **Verdict** | No. |

### R4 — Prompt-only (“indent nested lists”)

Keep R0 (or add R1) and add one sentence: indent continuation lines
and nested bullets under a numbered step (4 spaces).

| | |
| --- | --- |
| **Pros** | Tiny. Helps any CommonMark parser. |
| **Cons** | Models ignore format notes often. Does not replace a real parser. Does not create a used-page signal. |
| **Verdict** | Optional add-on after R1, not a standalone fix. |

### Renderer comparison

| | Fixes `1.` + paragraph? | Fixes unindented `-`? | Vanilla JS | New dep | Stream-aware |
| --- | --- | --- | --- | --- | --- |
| **R0 scanner** | No | No | Yes | No | No |
| **R1 `marked`** | Yes | No (spec) | Yes | `marked` + purify | No |
| **R2 markdown-it** | Yes | No (spec) | Yes | markdown-it | No |
| **R3 Streamdown** | Yes | No (spec) | No (React) | already in app | Yes |
| **R4 indent prompt** | Helps if obeyed | Helps if obeyed | n/a | No | n/a |

---

## How they combine

Pick one S and one R. Useful pairings:

| Pair | What you get | Cost |
| --- | --- | --- |
| **S0 + R1** | Current cards, better lists. Body still has URLs that we strip. Leftover `Download Badger:` remains. | Widget + Pages only |
| **S2 + R1** | `[n]` in prose (or stripped), real cards, clean-ish lists, both Worker modes. | Prompts + widget + Worker deploy + Pages |
| **S1 + R1** (+ S2 or S3 on aisearch) | Cleanest body on tool-loop. Two conventions if aisearch stays. | Tools + prompts + widget + both deploys |
| **S4 + R1** | Cleanest code, cards are “retrieved” not “used.” | Prompt + widget |
| **S0 + R0** | Today. Do nothing. | — |

Do **not** keep S0 harvest *and* add a cite tool — two signals will
drift. Do **not** stack a custom list-fixer on top of `marked`.

Suggested lean default if we want used-only cards **and** lists:
**S2 + R1**, optional R4 if nested bullets still look wrong.

---

## Steps

### Phase 0 — Pick (this gate)

- [ ] Choose a used-page signal: S0 / S1 / S2 / S3 / S4 / S5 / S6
- [ ] Choose a renderer: R0 / R1 / R2 / R3 / R4-as-add-on
- [ ] If S1: decide the aisearch twin (S2 or S3) or “tool-loop only
      for now”
- [ ] Write the chosen pair into this file and add implementation
      phases (files, deploys, review checks)

### Phase 0 review gate — STOP for sign-off

- [ ] Decision recorded above
- [ ] Decision: implement the pair / adjust / abandon

Implementation phases are **not** written until Phase 0 picks. The
old marked-only sequence (add `marked`, maybe indent prompt, ship)
is the implementation sketch for **S0 + R1** only.

## Known limits / notes

- **Not scrambled.** `text-delta` chunks append in order.
  `messageText` joins text parts with `""`. Harvest leftover colons
  are strip artifacts.
- **Playground** (`localhost:5173`, Streamdown) has no card row and
  is out of scope unless a later plan ports the chosen S there.
- **Deploy split.** Widget JS → Pages (`overrides/javascripts/chat-widget.js`
  via `npm run build:widget`). Prompt / tools → Worker
  (`cd agent && npm run deploy`).
- **Parent plans.** Latency work in
  `plans/2026-08-23-aisearch-single-call.md` is why aisearch must
  not be forgotten when picking S1.
