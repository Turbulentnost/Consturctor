@echo off
cd /d "%~dp0\.."
python scripts\build_installer.py %*
