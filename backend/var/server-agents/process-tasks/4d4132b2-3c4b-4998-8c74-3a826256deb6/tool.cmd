@echo off
set "PYTHONPATH=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend"
set "PROCESS_AGENT_WORKSPACE=C:\Users\User\Downloads\Turbo-don\projects\Constructor\Consturctor\backend\var\server-agents\process-tasks\4d4132b2-3c4b-4998-8c74-3a826256deb6"
set PYTHONIOENCODING=utf-8
"C:\Users\User\AppData\Local\Programs\Python\Python312\python.exe" -m app.services.server_agents %*
