# Finanzen

Private Finanzübersicht: ruft Kontostände und Umsätze der eigenen Banken
automatisch ab (über [Enable Banking](https://enablebanking.com), PSD2),
erkennt Umbuchungen und Duplikate, kategorisiert und zeigt alles in einer
Web-App, die auf dem iPhone wie eine normale App vom Home-Bildschirm startet.

> Stand: Projektgerüst. Code folgt schrittweise, siehe „Bauplan“ unten.
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

*Wird in Bauschritt 7 ausgefüllt:* LXC-Container anlegen, `deploy/install.sh`
(idempotent: Nutzer, Verzeichnisse, venv, systemd-Units, Tailscale serve),
Enable-Banking-Application einrichten, App koppeln, Kurzbefehl einrichten,
Backups auf die OMV-Freigabe.

Entwicklung lokal:

```bash
cd server && python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt -r requirements-dev.txt
python -m pytest
cd ../web && npm install && npm test && npm run build
```

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
- **Vermögen:** Summe der Kontostände in EUR plus letzter Depotwert. Als
  Kontostand zählt der gebuchte bzw. aktuelle Saldo (`CLBD`, `ITBD`, `XPCD`),
  nicht „verfügbar“ (der enthält den Kreditrahmen).
- **Saldo an einem vergangenen Tag:** letzter Saldo minus die Buchungen
  seither.
- **Fremdwährungen:** EZB-Referenzkurs des Buchungsdatums; ohne Kurs nicht
  in Summen, sondern als „nicht umgerechnet“ gezählt.

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
5. Demo-Daten und lokaler Demo-Server
6. Web-App, Ansicht für Ansicht
7. Server-Betrieb: LXC, install/deploy, systemd, Tailscale, Kopplung
8. Echte Banken: Volksbank Salzburg, dann flatex, PayPal, PayLife
9. Funktionen F1, F8, F9, F11, F12 (F13 später)
10. Release
