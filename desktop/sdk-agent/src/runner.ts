import { Agent } from "@cursor/sdk";
import * as readline from "node:readline";
import { stdin, stdout } from "node:process";
import { randomUUID } from "node:crypto";

type JsonValue =
  | string
  | number
  | boolean
  | null
  | JsonValue[]
  | { [key: string]: JsonValue };

type ToolSpec = {
  name: string;
  description?: string;
  inputSchema?: Record<string, JsonValue>;
};

type RunCommand = {
  type: "run";
  id: string;
  prompt: string;
  model?: string;
  cwd?: string;
  mode?: "design" | "run";
  tools?: ToolSpec[];
  resumeAgentId?: string;
};

type ToolResultCommand = {
  type: "tool_result";
  requestId: string;
  ok?: boolean;
  result?: Record<string, JsonValue>;
  error?: string;
};

type CancelCommand = {
  type: "cancel";
  id?: string;
};

type Command = RunCommand | ToolResultCommand | CancelCommand;

type PendingTool = {
  resolve: (value: ToolResultCommand) => void;
  reject: (error: Error) => void;
  timer: ReturnType<typeof setTimeout>;
};

const pendingTools = new Map<string, PendingTool>();

function emit(payload: Record<string, unknown>): void {
  stdout.write(JSON.stringify(payload) + "\n");
}

function safeError(error: unknown): string {
  if (error instanceof Error) return error.message;
  return String(error || "Unknown error");
}

function normalizeToolName(name: string): string {
  return (name || "").trim();
}

