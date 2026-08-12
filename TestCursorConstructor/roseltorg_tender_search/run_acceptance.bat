@echo off
REM Приёмочная проверка: поиск по 5 разнотипным ключевым словам.
REM Открывает report.xlsx для ручной сверки с карточками на roseltorg.ru.
call "%~dp0run.bat" --acceptance
