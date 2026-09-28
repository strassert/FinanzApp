#!/usr/bin/env bash
# Idempotent installation inside the LXC container (run as root).
# Creates user, directories, venv (packages only when requirements.txt changed),
# config templates, systemd units and Tailscale serve. Restarts the service,
# never reboots. Database migrations run when the service starts.
#
# Usage: sudo deploy/install.sh            (from the repository root)
set -euo pipefail

REPO="$(cd "$(dirname "$0")/.." && pwd)"
APP_USER=finanzen
OPT=/opt/finanzen
DATA=/var/lib/finanzen
ETC=/etc/finanzen
PORT=8750
DEMO_PORT=8752

say() { printf '\033[1m==> %s\033[0m\n' "$*"; }
[[ $EUID -eq 0 ]] || { echo "Bitte als root ausführen (sudo)." >&2; exit 1; }
[[ -f "$REPO/server/finanzen/static/app/index.html" ]] || {
  echo "Web-App nicht gebaut – bitte deploy/deploy.sh verwenden." >&2; exit 1; }

say "Pakete"
missing=()
for pkg in python3 python3-venv age; do dpkg -s "$pkg" >/dev/null 2>&1 || missing+=("$pkg"); done
if ((${#missing[@]})); then apt-get update -q && apt-get install -y -q "${missing[@]}"; fi
PY=$(command -v python3)
"$PY" -c 'import sys; assert sys.version_info >= (3, 11), sys.version' || {
  echo "Python >= 3.11 nötig (Debian 13 hat 3.13)." >&2; exit 1; }

say "Zeitzone"
if [[ "$(timedatectl show -p Timezone --value 2>/dev/null || cat /etc/timezone 2>/dev/null)" != "Europe/Vienna" ]]; then
  timedatectl set-timezone Europe/Vienna 2>/dev/null || ln -sf /usr/share/zoneinfo/Europe/Vienna /etc/localtime
fi

say "Nutzer und Verzeichnisse"
id "$APP_USER" >/dev/null 2>&1 || useradd --system --home-dir "$DATA" --shell /usr/sbin/nologin "$APP_USER"
install -d -m 755 "$OPT"
install -d -m 700 -o "$APP_USER" -g "$APP_USER" "$DATA"
install -d -m 750 -o root -g "$APP_USER" "$ETC"

say "Programm"
rm -rf "$OPT/app.new"
mkdir -p "$OPT/app.new"
cp -a "$REPO/server/finanzen" "$OPT/app.new/"
cp "$REPO/server/requirements.txt" "$OPT/app.new/"
find "$OPT/app.new" -name '__pycache__' -prune -exec rm -rf {} +
rm -rf "$OPT/app.old"
[[ -d "$OPT/app" ]] && mv "$OPT/app" "$OPT/app.old"
mv "$OPT/app.new" "$OPT/app"
chmod -R a+rX "$OPT/app"

say "Python-Umgebung"
[[ -x "$OPT/venv/bin/python" ]] || "$PY" -m venv "$OPT/venv"
REQ_HASH=$(sha256sum "$OPT/app/requirements.txt" | cut -d' ' -f1)
if [[ "$(cat "$OPT/venv/.requirements.sha256" 2>/dev/null)" != "$REQ_HASH" ]]; then
  "$OPT/venv/bin/pip" install -q --upgrade pip
  "$OPT/venv/bin/pip" install -q -r "$OPT/app/requirements.txt"
  echo "$REQ_HASH" > "$OPT/venv/.requirements.sha256"
else
  echo "unverändert"
fi
# the package is imported from the app directory
echo "$OPT/app" > "$("$OPT/venv/bin/python" -c 'import site; print(site.getsitepackages()[0])')/finanzen-app.pth"

cat > /usr/local/bin/finanzen <<EOF
#!/bin/sh
# CLI wrapper: sudo -u $APP_USER finanzen <command>
export FINANZEN_CONFIG=\${FINANZEN_CONFIG:-$ETC/config.toml}
exec $OPT/venv/bin/python -m finanzen "\$@"
EOF
chmod 755 /usr/local/bin/finanzen

say "Konfiguration"
TS_NAME=$(tailscale status --json 2>/dev/null | "$PY" -c 'import json,sys; print(json.load(sys.stdin)["Self"]["DNSName"].rstrip("."))' 2>/dev/null || true)
if [[ ! -f "$ETC/config.toml" ]]; then
  sed -e "s|https://finanzen.<tailnet>.ts.net|https://${TS_NAME:-finanzen.example.ts.net}|" \
      "$REPO/server/config.example.toml" > "$ETC/config.toml"
  echo "angelegt: $ETC/config.toml – application_id eintragen"
fi
if [[ ! -f "$ETC/demo.toml" ]]; then
  cat > "$ETC/demo.toml" <<EOF
db_path = "$DATA/demo.db"
port = $DEMO_PORT
demo = true
public_url = "https://${TS_NAME:-finanzen.example.ts.net}:8443"
EOF
fi
chown root:"$APP_USER" "$ETC"/*.toml
chmod 640 "$ETC"/*.toml
if [[ -f "$ETC/enablebanking.pem" ]]; then
  chown "$APP_USER":"$APP_USER" "$ETC/enablebanking.pem"; chmod 600 "$ETC/enablebanking.pem"
fi

say "systemd"
changed=0
for unit in "$REPO"/deploy/systemd/*; do
  name=$(basename "$unit")
  if ! cmp -s "$unit" "/etc/systemd/system/$name"; then
    install -m 644 "$unit" "/etc/systemd/system/$name"; changed=1
  fi
done
((changed)) && systemctl daemon-reload
systemctl enable --now finanzen-sync.timer >/dev/null
if [[ -d /mnt/backup/finanzen && -f "$ETC/backup-recipient.txt" ]]; then
  systemctl enable --now finanzen-backup.timer >/dev/null
else
  echo "Backup-Timer noch aus: /mnt/backup/finanzen einhängen und $ETC/backup-recipient.txt anlegen."
fi
systemctl enable finanzen.service finanzen-demo.service >/dev/null
systemctl restart finanzen.service finanzen-demo.service

say "Tailscale serve"
if command -v tailscale >/dev/null; then
  tailscale serve --bg --https=443 "http://127.0.0.1:$PORT" >/dev/null
  tailscale serve --bg --https=8443 "http://127.0.0.1:$DEMO_PORT" >/dev/null
  echo "App:  https://${TS_NAME:-<host>.ts.net}/"
  echo "Demo: https://${TS_NAME:-<host>.ts.net}:8443/"
else
  echo "tailscale nicht gefunden – siehe README, Abschnitt Setup."
fi

sleep 1
systemctl is-active --quiet finanzen.service && say "Fertig." || { journalctl -u finanzen -n 20 --no-pager; exit 1; }
