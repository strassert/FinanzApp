# Finanzen

Private Finanzübersicht: ruft Kontostände und Umsätze der eigenen Banken
automatisch ab (über [Enable Banking](https://enablebanking.com), PSD2),
erkennt Umbuchungen und Duplikate, kategorisiert und zeigt alles in einer
Web-App, die auf dem iPhone wie eine normale App vom Home-Bildschirm startet.

> Stand: App und Server fertig mit Demo-Daten getestet; echte Bankanbindung
> und Installation auf dem Server stehen aus (siehe „Bauplan“).
> Spezifikation: [SPEC.md](SPEC.md). Regeln für Agenten: [AGENTS.md](AGENTS.md).

## Architektur

```
 iPhone (Safari-PWA)            Proxmox
 ┌──────────────────┐   Tailscale   ┌───────────────────────────────────────┐
 │ Web-App          │◄────HTTPS────►│ LXC „finanzen“ (Debian 13)            │
 │ Offline-Cache    │               │  tailscale serve :443 → 127.0.0.1:8750│
 └──────────────────┘               │  finanzen.service (Flask + waitress)  │
 ┌──────────────────┐               │   ├─ bank/  ──HTTPS──► Enable Banking │
 │ Kurzbefehl       │──Apple Pay───►│   ├─ core/  (Auswertung)              │
 │ „Transaktion“    │   Meldung     │   ├─ api/   (Token-Auth)              │
 └──────────────────┘               │   └─ SQLite (WAL)                     │
                                    │  finanzen-sync.timer 06:30 / 18:30    │
                                    │  finanzen-backup.timer ──age──► OMV   │
                                    └───────────────────────────────────────┘
```

- **Server** (`server/`): Python-Dienst als eigener Linux-Nutzer mit eigenem
  venv, Datenbank unter `/var/lib/finanzen`, Konfiguration unter
  `/etc/finanzen`, systemd-Service. Nur über Tailscale erreichbar, kein
  öffentlicher Port.
- **Bank-Modul** (`server/finanzen/bank/`): einzige Stelle, die mit Banken
  spricht. Schmale Schnittstelle: Institute auflisten, Zustimmung starten
  und abschließen, Konten, Salden, Umsätze. Der private Schlüssel der
  Enable-Banking-Application verlässt den Server nie. Für Tests und Demo
  gibt es eine Fake-Bank mit derselben Schnittstelle.
- **Auswertung** (`server/finanzen/core/`): Speichern, Verknüpfen,
  Kategorien, Währungen, Zeiträume, Berichte. Kennt nur die Datenbank.
- **Web-App** (`web/`): Svelte + TypeScript, vom Server als statische
  Dateien ausgeliefert. Kopplung per QR-Code (`finanzen://pair` bzw. Link
  mit Token). Service Worker für die Offline-Anzeige.
- **Parser auf dem Server:** Datei-Import und Apple-Pay-Meldungen werden
  serverseitig ausgewertet; eine Korrektur braucht nur ein Deploy.

## Setup

Alles läuft in einem eigenen LXC-Container auf dem Proxmox-Server. Befehle
mit `pve#` auf dem Proxmox-Host, mit `ct#` im Container (als root), mit
`pc$` auf deinem Rechner.

### 1. Container anlegen

In der Proxmox-Oberfläche: *Create CT* mit der Vorlage **Debian 13**,
unprivilegiert, 1 CPU, 512 MB RAM, 8 GB Disk, Hostname `finanzen`.
Danach auf dem Host für Tailscale das TUN-Gerät freigeben und die
OMV-Backup-Freigabe einhängen (unprivilegierte Container können selbst kein
NFS/SMB einhängen, deshalb über den Host):

Tailscale braucht das TUN-Gerät (virtuelle Netzwerkschnittstelle `tailscale0`),
das ein unprivilegierter Container nicht selbst anlegen darf:

```bash
pve# pct set <CTID> --dev0 /dev/net/tun          # ab Proxmox 8.1 (Version: pveversion)
# ältere Versionen stattdessen:
pve# cat >> /etc/pve/lxc/<CTID>.conf <<'CONF'
lxc.cgroup2.devices.allow: c 10:200 rwm
lxc.mount.entry: /dev/net/tun dev/net/tun none bind,create=file
CONF
# OMV-Freigabe auf dem Host einhängen (NFS-Beispiel) und in den Container durchreichen
pve# mkdir -p /mnt/omv-backup && echo "<omv-ip>:/export/backup /mnt/omv-backup nfs defaults,_netdev 0 0" >> /etc/fstab && mount -a
pve# pct set <CTID> -mp0 /mnt/omv-backup,mp=/mnt/backup
pve# pct reboot <CTID>
```

Im unprivilegierten Container gehören Dateien der UID 100000+. Lege auf dem
Share ein Verzeichnis `finanzen` an, das der Container-Nutzer `finanzen`
beschreiben darf (UID im Container: `id -u finanzen` nach Schritt 3, auf dem
Host plus 100000).

### 2. Tailscale im Container

```bash
ct# apt update && apt install -y curl git nodejs npm sudo python3-venv
ct# curl -fsSL https://tailscale.com/install.sh | sh
ct# tailscale up            # im Browser anmelden; in der Tailscale-Konsole HTTPS aktivieren
```

### 3. Installieren

```bash
ct# git clone https://github.com/strassert/FinanzApp.git /root/FinanzApp && cd /root/FinanzApp
ct# deploy/deploy.sh            # Probelauf: zeigt nur, was passieren würde
ct# deploy/deploy.sh --apply    # baut, testet, installiert, startet
```

`install.sh` ist idempotent: Nutzer `finanzen`, `/opt/finanzen` (Programm
und venv), `/var/lib/finanzen` (Datenbank), `/etc/finanzen` (Konfiguration),
systemd-Units, `tailscale serve` (App auf Port 443, Demo auf 8443). Pakete
werden nur neu installiert, wenn sich `requirements.txt` ändert.
Aktualisieren: `git pull && deploy/deploy.sh --apply`.

### 4. Enable Banking

> Die Schritte folgen der Vorlage und sind noch gegen die aktuelle Enable-Banking-Doku zu prüfen (Bauschritt 8).

1. Im Control Panel von Enable Banking eine Application als **Production**
   anlegen. Redirect-URL: `https://finanzen.<tailnet>.ts.net/connect/callback`.
2. Schlüssel: Entweder das Panel erzeugt ihn (dann genau diese `.pem`-Datei
   verwenden) oder du erzeugst ihn im Container und lädst nur das Zertifikat hoch:
   ```bash
   ct# openssl req -new -x509 -days 3650 -nodes -subj "/CN=finanzen" \
         -newkey rsa:2048 -keyout /etc/finanzen/enablebanking.pem -out /root/enablebanking.crt
   ct# chown finanzen:finanzen /etc/finanzen/enablebanking.pem && chmod 600 /etc/finanzen/enablebanking.pem
   ```
3. Die Application über „Activate by linking accounts“ aktivieren und die
   eigenen Konten verknüpfen. Eine eingeschränkte Application liefert nur
   verknüpfte Konten – eine leere Verbindung heißt meist: Konto nicht verknüpft.
4. `application_id` in `/etc/finanzen/config.toml` eintragen, dann prüfen:
   `ct# sudo -u finanzen finanzen check`

Der private Schlüssel verlässt den Container nie.

### 5. iPhone koppeln

```bash
ct# sudo -u finanzen finanzen pair
```

Auf dem iPhone (Tailscale verbunden) `https://finanzen.<tailnet>.ts.net/` in
**Safari** öffnen, *Teilen → Zum Home-Bildschirm*, die App vom Home-Bildschirm
starten und den Kopplungslink dort einfügen. (Die Home-Bildschirm-App hat
eigenen Speicher; eine Kopplung nur in Safari gilt dort nicht.) Danach in der App unter
*Konten → Bank verbinden* zuerst die Volksbank Salzburg verbinden. Die
Zustimmung öffnet sich im Browser; direkt danach wird die ganze Historie
geladen. Tokens verwalten: `finanzen token list|revoke --id N`.

Apple Pay sofort erfassen: Anleitung in der App unter *Konten → Apple Pay
sofort erfassen* (eigener Token mit `--scope wallet`, der nur Zahlungen
melden darf).

### 6. Backups

Auf **deinem Rechner** ein Schlüsselpaar erzeugen; nur der öffentliche Teil
kommt auf den Server:

```bash
pc$ age-keygen -o finanzen-backup-key.txt      # privat: in den Passwort-Manager, offline aufheben
pc$ age-keygen -y finanzen-backup-key.txt      # öffentlich: age1...
ct# echo "age1..." > /etc/finanzen/backup-recipient.txt
ct# deploy/install.sh                          # aktiviert den Backup-Timer (03:15, 14 behalten)
ct# sudo -u finanzen finanzen backup           # einmal sofort
```

Prüfen, ohne Live-Daten anzufassen (auf dem Rechner mit dem privaten Schlüssel):

```bash
pc$ scripts/verify-backup.sh /pfad/zur/omv-freigabe/finanzen finanzen-backup-key.txt
```

### Betrieb

| Was | Wo |
| --- | --- |
| Abrufe 06:30 und 18:30 | `systemctl list-timers finanzen-sync.timer`, Log: `journalctl -u finanzen-sync` |
| Dienst | `systemctl status finanzen`, `journalctl -u finanzen` |
| Manuell abrufen | `sudo -u finanzen finanzen sync` |
| Kurse und Depotwert (läuft mit jedem Abruf) | `sudo -u finanzen finanzen quotes`; Symbole unter `[quotes]` in `/etc/finanzen/config.toml` |
| Demo (erfundene Daten) | `https://finanzen.<tailnet>.ts.net:8443/` |

### Entwicklung

```bash
cd server && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt -r requirements-dev.txt
.venv/bin/python -m pytest
.venv/bin/python -m finanzen demo --out /tmp/demo.db
printf 'db_path="/tmp/demo.db"\ndemo=true\n' > /tmp/demo.toml && .venv/bin/python -m finanzen --config /tmp/demo.toml serve
cd ../web && npm install && npm test && npm run build     # oder: npm run dev (Proxy auf :8750)
```

Mit `bank = "fake"` in einer lokalen Config läuft der ganze Ablauf inklusive
Bank-Zustimmung gegen die eingebaute Fake-Bank.

## Wie die Zahlen berechnet werden

Alle Beträge sind intern ganze Cent. Summen werden in EUR gebildet.

### Umsätze und ihre Rolle

Jeder Rohumsatz bleibt gespeichert. Daraus wird bei jeder Änderung für
**alle** Umsätze neu berechnet, welche Rolle er hat:

| Rolle | zählt als |
| --- | --- |
| `expense` | Ausgabe (negativer Betrag) bzw. Erstattung, die eine Ausgabe mindert |
| `income` | Einnahme |
| `transfer` | Umbuchung zwischen eigenen Konten – zählt weder als Ausgabe noch als Einnahme |
| `excluded` | Duplikat oder vom Nutzer ausgeschlossen – zählt nirgends |

### Umbuchungen und Duplikate (stärkster Beleg zuerst)

| Beleg | Ergebnis |
| --- | --- |
| Abbuchung nennt die IBAN eines eigenen Kontos | Umbuchung, automatisch |
| Text passt zum Muster eines eigenen Kontos (`PAYPAL`, `PAYLIFE`, `FLATEX`; pro Konto änderbar) | Umbuchung; bei PayPal ohne Finanzierungszeile direkt mit dem PayPal-Kauf verknüpft |
| Gegenseite ist der Kontoinhaber (Name aus mind. zwei Wörtern) | Umbuchung |
| nur gleicher Betrag auf eigenem Konto binnen 3 Tagen | Vorschlag zur Bestätigung |
| Gutschrift vom selben Händler binnen 120 Tagen nach einem Kauf | Erstattung: übernimmt die Kategorie und mindert sie |
| gleicher Betrag, gleiches Konto, aus Datei und API (±1 Tag) | Vorschlag Duplikat |

**PayPal und Kreditkarte:** Der Kauf bei PayPal bzw. auf der Karte ist die
Ausgabe; die Abbuchung vom Girokonto dafür ist eine Umbuchung. So zählt
jeder Kauf genau einmal und beim richtigen Konto.

### Kategorien

Vorrang: Wahl des Nutzers → Umbuchung → eigene Händler-Regeln →
eingebaute Schlagwörter → MCC der Karte → „Sonstiges“.

### Budget-Zeitraum

Ein Zeitraum läuft von Gehalt zu Gehalt. Zeitraum M beginnt nominell am
29. des Vormonats. Liegt eine Gehaltsbuchung zwischen 10 Tagen davor und
5 Tagen danach, beginnt er stattdessen an ihrem Buchungsdatum. Benannt wird
er nach dem Monat, den er großteils abdeckt (Gehalt am 28. Sep → „Oktober“).

### Kennzahlen

- **Ausgaben:** Summe der `expense`-Umsätze im Zeitraum (Erstattungen
  mindern sie).
- **Vergleich zum Vormonat:** Ausgaben des vorigen Zeitraums bis zum
  gleichen Tag innerhalb des Zeitraums.
- **Sparquote:** (Einnahmen − Ausgaben) / Einnahmen.
- **Durchschnitt je Kategorie (Ø):** Summe der letzten 12 Zeiträume vor
  dem angezeigten, geteilt durch deren Anzahl. Es zählen nur Zeiträume, die
  nach der ersten Buchung beginnen; bei kürzerer Historie also weniger als 12.
  Folgt der Kartenauswahl.
- **Übrig / Übrig pro Tag:** Einnahmen − Ausgaben − Fixkosten, die bis zum
  Ende des Zeitraums noch erwartet werden (siehe „Fixkosten“; vorgemerkte
  zählen schon als Ausgabe) + erwartete regelmäßige Einnahmen; geteilt durch
  die verbleibenden Tage. Nur im laufenden Zeitraum; folgt der
  Kartenauswahl. Sparpläne und andere Umbuchungen zählen nicht.
- **Vermögen:** Summe der Kontostände in EUR plus letzter Depotwert. Als
  Kontostand zählt der gebuchte bzw. aktuelle Saldo (`CLBD`, `ITBD`, `XPCD`),
  nicht „verfügbar“ (der enthält den Kreditrahmen).
- **Saldo an einem vergangenen Tag:** letzter Saldo minus die Buchungen
  seither.
- **Depotwert:** Stückzahl je ISIN an dem Tag × letzter bekannter Kurs in EUR.
  Stückzahlen aus dem flatex-Export „Depotumsätze“ (Käufe/Verkäufe; die
  Buchungspaare „Thesaurierung transparenter Fonds“ sind österreichische
  Steuerbuchungen und ändern den Bestand nicht). Kurse: Tagesschluss für
  ISINs mit Symbol unter `[quotes]`, sonst der Ausführungskurs aus dem Export.
- **Fremdwährungen:** EZB-Referenzkurs des Buchungsdatums; ohne Kurs nicht
  in Summen, sondern als „nicht umgerechnet“ gezählt.

### Fixkosten (regelmäßige Zahlungen)

Gebuchte Ausgaben und Einnahmen (keine Umbuchungen) werden je Konto,
Richtung und Empfänger gruppiert. Der Empfänger ist die Gegenseite, sonst
der Buchungstext ohne Ziffern. Innerhalb einer Gruppe bilden Buchungen eine
Reihe, wenn der Betrag höchstens 25 % vom letzten der Reihe abweicht. So
bleiben Gehalt und Urlaubszuschuss getrennt.

| Rhythmus | Abstand | mind. Buchungen |
| --- | --- | --- |
| wöchentlich | 7 ± 2 Tage | 3 |
| monatlich | 30 ± 5 Tage | 3 |
| vierteljährlich | 91 ± 12 Tage | 2 |
| halbjährlich | 182 ± 15 Tage | 2 |
| jährlich | 365 ± 20 Tage | 2 |

Mindestens 75 % der Abstände müssen passen. Eine Reihe aus nur zwei
Buchungen zählt nur, wenn an den Empfänger sonst nichts ging und der Betrag
höchstens 5 % abweicht. Beendet ist eine Reihe, wenn die nächste Buchung
länger als einen Rhythmus überfällig ist.

- **Erwarteter Betrag:** Median der letzten drei Buchungen. War der Betrag
  davor gleich und ändert sich mit der letzten Buchung, gilt der neue Betrag
  (Preisänderung; der alte wird angezeigt).
- **Pro Monat:** Betrag × Buchungen pro Jahr / 12.
- **„Keine Fixkosten“:** wird je Empfänger gespeichert und übersteht jede
  Neuberechnung.

### Kontostandsprognose

Für jedes EUR-Konto mit Bankanbindung, bis zum Ende des Budget-Zeitraums
(also bis vor das nächste Gehalt):

Prognose = Kontostand heute + vorgemerkte Umsätze, die der Saldo noch nicht
enthält + alle erwarteten regelmäßigen Buchungen bis dahin.

- Apple-Pay-Meldungen zählen immer als noch nicht enthalten, vorgemerkte
  Bankumsätze nur, wenn die Bank einen Saldo ohne Vormerkungen liefert.
- Erwartet werden die Fixkosten wie oben, zusätzlich regelmäßige
  Umbuchungen (z. B. Sparplan). Ein Termin entfällt, wenn um diesen Tag
  (± Toleranz des Rhythmus) schon eine Buchung desselben Empfängers
  vorgemerkt ist oder mit anderem Betrag gebucht wurde. Überfällige Termine
  zählen weiter.
- Zusätzlich wird der tiefste Stand im Zeitraum mit Datum angezeigt.
- **Kreditkarte:** Einen Monat nach der letzten Abrechnung wird der offene
  Betrag der Karte vom zahlenden Konto abgebucht. Abrechnung = Umbuchung von
  einem anderen Konto auf die Karte (verknüpft oder mit dem Muster der
  Karte, z. B. `PAYLIFE`). Offener Betrag = Kartensaldo plus, was er noch
  nicht enthält; ohne Saldo (Import ohne Saldospalte) die Summe aller
  Kartenbuchungen. Abrechnungen zählen nicht zusätzlich als regelmäßige
  Umbuchung. Käufe nach dem Stichtag der Karte fallen so schon in diese
  Abrechnung; die Prognose ist dann eher zu vorsichtig.

### Vorgemerkte Umsätze und Apple Pay

Vorgemerkte Umsätze, die beim nächsten Abruf fehlen, werden durch die
gebuchten ersetzt; Kategorie und Notiz wandern mit. Apple-Pay-Meldungen aus
dem Kurzbefehl zählen sofort als vorgemerkt; liefert die Bank denselben
Betrag auf dem Konto (2 Tage davor bis 10 Tage danach, Fremdwährung ±3 %),
wird die Bankbuchung damit verknüpft und die Meldung zählt nicht mehr.

## Bauplan

1. ✅ Interview und Steckbrief
2. ✅ Projektdateien
3. ✅ Fake-Bank (Enable-Banking-Mock; API-Annahmen noch gegen die Doku prüfen)
4. ✅ Datenlogik mit Tests
5. ✅ Demo-Daten und lokaler Demo-Server
6. ✅ Web-App (Startseite, Umsätze, Erkunden, Konten, Kategorien, Import, Apple Pay)
7. ✅ Server-Betrieb: Skripte, systemd, Tailscale serve, Kopplung, Backups – installiert (LXC 108); Backup-Ablage noch einzurichten
8. Echte Banken: ✅ Volksbank Salzburg, ✅ flatex-Depot per Export + Tageskurse (flatex nicht bei Enable Banking), dann PayPal, PayLife (Import)
9. ✅ Funktionen F1, F8, F9, F10, F11, F12 (F13 später)
10. Release
