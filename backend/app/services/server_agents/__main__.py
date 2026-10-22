import os
import sys

from app.services.server_agents import process_tools
from app.services.server_agents.sources import LOOKUPS, _emit, main

if sys.argv[1:2] and sys.argv[1] in process_tools.COMMANDS:
    raise SystemExit(process_tools.main(sys.argv[1:]))
if not sys.argv[1:2] or sys.argv[1] not in LOOKUPS:
    in_run = bool(os.environ.get(process_tools.WORKSPACE_ENV))
    commands = sorted(LOOKUPS | (process_tools.COMMANDS if in_run else set()))
    hint = ". Поиск — строка, task и news — путь к JSON" if in_run else " и строка поиска"
    _emit({"ok": False, "error": f"Команды: {', '.join(commands)}{hint}"})
    raise SystemExit(2)
raise SystemExit(main())
