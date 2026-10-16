"""Authenticated HTTP/WebSocket habitat; all clients share one serialized core.

Pair using POST /api/pair with a token read from the private runtime file. Browser
clients receive a signed HttpOnly SameSite cookie; command-line clients can send
Authorization: Bearer. Cookie mutations and WebSockets require the same origin.
The event history retains 512 entries and idempotency covers the last 4096 ids.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict, deque
from contextlib import asynccontextmanager, suppress
import hashlib
import hmac
import ipaddress
from pathlib import Path
import secrets
import time
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .store import Store


COOKIE = "terminus_session"
SESSION_SECONDS = 7 * 24 * 60 * 60


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
    def __init__(self, store, clock=time.time):
        self.store = store
        self.clock = clock
        self.lock = asyncio.Lock()
        self.clients = set()
        self.buckets = defaultdict(deque)

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
        state = self.store.organism.state()

        async def send(client):
            try:
                await asyncio.wait_for(client.send_json(state), timeout=.5)
            except (Exception, asyncio.CancelledError):
                self.clients.discard(client)

        await asyncio.gather(*(send(client) for client in tuple(self.clients)))

    async def ticker(self, interval):
        while True:
            await asyncio.sleep(interval)
            async with self.lock:
                self.store.organism.tick(self.clock())
                self.store.save()
                await self.broadcast()


def create_app(data_dir=".local", *, seed=814, tick_interval=1.0, clock=time.time, web_dir=None):
    """Build an application without starting a second organism until lifespan."""
    static = Path(web_dir) if web_dir else Path(__file__).resolve().parent.parent / "web"

    @asynccontextmanager
    async def lifespan(app):
        service = Service(Store(data_dir, now=clock(), seed=seed), clock=clock)
        app.state.service = service
        ticker = asyncio.create_task(service.ticker(tick_interval)) if tick_interval else None
        try:
            yield
        finally:
            if ticker:
                ticker.cancel()
                with suppress(asyncio.CancelledError):
                    await ticker
            async with service.lock:
                for client in tuple(service.clients):
                    with suppress(Exception):
                        await client.close(code=1001)
                service.store.close()

    app = FastAPI(title="Terminus", version="0.1.0", lifespan=lifespan,
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
    async def health():
        return {"status": "ok", "service": "terminus", "version": "0.1.0"}

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

    @app.post("/api/unpair")
    async def unpair(request: Request, response: Response):
        app.state.service.require(request, mutation=True)
        response.delete_cookie(COOKIE, path="/")
        return {"paired": False}

    @app.get("/api/state")
    async def state(request: Request):
        app.state.service.require(request)
        return app.state.service.store.organism.state()

    @app.get("/api/inspect")
    async def inspect(request: Request):
        service = app.state.service
        service.require(request)
        return {**service.store.organism.inspect(), "retention": {
            "history_events": service.store.history_limit, "idempotency_events": service.store.dedup_limit}}

    @app.post("/api/events")
    async def event(body: Event, request: Request):
        service = app.state.service
        service.require(request, mutation=True)
        async with service.lock:
            if service.store.contains(body.id):
                return {"accepted": False, "revision": service.store.organism.data["revision"]}
            service.rate("device:" + body.device_id, 30)
            service.rate("all-events", 120)
            payload = body.model_dump(exclude={"timestamp"})
            before = service.store.organism.dump()
            try:
                service.store.organism.event(payload, service.clock())
                service.store.save(payload)
            except Exception:
                from .core import Organism
                service.store.organism = Organism(saved=before)
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
        async with service.lock:
            service.clients.add(socket)
            await socket.send_json(service.store.organism.state())
        try:
            while True:
                message = await socket.receive_text()
                if len(message) > 512:
                    await socket.close(code=1009)
                    break
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
