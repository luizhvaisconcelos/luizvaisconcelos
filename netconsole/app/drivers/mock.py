"""Vendor fictício para demonstração e testes (sem hardware)."""
from __future__ import annotations

from ..models import Client, Device, Field
from .base import Driver, DriverError


class MockDriver(Driver):
    vendor = "mock"
    label = "Demo (simulado)"
    can_reboot = True
    fields = [Field(name="site", label="Nome do site", required=False, default="Colégio Demo")]
    rebooted: list[str] = []

    async def test(self) -> str:
        return "mock ok"

    async def devices(self) -> list[Device]:
        site = self.config.get("site") or "Colégio Demo"
        rows = [("ap", "AP-Sala-%02d" % i, "online" if i % 5 else "offline") for i in range(1, 11)]
        rows += [("switch", "SW-Core-%d" % i, "online") for i in range(1, 3)]
        return [Device(id=f"MOCK-{n}", vendor=self.vendor, type=t, name=n, model="X1", status=s,
                       mac="00:11:22:33:44:%02x" % i, ip=f"10.0.0.{i + 10}", site=site)
                for i, (t, n, s) in enumerate(rows)]

    async def clients(self) -> list[Client]:
        return [Client(vendor=self.vendor, mac="aa:bb:cc:00:00:%02x" % i, ip=f"10.1.0.{i}",
                       name=f"notebook-{i}", ssid="ALUNOS", vlan="30", device_id="MOCK-AP-Sala-01")
                for i in range(1, 6)]

    async def reboot(self, device_id: str) -> None:
        if not device_id.startswith("MOCK-"):
            raise DriverError("mock: dispositivo inválido")
        MockDriver.rebooted.append(device_id)
