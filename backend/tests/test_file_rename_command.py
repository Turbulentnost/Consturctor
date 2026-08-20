from app.services.agent_runtime import _parse_file_rename_command


def test_parse_rename_from_file_url() -> None:
    task = (
        "file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_7e81ded8.xlsx "
        "измени название файла на Поручения"
    )
    args = _parse_file_rename_command(task)
    assert args == {
        "source": "file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_7e81ded8.xlsx",
        "dest_name": "Поручения",
    }


def test_parse_rename_porucheniya_with_today() -> None:
    from datetime import date

    task = "переименуй файл поручений в Результат и сегодняшняя дата"
    args = _parse_file_rename_command(task)
    assert args is not None
    assert args["source"] == "desktop:porucheniya"
    assert args["dest_name"] == f"Результат_{date.today().strftime('%d.%m.%Y')}"


def test_parse_rename_ignored_for_copy_hints() -> None:
    task = "скопируй file:///C:/a.xlsx название Поручения"
    assert _parse_file_rename_command(task) is None
