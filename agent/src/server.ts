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
const MAX_TURNS_PER_MINUTE = 20;

const SYSTEM_PROMPT = `You are the ASRC NanoDocs assistant. Answer only from
chunks returned by the searchDocs tool. Cite the source URL for each claim.
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

function formatChunks(chunks: SearchChunk[] | undefined): string {
  if (!chunks?.length) {
    return "No matching documentation chunks.";
  }
  return chunks
    .map((chunk, i) => {
      const text = chunk.text ?? chunk.content ?? "";
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

    const result = streamText({
      model: workersai(MODEL),
      system: SYSTEM_PROMPT,
      messages: pruneMessages({
        messages: await convertToModelMessages(this.messages),
        toolCalls: "before-last-2-messages",
        reasoning: "before-last-message"
      }),
      tools: {
        searchDocs: tool({
          description:
            "Search the published NanoDocs corpus (tool SOPs, chemicals, policy). Call this before answering lab questions.",
          inputSchema: z.object({
            query: z
              .string()
              .min(1)
              .max(MAX_QUERY_CHARS)
              .describe("The search query, usually the user's question")
          }),
          execute: async ({ query }) => {
            const results = await docsSearch.search({
              messages: [{ role: "user", content: query }],
              ai_search_options: {
                retrieval: { max_num_results: MAX_RESULTS }
              }
            });
            const chunks = (results as { chunks?: SearchChunk[] }).chunks;
            console.log(
              `searchDocs query=${JSON.stringify(query)} chunks=${chunks?.length ?? 0}`
            );
            return formatChunks(chunks);
          }
        })
      },
      stopWhen: stepCountIs(8),
      abortSignal: options?.abortSignal,
      onFinish: onFinish as Parameters<typeof streamText>[0]["onFinish"]
    });

    return result.toUIMessageStreamResponse();
  }
}

export default {
  async fetch(request: Request, env: Env) {
    return (
      (await routeAgentRequest(request, env, { cors: true })) ||
      new Response("Not found", { status: 404 })
    );
  }
} satisfies ExportedHandler<Env>;
