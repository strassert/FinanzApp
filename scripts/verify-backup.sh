#!/usr/bin/env bash
# Run on YOUR computer (not the server): decrypt the newest backup into a
# temporary directory and check it. Never touches live data.
#
# Usage: scripts/verify-backup.sh <backup-dir> <age-identity-file>
#   backup-dir: e.g. the mounted OMV share /mnt/nas/backup/finanzen
#   identity:   your private age key (keep it offline / in the password manager)
set -euo pipefail

DIR=${1:?Backup-Verzeichnis angeben}
KEY=${2:?privaten age-Schlüssel angeben}
command -v age >/dev/null || { echo "age fehlt (https://age-encryption.org)" >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 fehlt" >&2; exit 1; }

LATEST=$(ls -1 "$DIR"/finanzen-*.db.gz.age 2>/dev/null | sort | tail -n 1)
[[ -n "$LATEST" ]] || { echo "Keine Backups in $DIR" >&2; exit 1; }
COUNT=$(ls -1 "$DIR"/finanzen-*.db.gz.age | wc -l | tr -d ' ')
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT

echo "Neuestes Backup: $(basename "$LATEST") ($COUNT vorhanden)"
age -d -i "$KEY" -o "$TMP/finanzen.db.gz" "$LATEST"
gunzip "$TMP/finanzen.db.gz"

python3 - "$TMP/finanzen.db" <<'PY'
import sqlite3, sys
c = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
ok = c.execute("PRAGMA integrity_check").fetchone()[0]
print(f"Integrität: {ok}")
for table in ("accounts", "transactions", "balances", "categories", "category_rules", "link_decisions"):
    print(f"  {table:<16} {c.execute(f'SELECT COUNT(*) FROM {table}').fetchone()[0]:>7} Zeilen")
last = c.execute("SELECT MAX(booking_date) FROM transactions").fetchone()[0]
print(f"Letzter Umsatz: {last}")
sys.exit(0 if ok == "ok" else 1)
PY
echo "Backup ist lesbar. (Temporäre Kopie wird gelöscht.)"
