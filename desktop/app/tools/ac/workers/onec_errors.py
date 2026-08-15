"""Ошибки read-only worker-а 1С."""


class OneCWorkerError(Exception):
    """Базовая ошибка worker-а 1С."""


class OneCConnectionError(OneCWorkerError):
    """Ошибка подключения к 1С."""


class OneCReadOnlyPolicyError(OneCWorkerError):
    """Нарушение read-only политики 1С."""


class OneCQueryError(OneCWorkerError):
    """Ошибка запроса к 1С."""


class OneCDocumentNotFoundError(OneCWorkerError):
    """Документ или задача 1С не найдены."""


class UnsupportedOneCToolError(OneCWorkerError):
    """Неподдерживаемый tool_name для 1С worker-а."""

