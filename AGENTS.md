# Finanzen

Private Finanzübersicht. Variante B: Python-Dienst auf einem Homeserver
(Proxmox-LXC, Debian 13) plus Web-App (PWA, Svelte + TypeScript), die der
Dienst ausliefert und die auf dem iPhone vom Home-Bildschirm startet.
Spezifikation: [SPEC.md](SPEC.md), Architektur und Rechenregeln: [README.md](README.md).

## Regeln

- Beträge als Integer in Cent (Minor Units); Floats nur an der JSON-Grenze.
  Währungen nur über die Kurstabelle (EZB, Kurs des Buchungsdatums) addieren;
  ohne Kurs aus Summen auslassen und als „nicht umgerechnet“ zählen.
- Bank-Zugriff nur über `server/finanzen/bank/` (Schnittstelle
  `BankProvider`), nie aus API-Routen oder der UI. Die Auswertung in
  `server/finanzen/core/` kennt nur die Datenbank.
- Verknüpfen löscht nie Datensätze. Es ändert nur die abgeleitete Rolle
  (`expense | income | transfer | excluded`) und läuft als Neuberechnung
  über alle Umsätze. Änderungen an Verknüpfung oder Kategorisierung brauchen
  einen Test.
- Entscheidungen des Nutzers (Kategorie, Notiz, bestätigte/abgelehnte
  Vorschläge) überleben jede Neuberechnung und wandern von vorgemerkten zu
  gebuchten Umsätzen mit.
- Kategorie-Vorrang: Wahl des Nutzers → Umbuchung → Händler-Regeln →
  bestätigter Händler → gelernt (selber Händler) → eingebaute Schlagwörter →
  gelernt (Wort) → Sprachmodell → MCC → „Sonstiges“. Gelernt und Sprachmodell
  sind Vorschläge; das Sprachmodell wird nie während der Neuberechnung
  aufgerufen (nur dessen Speicher gelesen).
- Keine Secrets im Repo, auch nicht in Beispielen; Zugangsdaten nur in
  gitignorierten Dateien mit `*.example`-Vorlage. Keine Transaktionsinhalte
  in Logs, keine vollen IBANs in API-Antworten.
- Server: Python ≥ 3.11 (Ziel Debian 13, Python 3.13). Wenige, verbreitete
  Abhängigkeiten mit Wheels; kein Compiler auf dem Server nötig.
- UI-Text Deutsch, Code und Kommentare Englisch.
- Diagramme: Farbe folgt Konto oder Kategorie, nie dem Rang; Palette hell
  und dunkel getrennt, mit Werkzeug auf Kontrast und Farbfehlsichtigkeit
  geprüft; jede Fläche hat eine beschriftete Zeile mit Betrag; keine zwei
  y-Achsen.
- Nach Änderungen: `cd server && python -m pytest`;
  `cd web && npm test && npm run build`.
- Nicht deployen, keine echten Bankdaten anfassen, keine Schlüssel erzeugen
  oder übertragen, außer auf Anweisung. `deploy/deploy.sh` ohne `--apply`
  ist ein Probelauf.
- Meldet der Nutzer eine falsche Zahl: erst die Berechnung an einem
  konkreten Umsatz nachvollziehen, dann ändern.
- Kleine Schritte: nach jedem Schritt Tests, Ergebnis zeigen, Commit.
