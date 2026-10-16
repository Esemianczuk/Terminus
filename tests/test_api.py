import asyncio
import json
import sqlite3
import uuid
from urllib.parse import urlsplit

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from terminus.api import Service, create_app
from terminus.store import Store


BASE_URL = "http://127.0.0.1:8769"
WS_URL = "ws://127.0.0.1:8769/ws"
ORIGIN = {"origin": BASE_URL}


def payload(**overrides):
    return {"id": str(uuid.uuid4()), "kind": "context", "context": "test editor",
            "device_id": "test-browser", "intensity": .6, "source": "synthetic", **overrides}


def bearer(app):
    return {"Authorization": "Bearer " + app.state.service.store.token}


def test_pair_auth_cookie_origin_and_input_boundaries(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        assert client.get("/api/health").json()["status"] == "ok"
        assert client.get("/api/state").status_code == 401
        assert client.post("/api/pair", json={"token": "invalid"}).status_code == 401
        assert client.post("/api/pair", json={"token": "💙"}).status_code == 401
        secret = app.state.service.store.token
        assert client.post("/api/pair", json={"token": secret}, headers={"origin": "http://evil.invalid"}).status_code == 403
        assert client.post("/api/pair", json={"token": secret}, headers={"origin": "http://host:broken"}).status_code == 403
        response = client.post("/api/pair", json={"token": secret}, headers=ORIGIN)
        assert response.status_code == 200
        assert "HttpOnly" in response.headers["set-cookie"]
        assert "SameSite=strict" in response.headers["set-cookie"]
        assert client.get("/api/state").status_code == 200
        assert client.post("/api/events", json=payload()).status_code == 403
        assert client.post("/api/events", json=payload(), headers={"origin": "http://evil.invalid"}).status_code == 403
        assert client.post("/api/events", json=payload(), headers=ORIGIN).status_code == 200
        assert client.post("/api/events", json=payload(), headers=bearer(app)).status_code == 200
        for invalid in ({"kind": "shell"}, {"intensity": 1.5}, {"context": "hello\nworld"}, {"x": -1}, {"context": "x" * 101}, {"unexpected": True}):
            assert client.post("/api/events", json=payload(**invalid), headers=ORIGIN).status_code == 422
        assert client.post("/api/events", content="x" * 9000, headers=ORIGIN).status_code == 413


def test_two_websockets_receive_the_same_persisted_revision(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        client.post("/api/pair", json={"token": app.state.service.store.token}, headers=ORIGIN)
        with client.websocket_connect(WS_URL, headers=ORIGIN) as first:
            with client.websocket_connect(WS_URL, headers=ORIGIN) as second:
                assert first.receive_json() == second.receive_json()
                event = payload(kind="poke")
                result = client.post("/api/events", json=event, headers=ORIGIN)
                state_a, state_b = first.receive_json(), second.receive_json()
                assert state_a == state_b
                assert state_a["revision"] == result.json()["revision"]
                assert state_a["learning"]["events_seen"] == 1
                assert state_a["recent_events"][-1]["source"] == "synthetic"
                duplicate = client.post("/api/events", json=event, headers=ORIGIN)
                assert duplicate.json() == {"accepted": False, "revision": state_a["revision"]}
                assert client.get("/api/state").json() == state_a


def test_websocket_requires_auth_and_same_origin(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect(WS_URL, headers=ORIGIN):
                pass
        client.post("/api/pair", json={"token": app.state.service.store.token}, headers=ORIGIN)
        for headers in ({}, {"origin": "http://evil.invalid"}):
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect(WS_URL, headers=headers):
                    pass


def test_restart_retains_state_cookie_and_dedup(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    event = payload()
    with TestClient(app, base_url=BASE_URL) as client:
        client.post("/api/pair", json={"token": app.state.service.store.token}, headers=ORIGIN)
        client.post("/api/events", json=event, headers=ORIGIN)
        state = client.get("/api/state").json()
        cookies = dict(client.cookies)
    restart = create_app(tmp_path, tick_interval=0)
    with TestClient(restart, base_url=BASE_URL, cookies=cookies) as client:
        assert client.get("/api/state").json() == state
        assert client.post("/api/events", json=event, headers=ORIGIN).json()["accepted"] is False


def test_rate_limiter_preserves_duplicate_idempotency(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        headers = bearer(app)
        first = payload()
        assert client.post("/api/events", json=first, headers=headers).status_code == 200
        for _ in range(29):
            assert client.post("/api/events", json=payload(), headers=headers).status_code == 200
        assert client.post("/api/events", json=payload(), headers=headers).status_code == 429
        assert client.post("/api/events", json=first, headers=headers).json()["accepted"] is False


def test_failed_transaction_restores_entire_model_replay_and_database(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL, raise_server_exceptions=False) as client:
        headers = bearer(app)
        for _ in range(2):
            assert client.post("/api/events", json=payload(), headers=headers).status_code == 200
        store = app.state.service.store
        before = store.organism.dump()
        persisted = store.db.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0]
        # The snapshot write happens before INSERT events. Fail the latter to
        # prove transaction rollback covers both, plus the mutated RNN replay.
        store.db.execute("CREATE TRIGGER test_disk_failure BEFORE INSERT ON events BEGIN SELECT RAISE(ABORT, 'injected save failure'); END")
        rejected = payload(context="uncommitted context")
        failed = client.post("/api/events", json=rejected, headers=headers)
        assert failed.status_code == 503
        assert failed.headers["retry-after"] == "5"
        assert client.get("/api/health").status_code == 503
        assert store.organism.dump() == before
        assert store.db.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0] == persisted
        assert not store.contains(rejected["id"])
        store.db.execute("DROP TRIGGER test_disk_failure")
        assert client.post("/api/events", json=rejected, headers=headers).json()["accepted"] is True
        assert client.get("/api/health").status_code == 200


def test_idle_checkpoints_are_bounded_and_events_and_clean_stop_are_durable(tmp_path):
    now = [1000.0]
    app = create_app(tmp_path, tick_interval=0, checkpoint_interval=15, clock=lambda: now[0])
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        writes_before = service.store.db.total_changes
        for _ in range(60):
            now[0] += 1
            client.portal.call(service.step)
        assert service.store.db.total_changes - writes_before == 4
        diagnostics = client.get("/api/inspect", headers=bearer(app)).json()["runtime"]
        assert diagnostics["last_tick_at"] == 1060
        assert diagnostics["last_persisted_at"] == 1060
        assert not diagnostics["pending_changes"]

        # A user event commits immediately, independent of the checkpoint timer.
        now[0] += 1
        event = payload()
        assert client.post("/api/events", json=event, headers=bearer(app)).json()["accepted"]
        with sqlite3.connect(tmp_path / "organism.sqlite3") as reader:
            persisted = json.loads(reader.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0])
            assert persisted == service.store.organism.dump()
            assert reader.execute("SELECT COUNT(*) FROM events WHERE id=?", (event["id"],)).fetchone()[0] == 1
        now[0] += 1
        client.portal.call(service.step)
        final_state = service.store.organism.dump()
        assert service.pending_changes
    restart = Store(tmp_path, now=now[0])
    try:
        assert restart.organism.dump() == final_state
        assert restart.contains(event["id"])
    finally:
        restart.close()


def test_checkpoint_failure_retains_life_retries_and_reports_recovery(tmp_path, monkeypatch, caplog):
    now = [1000.0]
    app = create_app(tmp_path, tick_interval=0, checkpoint_interval=15, clock=lambda: now[0])
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        original_save = service.store.save
        attempts = []

        def fail_checkpoint(event=None):
            attempts.append(now[0])
            raise sqlite3.OperationalError("injected private path must not reach health")

        monkeypatch.setattr(service.store, "save", fail_checkpoint)
        for _ in range(20):
            now[0] += 1
            client.portal.call(service.step)
        assert attempts == [1015, 1016, 1018]
        assert service.store.organism.data["revision"] == 20
        assert service.pending_changes
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json()["runtime"]["persistence_errors"] == 3
        assert response.json()["runtime"]["last_persistence_error"] == "OperationalError"
        assert "private path" not in response.text
        assert client.get("/api/state", headers=bearer(app)).json()["runtime"]["status"] == "degraded"
        assert len([record for record in caplog.records if "persistence failed" in record.message]) < len(attempts)

        monkeypatch.setattr(service.store, "save", original_save)
        now[0] = 1022
        client.portal.call(service.step)
        assert client.get("/api/health").status_code == 200
        diagnostics = client.get("/api/inspect", headers=bearer(app)).json()["runtime"]
        assert diagnostics["last_persisted_at"] == 1022
        assert diagnostics["persistence_errors"] == 3
        assert diagnostics["last_persistence_error"] is None
        assert not diagnostics["pending_changes"]
        with sqlite3.connect(tmp_path / "organism.sqlite3") as reader:
            assert json.loads(reader.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0]) == service.store.organism.dump()


def test_actual_ticker_survives_tick_failure_and_restores_coherent_state(tmp_path, monkeypatch):
    store = Store(tmp_path, now=1000)
    now = [1000.0]
    service = Service(store, clock=lambda: now[0], tick_interval=.001)
    before = store.organism.dump()
    organism_type = type(store.organism)
    original_tick = organism_type.tick
    failing = [True]

    def broken_tick(organism, timestamp):
        if failing[0]:
            organism.data["revision"] += 999
            organism.model.wx[:] = 0
            raise ValueError("injected partial tick")
        return original_tick(organism, timestamp)

    monkeypatch.setattr(organism_type, "tick", broken_tick)

    async def until(predicate):
        while not predicate():
            await asyncio.sleep(.0001)

    async def exercise():
        task = asyncio.create_task(service.ticker(.001))
        service.ticker_task = task
        try:
            # The failed organism is replaced from its full pre-tick snapshot.
            # Every failure restores the full pre-tick state, including weights.
            await asyncio.wait_for(until(lambda: service.tick_errors > 0), timeout=1)
            assert not task.done()
            assert store.organism.dump() == before
            assert service.diagnostics()["status"] == "degraded"
            failing[0] = False
            now[0] += 1
            await asyncio.wait_for(until(lambda: service.last_tick_at is not None), timeout=1)
            assert not task.done()
            assert store.organism.data["revision"] > before["data"]["revision"]
            assert service.diagnostics()["status"] == "ok"
        finally:
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    try:
        asyncio.run(exercise())
    finally:
        store.close()


def test_health_detects_stalled_or_stopped_ticker_but_allows_manual_services(tmp_path):
    now = [1000.0]
    app = create_app(tmp_path, tick_interval=0, clock=lambda: now[0])
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        now[0] += 60
        assert client.get("/api/health").status_code == 200
        service.tick_interval = 1
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json()["runtime"]["ticker_stalled"]
        client.portal.call(service.step)
        assert client.get("/api/health").status_code == 200
        service.ticker_task = type("EndedTask", (), {"done": lambda self: True})()
        response = client.get("/api/health")
        assert response.status_code == 503
        assert response.json()["runtime"]["ticker_stopped"]


def test_event_timestamps_preserve_observation_and_receipt_with_skew_bounds(tmp_path):
    now = 100000.0
    app = create_app(tmp_path, tick_interval=0, clock=lambda: now)
    with TestClient(app, base_url=BASE_URL) as client:
        headers = bearer(app)
        historical = payload(kind="presence", source="live", timestamp=now - 3600)
        assert client.post("/api/events", json=historical, headers=headers).status_code == 200
        state = client.get("/api/state", headers=headers).json()
        assert state["recent_events"][-1]["timestamp"] == now - 3600
        assert state["recent_events"][-1]["observed_at"] == now - 3600
        assert state["recent_events"][-1]["received_at"] == now
        assert state["recent_events"][-1]["historical"]
        assert state["devices"][-1]["last_seen"] == now - 3600
        stored = json.loads(app.state.service.store.db.execute("SELECT body FROM events WHERE id=?", (historical["id"],)).fetchone()[0])
        assert stored["observed_at"] == now - 3600 and stored["received_at"] == now
        assert "timestamp" not in stored
        for timestamp in (None, now + 120):
            assert client.post("/api/events", json=payload(timestamp=timestamp), headers=headers).status_code == 200
            assert client.get("/api/state", headers=headers).json()["recent_events"][-1]["observed_at"] == now
        for timestamp in (now + 120.001, now - 86460.001):
            rejected = payload(timestamp=timestamp)
            assert client.post("/api/events", json=rejected, headers=headers).status_code == 422
            assert not app.state.service.store.contains(rejected["id"])
        oldest = payload(timestamp=now - 86460)
        assert client.post("/api/events", json=oldest, headers=headers).status_code == 200
        # A retained duplicate remains idempotent even after its timestamp ages.
        app.state.service.clock = lambda: now + 2 * 86400
        assert client.post("/api/events", json=historical, headers=headers).json()["accepted"] is False


def test_failed_store_initialization_and_close_release_writer_lock_and_handles(tmp_path, monkeypatch):
    import terminus.store as store_module
    connections = []
    connect = sqlite3.connect

    def capture_connection(*args, **kwargs):
        connection = connect(*args, **kwargs)
        connections.append(connection)
        return connection

    monkeypatch.setattr(store_module.sqlite3, "connect", capture_connection)
    (tmp_path / "token").write_text("invalid")
    with pytest.raises(ValueError, match="token file is invalid"):
        Store(tmp_path, now=0)
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connections[-1].execute("SELECT 1")
    (tmp_path / "token").unlink()
    store = Store(tmp_path, now=0)
    connection = store.db

    def fail_save(event=None):
        raise OSError("injected close save failure")

    monkeypatch.setattr(store, "save", fail_save)
    with pytest.raises(OSError, match="injected close save failure"):
        store.close()
    with pytest.raises(sqlite3.ProgrammingError, match="closed"):
        connection.execute("SELECT 1")
    reopened = Store(tmp_path, now=1)
    reopened.close()


def test_persisted_future_clock_is_degraded_without_fake_ticks_and_recovers(tmp_path):
    store = Store(tmp_path, now=1000)
    before = store.organism.dump()
    store.close()
    now = [900.0]
    app = create_app(tmp_path, tick_interval=0, clock=lambda: now[0])
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        service.tick_interval = 1
        for timestamp in range(900, 904):
            now[0] = timestamp
            client.portal.call(service.step)
            response = client.get("/api/health")
            assert response.status_code == 503
            assert response.json()["runtime"]["clock_blocked"]
            assert response.json()["runtime"]["clock_error"] == "WallClockBehindOrganism"
            assert response.json()["runtime"]["last_tick_at"] is None
            assert service.store.organism.dump() == before
            assert not service.pending_changes
            assert client.get("/api/state", headers=bearer(app)).json()["runtime"]["status"] == "degraded"
        now[0] = 1001
        client.portal.call(service.step)
        response = client.get("/api/health")
        assert response.status_code == 200
        assert not response.json()["runtime"]["clock_blocked"]
        assert response.json()["runtime"]["clock_error"] is None
        assert response.json()["runtime"]["last_tick_at"] == 1001
        assert service.store.organism.data["revision"] == before["data"]["revision"] + 1


class InitialSnapshotSocket:
    """An authenticated route peer; no network or live service is involved."""

    def __init__(self, token, failure=None):
        self.headers = {"authorization": "Bearer " + token, "origin": BASE_URL, "host": "127.0.0.1:8769"}
        self.cookies = {}
        self.url = urlsplit(WS_URL)
        self.failure = failure
        self.accepted = False
        self.snapshots = []
        self.send_started = asyncio.Event()
        self.closed = None

    async def accept(self):
        self.accepted = True

    async def send_json(self, state):
        self.send_started.set()
        if self.failure == "raise":
            raise RuntimeError("peer disconnected during initial snapshot")
        if self.failure == "block":
            await asyncio.Event().wait()
        self.snapshots.append(state)

    async def receive_text(self):
        raise WebSocketDisconnect(code=1000)

    async def close(self, code):
        self.closed = code


@pytest.mark.parametrize("failure", ["raise", "block"])
def test_failed_initial_websocket_snapshot_releases_client_and_lock(tmp_path, failure):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ws")
        socket = InitialSnapshotSocket(service.store.token, failure=failure)
        client.portal.call(endpoint, socket)
        assert socket.accepted
        assert not service.clients
        assert not service.lock.locked()
        if failure == "block":
            assert socket.closed == 1011
        replacement = InitialSnapshotSocket(service.store.token)
        client.portal.call(endpoint, replacement)
        assert replacement.accepted and len(replacement.snapshots) == 1
        assert not service.clients
        assert not service.lock.locked()


def test_cancelled_initial_websocket_snapshot_releases_client_and_lock(tmp_path):
    app = create_app(tmp_path, tick_interval=0)
    with TestClient(app, base_url=BASE_URL) as client:
        service = app.state.service
        endpoint = next(route.endpoint for route in app.routes if getattr(route, "path", None) == "/ws")

        async def cancel_initial_send():
            socket = InitialSnapshotSocket(service.store.token, failure="block")
            task = asyncio.create_task(endpoint(socket))
            await asyncio.wait_for(socket.send_started.wait(), timeout=1)
            assert socket in service.clients
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
            assert not service.clients
            assert not service.lock.locked()
            replacement = InitialSnapshotSocket(service.store.token)
            await endpoint(replacement)
            assert len(replacement.snapshots) == 1

        client.portal.call(cancel_initial_send)
