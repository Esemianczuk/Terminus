"""Persistent graph delegates and smooth styling without hardware rendering."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6 import QtCore, QtQml, QtWidgets

from desktop.gpu import ROOT, SceneRows


@pytest.fixture(scope="module")
def application():
    return QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


def test_moving_primitives_emit_data_changes_without_resetting_or_reinserting_rows(application):
    model = SceneRows(72)
    resets, inserts, removes, changes = [], [], [], []
    model.modelReset.connect(lambda: resets.append(True))
    model.rowsInserted.connect(lambda _, first, last: inserts.append((first,last)))
    model.rowsRemoved.connect(lambda _, first, last: removes.append((first,last)))
    model.dataChanged.connect(lambda first,last,roles: changes.append((first.row(),last.row(),roles)))
    assert model.update([{"id": str(i), "x": i} for i in range(3)])
    persistent = QtCore.QPersistentModelIndex(model.index(0,0))
    for frame in range(1,20):
        assert model.update([{"id": str(i), "x": i+frame*.1} for i in range(3)])
    assert resets == [] and removes == [] and inserts == [(0,2)]
    assert len(changes) == 19
    assert all(first == 0 and last == 2 and roles == [model.EntryRole] for first,last,roles in changes)
    assert persistent.isValid() and persistent.row() == 0
    assert model.inserted == 3 and model.removed == 0
    assert not model.update([{"id": str(i), "x": i+19*.1} for i in range(3)])
    assert len(changes) == 19


def test_topology_changes_only_add_or_remove_the_changed_tail(application):
    model = SceneRows(3)
    model.update([{"x": 1}, {"x": 2}])
    first = QtCore.QPersistentModelIndex(model.index(0,0))
    second = QtCore.QPersistentModelIndex(model.index(1,0))
    model.update([{"x": 3}])
    assert first.isValid() and not second.isValid()
    assert model.rowCount() == 1
    model.update([{"x": 3}, {"x": 4}, {"x": 5}, {"x": 6}])
    assert model.rowCount() == 3 and model.inserted == 4 and model.removed == 1
    value = model.data(model.index(0,0), model.EntryRole)
    value["x"] = 999
    assert model.data(model.index(0,0), model.EntryRole) == {"x": 3}
    assert model.data(QtCore.QModelIndex(), model.EntryRole) is None
    assert model.rowCount(model.index(0,0)) == 0


def find_visual(item, name):
    if item.objectName() == name:
        return item
    for child in item.childItems():
        found = find_visual(child,name)
        if found is not None:
            return found
    return None


def test_real_qml_retains_graph_delegates_and_blends_focus_contact_strength(application):
    engine = QtQml.QQmlEngine()
    component = QtQml.QQmlComponent(engine, QtCore.QUrl.fromLocalFile(str(ROOT / "desktop/qml/CreatureScene.qml")))
    root = component.create()
    assert root is not None, [error.toString() for error in component.errors()]
    root.setProperty("width",440)
    root.setProperty("height",340)
    nodes, edges = SceneRows(72,root), SceneRows(320,root)
    root.setProperty("nodes",nodes)
    root.setProperty("edges",edges)
    node = {"index": 0, "x": 20., "y": 30., "activation": .2, "focus": False, "contact": False}
    edge = {"index": 0, "x0": 20., "y0": 30., "x1": 60., "y1": 50., "cx": 40., "cy": 35.,
            "activation": .2, "weight": .3, "focus": False}
    nodes.update([node])
    edges.update([edge])
    application.processEvents()
    first_node, first_edge = find_visual(root,"graph-node-0"), find_visual(root,"graph-edge-0")
    assert first_node is not None and first_edge is not None
    assert first_node.property("radius") == pytest.approx(1.7)
    for frame in range(1,10):
        nodes.update([{**node,"x":20+frame,"focus":True,"contact":True,
                       "focusStrength":frame/10,"contactStrength":frame/10}])
        edges.update([{**edge,"x0":20+frame,"focusStrength":frame/10}])
        application.processEvents()
        assert find_visual(root,"graph-node-0") is first_node
        assert find_visual(root,"graph-edge-0") is first_edge
        assert first_node.property("x") == 20+frame
        assert first_node.property("focusStrength") == pytest.approx(frame/10)
        assert first_node.property("contactStrength") == pytest.approx(frame/10)
        assert first_edge.property("focusStrength") == pytest.approx(frame/10)
        assert 1.7 < first_node.property("radius") < 6.4
    # Legacy bool-only submissions remain supported.
    nodes.update([{**node,"focus":True,"contact":True}])
    assert first_node.property("focusStrength") == 1
    assert first_node.property("contactStrength") == 1
    assert first_node.property("radius") == pytest.approx(6.4)
    root.deleteLater()
    application.sendPostedEvents(None,QtCore.QEvent.DeferredDelete)


def test_desktop_awareness_has_no_visible_window_box_repeater():
    source = (ROOT / "desktop/qml/CreatureScene.qml").read_text()
    assert "model: scene.desktopRects" not in source
    assert "Behavior on" not in source and "NumberAnimation" not in source and "Timer {" not in source
