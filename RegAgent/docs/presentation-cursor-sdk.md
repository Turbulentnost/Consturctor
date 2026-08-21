# RegAgent — работа Cursor SDK

---

## Слайд 1. Тitle

**RegAgent + Cursor SDK**  
Desktop-агент: LLM, инструменты, 1С, Outlook

---

## Слайд 2. Cursor SDK

- Python-библиотека `cursor-sdk`
- Локальный агент: модель + tools
- Встроенные: read, grep, shell, webSearch
- Custom tools — ваши интеграции

---

## Слайд 3. Архитектура

```
UI (PySide6) → AgentWorker (QThread) → CardAgentSession
    → cursor_sdk.Agent → constructor_integrations → ToolRegistry
```

---

## Слайд 4. Жизненный цикл

1. open_card / resume agent_id  
2. system prompt = rules_prompt  
3. send(message) → run.messages() stream  
4. tool_call → invoke_tool  
5. run.wait() → ответ  

---

## Слайд 5. constructor_integrations

```json
{"tool": "onec.docflow_tasks", "arguments": {"limit": 400}}
```

- Единая CustomTool для 1C/Outlook  
- HITL для write-операций  

---

## Слайд 6. Инструменты

| Tool | Режим |
|------|-------|
| outlook.* | COM |
| onec.docflow_tasks | OData |
| onec.search_* | COM |

---

## Слайд 7. OData поручения

- `Document_ТД_Поручения`  
- urgency_tier + pastel colors  
- Excel export scripts  

---

## Слайд 8. Итог

RegAgent = регламент + SDK + интеграции.  
Новый tool → registry.register → доступен агенту.
