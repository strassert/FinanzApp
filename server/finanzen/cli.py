"""Command line: python -m finanzen <command>.

serve                     run the HTTP server (waitress)
demo [--out PATH]         build the demo database
check                     check key, application and redirect URL
token create|list|revoke  manage API tokens
pair [--name NAME]        create an app token and print the pairing link + QR code
sync                      fetch all connections (used by the systemd timer)
fx                        update ECB rates
backup [--dir D]          encrypted backup (age, public key only), keeps 14
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

from . import __version__
from .config import Config, load


def _provider(cfg: Config):
    if cfg.bank == "fake":
        from .demo import make_fake
        fake, provider, _clock = make_fake(date.today(), auth_base=cfg.public_url.rstrip("/") + "/fake-bank")
        return provider, fake
    from .bank.enablebanking import EnableBankingProvider
    key = Path(cfg.private_key_path).read_bytes()
    return EnableBankingProvider(cfg.application_id, key), None


def cmd_serve(cfg: Config, args) -> int:
    from waitress import serve
    from .api import create_app
    provider, fake = (None, None) if cfg.demo else _provider(cfg)
    app = create_app(cfg, provider=provider)
    if fake is not None:
        from flask import redirect, request

        @app.get("/fake-bank/authorize")
        def fake_authorize():  # the "bank" approves immediately (development only)
            return redirect(fake.approve(request.url.replace(request.host_url.rstrip("/") + "/fake-bank",
                                                             fake.auth_base)))
    logging.getLogger("waitress").setLevel(logging.WARNING)
    print(f"Finanzen {__version__} on http://{cfg.host}:{cfg.port}"
          f"{' (Demo, nur lesend)' if cfg.demo else ''}")
    serve(app, host=cfg.host, port=cfg.port, threads=4)
    return 0


def cmd_demo(cfg: Config, args) -> int:
    from .demo import build_demo_db
    path = build_demo_db(args.out, date.fromisoformat(args.today) if args.today else None)
    print(f"Demo-Datenbank: {path}")
    return 0


def _conn(cfg: Config):
    from .core.db import connect
    return connect(cfg.db_path)


def cmd_token(cfg: Config, args) -> int:
    from .auth import create_token, list_tokens, revoke_token
    conn = _conn(cfg)
    if args.action == "create":
        print(create_token(conn, args.name, args.scope))
    elif args.action == "list":
        for t in list_tokens(conn):
            state = "widerrufen" if t["revoked_at"] else "aktiv"
            print(f"{t['id']:>3}  {t['scope']:<5} {state:<11} {t['name']}  zuletzt: {t['last_used_at'] or '-'}")
    elif args.action == "revoke":
        print("widerrufen" if revoke_token(conn, args.id) else "nicht gefunden")
    return 0


def cmd_pair(cfg: Config, args) -> int:
    from .auth import create_token
    if not cfg.public_url:
        print("public_url fehlt in der Konfiguration.", file=sys.stderr)
        return 1
    token = create_token(_conn(cfg), args.name, "app")
    link = f"{cfg.public_url.rstrip('/')}/#/koppeln/{token}"
    print("Öffne diesen Link auf dem iPhone in Safari (oder scanne den QR-Code):\n")
    print(link + "\n")
    try:
        import qrcode  # optional
        qr = qrcode.QRCode(border=1)
        qr.add_data(link)
        qr.print_ascii(invert=True)
    except ImportError:
        print("(QR-Code: pip install qrcode)")
    return 0


def cmd_sync(cfg: Config, args) -> int:
    from . import sync
    from .core import fx
    conn = _conn(cfg)
    provider, _ = _provider(cfg)
    try:
        fx.update_rates(conn, _http_get)
    except Exception as exc:  # rates are optional for a sync
        logging.warning("ECB rates not updated: %s", type(exc).__name__)
    results = sync.sync_all(conn, provider, trigger="schedule")
    for r in results:
        print(f"connection {r.connection_id}: {r.status} ({r.new_count} neu) {r.message}")
    return 0 if all(r.status in ("ok", "skipped", "expired") for r in results) else 2


def _http_get(url: str) -> bytes:
    import requests
    resp = requests.get(url, timeout=60)
    resp.raise_for_status()
    return resp.content


def cmd_fx(cfg: Config, args) -> int:
    from .core import fx
    from .core.recompute import recompute
    conn = _conn(cfg)
    print(f"{fx.update_rates(conn, _http_get)} Kurse gespeichert")
    recompute(conn)
    return 0


def cmd_check(cfg: Config, args) -> int:
    ok = True

    def report(good: bool, text: str) -> None:
        nonlocal ok
        ok = ok and good
        print(("OK    " if good else "FEHLT ") + text)

    report(bool(cfg.public_url.startswith("https://")), f"public_url (HTTPS): {cfg.public_url or '-'}")
    if cfg.bank == "fake":
        report(True, "Bank: Fake (Entwicklung)")
        return 0
    key = Path(cfg.private_key_path)
    report(key.is_file(), f"privater Schlüssel: {key}")
    if key.is_file():
        mode = key.stat().st_mode & 0o777
        report(mode & 0o077 == 0, f"Schlüsselrechte 600 (ist {oct(mode)})")
    report(bool(cfg.application_id), "application_id gesetzt")
    if ok:
        from .bank import BankError
        provider, _ = _provider(cfg)
        try:
            app_info = provider.application()
            report(True, f"Application erreichbar: {app_info.get('name', '?')}")
            report(bool(app_info.get("active", True)), "Application aktiv (Production, Konten verknüpft)")
            urls = app_info.get("redirect_urls") or []
            report(cfg.redirect_url in urls, f"Redirect-URL registriert: {cfg.redirect_url}")
        except BankError as exc:
            report(False, f"Enable Banking: {type(exc).__name__} {exc.code or ''}")
    return 0 if ok else 1


def cmd_backup(cfg: Config, args) -> int:
    """Consistent SQLite copy -> gzip -> age (public key only) -> backup dir; keep N."""
    import gzip
    import shutil
    import sqlite3
    import subprocess
    import tempfile
    from datetime import datetime

    target = Path(args.dir or cfg.backup_dir)
    recipients = cfg.backup_recipient_file
    if not target.is_dir():
        print(f"Backup-Ziel fehlt oder ist nicht eingehängt: {target}", file=sys.stderr)
        return 1
    if not Path(recipients).is_file():
        print(f"Öffentlicher age-Schlüssel fehlt: {recipients}", file=sys.stderr)
        return 1
    if shutil.which("age") is None:
        print("age ist nicht installiert (apt install age).", file=sys.stderr)
        return 1
    stamp = datetime.now().strftime("%Y%m%d-%H%M")
    final = target / f"finanzen-{stamp}.db.gz.age"
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "finanzen.db"
        src = sqlite3.connect(cfg.db_path)
        dst = sqlite3.connect(copy)
        src.backup(dst)
        dst.close()
        src.close()
        packed = Path(tmp) / "finanzen.db.gz"
        with open(copy, "rb") as fi, gzip.open(packed, "wb") as fo:
            shutil.copyfileobj(fi, fo)
        partial = final.with_suffix(".partial")
        subprocess.run(["age", "--encrypt", "-R", recipients, "-o", str(partial), str(packed)], check=True)
        partial.rename(final)
    backups = sorted(target.glob("finanzen-*.db.gz.age"))
    for old in backups[:-args.keep]:
        old.unlink()
    print(f"Backup: {final} ({final.stat().st_size // 1024} KB), {min(len(backups), args.keep)} behalten")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="finanzen", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, help="Pfad zur config.toml")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("serve")
    p = sub.add_parser("demo")
    p.add_argument("--out", default="demo.db")
    p.add_argument("--today", help="Stichtag JJJJ-MM-TT (Standard: heute)")
    sub.add_parser("check")
    p = sub.add_parser("token")
    p.add_argument("action", choices=["create", "list", "revoke"])
    p.add_argument("--name", default="iPhone")
    p.add_argument("--scope", default="app", choices=["app", "home", "wallet"])
    p.add_argument("--id", type=int)
    p = sub.add_parser("pair")
    p.add_argument("--name", default="iPhone")
    sub.add_parser("sync")
    sub.add_parser("fx")
    p = sub.add_parser("backup")
    p.add_argument("--dir", help="Zielverzeichnis (Standard: backup_dir aus der Konfiguration)")
    p.add_argument("--keep", type=int, default=14)
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    cfg = load(args.config)
    handler = {"serve": cmd_serve, "demo": cmd_demo, "check": cmd_check, "token": cmd_token,
               "pair": cmd_pair, "sync": cmd_sync, "fx": cmd_fx, "backup": cmd_backup}[args.command]
    return handler(cfg, args)
