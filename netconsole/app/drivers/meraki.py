"""Cisco Meraki — Dashboard API v1 (https://developer.cisco.com/meraki/api-v1/)."""
from __future__ import annotations

from ..models import Client, Device, Field
from .base import Driver, DriverError, norm_mac

TYPE_MAP = {"wireless": "ap", "switch": "switch", "appliance": "gateway"}
STATUS_MAP = {"online": "online", "offline": "offline", "alerting": "alerting", "dormant": "offline"}


class MerakiDriver(Driver):
    vendor = "meraki"
    label = "Cisco Meraki"
    can_reboot = True
    fields = [
        Field(name="api_key", label="API Key", secret=True, help="Dashboard > My profile > API access"),
        Field(name="org_id", label="Organization ID", required=False, help="Vazio = todas as orgs da chave"),
        Field(name="base_url", label="Base URL", required=False, default="https://api.meraki.com/api/v1",
              help="Use o shard da org se necessário (ex.: api.meraki.com)"),
        Field(name="collect_clients", label="Coletar clientes", required=False, default=True, kind="bool"),
    ]

    def __init__(self, config, **kw):
        super().__init__(config, **kw)
        self.base = (config.get("base_url") or "https://api.meraki.com/api/v1").rstrip("/")
        self.http.headers["Authorization"] = f"Bearer {config['api_key']}"

    async def _paged(self, path: str, params: dict | None = None) -> list:
        out: list = []
        url: str | None = self.base + path
        params = {"perPage": 1000, **(params or {})}
        while url:
            r = self.check(await self.request("GET", url, params=params))
            body = r.json()
            out.extend(body if isinstance(body, list) else body.get("items", []))
            url = r.links.get("next", {}).get("url")
            params = None  # a URL do Link já carrega a query
        return out

    async def _orgs(self) -> list[dict]:
        if self.config.get("org_id"):
            return [{"id": str(self.config["org_id"]), "name": str(self.config["org_id"])}]
        return await self._paged("/organizations")

    async def test(self) -> str:
        orgs = await self._orgs()
        if not orgs:
            raise DriverError("meraki: chave sem acesso a nenhuma organização")
        return ", ".join(o["name"] for o in orgs[:5])

    async def devices(self) -> list[Device]:
        result: list[Device] = []
        for org in await self._orgs():
            oid = org["id"]
            nets = {n["id"]: n["name"] for n in await self._paged(f"/organizations/{oid}/networks")}
            status = {s["serial"]: s for s in await self._paged(f"/organizations/{oid}/devices/statuses")}
            for d in await self._paged(f"/organizations/{oid}/devices"):
                st = status.get(d["serial"], {})
                result.append(Device(
                    id=d["serial"], vendor=self.vendor,
                    type=TYPE_MAP.get(d.get("productType", ""), "other"),
                    name=d.get("name") or d["serial"], model=d.get("model", ""),
                    mac=norm_mac(d.get("mac", "")), serial=d["serial"],
                    ip=st.get("lanIp") or d.get("lanIp") or "", firmware=d.get("firmware", ""),
                    status=STATUS_MAP.get(st.get("status", ""), "unknown"),
                    site=f"{org['name']} / {nets.get(d.get('networkId'), '')}".strip(" /"),
                ))
        return result

    async def clients(self) -> list[Client]:
        if not self.config.get("collect_clients", True):
            return []
        out: list[Client] = []
        for org in await self._orgs():
            for net in await self._paged(f"/organizations/{org['id']}/networks"):
                if not {"wireless", "switch", "appliance"} & set(net.get("productTypes", [])):
                    continue
                for c in await self._paged(f"/networks/{net['id']}/clients", {"timespan": 3600}):
                    wireless = bool(c.get("ssid"))
                    out.append(Client(
                        vendor=self.vendor, mac=norm_mac(c.get("mac", "")), ip=c.get("ip") or "",
                        name=c.get("description") or c.get("dhcpHostname") or "",
                        kind="wireless" if wireless else "wired", ssid=c.get("ssid") or "",
                        vlan=str(c.get("vlan") or ""), device_id=c.get("recentDeviceSerial") or "",
                    ))
        return out

    async def reboot(self, device_id: str) -> None:
        self.check(await self.request("POST", f"{self.base}/devices/{device_id}/reboot"))
