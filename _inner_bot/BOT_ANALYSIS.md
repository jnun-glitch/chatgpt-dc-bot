# 🔎 Bot-Gesamtanalyse – aktueller Stand

Stand: 2026-09-05

## Bewertung

**Ca. 8/10 als Entwicklungsstand.** Das Repository ist bereits ein modularer All-in-One-Discord-Bot mit Cogs für Moderation, AutoMod, Tickets, Musik, Voice/Transkription, KI, Dashboard und Community-Funktionen. Die letzten Core-Probleme wurden bereits gezielt repariert.

## Aktueller Stand

- `commands.Bot` + `setup_hook()` + automatische Cog-Discovery sind vorhanden.
- `on_message()` ruft `process_commands()` auf.
- Slash-Commands werden nach dem Laden der Cogs synchronisiert.
- Zentrale DB-/Permission-Schicht und Health-Endpunkt sind vorhanden.
- Music und Voice sind funktional erweitert.
- CI kompiliert Python, führt Tests aus und macht einen Import-Smoke-Test.
- Die letzte CI-Ausführung auf `main` war erfolgreich.
- `python-dotenv` ist in `requirements.txt`; `sitecustomize.py` lädt `_inner_bot/.env` bereits beim Interpreter-Start. **Ein zusätzlicher `.env`-Fix in `bot.py` ist daher nicht notwendig.**

## 🐞 Wichtigste technische Risiken

### 1. AutoMod vereinheitlichen
`automod.py` verwendet noch direkte Bad-Word-RegEx-Logik. Das sollte auf eine gemeinsame API aus `core/badwords.py` umgestellt werden, damit Normalisierung und Regeln nicht an zwei Stellen auseinanderlaufen.

Außerdem sollten Warn-/Strike-Zustände persistent werden, statt nur im RAM zu liegen.

### 2. `!ai` modernisieren
Die Ticket-AI wird aktuell über `on_message()` und `!ai` ausgelöst. Discord behandelt Message Content als privilegierten Intent und hat 2026 die Anforderungen rund um privilegierte Datenzugriffe verschärft. Deshalb sollte die AI-Analyse langfristig als Slash-/Context-Command laufen. citeturn1search0turn0search2

### 3. Zu breite Intents
`bot.py` nutzt `discord.Intents.all()`. Das ist funktional, aber langfristig unnötig breit. Nach einem Intent-Audit sollte nur das aktiviert werden, was die tatsächlich verwendeten Cogs benötigen. Privilegierte Intents benötigen besondere Behandlung, insbesondere bei verifizierten Apps. citeturn1search0turn1search7

### 4. AI-Concurrency
Teure KI-Operationen sollten pro User/Guild begrenzt werden. discord.py bietet Application-Command-Cooldowns und Concurrency-Mechanismen, die dafür geeignet sind. citeturn1search3turn1search1

### 5. Datenbank
`core/db.py` ist weiterhin zu groß und bündelt mehrere fachliche Bereiche. Mittelfristig sollte die DB-Schicht in Services wie `tickets.py`, `moderation.py`, `levels.py`, `server_config.py`, `giveaways.py` und `stats.py` aufgeteilt werden.

### 6. Dashboard
Der vorhandene Health-Endpunkt ist eine gute Basis. Als nächstes sollten dort echte Diagnosen für DB, APIs, Cogs sowie aktive Voice-/Music-/Ticket-Sessions zusammenlaufen.

## 🔎 Discord-Best-Practices, die für dieses Projekt relevant sind

- Slash Commands und Context Actions verbessern Discovery und standardisieren die Interaktion. citeturn0search1turn0search5
- Discord unterstützt granulare Command Permissions nach Rolle, Mitglied und Channel. Kritische Bot-Aktionen sollten trotzdem zusätzlich zur Laufzeit geprüft werden. citeturn0search6
- Message Content, Guild Members und Guild Presences sind privilegierte Intents. Nur tatsächlich benötigte Daten sollten angefordert werden. citeturn1search0

## 💡 Ausgewählte Verbesserungen – bewusst keine Feature-Flut

### Priorität A – Stabilität
1. AutoMod auf `core/badwords.py` vereinheitlichen.
2. `/ai` als moderner Application Command mit denselben Ticket-Permissions.
3. Cooldown + `max_concurrency` für AI-Analyse.
4. Kritische Commands mit Bot-Permissions und Runtime-Checks härten.

### Priorität B – Persistenz
5. AutoMod-Strikes mit Ablaufzeit speichern.
6. DB-Services schrittweise aus `core/db.py` herauslösen.
7. Migrationen versionieren.

### Priorität C – Diagnose
8. `/diagnostics` bzw. erweitertes `/status`.
9. DB/API/Cog/Voice/Music-Health.
10. strukturierte Fehler- und Command-Metriken.

### Priorität D – Modernisierung
11. Birthday-Cog auf Slash Commands und timezone-aware Datumslogik umstellen.
12. weitere alte Prefix-Commands abbauen.
13. benötigte Intents inventarisieren und `Intents.all()` reduzieren.

## 🧪 Testplan

Zuerst die fehleranfälligen Kernpfade testen, nicht wahllos neue Tests erzeugen:

- AutoMod-Normalisierung und gemeinsame Bad-Word-API
- Permission-Entscheidungen
- Transcript-Escaping
- Social-Alert-Deduplizierung
- Music-Queue-State
- DB-Migrationen
- AI-Cooldown/Concurrency

Die bestehende CI bleibt unverändert und soll weiterhin Compile + Tests + Import-Smoke ausführen.

## 🚀 Nächster Entwicklungsschritt

**Nicht noch einen großen neuen Cog bauen.** Der nächste Sprint soll die vorhandene Architektur stabilisieren: AutoMod-API, `/ai`, AI-Concurrency, Permissions und Tests. Danach folgt Persistenz/Diagnostics und erst anschließend wieder größere neue Features.

Ein konkreter GitHub-Arbeitspunkt wurde dafür als **Issue #1** angelegt.
