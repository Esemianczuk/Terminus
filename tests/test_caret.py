import io
import json
from types import SimpleNamespace

from desktop.caret import LocalCaretObserver, bounded_rect, caret_from_source


API = SimpleNamespace(ROLE_PASSWORD_TEXT=40, STATE_FOCUSED=1, STATE_VISIBLE=2,
                      STATE_SHOWING=3, DESKTOP_COORDS=0)


class Source:
    def __init__(self, *, password=False, focused=True, end=False):
        self.password, self.focused, self.end = password, focused, end
        self.calls = []

    def getState(self):
        return SimpleNamespace(contains=lambda state: self.focused)

    def getRole(self):
        return 40 if self.password else 60

    def queryText(self):
        assert not self.password
        self.calls.append("queryText")
        return SimpleNamespace(caretOffset=4, getCharacterExtents=self.extents)

    def extents(self, offset, coordinate):
        self.calls.append((offset, coordinate))
        return [0, 0, 0, 0] if self.end and offset == 4 else [200, 300, 8, 20]

    def getText(self, *args):
        raise AssertionError("Caret must never read contents")

    def getName(self):
        raise AssertionError("Caret must never read names")


def test_caret_queries_only_focused_source_geometry_and_no_contents():
    source = Source()
    assert caret_from_source(source, API) == {
        "rect": {"x": 200, "y": 300, "width": 1, "height": 20}, "secure": False}
    assert source.calls == ["queryText", (4, API.DESKTOP_COORDS)]
    end = Source(end=True)
    assert caret_from_source(end, API)["rect"]["x"] == 208
    assert end.calls == ["queryText", (4, 0), (3, 0)]


def test_password_or_unfocused_sources_never_query_text_interface():
    password = Source(password=True)
    assert caret_from_source(password, API) == {"rect": None, "secure": True}
    assert password.calls == []
    unfocused = Source(focused=False)
    assert caret_from_source(unfocused, API) == {"rect": None, "secure": None}
    assert unfocused.calls == []


def test_parent_cache_is_bounded_expires_and_does_not_expose_mutable_state():
    now = [10.]
    observer = LocalCaretObserver(clock=lambda: now[0])
    observer.process = SimpleNamespace(poll=lambda: None)
    payload = {"rect": {"x": -200, "y": 300, "width": 1, "height": 20}, "secure": False, "available": True}
    assert observer._accept(json.dumps(payload))
    assert observer.snapshot()["rect"] == payload["rect"]
    observer.snapshot()["rect"]["x"] = 999
    assert observer.snapshot()["rect"]["x"] == -200
    now[0] += 2.8
    assert observer.snapshot()["rect"] is None
    assert observer.snapshot()["secure"] is None
    assert observer.snapshot()["fresh"] is False
    assert not observer._accept('{"available":true,"secure":1}')
    assert not observer._accept(json.dumps({**payload, "offset": 100}))
    assert not observer._accept("x" * 513)
    assert observer._accept(json.dumps({**payload, "secure": True}))
    assert observer.snapshot()["rect"] is None


def test_rect_validation_rejects_unbounded_or_nonfinite_or_extra_fields():
    valid = {"x": 1, "y": 2, "width": 1, "height": 20}
    assert bounded_rect(valid) == valid
    for invalid in ({**valid, "x": float("nan")}, {**valid, "height": 1000000},
                    {**valid, "x": 200000}, {**valid, "width": False}, {**valid, "offset": 1}):
        assert bounded_rect(invalid) is None


def test_missing_helper_is_optional_and_oversize_pipe_does_not_accumulate():
    def unavailable(*args, **kwargs):
        raise FileNotFoundError()
    observer = LocalCaretObserver(popen=unavailable)
    assert observer.start() is False
    assert observer.snapshot()["available"] is False
    observer.close()
    observer.process = SimpleNamespace(stdout=io.BytesIO(b"x" * 100000), poll=lambda: None)
    observer._read()
    assert observer.process.stdout.tell() == 513
    assert observer.snapshot()["available"] is False


def test_start_and_close_reap_only_the_owned_helper():
    class Process:
        stdout = io.BytesIO(b"")
        returncode = None
        terminated = False
        def poll(self):
            return self.returncode
        def terminate(self):
            self.terminated = True
        def wait(self, timeout):
            self.returncode = 0
    process = Process()
    calls = []
    def popen(args, **kwargs):
        calls.append((args, kwargs))
        return process
    observer = LocalCaretObserver(popen=popen)
    assert observer.start()
    assert calls[0][0][0] == "/usr/bin/python3"
    assert calls[0][0][-1] == "--worker"
    observer.close()
    assert process.terminated and process.returncode == 0
    assert process.stdout.closed
    assert observer.process is observer.reader is None
