import { createWorkersAI } from "workers-ai-provider";
import { callable, routeAgentRequest } from "agents";
import { AIChatAgent, type OnChatMessageOptions } from "@cloudflare/ai-chat";
import {
  convertToModelMessages,
  pruneMessages,
  stepCountIs,
  streamText,
  tool
} from "ai";
import { z } from "zod";

const MODEL = "@cf/zai-org/glm-4.7-flash";
const MAX_QUERY_CHARS = 500;
const MAX_RESULTS = 8;
// Hard cap enforced in code — the prompt alone does not stop the model
// from looping on searchDocs, and each call is a slow remote round trip.
const MAX_SEARCHES_PER_TURN = 2;
const MAX_TURNS_PER_MINUTE = 20;
const MAX_PAGE_HINT_CHARS = 300;
// Only the last ~5 turns go to the model. Older history stays persisted
// for the UI but just slows prompt processing and muddies answers.
const MAX_CONTEXT_MESSAGES = 10;

// Origins allowed to call this Worker cross-origin: the local Zensical
// preview and the live docs site. The Vite playground on :5173 is
// same-origin with the Worker in dev, so it needs no CORS headers.
const ALLOWED_ORIGINS = new Set([
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "https://nanodocs.pages.dev"
]);

function corsHeadersFor(request: Request): HeadersInit | false {
  const origin = request.headers.get("Origin");
  if (!origin || !ALLOWED_ORIGINS.has(origin)) {
    return false;
  }
  return {
    "Access-Control-Allow-Origin": origin,
    "Access-Control-Allow-Methods": "GET, POST, HEAD, OPTIONS",
    "Access-Control-Allow-Headers": "*",
    "Access-Control-Max-Age": "86400"
  };
}

const SYSTEM_PROMPT = `You are the ASRC NanoDocs assistant. Answer only from
chunks returned by the searchDocs tool. Cite the source URL for each claim,
copying the URL exactly as it appears in the search results. Cite only pages
you actually used — never mention or list pages you did not use.
Call searchDocs at least once. A second search is allowed if you need a
tighter query; do not search a third time.
If searchDocs returns nothing useful, say you do not know — do not invent
tools, chemicals, or policies. Prefer official SOP and policy pages over
indexes, signup, or authoring pages. The visitor may be on one page; search
the whole published corpus anyway.`;

type SearchChunk = {
  text?: string;
  content?: string;
  score?: number;
  item?: { key?: string; metadata?: Record<string, unknown> };
  metadata?: { filename?: string; folder?: string; url?: string };
};

function chunkText(chunk: SearchChunk): string {
  return chunk.text ?? chunk.content ?? "";
}

function isChromeChunk(chunk: SearchChunk): boolean {
  const text = chunkText(chunk);
  return /<!doctype html>/i.test(text) || /\[skip to content\]/i.test(text);
}

function formatChunks(chunks: SearchChunk[] | undefined): string {
  const kept = (chunks ?? []).filter((chunk) => !isChromeChunk(chunk));
  if (!kept.length) {
    return "No matching documentation chunks.";
  }
  return kept
    .map((chunk, i) => {
      const text = chunkText(chunk);
      const url =
        (typeof chunk.metadata?.url === "string" && chunk.metadata.url) ||
        (typeof chunk.item?.key === "string" && chunk.item.key) ||
        (typeof chunk.metadata?.filename === "string" &&
          chunk.metadata.filename) ||
        "unknown";
      const score =
        typeof chunk.score === "number" ? chunk.score.toFixed(3) : "?";
      return `[${i + 1}] ${url} (score ${score})\n${text}`;
    })
    .join("\n\n");
}

export class ChatAgent extends AIChatAgent<Env> {
  maxPersistedMessages = 40;

  #turnTimes: number[] = [];

  @callable()
  async addServer(_name: string, _url: string) {
    return { error: "MCP is not enabled on this agent." };
  }

  @callable()
  async removeServer(_serverId: string) {
    return { error: "MCP is not enabled on this agent." };
  }

  async onChatMessage(onFinish: unknown, options?: OnChatMessageOptions) {
    const now = Date.now();
    this.#turnTimes = this.#turnTimes.filter((t) => now - t < 60_000);
    if (this.#turnTimes.length >= MAX_TURNS_PER_MINUTE) {
      return new Response("Too many messages. Wait a minute and try again.", {
        status: 429
      });
    }
    this.#turnTimes.push(now);

    const workersai = createWorkersAI({ binding: this.env.AI });
    const docsSearch = this.env.DOCS_SEARCH;
    let searchesThisTurn = 0;

    // Optional hint from the site widget: which page the visitor is on.
    // Context only — the system prompt still demands corpus-wide search.
    const pageHint =
      typeof options?.body?.page === "string"
        ? options.body.page.slice(0, MAX_PAGE_HINT_CHARS)
        : undefined;
    const system = pageHint
      ? `${SYSTEM_PROMPT}\nThe visitor is currently reading ${pageHint} — context only; still search the whole corpus.`
      : SYSTEM_PROMPT;

    // Window must start on a user message — a leading assistant reply
    // with tool parts confuses conversion and some models reject it.
    const recent = this.messages.slice(-MAX_CONTEXT_MESSAGES);
    while (recent.length && recent[0].role !== "user") {
      recent.shift();
    }

    const result = streamText({
      model: workersai(MODEL),
      system,
      messages: pruneMessages({
        messages: await convertToModelMessages(recent),
        toolCalls: "before-last-2-messages",
        reasoning: "before-last-message"
      }),
      tools: {
        searchDocs: tool({
          description:
            "Search the published NanoDocs corpus (tool SOPs, chemicals, policy). Call before answering. A second call with a tighter query is allowed; do not call a third time.",
          inputSchema: z.object({
            query: z
              .string()
              .min(1)
              .max(MAX_QUERY_CHARS)
              .describe("The search query, usually the user's question")
          }),
          execute: async ({ query }) => {
            if (searchesThisTurn >= MAX_SEARCHES_PER_TURN) {
              console.log(
                `searchDocs query=${JSON.stringify(query)} BLOCKED (limit ${MAX_SEARCHES_PER_TURN}/turn)`
              );
              return "Search limit reached for this turn. Answer now using only the chunks already retrieved; if they are not enough, say you do not know.";
            }
            searchesThisTurn += 1;
            const results = await docsSearch.search({
              messages: [{ role: "user", content: query }],
              ai_search_options: {
                retrieval: { max_num_results: MAX_RESULTS }
              }
            });
            const chunks = (results as { chunks?: SearchChunk[] }).chunks;
            const kept = (chunks ?? []).filter((c) => !isChromeChunk(c)).length;
            console.log(
              `searchDocs query=${JSON.stringify(query)} chunks=${chunks?.length ?? 0} kept=${kept}`
            );
            return formatChunks(chunks);
          }
        })
      },
      stopWhen: stepCountIs(4),
      abortSignal: options?.abortSignal,
      onFinish: onFinish as Parameters<typeof streamText>[0]["onFinish"]
    });

    return result.toUIMessageStreamResponse();
  }
}

export default {
  async fetch(request: Request, env: Env) {
    return (
      (await routeAgentRequest(request, env, {
        cors: corsHeadersFor(request)
      })) || new Response("Not found", { status: 404 })
    );
  }
} satisfies ExportedHandler<Env>;
