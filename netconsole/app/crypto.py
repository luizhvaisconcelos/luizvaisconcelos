"""Cifra as credenciais dos vendors em repouso (Fernet / AES-128-CBC + HMAC)."""
from __future__ import annotations

import json
import os
from pathlib import Path

from cryptography.fernet import Fernet


def load_fernet(data_dir: Path) -> Fernet:
    key = os.environ.get("NETCONSOLE_SECRET_KEY", "").strip()
    if not key:
        path = data_dir / "secret.key"
        if path.exists():
            key = path.read_text().strip()
        else:
            key = Fernet.generate_key().decode()
            fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            with os.fdopen(fd, "w") as f:
                f.write(key)
    return Fernet(key.encode())


def seal(f: Fernet, data: dict) -> str:
    return f.encrypt(json.dumps(data).encode()).decode()


def unseal(f: Fernet, token: str) -> dict:
    return json.loads(f.decrypt(token.encode()))
