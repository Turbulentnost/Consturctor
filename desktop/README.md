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

Подключение к 1С настраивается только на стороне [backend](../backend/README.md) (`ERP_SQL_SERVER=ii1`).
