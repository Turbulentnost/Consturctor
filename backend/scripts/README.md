# Экспорт пользователей 1С из erp_pm (только чтение)

Утилита: читает `v8users` из SQL Server базы **erp_pm** (1С:ERP) и пишет логин, отображаемое имя, email (если найден), **отдел**, OSName и hex поля `Data`.

## Важно

- **Никаких записей в БД** — только `SELECT`.
- Открытых паролей в 1С нет: в файле — hex поля `Data`.
- Отдел берётся из справочников `_Reference366` (сотрудник) + `_Reference513` (подразделение).
- База `erp_pm` **не** является БД Constructor.
- Подключайтесь к внутреннему хосту `ii1` (`192.168.1.157`), не к `localhost`.
  Сырой IP с Windows Auth обычно не работает (ошибка 18452).

## Запуск

```powershell
cd c:\Users\testii\Downloads\projects_Mangasaryan\Constructor\backend\scripts
copy .env.example .env
# при необходимости отредактируйте .env

python -m pip install pyodbc python-dotenv
python export_users.py
```

Результат: `backend/scripts/exports/erp_pm_users_export.txt` (UTF-8 BOM, TSV).

## Проверка пароля

Алгоритм: [`../tools/onec/password.py`](../tools/onec/password.py). Тот же модуль использует backend при `POST /api/v1/auth/login`.

```powershell
python verify_password.py --sql --server 192.168.1.157 --user "Мангасарян" --password "..."
```

## Права

Рекомендуется учётная запись с ролью `db_datareader` на `erp_pm`.
