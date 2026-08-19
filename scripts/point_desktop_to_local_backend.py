#!/usr/bin/env python3
"""Point turbobot desktop to local gateway (127.0.0.1:7812)."""
from __future__ import annotations

import sys

LOCAL = "http://127.0.0.1:7812"


def main() -> int:
    try:
        from PySide6.QtCore import QCoreApplication, QSettings
    except ImportError:
        print("PySide6 required: pip install PySide6")
        return 1

    app = QCoreApplication(sys.argv)
    settings = QSettings("turbobot", "desktop")
    settings.setValue("server/backend_url", LOCAL)
    settings.remove("session/access_token")
    settings.setValue("session/remember", False)
    settings.sync()
    print(f"Desktop backend -> {LOCAL}")
    print("Session cleared — log in again in turbobot.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
