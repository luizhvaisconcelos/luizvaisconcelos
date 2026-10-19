import pytest
from fastapi.testclient import TestClient

from app.drivers.mock import MockDriver
from app.main import create_app

H = {"Authorization": "Bearer adm"}
V = {"Authorization": "Bearer vw"}


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("NETCONSOLE_ADMIN_TOKEN", "adm")
    monkeypatch.setenv("NETCONSOLE_VIEWER_TOKEN", "vw")
    with TestClient(create_app(tmp_path, start_poller=False)) as c:
        yield c


def add_mock(c):
    r = c.post("/api/providers", json={"vendor": "mock", "name": "demo", "config": {}}, headers=H)
    assert r.status_code == 201
    return r.json()["id"]


def test_auth_required(client):
    assert client.get("/api/devices").status_code == 401
    assert client.get("/api/devices", headers={"Authorization": "Bearer x"}).status_code == 401
    assert client.get("/healthz").status_code == 200


def test_sync_and_filter(client):
    pid = add_mock(client)
    assert client.post(f"/api/providers/{pid}/sync", headers=H).status_code == 202
    devs = client.get("/api/devices", headers=V).json()
    assert len(devs) == 12
    assert {d["type"] for d in devs} == {"ap", "switch"}
    assert all(d["status"] == "offline" for d in client.get("/api/devices?status=offline", headers=V).json())
    s = client.get("/api/summary", headers=V).json()
    assert s["by_vendor"]["mock"]["total"] == 12 and s["clients"] == 5


def test_viewer_cannot_mutate(client):
    pid = add_mock(client)
    assert client.post("/api/providers", json={"vendor": "mock", "name": "x"}, headers=V).status_code == 403
    assert client.post(f"/api/devices/{pid}/MOCK-SW-Core-1/reboot", headers=V).status_code == 403
    assert client.get("/api/audit", headers=V).status_code == 403


def test_reboot_is_audited(client):
    pid = add_mock(client)
    MockDriver.rebooted.clear()
    assert client.post(f"/api/devices/{pid}/MOCK-SW-Core-1/reboot", headers=H).status_code == 200
    assert MockDriver.rebooted == ["MOCK-SW-Core-1"]
    assert any(a["action"] == "device.reboot" for a in client.get("/api/audit", headers=H).json())
    assert client.post(f"/api/devices/{pid}/INVALID/reboot", headers=H).status_code == 502


def test_secrets_masked_and_encrypted(client, tmp_path):
    r = client.post("/api/providers", json={"vendor": "meraki", "name": "m",
                    "config": {"api_key": "SUPERSECRET"}}, headers=H)
    assert r.json()["config"]["api_key"] == "********"
    assert b"SUPERSECRET" not in (tmp_path / "netconsole.db").read_bytes()
    pid = r.json()["id"]
    # update sem reenviar o segredo mantém o original (reenvio da máscara não sobrescreve)
    r = client.put(f"/api/providers/{pid}", json={"config": {"api_key": "********", "org_id": "1"}}, headers=H)
    assert r.status_code == 200 and r.json()["config"] == {"api_key": "********", "org_id": "1",
        "base_url": "https://api.meraki.com/api/v1", "collect_clients": True}


def test_validation(client):
    assert client.post("/api/providers", json={"vendor": "nope", "name": "x"}, headers=H).status_code == 422
    assert client.post("/api/providers", json={"vendor": "meraki", "name": "x", "config": {}}, headers=H).status_code == 422
