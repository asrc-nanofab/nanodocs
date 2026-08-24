import { createOpenAI } from "@ai-sdk/openai";
import { callable, routeAgentRequest } from "agents";
import { AIChatAgent, type OnChatMessageOptions } from "@cloudflare/ai-chat";
import {
  convertToModelMessages,
  createUIMessageStream,
  createUIMessageStreamResponse,
  pruneMessages,
  stepCountIs,
  streamText,
  tool,
  type UIMessage,
  type UIMessageStreamWriter
} from "ai";
import { createWorkersAI } from "workers-ai-provider";
import { createGatewayFetch } from "workers-ai-provider/gateway";
import { z } from "zod";

// Tool-loop model. Routed through AI Gateway via the Worker's AI binding
// so the OpenAI key stored on the gateway (BYOK) is used — no key in code.
// Bare "gpt-5.6" routes to Sol; Luna needs the explicit id. Tools on
// chat completions require reasoningEffort "none"; Responses replay
// crashed the local Durable Object on follow-up turns.
const MODEL = "gpt-5.6-luna";
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

// aisearch mode: AI Search retrieves and injects the context itself, so
// there is no tool to instruct — only how to answer from that context.
const AISEARCH_SYSTEM_PROMPT = `You are the ASRC NanoDocs assistant. Answer
only from the retrieved documentation context provided with this request.
Cite the source URL for each claim, copying the URL exactly as it appears in
the context. Cite only pages you actually used — never mention or list pages
you did not use. If the context contains nothing useful, say you do not
know — do not invent tools, chemicals, or policies. Prefer official SOP and
policy pages over indexes, signup, or authoring pages.`;

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

// Worker-authenticated gateway call. byok:false strips the dummy
// Authorization header so the gateway injects the stored OpenAI key
// (Provider Keys alias "default" on AI_GATEWAY_ID).
function openaiForToolLoop(env: Env) {
  const gatewayId = env.AI_GATEWAY_ID || "default";
  console.log(`toolloop model=${MODEL} gateway=${gatewayId} via=binding`);
  const throughGateway = createGatewayFetch({
    binding: env.AI,
    gateway: gatewayId,
    byok: false
  });
  return createOpenAI({
    apiKey: "unused",
    fetch: (input, init) =>
      // Drop abort. Cancelling a remote AI stream is what prints
      // "internal error; reference = …" in wrangler dev.
      throughGateway(input, init ? { ...init, signal: undefined } : init)
  });
}

