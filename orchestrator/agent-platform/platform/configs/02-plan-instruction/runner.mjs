// Конфигурация 2: полный доступ + инструкция из режима plan.
//
// Отличие от конфигурации 1 — поле mode запроса:
//   mode = "plan"  — ход планирования: agent.send(..., { mode: "plan" }). Агент только изучает
//                    окружение и оформляет план инструментом createPlan. В конце хода раннер
//                    отдаёт платформе {"type":"plan","markdown":…}: план из createPlan, а если
//                    агент его не вызвал — финальный ответ. Платформа сохраняет план как .plan.md
//                    и делает его инструкцией агента.
//   mode = "agent" — обычный ход: промпт с планом (и историей прошлого прогона) собирает платформа.
//
// Алгоритм одного запуска:
//   1. Платформа пишет в stdin одну JSON-строку запроса: mode, prompt, attachments, cwd (папка сессии),
//      model, resumeAgentId (для продолжения диалога), title, storeDir.
//      Вложения уже лежат в cwd/attachments: фотографии уходят в SDK картинками сообщения,
//      а пути всех вложений дописываются к тексту — файлы агент открывает своими инструментами.
//   2. Создаём локального агента Cursor SDK без ограничений встроенных инструментов:
//      shell, read, edit, delete, grep, glob, ls, semSearch, task, webSearch, webFetch и т.д.
//   3. Запускаем MCP-сервер mcp_server.py и отдаём агенту его инструменты (customTools) — все инструменты TurboTester (Outlook, 1С,
//      Excel, Office, TurboProject, пользователи, уведомления…).
//   4. Отправляем промпт как есть, без обёрток и правил (кроме списка вложений).
//   5. Транслируем поток SDK в stdout построчным JSON: agent, status, thinking,
//      assistant, tool_call, usage, done. Строка {"type":"cancel"} в stdin отменяет запуск.
//   6. Для панели «Взаимодействие» каждое обращение к SDK и каждое событие его потока
//      дублируются строкой trace. Контекст платформа собирает сама по шагам потока;
//      в tool_call для этого передаётся полный размер аргументов и результата.

