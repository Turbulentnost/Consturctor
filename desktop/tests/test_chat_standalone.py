from PySide6.QtWidgets import QApplication

from app.api_client import ApiClient, UserProfile
from app.chat.page import ChatPage


def _ensure_app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_detached_chat_hides_dialog_list() -> None:
    _ensure_app()
    page = ChatPage(ApiClient("http://127.0.0.1:9"))
    page.set_user(UserProfile(id="u1", fio="Тест"))
    assert page._left_wrap.isHidden()
    page.set_standalone(True)
    assert page._left_wrap.isHidden()
    page.set_standalone(False)
    assert page._left_wrap.isHidden()
    page._poll.stop()


def test_support_keeps_list_when_docked() -> None:
    _ensure_app()
    page = ChatPage(ApiClient("http://127.0.0.1:9"))
    page.set_user(UserProfile(id="u2", fio="Поддержка", is_support=True))
    assert not page._left_wrap.isHidden()
    page.set_standalone(True)
    assert not page._left_wrap.isHidden()
    page.set_standalone(False)
    assert not page._left_wrap.isHidden()
    page._poll.stop()
