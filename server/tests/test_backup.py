import gzip
import shutil
import sqlite3
import subprocess

import pytest

from finanzen.cli import main
from finanzen.demo import build_demo_db

pytestmark = pytest.mark.skipif(shutil.which("age") is None, reason="age not installed")


def test_backup_is_encrypted_rotated_and_restorable(tmp_path):
    db = build_demo_db(tmp_path / "live.db")
    key = tmp_path / "throwaway-key.txt"            # test-only key pair
    subprocess.run(["age-keygen", "-o", str(key)], check=True, capture_output=True)
    pub = subprocess.run(["age-keygen", "-y", str(key)], check=True, capture_output=True, text=True).stdout
    (tmp_path / "recipient.txt").write_text(pub)
    target = tmp_path / "backups"
    target.mkdir()
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'db_path = "{db}"\nbackup_dir = "{target}"\nbackup_recipient_file = "{tmp_path / "recipient.txt"}"\n')

    for i in range(3):
        for old in target.glob("*.age"):          # distinct timestamps without waiting
            old.rename(target / f"finanzen-2026010{i}-0000.db.gz.age")
        assert main(["--config", str(cfg), "backup", "--keep", "2"]) == 0
    files = sorted(target.glob("*.age"))
    assert len(files) == 2
    raw = files[-1].read_bytes()
    assert raw.startswith(b"age-encryption.org") and b"SQLite" not in raw

    out = tmp_path / "restored.db.gz"
    subprocess.run(["age", "-d", "-i", str(key), "-o", str(out), str(files[-1])], check=True)
    restored = tmp_path / "restored.db"
    restored.write_bytes(gzip.decompress(out.read_bytes()))
    c = sqlite3.connect(restored)
    assert c.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    live = sqlite3.connect(db)
    assert c.execute("SELECT COUNT(*) FROM transactions").fetchone() == live.execute(
        "SELECT COUNT(*) FROM transactions").fetchone()


def test_backup_refuses_without_mount(tmp_path, capsys):
    cfg = tmp_path / "config.toml"
    cfg.write_text(f'db_path = "{tmp_path / "x.db"}"\nbackup_dir = "{tmp_path / "missing"}"\n')
    assert main(["--config", str(cfg), "backup"]) == 1
    assert "nicht eingehängt" in capsys.readouterr().err