import { Agent, CursorAgentError, JsonlLocalAgentStore } from "@cursor/sdk";
import { spawn } from "node:child_process";
import { mkdirSync, readFileSync, writeFileSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";
import * as readline from "node:readline";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const DEFAULT_MODEL = "grok-4.7";

// model_params из config.json: у grok-4.7 это reasoning_effort, fast и context.
function modelSelection(request) {
  const params = Array.isArray(request.modelParams)
    ? request.modelParams.flatMap((item) =>
        item && typeof item.id === "string" && typeof item.value === "string"
          ? [{ id: item.id, value: item.value }]
          : [],
      )
    : [];
  const id = request.model || DEFAULT_MODEL;
  return params.length ? { id, params } : { id };
}
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

function describeOptions(options, request, server) {
  return {
    apiKey: "***",
    model: options.model,
    name: options.name,
    local: {
      cwd: options.local.cwd,
      settingSources: options.local.settingSources,
      store: request.storeDir ? `JsonlLocalAgentStore(${request.storeDir})` : "по умолчанию",
      customTools: Object.keys(options.local.customTools),
    },
    constructorMcp: {
      command: server.command,
      args: server.args,
      cwd: server.cwd,
      env: "окружение платформы + PYTHONIOENCODING, PYTHONUTF8, TURBOTESTER_SESSION_DIR",
    },
  };
}

function message(error) {
  return error instanceof Error ? error.message : String(error ?? "Неизвестная ошибка");
}

// createPlan присылает план markdown-строкой и, у новых моделей, отдельно название и обзор.
function planFromArgs(args) {
  if (!args || typeof args !== "object") return null;
  const plan = typeof args.plan === "string" ? args.plan.trim() : "";
  if (!plan) return null;
  const name = typeof args.name === "string" ? args.name.trim() : "";
  const overview = typeof args.overview === "string" ? args.overview.trim() : "";
  const head = [name && !plan.startsWith("#") ? `# ${name}` : "", overview && !plan.includes(overview) ? overview : ""];
  return { markdown: [...head.filter(Boolean), plan].join("\n\n"), name };
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

// Шаги подагента приходят только дельтами его вызова task, в run.stream их нет.
// parent — call_id этого task: по нему платформа показывает ход подагента отдельно.
function relaySubagent({ update }) {
  if (update?.type !== "tool-call-delta" || !update.taskUpdate) return;
  const parent = update.callId;
  const step = update.taskUpdate;
  if (step.type === "text-delta" && step.text) {
    emit({ type: "assistant", parent, text: step.text });
  } else if (step.type === "thinking-delta" && step.text) {
    emit({ type: "thinking", parent, text: step.text });
  } else if (step.type === "tool-call-started" || step.type === "tool-call-completed") {
    const call = step.toolCall ?? {};
    const done = step.type === "tool-call-completed";
    trace("sdk→runner", `подагент: ${step.type}`, { parent, callId: step.callId, toolCall: call });
    emit({
      type: "tool_call",
      parent,
      callId: step.callId,
      name: call.type,
      status: done ? (call.result?.status === "error" ? "error" : "completed") : "running",
      argsChars: asText(call.args).length,
      resultChars: done ? asText(call.result).length : 0,
      args: preview(call.args),
      result: done ? preview(call.result) : undefined,
    });
  }
}

function stringEnv(source) {
  const env = {};
  for (const [key, value] of Object.entries(source)) {
    if (typeof value === "string") env[key] = value;
  }
  return env;
}

function constructorServer(request) {
  return {
    command: request.python || "python",
    args: [join(HERE, "mcp_server.py")],
    cwd: request.cwd,
    env: stringEnv({
      ...process.env,
      PYTHONIOENCODING: "utf-8",
      PYTHONUTF8: "1",
      TURBOTESTER_SESSION_DIR: request.cwd,
    }),
  };
}

// С настройками проекта (без них SDK не читает хук разрешений) модель не видит инструменты
// inline-MCP-серверов из mcpServers. Поэтому раннер сам запускает mcp_server.py и отдаёт его
// инструменты агенту как customTools: в потоке они выглядят так же — tool_call "mcp" с toolName.
async function connectConstructorMcp(server) {
  const child = spawn(server.command, server.args, { cwd: server.cwd, env: server.env, windowsHide: true });
  const pending = new Map();
  let lastId = 0;
  let failure = null;
  const fail = (error) => {
    failure ??= error;
    for (const waiter of pending.values()) waiter.reject(failure);
    pending.clear();
  };
  child.on("error", fail);
  child.on("exit", (code) => fail(new Error(`MCP-сервер TurboTester завершился (код ${code})`)));
  child.stdin.on("error", () => undefined);
  child.stderr.setEncoding("utf8");
  child.stderr.on("data", (text) => trace("mcp→runner", "stderr", undefined, { text }));
  readline.createInterface({ input: child.stdout, crlfDelay: Infinity }).on("line", (line) => {
    let reply;
    try {
      reply = JSON.parse(line);
    } catch {
      return;
    }
    const waiter = pending.get(reply.id);
    if (!waiter) return;
    pending.delete(reply.id);
    if (reply.error) waiter.reject(new Error(reply.error.message || "Ошибка MCP-сервера"));
    else waiter.resolve(reply.result ?? {});
  });
  const send = (payload) => child.stdin.write(`${JSON.stringify({ jsonrpc: "2.0", ...payload })}\n`);
  const call = (method, params) =>
    new Promise((resolve, reject) => {
      if (failure) return reject(failure);
      const id = ++lastId;
      pending.set(id, { resolve, reject });
      send({ id, method, params });
    });
  const close = () => {
    child.stdin.end();
    child.kill();
  };

  try {
    await call("initialize", {
      protocolVersion: "2024-11-05",
      capabilities: {},
      clientInfo: { name: "turbotester-runner", version: "1.0.0" },
    });
    send({ method: "notifications/initialized" });
    const { tools = [] } = await call("tools/list", {});
    const customTools = Object.fromEntries(
      tools.map((tool) => [
        tool.name,
        {
          description: tool.description,
          inputSchema: tool.inputSchema,
          execute: async (args) => {
            try {
              const result = await call("tools/call", { name: tool.name, arguments: args ?? {} });
              return { content: result.content ?? [], isError: Boolean(result.isError) };
            } catch (error) {
              return { content: [{ type: "text", text: message(error) }], isError: true };
            }
          },
        },
      ]),
    );
    return { tools: customTools, close };
  } catch (error) {
    close();
    throw error;
  }
}

// Разрешения как в Cursor: хук preToolUse (approval_hook.py) спрашивает платформу перед каждым
// инструментом, а она — человека, если действие что-то меняет. SDK читает хуки из .cursor/hooks.json
// рабочей папки, поэтому раннер кладёт его туда и включает настройки проекта.
const HOOK_TIMEOUT_S = 32 * 60;

function installApprovalHook(request) {
  const api = (process.env.TURBOTESTER_API_URL || "").trim();
  const sessionId = String(request.sessionId || process.env.TURBOTESTER_SESSION_ID || "").trim();
  if (!api || !sessionId || !request.cwd) return null;
  // Корень проекта SDK ищет через `git rev-parse --show-toplevel`: без потолка им станет
  // репозиторий, внутри которого лежат рабочие папки, и хук из рабочей папки не загрузится.
  process.env.GIT_CEILING_DIRECTORIES = dirname(request.cwd);
  const quote = (value) => `"${String(value).replace(/"/g, '\\"')}"`;
  // SDK читает hooks.json как JSON с комментариями: «//» внутри строки обрезает хук, поэтому адрес без схемы.
  const host = api.replace(/^[a-z]+:\/\//i, "").replace(/\/+$/, "");
  const command = [request.python || "python", join(HERE, "approval_hook.py"), host, sessionId].map(quote).join(" ");
  const folder = join(request.cwd, ".cursor");
  mkdirSync(folder, { recursive: true });
  const hooks = { version: 1, hooks: { preToolUse: [{ command, timeout: HOOK_TIMEOUT_S, failClosed: true }] } };
  writeFileSync(join(folder, "hooks.json"), JSON.stringify(hooks, null, 2), "utf8");
  return hooks;
}

const ANSWER_WAIT_S = 50;

async function sessionQuestions(request, path) {
  const api = (process.env.TURBOTESTER_API_URL || "").trim().replace(/\/+$/, "");
  const sessionId = String(request.sessionId || process.env.TURBOTESTER_SESSION_ID || "").trim();
  if (!api || !sessionId) return null;
  const url = `${api}/api/v1/platform/sessions/${encodeURIComponent(sessionId)}/questions${path}`;
  const response = await fetch(url, { signal: AbortSignal.timeout((ANSWER_WAIT_S + 15) * 1000) });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

// Ход закончился, а вопрос человеку открыт (вызов ask_user оборвался или модель не дождалась):
// сессию не завершаем — ждём ответ и отдаём его агенту следующим сообщением.
async function answerToOpenQuestion(request, isCancelled) {
  const open = await sessionQuestions(request, "")
    .then((body) => body?.question)
    .catch(() => null);
  if (!open) return null;
  trace("platform→runner", "открытый вопрос после хода", open);
  emit({ type: "status", text: "Жду ответа человека на вопрос агента" });
  while (!isCancelled()) {
    let result;
    try {
      result = await sessionQuestions(request, `/${encodeURIComponent(open.id)}?wait=${ANSWER_WAIT_S}`);
    } catch {
      await new Promise((resolve) => setTimeout(resolve, 5000));
      continue;
    }
    if (!result || result.status === "cancelled") return null;
    if (result.status === "waiting") continue;
    const topic = open.title || open.questions?.[0]?.prompt || "";
    return `Ответ человека на твой вопрос «${topic}»:\n${JSON.stringify(result, null, 2)}`;
  }
  return null;
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
  const hooks = installApprovalHook(request);
  if (hooks) trace("runner→sdk", "хук разрешений", hooks);

  const server = constructorServer(request);
  let mcp = { tools: {}, close: () => undefined };
  try {
    mcp = await connectConstructorMcp(server);
    trace("mcp→runner", "инструменты", { tools: Object.keys(mcp.tools) });
  } catch (error) {
    trace("mcp→runner", "ошибка", { message: message(error) });
    emit({ type: "status", text: `MCP-сервер TurboTester недоступен: ${message(error)}` });
  }

  const options = {
    apiKey,
    model: modelSelection(request),
    name: request.title || undefined,
    local: {
      cwd: request.cwd,
      settingSources: hooks ? ["project"] : [],
      customTools: mcp.tools,
      // Хранилище SQLite по умолчанию на этой машине не открывает свою базу в конце хода
      // («unable to open database file»): ход не завершается, и SDK повторяет его по таймауту.
      ...(request.storeDir ? { store: new JsonlLocalAgentStore(request.storeDir) } : {}),
    },
  };

  emit({ type: "status", text: request.resumeAgentId ? "Продолжаю диалог с агентом…" : "Создаю агента Cursor SDK…" });
  const described = describeOptions(options, request, server);
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

  const planning = request.mode === "plan";
  try {
    emit({ type: "agent", agentId: agent.agentId });
    const sendOptions = { mode: planning ? "plan" : "agent", local: { force: true }, onDelta: relaySubagent };
    trace("runner→sdk", "agent.send", { ...shown, options: sendOptions }, { text: shown.prompt });
    let run = await agent.send(sdkMessage, sendOptions);
    trace("sdk→runner", "run", { runId: run.id, requestId: run.requestId, status: run.status });
    emit({ type: "status", text: planning ? "Агент составляет план" : "Агент работает", runId: run.id });

    let cancelled = false;
    let plan = null;
    let answer = "";
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

    let result;
    for (;;) {
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
            if (block.type === "text" && block.text) {
              answer += block.text;
              emit({ type: "assistant", text: block.text });
            }
          }
        } else if (event.type === "thinking" && event.text) {
          emit({ type: "thinking", text: event.text });
        } else if (event.type === "tool_call") {
          const done = event.status !== "running";
          if (event.name === "createPlan") plan = planFromArgs(event.args) ?? plan;
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
      result = await run.wait();
      trace("sdk→runner", "результат хода", {
        status: result.status,
        durationMs: result.durationMs,
        model: result.model,
        usage: result.usage,
        error: result.error,
        result: result.result,
      });
      if (cancelled) break;
      const reply = await answerToOpenQuestion(request, () => cancelled);
      if (!reply) break;
      trace("runner→sdk", "agent.send", { prompt: reply, options: sendOptions }, { text: reply });
      run = await agent.send(reply, sendOptions);
      trace("sdk→runner", "run", { runId: run.id, requestId: run.requestId, status: run.status });
      emit({ type: "status", text: "Ответ человека передан агенту", runId: run.id });
    }
    if (planning && !cancelled && result.status === "finished") {
      const fallback = (typeof result.result === "string" && result.result.trim()) || answer.trim();
      const chosen = plan ?? (fallback ? { markdown: fallback, name: "" } : null);
      if (chosen) emit({ type: "plan", markdown: chosen.markdown, name: chosen.name, source: plan ? "createPlan" : "answer" });
    }
    emit({
      type: "done",
      status: cancelled ? "cancelled" : result.status,
      result: typeof result.result === "string" ? result.result : undefined,
      agentId: agent.agentId,
    });
  } finally {
    trace("runner→sdk", "agent.dispose", { agentId: agent.agentId });
    await agent[Symbol.asyncDispose]().catch(() => undefined);
    mcp.close();
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
