@echo off
set "PYTHONPATH=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend"
set "PROCESS_AGENT_WORKSPACE=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend\var\server-agents\process-tasks\0941f7b3-c5bb-434d-80e1-e5d34ab4475c"
set PYTHONIOENCODING=utf-8
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m app.services.server_agents %*
