"""Contrato que todo vendor implementa. A UI/API só conhece estes modelos normalizados."""
from __future__ import annotations

import asyncio
from abc import ABC, abstractmethod
from typing import Any, Callable

import httpx

from ..models import Client, Device, Field


class DriverError(Exception):
    pass


class Driver(ABC):
    vendor: str = ""
    label: str = ""
    fields: list[Field] = []
    can_reboot: bool = False

    def __init__(
        self,
        config: dict,
        *,
        transport: httpx.AsyncBaseTransport | None = None,
        persist: Callable[[dict], None] | None = None,
    ):
        self.config = config
        self._persist = persist or (lambda _updates: None)
        self.http = httpx.AsyncClient(
            verify=bool(config.get("verify_tls", True)),
            timeout=httpx.Timeout(30.0, connect=10.0),
            transport=transport,
            headers={"User-Agent": "netconsole/0.1"},
        )

    async def aclose(self) -> None:
        await self.http.aclose()

    async def request(self, method: str, url: str, **kw: Any) -> httpx.Response:
        """HTTP com retry em 429 respeitando Retry-After (Meraki/Aruba aplicam rate limit)."""
        for attempt in range(4):
            try:
                r = await self.http.request(method, url, **kw)
            except httpx.HTTPError as e:
                raise DriverError(f"{self.vendor}: falha de rede: {e.__class__.__name__}") from e
            if r.status_code == 429 and attempt < 3:
                await asyncio.sleep(min(float(r.headers.get("Retry-After", 2)), 30))
                continue
            return r
        return r  # pragma: no cover

    def check(self, r: httpx.Response) -> httpx.Response:
        if r.status_code >= 400:
            # não vaza corpo/headers (podem conter token) — só status
            raise DriverError(f"{self.vendor}: HTTP {r.status_code} em {r.request.url.path}")
        return r

    @abstractmethod
    async def test(self) -> str:
        """Valida credenciais; retorna uma descrição curta (ex.: nome da org)."""

    @abstractmethod
    async def devices(self) -> list[Device]: ...

    async def clients(self) -> list[Client]:
        return []

    async def reboot(self, device_id: str) -> None:
        raise DriverError(f"{self.vendor}: reboot não suportado")


def norm_mac(mac: str) -> str:
    m = "".join(c for c in mac.lower() if c in "0123456789abcdef")
    return ":".join(m[i : i + 2] for i in range(0, 12, 2)) if len(m) == 12 else mac.lower()
