# Cursor Constructor Desktop

PySide6-оболочка, где **весь процесс идёт через Cursor Cloud Agents** (REST `/v1`):
документ → план → уточняющие вопросы → реализация → сохранение workflow → повторный запуск.
GitHub/git **не нужны**. План хранится локально в `data/workflows/*.json`.

## Запуск

```powershell
cd desktop
python -m pip install -r requirements.txt
copy .env.example .env
# впишите CURSOR_API_KEY
python main.py
```

> Нужен 64-bit Python: PySide6 не имеет колёс под 32-bit.

## Конфиг

```env
CURSOR_API_KEY=crsr_...
CURSOR_MODEL=composer
```

## Как это работает

1. **Конструктор** — загрузите файлы (текст, csv/json/xml, pdf/docx, картинки
   png/jpg/gif/webp) drag-and-drop или кнопкой; можно добавить заметки.
2. **Спланировать** — текст уходит в prompt, картинки — в `prompt.images`
   (до 5 шт.); cloud-агент строит JSON-план.
3. **Уточнения** — ответы на открытые вопросы уходят follow-up run’ом, план обновляется.
4. **Реализовать** — тот же cloud-режим без GitHub: агент выполняет план и проверки.
5. **Сохранить** — план + документ + agent/run id пишутся в `data/workflows/*.json`.
6. **Мои workflow** — список сохранённого; «Открыть» / «Запустить снова».

## Границы фаз

| Фаза | Runtime | Репозиторий |
|------|---------|-------------|
| План + Q&A | cloud | не нужен |
| Реализация | cloud | не нужен |
| Повторный запуск | тот же exec-агент | не нужен |

## Структура

```
app/
  api/rest_client.py     # Cursor Cloud Agents REST + SSE-стрим
  workflow/
    models.py            # WorkflowRecord / WorkflowPlan / …
    prompts.py           # промпты фаз + парсинг JSON-плана
    document.py          # чтение txt/md/pdf/docx
    storage.py           # JSON-персистентность в data/workflows
    service.py           # фазовая оркестрация + Qt-воркеры
  ui/pages/
    workflow_page.py     # конструктор
    saved_page.py        # список сохранённых workflow
```

Cloud-агенты, созданные через API, в Cursor Web могут быть скрыты: **Filter → Source → SDK**.
