from datetime import datetime
from xml.etree import ElementTree as ET

from app.tools.onec.dok_rework import apply_checkup_return
from app.tools.onec.dok_soap import DM_NS, xml_text


def _checkup() -> ET.Element:
    checkup = ET.Element(f"{{{DM_NS}}}task")
    ET.SubElement(checkup, f"{{{DM_NS}}}checkResults")
    return checkup


def test_return_history_keeps_reviewer_comment():
    checkup = _checkup()
    apply_checkup_return(
        checkup,
        datetime(2026, 10, 28, 18, 0),
        comment="Нет подписи директора.\nПриложите скан.",
    )
    result = checkup.find(f"{{{DM_NS}}}checkResults")

    assert xml_text(result, "m:returned") == "true"
    assert xml_text(result, "m:checkComment") == "Нет подписи директора.\nПриложите скан."


def test_return_without_comment_keeps_due_note():
    checkup = _checkup()
    apply_checkup_return(checkup, datetime(2026, 10, 28, 18, 0), comment="  ")
    result = checkup.find(f"{{{DM_NS}}}checkResults")

    assert xml_text(result, "m:checkComment") == "Новый срок исполнения: 28.10.2026 18:00:00"
