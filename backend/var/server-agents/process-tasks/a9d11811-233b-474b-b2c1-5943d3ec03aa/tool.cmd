@echo off
set "PYTHONPATH=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend"
set "PROCESS_AGENT_WORKSPACE=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend\var\server-agents\process-tasks\a9d11811-233b-474b-b2c1-5943d3ec03aa"
set PYTHONIOENCODING=utf-8
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m app.services.server_agents %*
