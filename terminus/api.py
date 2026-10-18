"""Authenticated HTTP/WebSocket habitat; all clients share one serialized core.

Loopback-bound browsers pair automatically through POST /api/pair-local. Other
browsers use POST /api/pair with the private token. Both receive a signed
HttpOnly SameSite cookie; command-line clients can send Authorization: Bearer.
Cookie mutations and WebSockets require the same origin.
The event history retains 512 entries and idempotency covers the last 4096 ids.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import ipaddress
import logging
import math
from pathlib import Path
import secrets
import sqlite3
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Store
from . import __version__
from .supervision import notify


COOKIE = "terminus_session"
SESSION_SECONDS = 7 * 24 * 60 * 60
logger = logging.getLogger(__name__)


class Event(BaseModel):
    model_config = ConfigDict(extra="forbid", allow_inf_nan=False)
    id: str = Field(min_length=1, max_length=96, pattern=r"^[a-zA-Z0-9_.:-]+$")
    kind: Literal["context", "poke", "drag", "presence", "git", "activity", "time"]
    device_id: str = Field(min_length=1, max_length=64, pattern=r"^[a-zA-Z0-9_.:-]+$")
    context: str = Field(min_length=1, max_length=100)
    intensity: float = Field(default=.5, ge=0, le=1)
    x: float | None = Field(default=None, ge=0, le=1)
    y: float | None = Field(default=None, ge=0, le=1)
    source: Literal["live", "manual", "synthetic"] = "manual"
    timestamp: float | None = None

    @field_validator("context")
    @classmethod
    def safe_context(cls, value):
        value = value.strip()
        if not value or any(ord(c) < 32 or ord(c) == 127 for c in value):
            raise ValueError("context must be a short label without control characters")
        return value


class Pair(BaseModel):
    model_config = ConfigDict(extra="forbid")
    token: str = Field(min_length=1, max_length=200)


def loopback_host(host):
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def same_origin(connection):
    origin = connection.headers.get("origin")
    if not origin:
        return False
    try:
        parsed = urlsplit(origin)
        scheme = "https" if connection.url.scheme in ("https", "wss") else "http"
        if parsed.scheme not in ("http", "https") or parsed.username or parsed.password:
            return False
        expected = urlsplit(f"{scheme}://{connection.headers.get('host', '')}")
        return (parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)) == (
            expected.scheme, expected.hostname, expected.port or (443 if expected.scheme == "https" else 80))
    except ValueError:
        return False


class Service:
    def __init__(self, store, clock=time.time, *, checkpoint_interval=15.0, tick_interval=1.0):
        self.store = store
        self.clock = clock
        self.checkpoint_interval = checkpoint_interval
        self.tick_interval = tick_interval
        self.started_at = clock()
        self.last_tick_at = None
        # These timestamps describe this process; a loaded snapshot is not a
        # newly completed checkpoint, so report no service write until one occurs.
        self.last_persisted_at = None
        self.next_checkpoint_at = self.started_at + checkpoint_interval
        self.pending_changes = False
        self.tick_errors = self.persistence_errors = 0
        self.last_tick_error = self.last_persistence_error = None
        self.persistence_failures = 0
        self.log_after = {}
        self.ticker_task = None
        self.next_collective_read = 0.
        self.lock = asyncio.Lock()
        self.clients = set()
        self.buckets = defaultdict(deque)

    def diagnostics(self):
        now = self.clock()
        last_tick = self.last_tick_at if self.last_tick_at is not None else self.started_at
        stalled = bool(self.tick_interval and now - last_tick > max(5.0, self.tick_interval * 3))
        stopped = bool(self.tick_interval and self.ticker_task is not None and self.ticker_task.done())
        clock_blocked = now < max(self.store.organism.data["last_tick_at"], self.store.organism.data["server_time"])
        clock_error = "WallClockBehindOrganism" if clock_blocked else None
        degraded = bool(stalled or stopped or clock_blocked or self.last_tick_error or self.last_persistence_error)
        return {"status": "degraded" if degraded else "ok", "started_at": self.started_at,
                "ticker_enabled": bool(self.tick_interval),
                "ticker_stalled": stalled, "ticker_stopped": stopped,
                "clock_blocked": clock_blocked, "clock_error": clock_error,
                "last_tick_at": self.last_tick_at, "last_persisted_at": self.last_persisted_at,
                "checkpoint_interval": self.checkpoint_interval, "pending_changes": self.pending_changes,
                "tick_errors": self.tick_errors, "persistence_errors": self.persistence_errors,
                "last_tick_error": self.last_tick_error, "last_persistence_error": self.last_persistence_error}

    def state(self):
        diagnostics = self.diagnostics()
        # Runtime facts are deliberately separate from the persisted organism.
        # Keep the frequent snapshot compact; full diagnostics live in inspect.
        return {**self.store.organism.state(), "runtime": {key: diagnostics[key] for key in (
            "status", "pending_changes", "clock_blocked", "clock_error", "last_tick_error", "last_persistence_error")}}

    def record_failure(self, operation, error, now):
        name = type(error).__name__
        if operation == "tick":
            self.tick_errors += 1
            self.last_tick_error = name
            count = self.tick_errors
        else:
            self.persistence_errors += 1
            self.persistence_failures += 1
            self.last_persistence_error = name
            count = self.persistence_failures
            self.next_checkpoint_at = now + min(30.0, 2.0 ** min(count - 1, 5))
        if now >= self.log_after.get(operation, -math.inf):
            logger.warning("Terminus %s failed (%s); runtime will retry", operation, name)
            self.log_after[operation] = now + min(60.0, 2.0 ** min(count, 6))

    def persist(self, event=None, *, now=None):
        now = self.clock() if now is None else now
        try:
            self.store.save(event)
        except Exception as error:
            self.record_failure("persistence", error, now)
            raise
        self.last_persisted_at = now
        self.next_checkpoint_at = now + self.checkpoint_interval
        self.pending_changes = False
        self.persistence_failures = 0
        self.last_persistence_error = None

    async def step(self):
        """Advance one coherent tick; a failed checkpoint never freezes life."""
        from .core import Organism
        async with self.lock:
            now = self.clock()
            if now >= self.next_collective_read:
                self.next_collective_read = now + 10
                try:
                    import json
                    path = self.store.directory / "collective-prior.json"
                    if path.stat().st_size > 4096:
                        raise ValueError("Oversized collective prior")
                    prior = json.loads(path.read_text())
                    from .collective import KINDS
                    probabilities = prior["probabilities"]
                    if (prior.get("schema") != 1 or set(probabilities) != set(KINDS)
                            or any(not isinstance(v,(int,float)) or isinstance(v,bool) or not math.isfinite(v)
                                   or not 0 <= v <= 1 for v in probabilities.values())
                            or not .99 <= sum(probabilities.values()) <= 1.01):
                        raise ValueError("Invalid collective prior")
                    self.store.organism.data["collective_prior"] = prior
                except (OSError,ValueError,KeyError,TypeError,AttributeError):
                    pass
            if now < max(self.store.organism.data["last_tick_at"], self.store.organism.data["server_time"]):
                # The core refuses backward time. Publish that blocked state
                # without claiming a successful tick or rewriting its history.
                await self.broadcast()
                return
            before = self.store.organism.dump()
            try:
                self.store.organism.tick(now)
            except Exception as error:
                self.store.organism = Organism(saved=before)
                self.record_failure("tick", error, now)
            else:
                if self.store.organism.data["revision"] > before["data"]["revision"]:
                    self.last_tick_at = now
                    self.last_tick_error = None
                    self.pending_changes = True
            if self.pending_changes and now >= self.next_checkpoint_at:
                try:
                    self.persist(now=now)
                except Exception:
                    pass  # The coherent in-memory state remains available for retry.
            await self.broadcast()

    def sign_session(self):
        payload = f"v1.{int(self.clock()) + SESSION_SECONDS}.{secrets.token_urlsafe(18)}"
        signature = hmac.new(self.store.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
        return payload + "." + signature

    def valid_session(self, value):
        try:
            version, expiration, nonce, signature = value.split(".")
            payload = f"{version}.{expiration}.{nonce}"
            correct = hmac.new(self.store.token.encode(), payload.encode(), hashlib.sha256).hexdigest()
            return version == "v1" and int(expiration) >= self.clock() and hmac.compare_digest(signature, correct)
        except (ValueError, TypeError, AttributeError):
            return False

    def authorized(self, connection):
        authorization = connection.headers.get("authorization", "")
        if authorization.startswith("Bearer ") and hmac.compare_digest(authorization[7:].encode(), self.store.token.encode()):
            return "bearer"
        if self.valid_session(connection.cookies.get(COOKIE)):
            return "cookie"
        return None

    def require(self, request, mutation=False):
        method = self.authorized(request)
        if not method:
            raise HTTPException(401, "Pair this device using the private local token")
        if mutation and ((request.headers.get("origin") and not same_origin(request)) or
                         (method == "cookie" and not same_origin(request))):
            raise HTTPException(403, "A same-origin request is required")

    def rate(self, key, limit, seconds=60):
        now = self.clock()
        bucket = self.buckets[key]
        while bucket and bucket[0] <= now - seconds:
            bucket.popleft()
        if len(bucket) >= limit:
            raise HTTPException(429, "Too many events; give Terminus a moment", headers={"Retry-After": str(seconds)})
        bucket.append(now)
        # Keys are user supplied; keep even the rate limiter bounded.
        if len(self.buckets) > 512:
            for old in list(self.buckets):
                if not self.buckets[old] or self.buckets[old][-1] < now - seconds:
                    del self.buckets[old]
            if len(self.buckets) > 512:
                for old in list(self.buckets)[:len(self.buckets) - 512]:
                    del self.buckets[old]

    async def broadcast(self):
        state = self.state()

        async def send(client):
            try:
                await asyncio.wait_for(client.send_json(state), timeout=.5)
            except (Exception, asyncio.CancelledError):
                self.clients.discard(client)

        await asyncio.gather(*(send(client) for client in tuple(self.clients)))

    async def ticker(self, interval):
        while True:
            await asyncio.sleep(interval)
            try:
                await self.step()
            except Exception as error:
                # Keep the supervisor alive even if snapshot/broadcast code
                # fails outside the transactional physiology/checkpoint paths.
                self.record_failure("tick", error, self.clock())
            healthy = self.diagnostics()["status"] == "ok"
            notify("Core healthy" if healthy else "Core degraded; watchdog recovery pending", healthy=healthy)


def create_app(data_dir=".local", *, seed=814, tick_interval=1.0, checkpoint_interval=15.0,
               clock=time.time, web_dir=None, loopback_browser_pairing=False):
    """Build an application without starting a second organism until lifespan."""
    if not math.isfinite(checkpoint_interval) or checkpoint_interval <= 0:
        raise ValueError("checkpoint_interval must be positive and finite")
    if not math.isfinite(tick_interval) or tick_interval < 0:
        raise ValueError("tick_interval must be nonnegative and finite")
    static = Path(web_dir) if web_dir else Path(__file__).resolve().parent.parent / "web"

    @asynccontextmanager
    async def lifespan(app):
        service = Service(Store(data_dir, now=clock(), seed=seed), clock=clock,
                          checkpoint_interval=checkpoint_interval, tick_interval=tick_interval)
        app.state.service = service
        ticker = asyncio.create_task(service.ticker(tick_interval)) if tick_interval else None
        service.ticker_task = ticker
        notify("Organism state restored; core starting")
        try:
            yield
        finally:
            try:
                if ticker:
                    ticker.cancel()
                    with suppress(asyncio.CancelledError):
                        await ticker
            finally:
                async with service.lock:
                    for client in tuple(service.clients):
                        with suppress(Exception):
                            await client.close(code=1001)
                    service.store.close()

    app = FastAPI(title="Terminus", version=__version__, lifespan=lifespan,
                  docs_url=None, redoc_url=None, openapi_url=None)

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        length = request.headers.get("content-length")
        if length and (not length.isdigit() or int(length) > 8192):
            return Response("Request too large", status_code=413)
        if request.method in ("POST", "PUT", "PATCH"):
            chunks, size = [], 0
            async for chunk in request.stream():
                size += len(chunk)
                if size > 8192:
                    return Response("Request too large", status_code=413)
                chunks.append(chunk)
            request._body = b"".join(chunks)
        response = await call_next(request)
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["Cache-Control"] = "no-store" if request.url.path.startswith("/api") else "no-cache"
        response.headers["Content-Security-Policy"] = "default-src 'self'; img-src 'self' data:; connect-src 'self'; style-src 'self' 'unsafe-inline'; script-src 'self'; frame-ancestors 'none'"
        return response

    @app.get("/api/health")
    async def health(response: Response):
        diagnostics = app.state.service.diagnostics()
        if diagnostics["status"] != "ok":
            response.status_code = 503
        return {"status": diagnostics["status"], "service": "terminus", "version": __version__, "runtime": diagnostics}

    @app.post("/api/pair")
    async def pair(body: Pair, request: Request, response: Response):
        service = app.state.service
        service.rate("pair:" + (request.client.host if request.client else "local"), 15)
        if request.headers.get("origin") and not same_origin(request):
            raise HTTPException(403, "A same-origin request is required")
        if not hmac.compare_digest(body.token.encode(), service.store.token.encode()):
            raise HTTPException(401, "Pairing token does not match")
        response.set_cookie(COOKIE, service.sign_session(), max_age=SESSION_SECONDS,
                            httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return {"paired": True, "organism_id": service.store.organism.data["organism_id"]}

    @app.post("/api/pair-local")
    async def pair_local(request: Request, response: Response):
        # A same-origin page served directly from this machine can acquire its
        # ordinary session cookie without making the person handle a secret.
        # Both the TCP peer and Host must be loopback. A network-bound server,
        # reverse proxy or cross-origin page must use explicit token pairing.
        peer = request.client.host if request.client else ""
        forwarded = any(request.headers.get(name) for name in
                        ("forwarded", "x-forwarded-for", "x-forwarded-host", "x-forwarded-proto"))
        if not (loopback_browser_pairing and loopback_host(peer) and not forwarded
                and loopback_host(request.url.hostname or "") and same_origin(request)):
            raise HTTPException(403, "Local browser pairing is unavailable")
        service = app.state.service
        service.rate("pair-local:" + peer, 30)
        response.set_cookie(COOKIE, service.sign_session(), max_age=SESSION_SECONDS,
                            httponly=True, secure=request.url.scheme == "https", samesite="strict", path="/")
        return {"paired": True, "organism_id": service.store.organism.data["organism_id"]}

    @app.post("/api/unpair")
    async def unpair(request: Request, response: Response):
        app.state.service.require(request, mutation=True)
        response.delete_cookie(COOKIE, path="/")
        return {"paired": False}

    @app.get("/api/state")
    async def state(request: Request):
        app.state.service.require(request)
        return app.state.service.state()

    @app.get("/api/inspect")
    async def inspect(request: Request):
        service = app.state.service
        service.require(request)
        return {**service.store.organism.inspect(), "runtime": service.diagnostics(), "retention": {
            "history_events": service.store.history_limit, "idempotency_events": service.store.dedup_limit}}

    @app.post("/api/events")
    async def event(body: Event, request: Request):
        service = app.state.service
        service.require(request, mutation=True)
        async with service.lock:
            try:
                duplicate = service.store.contains(body.id)
            except (sqlite3.Error, OSError) as error:
                service.record_failure("persistence", error, service.clock())
                raise HTTPException(503, "Memory is temporarily unavailable; retry this same event", headers={"Retry-After": "5"}) from error
            if duplicate:
                return {"accepted": False, "revision": service.store.organism.data["revision"]}
            now = service.clock()
            observed_at = now if body.timestamp is None else body.timestamp
            if observed_at > now + 120 or observed_at < now - 86460:
                raise HTTPException(422, "Event timestamp must be within the last 24 hours and 60 seconds, with at most 120 seconds of clock skew")
            service.rate("device:" + body.device_id, 30)
            service.rate("all-events", 120)
            payload = body.model_dump(exclude={"timestamp"})
            payload.update(observed_at=min(observed_at, now), received_at=now)
            before = service.store.organism.dump()
            try:
                service.store.organism.event(payload, now)
                service.persist(payload, now=now)
            except Exception as error:
                from .core import Organism
                service.store.organism = Organism(saved=before)
                if isinstance(error, (sqlite3.Error, OSError)):
                    raise HTTPException(503, "Memory could not be saved; retry this same event", headers={"Retry-After": "5"}) from error
                raise
            await service.broadcast()
            return {"accepted": True, "revision": service.store.organism.data["revision"]}

    @app.websocket("/ws")
    async def websocket(socket: WebSocket):
        service = app.state.service
        if not service.authorized(socket) or not same_origin(socket):
            await socket.close(code=1008)
            return
        await socket.accept()
        try:
            async with service.lock:
                service.clients.add(socket)
                await asyncio.wait_for(socket.send_json(service.state()), timeout=.5)
            while True:
                message = await socket.receive_text()
                if len(message) > 512:
                    await socket.close(code=1009)
                    break
        except asyncio.TimeoutError:
            with suppress(Exception):
                await asyncio.wait_for(socket.close(code=1011), timeout=.5)
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            service.clients.discard(socket)

    @app.get("/")
    async def index():
        if (static / "index.html").is_file():
            return FileResponse(static / "index.html")
        return Response("Terminus habitat assets are not installed.", media_type="text/plain", status_code=503)

    if static.is_dir():
        app.mount("/", StaticFiles(directory=static), name="habitat")
    return app
