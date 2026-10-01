"""Document_ТД_Протокол create body: mapping of agent arguments to OData fields."""

from __future__ import annotations

import pytest

from app.services import meeting_protocol_write as mpw

USERS = {
    "Соломичева Светлана Викторовна": {
        "ref_key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
        "fio": "Соломичева Светлана Викторовна",
        "person_key": "aaaaaaaa-0000-0000-0000-000000000001",
        "department_key": "4668a58b-6eb1-11e2-afce-001e67112509",
    },
    "Жалыбин Максим Дмитриевич": {
        "ref_key": "41290a43-5990-11f1-980e-6cb31113810e",
        "fio": "Жалыбин Максим Дмитриевич",
        "person_key": "2a2a4097-58c5-11f1-980d-6cb31113810c",
        "department_key": "2094af18-de06-11ef-95fc-6cb31113810e",
    },
}
PERSONS = {
    "Жалыбин Максим Дмитриевич": "2a2a4097-58c5-11f1-980d-6cb31113810c",
    "Соломичева Светлана Викторовна": "aaaaaaaa-0000-0000-0000-000000000001",
    "Мегрелишвили Михаил Эмзарович": "bbbbbbbb-0000-0000-0000-000000000002",
}
THEME = {
    "Ref_Key": "b2e6e94a-6885-11f1-9822-6cb31113810e",
    "Description": 'Еженедельное совещание РГ по проекту "Разработка ИИ-агентов (первая очередь)"',
    "Руководитель_Key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
    "Проверяющий_Key": "5b2e1e74-a805-11eb-85c6-ac1f6b05524d",
    "Проект_Key": "7e931aca-634a-11f1-981b-6cb31113810e",
    "Подразделение_Key": "4668a58b-6eb1-11e2-afce-001e67112509",
    "ВидСовещания": "Отчетное",
    "Кабинет_Key": "00000000-0000-0000-0000-000000000000",
}


@pytest.fixture(autouse=True)
def _fake_resolvers(monkeypatch):
    def resolve_user_card(query: str):
        for fio, card in USERS.items():
            if query == card["ref_key"] or query.casefold() in fio.casefold():
                return dict(card)
        raise mpw.ProtocolWriteError(f"Пользователь 1С не найден: {query}")

    def resolve_person(query: str):
        for fio, key in PERSONS.items():
            if query.casefold() in fio.casefold():
                return {"ref_key": key, "fio": fio}
        raise mpw.ProtocolWriteError(f"Физическое лицо 1С не найдено: {query}")

    def resolve_theme(query: str):
        return dict(THEME) if "ИИ-агентов" in query or query == THEME["Ref_Key"] else None

    def resolve_ref(entity: str, query: str):
        if entity == mpw.ACCESS_ENTITY and query == "Общий":
            return "bbdfce50-4266-11e8-8272-ac1f6b05524d"
        if entity == mpw.ROOM_ENTITY and "конференц" in query:
            return "35ccfb35-ad89-11f0-9720-6cb31113810e"
        return ""

    monkeypatch.setattr(mpw, "resolve_user_card", resolve_user_card)
    monkeypatch.setattr(mpw, "resolve_person", resolve_person)
    monkeypatch.setattr(mpw, "resolve_theme", resolve_theme)
    monkeypatch.setattr(mpw, "resolve_ref", resolve_ref)


@pytest.fixture(autouse=True)
def _no_live_odata_writes(monkeypatch):
    for name in ("_odata_post", "_odata_patch", "_odata_delete"):
        monkeypatch.setattr(mpw, name, lambda args, name=name: pytest.fail(f"unexpected {name}: {args}"))


