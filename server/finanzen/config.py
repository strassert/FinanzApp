"""Server configuration from a TOML file (default /etc/finanzen/config.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

DEFAULT_PATH = Path(os.environ.get("FINANZEN_CONFIG", "/etc/finanzen/config.toml"))


@dataclass
class Config:
    db_path: str = "/var/lib/finanzen/finanzen.db"
    host: str = "127.0.0.1"
    port: int = 8750
    public_url: str = ""                 # https://<host>.ts.net – used for the consent redirect
    country: str = "AT"
    demo: bool = False                   # read-only, no bank access, no token needed
    bank: str = "enablebanking"          # enablebanking | fake
    application_id: str = ""
    private_key_path: str = "/etc/finanzen/enablebanking.pem"
    static_dir: str = str(Path(__file__).parent / "static" / "app")
    sync_times: list[str] = field(default_factory=lambda: ["06:30", "18:30"])

    @property
    def redirect_url(self) -> str:
        return self.public_url.rstrip("/") + "/connect/callback"


def load(path: Optional[Path] = None) -> Config:
    path = Path(path or DEFAULT_PATH)
    cfg = Config()
    if path.exists():
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        eb = data.pop("enablebanking", {})
        for key, value in {**data, **eb}.items():
            if hasattr(cfg, key):
                setattr(cfg, key, value)
    return cfg
