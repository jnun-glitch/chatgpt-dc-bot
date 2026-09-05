# 🔎 Bot-Gesamtanalyse – aktueller Stand

Stand: 2026-09-05

## Bewertung

**Aktuell: ca. 8/10 als Entwicklungsstand.**

Das Projekt hat inzwischen viele eigenständige Cogs, eine zentrale DB-Schicht, Dashboard/Health, Ticket-System, DeepSeek-Ticketanalyse, lokale Voice-Transkription und Musik. Die wichtigsten strukturellen Fehler aus der vorherigen Analyse wurden im Core behoben.

## ✅ Gerade behoben

### Bot-Core
- Umstieg von `discord.Client` auf `commands.Bot`.
- `setup_hook()` lädt Extensions vor dem Slash-Command-Sync.
- `on_message()` ruft jetzt `process_commands()` auf, sodass klassische `!`-Commands wieder funktionieren.
- Cogs werden automatisch aus `cogs/*.py` entdeckt, statt dass eine veraltete manuelle Liste gepflegt werden muss.
- Einzelne kaputte Cogs verhindern nicht mehr den kompletten Start; der Fehler wird protokolliert.

### Permissions
- Zentrale Permission-Helfer in `core/permissions.py`.
- Server-Konfiguration ist auf Administratoren bzw. Manage-Server beschränkt.
- `/config-reset` nutzt jetzt die vorhandene `set_guild_config`-Schicht statt eine nicht existierende `key`-Spalte in `guild_config` anzusprechen.

### Musik
Die Music-Cog wurde erweitert um:
- Play
- Pause/Resume
- Skip
- Stop
- Queue
- Remove
- Clear
- Shuffle
- Loop/Repeat
- Lautstärke
- Now Playing

Die aktuelle Architektur bleibt bewusst leichtgewichtig mit yt-dlp + FFmpeg. Für sehr große Bots wäre später Lavalink/Wavelink die nächste Ausbaustufe.

### Voice-Transkription
- lokale Spracherkennung mit `faster-whisper`
- keine OpenAI-API für Voice nötig
- Speicherung unter einem zentralen Datenordner
- Dateiname enthält die bisher erkannten Sprecher
- Live-Ausgabe in Discord
- `/voice history`
- `/voice clear`
- Audio wird nicht als Datei vom Voice-Cog persistiert

### Ticket-Transcripts
- HTML-Ausgabe wird jetzt escaped, bevor Benutzertexte in HTML eingesetzt werden.
- Ticket-Transcripts landen im zentralen Transcript-Datenpfad.

### Abhängigkeiten / Betrieb
- `faster-whisper` und `python-dotenv` stehen in `requirements.txt`.
- `.gitignore` schützt `.env`, DB-/Runtime-Daten, Logs und lokale Transcripts vor versehentlichem Commit.

### Tests / CI
- GitHub Actions prüft Python-Kompilierung, Tests und einen Import-Smoke-Test.
- Erste automatisierte Tests decken die zentrale Permission-Schicht ab.

## 🔴 Noch offene Punkte

### 1. Datenbankarchitektur
`core/db.py` ist weiterhin sehr groß und bündelt viele fachlich unterschiedliche Bereiche. Langfristig sollten einzelne Services entstehen, etwa:

```text
core/data/
  tickets.py
  moderation.py
  levels.py
  server_config.py
  giveaways.py
  stats.py
```

Die SQLite-Verbindung ist global gecacht. Für mehrere Prozesse/Instanzen sollte später eine klar definierte DB-Abstraktion oder PostgreSQL eingeplant werden.

### 2. AutoMod
`automod.py` greift direkt auf `_BAD_WORD_RE` zu. Dadurch kann ein Teil der neueren Normalisierungslogik aus `core/badwords.py` umgangen werden. Das sollte auf eine gemeinsame `find_bad_word()`- bzw. `check_text()`-API umgestellt werden.

Außerdem sind einige Warn-/Timeout-Counter nur im Speicher. Nach einem Bot-Neustart gehen diese Zustände verloren.

### 3. Birthday-Cog
`birthdays.py` verwendet klassische Textcommands und alte direkte DB-Zugriffe. Die Tabelle muss garantiert durch `init_db()` existieren und die Zeitbehandlung sollte konsequent timezone-aware werden.

