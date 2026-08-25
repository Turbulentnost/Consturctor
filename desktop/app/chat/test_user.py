from __future__ import annotations

from app.api_client import LoginResult, UserProfile
from app.chat.models import DirectoryUser

TEST_USER_ID = "A11ADEA24A5000000000000000000001"
TEST_USER_FIO = "Анна Де Армас"
TEST_USER_PASSWORD = "anna"
TEST_USER_POSITION = "Тестовый пользователь"


def is_test_user_fio(fio: str) -> bool:
    return fio.strip().casefold() == TEST_USER_FIO.casefold()


def is_test_credentials(fio: str, password: str) -> bool:
    return is_test_user_fio(fio) and bool(password)


def matches_test_user_query(query: str) -> bool:
    needle = query.strip().casefold()
    if not needle:
        return True
    name = TEST_USER_FIO.casefold()
    if name.startswith(needle) or needle in name:
        return True
    return any(part.startswith(needle) for part in name.split())


def test_user_profile() -> UserProfile:
    return UserProfile(
        id=TEST_USER_ID,
        fio=TEST_USER_FIO,
        position=TEST_USER_POSITION,
        department="Тест",
        activity_status="online",
    )


def test_login_result() -> LoginResult:
    return LoginResult(access_token="", user=test_user_profile())


def test_directory_user() -> DirectoryUser:
    return DirectoryUser(
        id=TEST_USER_ID,
        fio=TEST_USER_FIO,
        position=TEST_USER_POSITION,
        department="Тест",
        activity_status="online",
        online=True,
    )
