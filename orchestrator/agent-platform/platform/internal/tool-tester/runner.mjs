// Служебный тестировщик инструментов платформы (не конфигурация: в списке конфигураций его нет).
//
// Алгоритм одного запуска:
//   1. Платформа пишет в stdin одну JSON-строку запроса: prompt (задача тестировщика с карточкой
//      инструмента), cwd (папка сессии), model, resumeAgentId, title, storeDir.
//   2. Создаём локального агента Cursor SDK только с MCP-инструментами и чтением файлов:
//      ни терминала, ни правки файлов, ни подагентов — проверяется один инструмент.
//   3. Подключаем MCP-сервер mcp_server.py: тестируемый инструмент (TURBOTESTER_TEST_TOOL,
//      вызов через API TurboTester; изменяющие данные — только после разрешения человека),
//      wait_call, ask_user и wait_answer.
//   4. Отправляем промпт как есть.
//   5. Транслируем поток SDK в stdout построчным JSON: agent, status, thinking,
//      assistant, tool_call, usage, done. Строка {"type":"cancel"} в stdin отменяет запуск.
//   6. Для панели «Взаимодействие» каждое обращение к SDK и каждое событие его потока
//      дублируются строкой trace. Контекст платформа собирает сама по шагам потока;
//      в tool_call для этого передаётся полный размер аргументов и результата.

import { Agent, CursorAgentError, JsonlLocalAgentStore } from "@cursor/sdk";
import { readFileSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";
import * as readline from "node:readline";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_MODEL = "grok-4.7";
const PREVIEW_STRING_CHARS = 12000;
const PREVIEW_ITEMS = 200;
const IMAGE_PREVIEW_CHARS = 4_000_000;

function emit(payload) {
  writeSync(1, `${JSON.stringify(payload)}\n`);
}

function trace(dir, kind, data, extra = {}) {
  emit({ type: "trace", dir, kind, data, ...extra });
}

function asText(value) {
  if (value === undefined || value === null) return "";
  return typeof value === "string" ? value : JSON.stringify(value);
}

function describeOptions(options, request) {
  const server = options.mcpServers.tester;
  return {
    apiKey: "***",
    model: options.model,
    name: options.name,
    tools: options.tools,
    mcpServers: {
      tester: {
        type: server.type,
        command: server.command,
        args: server.args,
        cwd: server.cwd,
        env: "окружение платформы (TURBOTESTER_TEST_TOOL…) + PYTHONIOENCODING, PYTHONUTF8, TURBOTESTER_SESSION_DIR",
      },
    },
    local: {
      cwd: options.local.cwd,
      settingSources: options.local.settingSources,
      store: request.storeDir ? `JsonlLocalAgentStore(${request.storeDir})` : "по умолчанию",
    },
  };
}

function message(error) {
  return error instanceof Error ? error.message : String(error ?? "Неизвестная ошибка");
}

// Обрезаем каждую строку и массив по отдельности: JSON остаётся разбираемым,
// и карточка инструмента в чате видит структуру даже у огромного ответа.
function compact(value, stringLimit) {
  if (typeof value === "string") {
    return value.length > stringLimit ? `${value.slice(0, stringLimit)}…` : value;
  }
  if (Array.isArray(value)) {
    const items = value.slice(0, PREVIEW_ITEMS).map((item) => compact(item, stringLimit));
    if (value.length > PREVIEW_ITEMS) items.push(`… ещё ${value.length - PREVIEW_ITEMS}`);
    return items;
  }
  if (value && typeof value === "object") {
    return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, compact(item, stringLimit)]));
  }
  return value;
}

function preview(value, stringLimit = PREVIEW_STRING_CHARS) {
  if (value === undefined || value === null) return undefined;
  return typeof value === "string" ? compact(value, stringLimit) : JSON.stringify(compact(value, stringLimit));
}

function stringEnv(source) {
  const env = {};
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === "string") env[key] = value;
  }
  return env;
}

function testerMcp(request) {
  return {
    tester: {
      type: "stdio",
      command: request.python || "python",
      args: [join(HERE, "mcp_server.py")],
      cwd: request.cwd,
      env: stringEnv({
        ...process.env,
        PYTHONIOENCODING: "utf-8",
        PYTHONUTF8: "1",
        TURBOTESTER_SESSION_DIR: request.cwd,
      }),
    },
  };
}

// SDKUserMessage: текст плюс фотографии; без вложений — просто строка промпта.
function userMessage(request) {
  const prompt = String(request.prompt || "").trim();
  const attachments = Array.isArray(request.attachments) ? request.attachments : [];
  if (!attachments.length) return { message: prompt, shown: { prompt } };
  const listing = attachments
    .map((item) => `- ${item.path}${item.image ? " (изображение, приложено к сообщению)" : ""}`)
    .join("\n");
  const text = [prompt, `Вложения пользователя:\n${listing}`].filter(Boolean).join("\n\n");
  const images = attachments
    .filter((item) => item.image)
    .map((item) => ({ data: readFileSync(item.path).toString("base64"), mimeType: item.mime }));
  return {
    message: images.length ? { text, images } : text,
    shown: {
      prompt: text,
      images: attachments
        .filter((item) => item.image)
        .map((item, index) => ({ name: item.name, mimeType: item.mime, base64Chars: images[index].data.length })),
    },
  };
}

async function readRequest(lines) {
  for await (const line of lines) {
    if (line.trim()) return JSON.parse(line);
  }
  throw new Error("Платформа не передала запрос запуска");
}

