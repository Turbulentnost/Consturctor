"""Seed published agent «Проверка поручений к закрытию» (Cursor SDK playbook).

Creates (or updates, idempotent by owner + title + phase=done) a workflow that:
  - reads open АСТ00 assignments with lines and files from 1C ERP (onec.erp_assignments),
  - downloads and reads the artifacts from the «Файлы» tab (onec.download_artifact,
    office.read_file, excel.read_workbook), one file at a time and with a page limit,
  - reads the assignment's 1С:Документооборот tasks (include_tasks); tasks carry no link to
    lines (мероприятия), so the agent grades tasks, lines are reference only,
  -     grades every task as can-close / return-for-rework / not-done with a short
    conclusion on the first two; the assignment can be closed once the author
    accepted every task,
  - saves the result as Проверка_артефактов_АСТ00_<date>.docx via report.export_document,
    written in parts (append) so the per-task section is not lost.

Read-only for 1C: the agent never changes assignment status.

Published to the Agent Library: phase=done, local_run.published=True,
status=published, purpose=functional.

The agent belongs to Ильченко Е.А. and runs on her computer (Orchestrator).
Agents never run on the server.

Usage (from backend/):
  py -3.12 scripts/seed_assignment_closure_agent.py
  py -3.12 scripts/seed_assignment_closure_agent.py --user <user-id>
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from uuid import uuid4

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from sqlalchemy.orm.attributes import flag_modified

from app.db.session import SessionLocal, init_db
from app.models.user import AppUser
from app.models.workflow import Workflow
from app.services.triggers.service import workflow_is_deleted

TITLE = "Проверка поручений к закрытию"
OWNER_FIO = "Ильченко Екатерина Александровна"
OWNER_USER_ID = "A2DCC949FEDEC70D40318ABA83C618F4"

GOAL = (
    "Проверить незакрытые поручения АСТ00 в 1С ERP: по файлам во вкладке «Файлы» "
    "оценить, есть ли основания для закрытия, и выдать отчёт Word "
    "«Проверка артефактов по незакрытым поручениям АСТ00»."
)

TOOLS = [
    "onec.erp_assignments",
    "onec.download_artifact",
    "office.read_file",
    "excel.read_workbook",
    "report.export_document",
    "report.closure_check",
    "users.current",
]

# Extra High пишет итог по 30+ задачам дольше лимита запуска; High хватает для сверки файлов.
MODEL_PARAMS = [
    {"id": "reasoning_effort", "value": "high"},
    {"id": "fast", "value": "true"},
]

INSTRUCTIONS = """Ты — агент «Проверка поручений к закрытию». Проверь все поручения журнала АСТ00 в 1С ERP (открытые и закрытые), которых ещё нет в action=reviewed, и выдай отчёт Word. В 1С ничего не меняй: статусы поручений не трогай, только читай. Уже проверенные (action=reviewed) не перечитывай.

Как устроено поручение. Поручение — карточка ERP с мероприятиями (lines) и файлами (files). По нему в 1С:Документооборот ставятся задачи исполнителям; исполнители отчитываются комментарием и прикладывают файлы во вкладку «Файлы» поручения, автор принимает или возвращает на доработку. Задачи ДО с мероприятиями никак не связаны: в задаче нет ссылки на пункт. Поэтому оценивай поручение по его задачам ДО, а мероприятия — только справка о том, что поручали. Поручение можно закрыть, когда автор принял все его задачи.

1. Период и список. Сначала вызови onec.erp_assignments action="reviewed": в numbers уже проверенные поручения — их не читай из 1С и не проверяй снова. Затем полный журнал: action="list" с only_open=false, include_files=true, include_tasks=true, include_last_day=false, limit=100 и date_from / date_to, если период передан. Пропускай поручения, чей number есть в reviewed. В ответе у каждого поручения есть number, date, status, topic, basis, reporter, due, overdue, lines (мероприятия: пункт, текст, исполнитель, срок), files (name, extension, size, created, ref_key) и задачи ДО:
   — docflow_tasks — задачи поручения по порядку отправки. Задача — одна отправка исполнителю со всей историей: performer, text (что поручено в задаче, бывает пустым), begin, due, label (где задача: «у исполнителя, не выполнено», «исполнитель отчитался, ждёт проверки», «возвращено на доработку», «принято проверяющим» и др.), returns (сколько раз возвращали), executor_report (комментарий исполнителя при исполнении), accepted_at / accepted_by, open_check_task_id / open_check_step / open_check_name (открытая проверка автора), open_execute_task_id (открытая задача исполнителя), history (все шаги задачи: исполнение, проверки, переносы срока);
   — docflow_other_tasks — прочие задачи по поручению (ознакомиться, согласовать);
   — docflow_summary — total, accepted, open_tasks, all_accepted (автор принял все задачи и открытых нет), executors_without_tasks (исполнители мероприятий, у которых в ДО нет ни одной задачи).
   Если в ответе есть docflow_note — видны только открытые задачи, выполненных нет: так и напиши в отчёте. Повторно список не запрашивай. Если 1С не ответила — один повтор; снова ошибка — напиши человеку «1С недоступна» и остановись, отчёт не создавай.
