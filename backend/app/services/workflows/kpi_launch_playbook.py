"""Агент «Запуск модулей KPI»: готовые модули, кэш на сервере и отчёт.

На платформе TurboTester это карточка 80d85957-2002-480d-b058-caa7a8198711.
ФИО людей на должности он читает только инструментом onec.position_holders.
PowerShell у него без подтверждения, кроме команд удаления и перезаписи файлов.
"""

from __future__ import annotations

KPI_LAUNCH_PLATFORM_ID = "80d85957-2002-480d-b058-caa7a8198711"
KPI_LAUNCH_TITLE = "запуск модулей kpi"


def is_kpi_launch_agent(blob: str) -> bool:
    text = (blob or "").casefold().replace("ё", "е")
    if KPI_LAUNCH_PLATFORM_ID in text:
        return True
    return KPI_LAUNCH_TITLE in text


def kpi_launch_runtime_tools() -> list[str]:
    return [
        "onec.position_holders",
        "onec.odata_catalog",
        "onec.odata_get",
        "onec.sql_query",
        "kpi.publish_position_result",
        "workspace.powershell_run",
    ]
