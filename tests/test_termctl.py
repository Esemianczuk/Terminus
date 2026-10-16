"""Core manager ownership and concurrent-start boundaries, without services."""
import importlib.util
import json
import os
from pathlib import Path
import threading
import time

import pytest

SPEC = importlib.util.spec_from_file_location('termctl', Path(__file__).parents[1] / 'scripts' / 'termctl.py')
ctl = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(ctl)


def test_core_manager_cannot_adopt_the_test_runner():
    assert ctl.process_identity(os.getpid()) is None
    assert not ctl.owned_process(None)


@pytest.mark.parametrize('changed', [{'start_ticks': 'new'}, {'boot_id': 'new-boot'}, {'uid': -1}])
def test_changed_process_identity_can_never_receive_a_stop_signal(monkeypatch, changed):
    record = {'pid': 17, 'start_ticks': 'old', 'boot_id': 'old-boot', 'uid': os.getuid()}
    monkeypatch.setattr(ctl, 'process_identity', lambda pid: {**record, **changed})
    monkeypatch.setattr(ctl.os, 'kill', lambda *a: pytest.fail('Must never signal a changed process'))
    assert ctl.stop(record) == 1


def test_two_start_requests_are_serialized_by_manager_lock(tmp_path, monkeypatch):
    monkeypatch.setattr(ctl, 'DATA', tmp_path)
    monkeypatch.setattr(ctl.sys, 'argv', ['termctl', 'start'])
    monkeypatch.setattr(ctl, 'load_record', lambda: None)
    first_inside, release = threading.Event(), threading.Event()
    active, maximum, count = 0, 0, 0
    guard = threading.Lock()

    def fake_start(record):
        nonlocal active, maximum, count
        with guard:
            active += 1
            maximum = max(maximum, active)
            count += 1
            current = count
        if current == 1:
            first_inside.set()
            assert release.wait(2)
        with guard:
            active -= 1
        return 0

    monkeypatch.setattr(ctl, 'start', fake_start)
    results = []
    first = threading.Thread(target=lambda: results.append(ctl.main()))
    second = threading.Thread(target=lambda: results.append(ctl.main()))
    first.start()
    assert first_inside.wait(1)
    second.start()
    time.sleep(.05)
    release.set()
    first.join(2)
    second.join(2)
    assert not first.is_alive() and not second.is_alive()
    assert maximum == 1 and count == 2 and results == [0, 0]


def test_launch_retries_initializing_process_identity_without_duplicate_child(tmp_path, monkeypatch):
    runtime = tmp_path / '.local'
    runtime.mkdir()
    python = tmp_path / '.venv' / 'bin' / 'python'
    python.parent.mkdir(parents=True)
    python.touch()
    monkeypatch.setattr(ctl, 'ROOT', tmp_path)
    monkeypatch.setattr(ctl, 'DATA', runtime)
    monkeypatch.setattr(ctl, 'RECORD', runtime / 'managed-core.json')
    identity = {'pid': 17, 'start_ticks': 'ticks', 'boot_id': 'boot', 'uid': os.getuid()}
    identities = iter([None, identity])
    identity_calls, launches, sleeps, health_calls = [], [], [], []

    def initializing_identity(pid):
        identity_calls.append(pid)
        return next(identities)

    def health():
        health_calls.append(True)
        if len(health_calls) == 1:
            return False  # Nothing served the port before this one launch.
        assert json.loads(ctl.RECORD.read_text()) == identity
        return True

    def launch(command, **kwargs):
        launches.append(command)
        return type('Child', (), {'pid': 17, 'poll': lambda self: None})()

    monkeypatch.setattr(ctl, 'process_identity', initializing_identity)
    monkeypatch.setattr(ctl, 'health', health)
    monkeypatch.setattr(ctl.subprocess, 'Popen', launch)
    monkeypatch.setattr(ctl.time, 'sleep', lambda seconds: sleeps.append(seconds))
    monkeypatch.setattr(ctl, 'stop', lambda record: pytest.fail('Healthy initialized child must remain running'))
    assert ctl.start(None) == 0
    assert identity_calls == [17, 17]
    assert len(launches) == 1 and len(health_calls) == 2
    assert sleeps == [.1]
    assert json.loads(ctl.RECORD.read_text()) == identity


def test_legacy_record_upgrade_uses_the_same_verified_identity(tmp_path, monkeypatch):
    record_path = tmp_path / 'managed-core.json'
    legacy = {'pid': 17, 'start_ticks': 'old'}
    identity = {**legacy, 'boot_id': 'boot', 'uid': os.getuid()}
    record_path.write_text(json.dumps(legacy))
    monkeypatch.setattr(ctl, 'RECORD', record_path)
    calls = []

    def identity_once(pid):
        calls.append(pid)
        if len(calls) > 1:
            pytest.fail('A second identity read could adopt a replacement process')
        return identity

    monkeypatch.setattr(ctl, 'process_identity', identity_once)
    assert ctl.load_record() == identity
    assert calls == [17]
    assert json.loads(record_path.read_text()) == identity