function stringFrom(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function recordFrom(value: unknown): Record<string, unknown> {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : {};
}

function requestIdFrom(value: unknown): string {
  const rec = recordFrom(value);
  return (
    stringFrom(rec.call_id) ||
    stringFrom(rec.callId) ||
    stringFrom(rec.toolCallId) ||
    stringFrom(rec.requestId) ||
    stringFrom(rec.id)
  );
}

function toolNameFrom(value: unknown, fallback = ""): string {
  const rec = recordFrom(value);
  const direct = stringFrom(rec.name) || stringFrom(rec.type) || fallback;
  const args = recordFrom(rec.args || rec.arguments);
  if (direct.toLowerCase() === "mcp") {
    const inner = stringFrom(args.toolName) || stringFrom(args.tool) || stringFrom(args.name);
    if (inner) return inner;
  }
  return direct;
}

function emitSdkToolCall(event: Record<string, unknown>, extra: Record<string, unknown> = {}): void {
  const args = recordFrom(event.args || event.arguments);
  const provider = stringFrom(args.providerIdentifier);
  const rawName = stringFrom(event.name) || stringFrom(event.type);
  if (rawName.toLowerCase() === "mcp" && provider === "custom-user-tools") {
    return;
  }
  emit({
    type: "tool_call",
    tool: toolNameFrom(event, rawName),
    status: stringFrom(event.status) || "running",
    requestId: requestIdFrom(event),
    arguments: args,
    result: event.result,
    ...extra,
  });
}

function emitNestedTask(parentId: string, nested: unknown): void {
  const update = recordFrom(nested);
  const kind = stringFrom(update.type);
  if (kind === "thinking-delta" || kind === "text-delta") {
    const text = stringFrom(update.text);
    if (!text) return;
    emit({ type: "task", requestId: parentId, status: "running", text });
    return;
  }
  if (kind !== "tool-call-started" && kind !== "partial-tool-call" && kind !== "tool-call-completed") {
    return;
  }
  const toolCall = recordFrom(update.toolCall);
  const args = recordFrom(toolCall.args || toolCall.arguments);
  const name = toolNameFrom(toolCall, stringFrom(toolCall.type));
  const childId = requestIdFrom(update) || requestIdFrom(toolCall);
  const completed = kind === "tool-call-completed";
  if (childId && childId !== parentId) {
    emit({
      type: "tool_call",
      tool: name || "task",
      status: completed ? stringFrom(update.status) || "completed" : "running",
      requestId: childId,
      parentId,
      arguments: args,
      result: toolCall.result ?? update.result,
    });
  }
  if (name) {
    emit({
      type: "task",
      requestId: parentId,
      status: "running",
      text: completed ? `\nГотово: ${name}` : `\nВыполняется: ${name}`,
    });
  }
}

const ASK_QUESTION_SCHEMA: Record<string, JsonValue> = {
  type: "object",
  properties: {
    question: {
      type: "string",
      description: "Один вопрос про один параметр. Не объединяй несколько вопросов.",
    },
    options: {
      type: "array",
      items: { type: "string" },
      description: "Необязательные варианты ответа",
    },
  },
  required: ["question"],
};

function isAskQuestion(name: string): boolean {
  const folded = normalizeToolName(name).toLowerCase();
  return folded === "askquestion" || folded === "ask_question";
}

function questionPayload(args: Record<string, unknown>): { question: string; options: string[] } {
  const question =
    stringFrom(args.question) ||
    stringFrom(args.prompt) ||
    stringFrom(args.title) ||
    stringFrom(args.message);
  const rawOptions = Array.isArray(args.options)
    ? args.options
    : Array.isArray(args.choices)
      ? args.choices
      : Array.isArray(args.answers)
        ? args.answers
        : [];
  const options = rawOptions
    .map((item) => {
      if (typeof item === "string") return item.trim();
      if (item && typeof item === "object") {
        const record = item as Record<string, unknown>;
        return stringFrom(record.label) || stringFrom(record.text) || stringFrom(record.value);
      }
      return "";
    })
    .filter(Boolean)
    .slice(0, 6);
  return { question, options };
}

async function executeAskQuestion(args: Record<string, JsonValue>): Promise<JsonValue> {
  const { question, options } = questionPayload(args as Record<string, unknown>);
  const requestId = randomUUID();
  emit({
    type: "tool_call",
    requestId,
    tool: "askQuestion",
    arguments: args || {},
  });
  if (question) {
    emit({ type: "question", requestId, question, options, arguments: args });
  }
  emit({
    type: "tool_request",
    requestId,
    tool: "askQuestion",
    arguments: args || {},
  });
  const payload = await waitForToolResult(requestId);
  const result = payload.result && typeof payload.result === "object" ? payload.result : {};
  const answer =
    stringFrom((result as Record<string, unknown>).answer) ||
    stringFrom((result as Record<string, unknown>).text) ||
    stringFrom(payload.error);
  const ok = payload.ok !== false && Boolean(answer);
  emit({
    type: "tool_result",
    requestId,
    tool: "askQuestion",
    ok,
    result: { answer, text: answer },
  });
  if (!ok) {
    return {
      content: [{ type: "text", text: answer || "Пользователь не ответил" }],
      isError: true,
    };
  }
  return {
    content: [{ type: "text", text: `Ответ пользователя: ${answer}` }],
  };
}

function buildCustomTools(specs: ToolSpec[]): Record<string, unknown> {
  const tools: Record<string, unknown> = {};
  for (const spec of specs) {
    const name = normalizeToolName(spec.name);
    if (!name || tools[name]) continue;
    if (isAskQuestion(name)) {
      tools.askQuestion = {
        description: spec.description || "Задать вопрос пользователю на рабочем столе и дождаться ответа.",
        inputSchema: spec.inputSchema || ASK_QUESTION_SCHEMA,
        execute: executeAskQuestion,
      };
      continue;
    }
    tools[name] = {
      description: spec.description || name,
      inputSchema: spec.inputSchema || { type: "object", properties: {} },
      async execute(args: Record<string, JsonValue>) {
        const requestId = randomUUID();
        emit({
          type: "tool_call",
          requestId,
          tool: name,
          arguments: args || {},
        });
        emit({
          type: "tool_request",
          requestId,
          tool: name,
          arguments: args || {},
        });
        const payload = await waitForToolResult(requestId);
        if (!payload.ok) {
          const message = payload.error || `Tool ${name} failed`;
          emit({ type: "tool_result", requestId, tool: name, ok: false, error: message });
          return {
            content: [{ type: "text", text: message }],
            isError: true,
            structuredContent: { error: message },
          };
        }
        const result = payload.result || {};
        const skipped = Boolean((result as { skipped?: unknown }).skipped);
        emit({ type: "tool_result", requestId, tool: name, ok: true, skipped, result });
        return modelView(result);
      },
    };
  }
  if (!tools.askQuestion) {
    tools.askQuestion = {
      description: "Ask the desktop user a question and wait for the answer.",
      inputSchema: ASK_QUESTION_SCHEMA,
      execute: executeAskQuestion,
    };
  }
  return tools;
}

function testsPassReady(text: string): boolean {
  const upper = (text || "").toUpperCase();
  if (upper.includes("TESTS: FAIL") || upper.includes("TESTS:FAIL")) {
    return false;
  }
  return upper.includes("TESTS: PASS") || upper.includes("TESTS:PASS");
}

function playbookDraftReady(text: string): boolean {
  const raw = (text || "").trim();
  if (!raw) return false;
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/i);
  const blob = fence?.[1]?.trim() || raw.slice(raw.indexOf("{"), raw.lastIndexOf("}") + 1);
  if (!blob || blob[0] !== "{") return false;
  try {
    const data = JSON.parse(blob) as { steps?: unknown };
    return Array.isArray(data.steps) && data.steps.length > 0;
  } catch {
    return false;
  }
}