// chatCompletions() takes plain {role, content} messages — flatten each
// UI message's text parts and drop tool/reasoning parts and empty turns.
function toPlainMessages(
  messages: UIMessage[]
): { role: "user" | "assistant"; content: string }[] {
  const plain: { role: "user" | "assistant"; content: string }[] = [];
  for (const msg of messages) {
    if (msg.role !== "user" && msg.role !== "assistant") {
      continue;
    }
    const text = msg.parts
      .filter((part) => part.type === "text")
      .map((part) => part.text)
      .join("")
      .trim();
    if (text) {
      plain.push({ role: msg.role, content: text });
    }
  }
  return plain;
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

    // Optional hint from the site widget: which page the visitor is on.
    // Context only — the system prompt still demands corpus-wide answers.
    const pageHint =
      typeof options?.body?.page === "string"
        ? options.body.page.slice(0, MAX_PAGE_HINT_CHARS)
        : undefined;

    // Window must start on a user message — a leading assistant reply
    // with tool parts confuses conversion and some models reject it.
    const recent = this.messages.slice(-MAX_CONTEXT_MESSAGES);
    while (recent.length && recent[0].role !== "user") {
      recent.shift();
    }

    // Widen the literal type wrangler generates from the configured value.
    const mode: string = this.env.CHAT_MODE;
    return mode === "aisearch"
      ? this.#aiSearchTurn(recent, pageHint, options?.abortSignal)
      : this.#toolLoopTurn(recent, pageHint, onFinish, options);
  }

  async #toolLoopTurn(
    recent: UIMessage[],
    pageHint: string | undefined,
    onFinish: unknown,
    options?: OnChatMessageOptions
  ) {
    const openai = openaiForToolLoop(this.env);
    const docsSearch = this.env.DOCS_SEARCH;
    let searchesThisTurn = 0;

    const system = pageHint
      ? `${SYSTEM_PROMPT}\nThe visitor is currently reading ${pageHint} — context only; still search the whole corpus.`
      : SYSTEM_PROMPT;

    const result = streamText({
      // Luna rejects function tools on chat completions unless
      // reasoning is off. The Responses API works for turn 1 but
      // crashes the local DO on turn 2 (reasoning item replay).
      model: openai.chat(MODEL),
      providerOptions: { openai: { reasoningEffort: "none" } },
      system,
      messages: pruneMessages({
        messages: await convertToModelMessages(recent),
        toolCalls: "before-last-message",
        reasoning: "all"
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

    return result.toUIMessageStreamResponse({ sendReasoning: false });
  }

  // One chatCompletions() call: AI Search rewrites nothing (query rewrite
  // off), retrieves, and generates with the dashboard-configured model.
  // The retrieved chunks are re-emitted as a synthetic searchDocs tool part
  // in the exact "[n] url (score s)" format the widget's citation parser
  // and the AIChatAgent persistence layer already understand.
  #aiSearchTurn(
    recent: UIMessage[],
    pageHint: string | undefined,
    abortSignal?: AbortSignal
  ) {
    const docsSearch = this.env.DOCS_SEARCH;
    const system = pageHint
      ? `${AISEARCH_SYSTEM_PROMPT}\nThe visitor is currently reading ${pageHint} — context only.`
      : AISEARCH_SYSTEM_PROMPT;
    const plain = toPlainMessages(recent);
    let query = "";
    for (let i = plain.length - 1; i >= 0; i--) {
      if (plain[i].role === "user") {
        query = plain[i].content;
        break;
      }
    }

    const stream = createUIMessageStream({
      execute: async ({ writer }) => {
        const toolCallId = `aisearch-${crypto.randomUUID()}`;
        const textId = `${toolCallId}-text`;
        writer.write({ type: "start" });
        writer.write({ type: "start-step" });
        // Emitted before the call so the widget shows "Searching: …"
        // during retrieval. If the call fails mid-part, AIChatAgent's
        // transcript repair settles the orphan before the next turn.
        writer.write({
          type: "tool-input-available",
          toolCallId,
          toolName: "searchDocs",
          input: { query }
        });

        // Empty AISEARCH_MODEL → dashboard Generation picker. Set locally
        // when the picker is on a provider that has no key (Internal Error).
        const generationModel = this.env.AISEARCH_MODEL || undefined;
        let sse: ReadableStream;
        try {
          sse = await docsSearch.chatCompletions({
            messages: [{ role: "system", content: system }, ...plain],
            stream: true,
            ...(generationModel ? { model: generationModel } : {}),
            ai_search_options: {
              retrieval: { max_num_results: MAX_RESULTS }
            }
          });
        } catch (error) {
          const message =
            error instanceof Error ? error.message : String(error);
          console.error(`aiSearch chatCompletions failed: ${message}`);
          await aiSearchFallback(
            this.env,
            writer,
            toolCallId,
            textId,
            query,
            system,
            abortSignal
          );
          return;
        }

        const reader = sse.getReader();
        if (abortSignal && !abortSignal.aborted) {
          abortSignal.addEventListener(
            "abort",
            () => void reader.cancel().catch(() => {}),
            { once: true }
          );
        }

        // SSE framing: one "chunks" event carrying a JSON array of
        // retrieved chunks, then OpenAI-style completion deltas, then
        // "data: [DONE]". Reads can split lines, so buffer partials.
        const decoder = new TextDecoder();
        let buffer = "";
        let toolSettled = false;
        let textStarted = false;
        try {
          while (true) {
            const { done, value } = await reader.read();
            if (done) {
              break;
            }
            buffer += decoder.decode(value, { stream: true });
            const lines = buffer.split("\n");
            buffer = lines.pop() ?? "";
            for (const line of lines) {
              if (!line.startsWith("data: ")) {
                continue;
              }
              const payload = line.slice(6).trim();
              if (payload === "[DONE]") {
                continue;
              }
              let data: unknown;
              try {
                data = JSON.parse(payload);
              } catch {
                continue;
              }
              if (Array.isArray(data)) {
                const chunks = data as SearchChunk[];
                const kept = chunks.filter((c) => !isChromeChunk(c)).length;
                console.log(
                  `aiSearch query=${JSON.stringify(query)} chunks=${chunks.length} kept=${kept}`
                );
                writer.write({
                  type: "tool-output-available",
                  toolCallId,
                  output: formatChunks(chunks)
                });
                toolSettled = true;
                continue;
              }
              const completion = data as {
                model?: string;
                choices?: { delta?: { content?: string } }[];
              };
              const delta = completion.choices?.[0]?.delta?.content;
              if (typeof delta === "string" && delta !== "") {
                if (!textStarted) {
                  // Log which dashboard-configured model actually answered.
                  console.log(`aiSearch generation model=${completion.model}`);
                  writer.write({ type: "text-start", id: textId });
                  textStarted = true;
                }
                writer.write({ type: "text-delta", id: textId, delta });
              }
            }
          }
        } finally {
          reader.releaseLock();
        }

        // The tool part must always settle — persisted incomplete parts
        // break convertToModelMessages if the mode flips back to toolloop.
        if (!toolSettled) {
          writer.write({
            type: "tool-output-available",
            toolCallId,
            output: "No matching documentation chunks."
          });
        }
        if (textStarted) {
          writer.write({ type: "text-end", id: textId });
        }
        writer.write({ type: "finish-step" });
        writer.write({ type: "finish" });
      },
      onError: (error) =>
        error instanceof Error ? error.message : String(error)
    });

    return createUIMessageStreamResponse({ stream });
  }
}

// chatCompletions() is returning Internal Error (dashboard generation
// path). Retrieval still works, so answer with search() + Workers AI.
async function aiSearchFallback(
  env: Env,
  writer: UIMessageStreamWriter,
  toolCallId: string,
  textId: string,
  query: string,
  system: string,
  abortSignal?: AbortSignal
) {
  const results = await env.DOCS_SEARCH.search({
    messages: [{ role: "user", content: query }],
    ai_search_options: {
      retrieval: { max_num_results: MAX_RESULTS }
    }
  });
  const chunks = (results as { chunks?: SearchChunk[] }).chunks;
  const kept = (chunks ?? []).filter((c) => !isChromeChunk(c)).length;
  console.log(
    `aiSearch fallback search query=${JSON.stringify(query)} chunks=${chunks?.length ?? 0} kept=${kept}`
  );
  writer.write({
    type: "tool-output-available",
    toolCallId,
    output: formatChunks(chunks)
  });

  const workersai = createWorkersAI({ binding: env.AI });
  writer.write({ type: "text-start", id: textId });
  try {
    const result = streamText({
      model: workersai("@cf/zai-org/glm-4.7-flash"),
      system: `${system}\n\nRetrieved context:\n${formatChunks(chunks)}`,
      prompt: query,
      abortSignal
    });
    for await (const delta of result.textStream) {
      writer.write({ type: "text-delta", id: textId, delta });
    }
  } catch (error) {
    const message = error instanceof Error ? error.message : String(error);
    console.error(`aiSearch fallback generation failed: ${message}`);
    writer.write({
      type: "text-delta",
      id: textId,
      delta: quotaOrErrorText(message)
    });
  }
  writer.write({ type: "text-end", id: textId });
  writer.write({ type: "finish-step" });
  writer.write({ type: "finish" });
}

function quotaOrErrorText(message: string): string {
  if (/10,000 neurons|daily free allocation/i.test(message)) {
    return "Workers AI's free daily quota is used up, so I can't generate an answer until it resets or the account is on the Workers Paid plan. Retrieval and OpenAI (the tool-loop / Luna path) do not use that quota.";
  }
  return `I couldn't generate an answer (${message}).`;
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
