// Scratch smoke test for the chat agent over the Agents WebSocket protocol.
// Each CLI arg is one turn in the same conversation, sent sequentially.
// Usage: node scratch-chat-test.mjs "question 1" ["follow-up 2" ...]
const questions = process.argv.slice(2);
if (!questions.length) {
  questions.push("What PPE do I need to use HF?");
}
const conversationId = crypto.randomUUID();
const url = `ws://localhost:5173/agents/chat-agent/${conversationId}`;
const started = Date.now();
const t = () => `[+${((Date.now() - started) / 1000).toFixed(1)}s]`;

const ws = new WebSocket(url);
const history = [];
let turn = 0;
let turnStarted = 0;
let text = "";
let firstTokenAt = null;

const bail = setTimeout(() => {
  console.log(`${t()} TIMEOUT (240s)`);
  process.exit(1);
}, 240_000);

function askNext() {
  const question = questions[turn];
  turnStarted = Date.now();
  text = "";
  firstTokenAt = null;
  history.push({
    id: crypto.randomUUID(),
    role: "user",
    parts: [{ type: "text", text: question }]
  });
  console.log(`${t()} TURN ${turn + 1}: ${question}`);
  ws.send(
    JSON.stringify({
      type: "cf_agent_use_chat_request",
      id: crypto.randomUUID(),
      init: {
        method: "POST",
        body: JSON.stringify({
          messages: history,
          page: "http://localhost:8000/"
        })
      }
    })
  );
}

async function finishTurn() {
  console.log(`--- answer (turn ${turn + 1}) ---`);
  console.log(text);
  // Adopt the server's persisted copy so the next turn carries exactly
  // what the agent has (mirrors the widget's behavior).
  const res = await fetch(
    `http://localhost:5173/agents/chat-agent/${conversationId}/get-messages`
  );
  const persisted = await res.json();
  history.length = 0;
  history.push(...persisted);
  const last = persisted[persisted.length - 1];
  const partTypes = (last?.parts ?? []).map((p) => p.type).join(", ");
  console.log(
    `--- persisted: ${persisted.length} messages; last role=${last?.role} parts=[${partTypes}]`
  );
  turn += 1;
  if (turn < questions.length) {
    askNext();
  } else {
    clearTimeout(bail);
    process.exit(0);
  }
}

ws.addEventListener("open", askNext);

ws.addEventListener("message", async (event) => {
  let frame;
  try {
    frame = JSON.parse(event.data);
  } catch {
    return;
  }
  if (frame.type !== "cf_agent_use_chat_response") return;
  if (frame.error) {
    console.log(`${t()} ERROR frame: ${frame.body}`);
    process.exit(1);
  }
  if (frame.body) {
    let chunk;
    try {
      chunk = JSON.parse(frame.body);
    } catch {
      return;
    }
    if (chunk.type === "text-delta") {
      if (!firstTokenAt) {
        firstTokenAt = Date.now();
        console.log(
          `${t()} first token (${((firstTokenAt - turnStarted) / 1000).toFixed(1)}s into turn)`
        );
      }
      text += chunk.delta ?? "";
    } else if (chunk.type === "tool-output-available") {
      const preview = String(chunk.output).slice(0, 160).replace(/\n/g, " | ");
      console.log(`${t()} tool output: ${preview}...`);
    } else {
      console.log(`${t()} chunk: ${chunk.type}`);
    }
  }
  if (frame.done) {
    await finishTurn();
  }
});

ws.addEventListener("error", () => {
  console.log(`${t()} WS error — is the dev server on :5173 up?`);
  process.exit(1);
});
