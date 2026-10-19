"""Ruckus SmartZone (vSZ / SZ100 / SZ300) — Public API REST (porta 8443).

Autenticação via serviceTicket (POST /serviceTicket). Em versões novas (>= 6.x/7.x) a Public API
também aceita sessão por cookie; ajuste `api_version` conforme a versão do seu controller.
"""
from __future__ import annotations

from ..models import Client, Device, Field
from .base import Driver, DriverError, norm_mac

STATUS = {"online": "online", "offline": "offline", "flagged": "alerting", "discovery": "unknown"}


class RuckusSmartZoneDriver(Driver):
    vendor = "ruckus_smartzone"
    label = "Ruckus SmartZone"
    can_reboot = True
    fields = [
        Field(name="base_url", label="URL do SmartZone", help="Ex.: https://sz.escola.local:8443"),
        Field(name="username", label="Usuário (somente leitura recomendado)"),
        Field(name="password", label="Senha", secret=True),
        Field(name="api_version", label="Versão da API", required=False, default="v9_1",
              help="Ex.: v9_1, v11_1 — veja /wsg/apidoc no seu controller"),
        Field(name="verify_tls", label="Validar certificado TLS", required=False, default=True, kind="bool",
              help="Desligue só se o controller usa cert autoassinado (prefira instalar CA)"),
    ]

    def __init__(self, config, **kw):
        super().__init__(config, **kw)
        ver = config.get("api_version") or "v9_1"
        self.api = f"{config['base_url'].rstrip('/')}/wsg/api/public/{ver}"
        self._ticket: str | None = None

    async def _login(self) -> None:
        r = self.check(await self.request("POST", f"{self.api}/serviceTicket", json={
            "username": self.config["username"], "password": self.config["password"]}))
        self._ticket = r.json().get("serviceTicket")
        if not self._ticket:
            raise DriverError("ruckus_smartzone: login sem serviceTicket")

    async def _call(self, method: str, path: str, **kw):
        if not self._ticket:
            await self._login()
        for attempt in (0, 1):
            r = await self.request(method, self.api + path,
                                   params={**kw.pop("params", {}), "serviceTicket": self._ticket}, **kw)
            if r.status_code in (401, 403) and attempt == 0:
                await self._login()
                continue
            return self.check(r)

    async def _list(self, path: str) -> list[dict]:
        out: list[dict] = []
        while True:
            body = (await self._call("GET", path, params={"index": len(out), "listSize": 1000})).json()
            out.extend(body.get("list", []))
            if not body.get("hasMore") or not body.get("list"):
                return out

    async def test(self) -> str:
        await self._login()
        body = (await self._call("GET", "/aps", params={"listSize": 1})).json()
        return f"{body.get('totalCount', '?')} APs"

    async def devices(self) -> list[Device]:
        # Switches ICX gerenciados pelo SmartZone usam outra API (switchm) e não são coletados ainda.
        return [Device(
            id=norm_mac(a.get("mac", "")), vendor=self.vendor, type="ap", name=a.get("name", ""),
            model=a.get("model", ""), mac=norm_mac(a.get("mac", "")), serial=a.get("serial", ""),
            ip=a.get("ip") or "", firmware=a.get("firmwareVersion", ""),
            status=STATUS.get(str(a.get("status") or a.get("connectionState") or "").lower(), "unknown"),
            site=" / ".join(x for x in (a.get("zoneName"), a.get("apGroupName")) if x),
        ) for a in await self._list("/aps")]

    async def clients(self) -> list[Client]:
        out: list[Client] = []
        page = 1
        while True:
            body = (await self._call("POST", "/query/client", json={"page": page, "limit": 1000})).json()
            rows = body.get("list", [])
            out += [Client(
                vendor=self.vendor, mac=norm_mac(c.get("clientMac", "")), ip=c.get("ipAddress") or "",
                name=c.get("hostname") or c.get("userName") or "", kind="wireless",
                ssid=c.get("ssid") or "", vlan=str(c.get("vlan") or ""), device_id=norm_mac(c.get("apMac", "")),
            ) for c in rows]
            if not body.get("hasMore") or not rows:
                return out
            page += 1

    async def reboot(self, device_id: str) -> None:
        await self._call("PUT", f"/aps/{device_id}/reboot")

    async def aclose(self) -> None:
        if self._ticket:
            try:
                await self.http.delete(f"{self.api}/serviceTicket", params={"serviceTicket": self._ticket})
            except Exception:
                pass
        await super().aclose()
