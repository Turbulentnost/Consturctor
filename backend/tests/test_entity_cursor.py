from app.schemas.regulation import RegulationFragment
from app.services.regulation.entity_cursor import apply_entity_payload
from app.services.regulation.entity_tags import annotate_entities


def _frag(**kwargs) -> RegulationFragment:
    payload = {
        "fragmentId": "B-1",
        "page": 1,
        "section": "",
        "text": "",
        "blockType": "paragraph",
    }
    payload.update(kwargs)
    return RegulationFragment(**payload)


def test_apply_entity_payload_tags_user_role() -> None:
    fragments = [
        _frag(fragmentId="title", text="Регламент действий должности «Помощник ПСД»", blockType="heading"),
        _frag(fragmentId="duty", text="контроль исполнения решений и поручений"),
        _frag(fragmentId="other", text="8.1. Заседания Совета директоров", blockType="heading"),
    ]
    tagged, legend = apply_entity_payload(
        fragments,
        {
            "entities": [
                {
                    "entityId": "role:user",
                    "kind": "role",
                    "title": "Помощник Председателя совета директоров",
                    "shortTitle": "Помощник ПСД",
                }
            ],
            "assignments": [{"fragmentId": "duty", "entityIds": ["role:user"]}],
        },
        position="Помощник Председателя совета директоров",
    )
    by_id = {item.fragmentId: item for item in tagged}
    assert by_id["duty"].entities[0].title == "Помощник Председателя совета директоров"
    assert by_id["title"].entities == []
    assert by_id["other"].entities == []
    assert legend[0].shortTitle == "Помощник ПСД"
    assert legend[0].fragmentIds == ["duty"]


def test_annotate_does_not_treat_directors_board_as_role() -> None:
    fragments = [
        _frag(fragmentId="h", text="8.1. Заседания Совета директоров", blockType="heading"),
        _frag(fragmentId="b", text="Повестка формируется заранее."),
    ]
    tagged, legend = annotate_entities(fragments)
    assert tagged[1].entities == []
    assert legend == []


def test_annotate_marks_assistant_heading() -> None:
    fragments = [
        _frag(fragmentId="h", text="Помощник Председателя совета директоров", blockType="heading"),
        _frag(fragmentId="b", text="Организует совещания без коллизий."),
    ]
    tagged, _legend = annotate_entities(fragments)
    assert tagged[1].entities[0].kind == "role"
