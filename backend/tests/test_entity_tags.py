from app.schemas.regulation import RegulationFragment
from app.services.regulation.entity_tags import annotate_entities, filter_display_noise, is_toc_line


def _frag(**kwargs) -> RegulationFragment:
    payload = {
        "fragmentId": "B-1",
        "page": 2,
        "section": "",
        "text": "",
        "blockType": "paragraph",
    }
    payload.update(kwargs)
    return RegulationFragment(**payload)


def test_filter_skips_running_headers() -> None:
    fragments = [
        _frag(
            fragmentId="h",
            page=2,
            text="РГ-33-02-001 РЕГЛАМЕНТ внедрения решений на\nбазе искусственного интеллекта\nВерсия 01\nЛист 2\nСодержание",
        ),
        _frag(fragmentId="k", page=4, text="5.2 Руководитель сектора внедрения ИИ", blockType="heading"),
    ]
    cleaned = filter_display_noise(fragments)
    assert [item.fragmentId for item in cleaned] == ["h", "k"]
    assert cleaned[0].text == "Содержание"


def test_annotate_groups_role_and_process_blocks() -> None:
    fragments = [
        _frag(fragmentId="abbr", text="- РС ИИ - руководитель сектора внедрения ИИ"),
        _frag(fragmentId="h-role", text="5.2 Руководитель сектора внедрения ИИ", blockType="heading"),
        _frag(fragmentId="duty", text="- утверждает правила работы сектора", blockType="list_item"),
        _frag(fragmentId="h-proc", text="6.2.1 Этап 0. Инициация и регистрация потребности", blockType="heading"),
        _frag(fragmentId="step", text="- вход: обращение заказчика", blockType="list_item"),
        _frag(fragmentId="other", text="6.3 Критерии перспективности и приоритизации проектов", blockType="heading"),
        _frag(fragmentId="other-body", text="До запуска проекта проводится оценка."),
    ]
    tagged, legend = annotate_entities(fragments)
    by_id = {item.fragmentId: item for item in tagged}
    assert by_id["duty"].entities[0].kind == "role"
    assert by_id["duty"].entities[0].entityId == by_id["h-role"].entities[0].entityId
    assert by_id["duty"].entities[0].shortTitle == "РС ИИ"
    assert by_id["step"].entities[0].kind == "process"
    assert by_id["step"].entities[0].entityId == by_id["h-proc"].entities[0].entityId
    assert by_id["other-body"].entities == []
    assert [item.kind for item in legend] == ["role", "process"]


def test_toc_line_detected() -> None:
    assert is_toc_line("1 Назначение и область применения ...................................................................... 3")
    assert not is_toc_line("1 Назначение и область применения")


def test_annotate_long_uppercase_line_does_not_hang() -> None:
    text = ("АБВГДЕЖЗ " * 80).strip()
    tagged, legend = annotate_entities([_frag(fragmentId="long", text=text)])
    assert tagged[0].fragmentId == "long"
    assert legend == []


def test_annotate_skips_directors_genitive() -> None:
    fragments = [
        _frag(fragmentId="h", text="8.1. Заседания Совета директоров", blockType="heading"),
        _frag(fragmentId="b", text="Секретарь готовит повестку."),
    ]
    tagged, legend = annotate_entities(fragments)
    assert tagged[1].entities == []
    assert legend == []
