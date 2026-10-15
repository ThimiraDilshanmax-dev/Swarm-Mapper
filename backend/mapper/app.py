from __future__ import annotations
import asyncio
import csv
import io
import json
import os
import secrets
import socket
import struct
import zipfile
import zlib
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4
from fastapi import APIRouter, Depends, FastAPI, HTTPException, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError
from .models import Profile, Telemetry
from .service import Conflict, MapperService

ROOT = Path(__file__).resolve().parents[2]
COOKIE = "contour_operator"


def is_local(host: str | None):
    return host in ("127.0.0.1", "::1", "localhost", "testclient")


def png_bytes(grid):
    import numpy as np
    data = np.where(grid.seen & (grid.log_odds > 0.48), 35,
                    np.where(grid.seen & (grid.log_odds < -0.48), 250, 222)).astype(np.uint8)
    data = np.flipud(data)
    raw = b"".join(b"\x00" + row.tobytes() for row in data)
    def chunk(kind, value):
        return struct.pack(">I", len(value)) + kind + value + struct.pack(">I", zlib.crc32(kind + value) & 0xffffffff)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", grid.n, grid.n, 8, 0, 0, 0, 0)) + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b"")


def create_app(directory: Path | None = None) -> FastAPI:
    service = MapperService(directory or Path(os.environ.get("MAPPER_DATA_DIR", ROOT / ".local")))

    @asynccontextmanager
    async def lifespan(app):
        loop = asyncio.create_task(service.loop())
        try:
            yield
        finally:
            await service.stop("Application shutting down")
            service.running = False
            await loop
            if service.session_id and service.mapping in ("mapping", "paused"):
                service.store.finish(service.session_id, "interrupted", service.summary())
            if service.robot:
                await service.robot.close()
            service.store.close()

    app = FastAPI(title="Contour Mapper", version="0.1.0", lifespan=lifespan)
    app.state.mapper = service
    action_lock = asyncio.Lock()

    def authorized(request: Request):
        token = request.cookies.get(COOKIE, "")
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if not any(secrets.compare_digest(t, service.operator_token) for t in (token, bearer)):
            raise HTTPException(401, "Sign in with the local operator token")
        if request.method not in ("GET", "HEAD", "OPTIONS"):
            origin = request.headers.get("origin")
            if origin:
                from urllib.parse import urlparse
                if urlparse(origin).hostname != request.url.hostname:
                    raise HTTPException(403, "Cross-origin commands are disabled")

    @app.get("/api/health")
    async def health():
        return {"ok": True, "application": "Contour", "version": "0.1.0"}

    @app.post("/api/login")
    async def login(body: dict):
        if not secrets.compare_digest(str(body.get("token", "")), service.operator_token):
            raise HTTPException(401, "Incorrect operator token")
        response = JSONResponse({"ok": True})
        response.set_cookie(COOKIE, service.operator_token, httponly=True, samesite="strict", max_age=86400)
        return response

    @app.get("/api/bootstrap")
    async def bootstrap(request: Request):
        if not is_local(request.client.host if request.client else None):
            authorized(request)
        response = JSONResponse({"ok": True, "name": "Contour", "version": "0.1.0"})
        response.set_cookie(COOKIE, service.operator_token, httponly=True, samesite="strict", max_age=86400)
        return response

    api = APIRouter(prefix="/api", dependencies=[Depends(authorized)])

    @api.get("/state")
    async def state():
        return service.snapshot()

    @api.get("/profile")
    async def profile():
        return service.profile

    @api.post("/profile/validate")
    async def validate_profile(profile: Profile):
        return profile

    @api.get("/sessions")
    async def sessions():
        return service.store.sessions()

    @api.get("/sessions/{sid}")
    async def session(sid: str):
        try:
            return service.store.get(sid)
        except KeyError:
            raise HTTPException(404, "Session not found")

    @api.get("/pairing")
    async def pairing(request: Request):
        try:
            addresses = sorted(set(socket.gethostbyname_ex(socket.gethostname())[2]))
        except OSError:
            addresses = []
        return dict(robot_token=service.robot_token, addresses=addresses, port=request.url.port or 8000,
                    path="/ws/robot", note="Select Robot, then connect firmware to this computer's LAN IPv4 address.")

    @api.post("/action")
    async def action(data: dict):
        client = str(data.get("client_id", ""))
        if client not in service.clients:
            raise HTTPException(409, "Reconnect the live console before sending commands")
        try:
            kind = str(data.get("action", ""))
            if kind in ("stop", "estop"):
                return await service.action(kind, data, client)
            async with action_lock:
                return await service.action(kind, data, client)
        except Conflict as exc:
            raise HTTPException(409, str(exc))
        except (ValueError, KeyError, TypeError, ValidationError) as exc:
            raise HTTPException(422, str(exc))

    @api.get("/export/{sid}/{format}")
    async def export(sid: str, format: str):
        if format not in ("json", "csv", "svg", "pgm", "png", "zip"):
            raise HTTPException(404, "Unknown export format")
        try:
            session = service.store.get(sid)
        except KeyError:
            raise HTTPException(404, "Session not found")
        current = sid == service.session_id or bool(service.replay and sid == service.replay["id"])
        if current:
            grid = service.grid
            path = service.path
            optimization = service.optimization
        else:
            _, grid, path, _, _ = await asyncio.to_thread(service._rebuild_replay,
                Profile.model_validate(session["profile"]), session["samples_data"])
            optimization = None
        result = dict(**session, derived=dict(path=path, optimization=optimization,
            profile=grid.profile.model_dump(),
            grid_resolution=grid.resolution, grid_origin=grid.origin,
            boundary_representation="Supported occupancy cells; gaps are not closed"))
        raw_json = json.dumps(result, indent=2, allow_nan=False).encode()
        csv_io = io.StringIO(newline="")
        writer = csv.writer(csv_io)
        writer.writerow(["frame", "time_s", "left_count", "right_count", "gyro_rad_s",
                         "integrated", "sensor", "sample_time_s", "range_m", "valid", "status"])
        for idx, entry in enumerate(session["samples_data"]):
            f = entry["frame"]
            for r in f["ranges"] or [{}]:
                writer.writerow([idx, f["t"], f["left"], f["right"], f["gyro_z"], entry["integrate"],
                    r.get("sensor",""), r.get("t",""), r.get("distance",""), r.get("valid",""), r.get("status","")])
        csv_data = csv_io.getvalue().encode("utf-8")
        cells = grid.boundary()
        if cells:
            xs, ys = zip(*cells)
            x0, y0 = min(xs)-0.1, -max(ys)-0.1
            width, height = max(xs)-min(xs)+0.2, max(ys)-min(ys)+0.2
        else:
            x0 = y0 = -1
            width = height = 2
        svg = ['<svg xmlns="http://www.w3.org/2000/svg" viewBox="%s %s %s %s">' % (x0,y0,width,height),
               '<title>Supported object-boundary occupancy cells; coordinates in metres, Y reflected for SVG</title>',
               '<g fill="#0d9488">']
        for x,y in cells:
            svg.append('<rect x="%s" y="%s" width="%s" height="%s"/>' %
                       (x-grid.resolution/2, -y-grid.resolution/2, grid.resolution, grid.resolution))
        svg.append("</g></svg>")
        svg_data = "".join(svg).encode()
        formats = {"json": (raw_json, "application/json"), "csv": (csv_data, "text/csv"),
                   "svg": (svg_data, "image/svg+xml"), "pgm": (grid.pgm(), "image/x-portable-graymap"),
                   "png": (png_bytes(grid), "image/png")}
        if format=="zip":
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for name, content in {
                    "session.json": raw_json, "measurements.csv": csv_data, "boundary.svg": svg_data,
                    "map.pgm": grid.pgm(), "map.png": png_bytes(grid),
                    "profile.json": json.dumps(grid.profile.model_dump(), indent=2).encode(),
                    "map.yaml": ("image: map.pgm\nresolution: %s\norigin: [%s, %s, 0.0]\nnegate: 0\noccupied_thresh: 0.65\nfree_thresh: 0.196\n" %
                                 (grid.resolution,*grid.origin)).encode(),
                }.items():
                    archive.writestr(name, content)
            content, media = buffer.getvalue(), "application/zip"
        else:
            content, media = formats[format]
        return Response(content, media_type=media, headers={"Content-Disposition":
            'attachment; filename="contour-' + sid + "." + format + '"'})

    app.include_router(api)

    @app.websocket("/ws/ui")
    async def ui_socket(ws: WebSocket):
        if not secrets.compare_digest(ws.cookies.get(COOKIE, ""), service.operator_token):
            await ws.close(code=4401)
            return
        origin = ws.headers.get("origin")
        if origin:
            from urllib.parse import urlparse
            if urlparse(origin).hostname != ws.url.hostname:
                await ws.close(code=4403)
                return
        await ws.accept()
        cid = uuid4().hex
        service.clients[cid] = ws
        await ws.send_json({"type": "welcome", "client_id": cid})
        try:
            while True:
                message = await ws.receive_json()
                if not isinstance(message, dict):
                    continue
                if message.get("type")=="drive":
                    service.input(cid, message)
                elif message.get("type")=="stop":
                    await service.stop("Controller released motion")
        except (WebSocketDisconnect, RuntimeError, ValueError):
            pass
        finally:
            service.clients.pop(cid, None)
            if service.owner==cid:
                await service.stop("Control connection closed")

    @app.websocket("/ws/robot")
    async def robot_socket(ws: WebSocket):
        token = ws.headers.get("authorization", "").removeprefix("Bearer ")
        if not secrets.compare_digest(token, service.robot_token):
            await ws.close(code=4401)
            return
        if service.source!="robot" or service.robot is not None:
            await ws.close(code=4409)
            return
        await ws.accept()
        try:
            hello = await asyncio.wait_for(ws.receive_json(), timeout=8)
            if isinstance(hello, dict) and hello.get("protocol")!=2:
                service.event("fault", "Incompatible robot protocol. Flash the supplied protocol 2 firmware.")
            if not isinstance(hello, dict) or hello.get("type")!="hello" or hello.get("robot_id")!="master" or not hello.get("boot_id") or hello.get("protocol")!=2:
                await ws.close(code=4400)
                return
            old_boot = service.robot_info.get("boot_id")
            service.robot_info = {k:hello.get(k) for k in
                ("robot_id","boot_id","firmware","tof_models","motors_enabled","ip")}
            service.robot = ws
            service.connected = True
            service.last_frame, service.last_seq = None, -1
            service.last_received = __import__("time").monotonic()
            await service.stop("ESP32 connected; explicit rearming required")
            if service.mapping=="mapping":
                service.mapping="paused"
            if old_boot and old_boot!=hello["boot_id"] and service.session_id:
                service.needs_segment = True
                service.event("fault", "Robot rebooted. Finish this session and start a new coordinate segment.")
            await ws.send_json({"type":"welcome","protocol":2})
            service.event("source", "Authenticated master robot connected")
            while True:
                raw = await ws.receive_text()
                if len(raw)>50000:
                    await ws.close(code=1009)
                    break
                try:
                    parsed = json.loads(raw)
                    if not isinstance(parsed, dict):
                        raise ValueError("Expected a telemetry object")
                    entries = parsed.get("frames") if parsed.get("type")=="batch" else [parsed]
                    if not isinstance(entries,list) or not 1<=len(entries)<=20:
                        raise ValueError("Invalid telemetry batch")
                    frames = [Telemetry.model_validate(entry) for entry in entries]
                    service.connected = True
                    for frame in frames:
                        await service.ingest(frame)
                except (ValidationError,ValueError,TypeError):
                    service.event("fault", "Malformed robot telemetry rejected")
        except (WebSocketDisconnect, RuntimeError, TimeoutError, ValueError):
            pass
        finally:
            if service.robot is ws:
                service.connected = False
                await service.stop("Robot disconnected; mapping paused")
                service.robot = None
                if service.mapping=="mapping":
                    service.mapping="paused"

    dist = ROOT / "frontend" / "dist"
    app.mount("/assets", StaticFiles(directory=dist/"assets", check_dir=False), name="assets")

    @app.get("/")
    async def index():
        if not (dist/"index.html").exists():
            return Response("Build the frontend first: cd frontend && npm install && npm run build",
                            media_type="text/plain", status_code=503)
        return FileResponse(dist/"index.html")

    @app.get("/favicon.svg")
    async def favicon():
        return FileResponse(dist/"favicon.svg",media_type="image/svg+xml")

    @app.get("/favicon.ico",status_code=204)
    async def legacy_favicon():
        return Response(status_code=204)

    return app


app = create_app()