### 4. Private VC / VC-Protect
Beide Cogs reagieren auf Voice-State-Events. Ihre Zuständigkeiten sollten klar getrennt werden, damit Schutzregeln, temporäre Channels und Voice-Receive nicht unerwartet miteinander kollidieren.

### 5. Musik
Die aktuelle Music-Cog ist deutlich besser, aber noch kein vollwertiges Lavalink-System. Für größere Server sind später Backend-Ausfallsicherheit, Playlists, bessere Plattformunterstützung, Caching und persistente Queue-Zustände sinnvoll.

### 6. Dashboard
Der Health-Endpunkt ist vorhanden, aber das Dashboard sollte noch echte Module anzeigen:
- DB-Status
- API-Status
- letzte Fehler
- Command-Nutzung
- aktive Tickets
- Voice-Sessions
- Music-Sessions

### 7. Permission-System
`core/permissions.py` ist der Anfang. Das Ziel sollte ein serverkonfigurierbares Regelwerk wie bei Red-DiscordBot sein: global, pro Server, pro Rolle, pro User und pro Channel. Red ist explizit modular aufgebaut und erlaubt das Aktivieren/Deaktivieren von Cogs sowie umfangreiche Konfiguration und Community-Cogs. Die Architektur ist deshalb eine gute Referenz, aber kein Code soll kopiert werden.

## 🆕 Analyse 2026-09-05: Discord-Best-Practices

Discord dokumentiert weiterhin Slash Commands, Kontextaktionen und granulare Command Permissions als bevorzugte Interaktionswege. Commands können serverseitig pro Rolle, Mitglied und Channel eingeschränkt werden. citeturn0search4turn0search6

Discord hat außerdem 2026 die Anforderungen rund um privilegierte Datenzugriffe verschärft. `MESSAGE_CONTENT`, `GUILD_MEMBERS` und `GUILD_PRESENCES` sind privilegierte Intents; insbesondere Message Content sollte nur dort verwendet werden, wo die Funktion ihn wirklich benötigt. citeturn0search2turn1search0

### Daraus abgeleitete Prioritäten
1. Prefix-Command-Abhängigkeiten weiter reduzieren, insbesondere `!ai` als Message-Content-Hook.
2. Wo möglich Slash-/Context-Commands verwenden, damit der Bot weniger auf Message Content angewiesen ist.
3. Bot-Permissions zusätzlich mit `bot_has_permissions()` bzw. Runtime-Prüfungen absichern.
4. Für teure KI-/Voice-Operationen Cooldowns und maximale Parallelität einsetzen.
5. Nur benötigte Gateway-Intents aktivieren, statt dauerhaft `Intents.all()` zu verlangen, sobald die einzelnen Cogs entsprechend umgebaut sind.

Discord.py unterstützt für Application Commands eigene Cooldowns; außerdem gibt es `max_concurrency`, was besonders für teure oder exklusiv laufende Operationen sinnvoll ist. citeturn1search3turn1search1

## 💡 Ausgewählte sinnvolle neue Ideen

Nicht ausgewählt wurden reine Fun-Features, weil das Projekt bereits viele Community-/Fun-Cogs besitzt. Sinnvoller sind Verbesserungen, die mehrere bestehende Systeme stabiler machen:

### A. `/ai` als echter Slash-Command
- ersetzt den speziellen `!ai`-Message-Hook
- behält Ticket-Berechtigungsprüfung
- kann mit Cooldown versehen werden
- reduziert langfristig die Abhängigkeit von `MESSAGE_CONTENT`

### B. Bot-Diagnostics
Neuer kleiner Admin-/Owner-Diagnosebereich:
- DB erreichbar?
- welche Cogs geladen?
- welche externen APIs konfiguriert?
- letzte Fehler
- Gateway-Latenz
- Voice-/Music-Sessions
- Anzahl aktiver Tickets

Das passt direkt zur bestehenden `/status`- und `/health`-Architektur, statt ein separates Monitoring-System einzuführen.

### C. Persistente AutoMod-Strikes
Warn-/Strike-Zustände in SQLite speichern und mit Ablaufzeit versehen. Damit überlebt die Eskalationslogik Neustarts und kann sauber getestet werden.

### D. Gemeinsame Permission-/Error-Schicht
Cogs sollten möglichst dieselben Permission-Helfer und dieselbe Fehlerausgabe verwenden. Discord bietet bereits granulare Command Permissions; die eigene Runtime-Schicht bleibt trotzdem nötig für kritische Aktionen. citeturn0search6

