from app.services.onec_tools import _odata_get

ref = "a4e88520-08dd-11f1-97a0-6cb31113810e"
dept = "bd7b5184-9f9c-11e4-80da-001e67112509"
user = "d82142c0-a801-11f0-9719-6cb31113810c"
paths = [
    f"Document_ТД_ВходящаяКорреспонденция(guid'{ref}')/КомуПодразделениеСсылка",
    f"Catalog_ПодразделенияОрганизаций(guid'{dept}')?$select=Description",
    f"Catalog_СтруктураПредприятия(guid'{dept}')?$select=Description",
    f"Catalog_Пользователи(guid'{user}')?$select=Description",
]
for path in paths:
    try:
        data = _odata_get({"path": path})["data"]
        if isinstance(data, dict) and "value" in data:
            data = (data.get("value") or [{}])[0]
        desc = ""
        if isinstance(data, dict):
            desc = str(data.get("Description") or data.get("Наименование") or "")
        print("ok", path.split("(")[0], desc.encode("unicode_escape").decode()[:120])
    except Exception as exc:
        print("fail", path.split("(")[0], str(exc)[:120])
