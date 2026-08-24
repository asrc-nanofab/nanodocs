/**
 * NanoDocs site chat widget.
 *
 * Source of truth for overrides/javascripts/chat-widget.js — build with
 * `npm run build:widget` from agent/. Talks to the sibling Worker
 * (nanodocs-agent) over the Agents WebSocket protocol:
 *
 *   - send  cf_agent_use_chat_request  (full UIMessage list + page hint)
 *   - recv  cf_agent_use_chat_response (body = one JSON stream chunk)
 *   - recv  cf_agent_chat_messages     (authoritative persisted list)
 *
 * Citations are parsed from searchDocs tool outputs ("[n] <url> (score s)"
 * lines), never from the model's prose — GLM often omits links or appends
 * heading-slug junk to them.
 */
import { AgentClient } from "agents/client";

// Worker host per docs origin. Unknown origins get no widget.
const AGENT_HOSTS = {
  localhost: "localhost:5173",
  "127.0.0.1": "localhost:5173",
  "nanodocs.pages.dev": "nanodocs-agent.nanofab.workers.dev"
};

const AGENT_NAME = "chat-agent";
const STORAGE_KEY = "nanodocs-chat-conversation";
const ROOT_ID = "nanodocs-chat";

const host = AGENT_HOSTS[window.location.hostname];
if (host && !document.getElementById(ROOT_ID)) {
  initWidget(host);
}

