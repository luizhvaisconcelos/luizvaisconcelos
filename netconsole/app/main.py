from __future__ import annotations

import asyncio
import hmac
import logging
import os
import secrets
import sqlite3
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Body, Depends, FastAPI, Header, HTTPException, Query
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import crypto
from .db import Store
from .drivers import REGISTRY, DriverError
from .service import Service, mask

log = logging.getLogger("netconsole")
STATIC = Path(__file__).parent / "static"


def _token(env: str, data_dir: Path | None = None) -> str:
    val = os.environ.get(env, "").strip()
    if not val and data_dir is not None:
        path = data_dir / "admin_token"
        if path.exists():
            return path.read_text().strip()
        val = secrets.token_hex(32)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(val)
        log.warning("NETCONSOLE_ADMIN_TOKEN ausente: token gerado em %s", path)
    return val


def create_app(data_dir: Path | None = None, transport=None, start_poller: bool = True) -> FastAPI:
    data_dir = Path(data_dir or os.environ.get("NETCONSOLE_DATA", "./data"))
    data_dir.mkdir(parents=True, exist_ok=True)
    store = Store(data_dir / "netconsole.db")
    svc = Service(store, crypto.load_fernet(data_dir), transport)
    admin_tok = _token("NETCONSOLE_ADMIN_TOKEN", data_dir)
    viewer_tok = _token("NETCONSOLE_VIEWER_TOKEN")
    interval = int(os.environ.get("NETCONSOLE_SYNC_INTERVAL", "300"))

    @asynccontextmanager
    async def lifespan(_app):
        task = asyncio.create_task(svc.run_forever(interval)) if start_poller else None
        yield
        if task:
            task.cancel()

    app = FastAPI(title="NetConsole", lifespan=lifespan, docs_url="/api/docs", openapi_url="/api/openapi.json")

    def _auth(authorization: str = Header(default="")) -> str:
        tok = authorization.removeprefix("Bearer ").strip()
        if tok and hmac.compare_digest(tok, admin_tok):
            return "admin"
        if tok and viewer_tok and hmac.compare_digest(tok, viewer_tok):
            return "viewer"
        raise HTTPException(401, "token inválido")

    def viewer(role: str = Depends(_auth)) -> str:
        return role

    def admin(role: str = Depends(_auth)) -> str:
        if role != "admin":
            raise HTTPException(403, "requer perfil admin")
        return role

    def _fields(vendor: str):
        if vendor not in REGISTRY:
            raise HTTPException(422, f"vendor desconhecido: {vendor}")
        return REGISTRY[vendor].fields

    def _clean(vendor: str, cfg: dict, old: dict | None = None) -> dict:
        out = {}
        for f in _fields(vendor):
            v = cfg.get(f.name)
            if f.secret and v in (None, "", "********") and old:
                v = old.get(f.name)  # mantém o segredo já salvo
            if v in (None, ""):
                v = f.default
            if f.required and v in (None, ""):
                raise HTTPException(422, f"campo obrigatório: {f.name}")
            if v not in (None, ""):
                out[f.name] = v
        return out

    def _view(row) -> dict:
        v = row["vendor"]
        return {"id": row["id"], "name": row["name"], "vendor": v, "enabled": bool(row["enabled"]),
                "last_sync": row["last_sync"], "last_error": row["last_error"],
                "config": mask(REGISTRY[v].fields, svc.config_of(row))}

    @app.get("/healthz")
    def healthz():
        return {"ok": True}

    @app.get("/api/vendors")
    def vendors(_: str = Depends(viewer)):
        return [{"vendor": k, "label": d.label, "can_reboot": d.can_reboot,
                 "fields": [f.model_dump() for f in d.fields]} for k, d in REGISTRY.items()]

    @app.get("/api/me")
    def me(role: str = Depends(viewer)):
        return {"role": role}

    @app.get("/api/providers")
    def providers(_: str = Depends(viewer)):
        return [_view(r) for r in store.list_providers()]

    @app.post("/api/providers", status_code=201)
    async def add_provider(body: dict = Body(...), role: str = Depends(admin)):
        vendor, name = body.get("vendor", ""), (body.get("name") or "").strip()
        if not name:
            raise HTTPException(422, "nome obrigatório")
        cfg = _clean(vendor, body.get("config", {}))
        try:
            pid = store.add_provider(name, vendor, crypto.seal(svc.fernet, cfg))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "já existe provedor com esse nome")
        store.audit(role, "provider.add", name, vendor)
        asyncio.create_task(svc.sync(pid))
        return _view(store.get_provider(pid))

    @app.put("/api/providers/{pid}")
    def update_provider(pid: int, body: dict = Body(...), role: str = Depends(admin)):
        row = store.get_provider(pid)
        if not row:
            raise HTTPException(404)
        cfg = _clean(row["vendor"], body.get("config", {}), svc.config_of(row))
        store.update_provider(pid, name=body.get("name") or row["name"],
                              enabled=int(body.get("enabled", row["enabled"])),
                              config_enc=crypto.seal(svc.fernet, cfg))
        store.audit(role, "provider.update", row["name"])
        return _view(store.get_provider(pid))

    @app.delete("/api/providers/{pid}", status_code=204)
    def del_provider(pid: int, role: str = Depends(admin)):
        row = store.get_provider(pid)
        if not row:
            raise HTTPException(404)
        store.delete_provider(pid)
        store.audit(role, "provider.delete", row["name"])

    @app.post("/api/providers/test")
    async def test_new(body: dict = Body(...), _: str = Depends(admin)):
        cfg = _clean(body.get("vendor", ""), body.get("config", {}))
        try:
            return {"ok": True, "info": await svc.test(body["vendor"], cfg)}
        except DriverError as e:
            return {"ok": False, "error": str(e)}

    @app.post("/api/providers/{pid}/sync", status_code=202)
    async def sync_now(pid: int, role: str = Depends(admin)):
        if not store.get_provider(pid):
            raise HTTPException(404)
        await svc.sync(pid)
        return _view(store.get_provider(pid))

    @app.get("/api/devices")
    def devices(vendor: str | None = None, type: str | None = None, status: str | None = None,
                q: str | None = Query(None, max_length=100), _: str = Depends(viewer)):
        out = store.devices()
        if vendor: out = [d for d in out if d["vendor"] == vendor]
        if type: out = [d for d in out if d["type"] == type]
        if status: out = [d for d in out if d["status"] == status]
        if q:
            ql = q.lower()
            out = [d for d in out if any(ql in str(d[k]).lower() for k in ("name", "mac", "ip", "serial", "site", "model"))]
        return sorted(out, key=lambda d: (d["vendor"], d["name"]))

    @app.get("/api/clients")
    def clients(q: str | None = Query(None, max_length=100), _: str = Depends(viewer)):
        out = store.clients()
        if q:
            ql = q.lower()
            out = [c for c in out if any(ql in str(c[k]).lower() for k in ("mac", "ip", "name", "ssid"))]
        return out[:2000]

    @app.get("/api/summary")
    def summary(_: str = Depends(viewer)):
        devs, by_vendor = store.devices(), {}
        for d in devs:
            v = by_vendor.setdefault(d["vendor"], {"total": 0, "online": 0, "offline": 0, "alerting": 0})
            v["total"] += 1
            if d["status"] in v: v[d["status"]] += 1
        return {"devices": len(devs), "clients": len(store.clients()),
                "online": sum(d["status"] == "online" for d in devs),
                "offline": sum(d["status"] == "offline" for d in devs), "by_vendor": by_vendor}

    @app.post("/api/devices/{pid}/{device_id}/reboot")
    async def reboot(pid: int, device_id: str, role: str = Depends(admin)):
        row = store.get_provider(pid)
        if not row:
            raise HTTPException(404)
        try:
            await svc.reboot(pid, device_id)
        except DriverError as e:
            store.audit(role, "device.reboot.fail", f"{row['name']}/{device_id}", str(e))
            raise HTTPException(502, str(e))
        store.audit(role, "device.reboot", f"{row['name']}/{device_id}")
        return {"ok": True}

    @app.get("/api/audit")
    def audit(_: str = Depends(admin)):
        return store.audit_log()

    app.mount("/assets", StaticFiles(directory=STATIC), name="assets")

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    return app


def app_factory() -> FastAPI:  # uvicorn --factory app.main:app_factory
    logging.basicConfig(level=logging.INFO)
    return create_app()
