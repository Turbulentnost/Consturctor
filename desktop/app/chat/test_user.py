from __future__ import annotations

from dataclasses import dataclass

from app.api_client import LoginResult, UserProfile
from app.chat.models import DirectoryUser

TEST_USER_ID = "A11ADEA24A5000000000000000000001"
TEST_USER_FIO = "Анна Де Армас"
TEST_USER_PASSWORD = "anna"
TEST_USER_POSITION = "Тестовый пользователь"

ILCHENKO_USER_ID = "E11C4E11K00000000000000000000001"
ILCHENKO_FIO = "Ильченко Екатерина Александровна"
ILCHENKO_PASSWORD = "ilchenko"
ILCHENKO_POSITION = "Корпоративный секретарь"

ZHALYBIN_USER_ID = "M11ZHALYBIN00000000000000000001"
ZHALYBIN_FIO = "Жалыбин Максим Дмитриевич"
ZHALYBIN_PASSWORD = "mdj"
ZHALYBIN_POSITION = "Промпт-инженер 2 категории"


@dataclass(frozen=True)
class LocalTestUser:
    id: str
    fio: str
    password: str
    position: str
    department: str
    any_password: bool = False


LOCAL_TEST_USERS: tuple[LocalTestUser, ...] = (
    LocalTestUser(
        id=TEST_USER_ID,
        fio=TEST_USER_FIO,
        password=TEST_USER_PASSWORD,
        position=TEST_USER_POSITION,
        department="Тест",
        any_password=True,
    ),
    LocalTestUser(
        id=ILCHENKO_USER_ID,
        fio=ILCHENKO_FIO,
        password=ILCHENKO_PASSWORD,
        position=ILCHENKO_POSITION,
        department="Корпоративное управление",
        any_password=False,
    ),
    LocalTestUser(
        id=ZHALYBIN_USER_ID,
        fio=ZHALYBIN_FIO,
        password=ZHALYBIN_PASSWORD,
        position=ZHALYBIN_POSITION,
        department="Сектор по внедрению искусственного интеллекта",
        any_password=True,
    ),
)


def _norm(value: str) -> str:
    return " ".join((value or "").split()).casefold()


def _fio_matches(entered: str, full: str) -> bool:
    left = _norm(entered)
    right = _norm(full)
    if not left:
        return False
    if left == right:
        return True
    parts_l = left.split()
    parts_r = right.split()
    if len(parts_l) >= 2 and len(parts_r) >= 2:
        return parts_l[0] == parts_r[0] and parts_l[1] == parts_r[1]
    return False


def find_test_user(fio: str) -> LocalTestUser | None:
    for user in LOCAL_TEST_USERS:
        if _fio_matches(fio, user.fio):
            return user
    return None


def is_test_user_fio(fio: str) -> bool:
    return find_test_user(fio) is not None


def is_test_credentials(fio: str, password: str) -> bool:
    user = find_test_user(fio)
    if user is None or not password:
        return False
    if user.any_password:
        return True
    return password == user.password


def is_zhalybin_user(user_id: str = "", fio: str = "") -> bool:
    if user_id == ZHALYBIN_USER_ID:
        return True
    return find_test_user(fio) is not None and _fio_matches(fio, ZHALYBIN_FIO)


def is_ilchenko_user(user_id: str = "", fio: str = "") -> bool:
    if user_id == ILCHENKO_USER_ID:
        return True
    return find_test_user(fio) is not None and _fio_matches(fio, ILCHENKO_FIO)


def is_local_test_user(user_id: str = "", fio: str = "") -> bool:
    if user_id and any(user.id == user_id for user in LOCAL_TEST_USERS):
        return True
    return find_test_user(fio) is not None


def canonical_test_credentials(user_id: str = "", fio: str = "") -> tuple[str, str] | None:
    user = find_test_user(fio) if fio else None
    if user is None and user_id:
        user = next((item for item in LOCAL_TEST_USERS if item.id == user_id), None)
    if user is None:
        return None
    return user.fio, user.password


def matches_test_user_query(query: str) -> bool:
    needle = query.strip().casefold()
    if not needle:
        return True
    for user in LOCAL_TEST_USERS:
        name = user.fio.casefold()
        if name.startswith(needle) or needle in name:
            return True
        if any(part.startswith(needle) for part in name.split()):
            return True
    return False


def matching_test_fios(query: str) -> list[str]:
    if not matches_test_user_query(query):
        return []
    needle = query.strip().casefold()
    if not needle:
        return [user.fio for user in LOCAL_TEST_USERS]
    found: list[str] = []
    for user in LOCAL_TEST_USERS:
        name = user.fio.casefold()
        if name.startswith(needle) or needle in name or any(part.startswith(needle) for part in name.split()):
            found.append(user.fio)
    return found


def _profile(user: LocalTestUser) -> UserProfile:
    return UserProfile(
        id=user.id,
        fio=user.fio,
        position=user.position,
        department=user.department,
        activity_status="online",
    )


def test_user_profile() -> UserProfile:
    return _profile(LOCAL_TEST_USERS[0])


def test_login_result(fio: str = "") -> LoginResult:
    user = find_test_user(fio) if fio else LOCAL_TEST_USERS[0]
    if user is None:
        user = LOCAL_TEST_USERS[0]
    return LoginResult(access_token="", user=_profile(user))


def test_directory_user() -> DirectoryUser:
    return _directory(LOCAL_TEST_USERS[0])


def test_directory_users() -> list[DirectoryUser]:
    return [_directory(user) for user in LOCAL_TEST_USERS]


def _directory(user: LocalTestUser) -> DirectoryUser:
    return DirectoryUser(
        id=user.id,
        fio=user.fio,
        position=user.position,
        department=user.department,
        activity_status="online",
        online=True,
    )
