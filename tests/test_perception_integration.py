"""Passive perception boundaries. No devices, real input or network are used."""
from copy import deepcopy
import json
import os
from pathlib import Path
import time
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets

from desktop import overlay


ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def resident(application, monkeypatch, tmp_path):
    class Client(QtCore.QObject):
        snapshot = QtCore.Signal(dict)
        disconnected = QtCore.Signal(str)

        def __init__(self):
            super().__init__()
            self.data_dir = tmp_path
            self.events = []

        def send_event(self, kind, **fields):
            self.events.append((kind, fields))

    clock = SimpleNamespace(now=100., wall=1_700_000_100.)
    monkeypatch.setattr(overlay, "time", SimpleNamespace(monotonic=lambda: clock.now,
                                                        time=lambda: clock.wall,
                                                        perf_counter=time.perf_counter))
    monkeypatch.setattr(overlay.Overlay, "load_art", lambda self: None)
    monkeypatch.setattr(overlay.Overlay, "render_frame", lambda self, now: None)
    monkeypatch.setattr(QtWidgets.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    client = Client()
    widget = overlay.Overlay(client, ROOT / "web/assets", 1.)
    for timer in (widget.animation, widget.asset_timer, widget.presence_timer, widget.awareness_timer):
        timer.stop()
    widget.connected = True
    widget.last_seen = clock.now
    widget.state = {"behavior": "idle", "revision": 1}

    def receive(*, phase="active", level=.7, sequence=1, age=0., elapsed=0., **extra):
        clock.now += elapsed
        clock.wall += elapsed
        widget.last_seen = clock.now
        snapshot = {"available": True, "enabled": True, "observed_at": clock.now,
                    "focused_window": {"x": 10, "y": 20, "width": 900, "height": 600, "own": False},
                    "typing": {"active": phase == "active", "last_at": clock.now-age,
                               "sequence": sequence, "rate": 5., "pulse": .7},
                    "bout": {"phase": phase, "level": level, "sequence": sequence,
                             "duration_s": 4., "pause_age_s": age},
                    "source": "x11-xinput2", "permission": "local-observation", **extra}
        widget.receive_awareness(deepcopy(snapshot))
        return snapshot

    yield SimpleNamespace(widget=widget, client=client, clock=clock, receive=receive)
    widget.close()
    widget.deleteLater()
    application.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_sustained_typing_escalates_before_the_regular_refresh_interval(resident):
    resident.receive(level=.1)
    resident.receive(level=.8, elapsed=1.5)
    events = resident.client.events
    assert [event[1]["intensity"] for event in events] == [.16, .8]
    resident.receive(level=.9, elapsed=1)
    assert len(events) == 2
    resident.receive(level=.9, elapsed=7.1)
    assert len(events) == 3


def test_stale_active_phase_and_stale_provider_snapshot_emit_nothing(resident):
    resident.receive(age=20)
    resident.receive(observed_at=resident.clock.now-10)
    assert resident.client.events == []


@pytest.mark.parametrize("phase", ["active", "pause"])
def test_secure_entry_cannot_emit_typing_or_pause_even_with_a_heavy_bout(resident, phase):
    resident.receive(phase=phase, age=3 if phase == "pause" else 0, secure_entry=True,
                     caret={"x": 30, "y": 40, "width": 1, "height": 18})
    assert resident.client.events == []
    assert resident.widget.awareness["typing"] is None
    assert resident.widget.awareness["caret"] is None


def test_pause_is_once_per_bout_and_preserves_actual_observation_time(resident):
    resident.receive(level=.8)
    resident.receive(phase="pause", age=2.8, elapsed=4)
    resident.receive(phase="pause", age=3.8, elapsed=1)
    resident.receive(phase="pause", age=7.8, elapsed=4)
    pauses = [fields for _, fields in resident.client.events if fields["context"] == "typing-pause"]
    assert len(pauses) == 1
    assert pauses[0]["timestamp"] == pytest.approx(1_700_000_101.2)


def test_geometry_text_and_raw_signals_stay_out_of_core_events(resident):
    sentinel = "NEVER_ENTER_EVENT_HISTORY"
    snapshot = resident.receive(
        focused_window={"x": 300, "y": 100, "width": 800, "height": 500,
                        "own": False, "title": sentinel, "pid": 1234},
        text=sentinel, keycodes=[sentinel], audio=sentinel,
        pointer={"available": True, "x": .31, "y": .72, "motion": .8, "raw": sentinel},
        windows={"available": True, "count": 3, "coverage": .6,
                 "rects": [{"x": .1, "y": .2, "width": .4, "height": .5, "title": sentinel}]},
        microphone={"available": True, "in_use": True, "audio": sentinel},
    )
    assert snapshot["text"] == sentinel  # The deliberately bad fixture really contains it.
    assert len(resident.client.events) == 4
    for kind, fields in resident.client.events:
        assert kind == "activity"
        assert set(fields) == {"context", "source", "intensity", "timestamp"}
        assert fields["source"] == "live"
        assert 0 <= fields["intensity"] <= 1
    serialized = json.dumps({"awareness": resident.widget.awareness, "events": resident.client.events})
    assert sentinel not in serialized
    assert "keycodes" not in serialized
    assert "audio" not in serialized
    assert resident.widget.awareness["pointer"]["x"] == .31
    assert resident.widget.awareness["windows"]["rects"][0]["width"] == .4


def test_native_window_has_no_keyboard_focus_or_grab(resident):
    widget = resident.widget
    assert widget.windowFlags() & QtCore.Qt.WindowDoesNotAcceptFocus
    assert widget.focusPolicy() == QtCore.Qt.NoFocus
    assert widget.testAttribute(QtCore.Qt.WA_ShowWithoutActivating)
    assert QtWidgets.QWidget.keyboardGrabber() is None
    assert widget.awareness_provider is None


def test_all_passive_sources_share_a_rolling_budget_and_never_block_manual_touch(resident):
    sent_at = []
    original_send = resident.client.send_event
    def capture(kind, **fields):
        sent_at.append(resident.clock.now)
        original_send(kind, **fields)
    resident.client.send_event = capture
    for index in range(180):
        resident.receive(phase="pause" if index % 2 else "active", sequence=index,
                         age=2. if index % 2 else 0., elapsed=.5,
                         pointer={"available": True, "x": .4, "y": .6, "motion": .9},
                         windows={"available": True, "count": 5, "coverage": .8, "rects": []},
                         microphone={"available": True, "in_use": index % 2 == 0})
    assert len(sent_at) > 18  # The budget replenishes across the minute boundary.
    assert resident.widget.passive_events_dropped > 0
    assert {fields["context"] for _, fields in resident.client.events} == {
        "typing", "typing-pause", "pointer", "desktop", "microphone"}
    for now in sent_at:
        assert sum(0 <= now-stamp < 60 for stamp in sent_at) <= 18
    before = len(resident.client.events)
    resident.client.send_event("poke", source="manual", intensity=.65)
    assert len(resident.client.events) == before + 1
    assert resident.client.events[-1][0] == "poke"


def test_exhausted_passive_budget_expires_without_replaying_a_backlog(resident):
    resident.widget.passive_event_budget = [resident.clock.now] * 18
    signals = {"pointer": {"available": True, "x": .3, "y": .5, "motion": 1.},
               "windows": {"available": True, "count": 2, "coverage": .5, "rects": []},
               "microphone": {"available": True, "in_use": True}}
    resident.receive(**signals)
    resident.receive(elapsed=59.9, **signals)
    assert resident.client.events == []
    assert resident.widget.passive_events_dropped == 8
    resident.receive(elapsed=.2, **signals)
    # Only the four current cues are delivered. The eight dropped observations
    # do not become queued input and cannot generate a later request storm.
    assert len(resident.client.events) == 4
    assert len(resident.widget.passive_event_budget) == 4
    assert all(fields["timestamp"] == resident.clock.wall for _, fields in resident.client.events)


@pytest.mark.parametrize("flag", ["available", "enabled"])
def test_unavailable_or_disabled_provider_cannot_send_activity(resident, flag):
    resident.receive(**{flag: False},
                     pointer={"available": True, "x": .2, "y": .3, "motion": .9},
                     windows={"available": True, "count": 2, "coverage": .8, "rects": []},
                     microphone={"available": True, "in_use": True})
    assert resident.client.events == []


def test_event_rate_limit_does_not_disconnect_or_schedule_retries(application, monkeypatch, tmp_path):
    from PySide6 import QtNetwork
    client = overlay.CoreClient("http://127.0.0.1:1", tmp_path)
    failures, deleted, scheduled = [], [], []
    client.disconnected.connect(failures.append)
    monkeypatch.setattr(QtCore.QTimer, "singleShot", lambda *args: scheduled.append(args))
    reply = SimpleNamespace(attribute=lambda _: 429,
                            error=lambda: QtNetwork.QNetworkReply.NetworkError.UnknownContentError,
                            deleteLater=lambda: deleted.append(True))
    for _ in range(30):
        client._finish_event(reply)
    assert failures == []
    assert scheduled == []  # No immediate poll or replay loop on a busy core.
    assert client.rate_limited_events == len(deleted) == 30
    assert client.poll_reply is None
    # Real connection failures retain their existing disconnection behavior.
    reply.attribute = lambda _: 503
    client._finish_event(reply)
    assert len(failures) == 1
    assert scheduled == []
    client.deleteLater()
