from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

DeviceType = Literal["ap", "switch", "gateway", "other"]
DeviceStatus = Literal["online", "offline", "alerting", "unknown"]


class Device(BaseModel):
    provider_id: int = 0
    id: str  # identificador único dentro do provedor (serial ou MAC)
    vendor: str
    type: DeviceType = "other"
    name: str = ""
    model: str = ""
    mac: str = ""
    serial: str = ""
    ip: str = ""
    firmware: str = ""
    status: DeviceStatus = "unknown"
    site: str = ""


class Client(BaseModel):
    provider_id: int = 0
    vendor: str
    mac: str
    ip: str = ""
    name: str = ""
    kind: Literal["wireless", "wired"] = "wireless"
    ssid: str = ""
    vlan: str = ""
    device_id: str = ""  # AP/switch ao qual está conectado
    signal_dbm: int | None = None


class Field(BaseModel):
    name: str
    label: str
    secret: bool = False
    required: bool = True
    default: str | bool | None = None
    help: str = ""
    kind: Literal["text", "bool"] = "text"
