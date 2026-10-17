"""The retired text accessibility integration must remain inert."""
import inspect
from desktop.caret import LocalCaretObserver


def test_retired_caret_observer_never_starts_a_helper_or_queries_text():
    def forbidden(*_, **__):
        raise AssertionError("No helper or text interface should be opened")
    observer = LocalCaretObserver(popen=forbidden)
    assert observer.start() is False
    assert observer.process is observer.reader is None
    assert observer.snapshot()["available"] is False
    assert observer.snapshot()["rect"] is None
    observer.close()
    source = inspect.getsource(inspect.getmodule(LocalCaretObserver))
    for forbidden_name in ("queryText", "getCharacterExtents", "pyatspi", "subprocess", "getText", "registerEventListener"):
        assert forbidden_name not in source