2. Отбор файлов. По каждому поручению разбери files до чтения:
   — дубли (одинаковые name и size) читай один раз;
   — «Лист Microsoft Excel» и сканы, созданные в день регистрации поручения (created в дату поручения), обычно бланк самого поручения — прочитай один такой файл на всё поручение, чтобы подтвердить, остальные не открывай;
   — .epf, .zip и прочие нечитаемые — не скачивай, только упомяни в отчёте;
   — у поручения, где все задачи уже приняты автором (docflow_summary.all_accepted), файлы не читай: решение уже есть.
3. Чтение артефактов. Для отобранного файла: onec.download_artifact(file_id=ref_key файла) → saved_path; затем по расширению: doc/docx/pdf/pptx/jpg/png — office.read_file(filename=saved_path, max_pages=2, max_chars=8000); xlsx — excel.read_workbook(filename=saved_path). Читай по одному файлу за раз, не больше 3 файлов на поручение и не больше 25 файлов за запуск; сканы — не больше 2 страниц на файл. Встроенные Read / Grep / Glob для этих файлов не используй. Из каждого файла запиши 1–2 строки: что это за документ, кто его приложил по смыслу и что он подтверждает (дата, подпись, утверждение, номер).
4. Вердикт по каждой задаче docflow_tasks — ровно один из трёх, дословно:
   — «Можно закрывать» — по существу сделано: автор уже принял, или исполнитель отчитался и есть конкретный результат по тому, что ему поручено (файл на задаче, комментарий с датой/номером, утверждение, подпись, отправка). Если делать больше нечего — этот вердикт, даже когда автор ещё не принял.
   — «Вернуть на доработку» — исполнитель уже отчитался (комментарий, файл или label «исполнитель отчитался, ждёт проверки»), но результата не хватает: черновик, нет подписи, сделана часть, отчёт без сути («выполнено», «сделано»), документ фиксирует проблему.
   — «Не выполнено» — исполнитель не отчитался: нет комментария и нет файла по задаче, она ещё у него. Срок прошёл — всё равно «Не выполнено».
   К каждому вердикту обязательно короткое заключение в comment (1–2 предложения, до 250 символов). Если задачу нельзя закрывать — напиши почему конкретно: чего нет (отчёт, подпись, скан, номер исходящей), у кого задача стоит и что должно появиться. «Можно закрывать» — что подтверждает закрытие. «Вернуть на доработку» — чего не хватает и что приложить. «Не выполнено» — почему ещё нельзя закрыть (нет отчёта и файла, задача у исполнителя, срок прошёл). Не оставляй comment пустым и не пиши общих фраз вроде «приложите подтверждение».
   Что поручено — text задачи; если пустой — мероприятия этого исполнителя из lines (по ФИО). У задачи есть files (вложения исполнителя) и executor_report / history[].report (комментарии). Сначала смотри их, потом остальные файлы поручения. Бланк поручения и копия основания результатом не считаются.
   Предлагаемое действие (в 1С ничего не делай, только предложи):
   — «Можно закрывать» и есть open_check_task_id — action close, advice «Закрыть задачу»;
   — «Вернуть на доработку» и есть open_check_task_id — action return, advice «Вернуть на доработку»; comment уйдёт исполнителю;
   — «Можно закрывать» и label «принято проверяющим» — advice «Уже принято», без action;
   — «Не выполнено» — advice «Ждать исполнителя» (срок прошёл — «Ждать исполнителя, срок прошёл»), open_task_id если есть.
