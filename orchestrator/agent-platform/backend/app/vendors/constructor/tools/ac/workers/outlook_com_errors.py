"""Исключения безопасного Outlook COM worker-а."""


class OutlookComError(Exception):
    """Базовая ошибка Outlook COM-интеграции."""


class ComUnavailableError(OutlookComError):
    """COM недоступен: не Windows, нет pywin32 или Outlook недоступен."""


class OutlookAccessError(OutlookComError):
    """Ошибка доступа к Outlook или MAPI-профилю пользователя."""


class UnsupportedOutlookToolError(OutlookComError):
    """Запрошен неподдерживаемый Outlook tool_name."""


class DangerousOutlookActionBlockedError(OutlookComError):
    """Опасное Outlook-действие заблокировано политикой безопасности."""
