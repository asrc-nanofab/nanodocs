# Deploying the docs chat

Personal runbook. The live site and the chat brain are **two Cloudflare
products**. A push to `main` only updates Pages. The model does not
change until you deploy the Worker yourself.

Learned the hard way 2026-08-26: Luna had been in git since the evening
of the 23rd, but `https://nanodocs.pages.dev` kept answering with
`glm-4.7-flash` because the Worker had not been redeployed.

The build story is in `notes/making-of-the-chatbot.md`. This file is
only: what do I run, and when.

## Two deploys, do not conflate

```text
Push to main
    → Cloudflare Pages rebuilds the site + widget JS
    → https://nanodocs.pages.dev is new
    → the widget still talks to the *old* Worker

cd agent && npm run deploy
    → uploads nanodocs-agent
    → https://nanodocs-agent.nanofab.workers.dev is new
    → that is the model, the prompt, CHAT_MODE, the search binding
```

| You changed | What to run |
| --- | --- |
| A Google Doc / site page / widget look | sync (if needed) + commit + **push `main`** |
| `agent/src/server.ts`, `agent/wrangler.jsonc`, the model, `CHAT_MODE` | **`cd agent && npm run deploy`** (push does nothing for this) |
| Both | both |

There is no GitHub Action for `agent/`. Wrangler from the **repo root**
is the Pages/PDF project — always `cd agent` first.

## Deploy the Worker

```bash
cd /home/sng/nanodocs/agent
npm run deploy
```

That is `vite build && wrangler deploy`. Confirm the new version (not
the 2026-08-23 17:48 GLM upload) and that the vars came along:

```bash
./node_modules/.bin/wrangler deployments list
```

You want `CHAT_MODE=toolloop` and `AI_GATEWAY_ID=default` on the live
version. Then on the live site start a **new** conversation (reset in
the chat header, or a new tab). Old threads stay on the previous
Durable Object conversation.

Luna needs the OpenAI key on AI Gateway as Provider Key alias
**`default`** on the gateway named `default`. If that key is missing
the new Worker fails; it does not silently fall back to GLM.

Current answer path (as of the 2026-08-26 deploy): **tool loop**, model
**`gpt-5.6-luna`**, retrieval from AI Search instance **`nanodocs`**.
The dashboard Generation picker is unused unless `CHAT_MODE` is
`aisearch`.

## What a push is for

```bash
git push origin main
```

Pages only. Use it for docs, `mkdocs.yml`, and the committed widget
bundle (`overrides/javascripts/chat-widget.js`, rebuilt with
`npm run build:widget` from `agent/`).
