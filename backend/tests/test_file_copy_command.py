from app.services.agent_runtime import _parse_file_copy_command


def test_parse_file_copy_command_from_chat() -> None:
    args = _parse_file_copy_command(
        "продублируй файл по file:///C:/Users/mdj/Desktop/act_porucheniya_ЖМД_7e81ded8.xlsx "
        "с названием Поручения"
    )
    assert args is not None
    assert args["source"].endswith("act_porucheniya_ЖМД_7e81ded8.xlsx")
    assert args["dest_name"] == "Поручения"


def test_parse_file_copy_ignores_ordinary_task() -> None:
    assert _parse_file_copy_command("собери реестр поручений ACT") is None
