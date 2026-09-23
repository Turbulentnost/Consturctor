from app.core.jwt import create_access_token, validate_token
from app.services.profile_overrides import apply_profile_overrides, lookup_profile_overrides


def test_komarkova_is_assistant_manager() -> None:
    department, position = apply_profile_overrides(
        "Комаркова Анастасия Эдуардовна",
        "Тендерный офис",
        "менеджер тендерного офиса",
    )
    assert position == "Помощник руководителя"
    assert department == "Управление делами"
    assert lookup_profile_overrides("Комарькова А.Э.")[1] == "Помощник руководителя"


def test_ilchenko_is_board_assistant() -> None:
    _, position = apply_profile_overrides("Ильченко Екатерина Александровна", "", "")
    assert position == "Помощник Председателя совета директоров"


def test_jwt_overrides_stale_position() -> None:
    token = create_access_token(
        user_id="u-kom",
        fio="Комаркова Анастасия Эдуардовна",
        position="менеджер тендерного офиса",
        department="Тендерный офис",
    )
    auth = validate_token(token)
    assert auth.position == "Помощник руководителя"
    assert auth.department == "Управление делами"
