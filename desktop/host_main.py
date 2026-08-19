"""Точка входа DesktopHost.exe — инструменты агента на этом ПК (:7830)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from platform_desktop_host.main import main as host_main

    host_main()


if __name__ == "__main__":
    main()
