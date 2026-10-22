@echo off
set "PYTHONPATH=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend"
set "PROCESS_AGENT_WORKSPACE=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend\var\server-agents\process-tasks\341ee880-aed8-426c-b619-ceae2464d1ac"
set PYTHONIOENCODING=utf-8
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m app.services.server_agents %*
