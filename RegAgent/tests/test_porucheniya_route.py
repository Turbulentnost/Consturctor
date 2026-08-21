from app.tools.porucheniya_route import reroute_if_porucheniya


def test_reroute_search_documents_porucheniya() -> None:
    name, args = reroute_if_porucheniya(
        "onec.search_documents",
        {"query": "Документ.ТД_Поручения", "max_results": 20},
    )
    assert name == "onec.docflow_tasks"
    assert args["limit"] == 20
    assert "max_results" not in args


def test_keep_unrelated_search() -> None:
    name, args = reroute_if_porucheniya(
        "onec.search_documents",
        {"query": "входящая корреспонденция"},
    )
    assert name == "onec.search_documents"
    assert args["query"] == "входящая корреспонденция"


def test_keep_docflow_tool() -> None:
    name, args = reroute_if_porucheniya("onec.docflow_tasks", {"only_open": True})
    assert name == "onec.docflow_tasks"
    assert args["only_open"] is True
