"""Finite, unhurried reaching. These fixtures never contact a live core."""
import os
from pathlib import Path
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtWidgets

from desktop import overlay
from terminus.core import Organism


def test_reach_has_slow_attack_a_real_hold_and_a_longer_soft_return():
    envelope = overlay.reach_envelope
    assert envelope(0) == envelope(1) == 0
    assert envelope(.15) == pytest.approx(.5)
    assert all(envelope(p) == 1 for p in (.30, .35, .45, .55))
    assert envelope(.775) == pytest.approx(.5)
    assert envelope(.95) < .02
    values = [envelope(index / 1000) for index in range(1001)]
    assert all(0 <= v <= 1 for v in values)
    assert all(a <= b for a, b in zip(values[:300], values[1:301]))
    assert all(a >= b for a, b in zip(values[550:], values[551:]))
    # Smooth endpoints and hold boundaries cannot kick the arm's velocity.
    epsilon = .00001
    for point in (0, .30, .55, 1):
        assert abs(envelope(min(1, point+epsilon))-envelope(max(0, point-epsilon))) / epsilon < .01


def test_core_inspection_and_its_visual_phases_are_finite_without_queued_revisit_interruptions():
    creature = Organism(now=0)
    creature.data["behavior"] = "inspect"
    creature._gesture("tendril-inspect", 1, target_id="self")
    gesture = creature.data["gesture"].copy()
    assert gesture["duration"] == 10.8
    assert gesture["duration"] * .30 == pytest.approx(3.24)
    assert gesture["duration"] * .25 == pytest.approx(2.70)
    assert gesture["duration"] * .45 == pytest.approx(4.86)
    creature.data["ethology"]["next_revisit_at"] = 2
    creature.tick(2)
    assert creature.data["gesture"] == gesture
    assert creature.data["ethology"]["next_revisit_at"] == pytest.approx(13.8)
    creature.tick(12)
    assert creature.data["gesture"] is None
    assert creature.data["events_seen"] == creature.model.updates == 0


@pytest.fixture(scope="module")
def application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def resident(application, monkeypatch, tmp_path):
    class Client(QtCore.QObject):
        snapshot = QtCore.Signal(dict)
        disconnected = QtCore.Signal(str)
        data_dir = tmp_path

        def send_event(self, *args, **kwargs):
            pytest.fail("Geometry fixtures must not emit observations")

    monkeypatch.setattr(overlay.Overlay, "load_art", lambda self: None)
    monkeypatch.setattr(overlay.Overlay, "render_frame", lambda self, now: None)
    monkeypatch.setattr(QtWidgets.QSystemTrayIcon, "isSystemTrayAvailable", lambda: False)
    client = Client()
    widget = overlay.Overlay(client, Path(__file__).resolve().parents[1] / "web/assets", 1.)
    for timer in (widget.animation, widget.asset_timer, widget.presence_timer, widget.awareness_timer):
        timer.stop()
    widget.connected = True
    widget.last_seen = overlay.time.monotonic()
    widget.creature_rect = QtCore.QRectF(100, 30, 150, 180)
    points = {"attention": QtCore.QPointF(175, 270), "left-a": QtCore.QPointF(20, 260),
              "left-b": QtCore.QPointF(35, 275), "right": QtCore.QPointF(300, 260)}
    widget.state = {"attention": "attention", "nodes": [{"id": key, "activation": level}
                    for key, level in (("attention", .9), ("left-a", .6), ("left-b", .5), ("right", .4))]}
    monkeypatch.setattr(widget, "pose", lambda now: {"kind": "tendril-inspect", "flight": 0., "facing": 1.,
                        "amplitude": 0., "gesture": .5, "stretch": 0., "curl": 0., "tilt": 0.,
                        "flight_x": 0., "flight_y": 0., "typing_phase": 0., "typing": 0.})
    yield SimpleNamespace(widget=widget, points=points, now=widget.last_seen)
    widget.close()
    widget.deleteLater()
    application.sendPostedEvents(None, QtCore.QEvent.DeferredDelete)


def test_support_contacts_ignore_small_rank_swaps_and_linger_before_a_salient_handoff(resident):
    widget, points, now = resident.widget, resident.points, resident.now
    def targets(when):
        return [key for key, _, _ in widget.tendril_geometry(points, when)]
    assert "left-a" in targets(now)
    widget.state["nodes"][2]["activation"] = .65
    assert "left-a" in targets(now+2)
    widget.state["nodes"][2]["activation"] = .95
    # Reset the previous contact's minimum linger to make the boundary explicit.
    widget.tendril_contacts[-1]["until"] = now+3
    assert "left-a" in targets(now+2.9)
    assert "left-b" in targets(now+3.1)
    for key, curve, _ in widget.tendril_geometry(points, now+3.2):
        assert curve.pointAtPercent(1) == points[key]


def test_a_reaching_gesture_keeps_its_authoritative_target_during_global_attention_changes(resident, monkeypatch):
    widget, points, now = resident.widget, resident.points, resident.now
    widget.state["attention"] = "left-b"
    monkeypatch.setattr(widget, "gesture", lambda _: {"kind": "tendril-inspect", "target_id": "attention"})
    contacts = widget.tendril_geometry(points, now)
    assert contacts[0][0] == "attention"
    assert contacts[0][1].pointAtPercent(1) == points["attention"]
