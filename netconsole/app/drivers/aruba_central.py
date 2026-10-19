"""HPE Aruba Networking Central — API clássica (monitoring/v1|v2).

Autenticação: access token OAuth2 gerado no Central (API Gateway > System Apps & Tokens).
Se client_id/secret/refresh_token forem informados, o token é renovado automaticamente em 401.
"""
from __future__ import annotations

from ..models import Client, Device, Field
from .base import Driver, DriverError, norm_mac

STATUS = {"up": "online", "down": "offline"}


class ArubaCentralDriver(Driver):
    vendor = "aruba_central"
    label = "Aruba Central"
    can_reboot = True
    fields = [
        Field(name="base_url", label="API Gateway URL",
              help="Ex.: https://apigw-uswest4.central.arubanetworks.com (varia por cluster)"),
        Field(name="access_token", label="Access token", secret=True),
        Field(name="client_id", label="Client ID", required=False),
        Field(name="client_secret", label="Client secret", secret=True, required=False),
        Field(name="refresh_token", label="Refresh token", secret=True, required=False),
    ]

    def __init__(self, config, **kw):
        super().__init__(config, **kw)
        self.base = config["base_url"].rstrip("/")

    async def _refresh(self) -> bool:
        c = self.config
        if not (c.get("client_id") and c.get("client_secret") and c.get("refresh_token")):
            return False
        r = self.check(await self.request("POST", f"{self.base}/oauth2/token", params={
            "client_id": c["client_id"], "client_secret": c["client_secret"],
            "grant_type": "refresh_token", "refresh_token": c["refresh_token"]}))
        tok = r.json()
        # o refresh token é de uso único: precisa persistir o novo par
        self.config.update(access_token=tok["access_token"], refresh_token=tok["refresh_token"])
        self._persist({"access_token": tok["access_token"], "refresh_token": tok["refresh_token"]})
        return True

    async def _get(self, path: str, params: dict | None = None) -> dict:
        for attempt in (0, 1):
            r = await self.request("GET", self.base + path, params=params,
                                   headers={"Authorization": f"Bearer {self.config['access_token']}"})
            if r.status_code == 401 and attempt == 0 and await self._refresh():
                continue
            return self.check(r).json()
        raise DriverError("aruba_central: não autorizado")  # pragma: no cover

    async def _offset_list(self, path: str, key: str) -> list[dict]:
        out: list[dict] = []
        while True:
            body = await self._get(path, {"limit": 1000, "offset": len(out)})
            page = body.get(key, [])
            out.extend(page)
            if not page or len(out) >= body.get("total", body.get("count", 0)):
                return out

    async def test(self) -> str:
        body = await self._get("/monitoring/v2/aps", {"limit": 1})
        return f"{body.get('total', body.get('count', 0))} APs"

    async def devices(self) -> list[Device]:
        specs = [("ap", "/monitoring/v2/aps", "aps"),
                 ("switch", "/monitoring/v1/switches", "switches"),
                 ("gateway", "/monitoring/v1/mobility_controllers", "mcs")]
        out: list[Device] = []
        for dtype, path, key in specs:
            for d in await self._offset_list(path, key):
                out.append(Device(
                    id=d.get("serial") or d.get("macaddr", ""), vendor=self.vendor, type=dtype,
                    name=d.get("name", ""), model=d.get("model", ""), mac=norm_mac(d.get("macaddr", "")),
                    serial=d.get("serial", ""), ip=d.get("ip_address") or "",
                    firmware=d.get("firmware_version", ""),
                    status=STATUS.get(str(d.get("status", "")).lower(), "unknown"),
                    site=d.get("site") or d.get("group_name") or "",
                ))
        return out

    async def clients(self) -> list[Client]:
        out: list[Client] = []
        for kind in ("wireless", "wired"):
            for c in await self._offset_list(f"/monitoring/v1/clients/{kind}", "clients"):
                out.append(Client(
                    vendor=self.vendor, mac=norm_mac(c.get("macaddr", "")), ip=c.get("ip_address") or "",
                    name=c.get("name") or "", kind=kind, ssid=c.get("essid") or "",
                    vlan=str(c.get("vlan") or ""), device_id=c.get("associated_device") or "",
                    signal_dbm=c.get("signal_db"),
                ))
        return out

    async def reboot(self, device_id: str) -> None:
        r = await self.request("POST", f"{self.base}/device_management/v1/device/{device_id}/action/reboot",
                               headers={"Authorization": f"Bearer {self.config['access_token']}"})
        self.check(r)
