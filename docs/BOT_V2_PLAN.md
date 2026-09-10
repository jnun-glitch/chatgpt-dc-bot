# ScratchAI Bot V2 – Stabilitätssprint abgeschlossen

Der Minecraft-Connector bleibt bewusst außen vor. Der aktuelle Stabilitätssprint aus GitHub Issue #1 ist umgesetzt bzw. sicher integriert.

## Erledigt

- AI-Chat, Scratch-Spiel-Generator, Analyse und Refinement bleiben erhalten.
- AutoMod nutzt die gemeinsame `core.badwords`-API.
- AutoMod-Warn-/Timeout-State wird persistent in SQLite gespeichert.
- Ticket-AI ist als `/ticket-ai analyze` verfügbar, mit Berechtigungsprüfung, Cooldown und begrenzter Parallelität.
- Der bestehende `/ai`-Game-Analyse-Command bleibt unangetastet; der frühere `!ai`-Ticketpfad bleibt als Übergang bestehen.
- `/system diagnostics` und `/system metrics` bleiben erhalten.
- `/system health` prüft API-Konfiguration, Datenbank, Voice, Music-Abhängigkeiten, Cogs und Slash-Root-Limit.
- Regressionstests für Custom-Command-Priorität, Ticket-AI-Runtime, AutoMod-Strikes, Transcript-Escaping, Twitch-Deduplizierung und Music-Queue wurden ergänzt.
- Discord-Gateway-Intents wurden inventarisiert und vor einer riskanten Reduzierung dokumentiert.
- Creator-Notifications für YouTube, Twitch und X sowie Twitch EventSub bleiben enthalten.
- `.env`-/Integrationsdokumentation wurde erweitert.

## Warum `/ticket-ai` statt `/ai`

Der Bot besitzt bereits einen `/ai`-Command für Spiel-/Feature-Analyse. Ein Überschreiben hätte diese bestehende Funktion entfernt. Deshalb verwendet die Ticketanalyse den eindeutigen Root `/ticket-ai`, während `!ai` als rückwärtskompatibler Übergang bestehen bleibt.

## Vor einer Intent-Reduzierung

Die Anwendung sollte in der echten Discord-Umgebung getestet werden, insbesondere Prefix-Commands, Verifizierung, Moderation, Tickets und Voice/Music. Erst danach sollte `discord.Intents.all()` schrittweise reduziert werden.