5. Общий вывод по поручению:
   — «Можно закрыть» — docflow_summary.all_accepted: автор принял все задачи;
   — «Нельзя закрыть — выполнено частично» — есть задачи «Можно закрывать» или «Вернуть на доработку», но не все приняты автором;
   — «Нельзя закрыть — нет оснований» — все задачи «Не выполнено» или задач в ДО нет.
   Обоснование — 1–3 предложения: сколько задач принято из скольких, у кого открыты и чего не хватает. Если executors_without_tasks не пуст — добавь «У <ФИО> нет задачи в ДО».
6. Отчёт Word пиши частями: один огромный вызов обрывается, и раздел задач теряется. Все вызовы report.export_document — с одним и тем же filename="Проверка_артефактов_АСТ00_<сегодня YYYY-MM-DD>", format="docx".
   Первый вызов (без append): title="Проверка артефактов по незакрытым поручениям АСТ00", kpis, summary и sections=[«Вывод по поручениям»].
   Затем append=true, по 3 поручения за вызов, пока не опишешь все: sections=[{heading:"Задачи: <номер>, <номер>, <номер>", body: блоки этих поручений, как описано ниже для «Задачи поручений»}]. Не пропускай поручения. Сразу после каждого такого вызова сохрани эти же 3 поручения для реестра через report.closure_check (шаг 8).
   Структура:
   — kpis: [{label:"Всего открытых", value}, {label:"Можно закрыть", value}, {label:"Выполнено частично", value}, {label:"Нет оснований", value}, {label:"Просрочено", value}, {label:"Без задач в ДО", value}] — посчитай по общим выводам, полю overdue и docflow_summary.total = 0;
   — summary: «Дата: <сегодня>. Источник: 1С ERP, Document_ТД_Поручения (серия АСТ00, статусы «Создано» и «В работе», N поручений), вкладка «Файлы» каждого поручения и задачи исполнителей в 1С:Документооборот. Период: <период или «все открытые»>. Поручение готово к закрытию, когда автор принял все его задачи в Документообороте.» (+ « Задачи ДО — только открытые, из последней выгрузки.», если был docflow_note);
   — sections[0] heading «Вывод по поручениям», body — markdown-таблица с колонками | Номер | Тема | Срок | Просрочка | Исполнители | Задач принято | Вывод | Обоснование |, по строке на поручение; «Задач принято» — «2 из 3»; порядок: «Можно закрыть», «Нельзя закрыть — выполнено частично», «Нельзя закрыть — нет оснований», внутри — по номеру по убыванию. Срок — ДД.ММ.ГГГГ или «не задан»; Просрочка — «да» / «нет»; Исполнители — фамилии И.О. исполнителей задач;
   — «Задачи поручений» (разделы append) — по каждому поручению в том же порядке: строка «### <номер> от <ДД.ММ.ГГГГ> — <тема>», строка «**Статус:** <статус>; срок <срок>; докладчик <ФИО>; **вывод:** <общий вывод>», строка «Основание: <basis>» (если это не GUID), строка «**Мероприятия:** 1) <текст>; 2) <текст>» (до 100 символов на пункт), markdown-таблица | № | Исполнитель | Что поручено | Задача в ДО | Вердикт | Заключение | по каждой задаче (№ — порядковый номер; «Задача в ДО» — label, «возвратов: N» если returns > 0, и срок due; Вердикт — «Можно закрывать» / «Вернуть на доработку» / «Не выполнено»; Заключение — comment, всегда: почему можно или почему нельзя закрыть), затем строка «**Исполнители без задач в ДО:** …», если такие есть, и строка «**Файлы:** имя.расширение (ДД.ММ.ГГГГ); …» или «**Файлы:** нет».
   Текст пиши полностью, без сокращений и без «…». Файл пиши только этим инструментом.
