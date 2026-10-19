"""Orquestra provedores: coleta periódica (cache em SQLite) e ações."""
from __future__ import annotations

import asyncio
import logging
import time

from . import crypto
from .db import Store
from .drivers import REGISTRY, Driver, DriverError
from .models import Field

log = logging.getLogger("netconsole")


def mask(fields: list[Field], config: dict) -> dict:
    secret = {f.name for f in fields if f.secret}
    return {k: ("********" if k in secret and v else v) for k, v in config.items()}


class Service:
    def __init__(self, store: Store, fernet, transport=None):
        self.store, self.fernet, self.transport = store, fernet, transport
        self._locks: dict[int, asyncio.Lock] = {}

    def config_of(self, row) -> dict:
        return crypto.unseal(self.fernet, row["config_enc"])

    def build(self, pid: int | None, vendor: str, config: dict) -> Driver:
        persist = None
        if pid is not None:
            def persist(updates: dict, pid=pid):  # tokens rotativos (Aruba) precisam sobreviver
                row = self.store.get_provider(pid)
                if row:
                    cfg = {**self.config_of(row), **updates}
                    self.store.update_provider(pid, config_enc=crypto.seal(self.fernet, cfg))
        return REGISTRY[vendor](config, transport=self.transport, persist=persist)

    async def test(self, vendor: str, config: dict, pid: int | None = None) -> str:
        d = self.build(pid, vendor, config)
        try:
            return await d.test()
        finally:
            await d.aclose()

    async def sync(self, pid: int) -> None:
        lock = self._locks.setdefault(pid, asyncio.Lock())
        async with lock:
            row = self.store.get_provider(pid)
            if not row or not row["enabled"]:
                return
            d = self.build(pid, row["vendor"], self.config_of(row))
            try:
                devices, clients = await asyncio.gather(d.devices(), d.clients())
                self.store.replace_inventory(
                    pid,
                    [x.model_copy(update={"provider_id": pid}).model_dump() for x in devices],
                    [x.model_copy(update={"provider_id": pid}).model_dump() for x in clients],
                )
                self.store.update_provider(pid, last_sync=time.time(), last_error=None)
            except Exception as e:  # um vendor fora do ar não derruba os demais
                msg = str(e) if isinstance(e, DriverError) else e.__class__.__name__
                log.warning("sync falhou provider=%s: %s", pid, msg)
                self.store.update_provider(pid, last_error=msg)
            finally:
                await d.aclose()

    async def sync_all(self) -> None:
        await asyncio.gather(*(self.sync(r["id"]) for r in self.store.list_providers()))

    async def reboot(self, pid: int, device_id: str) -> None:
        row = self.store.get_provider(pid)
        if not row:
            raise DriverError("provedor não encontrado")
        d = self.build(pid, row["vendor"], self.config_of(row))
        try:
            await d.reboot(device_id)
        finally:
            await d.aclose()

    async def run_forever(self, interval: int) -> None:
        while True:
            await self.sync_all()
            await asyncio.sleep(interval)
