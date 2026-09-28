# Steckbrief Finanzen

- Variante: B (Homeserver). Plattform: Web-App (PWA, TypeScript + Svelte),
  vom Server ausgeliefert, auf dem iPhone über „Zum Home-Bildschirm“.
  Server: neuer LXC-Container Debian 13 auf Proxmox, Python-Dienst
  (Flask + waitress, SQLite WAL), systemd, erreichbar nur über Tailscale serve.
- Banken (API, Enable Banking): Volksbank Salzburg (Girokonto mit Gehalt,
  wird zuerst angebunden), flatex (Verrechnungskonto), PayPal, PayLife.
  Ohne API: flatex-Depot per Datei-Import (Format offen); PayLife per
  Datei-Import, falls bei Enable Banking nicht gelistet.
- Funktionen: K1–K5, F1, F2, F4–F8, F9 (Apple Pay über eine
  Kurzbefehle-Automation), F10, F11 (Demo als eigene Adresse, nur lesend), F12.
  Später: F13 (Home Assistant, auf demselben Proxmox). Abgewählt: F3.
- Zeitraum: Gehalt am ~29.; keine gemeinsamen Konten; Apple-Pay-Zahlungen
  eigens markiert (belasten aber die hinterlegte Karte).
- Aussehen: „Finanzen“, Deutsch; ruhig und hell (plus Dunkelmodus nach
  iPhone-Einstellung), Akzent gedecktes Grün mit Kupfer. Startseite:
  Ausgaben → Kategorien → nach Karte → 12-Monats-Trend → Vermögensverlauf →
  Konten. Kennzahlen ohne Cent, Listen mit Cent. Icon: Vorschlag folgt.
- Betrieb: Abrufe 06:30 und 18:30 plus manuell; Tailscale auf Server und
  iPhone vorhanden; Ablauf-Warnung der Bankzustimmung nur in der App;
  Backups nächtlich mit age verschlüsselt, 14 behalten, Ablage auf
  OMV-Freigabe (NFS/SMB) auf eigenen physischen Platten; privater
  age-Schlüssel nur offline/Passwort-Manager; Cloud-Kopie optional später.
- Offene Punkte (erst mit echten Daten klärbar):
  - Führt Enable Banking PayLife und flatex?
  - Exportformat PayLife-Portal und flatex-Depot (CSV/Excel/PDF?).
  - Was liefert PayPal (Händler pro Zahlung, Finanzierungszeilen)?
  - Laufzeit der Zustimmung und Historientiefe je Bank (flatex, PayPal,
    PayLife).
- Geklärt mit echten Daten (Volksbank Salzburg, seit 28.09.2026 verbunden):
  Historie reicht bis 2024 zurück; Kartenumsätze kommen mit Händlernamen.
  - Welche Felder gibt die Kurzbefehle-Automation „Transaktion“ auf dem
    iPhone aus (Kartenname, Währung)?

## Funktionen im Detail

| Nr. | Funktion |
| --- | --- |
| K1 | Übersicht: Ausgaben im laufenden Zeitraum, Vergleich zum Vormonat am selben Tag, Einnahmen, Sparquote |
| K2 | Umsatzliste mit Filter (Zeitraum, Konto, Kategorie, Suche) und Detailansicht |
| K3 | Kategorien mit eigenen Händler-Regeln, in der App änderbar |
| K4 | Konten und Bankverbindungen, Zustimmung erneuern |
| K5 | Umbuchungen und Duplikate erkennen, unsichere Fälle zur Bestätigung |
| F1 | Datei-Import (CSV, XLSX, XLS) für PayLife und flatex-Depot, Dateiauswahl in der App |
| F2 | Budget-Zeitraum von Gehalt zu Gehalt (~29.) |
| F4 | Karten-Auswahl auf der Startseite, Diagramm „Ausgaben nach Karte“ |
| F5 | Vermögensverlauf (1 M bis alles), inkl. Depotwert |
| F6 | Budget-Anzeige in der Umsatzliste: Rest, Einnahmen, Ausgegeben, Übrig pro Tag |
| F7 | Erkunden: Sankey Einnahmen → Konten → Kategorien mit ziehbarer Zeitleiste |
| F8 | Fremdwährungen mit EZB-Kursen zum Buchungsdatum |
| F9 | Apple-Pay-Zahlungen sofort als vorgemerkte Buchung (iOS-Kurzbefehl → Server) |
| F10 | Offline-Anzeige des letzten Stands (Service Worker) |
| F11 | Demo-Version mit erfundenen Daten, eigene Adresse, nur lesend |
| F12 | Verschlüsselte nächtliche Backups auf die OMV-Freigabe |
| F13 | *später:* Kennzahlen für Home Assistant über eingeschränkten Token |

## Offen aus dem Bau

- Enable-Banking-API wurde ohne Zugriff auf die Doku umgesetzt und am
  28.09.2026 gegen die API-Referenz geprüft: Endpunkte, JWT und Felder
  stimmen, Fehlercodes korrigiert. Offen bis zur ersten echten Bank: welcher
  Fehlercode bei abgelehnter PSU-IP kommt (Annahmen in
  `server/finanzen/bank/enablebanking.py`).
- `deploy/install.sh` ist nur per Syntaxprüfung und Probelauf geprüft, noch
  nicht auf einem Server ausgeführt.
- flatex-Depot: vorerst Depotwert per Hand; Import erst, wenn eine echte
  Exportdatei vorliegt.
