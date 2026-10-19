import httpx
import pytest

from app.drivers.aruba_central import ArubaCentralDriver
from app.drivers.base import DriverError
from app.drivers.meraki import MerakiDriver
from app.drivers.ruckus_smartzone import RuckusSmartZoneDriver


def transport(handler):
    return httpx.MockTransport(handler)


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    async def fast(_): pass
    monkeypatch.setattr("asyncio.sleep", fast)


async def test_meraki_devices_pagination_and_429():
    calls = {"n": 0}

    def h(req: httpx.Request):
        assert req.headers["authorization"] == "Bearer K"
        p = req.url.path
        if p == "/api/v1/organizations":
            calls["n"] += 1
            if calls["n"] == 1:
                return httpx.Response(429, headers={"Retry-After": "1"})
            return httpx.Response(200, json=[{"id": "1", "name": "Colégio"}])
        if p == "/api/v1/organizations/1/networks":
            return httpx.Response(200, json=[{"id": "N1", "name": "Campus", "productTypes": ["wireless"]}])
        if p == "/api/v1/organizations/1/devices/statuses":
            return httpx.Response(200, json=[{"serial": "Q1", "status": "alerting", "lanIp": "10.0.0.5"},
                                             {"serial": "Q2", "status": "online"}])
        if p == "/api/v1/organizations/1/devices":
            if "page2" not in str(req.url):
                return httpx.Response(200, json=[{"serial": "Q1", "name": "AP1", "model": "MR46", "mac": "AA-BB-CC-DD-EE-FF",
                                                  "productType": "wireless", "networkId": "N1"}],
                                      headers={"Link": '<https://api.meraki.com/api/v1/organizations/1/devices?page2=1>; rel=next'})
            return httpx.Response(200, json=[{"serial": "Q2", "model": "MS120", "productType": "switch", "networkId": "N1"}])
        if p == "/api/v1/networks/N1/clients":
            return httpx.Response(200, json=[{"mac": "11:22:33:44:55:66", "description": "pc", "ssid": "ALUNOS",
                                              "vlan": 30, "recentDeviceSerial": "Q1"}])
        return httpx.Response(404)

    d = MerakiDriver({"api_key": "K"}, transport=transport(h))
    devs = await d.devices()
    assert [(x.id, x.type, x.status, x.mac) for x in devs] == [
        ("Q1", "ap", "alerting", "aa:bb:cc:dd:ee:ff"), ("Q2", "switch", "online", "")]
    assert devs[0].site == "Colégio / Campus" and devs[0].ip == "10.0.0.5"
    cl = await d.clients()
    assert cl[0].ssid == "ALUNOS" and cl[0].device_id == "Q1"


async def test_meraki_error_does_not_leak_token():
    d = MerakiDriver({"api_key": "TOPSECRET"}, transport=transport(lambda r: httpx.Response(401, text="TOPSECRET")))
    with pytest.raises(DriverError) as e:
        await d.test()
    assert "TOPSECRET" not in str(e.value)


async def test_aruba_refresh_token_rotation():
    saved = {}

    def h(req: httpx.Request):
        if req.url.path == "/oauth2/token":
            return httpx.Response(200, json={"access_token": "NEW", "refresh_token": "R2"})
        if req.headers["authorization"] != "Bearer NEW":
            return httpx.Response(401)
        p = req.url.path
        if p == "/monitoring/v2/aps":
            return httpx.Response(200, json={"total": 1, "aps": [{"serial": "S1", "name": "ap1", "macaddr": "aa:aa:aa:aa:aa:aa",
                                                                   "status": "Up", "group_name": "G"}]})
        if p == "/monitoring/v1/switches":
            return httpx.Response(200, json={"total": 0, "switches": []})
        if p == "/monitoring/v1/mobility_controllers":
            return httpx.Response(200, json={"total": 0, "mcs": []})
        return httpx.Response(404)

    d = ArubaCentralDriver({"base_url": "https://central.test", "access_token": "OLD", "client_id": "c",
                            "client_secret": "s", "refresh_token": "R1"},
                           transport=transport(h), persist=saved.update)
    devs = await d.devices()
    assert devs[0].status == "online" and devs[0].type == "ap"
    assert saved == {"access_token": "NEW", "refresh_token": "R2"}


async def test_ruckus_login_relogin_and_reboot():
    state = {"logins": 0, "rebooted": None}

    def h(req: httpx.Request):
        p = req.url.path
        if p.endswith("/serviceTicket") and req.method == "POST":
            state["logins"] += 1
            return httpx.Response(200, json={"serviceTicket": f"T{state['logins']}"})
        if p.endswith("/serviceTicket"):
            return httpx.Response(200)
        if req.url.params.get("serviceTicket") != "T2":  # primeiro ticket "expirou"
            return httpx.Response(401)
        if p.endswith("/aps") and req.method == "GET":
            return httpx.Response(200, json={"hasMore": False, "list": [
                {"mac": "AA:BB:CC:00:00:01", "name": "R750", "model": "R750", "status": "Online", "zoneName": "Z1"}]})
        if p.endswith("/reboot"):
            state["rebooted"] = p
            return httpx.Response(204)
        return httpx.Response(404)

    d = RuckusSmartZoneDriver({"base_url": "https://sz:8443", "username": "u", "password": "p"}, transport=transport(h))
    devs = await d.devices()
    assert devs[0].status == "online" and devs[0].id == "aa:bb:cc:00:00:01" and state["logins"] == 2
    await d.reboot(devs[0].id)
    assert state["rebooted"].endswith("/aps/aa:bb:cc:00:00:01/reboot")
