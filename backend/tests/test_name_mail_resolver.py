from __future__ import annotations

from app.services.name_mail_resolver import (
    discover_name_mail_slug,
    guess_name_mail_slugs,
    latin_slug_from_login,
    resolve_name_mail_for_user,
)


def test_latin_slug_from_cyrillic_login() -> None:
    assert latin_slug_from_login("Жалыбин М.Д.") == ""
    assert latin_slug_from_login("m.zhalybin") == "m.zhalybin"
    assert latin_slug_from_login("M.ZHALYBIN@turbo-don.ru") == "m.zhalybin"


def test_guess_slugs_ilchenko() -> None:
    slugs = guess_name_mail_slugs("Ильченко Екатерина Александровна")
    assert "e.ilchenko" in slugs
    assert "ilchenko" in slugs


def test_discover_uses_probe() -> None:
    calls: list[str] = []

    def probe(email: str, _password: str) -> bool:
        calls.append(email)
        return email == "e.ilchenko@turbo-don.ru"

    slug = discover_name_mail_slug(
        "Ильченко Екатерина Александровна",
        "secret",
        login_probe=probe,
    )
    assert slug == "e.ilchenko"
    assert calls


def test_resolve_prefers_v8users_latin_name() -> None:
    slug = resolve_name_mail_for_user(
        fio="Иванов Иван",
        erp_name="i.ivanov",
        password="x",
        login_probe=lambda _e, _p: True,
    )
    assert slug == "i.ivanov"
