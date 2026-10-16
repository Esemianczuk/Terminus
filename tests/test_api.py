import uuid

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from terminus.api import create_app


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
        assert client.post("/api/events", json=rejected, headers=headers).status_code == 500
        assert store.organism.dump() == before
        assert store.db.execute("SELECT body FROM snapshot WHERE id=1").fetchone()[0] == persisted
        assert not store.contains(rejected["id"])
        store.db.execute("DROP TRIGGER test_disk_failure")
        assert client.post("/api/events", json=rejected, headers=headers).json()["accepted"] is True
