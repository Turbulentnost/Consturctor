from app.core.jwt import create_access_token, validate_token
from app.services.profile_overrides import apply_profile_overrides, lookup_profile_overrides


def test_kartashova_is_board_assistant() -> None:
    department, position = apply_profile_overrides(
        "Карташова Анастасия Эдуардовна",
        "Тендерный офис",
        "Офис-менеджер",
    )
    assert position == "Помощник Председателя совета директоров"
    assert department == "Управление делами"
    assert lookup_profile_overrides("Комарькова А.Э.")[1] == "Помощник Председателя совета директоров"


def test_ilchenko_is_board_assistant() -> None:
    _, position = apply_profile_overrides("Ильченко Екатерина Александровна", "", "")
    assert position == "Помощник Председателя совета директоров"


def test_tishchenko_has_ilchenko_position_only_by_full_name() -> None:
    _, marina = apply_profile_overrides(
        "Тищенко Марина Николаевна",
        "Ревизионная комиссия",
        "Руководитель инспекционной группы",
    )
    assert marina == "Помощник Председателя совета директоров"
    _, other = apply_profile_overrides("Тищенко Марина Сергеевна", "", "Сборщик-упаковщик")
    assert other == "Сборщик-упаковщик"
    _, reversed_name = apply_profile_overrides("Марина Николаевна Тищенко", "Инспекционная группа", "")
    assert reversed_name == "Помощник Председателя совета директоров"


def test_jwt_overrides_stale_position() -> None:
    token = create_access_token(
        user_id="u-kom",
        fio="Комаркова Анастасия Эдуардовна",
        position="менеджер тендерного офиса",
        department="Тендерный офис",
    )
    auth = validate_token(token)
    assert auth.position == "Помощник Председателя совета директоров"
    assert auth.department == "Управление делами"
