# ScratchAI Integrationen – `.env` Anleitung

Diese Anleitung erklärt die externen Dienste des Bots. **Geheime Werte gehören nur in `_inner_bot/.env` und niemals in GitHub.**

## 1. Discord

```env
DISCORD_TOKEN=DEIN_DISCORD_BOT_TOKEN
OWNER_ID=DEINE_DISCORD_USER_ID
VERIFY_CHANNEL_ID=
VERIFIED_ROLE_NAME=Verified
WEBAPP_URL=
BOT_SECRET=
ADMIN_LOG_CHANNEL_ID=
```

### Discord Bot Token

1. Öffne das **Discord Developer Portal**.
2. Öffne deine Application.
3. Gehe zu **Bot**.
4. Kopiere den Token und trage ihn bei `DISCORD_TOKEN=` ein.
5. Token niemals posten oder committen. Wenn er versehentlich veröffentlicht wurde: im Developer Portal zurücksetzen.

`OWNER_ID` ist deine Discord User-ID als Zahl.

## 2. Twitch

Der Bot unterstützt Live-Abfragen, Creator-Alerts und EventSub WebSocket. Die normale `!stream <kanal>`-Abfrage verwendet App-/Client-Credentials.

### Twitch App erstellen

1. Öffne die **Twitch Developer Console**.
2. Erstelle eine neue Application.
3. Kopiere **Client ID**.
4. Erzeuge das zugehörige **Client Secret**.
5. Trage beides ein:

```env
TWITCH_CLIENT_ID=DEINE_CLIENT_ID
TWITCH_CLIENT_SECRET=DEIN_CLIENT_SECRET
TWITCH_DEFAULT_CHANNEL=dein_twitch_name
TWITCH_EVENTSUB_ENABLED=1
```

Für die normale Abfrage reicht `TWITCH_CLIENT_ID` + `TWITCH_CLIENT_SECRET`.

### Optional: EventSub WebSocket

Der vorhandene EventSub-Weg kann einen User Access Token verwenden:

```env
TWITCH_USER_ACCESS_TOKEN=DEIN_USER_ACCESS_TOKEN
```

Nicht benötigte Token-Felder leer lassen. Tokens sind geheim und gehören nicht nach GitHub.

### Test

```text
!stream dein_twitch_name
!live dein_twitch_name
```

Mit `TWITCH_DEFAULT_CHANNEL` kann auch `!stream` ohne Kanalargument verwendet werden.

## 3. YouTube

Für `!youtube` wird die **YouTube Data API v3** verwendet.

1. Öffne die **Google Cloud Console**.
2. Erstelle ein Projekt oder wähle dein Bot-Projekt.
3. Aktiviere **YouTube Data API v3**.
4. Öffne **APIs & Services → Credentials**.
5. Erstelle einen **API Key**.
6. Eintragen:

```env
YOUTUBE_API_KEY=DEIN_GOOGLE_API_KEY
```

Test:

```text
!youtube @kanalname
```

oder mit einer Channel-ID:

```text
!youtube UCxxxxxxxxxxxxxxxxxxxx
```

Es wird kein YouTube-Passwort benötigt.

## 4. Wetter – kein API-Key nötig

Der Wetter-Status verwendet Open-Meteo.

```text
!weather 48.897 9.192
```

Es muss kein `WEATHER_API_KEY` gesetzt werden.

## 5. Minecraft-Status

Der Minecraft-Status bleibt vom Minecraft-Connector getrennt. Für einen öffentlichen Serverstatus braucht der Bot keinen Minecraft-Plugin-Zugriff.

```text
!mcstatus farlandssmp.net
!mc farlandssmp.net
```

Für echte Server-Steuerung wäre später ein separater Minecraft-Connector nötig.

## 6. Website-Status

Der Bot darf keine beliebigen URLs aus Discord abrufen. Deshalb gibt es eine Domain-Whitelist.

