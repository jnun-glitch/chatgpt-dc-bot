# ScratchAI Bot V2 – Ausbau ohne Minecraft-Connector

Der Minecraft-Connector bleibt bewusst außen vor. Alle anderen Bereiche werden als eigenständige Module weiterentwickelt.

## Bereits im Projekt vorhanden / ausgebaut

- AI-Chat, Scratch-Spiel-Generator, Analyse und Refinement
- Moderation, AutoMod, Audit-Logging und AFK/Community-Funktionen
- Backups mit Retention
- Creator-Notifications für YouTube, Twitch und X
- Twitch EventSub für schnellere Live-Erkennung, mit Polling als Fallback
- Web-Dashboard mit Live-Nachrichten, Audit, Server-/Member-Ansichten, Executor und Konfiguration
- Slash-Command-Limit-Schutz durch Gruppierung von Overflow-Commands
- automatische Social-Alert-Deduplizierung
- Offline-Simulationen für Twitch/YouTube/X
- bounded Runtime-Monitoring und Systemdiagnostik

## Neue System-Schicht

`core/monitoring.py` hält nur begrenzte Counter, Latenz-Samples und kleine Diagnose-Events. Es werden keine Nachrichteninhalte, Tokens oder Secrets gespeichert.

`cogs/monitoring.py` stellt bereit:

- `/system diagnostics` – Bot, DB, Command-Limit, Cogs und Laufzeit prüfen
- `/system metrics` – Laufzeitmetriken ansehen
- Discord-Ready/Disconnect-Zähler
- Command-Erfolgs-/Fehlerzähler

## Nächste Ausbaustufen

1. AI: einheitliche Request-Limits, bessere Fehlerklassifizierung und Kosten-/Nutzungsmetriken.
2. Moderation: konfigurierbare Regeln pro Server, bessere Eskalationsstufen und belastbare Audit-Fehlerlogs.
3. Dashboard: Metrics-Seite, Systemdiagnose, Notification-Verwaltung und sicherere Admin-Aktionen.
4. Social: Live-State bei Subscription, Retry/Backoff und bessere Provider-Validierung.
5. Tests: Unit-, Integrations- und Offline-End-to-End-Simulationen für alle externen Provider.
6. Deployment: Production-Webserver statt Flask-Development-Server, Healthcheck und graceful shutdown.
7. Minecraft-Connector: erst in einer späteren Phase; bis dahin bleiben die Systeme unabhängig.
