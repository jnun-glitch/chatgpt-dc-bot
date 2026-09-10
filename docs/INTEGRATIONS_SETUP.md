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

---

## 2. Twitch

Der Bot hat bereits Twitch-Unterstützung für Live-Abfragen und Creator-Alerts. Die normale `!stream <kanal>`-Abfrage verwendet Client-Credentials; EventSub WebSocket ist ein separater Live-Alert-Weg.

### Twitch App erstellen

1. Öffne die **Twitch Developer Console**.
2. Erstelle eine neue Application.
3. Kopiere **Client ID**.
4. Erzeuge/verwende das zugehörige **Client Secret**.
5. Trage beides ein:

```env
TWITCH_CLIENT_ID=DEINE_CLIENT_ID
TWITCH_CLIENT_SECRET=DEIN_CLIENT_SECRET
TWITCH_DEFAULT_CHANNEL=dein_twitch_name
TWITCH_EVENTSUB_ENABLED=1
```

Für die normale Abfrage reicht `TWITCH_CLIENT_ID` + `TWITCH_CLIENT_SECRET`.

### Optional: EventSub WebSocket

Der vorhandene EventSub-Code kann einen User Access Token verwenden:

```env
TWITCH_USER_ACCESS_TOKEN=DEIN_USER_ACCESS_TOKEN
```

Nicht benötigte Token-Felder leer lassen. Der Twitch-Token ist ein Geheimnis.

### Test

```text
!stream dein_twitch_name
```

oder mit `TWITCH_DEFAULT_CHANNEL`:

```text
!stream
```

Alias:

```text
!live dein_twitch_name
```

---

## 3. YouTube

Für den neuen `!youtube`-Befehl wird die **YouTube Data API v3** verwendet.

1. Öffne die **Google Cloud Console**.
2. Erstelle ein Projekt oder wähle dein Bot-Projekt.
3. Aktiviere **YouTube Data API v3**.
4. Erstelle unter **APIs & Services → Credentials** einen API Key.
5. Eintragen:

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

Der Bot fragt öffentliche Kanalstatistiken ab. Es wird kein YouTube-Passwort benötigt.

---

## 4. Wetter – kein API-Key nötig

Der Bot verwendet Open-Meteo für den sicheren Wetter-Status.

```text
!weather 48.897 9.192
```

Beispiel Kornwestheim/Ludwigsburg-Region: Koordinaten entsprechend anpassen.

Es muss kein `WEATHER_API_KEY` gesetzt werden.

---

## 5. Minecraft-Status

Minecraft Connector bleibt getrennt vom Custom-Command-System. Für einen einfachen öffentlichen Serverstatus braucht der Bot keinen Minecraft-Plugin-Zugriff.

```text
!mcstatus farlandssmp.net
```

Alias:

```text
!mc farlandssmp.net
```

Das ist nur ein öffentlicher Status-Check. Für echte Server-Steuerung oder Ingame-Aktionen wäre später ein separater Minecraft-Connector nötig.

---

## 6. Website-Status

Der Bot darf **nicht** beliebige URLs von Discord-Nutzern abrufen. Deshalb gibt es eine Whitelist.

Beispiel:

```env
WEBSITE_STATUS_DOMAINS=scratch-ai-24bv.onrender.com,example.com
```

Danach:

```text
!webstatus https://scratch-ai-24bv.onrender.com
```

Nur Domains, die in `WEBSITE_STATUS_DOMAINS` stehen, werden abgefragt.

---

## 7. Custom Command USER → ROLE → DEFAULT

Die Antwort-Priorität ist:

1. **USER-ID**
2. **ROLE-ID**
3. **DEFAULT**

Sie kann über eine JSON-Variable konfiguriert werden:

```env
CUSTOM_RESPONSE_OVERRIDES_JSON={"default":{"hi":"hi default"},"roles":{"ROLE_ID":{"hi":"hi rolle"}},"users":{"USER_ID":{"hi":"hi user"}}}
```

Beispiel mit zwei Usern:

```env
CUSTOM_RESPONSE_OVERRIDES_JSON={"default":{"hi":"hi default"},"roles":{"123456789012345678":{"hi":"hi team"}},"users":{"1382373500844511345":{"hi":"hi fabi"},"939870060057600081":{"hi":"hi tom"}}}
```

Wichtig: JSON in `.env` muss eine einzelne Zeile sein. Bei komplizierten Antworten besser zunächst einfache Texte verwenden.

---

## 8. Sonstige vorhandene Variablen

```env
SOCIAL_SUBSCRIBER_POLL_SECONDS=300
NOTIFY_POLL_SECONDS=300
X_BEARER_TOKEN=
N8N_WEBHOOK_URL=
DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=
BACKUP_INTERVAL_SECONDS=
BACKUP_RETENTION=
BACKUP_DIR=
DATA_DIR=
TRANSCRIPTS_DIR=
DB_PATH=
PORT=8080
```

Nicht benötigte optionale Variablen dürfen leer bleiben.

---

## 9. Komplette Beispiel-`.env`

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

X_BEARER_TOKEN=
NOTIFY_POLL_SECONDS=300

N8N_WEBHOOK_URL=

CUSTOM_RESPONSE_OVERRIDES_JSON={"default":{"hi":"hi default"},"roles":{},"users":{}}
WEBSITE_STATUS_DOMAINS=scratch-ai-24bv.onrender.com

DEEPSEEK_API_KEY=
DEEPSEEK_MODEL=
BACKUP_INTERVAL_SECONDS=
BACKUP_RETENTION=
BACKUP_DIR=
DATA_DIR=
TRANSCRIPTS_DIR=
DB_PATH=
PORT=8080
```

## 10. Was braucht wirklich einen Key?

| Funktion | Variable | API-Key nötig? |
|---|---|---|
| Discord Bot | `DISCORD_TOKEN` | Ja |
| Twitch `!stream` | `TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET` | Ja |
| Twitch EventSub WebSocket | `TWITCH_USER_ACCESS_TOKEN` | Je nach vorhandener EventSub-Konfiguration |
| YouTube `!youtube` | `YOUTUBE_API_KEY` | Ja |
| Wetter | keine | Nein |
| Minecraft Status | keine | Nein |
| Website Status | `WEBSITE_STATUS_DOMAINS` | Nein |
| Custom USER/ROLE/DEFAULT | `CUSTOM_RESPONSE_OVERRIDES_JSON` | Nein |

## 11. Sicherheit

- `.env` niemals in GitHub committen.
- Keine Tokens in Discord-Chats posten.
- Keine beliebigen HTTP-URLs aus Custom Commands ausführen.
- Minecraft-Steuerung nicht mit dem Custom-Command-System vermischen.
- Nach Änderung der `.env` den Bot neu starten.
