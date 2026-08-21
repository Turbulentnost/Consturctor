"""Поиск / focus / screenshot окна браузера для OS fallback (Windows)."""

from __future__ import annotations

import ctypes
from typing import Any
from urllib.parse import urlparse


BROWSER_PROCESS_NAMES = {
    "chrome.exe",
    "msedge.exe",
    "firefox.exe",
    "brave.exe",
    "opera.exe",
    "chromium.exe",
}


def focus_browser_window(url_hint: str = "") -> dict[str, Any]:
    """Вывести окно браузера на передний план. Вернуть meta (hwnd/title/ok)."""
    hwnd = find_browser_hwnd(url_hint=url_hint)
    if not hwnd:
        return {"ok": False, "reason": "browser_window_not_found"}
    ok = _set_foreground(hwnd)
    title = _window_title(hwnd)
    rect = _window_rect(hwnd)
    return {
        "ok": bool(ok),
        "hwnd": int(hwnd),
        "title": title,
        "rect": rect,
        "reason": "focused" if ok else "focus_failed",
    }


def find_browser_hwnd(url_hint: str = "") -> int | None:
    """Найти HWND видимого окна браузера (предпочитая title с host из url)."""
    if not _is_windows():
        return None
    host = _url_host(url_hint)
    windows = _list_candidate_windows()
    if not windows:
        return None
    if host:
        for item in windows:
            if host in item["title"].casefold():
                return item["hwnd"]
    # Иначе самое большое видимое окно браузера (обычно рабочая вкладка).
    windows.sort(key=lambda item: item["area"], reverse=True)
    return windows[0]["hwnd"]


def capture_browser_window_png(
    url_hint: str = "",
    *,
    focus: bool = True,
) -> tuple[bytes, dict[str, Any]] | None:
    """Снять PNG окна браузера; meta содержит origin/size для кликов."""
    hwnd = find_browser_hwnd(url_hint=url_hint)
    if not hwnd:
        return None
    if focus:
        _set_foreground(hwnd)
    rect = _window_rect(hwnd)
    if rect is None:
        return None
    left, top, right, bottom = rect
    width = max(0, right - left)
    height = max(0, bottom - top)
    if width < 80 or height < 80:
        return None
    png = _capture_rect_png(left, top, width, height)
    if not png:
        png = _capture_hwnd_printwindow(hwnd, width, height)
    if not png:
        return None
    meta = {
        "capture_mode": "browser_window",
        "origin_x": left,
        "origin_y": top,
        "monitor_count": 1,
        "engine": "win32_window",
        "width": width,
        "height": height,
        "hwnd": int(hwnd),
        "title": _window_title(hwnd),
        "rect": [left, top, right, bottom],
    }
    return png, meta


def foreground_window_info() -> dict[str, Any]:
    """Информация о текущем foreground-окне (для OBSERVE)."""
    if not _is_windows():
        return {"ok": False}
    try:
        user32 = ctypes.windll.user32
        hwnd = int(user32.GetForegroundWindow())
    except Exception:
        return {"ok": False}
    if not hwnd:
        return {"ok": False}
    rect = _window_rect(hwnd)
    return {
        "ok": True,
        "hwnd": hwnd,
        "title": _window_title(hwnd),
        "rect": rect,
    }


def _list_candidate_windows() -> list[dict[str, Any]]:
    """Перечислить видимые top-level окна процессов браузера."""
    try:
        import win32gui
        import win32process
    except Exception:
        return []

    result: list[dict[str, Any]] = []

    def _enum(hwnd: int, _extra: object) -> None:
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = win32gui.GetWindowText(hwnd) or ""
        if not title.strip():
            return
        try:
            _thread_id, pid = win32process.GetWindowThreadProcessId(hwnd)
            name = _process_name(pid)
        except Exception:
            return
        if name not in BROWSER_PROCESS_NAMES:
            return
        rect = _window_rect(hwnd)
        if rect is None:
            return
        left, top, right, bottom = rect
        area = max(0, right - left) * max(0, bottom - top)
        if area < 200 * 200:
            return
        result.append(
            {
                "hwnd": int(hwnd),
                "title": title,
                "process": name,
                "area": area,
                "rect": rect,
            }
        )

    try:
        win32gui.EnumWindows(_enum, None)
    except Exception:
        return []
    return result


def _process_name(pid: int) -> str:
    """Имя exe процесса в lower-case."""
    try:
        import win32api
        import win32con
        import win32process

        handle = win32api.OpenProcess(
            win32con.PROCESS_QUERY_INFORMATION | win32con.PROCESS_VM_READ,
            False,
            pid,
        )
        try:
            return str(win32process.GetModuleFileNameEx(handle, 0)).split("\\")[-1].casefold()
        finally:
            win32api.CloseHandle(handle)
    except Exception:
        return ""


