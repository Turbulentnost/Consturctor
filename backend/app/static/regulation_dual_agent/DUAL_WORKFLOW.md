# Двухагентный воркфлоу создания регламента

## Этапы pipeline

```
upload → extract → material_review → select → interview (collect → dual_rounds) → assemble → done
```

| Этап | Кто работает | Действие |
|------|--------------|----------|
| extract | Исследователь | Извлечь процессы из materials |
| **material_review** | Исследователь | Отчёт полноты по каждому процессу → `PROCESS_COMPLETENESS.md` |
| select | UI | Пользователь отмечает процессы |
| collect | Оба | Deterministic queue + research prefetch |
| dual_rounds | Оба | Research заполняет из документа; Interviewer спрашивает human |
| assemble | Interviewer | Полный document JSON → DOCX в загрузки |
| spawn | Backend | Готовые процессы → агенты в «Мои агенты» |

## Два агента

### 1. Research (`agentRole: research`)
- Читает materials, не пишет в чат пользователю.  
- `prefetchOnly` / `researchOnly` apply на backend.  
- Пополняет `researchFacts`, `researchQueue`.

### 2. Interviewer (`agentRole: interview`)
- Единственный, кто пишет в чат.  
- Задаёт вопросы, принимает ответы.  
- Финализирует document.

## Непрерывная генерация вопросов
- Backend держит `questionQueue` (deterministic + round).  
- Research prefetch работает **параллельно**, пока пользователь отвечает.  
- Interviewer prefetch генерирует `roundQuestions` пакетами.  
- UI вызывает `advance-question` без ожидания LLM.

## Параллельное создание агентов
После каждого раунда backend проверяет `processes_ready_for_agent()`:
- Готовые → `spawn_regulation_process_agents()` → Workflow `phase=done`, published.  
- Неготовые → остаются в очереди вопросов.

## Финал
1. `_finalize_document` → DOCX  
2. Сообщение в чат со списком `spawnedAgents`  
3. Пользователь видит новых агентов в «Мои агенты»

## Файлы в workspace SDK
- `AGENTS.md` — активная роль (research или interview rules)  
- `REGULATION_BRIEF.md` — этот бриф  
- `RESEARCHER_AGENT.md`, `INTERVIEWER_AGENT.md`  
- `PROCESS_COMPLETENESS.md` — после material_review  
- `interview.json`, `materials/*`