async function settleRun(run: {
  supports: (op: "cancel") => boolean;
  status: string;
  cancel: () => Promise<void>;
  wait: () => Promise<unknown>;
}): Promise<void> {
  try {
    if (run.supports("cancel") && String(run.status || "").toLowerCase() === "running") {
      await run.cancel();
    }
  } catch {
    // Already terminal or cancel is unsupported.
  }
  try {
    await run.wait();
  } catch {
    // The follow-up send can still resume from the persisted agent.
  }
}

const MODEL_RESULT_CHARS = 8000;
const MODEL_NEXT_STEP =
  "Full JSON is in result_file. Open it with the built-in Read tool in pages (offset/limit) or search inside it; do not load the whole file at once. Do not recall the same Constructor tool for this data.";

function compactSummary(rec: Record<string, JsonValue>): Record<string, JsonValue> {
  const summary: Record<string, JsonValue> = {};
  const text = rec.summary;
  if (typeof text === "string" && text.trim()) {
    summary.summary = text.trim();
  }
  for (const [key, value] of Object.entries(rec)) {
    if (value === null || typeof value === "number" || typeof value === "boolean") {
      summary[key] = value;
    } else if (typeof value === "string") {
      summary[key] = value.slice(0, 500);
    } else if (Array.isArray(value)) {
      summary[`${key}_count`] = value.length;
    } else if (value && typeof value === "object") {
      summary[`${key}_keys`] = Object.keys(value).slice(0, 20);
    }
  }
  return summary;
}

function modelView(result: JsonValue): JsonValue {
  if (!result || typeof result !== "object" || Array.isArray(result)) {
    return result;
  }
  const rec = result as Record<string, JsonValue>;
  const resultFile =
    typeof rec.result_file === "string" && rec.result_file.trim() ? rec.result_file : null;
  // The Python bridge already returns a minimal pointer for large results.
  if (resultFile) {
    if (typeof rec.next_step === "string" && rec.next_step.trim()) {
      return rec;
    }
    return { ...rec, next_step: MODEL_NEXT_STEP };
  }
  const raw = JSON.stringify(rec);
  if (raw.length <= MODEL_RESULT_CHARS) {
    return rec;
  }
  // Oversized but no result_file was written: fall back to a compact summary.
  return {
    ...compactSummary(rec),
    next_step:
      "Result was too large and no result_file was written. Use this summary; do not invent a file.",
  };
}

function waitForToolResult(requestId: string, timeoutMs = 15 * 60 * 1000): Promise<ToolResultCommand> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => {
      pendingTools.delete(requestId);
      reject(new Error(`Tool result timeout: ${requestId}`));
    }, timeoutMs);
    pendingTools.set(requestId, { resolve, reject, timer });
  });
}

function receiveToolResult(command: ToolResultCommand): void {
  const pending = pendingTools.get(command.requestId);
  if (!pending) return;
  clearTimeout(pending.timer);
  pendingTools.delete(command.requestId);
  pending.resolve(command);
}

function readAgentId(agent: unknown, fallback: string): string {
  const record = agent && typeof agent === "object" ? (agent as Record<string, unknown>) : {};
  const value = record.agentId || record.agent_id || record.id;
  return typeof value === "string" && value.trim() ? value.trim() : fallback;
}

function isActiveRunError(error: unknown): boolean {
  const message = safeError(error).toLowerCase();
  return message.includes("already has active run") || message.includes("agentbusy");
}