def _window_title(hwnd: int) -> str:
    """Title окна."""
    try:
        import win32gui

        return str(win32gui.GetWindowText(hwnd) or "")
    except Exception:
        return ""


def _window_rect(hwnd: int) -> tuple[int, int, int, int] | None:
    """(left, top, right, bottom) в экранных координатах."""
    try:
        import win32gui

        left, top, right, bottom = win32gui.GetWindowRect(hwnd)
        return int(left), int(top), int(right), int(bottom)
    except Exception:
        return None


def _set_foreground(hwnd: int) -> bool:
    """Попытаться активировать окно (обход ограничений Windows focus)."""
    try:
        import win32con
        import win32gui
        import win32process
        import win32api

        if win32gui.IsIconic(hwnd):
            win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
        # AttachThreadInput трюк: иначе SetForegroundWindow часто игнорируется.
        fg = win32gui.GetForegroundWindow()
        current_tid = win32api.GetCurrentThreadId()
        fg_tid, _pid = win32process.GetWindowThreadProcessId(fg) if fg else (0, 0)
        target_tid, _pid2 = win32process.GetWindowThreadProcessId(hwnd)
        attached_fg = False
        attached_target = False
        if fg_tid and fg_tid != current_tid:
            attached_fg = bool(
                win32process.AttachThreadInput(current_tid, fg_tid, True)
            )
        if target_tid and target_tid != current_tid:
            attached_target = bool(
                win32process.AttachThreadInput(current_tid, target_tid, True)
            )
        try:
            win32gui.BringWindowToTop(hwnd)
            win32gui.SetForegroundWindow(hwnd)
        finally:
            if attached_target:
                win32process.AttachThreadInput(current_tid, target_tid, False)
            if attached_fg:
                win32process.AttachThreadInput(current_tid, fg_tid, False)
        return int(win32gui.GetForegroundWindow()) == int(hwnd)
    except Exception:
        try:
            import win32gui

            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            return False


def _capture_rect_png(left: int, top: int, width: int, height: int) -> bytes | None:
    """BitBlt прямоугольника экрана в PNG."""
    try:
        import win32con
        import win32gui
        import win32ui
        from PySide6.QtGui import QImage
    except Exception:
        return None
    hwnd = win32gui.GetDesktopWindow()
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    save_dc.BitBlt(
        (0, 0),
        (width, height),
        mfc_dc,
        (left, top),
        win32con.SRCCOPY | getattr(win32con, "CAPTUREBLT", 0x40000000),
    )
    bmp_str = bitmap.GetBitmapBits(True)
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    image = QImage(bmp_str, width, height, QImage.Format.Format_RGB32)
    if image.isNull():
        return None
    image = image.copy()
    return _qimage_to_png(image)


def _capture_hwnd_printwindow(hwnd: int, width: int, height: int) -> bytes | None:
    """Fallback: PrintWindow содержимого HWND."""
    try:
        import win32gui
        import win32ui
        from PySide6.QtGui import QImage
    except Exception:
        return None
    hwnd_dc = win32gui.GetWindowDC(hwnd)
    mfc_dc = win32ui.CreateDCFromHandle(hwnd_dc)
    save_dc = mfc_dc.CreateCompatibleDC()
    bitmap = win32ui.CreateBitmap()
    bitmap.CreateCompatibleBitmap(mfc_dc, width, height)
    save_dc.SelectObject(bitmap)
    # PW_RENDERFULLCONTENT = 2
    result = ctypes.windll.user32.PrintWindow(hwnd, save_dc.GetHandleOutput(), 2)
    bmp_str = bitmap.GetBitmapBits(True)
    win32gui.DeleteObject(bitmap.GetHandle())
    save_dc.DeleteDC()
    mfc_dc.DeleteDC()
    win32gui.ReleaseDC(hwnd, hwnd_dc)
    if not result:
        return None
    image = QImage(bmp_str, width, height, QImage.Format.Format_RGB32)
    if image.isNull():
        return None
    return _qimage_to_png(image.copy())


def _qimage_to_png(image: Any) -> bytes | None:
    """QImage → PNG bytes."""
    try:
        from PySide6.QtCore import QByteArray, QBuffer, QIODevice
    except Exception:
        return None
    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not image.save(buffer, "PNG"):
        return None
    raw = bytes(data)
    return raw or None


def _url_host(url: str) -> str:
    """Достать host из url для матчинга title."""
    text = (url or "").strip()
    if not text:
        return ""
    try:
        parsed = urlparse(text if "://" in text else f"https://{text}")
        return (parsed.hostname or "").casefold()
    except Exception:
        return ""


def _is_windows() -> bool:
    """Windows-only helpers."""
    import os

    return os.name == "nt"
