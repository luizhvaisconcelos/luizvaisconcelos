from __future__ import annotations

import json
import sqlite3
import threading
import time
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS providers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    vendor TEXT NOT NULL,
    config_enc TEXT NOT NULL,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_sync REAL,
    last_error TEXT
);
CREATE TABLE IF NOT EXISTS devices (
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    device_id TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (provider_id, device_id)
);
CREATE TABLE IF NOT EXISTS clients (
    provider_id INTEGER NOT NULL REFERENCES providers(id) ON DELETE CASCADE,
    mac TEXT NOT NULL,
    data TEXT NOT NULL,
    PRIMARY KEY (provider_id, mac)
);
CREATE TABLE IF NOT EXISTS audit (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts REAL NOT NULL,
    actor TEXT NOT NULL,
    action TEXT NOT NULL,
    target TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT ''
);
"""


class Store:
    def __init__(self, path: Path):
        self._lock = threading.Lock()
        self._db = sqlite3.connect(path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA foreign_keys=ON")
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.executescript(SCHEMA)

    def _q(self, sql: str, args: tuple = ()) -> list[sqlite3.Row]:
        with self._lock:
            cur = self._db.execute(sql, args)
            rows = cur.fetchall()
            self._db.commit()
            return rows

    # providers
    def add_provider(self, name: str, vendor: str, config_enc: str) -> int:
        with self._lock:
            cur = self._db.execute(
                "INSERT INTO providers(name, vendor, config_enc) VALUES (?,?,?)",
                (name, vendor, config_enc),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def update_provider(self, pid: int, **cols) -> None:
        allowed = {"name", "config_enc", "enabled", "last_sync", "last_error"}
        assert set(cols) <= allowed
        sets = ", ".join(f"{k}=?" for k in cols)
        self._q(f"UPDATE providers SET {sets} WHERE id=?", (*cols.values(), pid))

    def delete_provider(self, pid: int) -> None:
        self._q("DELETE FROM providers WHERE id=?", (pid,))

    def get_provider(self, pid: int) -> sqlite3.Row | None:
        rows = self._q("SELECT * FROM providers WHERE id=?", (pid,))
        return rows[0] if rows else None

    def list_providers(self) -> list[sqlite3.Row]:
        return self._q("SELECT * FROM providers ORDER BY name")

    # cache de inventário (substituído a cada sync bem-sucedido)
    def replace_inventory(self, pid: int, devices: list[dict], clients: list[dict]) -> None:
        with self._lock:
            self._db.execute("DELETE FROM devices WHERE provider_id=?", (pid,))
            self._db.execute("DELETE FROM clients WHERE provider_id=?", (pid,))
            self._db.executemany(
                "INSERT OR REPLACE INTO devices VALUES (?,?,?)",
                [(pid, d["id"], json.dumps(d)) for d in devices],
            )
            self._db.executemany(
                "INSERT OR REPLACE INTO clients VALUES (?,?,?)",
                [(pid, c["mac"], json.dumps(c)) for c in clients],
            )
            self._db.commit()

    def devices(self) -> list[dict]:
        return [json.loads(r["data"]) for r in self._q("SELECT data FROM devices")]

    def clients(self) -> list[dict]:
        return [json.loads(r["data"]) for r in self._q("SELECT data FROM clients")]

    # auditoria
    def audit(self, actor: str, action: str, target: str, detail: str = "") -> None:
        self._q(
            "INSERT INTO audit(ts, actor, action, target, detail) VALUES (?,?,?,?,?)",
            (time.time(), actor, action, target, detail),
        )

    def audit_log(self, limit: int = 200) -> list[dict]:
        rows = self._q("SELECT * FROM audit ORDER BY id DESC LIMIT ?", (limit,))
        return [dict(r) for r in rows]