async function main() {
  const lines = readline.createInterface({ input: process.stdin, crlfDelay: Infinity });
  const iterator = lines[Symbol.asyncIterator]();
  const request = await readRequest({ [Symbol.asyncIterator]: () => iterator });

  const apiKey = (process.env.CURSOR_API_KEY || "").trim();
  if (!apiKey) throw new Error("CURSOR_API_KEY не задан в backend/.env");
  const { message: sdkMessage, shown } = userMessage(request);
  if (!shown.prompt) throw new Error("Пустой промпт");

  const options = {
    apiKey,
    model: { id: request.model || DEFAULT_MODEL },
    name: request.title || undefined,
    // Не сохраняется в агенте: передаётся и при Agent.resume, потому что options общие.
    tools: ["mcp", "read"],
    mcpServers: testerMcp(request),
    local: {
      cwd: request.cwd,
      settingSources: [],
      // Хранилище SQLite по умолчанию на этой машине не открывает свою базу в конце хода
      // («unable to open database file»): ход не завершается, и SDK повторяет его по таймауту.
      ...(request.storeDir ? { store: new JsonlLocalAgentStore(request.storeDir) } : {}),
    },
  };

  emit({ type: "status", text: request.resumeAgentId ? "Продолжаю диалог с агентом…" : "Создаю агента Cursor SDK…" });
  const described = describeOptions(options, request);
  let agent;
  try {
    if (request.resumeAgentId) {
      trace("runner→sdk", "Agent.resume", { agentId: request.resumeAgentId, options: described });
      agent = await Agent.resume(request.resumeAgentId, options);
    } else {
      trace("runner→sdk", "Agent.create", described);
      agent = await Agent.create(options);
    }
  } catch (error) {
    trace("sdk→runner", "ошибка", { message: message(error) });
    if (!request.resumeAgentId) throw error;
    emit({ type: "status", text: `Прежний агент недоступен (${message(error)}). Создаю нового.` });
    trace("runner→sdk", "Agent.create", described);
    agent = await Agent.create(options);
  }
  trace("sdk→runner", "агент", { agentId: agent.agentId });

  try {
    emit({ type: "agent", agentId: agent.agentId });
    const sendOptions = { local: { force: true } };
    trace("runner→sdk", "agent.send", { ...shown, options: sendOptions }, { text: shown.prompt });
    const run = await agent.send(sdkMessage, sendOptions);
    trace("sdk→runner", "run", { runId: run.id, requestId: run.requestId, status: run.status });
    emit({ type: "status", text: "Агент работает", runId: run.id });

    let cancelled = false;
    (async () => {
      for await (const line of { [Symbol.asyncIterator]: () => iterator }) {
        let command;
        try {
          command = JSON.parse(line);
        } catch {
          continue;
        }
        if (command?.type === "cancel" && !cancelled) {
          cancelled = true;
          emit({ type: "status", text: "Отменяю запуск…" });
          if (run.supports("cancel")) {
            trace("runner→sdk", "run.cancel", { runId: run.id });
            await run.cancel().catch(() => undefined);
          }
        }
      }
    })();

    trace("runner→sdk", "run.stream", { runId: run.id });
    for await (const event of run.stream()) {
      if (event.type === "assistant") {
        const text = event.message.content.map((block) => (block.type === "text" ? block.text : "")).join("");
        const extra = event.message.content.filter((block) => block.type !== "text");
        if (text) trace("sdk→runner", "assistant", undefined, { text, merge: true });
        if (extra.length) trace("sdk→runner", "assistant: блоки", extra);
      } else if (event.type === "thinking") {
        if (event.text) trace("sdk→runner", "thinking", undefined, { text: event.text, merge: true });
      } else {
        trace("sdk→runner", event.type, event);
      }

      if (event.type === "assistant") {
        for (const block of event.message.content) {
          if (block.type === "text" && block.text) emit({ type: "assistant", text: block.text });
        }
      } else if (event.type === "thinking" && event.text) {
        emit({ type: "thinking", text: event.text });
      } else if (event.type === "tool_call") {
        const done = event.status !== "running";
        emit({
          type: "tool_call",
          callId: event.call_id,
          name: event.name,
          status: event.status,
          argsChars: asText(event.args).length,
          resultChars: done ? asText(event.result).length : 0,
          args: preview(event.args),
          result: done
            ? preview(event.result, event.name === "generateImage" ? IMAGE_PREVIEW_CHARS : PREVIEW_STRING_CHARS)
            : undefined,
        });
      } else if (event.type === "system" && Array.isArray(event.tools)) {
        emit({ type: "status", text: `Инструменты: ${event.tools.length}`, tools: event.tools });
      } else if (event.type === "task" && event.text) {
        emit({ type: "status", text: event.text });
      } else if (event.type === "usage") {
        emit({ type: "usage", usage: event.usage });
      } else if (event.type === "status" && event.message) {
        emit({ type: "status", text: event.message });
      }
    }

    trace("runner→sdk", "run.wait", { runId: run.id });
    const result = await run.wait();
    trace("sdk→runner", "результат хода", {
      status: result.status,
      durationMs: result.durationMs,
      model: result.model,
      usage: result.usage,
      error: result.error,
      result: result.result,
    });
    emit({
      type: "done",
      status: cancelled ? "cancelled" : result.status,
      result: typeof result.result === "string" ? result.result : undefined,
      agentId: agent.agentId,
    });
  } finally {
    trace("runner→sdk", "agent.dispose", { agentId: agent.agentId });
    await agent[Symbol.asyncDispose]().catch(() => undefined);
  }
}

main()
  .then(() => process.exit(0))
  .catch((error) => {
    const startup = error instanceof CursorAgentError;
    emit({ type: "error", text: message(error), startup });
    emit({ type: "done", status: "error" });
    process.exit(1);
  });
