"""Точка входа DesktopLauncher.exe — lazy-start desktop host (:7829)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def main() -> None:
    from platform_desktop_launcher.main import main as launcher_main

    launcher_main()


if __name__ == "__main__":
    main()
