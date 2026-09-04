# 🤖 ScratchAI Discord Bot

> Ein umfangreicher, modularer Discord-Bot für SMPs, Communities und Gaming-Server – mit Moderation, AutoMod, Tickets, Musik, Voice-Transkription, KI, Dashboard, Rollen-/Channel-Setup, Levelsystem und vielen Community-Features.

[![CI](https://github.com/jnun-glitch/chatgpt-dc-bot/actions/workflows/ci.yml/badge.svg)](https://github.com/jnun-glitch/chatgpt-dc-bot/actions/workflows/ci.yml)

## ✨ Was ist ScratchAI?

ScratchAI ist ein modular aufgebauter Discord-Bot auf Basis von **Python 3.12** und `discord.py`. Die einzelnen Funktionen sind als Cogs organisiert und können unabhängig voneinander weiterentwickelt werden.

Der Fokus des Projekts liegt auf einem Bot, der nicht nur einzelne Commands anbietet, sondern ein komplettes Server-System abbildet:

- 🛡️ Moderation & Sicherheitsfunktionen
- 🤖 intelligenter AutoMod
- ⚙️ automatisches SMP-Server-Setup
- 🎭 Rollen & Berechtigungen
- 📋 Audit- und Moderationslogs
- 🎫 Tickets & Support
- 🎵 Musik & Voice
- 🎙️ lokale Voice-Transkription
- 🧠 KI-Funktionen
- 🌐 Web-Dashboard
- ⭐ Level-/XP-System
- 🎉 Giveaways
- 🎭 Reaction Roles
- 🎂 Geburtstage
- 💤 AFK-System
- 🔢 Counting
- 👥 Community-Funktionen
- 🎮 Fun-Features
- 📊 Aktivitätsfunktionen
- 🆘 dynamisches Help-System

---

# 🚀 Features

## ⚙️ Server- & SMP-Setup

Mit `/setup-smp` kann ein Server weitgehend automatisch eingerichtet werden.

Das Setup-System kann unter anderem:

- SMP-Kategorien und Channels anlegen
- Text- und Voice-Channels erstellen
- Start-/Infotexte vorbereiten
- Rules-/Regelbereiche einrichten
- Standardrollen erstellen bzw. reparieren
- Staff-Channels absichern
- Rollen-Hierarchie prüfen
- vorhandene Standardrollen auf definierte Berechtigungen zurücksetzen
- Server-Strukturen möglichst idempotent einrichten

Zusätzlich gibt es `/setup-roles` für die Rollenverwaltung.

### 🔐 Sicherheitsorientierte Rollenstruktur

Das Projekt verwendet eine definierte Standard-Hierarchie, unter anderem mit:

`Owner → Manager → Bot Manager → Admin → Moderator → Supporter → Media → VIP → Member → Verified`

Zusätzliche Projektrollen wie `News`, `Dev Updates`, `Events`, `PowerBot`, `ScratchAI Bot` und `GalaxyBot` können ebenfalls berücksichtigt werden.

Standardrollen werden nicht einfach mit beliebigen Serverrechten ausgestattet. Kritische Berechtigungen werden kontrolliert, damit z. B. eine normale Member-/Support-Rolle nicht versehentlich Channel- oder Rollenverwaltung erhält.

Der Bot prüft außerdem seine eigene Rollenposition, weil Discord Aktionen wie das Verwalten bestimmter Rollen von der Bot-Hierarchie abhängig macht.

---

# 🛡️ Moderation

Das Moderationssystem bietet klassische Server-Moderation und Permission Checks.

Dazu gehören unter anderem:

- Bans
- Unbans
- Moderationsaktionen
- Permission-/Staff-Prüfungen
- geschützte Rollen
- geschützte Staff-Bereiche
- zentrale Log-Ausgaben

Moderationsfunktionen prüfen nicht nur den Command-Decorator, sondern wichtige Aktionen zusätzlich zur Laufzeit.

---

# 🤖 AutoMod

Der AutoMod ist deutlich umfangreicher als ein einfacher Bad-Word-Filter.

### Erkennung

Aktuell werden unter anderem folgende Regeln unterstützt:

- 🔗 Links
- 💬 Discord-Invites
- ⚡ Spam
- 🔁 doppelte Nachrichten
- 📢 zu viele Mentions
- 🔠 übermäßige Großschreibung
- 🤬 Bad Words
- 😀 übermäßige Emoji-Nutzung
- ↩️ übermäßig viele Zeilen
- 🚨 Raid-/Join-Erkennung
- 👶 zusätzliche Prüfungen für sehr neue Accounts
- 🌐 verdächtige URLs
- 🔤 IDN/Punycode-bezogene verdächtige Hosts
- 🌍 erlaubte Domains / Domain-Allowlist

Verdächtige URLs werden nicht nur anhand eines simplen `http`-Strings erkannt. Das System berücksichtigt unter anderem Hostnamen, Punycode, IPv4-Hosts, Userinfo und verdächtige TLDs.

### Maßnahmen

Je nach Regel kann AutoMod:

1. eine Nachricht erkennen,
2. die Nachricht entfernen,
3. einen Verstoß protokollieren,
4. eine Warnung auslösen,
5. bei wiederholten Verstößen eskalieren.

Raid-Erkennung und Ausnahmen für Staff-/Log-Bereiche sind ebenfalls integriert.

### AutoMod-Konfiguration

Es gibt Konfigurationsmöglichkeiten zum:

- Anzeigen der aktuellen Einstellungen
- Aktivieren/Deaktivieren einzelner Regeln
- Ändern von Limits
- Verwalten erlaubter Domains
- Verwalten blockierter Domains
- Anzeigen der Domainlisten
- Anzeigen des Raid-Status
- Zurücksetzen der AutoMod-Konfiguration

---

# 📋 Audit Log

Das Audit-System überwacht wichtige Serveränderungen und erstellt zentrale Logs.

Erfasst werden unter anderem:

- Nachrichten
- Nachrichtenänderungen
- gelöschte Nachrichten
- Bulk Deletes
- Serverbeitritte
- Serververlasser
- Bans
- Unbans
- Rollenänderungen
- Channeländerungen
- Voice-Änderungen
- Pins
- weitere relevante Serverevents

Wo Discord entsprechende Audit-Log-Daten bereitstellt, wird versucht, den ausführenden Benutzer zuzuordnen.

Die Logs können über einen zentralen Admin-/Audit-Channel ausgegeben werden.

> Hinweis: Discord stellt nicht für jedes Event eine perfekte Zuordnung zu einem einzelnen Benutzer bzw. einer einzelnen Nachricht bereit. Das System nutzt deshalb die verfügbaren Discord-Audit-Daten und Eventinformationen.

---

# 🎫 Tickets & Support

Das Projekt enthält ein Ticket-/Support-System für Communities.

Geplant bzw. integriert sind typische Support-Workflows wie:

- Ticket-Erstellung
- Support-Kanäle
- Staff-Zugriff
- geschützte Ticketbereiche
- Ticket-Verwaltung
- Support-Kommunikation

Das System ist für eine spätere Erweiterung mit KI-Ticketanalyse vorbereitet.

---

# 🧠 KI

ScratchAI besitzt ein eigenes KI-Cog und kann für AI-basierte Funktionen verwendet werden.

Die Architektur ist so aufgebaut, dass KI-Funktionen nicht fest in die komplette Bot-Logik eingebaut werden müssen.

Zusätzlich existiert eine Vorbereitung für externe Ticketanalyse über einen n8n-Webhook.

Beispiel-Konfiguration:

```env
N8N_WEBHOOK_URL=http://localhost:5678/webhook/ticket-analyze
```

---

# 🎵 Musik

Das Musiksystem basiert auf Voice-Channel-Wiedergabe und `yt-dlp`.

Unterstützt werden unter anderem:

- ▶️ Play
- ⏸️ Pause
- ▶️ Resume
- ⏭️ Skip
- ⏹️ Stop
- 🗑️ Queue-Einträge entfernen
- 🧹 Queue leeren
- 🔀 Shuffle
- 🔁 Loop
- 🔊 Lautstärke

### 🔐 Music-Sicherheit

Nicht jeder Benutzer darf den Bot beliebig aus einem Voice-Channel verschieben oder einen fremden Player übernehmen.

Die Music-Control-Logik unterscheidet zwischen:

- berechtigten Staff-/Admin-Benutzern
- Benutzern im gleichen Voice-Channel
- Benutzern außerhalb des aktuellen Voice-Channels

Dadurch wird verhindert, dass normale Benutzer den Musikplayer eines anderen Channels übernehmen.

---

# 🎙️ Voice & Transkription

Das Voice-System kann Voice-Channels beitreten und verlassen und unterstützt lokale Speech-to-Text-Verarbeitung über **faster-whisper**.

### Voice-Befehle

- `/voice join`
- `/voice leave`
- `/voice transcribe`
- `/voice status`
- `/voice history`
- `/voice clear`

Administrative Voice-Funktionen sind geschützt und erfordern entsprechende Serverrechte.

### 📝 Transkription

Die Transkription:

- verarbeitet Voice-Audio lokal über faster-whisper
- arbeitet in konfigurierbaren Audio-Chunks
- kann Sprecherinformationen berücksichtigen
- speichert Transkripte nach Server und Datum
- kann Transkript-Ausgaben in einen Text-Channel senden
- bietet eine History-/Verwaltungsfunktion

Standardmäßig wird ein Whisper-Modell wie `base` verwendet und auf CPU mit `int8` ausgeführt.

### 🛡️ Voice AutoMod Review

Ein wichtiges Sicherheitsprinzip des Projekts:

**Voice-Erkennung bestraft niemanden automatisch.**

Wenn eine Transkription ein konfiguriertes Bad Word erkennt:

1. wird der Treffer erkannt,
2. wird ein Hinweis im geschützten `#bad-word-log` erstellt,
3. die Moderatoren werden benachrichtigt,
4. der erkannte Text wird als Kontext angezeigt,
5. ein Moderator entscheidet manuell, ob eine Aktion notwendig ist.

Es gibt also **keinen automatischen Timeout/Ban aufgrund eines Voice-Transkriptions-Treffers**.

---

# 🌐 Dashboard

Das Projekt enthält ein Web-Dashboard-Cog und eine Web-App-Anbindung.

Die Dashboard-Integration ist über die Konfiguration mit der Bot-Webapp verknüpft.

```env
WEBAPP_URL=https://example.com
BOT_SECRET=change-me
```

Das Dashboard kann als Grundlage für eine spätere zentrale Serververwaltung dienen, ohne dass alle Einstellungen ausschließlich über Discord geändert werden müssen.

---

# ⭐ Level & XP

Das Projekt besitzt ein Level-/Aktivitätssystem mit Rollenfortschritt.

Beispielhafte Levelrollen:

- Level 5 → `Scratcher`
- Level 10 → `Pro`
- Level 20 → `Master`

Die Levelrollen können über die Bot-Konfiguration angepasst bzw. erweitert werden.

---

# 🎭 Reaction Roles

Reaction Roles ermöglichen es Mitgliedern, Rollen über Interaktionen auszuwählen.

Das System ist als eigener Cog aufgebaut und kann unabhängig von den Moderations- und Adminfunktionen erweitert werden.

Typische Anwendungsfälle:

- Benachrichtigungsrollen
- Community-Rollen
- Event-Rollen
- Spiele-/SMP-Rollen
- Interessenrollen

---

# 🎉 Giveaways

Das Giveaway-System ist als eigener Cog integriert.

Es bildet die Grundlage für zeitlich begrenzte Community-Gewinnspiele und die Verwaltung von Teilnehmern/Gewinnern.

---

# 🎂 Geburtstage

Das Birthday-System verwaltet Geburtstagsdaten und kann für Community-Benachrichtigungen verwendet werden.

---

# 💤 AFK

Das AFK-System ermöglicht es Mitgliedern, einen AFK-Status zu setzen.

Der Bot kann bei Interaktionen mit einem AFK-Benutzer auf dessen Status hinweisen und den Status beim Zurückkehren berücksichtigen.

---

# 🔢 Counting

Das Counting-System stellt eine klassische Community-Counting-Funktion bereit.

Es kann als eigenes Feature aktiviert und unabhängig von anderen Community-Systemen betrieben werden.

---

# 👥 Community

Community-Funktionen sind in einem eigenen Cog organisiert und können unabhängig erweitert werden.

Damit bleibt die eigentliche Bot-Struktur modular, statt sämtliche Community-Features in einer einzigen Datei zu bündeln.

---

# 🎮 Fun

Zusätzliche Fun-/Community-Funktionen befinden sich in einem eigenen Cog.

Dadurch können Unterhaltungssysteme hinzugefügt oder verändert werden, ohne Moderation, Musik oder Administration anzufassen.

---

# 📊 Aktivität

Das Projekt besitzt außerdem ein Activity-System zur Verarbeitung von Aktivitätsdaten bzw. Community-Aktivität.

Dieses kann mit Level-, Statistik- und Dashboard-Funktionen zusammenspielen.

---

# 🆘 Dynamisches Help-System

`/help` ist nicht einfach eine statische Command-Liste.

Das Help-System erkennt geladene Commands und gruppiert sie nach Bereichen.

Aktuelle Kategorien umfassen unter anderem:

- 🛡️ Moderation
- ⚙️ Administration
- 🎫 Tickets
- 🤖 AutoMod
- 🎵 Music
- 🎙️ Voice
- 🌐 Server
- ⭐ Level
- 🎉 Giveaways
- 🎭 Reaction Roles
- 🏗️ Schematics

Dadurch bleibt die Hilfe auch bei neuen Commands leichter aktuell.

---

# ⚙️ Konfiguration

Der Bot besitzt ein zentrales Config-System.

Verfügbare Verwaltungsfunktionen umfassen unter anderem:

- `/config`
- `/config-set`
- `/config-reset`
- `/bot modus`
- `/status`
- `/help`

Das Config-System dient als zentrale Grundlage für serverbezogene Einstellungen.

---

# 🔐 Sicherheit

Sicherheit ist ein zentraler Bestandteil des Projekts.

### Geschützte Rollen

Bestimmte Rollen werden als besonders kritisch behandelt, darunter beispielsweise:

- Owner
- Manager
- Bot Manager
- Moderator

### Geschützte Staff-Channels

Für interne Moderationsinformationen existieren geschützte Bereiche wie:

- `#staff-movements`
- `#bad-word-log`
- `#audit-log`

Diese Channels werden mit privaten Berechtigungen eingerichtet bzw. repariert.

### Permission Checks

Wichtige Adminfunktionen verlassen sich nicht ausschließlich auf die Anzeige von Slash-Command-Berechtigungen. Kritische Aktionen führen zusätzliche Runtime-Checks durch.

### Bot-Hierarchie

Der Bot prüft, ob seine höchste Rolle hoch genug in der Discord-Rollenhierarchie steht. Wenn das nicht der Fall ist, wird eine Warnung protokolliert, statt stillschweigend falsche Annahmen zu machen.

---

# 🏗️ Projektstruktur

```text
chatgpt-dc-bot/
├── .github/
│   └── workflows/
│       └── ci.yml
├── _inner_bot/
│   ├── bot.py
│   ├── requirements.txt
│   ├── core/
│   │   ├── config.py
│   │   ├── permissions.py
│   │   ├── roles.py
│   │   ├── logging.py
│   │   └── badwords.py
│   ├── cogs/
│   │   ├── active.py
│   │   ├── admin.py
│   │   ├── afk.py
│   │   ├── ai.py
│   │   ├── audit.py
│   │   ├── automod.py
│   │   ├── birthdays.py
│   │   ├── community.py
│   │   ├── counting.py
│   │   ├── dashboard.py
│   │   ├── fun.py
│   │   ├── giveaways.py
│   │   ├── help.py
│   │   ├── music.py
│   │   ├── reactionroles.py
│   │   ├── serverconfig.py
│   │   ├── voice.py
│   │   └── weitere Feature-Cogs
│   ├── data/
│   ├── transcripts/
│   └── tests/
└── README.md
```

Die Cogs werden dynamisch geladen. Dadurch kann die Bot-Architektur modular erweitert werden.

---

# 🧰 Tech Stack

| Bereich | Technologie |
|---|---|
| Sprache | Python 3.12 |
| Discord | `discord.py` |
| Voice | `PyNaCl`, Discord Voice APIs |
| Musik | `yt-dlp` |
| Speech-to-Text | `faster-whisper` |
| Web | Flask |
| KI | OpenAI Python SDK |
| Automatisierung | n8n Webhook-Unterstützung |
| Tests | pytest |
| CI | GitHub Actions |

Aktuelle Kernabhängigkeiten sind unter anderem:

```text
discord.py>=2.7.1,<2.8
flask>=3.0.0
PyNaCl>=1.5.0
yt-dlp>=2026.1.0
discord-ext-voice-recv>=0.5.3a
openai>=1.0.0
faster-whisper>=1.2.0
```

---

# 📦 Installation

## 1. Repository klonen

```bash
git clone https://github.com/jnun-glitch/chatgpt-dc-bot.git
cd chatgpt-dc-bot
```

## 2. Python-Umgebung erstellen

```bash
python -m venv .venv
```

### Windows

```powershell
.venv\Scripts\activate
```

### Linux/macOS

```bash
source .venv/bin/activate
```

## 3. Abhängigkeiten installieren

```bash
pip install -r _inner_bot/requirements.txt
```

## 4. Environment konfigurieren

Die Bot-Konfiguration wird aus `_inner_bot/.env` geladen.

Beispiel:

```env
DISCORD_TOKEN=YOUR_DISCORD_BOT_TOKEN

VERIFY_CHANNEL_ID=0
VERIFIED_ROLE_NAME=Verified

WEBAPP_URL=https://example.com
BOT_SECRET=change-me

N8N_WEBHOOK_URL=http://localhost:5678/webhook/ticket-analyze

OWNER_ID=0
ADMIN_LOG_CHANNEL_ID=0

VOICE_TRANSCRIBE_CHUNK_SECONDS=5
VOICE_WHISPER_MODEL=base
VOICE_WHISPER_DEVICE=cpu
VOICE_WHISPER_COMPUTE_TYPE=int8
VOICE_REVIEW_COOLDOWN=30
```

> **Wichtig:** Niemals Bot-Tokens, Secrets oder andere Zugangsdaten committen.

## 5. Bot starten

```bash
cd _inner_bot
python bot.py
```

---

# 🔑 Environment-Variablen

| Variable | Zweck |
|---|---|
| `DISCORD_TOKEN` | Discord-Bot-Token |
| `VERIFY_CHANNEL_ID` | Channel für Verifizierung |
| `VERIFIED_ROLE_NAME` | Name der Verified-Rolle |
| `WEBAPP_URL` | URL der Web-App / des Dashboards |
| `BOT_SECRET` | Secret für Web-/Bot-Integration |
| `N8N_WEBHOOK_URL` | Optionaler n8n-Webhook für Ticketanalyse |
| `OWNER_ID` | Owner-/Bot-Administrations-ID |
| `ADMIN_LOG_CHANNEL_ID` | zentraler Admin-/Log-Channel |
| `VOICE_TRANSCRIBE_CHUNK_SECONDS` | Länge der Voice-Transkriptions-Chunks |
| `VOICE_WHISPER_MODEL` | faster-whisper Modell |
| `VOICE_WHISPER_DEVICE` | Rechengerät, z. B. `cpu` |
| `VOICE_WHISPER_COMPUTE_TYPE` | Whisper Compute Type, z. B. `int8` |
| `VOICE_REVIEW_COOLDOWN` | Cooldown für Voice-Review-Hinweise |

---

# 🧪 Tests & CI

Das Projekt besitzt eine GitHub-Actions-CI.

Bei Pushes und Pull Requests werden unter anderem ausgeführt:

```bash
python -m compileall -q _inner_bot
pytest -q
PYTHONPATH=_inner_bot python -c "import bot; print('bot import OK')"
```

Dadurch werden Syntax-/Import-Probleme und vorhandene Tests automatisch geprüft.

---

# 🩺 Troubleshooting

## Der Bot startet nicht

Prüfe:

1. Ist `DISCORD_TOKEN` gesetzt?
2. Wurde die virtuelle Python-Umgebung aktiviert?
3. Sind alle Requirements installiert?
4. Läuft der Bot aus dem richtigen Verzeichnis?
5. Sind die benötigten Discord-Intents im Developer Portal aktiviert?

## Rollen werden nicht erstellt oder geändert

Prüfe die Discord-Rollenhierarchie. Die Bot-Rolle muss hoch genug stehen, um die betreffenden Rollen verwalten zu können.

## Musik funktioniert nicht

Prüfe insbesondere:

- Voice-Berechtigungen
- `PyNaCl`
- `yt-dlp`
- erreichbare Audioquelle
- Bot-Zugriff auf den Voice-Channel

## Voice-Transkription funktioniert nicht

Prüfe:

- `faster-whisper`
- Whisper-Modell
- CPU/GPU-Konfiguration
- Voice-Receive-Unterstützung
- Schreibrechte im `transcripts/`-Verzeichnis

---

# 🗺️ Roadmap

Die Architektur ist auf weitere Ausbaustufen vorbereitet.

### 🔴 Priorität

- vollständiges SMP-Setup weiter ausbauen
- Rollen-/Permission-System weiter härten
- Audit-System erweitern
- AutoMod weiter verbessern

### 🟠 Danach

- Tickets weiter ausbauen
- Musik verbessern
- Voice-System erweitern
- Reaction Roles erweitern

### 🟡 Weitere Ausbaustufen

- Dashboard weiter ausbauen
- KI-Features erweitern
- Konfigurationssystem erweitern
- Performance optimieren
- zusätzliche Tests
- CI/CD weiter ausbauen

### 🟢 Langfristig

- bessere Voice-Transkription
- umfangreichere Voice-Auswertung
- tiefere Dashboard-Integration
- mehr Community-/SMP-Automatisierung
- Discord ↔ externe Systeme / Server-Connectoren

---

# 🧩 Entwicklungsprinzipien

Das Projekt folgt einigen wichtigen Grundsätzen:

### Modular statt monolithisch

Neue Funktionen gehören möglichst in einen eigenen Cog oder eine passende Core-Komponente.

### Security first

Berechtigungen werden explizit geprüft. Kritische Rollen und Staff-Channels werden geschützt.

### Keine automatische Voice-Bestrafung

Voice-Transkription dient bei Moderations-Treffern als **Hinweis für Moderatoren**, nicht als automatische Strafmaschine.

### Konfiguration statt Hardcoding

Server- und Feature-Einstellungen sollen möglichst über Config-/Environment-Werte steuerbar bleiben.

### Testbar bleiben

Core-Logik soll unabhängig von Discord-Live-Events getestet werden können.

---

# 🤝 Mitmachen

Pull Requests und Verbesserungen sind willkommen.

Für neue Features:

1. Feature möglichst als eigenen Cog strukturieren.
2. Berechtigungen von Anfang an berücksichtigen.
3. Bestehende Core-Utilities wiederverwenden.
4. Tests für wichtige Logik ergänzen.
5. Keine Secrets in Commits aufnehmen.
6. CI vor dem Merge grün halten.

---

# 📌 Projektstatus

**Aktiv in Entwicklung.**

ScratchAI ist als langfristig erweiterbarer Discord-Bot gedacht. Die aktuelle Architektur bildet bereits Moderation, Sicherheit, Server-Setup, Community, Voice, Musik, KI und Dashboard-Funktionen in getrennten Modulen ab.

---

## ⭐ Wenn dir das Projekt gefällt

Gib dem Repository gerne einen ⭐ und verfolge die Entwicklung.

**ScratchAI – ein Discord-Bot, der nicht nur Commands kann, sondern einen kompletten Server verwalten kann.** 🚀
