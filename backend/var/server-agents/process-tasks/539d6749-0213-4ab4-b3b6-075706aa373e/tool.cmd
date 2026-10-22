@echo off
set "PYTHONPATH=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend"
set "PROCESS_AGENT_WORKSPACE=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend\var\server-agents\process-tasks\539d6749-0213-4ab4-b3b6-075706aa373e"
set PYTHONIOENCODING=utf-8
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m app.services.server_agents %*