```env
WEBSITE_STATUS_DOMAINS=scratch-ai-24bv.onrender.com,example.com
```

Danach:

```text
!webstatus https://scratch-ai-24bv.onrender.com
```

Nur freigegebene Domains werden abgefragt.

## 7. Custom Command USER → ROLE → DEFAULT

Die Priorität ist:

1. **USER-ID**
2. **ROLE-ID**
3. **DEFAULT**

Beispiel:

```env
CUSTOM_RESPONSE_OVERRIDES_JSON={"default":{"hi":"hi default"},"roles":{"123456789012345678":{"hi":"hi team"}},"users":{"1382373500844511345":{"hi":"hi fabi"},"939870060057600081":{"hi":"hi tom"}}}
```

Damit bekommt User `1382373500844511345` bei `hi` die User-Antwort. Ein User mit der Rolle `123456789012345678` bekommt die Rollen-Antwort. Alle anderen bekommen die Default-Antwort.

Die JSON-Konfiguration muss in `.env` auf **einer Zeile** stehen.

## 8. Ticket-AI

Die bestehende `/ai`-Spielanalyse bleibt erhalten. Die Ticketanalyse verwendet deshalb:

```text
/ticket-ai analyze
```

Sie funktioniert nur in einem registrierten Ticket und prüft Moderations-/Ticket-Rechte.

Die Ausführung kann begrenzt werden:

```env
TICKET_AI_MAX_CONCURRENCY=2
TICKET_AI_COOLDOWN_SECONDS=300
```

`TICKET_AI_MAX_CONCURRENCY` = maximale Anzahl gleichzeitig laufender Analysen.

`TICKET_AI_COOLDOWN_SECONDS` = Wartezeit pro Ticket zwischen Analysen.

Die Ticket-AI benötigt den konfigurierten Provider:

```env
DEEPSEEK_API_KEY=DEIN_DEEPSEEK_KEY
DEEPSEEK_MODEL=deepseek-v4-flash
```

## 9. Lokale Voice-Transkription

Voice verwendet `faster-whisper` lokal. Die wichtigsten Einstellungen:

```env
VOICE_TRANSCRIBE_CHUNK_SECONDS=5
VOICE_WHISPER_MODEL=base
VOICE_WHISPER_DEVICE=cpu
VOICE_WHISPER_COMPUTE_TYPE=int8
VOICE_REVIEW_COOLDOWN=30
```

Empfohlene Startwerte für einen normalen PC:

```env
VOICE_TRANSCRIBE_CHUNK_SECONDS=5
VOICE_WHISPER_MODEL=base
VOICE_WHISPER_DEVICE=cpu
VOICE_WHISPER_COMPUTE_TYPE=int8
VOICE_REVIEW_COOLDOWN=30
```

Die Voice-AutoMod-Review bestraft Voice-Treffer nicht automatisch, sondern meldet sie zur manuellen Prüfung.

## 10. Sonstige vorhandene Variablen

```env
SOCIAL_SUBSCRIBER_POLL_SECONDS=300
NOTIFY_POLL_SECONDS=300
X_BEARER_TOKEN=
N8N_WEBHOOK_URL=
BACKUP_INTERVAL_SECONDS=
BACKUP_RETENTION=
BACKUP_DIR=
DATA_DIR=
TRANSCRIPTS_DIR=
DB_PATH=
PORT=8080
```

Nicht benötigte optionale Variablen dürfen leer bleiben.

`DASHBOARD_TOKEN` muss normalerweise nicht manuell gesetzt werden; das Dashboard kann bei fehlendem Env-Wert sein Token in der lokalen Token-Datei verwalten.

## 11. Komplette Beispiel-`.env`

