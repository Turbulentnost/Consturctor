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

function buildCustomTools(specs: ToolSpec[], design: boolean): Record<string, unknown> {
  const tools: Record<string, unknown> = {};
  for (const spec of specs) {
    const name = normalizeToolName(spec.name);
    if (!name || tools[name]) continue;
    tools[name] = {
      description: spec.description || name,
      inputSchema: spec.inputSchema || { type: "object", properties: {} },
      async execute(args: Record<string, JsonValue>) {
        if (design) {
          const message =
            `Design mode: ${name} is registered as a Constructor customTool, not project MCP. ` +
            "Do not execute it now. If a business parameter is missing, ask the user.";
          emit({
            type: "tool_call",
            tool: name,
            status: "blocked_in_design",
            arguments: args || {},
            mode: "design",
          });
          emit({
            type: "tool_result",
            tool: name,
            ok: true,
            status: "skipped",
            skipped: true,
            result: { text: message },
          });
          return {
            content: [{ type: "text", text: message }],
          };
        }
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
        emit({ type: "tool_result", requestId, tool: name, ok: true, result });
        return result as JsonValue;
      },
    };
  }
  return tools;
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
  emit({ type: "run", id });
  emit({ type: "status", text: "Запускаю локальный Cursor SDK агент..." });
  const design = command.mode === "design";
  const customTools = buildCustomTools(command.tools || [], design);
  const customNames = Object.keys(customTools);
  emit({
    type: "status",
    text: customNames.length
      ? `Constructor customTools: ${customNames.slice(0, 24).join(", ")}${customNames.length > 24 ? ` (+${customNames.length - 24})` : ""}`
      : "Constructor customTools are empty. Do not look for project MCP servers.",
  });
  let agent: Awaited<ReturnType<typeof Agent.create>> | undefined;
  try {
    agent = await Agent.create({
      apiKey,
      model: { id: model },
      local: {
        cwd,
        customTools: customTools as never,
        // Do not load repo .cursor/mcp.json. Constructor tools come from customTools.
        settingSources: [],
      },
      // mcp is required for customTools. askQuestion lets the planner ask the user.
      // An mcp-only allowlist with empty customTools made the model say "no MCP found".
      tools: customNames.length > 0 ? ["mcp", "askQuestion"] : ["askQuestion"],
    });
    const run = await agent.send(command.prompt);
    emit({ type: "status", text: "Агент работает на этом компьютере..." });
    for await (const event of run.stream()) {
      if (event.type === "assistant") {
        for (const block of event.message.content) {
          if (block.type === "text" && block.text) {
            answer += block.text;
            emit({ type: "assistant", text: block.text });
          }
        }
      } else if (event.type === "thinking" && event.text) {
        emit({ type: "thinking", text: event.text });
      } else if (event.type === "tool_call") {
        const args = event.args && typeof event.args === "object" ? event.args : {};
        emit({
          type: "tool_call",
          tool: event.name,
          status: event.status,
          arguments: args,
        });
        if (event.name === "askQuestion") {
          const { question, options } = questionPayload(args as Record<string, unknown>);
          if (question) {
            emit({ type: "question", question, options, arguments: args });
          }
        }
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
