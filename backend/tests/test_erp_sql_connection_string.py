from app.clients import erp_sql


def test_driver17_omits_encrypt_no(monkeypatch) -> None:
    monkeypatch.setattr(erp_sql.settings, "erp_sql_driver", "ODBC Driver 17 for SQL Server")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_server", "ii1")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_database", "erp_pm")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_encrypt", "no")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_timeout", 45)
    monkeypatch.setattr(erp_sql.settings, "erp_sql_trusted_connection", True)
    monkeypatch.setattr(erp_sql.settings, "erp_sql_user", "")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_password", "")

    dsn = erp_sql._build_connection_string()

    assert "Encrypt=" not in dsn
    assert "Connection Timeout=45" in dsn
    assert "Trusted_Connection=yes" in dsn
    assert "PWD=" not in dsn


def test_driver18_keeps_encrypt(monkeypatch) -> None:
    monkeypatch.setattr(erp_sql.settings, "erp_sql_driver", "ODBC Driver 18 for SQL Server")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_server", "ii1")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_database", "erp_pm")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_encrypt", "no")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_timeout", 45)
    monkeypatch.setattr(erp_sql.settings, "erp_sql_trusted_connection", True)
    monkeypatch.setattr(erp_sql.settings, "erp_sql_user", "")
    monkeypatch.setattr(erp_sql.settings, "erp_sql_password", "")

    dsn = erp_sql._build_connection_string()

    assert "Encrypt=no" in dsn
    assert "TrustServerCertificate=yes" in dsn
    assert "Connection Timeout=45" in dsn
