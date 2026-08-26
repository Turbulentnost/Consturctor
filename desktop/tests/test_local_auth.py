from pathlib import Path

from app.local_auth import mint_local_access_token, parse_local_regulation


def test_mint_local_access_token_has_three_parts() -> None:
    token = mint_local_access_token("user-1", "Тест", secret="change-me")
    assert token.count(".") == 2
    assert token.startswith("eyJ")


def test_local_role_match_uses_fragments(tmp_path: Path) -> None:
    from app.local_auth import local_role_match

    path = tmp_path / "reg.txt"
    path.write_text("Контроль поручений\nПодготовка протокола", encoding="utf-8")
    regulation = parse_local_regulation(str(path))
    result = local_role_match(regulation, "Корпоративный секретарь", "КУ")
    assert result.matches
    assert result.functions
    assert result.matches[0].status == "accepted"


def test_parse_local_regulation_from_text(tmp_path: Path) -> None:
    path = tmp_path / "reg.txt"
    path.write_text("Раздел один\n\nОбязанности помощника", encoding="utf-8")
    result = parse_local_regulation(str(path))
    assert result.file_name == "reg.txt"
    assert result.fragments
    assert "Обязанности" in " ".join(item.text for item in result.fragments)