### E. Test-Härtung
Nicht blind 100 neue Tests schreiben, sondern zuerst die fehleranfälligen Kernpfade testen:
- AutoMod-Normalisierung
- Permission-Entscheidungen
- Transcript-Escaping
- Social-Alert-Deduplizierung
- Music-Queue-State
- DB-Migrationen

## 🐞 Gefundene Bugs / technische Risiken

### Hoch
- `bot.py` verwendet aktuell `BOT_TOKEN = os.environ.get("DISCORD_TOKEN", "").strip()` und lädt `.env` nicht selbst. Obwohl `python-dotenv` installiert ist, ist ein lokaler Start dadurch davon abhängig, dass die Umgebung den Wert bereits gesetzt hat. Das sollte in einem kleinen, gezielten Core-Fix behoben werden.
- `bot.py` setzt `discord.Intents.all()`. Das ist funktional bequem, fordert aber mehr privilegierte Zugriffe als viele Features tatsächlich benötigen. Der Intent-Bedarf sollte pro Cog inventarisiert und anschließend minimiert werden. citeturn1search0

### Mittel
- `!ai` hängt an `on_message()` und Message Content. Ein Slash-Command wäre langfristig robuster und näher an Discords aktuellem App-Modell. citeturn0search2turn0search6
- KI-Ticketanalyse hat keinen sichtbaren Application-Command-Cooldown bzw. keine `max_concurrency`-Sperre im Entry-Point. Bei mehreren parallelen Analysen können unnötig viele teure Operationen gestartet werden. Discord.py bietet dafür passende Mechanismen. citeturn1search3
- `list_` im Social-Cog muss zwar die 2000-Zeichen-Grenze berücksichtigen, nutzt aber mehrere Follow-ups; das ist grundsätzlich okay, sollte jedoch als wiederverwendbarer Pagination-Helper vereinheitlicht werden.

### Niedrig
- Der Health-Endpunkt zeigt bereits wichtige Runtime-Daten, aber keine DB/API-Checks.
- `restart_count` ist ein Prozesswert und deshalb keine echte Restart-Historie.

## 🚀 Nächster Entwicklungsplan

### Schritt 1 – Stabilität zuerst
1. `.env`-Laden im Entry-Point sauber machen.
2. `/ai` als Slash-Command hinzufügen und `!ai` danach nur noch als Übergang behandeln.
3. Cooldown + `max_concurrency` für AI-Analyse.
4. Bot-Permissions für kritische Commands explizit prüfen.
5. AutoMod auf gemeinsame `core/badwords.py`-API umstellen.

### Schritt 2 – Persistenz
6. AutoMod-Strikes persistent machen.
7. DB-Service-Schicht schrittweise aus `core/db.py` herauslösen.
8. Versionierte Migrationen ergänzen.

### Schritt 3 – Observability
9. `/diagnostics`/erweitertes `/status`.
10. DB/API/Voice/Music-Health.
11. strukturierte Fehler-/Command-Metriken.

### Schritt 4 – Modernisierung
12. Birthday-Cog auf Slash Commands + timezone-aware Datumslogik umstellen.
13. weitere alte Prefix-Commands abbauen.
14. benötigte Intents minimieren.

## 🎯 Zielarchitektur

```text
Discord
  │
  ├── Slash / Context Commands
  ├── Events (nur notwendige Intents)
  └── UI Views / Modals
          │
          ▼
      Cog Layer
          │
          ├── Moderation
          ├── AutoMod
          ├── Tickets
          ├── Community
          ├── Music
          ├── Voice
          ├── Minecraft
          └── Dashboard
          │
          ▼
      Core Services
          │
          ├── Permissions
          ├── Config
          ├── Database
          ├── Logging
          ├── Metrics
          ├── Transcript Storage
          └── API Clients
          │
          ▼
        Tests + CI
```

## Fazit

Ich würde **jetzt nicht noch einen großen neuen Feature-Cog bauen**. Der sinnvollste nächste Schritt ist ein kleiner Stabilitäts-Sprint: `.env`-Startpfad, `/ai`-Modernisierung, AI-Concurrency/Cooldown, Permission-Härtung und AutoMod-API-Vereinheitlichung. Danach lohnt sich erst die nächste größere Feature-Runde.
