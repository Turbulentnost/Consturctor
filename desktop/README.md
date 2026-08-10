# Constructor Desktop

Нативное приложение на **PySide6** — то, что видит пользователь.

Общая схема платформы: [корневой README](../README.md).

## Как работает

1. При старте открывается окно **входа**.
2. Поле ФИО ищет совпадения через backend: `GET /api/v1/auth/users?search=...` (данные из 1С `erp_pm`).
3. По кнопке «Войти» desktop отправляет ФИО и пароль на `POST /api/v1/auth/login`.
4. Backend проверяет пароль в 1С и возвращает JWT + профиль (ФИО, **отдел**).
5. Открывается главное окно:
   - ФИО и отдел;
   - статус backend / ERP / LLM (`GET /health`, при необходимости `GET /api/v1/auth/me`);
   - «Выйти» — сброс токена и возврат на экран входа.

Desktop **не** подключается к SQL Server напрямую — только к backend по HTTP.

## Как должно работать дальше

Сейчас после входа — каркас (профиль + статус). Дальше здесь должен появиться конструктор ИИ-агента: создание/редактирование агента, загрузка инструкций, вызовы LLM/VLM через backend, запуск и просмотр результатов. Вход и привязка к отделу из 1С остаются базой доступа.

## Запуск

```powershell
# Backend должен уже слушать порт 7812
cd c:\Users\testii\Downloads\projects_Mangasaryan\Constructor\desktop
python -m pip install -r requirements.txt
copy .env.example .env
python main.py
```

Конфиг (`.env`):

```env
BACKEND_URL=http://127.0.0.1:7812
```

Подключение к 1С настраивается только на стороне [backend](../backend/README.md) (`ERP_SQL_SERVER=ii1`).