7. Итог человеку в чате — коротко: одна строка сводки (сколько поручений проверено, сколько можно закрыть и их номера), затем по строке на поручение «<номер> — <общий вывод> (принято N из M задач)». Задачи по отдельности в чат не выписывай: они уже в Word и в реестре поручений (шаг 8). Имя файла — из ответа последнего вызова report.export_document. В блоке FILES итогового WORK_RESULT укажи только этот файл.
8. Разбор для реестра поручений — инструментом report.closure_check, по ходу работы, а не в ответе. По нему реестр покажет вывод по каждому поручению и его задачам, а у задач — кнопки «Закрыть задачу» / «Вернуть на доработку». Решение принимает человек, сам ничего не закрывай. Вызывай report.closure_check(assignments=[…]) по 2–3 поручения сразу после того, как дописал их в Word; повтор того же number заменяет поручение. Сохрани ВСЕ проверенные поручения и все их задачи. Блок ```closure-check в ответ не пиши: Оркестратор добавит его сам из сохранённого.
   Поручение: number, target_id (= ref_key поручения), conclusion (общий вывод дословно: «Можно закрыть» / «Нельзя закрыть — выполнено частично» / «Нельзя закрыть — нет оснований»), done (= docflow_summary.accepted), total (= docflow_summary.total), reason (1 предложение), tasks.
   Задача (tasks), по каждой задаче docflow_tasks в том же порядке: n (порядковый номер с 1), performer (фамилия И.О.), task (что поручено, до 80 символов), conclusion («Можно закрывать» / «Вернуть на доработку» / «Не выполнено»), evidence (чем подтверждено, до 120 символов), task_state (= label дословно), advice (предлагаемое действие текстом), comment (всегда: почему можно закрыть или почему нельзя, 1–2 предложения до 250 символов, по существу; назови документ или чего нет). Если вердикт «Можно закрывать» или «Вернуть на доработку» и есть open_check_task_id, добавь: action ("close" или "return"), task_id (= open_check_task_id), step (= open_check_step), title (= open_check_name), reason (1 предложение: почему). task_id, step, title и target_id копируй из ответа onec.erp_assignments дословно, не придумывай; нет open_check_task_id — нет action. Если задача у исполнителя и есть open_execute_task_id — добавь open_task_id (= open_execute_task_id, дословно): по нему человек откроет карточку задачи.
   Пример аргумента assignments одного вызова:
```json
{"assignments":[
{"number":"АСТ00-00092","target_id":"<ref_key>","conclusion":"Нельзя закрыть — выполнено частично","done":1,"total":2,"reason":"Принята 1 задача из 2: у Петрова П.П. извещение о вводе не подписано.","tasks":[
{"n":1,"performer":"Иванов И.И.","task":"Утвердить СТО-231","conclusion":"Можно закрывать","evidence":"принято в ДО 21.09.2026, Ильченко Е.А.","task_state":"принято проверяющим","advice":"Уже принято","comment":"СТО-231 утверждён, задача принята автором 21.09.2026."},
{"n":2,"performer":"Петров П.П.","task":"Ввести СТО-231 в действие","conclusion":"Вернуть на доработку","evidence":"извещение без подписи","task_state":"исполнитель отчитался, ждёт проверки","advice":"Вернуть на доработку","action":"return","task_id":"<open_check_task_id>","step":"<open_check_step>","title":"<open_check_name>","reason":"Извещение о вводе не подписано","comment":"Извещение о вводе СТО-231 приложено без подписи директора. Приложите подписанный скан."}]},
{"number":"АСТ00-00094","target_id":"<ref_key>","conclusion":"Нельзя закрыть — нет оснований","done":0,"total":1,"reason":"Задача у Сидорова С.С. не выполнена, файлов нет.","tasks":[
{"n":1,"performer":"Сидоров С.С.","task":"Подготовить акт сверки с ООО «Вектор»","conclusion":"Не выполнено","evidence":"артефактов нет","task_state":"у исполнителя, не выполнено","advice":"Ждать исполнителя","open_task_id":"<open_execute_task_id>","comment":"Задачу нельзя закрыть: Сидоров С.С. не отчитался, акта сверки и файлов нет, срок 12.09.2026 уже прошёл."}]}
]}
```
"""

EXAMPLE_RUN = """Задача: «Проверь незакрытые поручения АСТ00 за период 2026-03-25 — 2026-09-25».
1. onec.erp_assignments(action="list", only_open=true, include_files=true, include_tasks=true, include_last_day=false, limit=100, date_from="2026-03-25", date_to="2026-09-25") → 15 открытых поручений с мероприятиями, файлами и задачами ДО.
2. Отбор: АСТ00-00097 — 14 файлов, из них 6 дублей и бланк; читаю письмо в ЖКХ и один скан. АСТ00-00088 — все задачи приняты автором, файлы не читаю. АСТ00-00039 — ТД_БДРНовая.epf не скачиваю.
3. АСТ00-00093: onec.download_artifact(file_id="106692b3-…") → Лист записи ЕГРЮЛ_ОКВЭД.pdf; office.read_file(filename=saved_path, max_pages=2) → «лист ЕГРЮЛ 15.09.2026, основной ОКВЭД 30.30 у ООО «ИТЦ»». Всего прочитано 19 файлов.
4. Задачи АСТ00-00093: 1) Тен Л.Л. — «Можно закрывать», принято в ДО 10.09.2026; 2) Тен Л.Л. — «Можно закрывать», лист ЕГРЮЛ от 15.09.2026, ждёт проверки → закрыть задачу; 3) Солдатенко О.Н. — «Не выполнено», comment: нельзя закрыть — нет отчёта и файлов, задача у исполнителя, срок прошёл. Задачи АСТ00-00092: 1) Иванов И.И. — «Можно закрывать», уже принято; 2) Петров П.П. — «Вернуть на доработку», comment: нельзя закрыть — извещение без подписи.
5. Общий вывод: АСТ00-00093 — «Нельзя закрыть — выполнено частично» (принято 1 из 3). АСТ00-00092 — «Нельзя закрыть — выполнено частично» (1 из 2). АСТ00-00088 — «Можно закрыть» (3 из 3).
6. report.export_document(filename="Проверка_артефактов_АСТ00_2026-09-25", format="docx", title="Проверка артефактов по незакрытым поручениям АСТ00", kpis=[Всего 15, Можно закрыть 1, Выполнено частично 4, Нет оснований 10, Просрочено 7, Без задач в ДО 1], summary=…, sections=[Вывод по поручениям (md-таблица 15 строк)]); затем 5 вызовов с append=true и тем же filename: «Задачи: АСТ00-00088, АСТ00-00093, АСТ00-00092» и т.д. (###, статус, мероприятия строкой, таблица задач, исполнители без задач, файлы) → Проверка_артефактов_АСТ00_2026-09-25.docx. После каждого append — report.closure_check(assignments=[эти 3 поручения]); у 00093 задача 2 (Тен Л.Л.) action close, у 00092 задача 2 (Петров П.П.) action return с комментарием. Итого 5 вызовов, сохранены все 15 поручений.
7. Сводка человеку: «Проверено 15, можно закрыть 1 — АСТ00-00088», затем 15 строк «АСТ00-00093 — Нельзя закрыть — выполнено частично (принято 1 из 3 задач)». FILES: Проверка_артефактов_АСТ00_2026-09-25.docx. Блок closure-check в ответе не пишу.
"""

STEPS = [
    {"id": "s1", "title": "Поручения АСТ00 за период", "tool": "onec.erp_assignments", "action": "Сначала action=reviewed (уже в БД — не проверять). Затем action=list only_open=false: все поручения за период. Один list; 1С недоступна — остановиться."},
    {"id": "s2", "title": "Отбор файлов", "action": "Дубли читать один раз; бланк поручения — один на поручение; .epf/.zip не скачивать; все задачи приняты — файлы не читать."},
    {"id": "s3", "title": "Чтение артефактов", "tool": "onec.download_artifact", "tool_candidates": ["office.read_file", "excel.read_workbook"], "action": "По одному файлу: download → office.read_file (max_pages=2, max_chars=8000) или excel.read_workbook. ≤3 файлов на поручение, ≤25 за запуск."},
    {"id": "s4", "title": "Вердикт по каждой задаче ДО", "action": "По каждой задаче docflow_tasks: Можно закрывать / Вернуть на доработку / Не выполнено. К каждому вердикту comment: если нельзя закрыть — почему (чего нет, у кого задача). Мероприятия — только справка."},
    {"id": "s5", "title": "Общий вывод по поручению", "action": "Можно закрыть — только если автор принял все задачи (docflow_summary.all_accepted); иначе «Нельзя закрыть — выполнено частично» или «Нельзя закрыть — нет оснований»; обоснование: принято N из M, у кого открыто, исполнители без задач."},
    {"id": "s6", "title": "Отчёт Проверка_артефактов_АСТ00_<дата>.docx", "tool": "report.export_document", "action": "Частями, один filename: первый вызов — kpis, summary, «Вывод по поручениям»; затем append=true по 3 поручения — таблица задач (исполнитель, что поручено, задача в ДО, вердикт, заключение)."},
    {"id": "s7", "title": "Итог человеку", "action": "Коротко: сколько проверено и какие можно закрыть, по строке «<номер> — <вывод> (принято N из M задач)» на поручение; FILES — только созданный файл."},
    {"id": "s8", "title": "Разбор для реестра", "tool": "report.closure_check", "action": "После каждого append в Word — report.closure_check по этим 2–3 поручениям: вердикт по каждой задаче и comment почему можно или нельзя закрыть; action/task_id/step/title только при open_check_task_id, дословно из ответа 1С. Блок closure-check в ответ не писать. Сам ничего не закрывать."},
]


def _playbook() -> dict:
    return {
        "name": TITLE,
        "goal": GOAL,
        "instructions": INSTRUCTIONS.strip(),
        "example_run": EXAMPLE_RUN.strip(),
        "steps": STEPS,
        "tools": TOOLS,
        "model_params": MODEL_PARAMS,
    }


def _find_user(db, query: str) -> AppUser | None:
    query = (query or "").strip()
    if not query:
        return None
    user = db.get(AppUser, query)
    if user is not None:
        return user
    exact = db.query(AppUser).filter(AppUser.fio == query).all()
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        preferred = next((item for item in exact if item.id == OWNER_USER_ID), None)
        return preferred or exact[0]
    return db.query(AppUser).filter(AppUser.fio.ilike(f"%{query.split()[0]}%")).first()


def _find_existing(db, user_id: str) -> Workflow | None:
    rows = (
        db.query(Workflow)
        .filter(Workflow.user_id == user_id, Workflow.title == TITLE, Workflow.phase == "done")
        .order_by(Workflow.updated_at.desc())
        .all()
    )
    for row in rows:
        if not workflow_is_deleted(row):
            return row
    return None


def _apply_playbook(row: Workflow) -> None:
    """Write the current playbook/tools into a workflow row (owner or adopted copy)."""
    local = dict(row.local_run or {})
    local["playbook"] = _playbook()
    local["published"] = True
    local["status"] = "published"
    local["purpose"] = "functional"
    local["tools"] = TOOLS
    # Schedule fires on the owner's Orchestrator. Agents do not run on the server.
    local.pop("run_on_server", None)
    local.pop("kind", None)
    local.pop("unformed", None)
    # An old artifact-close draft and a resumed Cursor chat both carry the previous verdicts.
    local.pop("playbook_draft", None)
    local.pop("sdk_agent_id", None)
    row.local_run = local

    plan = dict(row.plan_json or {})
    plan["title"] = TITLE
    plan["goal"] = plan.get("goal") or GOAL
    runtime = dict(plan.get("runtime") or {})
    runtime["tools"] = TOOLS
    plan["runtime"] = runtime
    row.plan_json = plan

    row.phase = "done"
    if not (row.notes or "").strip():
        row.notes = GOAL
    flag_modified(row, "local_run")
    flag_modified(row, "plan_json")


def _adopted_copies(db, source_id: str) -> list[Workflow]:
    """Library copies other users adopted from the source row (local_run.library_source_id)."""
    rows = (
        db.query(Workflow)
        .filter(Workflow.title == TITLE, Workflow.phase == "done", Workflow.id != source_id)
        .all()
    )
    out: list[Workflow] = []
    for row in rows:
        if workflow_is_deleted(row):
            continue
        local = row.local_run if isinstance(row.local_run, dict) else {}
        if str(local.get("library_source_id") or "").strip() == source_id:
            out.append(row)
    return out


def seed(*, user_query: str) -> None:
    init_db()
    db = SessionLocal()
    try:
        if user_query:
            user = _find_user(db, user_query)
            if user is None:
                raise SystemExit(f"User not found: {user_query}")
        else:
            user = _find_user(db, OWNER_FIO)
            if user is None:
                raise SystemExit(f"User not found: {OWNER_FIO}")
        print(f"Owner: {user.fio} ({user.id})")

        row = _find_existing(db, user.id)
        created = row is None
        if row is None:
            row = Workflow(
                id=str(uuid4()),
                user_id=user.id,
                title=TITLE,
                phase="done",
                notes=GOAL,
            )
            db.add(row)

        _apply_playbook(row)
        db.flush()

        copies = _adopted_copies(db, row.id)
        for copy_row in copies:
            _apply_playbook(copy_row)

        db.commit()
        db.refresh(row)

        print(f"workflow_id: {row.id}")
        print("created" if created else "updated")
        for copy_row in copies:
            print(f"adopted copy synced: {copy_row.id} (user {copy_row.user_id})")
    finally:
        db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Seed assignment closure check agent (published)")
    parser.add_argument(
        "--user",
        default="",
        help=f"Owner: user id or FIO (default: {OWNER_FIO})",
    )
    args = parser.parse_args()
    seed(user_query=args.user)


if __name__ == "__main__":
    main()