def _args() -> dict:
    return {
        "topic": "Разработка ИИ-агентов",
        "date": "2026-09-21",
        "time_start": "10:30",
        "time_end": "11:00",
        "room": "малый конференц-зал",
        "participants": ["Соломичева Светлана Викторовна", "Жалыбин Максим Дмитриевич", "Неизвестный Гость"],
        "agenda": ["Статус ИИ-агентов", {"question": "Библиотека агентов", "responsible": "Жалыбин"}],
        "decisions": ["Подключить агента совещаний в библиотеку", {"text": "Расчёт KPI", "due": "2026-09-24"}],
        "tasks": [
            {"text": "Проверить в outlook регистрацию вх.корр в 1с", "executor": "Жалыбин Максим Дмитриевич", "due": "2026-09-24"},
            {"text": "Сделать расчёт КПИ", "executor": "Комаркова", "due": "2026-09-22", "priority": "Высокий"},
        ],
        "comment": "Сформировано ИИ-агентом по аудиозаписи 1 сент., 13.07_ (1).aac",
    }


def test_header_comes_from_theme_and_session():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert body["ТемаСовещания_Key"] == THEME["Ref_Key"]
    assert body["Руководитель_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert body["Ответственный_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert body["Подготовил_Key"] == USERS["Жалыбин Максим Дмитриевич"]["ref_key"]
    assert body["Проект_Key"] == THEME["Проект_Key"]
    assert body["Подразделение_Key"] == THEME["Подразделение_Key"]
    assert body["Кабинет_Key"] == "35ccfb35-ad89-11f0-9720-6cb31113810e"
    assert body["ГрифДоступа_Key"] == "bbdfce50-4266-11e8-8272-ac1f6b05524d"
    assert body["ВидСовещания"] == "Отчетное"
    assert body["Статус"] == "Подготовлен"
    assert body["Posted"] is False
    assert body["Date"].startswith("2026-09-21")
    assert body["ВремяНачалаСовещания"] == "0001-01-01T10:30:00"
    assert body["ВремяОкончанияСовещания"] == "0001-01-01T11:00:00"
    assert meta["leader"] == "Соломичева Светлана Викторовна"
    assert meta["prepared_by"] == "Жалыбин Максим Дмитриевич"


def test_tabular_sections_map_to_1c_fields():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    attendees = body["ПрисутствующиеНаСовещании"]
    assert [row["Участник_Key"] for row in attendees] == [
        PERSONS["Соломичева Светлана Викторовна"],
        PERSONS["Жалыбин Максим Дмитриевич"],
    ]
    assert attendees[1]["LineNumber"] == "2"
    assert "Соломичева Светлана Викторовна; Жалыбин Максим Дмитриевич" == body["КраткийСоставДокумента"]

    agenda = body["ПовесткаСовещания"]
    assert agenda[0]["Вопрос"] == "Статус ИИ-агентов"
    assert agenda[0]["Вопрос_Type"] == "Edm.String"
    assert agenda[1]["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]

    decisions = body["Решения"]
    assert decisions[0]["ТекстРешения"] == "Подключить агента совещаний в библиотеку"
    assert decisions[0]["ДатаНачала"] == "2026-09-21T00:00:00"
    assert decisions[0]["ДокументОснование_Type"] == "StandardODATA.Undefined"
    assert decisions[1]["ДатаОкончания"] == "2026-09-24T23:59:59"

    tasks = body["ПеременныеЗадачиПротокола"]
    standing = body["ПостоянныеЗадачиПротокола"]
    assert len(tasks) == len(standing) == 2
    assert tasks[0]["Задача"].startswith("Проверить в outlook")
    assert tasks[0]["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]
    assert "Ответственный" not in tasks[0]
    assert tasks[0]["Отправлена"] is False
    assert tasks[0]["Автор_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert tasks[0]["ДатаПостановкиЗадачи"] == "2026-09-21T00:00:00"
    assert tasks[0]["ДатаФактическогоИсполнения"] == "2026-09-24T23:59:59"
    assert tasks[1]["Приоритет"] == "Высокий"
    assert "Ответственный_Key" not in tasks[1]  # Комаркова не найдена в 1С — строку не пишем

    assert meta["tasks_count"] == 2 and meta["agenda_count"] == 2 and meta["decisions_count"] == 2


def test_unknown_meeting_type_does_not_block_tasks():
    args = _args()
    args["meeting_type"] = "Планерное"
    body, meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert body["ВидСовещания"] == "Отчетное"
    assert any("Планерное" in item for item in meta["unresolved"])
    assert len(body["ПеременныеЗадачиПротокола"]) == 2


def test_unresolved_names_go_to_comment_not_error():
    body, meta = mpw.build_protocol_create_body(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert any("Неизвестный Гость" in item for item in meta["unresolved"])
    assert any("Комаркова" in item for item in meta["unresolved"])
    assert body["Комментарий"].startswith("Сформировано ИИ-агентом")
    assert "Не сопоставлено с 1С" in body["Комментарий"]


def test_outlook_room_alias_resolves_to_catalog_name(monkeypatch):
    queries: list[str] = []
    original = mpw.resolve_ref

    def fake_resolve(entity, query):
        if entity == mpw.ROOM_ENTITY:
            queries.append(query)
            return "84107ae4-e273-11ec-88d8-ac1f6b05524d"
        return original(entity, query)

    monkeypatch.setattr(mpw, "resolve_ref", fake_resolve)
    args = _args()
    args["room"] = "Кабинент  СР"
    body, meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert queries == ["Служба развития"]
    assert body["Кабинет_Key"] == "84107ae4-e273-11ec-88d8-ac1f6b05524d"
    assert not any("кабинет" in item for item in meta["unresolved"])


def test_resave_replaces_previous_unresolved_note():
    args = _args()
    args["comment"] = "Сформировано ИИ-агентом\nНе сопоставлено с 1С: кабинет «Кабинент СР»"
    body, _meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert "Кабинент СР" not in body["Комментарий"]
    assert body["Комментарий"].count("Не сопоставлено с 1С") == 1


def test_resave_strips_note_from_flattened_comment_keeping_outlook_marker():
    args = _args()
    args["comment"] = (
        "Сформировано ИИ-агентом по аудиозаписи 09.48_.m4a "
        "Не сопоставлено с 1С: кабинет «Кабинент СР» outlook:AAMk|2026-09-28"
    )
    body, _meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert "Кабинент СР" not in body["Комментарий"]
    assert "09.48_.m4a outlook:AAMk|2026-09-28" in body["Комментарий"]


def test_leader_falls_back_to_session_without_theme():
    args = _args()
    args["topic"] = "Совещание без темы в справочнике"
    body, meta = mpw.build_protocol_create_body(args, actor_fio="Жалыбин Максим Дмитриевич")
    assert "ТемаСовещания_Key" not in body
    assert body["Руководитель_Key"] == USERS["Жалыбин Максим Дмитриевич"]["ref_key"]
    assert body["Подразделение_Key"] == USERS["Жалыбин Максим Дмитриевич"]["department_key"]
    assert any("тема совещания" in item for item in meta["unresolved"])


def test_leader_required_when_nothing_known():
    args = _args()
    args["topic"] = ""
    with pytest.raises(mpw.ProtocolWriteError):
        mpw.build_protocol_create_body(args)


def test_empty_protocol_is_rejected(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_post", lambda *_: pytest.fail("POST must not happen"))
    with pytest.raises(mpw.ProtocolWriteError):
        mpw.handle_protocol_write(
            {"topic": "Разработка ИИ-агентов", "date": "2026-09-21"},
            actor_fio="Жалыбин Максим Дмитриевич",
        )


NEW_KEY = "96396617-b5b0-11f1-9889-6cb31113810c"


def _missing_record(args):
    from app.services.onec_tools import OnecToolError

    raise OnecToolError("1C OData HTTP 404: запись не найдена")


def test_create_posts_and_returns_number(monkeypatch):
    posted: list[dict] = []

    def fake_post(args):
        posted.append(args)
        return {"data": {"Ref_Key": NEW_KEY, "Number": "ДР__062_О_427"}}

    monkeypatch.setattr(mpw, "_odata_post", fake_post)
    monkeypatch.setattr(mpw, "_odata_patch", _missing_record)
    result = mpw.handle_protocol_write(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert posted[0]["entity"] == mpw.PROTOCOL_ENTITY
    assert result["number"] == "ДР__062_О_427"
    assert result["ref_key"] == NEW_KEY
    assert result["posted"] is False
    assert "ДР__062_О_427" in result["summary"]
    assert result["unresolved"]


def test_create_writes_tasks_to_register(monkeypatch):
    posted: list[dict] = []

    def fake_post(args):
        posted.append(args)
        return {"data": {"Ref_Key": NEW_KEY, "Number": "ДР__062_О_427"}}

    monkeypatch.setattr(mpw, "_odata_post", fake_post)
    monkeypatch.setattr(mpw, "_odata_patch", _missing_record)
    result = mpw.handle_protocol_write(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    records = [call["body"] for call in posted if call["entity"] == mpw.TASK_REGISTER]
    assert len(records) == 2
    first = records[0]
    assert first["Протокол_Key"] == NEW_KEY
    assert first["ТемаСовещания_Key"] == THEME["Ref_Key"]
    assert first["ИдентификаторЗадачи"] == mpw.task_register_id(NEW_KEY, 1)
    assert first["Задача"] == "Проверить в outlook регистрацию вх.корр в 1с"
    assert first["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]
    assert first["Автор_Key"] == USERS["Соломичева Светлана Викторовна"]["ref_key"]
    assert first["СрокИсполнения"].startswith("2026-09-24")
    assert first["НомерПунктаПротокола"] == 1 and first["Отправлена"] is False
    assert records[1]["ИдентификаторЗадачи"] != first["ИдентификаторЗадачи"]
    assert result["task_register"] == {"entity": mpw.TASK_REGISTER, "written": 2, "removed": 0, "errors": []}
    assert "задач в регистре: 2" in result["summary"]


def test_register_failure_is_reported_not_raised(monkeypatch):
    from app.services.onec_tools import OnecToolError

    def fake_post(args):
        if args["entity"] == mpw.TASK_REGISTER:
            raise OnecToolError("1C OData HTTP 401: Доступ запрещен")
        return {"data": {"Ref_Key": NEW_KEY, "Number": "ДР__062_О_427"}}

    monkeypatch.setattr(mpw, "_odata_post", fake_post)
    monkeypatch.setattr(mpw, "_odata_patch", _missing_record)
    result = mpw.handle_protocol_write(_args(), actor_fio="Жалыбин Максим Дмитриевич")
    assert result["ref_key"] == NEW_KEY
    assert len(result["task_register"]["errors"]) == 2
    assert "записаны не все" in result["summary"]


def test_register_resave_patches_and_drops_removed_lines(monkeypatch):
    patched: list[dict] = []
    deleted: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_patch", lambda args: patched.append(args) or {"updated": True})
    monkeypatch.setattr(mpw, "_odata_delete", lambda args: deleted.append(args) or {"deleted": True})
    rows = [{"LineNumber": "1", "Задача": "Одна задача", "НомерПунктаПротокола": "3"}]
    result = mpw.sync_task_register(NEW_KEY, THEME["Ref_Key"], rows, previous_count=3)
    assert result["written"] == 1 and result["removed"] == 2
    assert patched[0]["key"]["ИдентификаторЗадачи"] == mpw.task_register_id(NEW_KEY, 1)
    assert "Отправлена" not in patched[0]["body"]
    assert patched[0]["body"]["НомерПунктаПротокола"] == 3
    assert [call["key"]["ИдентификаторЗадачи"] for call in deleted] == [
        mpw.task_register_id(NEW_KEY, 2),
        mpw.task_register_id(NEW_KEY, 3),
    ]


def test_register_record_key_segment():
    from app.services.onec_tools import _odata_key_segment

    key = {"Протокол_Key": NEW_KEY, "ТемаСовещания_Key": THEME["Ref_Key"], "ИдентификаторЗадачи": NEW_KEY}
    assert _odata_key_segment({"key": key}) == (
        f"Протокол_Key=guid'{NEW_KEY}',ТемаСовещания_Key=guid'{THEME['Ref_Key']}',"
        f"ИдентификаторЗадачи=guid'{NEW_KEY}'"
    )
    assert _odata_key_segment({"ref_key": NEW_KEY}) == f"guid'{NEW_KEY}'"


def test_register_theme_change_moves_all_records(monkeypatch):
    deleted: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_patch", lambda args: {"updated": True})
    monkeypatch.setattr(mpw, "_odata_delete", lambda args: deleted.append(args) or {"deleted": True})
    old_theme = "11111111-2222-3333-4444-555555555555"
    rows = [{"LineNumber": "1", "Задача": "A"}, {"LineNumber": "2", "Задача": "B"}]
    mpw.sync_task_register(NEW_KEY, THEME["Ref_Key"], rows, previous_count=2, previous_theme_key=old_theme)
    assert len(deleted) == 2
    assert all(call["key"]["ТемаСовещания_Key"] == old_theme for call in deleted)


def test_time_parsing_variants():
    assert mpw._time_value("9:05") == "0001-01-01T09:05:00"
    assert mpw._time_value("2026-09-21T10:30:00") == "0001-01-01T10:30:00"
    assert mpw._time_value("") == ""
    with pytest.raises(mpw.ProtocolWriteError):
        mpw._time_value("25:00")


PROTOCOL_KEY = "96396617-b5b0-11f1-9889-6cb31113810c"


def _card(**overrides) -> dict:
    card = {
        "Ref_Key": PROTOCOL_KEY,
        "Number": "ДР__062_О_426",
        "Date": "2026-09-21T00:00:00",
        "Posted": False,
        "Статус": "Подготовлен",
        "ВидСовещания": "Отчетное",
        "ТемаСовещания_Key": THEME["Ref_Key"],
        "Руководитель_Key": USERS["Соломичева Светлана Викторовна"]["ref_key"],
        "Ответственный_Key": USERS["Соломичева Светлана Викторовна"]["ref_key"],
        "Подготовил_Key": USERS["Жалыбин Максим Дмитриевич"]["ref_key"],
        "Кабинет_Key": "35ccfb35-ad89-11f0-9720-6cb31113810e",
        "ВремяНачалаСовещания": "0001-01-01T10:30:00",
        "ВремяОкончанияСовещания": "0001-01-01T11:00:00",
        "ДатаСледующегоСовещания": "0001-01-01T00:00:00",
        "Комментарий": "Сформировано агентом\noutlook:AAMkAGI2",
        "ПрисутствующиеНаСовещании": [
            {"LineNumber": "2", "Участник_Key": PERSONS["Жалыбин Максим Дмитриевич"]},
            {"LineNumber": "1", "Участник_Key": PERSONS["Соломичева Светлана Викторовна"]},
        ],
        "ПовесткаСовещания": [
            {"LineNumber": "1", "Вопрос": "Статус ИИ-агентов", "Ответственный_Key": PERSONS["Жалыбин Максим Дмитриевич"]},
        ],
        "Решения": [
            {"LineNumber": "1", "ТекстРешения": "Расчёт KPI", "ДатаОкончания": "2026-09-24T23:59:59"},
        ],
        "ПеременныеЗадачиПротокола": [
            {
                "LineNumber": "1",
                "Задача": "Сделать расчёт КПИ",
                "Ответственный_Key": PERSONS["Мегрелишвили Михаил Эмзарович"],
                "ДатаФактическогоИсполнения": "2026-09-22T23:59:59",
                "Приоритет": "Высокий",
                "Примечание": "",
                "НомерПунктаПротокола": "1",
            }
        ],
    }
    card.update(overrides)
    return card


def _fake_get(card: dict):
    persons = {key: fio for fio, key in PERSONS.items()}
    users = {c["ref_key"]: fio for fio, c in USERS.items()}

    def fake_get(args):
        entity, key = args.get("entity"), args.get("ref_key")
        if entity == mpw.PROTOCOL_ENTITY:
            return {"value": [card]} if key == card["Ref_Key"] else {"value": []}
        if entity == mpw.PERSON_ENTITY and key in persons:
            return {"value": [{"Ref_Key": key, "Description": persons[key]}]}
        if entity == mpw.USER_ENTITY and key in users:
            return {"value": [{"Ref_Key": key, "Description": users[key]}]}
        if entity == mpw.THEME_ENTITY and key == THEME["Ref_Key"]:
            return {"value": [dict(THEME)]}
        if entity == mpw.ROOM_ENTITY:
            return {"value": [{"Ref_Key": key, "Description": "Малый конференц-зал"}]}
        return {"value": []}

    return fake_get


def test_read_protocol_form_maps_guids_to_names(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_get", _fake_get(_card()))
    result = mpw.read_protocol_form(PROTOCOL_KEY)
    assert result["number"] == "ДР__062_О_426"
    assert result["editable"] is True
    form = result["form"]
    assert form["topic"] == THEME["Description"]
    assert form["theme_key"] == THEME["Ref_Key"]
    assert form["date"] == "2026-09-21"
    assert form["time_start"] == "10:30" and form["time_end"] == "11:00"
    assert form["next_meeting_date"] == ""
    assert form["room"] == "Малый конференц-зал"
    assert form["leader"] == "Соломичева Светлана Викторовна"
    assert form["prepared_by"] == "Жалыбин Максим Дмитриевич"
    # tabular parts sorted by LineNumber, GUIDs resolved
    assert form["participants"] == ["Соломичева Светлана Викторовна", "Жалыбин Максим Дмитриевич"]
    assert [(row["question"], row["responsible"]) for row in form["agenda"]] == [
        ("Статус ИИ-агентов", "Жалыбин Максим Дмитриевич")
    ]
    assert [(row["text"], row["due"]) for row in form["decisions"]] == [("Расчёт KPI", "2026-09-24")]
    assert form["tasks"][0]["executor"] == "Мегрелишвили Михаил Эмзарович"
    assert form["tasks"][0]["due"] == "2026-09-22"
    assert form["tasks"][0]["priority"] == "Высокий"
    assert "outlook:AAMkAGI2" in form["comment"]


def test_read_protocol_form_prefers_assigned_tasks_part(monkeypatch):
    card = _card(
        ПостоянныеЗадачиПротокола=[
            {"LineNumber": "1", "Задача": "Постоянная задача", "Ответственный": "Давлетов Руслан Игоревич"}
        ]
    )
    monkeypatch.setattr(mpw, "_odata_get", _fake_get(card))
    tasks = mpw.read_protocol_form(PROTOCOL_KEY)["form"]["tasks"]
    assert [task["text"] for task in tasks] == ["Сделать расчёт КПИ", "Постоянная задача"]
    assert tasks[0]["executor"] == "Мегрелишвили Михаил Эмзарович"


def test_read_protocol_form_posted_is_not_editable(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_get", _fake_get(_card(Posted=True, Статус="Проведён")))
    result = mpw.read_protocol_form(PROTOCOL_KEY)
    assert result["editable"] is False and result["posted"] is True


def test_update_patches_draft_and_keeps_outlook_marker(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_get", _fake_get(_card()))
    calls: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_patch", lambda args: calls.append(args) or {"updated": True})
    monkeypatch.setattr(mpw, "_odata_delete", lambda args: {"deleted": True})
    args = {**_args(), "action": "update", "ref_key": PROTOCOL_KEY, "comment": "Правки вручную"}
    result = mpw.handle_protocol_write(args, actor_fio="Жалыбин Максим Дмитриевич")
    patched = calls[0]
    assert patched["entity"] == mpw.PROTOCOL_ENTITY and patched["ref_key"] == PROTOCOL_KEY
    assert [call["entity"] for call in calls[1:]] == [mpw.TASK_REGISTER, mpw.TASK_REGISTER]
    body = patched["body"]
    for field in ("ДатаСоздания", "Posted", "DeletionMark", "Статус", "Подготовил_Key"):
        assert field not in body
    assert body["ПовесткаСовещания"][0]["Вопрос"] == "Статус ИИ-агентов"
    assert len(body["Решения"]) == 2 and len(body["ПеременныеЗадачиПротокола"]) == 2
    assert len(body["ПостоянныеЗадачиПротокола"]) == 2
    assert body["ПеременныеЗадачиПротокола"][0]["Ответственный_Key"] == PERSONS["Жалыбин Максим Дмитриевич"]
    assert body["ПостоянныеЗадачиПротокола"][0]["Ответственный"] == "Жалыбин Максим Дмитриевич"
    assert body["Комментарий"].startswith("Правки вручную")
    assert "outlook:AAMkAGI2" in body["Комментарий"]
    assert result["updated"] is True and result["number"] == "ДР__062_О_426"
    assert result["ref_key"] == PROTOCOL_KEY


def test_update_refuses_posted_protocol(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_get", _fake_get(_card(Posted=True, Статус="Проведён")))
    monkeypatch.setattr(mpw, "_odata_patch", lambda *_: pytest.fail("PATCH must not happen"))
    with pytest.raises(mpw.ProtocolWriteError, match="проведён"):
        mpw.handle_protocol_write(
            {**_args(), "action": "update", "ref_key": PROTOCOL_KEY},
            actor_fio="Жалыбин Максим Дмитриевич",
        )


def test_update_requires_ref_key():
    with pytest.raises(mpw.ProtocolWriteError, match="ref_key"):
        mpw.handle_protocol_write({**_args(), "action": "update"}, actor_fio="Жалыбин Максим Дмитриевич")


def test_meeting_protocols_ref_key_returns_card(monkeypatch):
    from app.services import meeting_protocols

    monkeypatch.setattr(mpw, "_odata_get", _fake_get(_card()))
    result = meeting_protocols.list_meeting_protocols({"meeting_kind": "any", "ref_key": PROTOCOL_KEY})
    assert result["readonly"] is True
    assert result["protocol"]["number"] == "ДР__062_О_426"
    assert result["protocol"]["form"]["leader"] == "Соломичева Светлана Викторовна"


def test_tool_registered_as_write_tool():
    from app.services import onec_tools

    assert "onec.meeting_protocol_write" in onec_tools.ONEC_TOOLS
    assert "onec.meeting_protocol_write" in onec_tools.ONEC_WRITE_TOOLS
    assert onec_tools.REAL_HANDLERS["onec.meeting_protocol_write"] is mpw.handle_protocol_write
    stub = onec_tools.STUB_HANDLERS["onec.meeting_protocol_write"]({"tasks": ["a"]})
    assert stub["source"] == "stub" and stub["entity"] == mpw.PROTOCOL_ENTITY


SENT_ID = "11111111-2222-4333-8444-555555555555"
OPEN_ID = "66666666-7777-4888-9999-000000000000"


def _register_rows() -> list[dict]:
    base = {"Протокол_Key": PROTOCOL_KEY, "ТемаСовещания_Key": THEME["Ref_Key"], "ПроцессID": ""}
    return [
        {**base, "ИдентификаторЗадачи": OPEN_ID, "НомерПунктаПротокола": "2", "Задача": "Открытая задача",
         "Ответственный_Key": PERSONS["Жалыбин Максим Дмитриевич"], "СрокИсполнения": "2026-10-05T23:59:59",
         "Отправлена": False},
        {**base, "ИдентификаторЗадачи": SENT_ID, "НомерПунктаПротокола": "1", "Задача": "Отправленная задача",
         "Ответственный_Key": PERSONS["Мегрелишвили Михаил Эмзарович"], "Отправлена": True},
    ]


def _fake_get_with_register(card: dict, rows: list[dict]):
    base = _fake_get(card)

    def fake_get(args):
        if args.get("entity") == mpw.TASK_REGISTER:
            assert PROTOCOL_KEY in args.get("filter", "")
            return {"value": [dict(row) for row in rows]}
        return base(args)

    return fake_get


def test_read_protocol_form_posted_takes_tasks_from_register(monkeypatch):
    card = _card(Posted=True, Статус="НаИсполнении")
    monkeypatch.setattr(mpw, "_odata_get", _fake_get_with_register(card, _register_rows()))
    form = mpw.read_protocol_form(PROTOCOL_KEY)["form"]
    assert form["tasks_source"] == "register"
    assert [task["item"] for task in form["tasks"]] == ["1", "2"]
    sent, open_task = form["tasks"]
    assert sent["id"] == SENT_ID and sent["sent"] is True
    assert open_task["executor"] == "Жалыбин Максим Дмитриевич" and open_task["due"] == "2026-10-05"


def test_add_tasks_refuses_draft(monkeypatch):
    monkeypatch.setattr(mpw, "_odata_get", _fake_get_with_register(_card(), []))
    with pytest.raises(mpw.ProtocolWriteError, match="черновик"):
        mpw.handle_protocol_write(
            {"action": "add_tasks", "ref_key": PROTOCOL_KEY, "tasks": [{"text": "Новая"}]}
        )


def test_add_tasks_numbers_from_register_not_table(monkeypatch):
    card = _card(Posted=True, Статус="Закрыт")
    monkeypatch.setattr(mpw, "_odata_get", _fake_get_with_register(card, []))
    posted: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_post", lambda args: posted.append(args) or {})
    mpw.handle_protocol_write({"action": "add_tasks", "ref_key": PROTOCOL_KEY, "tasks": ["Первая", "Вторая"]})
    assert [call["body"]["НомерПунктаПротокола"] for call in posted] == [1, 2]


def test_add_tasks_renumbers_unsent_by_id(monkeypatch):
    card = _card(Posted=True, Статус="Закрыт")
    monkeypatch.setattr(mpw, "_odata_get", _fake_get_with_register(card, _register_rows()))
    patched: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_patch", lambda args: patched.append(args) or {})
    mpw.handle_protocol_write({"action": "add_tasks", "ref_key": PROTOCOL_KEY, "tasks": [{"id": OPEN_ID, "item": 7}]})
    assert patched[0]["body"] == {"НомерПунктаПротокола": 7}


def test_add_tasks_appends_to_register_and_edits_unsent(monkeypatch):
    card = _card(Posted=True, Статус="НаИсполнении")
    monkeypatch.setattr(mpw, "_odata_get", _fake_get_with_register(card, _register_rows()))
    posted: list[dict] = []
    patched: list[dict] = []
    monkeypatch.setattr(mpw, "_odata_post", lambda args: posted.append(args) or {})
    monkeypatch.setattr(mpw, "_odata_patch", lambda args: patched.append(args) or {"updated": True})
    result = mpw.handle_protocol_write(
        {
            "action": "add_tasks",
            "ref_key": PROTOCOL_KEY,
            "tasks": [
                {"text": "Новая задача", "executor": "Соломичева", "due": "2026-10-10"},
                {"id": OPEN_ID, "due": "2026-10-12"},
                {"id": SENT_ID, "text": "Переписать"},
                {"text": "Кому-то", "executor": "Неизвестный"},
            ],
        }
    )
    assert len(posted) == 1
    record = posted[0]["body"]
    assert posted[0]["entity"] == mpw.TASK_REGISTER
    assert record["Протокол_Key"] == PROTOCOL_KEY and record["ТемаСовещания_Key"] == THEME["Ref_Key"]
    assert record["НомерПунктаПротокола"] == 3
    assert record["Ответственный_Key"] == PERSONS["Соломичева Светлана Викторовна"]
    assert record["СрокИсполнения"].startswith("2026-10-10")
    assert record["ДатаПостановкиЗадачи"] == "2026-09-21T00:00:00"
    assert record["Отправлена"] is False and record["ИдентификаторЗадачи"] not in (OPEN_ID, SENT_ID)
    assert len(patched) == 1
    assert patched[0]["key"]["ИдентификаторЗадачи"] == OPEN_ID
    assert list(patched[0]["body"]) == ["СрокИсполнения"]
    assert [item["item"] for item in result["added"]] == [3]
    assert result["changed"][0]["id"] == OPEN_ID
    assert any("отправлена" in error for error in result["errors"])
    assert result["unresolved"] == ["исполнитель задачи «Неизвестный»"]
