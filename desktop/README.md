# turbobot Desktop

Нативное приложение на **PySide6** — то, что видит пользователь.

Общая схема платформы: [корневой README](../README.md).

## Как работает

1. Одно окно **1280×800**: экран входа и основная оболочка меняются внутри него.
2. Вход — зелёно-чёрный glass-UI; ФИО ищется через `GET /api/v1/auth/users?search=...`.
3. «Войти» → `POST /api/v1/auth/login` → JWT + профиль (ФИО, отдел).
4. После входа — сайдбар (референс glass/emerald):
   - **Создать агента** (`+`) — стартовая вкладка;
   - **Мои агенты**;
   - **KPI**;
   - белый активный пункт с анимацией сдвига.
5. В шапке контента: ФИО, отдел, статус ERP, «Выйти».

Desktop **не** подключается к SQL Server напрямую — только к backend по HTTP.

## Как должно работать дальше

Вкладки сейчас — каркас. Дальше: полноценный конструктор агента, список агентов и KPI; вход и отдел из 1С остаются базой доступа.

## Запуск

```powershell
# Backend должен уже слушать порт 7812
cd c:\Users\testii\Downloads\projects_Mangasaryan\turbobot\desktop
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

Конфиг (`.env`):

```env
BACKEND_URL=http://127.0.0.1:7812
```

Live-доступ к 1С через COMConnector настраивается на стороне desktop (`ONEC_COM_SERVER`, `ONEC_COM_REF`, `ERP_LOGIN`, `ERP_PASSWORD`, `ONEC_COM_PROGID`), а `ERP_LOGIN` / `ERP_PASSWORD` можно оставить пустыми, если ваша база пускает без них. Backend по-прежнему остаётся точкой для auth/оркестрации и server-side OData/SQL.

## Сборка Windows exe

```powershell
cd Constructor
python desktop\build_exe.py
```

Скрипт собирает onedir-дистрибутив в `desktop/dist/ConstructorDesktop`. Переносите **всю папку**, не один файл:

- `ConstructorDesktop.exe` — GUI без установленного Python.
- `ConstructorComWorker.exe` — консольный процесс для COM (Outlook/1С) и `code.run_python`. Не запускайте вручную.
- `.env` рядом с exe — `BACKEND_URL` на LAN IP машины сборки (`http://<ip>:7812`), не `127.0.0.1`.
- `tools/` — web_search, site_browser, roseltorg.
- `ms-playwright/` — Chromium для Playwright, если он был в кэше при сборке.

На целевом ПК нужны установленный Outlook и 32-bit `V83.COMConnector` (плюс `SysWOW64\cscript.exe`). Backend должен быть запущен на адресе из `.env`.

## Установщик Windows

После `python desktop\build_exe.py`:

```powershell
python desktop\installer\build_installer.py
```

Результат: `desktop/dist/ConstructorDesktop-Setup.exe`.

- Ставит в `%LOCALAPPDATA%\ConstructorDesktop` без прав администратора.
- Ярлыки в меню Пуск и на рабочем столе.
- `BACKEND_URL` — LAN IP машины сборки, не `127.0.0.1`. При обновлении пароли в `.env` сохраняются, адрес сервера переписывается.
- В Setup попадает текущий `.env` из сборки — не выкладывайте установщик в общий доступ.