```env
DISCORD_TOKEN=DEIN_DISCORD_TOKEN
OWNER_ID=DEINE_USER_ID
VERIFY_CHANNEL_ID=
VERIFIED_ROLE_NAME=Verified
WEBAPP_URL=
BOT_SECRET=
ADMIN_LOG_CHANNEL_ID=

WARN_EXPIRY_DAYS=30
WARN_POINTS=1
WARN_ESCALATION_THRESHOLD=3
WARN_ESCALATION_MINUTES=10

TWITCH_CLIENT_ID=DEINE_TWITCH_CLIENT_ID
TWITCH_CLIENT_SECRET=DEIN_TWITCH_CLIENT_SECRET
TWITCH_USER_ACCESS_TOKEN=
TWITCH_EVENTSUB_ENABLED=1
TWITCH_DEFAULT_CHANNEL=dein_twitch_name

YOUTUBE_API_KEY=DEIN_GOOGLE_API_KEY
SOCIAL_SUBSCRIBER_POLL_SECONDS=300

CUSTOM_RESPONSE_OVERRIDES_JSON={"default":{"hi":"hi default"},"roles":{},"users":{}}

TICKET_AI_MAX_CONCURRENCY=2
TICKET_AI_COOLDOWN_SECONDS=300
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=deepseek-v4-flash

WEBSITE_STATUS_DOMAINS=scratch-ai-24bv.onrender.com

VOICE_TRANSCRIBE_CHUNK_SECONDS=5
VOICE_WHISPER_MODEL=base
VOICE_WHISPER_DEVICE=cpu
VOICE_WHISPER_COMPUTE_TYPE=int8
VOICE_REVIEW_COOLDOWN=30

X_BEARER_TOKEN=
NOTIFY_POLL_SECONDS=300
N8N_WEBHOOK_URL=

BACKUP_INTERVAL_SECONDS=
BACKUP_RETENTION=
BACKUP_DIR=
DATA_DIR=
TRANSCRIPTS_DIR=
DB_PATH=
PORT=8080
```

## 12. Was braucht wirklich einen Key?

| Funktion | Variable | API-Key nötig? |
|---|---|---|
| Discord Bot | `DISCORD_TOKEN` | Ja |
| Twitch `!stream` | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Ja |
| Twitch EventSub WebSocket | `TWITCH_USER_ACCESS_TOKEN` | Nur für diesen vorhandenen WebSocket-Weg |
| YouTube `!youtube` | `YOUTUBE_API_KEY` | Ja |
| Ticket-AI | `DEEPSEEK_API_KEY` | Ja |
| Wetter | keine | Nein |
| Minecraft Status | keine | Nein |
| Website Status | `WEBSITE_STATUS_DOMAINS` | Nein |
| Custom USER/ROLE/DEFAULT | `CUSTOM_RESPONSE_OVERRIDES_JSON` | Nein |
| Voice STT | keine | Nein, lokal |

## 13. Lokaler Test nach dem Ausfüllen

1. `_inner_bot/.env` ausfüllen.
2. Prüfen, dass `.env` nicht nach GitHub committed wird.
3. Abhängigkeiten installieren:

```bash
pip install -r _inner_bot/requirements.txt
```

4. Bot starten:

```bash
cd _inner_bot
python bot.py
```

5. Danach nacheinander testen:

```text
/help
/status
/system diagnostics
/system health
!stream dein_twitch_name
!youtube @kanalname
!weather 48.897 9.192
!mcstatus farlandssmp.net
!webstatus https://scratch-ai-24bv.onrender.com
```

Für Ticket-AI in einem Ticket:

```text
/ticket-ai analyze
```

Für Custom Commands:

```text
/custom create
```

Danach den erstellten Prefix-Command mit `!name` ausführen.

## 14. Sicherheit

- `.env` niemals in GitHub committen.
- Keine Tokens in Discord-Chats posten.
- Nach Änderung der `.env` den Bot neu starten.
- Keine beliebigen HTTP-URLs aus Custom Commands ausführen.
- Minecraft-Steuerung nicht mit dem Custom-Command-System vermischen.
- Für echte Tests niemals echte Tokens in Beispiel-Dateien eintragen.
