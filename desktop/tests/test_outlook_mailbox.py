"""Выбор ящика для outlook.search_mail: не подставлять ящик профиля вместо чужого."""

from __future__ import annotations

import pytest

from app.tools.ac.workers import outlook_com_actions as oca


class _Folder:
    def __init__(self, name: str) -> None:
        self.Name = name
        self.StoreID = f"store:{name}"


class _Store:
    def __init__(self, name: str, store_type: int) -> None:
        self.DisplayName = name
        self.ExchangeStoreType = store_type

    def GetDefaultFolder(self, folder_id: int) -> _Folder:
        return _Folder(f"{self.DisplayName}/{folder_id}")


class _Recipient:
    def __init__(self, resolved: bool) -> None:
        self.Resolved = resolved

    def Resolve(self) -> None:
        return None


class _User:
    Name = "Тест"


class _Namespace:
    def __init__(self, stores: list[_Store], *, shared: bool, resolved: bool = True) -> None:
        self.Stores = stores
        self.Accounts: list = []
        self.CurrentUser = _User()
        self._shared = shared
        self._resolved = resolved

    def GetDefaultFolder(self, folder_id: int) -> _Folder:
        return _Folder(f"profile/{folder_id}")

    def CreateRecipient(self, name: str) -> _Recipient:
        return _Recipient(self._resolved)

    def GetSharedDefaultFolder(self, recipient: _Recipient, folder_id: int) -> _Folder:
        if not self._shared:
            raise RuntimeError("access denied")
        return _Folder(f"shared/{folder_id}")


def test_own_mailbox_matches_despite_underscore() -> None:
    ns = _Namespace([_Store("test_ii@turbo-don.ru", 0)], shared=False)
    folder, status = oca._mailbox_folder(ns, "testii@turbo-don.ru", oca.INBOX_FOLDER_ID)
    assert status == "own"
    assert folder.Name.startswith("test_ii@turbo-don.ru")


def test_other_user_mailbox_is_never_profile_mailbox() -> None:
    ns = _Namespace([_Store("test_ii@turbo-don.ru", 0)], shared=False)
    with pytest.raises(oca.OutlookAccessError) as exc:
        oca._mailbox_folder(ns, "ivanov@turbo-don.ru", oca.INBOX_FOLDER_ID)
    assert "ivanov@turbo-don.ru" in str(exc.value)


def test_other_user_mailbox_opens_shared_folder() -> None:
    ns = _Namespace([_Store("test_ii@turbo-don.ru", 0)], shared=True)
    folder, status = oca._mailbox_folder(ns, "ivanov@turbo-don.ru", oca.INBOX_FOLDER_ID)
    assert status == "shared"
    assert folder.Name.startswith("shared/")


def test_added_mailbox_in_profile_is_used() -> None:
    ns = _Namespace(
        [_Store("test_ii@turbo-don.ru", 0), _Store("ivanov@turbo-don.ru", 1)], shared=False
    )
    folder, status = oca._mailbox_folder(ns, "ivanov@turbo-don.ru", oca.INBOX_FOLDER_ID)
    assert status == "store"
    assert folder.Name.startswith("ivanov@turbo-don.ru")


class _ExchangeUser:
    def __init__(self, smtp: str) -> None:
        self.PrimarySmtpAddress = smtp


class _Entry:
    def __init__(self, name: str, smtp: str) -> None:
        self.Name = name
        self._smtp = smtp

    def GetExchangeUser(self) -> _ExchangeUser:
        return _ExchangeUser(self._smtp)


class _Person:
    def __init__(self, name: str, smtp: str) -> None:
        self.Name = name
        self.AddressEntry = _Entry(name, smtp)


class _BookRecipient:
    def __init__(self, entry: _Entry | None) -> None:
        self.Resolved = entry is not None
        self.AddressEntry = entry

    def Resolve(self) -> None:
        return None


class _BookNamespace(_Namespace):
    def __init__(self, current: _Person, book: dict[str, _Entry]) -> None:
        super().__init__([], shared=False)
        self.CurrentUser = current
        self.queries: list[str] = []
        self._book = book

    def CreateRecipient(self, name: str) -> _BookRecipient:
        self.queries.append(name)
        return _BookRecipient(self._book.get(name))


def test_mailbox_for_profile_owner() -> None:
    ns = _BookNamespace(_Person("Ильченко Екатерина Александровна", "E.Ilchenko@turbo-don.ru"), {})
    assert oca._mailbox_for_person(ns, "Ильченко Екатерина Александровна") == "e.ilchenko@turbo-don.ru"
    assert ns.queries == []


def test_mailbox_for_person_from_address_book() -> None:
    ns = _BookNamespace(
        _Person("Тестов Тест", "test_ii@turbo-don.ru"),
        {"Ильченко Екатерина": _Entry("Екатерина Ильченко", "e.ilchenko@turbo-don.ru")},
    )
    assert oca._mailbox_for_person(ns, "Ильченко Екатерина Александровна") == "e.ilchenko@turbo-don.ru"


def test_mailbox_for_person_rejects_other_name() -> None:
    ns = _BookNamespace(
        _Person("Тестов Тест", "test_ii@turbo-don.ru"),
        {"Ильченко Екатерина Александровна": _Entry("Ильченко Ольга", "o.ilchenko@turbo-don.ru")},
    )
    with pytest.raises(oca.OutlookAccessError):
        oca._mailbox_for_person(ns, "Ильченко Екатерина Александровна")


def test_unknown_mailbox_reports_address_book() -> None:
    ns = _Namespace([_Store("test_ii@turbo-don.ru", 0)], shared=True, resolved=False)
    with pytest.raises(oca.OutlookAccessError) as exc:
        oca._mailbox_folder(ns, "nobody@turbo-don.ru", oca.INBOX_FOLDER_ID)
    assert "адресной книге" in str(exc.value)