async function runAgent(command: RunCommand): Promise<void> {
  const id = command.id || randomUUID();
  const model = command.model || process.env.CURSOR_SDK_MODEL || "grok-4.6";
  const cwd = command.cwd || process.cwd();
  const apiKey = process.env.CURSOR_API_KEY || "";
  if (!apiKey.trim()) {
    emit({ type: "error", id, message: "CURSOR_API_KEY is not set" });
    emit({ type: "done", id, status: "error", answer: "" });
    return;
  }
  if (!command.prompt.trim()) {
    emit({ type: "error", id, message: "Empty prompt" });
    emit({ type: "done", id, status: "error", answer: "" });
    return;
  }

  let answer = "";
  let thought = "";
  emit({ type: "run", id });
  emit({ type: "status", text: "Запускаю локальный Cursor SDK агент..." });
  const design = command.mode === "design";
  const customTools = buildCustomTools(command.tools || []);
  const customNames = Object.keys(customTools);
  emit({
    type: "status",
    text: customNames.length
      ? `Инструменты Constructor: ${customNames.slice(0, 24).join(", ")}${customNames.length > 24 ? ` (+${customNames.length - 24})` : ""}`
      : "Инструменты Constructor пустые. Не ищи проектные MCP-серверы.",
  });
  let agent: Awaited<ReturnType<typeof Agent.create>> | undefined;
  try {
    const agentOptions = {
      apiKey,
      model: { id: model },
      local: {
        cwd,
        customTools: customTools as never,
        // Do not load repo .cursor/mcp.json. Constructor tools come from customTools.
        settingSources: [],
      },
    };
    agent = command.resumeAgentId
      ? await Agent.resume(command.resumeAgentId, agentOptions as never)
      : await Agent.create(agentOptions as never);
    const agentId = readAgentId(agent, command.resumeAgentId || "");
    emit({ type: "agent", id, agentId, resumed: Boolean(command.resumeAgentId) });
    const sendOptions = {
      local: {
        force: true,
        customTools: customTools as never,
      },
      onDelta: (payload: { update?: Record<string, unknown> }) => {
        const update = recordFrom(payload?.update);
        if (stringFrom(update.type) !== "tool-call-delta") return;
        const parentId = requestIdFrom(update);
        if (!parentId) return;
        emitNestedTask(parentId, update.taskUpdate);
      },
    };
    let run;
    try {
      run = await agent.send(command.prompt, sendOptions as never);
    } catch (error) {
      if (!command.resumeAgentId || !isActiveRunError(error)) {
        throw error;
      }
      emit({ type: "status", text: "Закрываю предыдущий запуск того же агента..." });
      run = await agent.send(command.prompt, sendOptions as never);
    }
    emit({ type: "status", text: "Агент работает на этом компьютере..." });
    const finishIfReady = async (draft: string): Promise<boolean> => {
      const designReady = design && playbookDraftReady(draft);
      const demoReady = !design && testsPassReady(draft);
      if (!designReady && !demoReady) return false;
      emit({
        type: "status",
        text: designReady
          ? "Черновик готов. Останавливаю этот ход и перехожу к пробному прогону."
          : "Пробный прогон завершен (TESTS: PASS). Останавливаю этот ход.",
      });
      emit({ type: "final", id, status: "ok", answer: draft });
      emit({ type: "done", id, status: "ok", answer: draft });
      await settleRun(run);
      await agent.close();
      return true;
    };
    for await (const event of run.stream()) {
      if (event.type === "assistant") {
        for (const block of event.message.content) {
          if (block.type === "text" && block.text) {
            answer += block.text;
            emit({ type: "assistant", text: block.text });
            if (await finishIfReady(answer)) return;
          }
        }
      } else if (event.type === "thinking" && event.text) {
        thought += event.text;
        emit({ type: "thinking", text: event.text });
        if ((await finishIfReady(thought)) || (await finishIfReady(answer))) return;
      } else if (event.type === "tool_call") {
        emitSdkToolCall(event as unknown as Record<string, unknown>);
      } else if (event.type === "task") {
        const rec = event as { status?: string; text?: string };
        emit({
          type: "task",
          requestId: requestIdFrom(event),
          status: rec.status || "running",
          text: rec.text || "",
        });
      } else if (event.type === "system") {
        const listed = Array.isArray(event.tools) ? event.tools.filter(Boolean) : [];
        emit({
          type: "status",
          text: listed.length
            ? `Cursor SDK tools: ${listed.join(", ")}`
            : "Агент обновил состояние запуска.",
        });
      }
    }
    const result = await run.wait();
    const status = String(result.status || "").toLowerCase();
    emit({
      type: "final",
      id,
      status: status === "finished" || status === "success" ? "ok" : status || "ok",
      answer: answer || String(result.result || ""),
    });
    emit({
      type: "done",
      id,
      status: status === "finished" || status === "success" ? "ok" : status || "ok",
      answer: answer || String(result.result || ""),
    });
  } catch (error) {
    const message = safeError(error);
    emit({ type: "error", id, message });
    emit({ type: "done", id, status: "error", answer: message });
  } finally {
    try {
      await agent?.close();
    } catch {
      // Ignore close errors: the run already produced its terminal status.
    }
  }
}

const rl = readline.createInterface({ input: stdin, crlfDelay: Infinity });
rl.on("line", (line: string) => {
  if (!line.trim()) return;
  let command: Command;
  try {
    command = JSON.parse(line) as Command;
  } catch (error) {
    emit({ type: "error", message: `Bad JSON command: ${safeError(error)}` });
    return;
  }
  if (command.type === "tool_result") {
    receiveToolResult(command);
    return;
  }
  if (command.type === "run") {
    void runAgent(command);
    return;
  }
  if (command.type === "cancel") {
    emit({ type: "status", text: "Отмена будет применена после текущего шага." });
  }
});

emit({ type: "ready" });