function initWidget(workerHost) {
  const httpBase =
    (workerHost.startsWith("localhost:") || workerHost.startsWith("127.0.0.1:")
      ? "http://"
      : "https://") + workerHost;

  let conversationId = sessionStorage.getItem(STORAGE_KEY);
  if (!conversationId) {
    conversationId = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, conversationId);
  }

  /** UIMessage-shaped list mirrored from the Agent. */
  let messages = [];
  /** Assistant message currently being streamed, if any. */
  let streamingMsg = null;
  /** DOM node of the streaming bubble, patched in place per token. */
  let streamingEl = null;
  /** True between sending a question and the final done frame. */
  let pending = false;
  /** What the agent is doing right now, shown beside the typing dots. */
  let activity = "";
  let client = null;
  let historyLoaded = false;

  // --- DOM -----------------------------------------------------------

  const root = document.createElement("div");
  root.id = ROOT_ID;
  root.innerHTML = `
    <button class="ndc-fab" type="button" aria-label="Ask NanoDocs" aria-expanded="false">
      <svg viewBox="0 0 24 24" width="22" height="22" aria-hidden="true"><path fill="currentColor" d="M12 3C6.5 3 2 6.9 2 11.7c0 2.6 1.3 4.9 3.4 6.5-.2 1-.8 2.5-1.9 3.4 1.9.1 3.9-.6 5.3-1.5.7-.2 1.5-.3 2.2-.3 5.5 0 10-3.9 10-8.7S17.5 3 12 3z"/></svg>
      <span class="ndc-fab-label">Ask NanoDocs</span>
    </button>
    <section class="ndc-panel" role="dialog" aria-label="NanoDocs assistant" hidden>
      <header class="ndc-header">
        <span class="ndc-title">Ask NanoDocs</span>
        <button class="ndc-reset" type="button" title="New conversation">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M17.65 6.35A7.96 7.96 0 0 0 12 4a8 8 0 1 0 7.73 10h-2.08A6 6 0 1 1 12 6c1.66 0 3.14.69 4.22 1.78L13 11h7V4l-2.35 2.35z"/></svg>
        </button>
        <button class="ndc-close" type="button" aria-label="Close chat">
          <svg viewBox="0 0 24 24" width="18" height="18" aria-hidden="true"><path fill="currentColor" d="M19 6.41 17.59 5 12 10.59 6.41 5 5 6.41 10.59 12 5 17.59 6.41 19 12 13.41 17.59 19 19 17.59 13.41 12z"/></svg>
        </button>
      </header>
      <div class="ndc-messages" aria-live="polite"></div>
      <div class="ndc-status" hidden></div>
      <form class="ndc-form">
        <textarea rows="1" placeholder="Ask about tools, chemicals, policies…" aria-label="Your question"></textarea>
        <button class="ndc-send" type="submit" aria-label="Send">
          <svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true"><path fill="currentColor" d="M2 21l21-9L2 3v7l15 2-15 2v7z"/></svg>
        </button>
      </form>
      <p class="ndc-footnote">Answers come from published NanoDocs pages. Verify against the SOP before lab work.</p>
    </section>`;
  document.body.appendChild(root);

  const fab = root.querySelector(".ndc-fab");
  const panel = root.querySelector(".ndc-panel");
  const messagesEl = root.querySelector(".ndc-messages");
  const statusEl = root.querySelector(".ndc-status");
  const form = root.querySelector(".ndc-form");
  const input = root.querySelector("textarea");
  const sendBtn = root.querySelector(".ndc-send");

  // Material's instant navigation swaps page content but leaves body
  // children alone; re-attach defensively in case a theme update changes
  // that. document$ emits after every (instant or full) page load.
  if (window.document$ && typeof window.document$.subscribe === "function") {
    window.document$.subscribe(() => {
      if (!document.body.contains(root)) {
        document.body.appendChild(root);
      }
    });
  }

  // --- Rendering -----------------------------------------------------

  function escapeHtml(text) {
    return text
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  // Same-origin rewrite so citations navigate the site being viewed
  // (localhost in dev, pages.dev in production). Fragments are dropped:
  // crawl URLs have none, and GLM sometimes appends heading-slug junk.
  function cleanDocsUrl(raw) {
    try {
      const url = new URL(raw);
      if (
        url.hostname === "nanodocs.pages.dev" ||
        url.hostname === window.location.hostname
      ) {
        return url.pathname;
      }
      return url.origin + url.pathname;
    } catch {
      return null;
    }
  }

  function renderInline(text) {
    let html = escapeHtml(text);
    html = html.replace(/`([^`]+)`/g, "<code>$1</code>");
    html = html.replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");
    // Markdown links, then bare URLs left over in prose.
    html = html.replace(
      /\[([^\]]+)\]\((https?:\/\/[^)\s]+)\)/g,
      (m, label, url) => {
        const href = cleanDocsUrl(url);
        return href ? `<a href="${href}">${label}</a>` : label;
      }
    );
    html = html.replace(/(?<!["'=(\]])(https?:\/\/[^\s<)]+)/g, (m, url) => {
      const href = cleanDocsUrl(url);
      return href ? `<a href="${href}">${href}</a>` : m;
    });
    return html;
  }

  /** Tiny markdown-to-HTML for assistant text: headings, lists, code fences. */
  function renderMarkdown(text) {
    const lines = text.split("\n");
    const out = [];
    let list = null;
    let fence = null;
    const closeList = () => {
      if (list) {
        out.push(list === "ul" ? "</ul>" : "</ol>");
        list = null;
      }
    };
    for (const line of lines) {
      if (fence !== null) {
        if (/^```/.test(line)) {
          out.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`);
          fence = null;
        } else {
          fence.push(line);
        }
        continue;
      }
      if (/^```/.test(line)) {
        closeList();
        fence = [];
        continue;
      }
      const heading = line.match(/^(#{1,6})\s+(.*)$/);
      const bullet = line.match(/^\s*[-*]\s+(.*)$/);
      const numbered = line.match(/^\s*\d+[.)]\s+(.*)$/);
      if (heading) {
        closeList();
        out.push(`<p class="ndc-h">${renderInline(heading[2])}</p>`);
      } else if (bullet || numbered) {
        const kind = bullet ? "ul" : "ol";
        if (list !== kind) {
          closeList();
          out.push(kind === "ul" ? "<ul>" : "<ol>");
          list = kind;
        }
        out.push(`<li>${renderInline((bullet || numbered)[1])}</li>`);
      } else if (line.trim() === "") {
        closeList();
      } else {
        closeList();
        out.push(`<p>${renderInline(line)}</p>`);
      }
    }
    closeList();
    if (fence !== null) {
      out.push(`<pre><code>${escapeHtml(fence.join("\n"))}</code></pre>`);
    }
    return out.join("");
  }

  /** Unique docs URLs from searchDocs tool outputs on one message. */
  function extractCitations(msg) {
    const urls = [];
    for (const part of msg.parts || []) {
      const isSearch =
        typeof part.type === "string" && part.type.startsWith("tool-");
      if (!isSearch || part.state !== "output-available") continue;
      const output = typeof part.output === "string" ? part.output : "";
      for (const match of output.matchAll(
        /^\[\d+\]\s+(https?:\/\/\S+)\s+\(score/gm
      )) {
        const href = cleanDocsUrl(match[1]);
        if (href && !urls.includes(href)) {
          urls.push(href);
        }
      }
    }
    return urls;
  }

  /** Docs URLs the model actually linked in its prose, normalized. */
  function citedInProse(msg) {
    const hrefs = new Set();
    for (const match of messageText(msg).matchAll(/https?:\/\/[^\s<)\]]+/g)) {
      // Trim sentence punctuation the URL regex drags along.
      const href = cleanDocsUrl(match[0].replace(/[.,;:!?]+$/, ""));
      if (href) hrefs.add(href);
    }
    return hrefs;
  }

  function citationLabel(href) {
    const segments = href.split("/").filter((s) => s && !s.startsWith("http"));
    const leaf = segments.length ? segments[segments.length - 1] : "Home";
    const title = leaf
      .replace(/[-_]/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
    const trail = segments.slice(0, -1).join(" / ");
    return { title, trail };
  }

  function messageText(msg) {
    return (msg.parts || [])
      .filter((p) => p.type === "text")
      .map((p) => p.text)
      .join("");
  }

  // Follow the stream only while the visitor is at (or near) the bottom;
  // scrolling up mid-answer must not fight them. Measured directly from the
  // live scroll position right before each DOM update — a cached flag from
  // scroll events races with fast token streams and yanks the view down.
  function isPinned() {
    return (
      messagesEl.scrollHeight - messagesEl.scrollTop - messagesEl.clientHeight <
      40
    );
  }

  function scrollToBottom() {
    messagesEl.scrollTop = messagesEl.scrollHeight;
  }

  function assistantBody(msg) {
    const text = messageText(msg);
    return msg === streamingMsg && text === ""
      ? `<span class="ndc-dots"><i></i><i></i><i></i></span>${
          activity
            ? `<span class="ndc-activity">${escapeHtml(activity)}</span>`
            : ""
        }`
      : renderMarkdown(text);
  }

  function render(forcePin = false) {
    const pinned = forcePin || isPinned();
    const items = [];
    for (const msg of messages) {
      if (msg.role === "user") {
        items.push(
          `<div class="ndc-msg ndc-user">${escapeHtml(messageText(msg))}</div>`
        );
      } else if (msg.role === "assistant") {
        // Citation cards attach only after the turn finishes, so the
        // streaming text never shifts around them. Show only the pages the
        // model linked in its answer; if it wrote no links, fall back to
        // everything searchDocs retrieved so sources are never lost.
        let cardHrefs = [];
        if (msg !== streamingMsg) {
          const retrieved = extractCitations(msg);
          const used = citedInProse(msg);
          const cited = retrieved.filter((href) => used.has(href));
          cardHrefs = cited.length ? cited : retrieved;
        }
        const cards = cardHrefs
          .map((href) => {
            const { title, trail } = citationLabel(href);
            return `<a class="ndc-cite" href="${href}">
              <span class="ndc-cite-title">${escapeHtml(title)}</span>
              ${trail ? `<span class="ndc-cite-trail">${escapeHtml(trail)}</span>` : ""}
            </a>`;
          })
          .join("");
        items.push(
          `<div class="ndc-msg ndc-assistant">${assistantBody(msg)}${
            cards
              ? `<div class="ndc-cites" aria-label="Sources">${cards}</div>`
              : ""
          }</div>`
        );
      }
    }
    if (!items.length) {
      items.push(
        `<div class="ndc-empty">Ask about any published SOP, chemical procedure, or lab policy.</div>`
      );
    }
    messagesEl.innerHTML = items.join("");
    // The streaming message is always the last bubble; keep a handle so
    // token updates can patch it in place instead of rebuilding the list.
    streamingEl =
      streamingMsg &&
      messagesEl.lastElementChild?.classList.contains("ndc-assistant")
        ? messagesEl.lastElementChild
        : null;
    if (pinned) {
      scrollToBottom();
    }
    sendBtn.disabled = pending;
  }

  /** Token-cheap update: patch only the streaming bubble's contents. */
  function updateStreaming() {
    if (!streamingMsg) return;
    if (!streamingEl || !messagesEl.contains(streamingEl)) {
      render();
      return;
    }
    const pinned = isPinned();
    streamingEl.innerHTML = assistantBody(streamingMsg);
    if (pinned) {
      scrollToBottom();
    }
  }

  function setStatus(text) {
    statusEl.textContent = text || "";
    statusEl.hidden = !text;
  }

  // --- Agent transport -------------------------------------------------

  function ensureClient() {
    if (client) return client;
    client = new AgentClient({
      host: workerHost,
      agent: AGENT_NAME,
      name: conversationId
    });
    client.addEventListener("open", () => {
      setStatus("");
      // Only replay if a reply was mid-stream. Asking to resume an
      // already-finished turn hits the remote AI proxy and logs
      // "internal error; reference = …".
      if (pending) {
        client.send(JSON.stringify({ type: "cf_agent_stream_resume_request" }));
      }
    });
    client.addEventListener("close", () => {
      if (pending) {
        setStatus("Connection lost — reconnecting…");
      }
    });
    client.addEventListener("error", () => {
      setStatus("Assistant unreachable — retrying…");
    });
    client.addEventListener("message", (event) => {
      if (typeof event.data !== "string") return;
      let frame;
      try {
        frame = JSON.parse(event.data);
      } catch {
        return;
      }
      handleFrame(frame);
    });
    return client;
  }

  function beginAssistantMessage() {
    streamingMsg = { id: crypto.randomUUID(), role: "assistant", parts: [] };
    messages.push(streamingMsg);
    return streamingMsg;
  }

  function applyChunk(chunk) {
    const msg = streamingMsg || beginAssistantMessage();
    switch (chunk.type) {
      // The model reasons before every step, and there are quiet gaps
      // between steps — cover both so the visitor never stares at
      // silent dots wondering if the bot hung.
      case "start-step":
      case "reasoning-start":
        activity = "Thinking…";
        break;
      case "text-start":
        activity = "";
        msg.parts.push({ type: "text", text: "", _sid: chunk.id });
        break;
      case "text-delta": {
        let part = msg.parts.findLast(
          (p) => p.type === "text" && p._sid === chunk.id
        );
        if (!part) {
          part = { type: "text", text: "", _sid: chunk.id };
          msg.parts.push(part);
        }
        part.text += chunk.delta || "";
        break;
      }
      // Tool parts must stay schema-valid (toolCallId + input + output):
      // this whole list is sent back to the Agent on the next turn, and
      // convertToModelMessages rejects incomplete tool parts.
      case "tool-input-start":
        activity = "Searching the docs…";
        break;
      case "tool-input-available": {
        const query =
          chunk.input && typeof chunk.input.query === "string"
            ? chunk.input.query
            : "";
        activity = query ? `Searching: ${query}` : "Searching the docs…";
        msg.parts.push({
          type: `tool-${chunk.toolName || "searchDocs"}`,
          toolCallId: chunk.toolCallId,
          state: "input-available",
          input: chunk.input
        });
        break;
      }
      case "tool-output-available": {
        const part = msg.parts.find(
          (p) => p.toolCallId && p.toolCallId === chunk.toolCallId
        );
        if (part) {
          part.state = "output-available";
          part.output = chunk.output;
        }
        // The model goes straight back to reasoning over the results.
        activity = "Thinking…";
        break;
      }
      case "error": {
        const err = chunk.errorText || "Something went wrong — try again.";
        setStatus(err);
        if (!messageText(msg)) {
          msg.parts.push({ type: "text", text: err });
        }
        break;
      }
      default:
        break;
    }
    updateStreaming();
  }

  function finishTurn(keepStatus) {
    pending = false;
    streamingMsg = null;
    activity = "";
    if (!keepStatus) {
      setStatus("");
    }
    render();
    // Swap the locally-built turn for the Agent's persisted copy so the
    // next request carries exactly what the server has. Skip if it looks
    // stale (persistence can land just after the done frame).
    const localLen = messages.length;
    setTimeout(async () => {
      if (pending) return;
      try {
        const res = await fetch(
          `${httpBase}/agents/${AGENT_NAME}/${conversationId}/get-messages`
        );
        if (!res.ok) return;
        const server = await res.json();
        if (!pending && Array.isArray(server) && server.length >= localLen) {
          messages = server;
          render();
        }
      } catch {
        // keep the local copy
      }
    }, 600);
  }

  function handleFrame(frame) {
    switch (frame.type) {
      case "cf_agent_chat_messages":
        // Authoritative persisted list (sent to non-submitting connections
        // and after server-side updates).
        if (!pending) {
          messages = frame.messages || [];
          render();
        }
        break;
      case "cf_agent_use_chat_response":
        if (frame.error) {
          const err =
            typeof frame.body === "string" && frame.body
              ? frame.body
              : "Something went wrong — try again.";
          const msg = streamingMsg || beginAssistantMessage();
          if (!messageText(msg)) {
            msg.parts.push({ type: "text", text: err });
          }
          finishTurn(true);
          setStatus(err);
          break;
        }
        if (frame.body) {
          let chunk;
          try {
            chunk = JSON.parse(frame.body);
          } catch {
            chunk = null;
          }
          if (chunk) applyChunk(chunk);
        }
        if (frame.done) {
          finishTurn();
        }
        break;
      case "cf_agent_stream_resuming":
        pending = true;
        streamingMsg = null;
        activity = "Thinking…";
        client.send(
          JSON.stringify({ type: "cf_agent_stream_resume_ack", id: frame.id })
        );
        break;
      case "cf_agent_message_updated": {
        const idx = messages.findIndex((m) => m.id === frame.message?.id);
        if (idx >= 0) {
          messages[idx] = frame.message;
          render();
        }
        break;
      }
      default:
        break;
    }
  }

  async function loadHistory() {
    if (historyLoaded) return;
    try {
      const res = await fetch(
        `${httpBase}/agents/${AGENT_NAME}/${conversationId}/get-messages`
      );
      if (!res.ok) throw new Error(`HTTP ${res.status}`);
      const server = await res.json();
      historyLoaded = true;
      // Adopt only if the server knows more — the visitor may have already
      // typed a first question while this fetch was in flight.
      if (Array.isArray(server) && server.length > messages.length) {
        messages = server;
      }
      setStatus("");
      render();
    } catch {
      setStatus("Assistant unreachable — is it offline?");
    }
  }

  function sendQuestion(text) {
    const socket = ensureClient();
    // PartySocket buffers sends while connecting and flushes before the
    // open event, so a question typed immediately after opening still lands.
    if (socket.readyState !== 1 /* OPEN */) {
      setStatus("Connecting…");
    }
    activity = "Thinking…";
    messages.push({
      id: crypto.randomUUID(),
      role: "user",
      parts: [{ type: "text", text }]
    });
    pending = true;
    streamingMsg = null;
    socket.send(
      JSON.stringify({
        type: "cf_agent_use_chat_request",
        id: crypto.randomUUID(),
        init: {
          method: "POST",
          body: JSON.stringify({
            messages,
            // Hint only — the Worker's system prompt keeps search corpus-wide.
            page: window.location.origin + window.location.pathname
          })
        }
      })
    );
    // Asking a question snaps back to following the reply.
    render(true);
  }

  function newConversation() {
    conversationId = crypto.randomUUID();
    sessionStorage.setItem(STORAGE_KEY, conversationId);
    if (client) {
      client.close();
      client = null;
    }
    messages = [];
    streamingMsg = null;
    streamingEl = null;
    pending = false;
    historyLoaded = true; // fresh instance has no history to fetch
    setStatus("");
    render();
    ensureClient();
  }

  // --- UI events -----------------------------------------------------

  function openPanel() {
    panel.hidden = false;
    fab.setAttribute("aria-expanded", "true");
    root.classList.add("ndc-open");
    ensureClient();
    loadHistory();
    render(true);
    input.focus();
  }

  function closePanel() {
    panel.hidden = true;
    fab.setAttribute("aria-expanded", "false");
    root.classList.remove("ndc-open");
  }

  fab.addEventListener("click", () => {
    if (panel.hidden) openPanel();
    else closePanel();
  });
  root.querySelector(".ndc-close").addEventListener("click", closePanel);
  root.querySelector(".ndc-reset").addEventListener("click", newConversation);
  document.addEventListener("keydown", (e) => {
    if (e.key === "Escape" && !panel.hidden) closePanel();
  });

  form.addEventListener("submit", (e) => {
    e.preventDefault();
    const text = input.value.trim();
    if (!text || pending) return;
    sendQuestion(text);
    input.value = "";
    input.style.height = "";
  });
  input.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      form.requestSubmit();
    }
  });
  input.addEventListener("input", () => {
    input.style.height = "";
    input.style.height = `${Math.min(input.scrollHeight, 120)}px`;
  });
}
