# Twitch-Streamer-Pings für ScratchAI

ScratchAI kann Twitch-Creator ohne deren Twitch-Passwort überwachen und in einen Discord-Kanal melden.

## Was wird benötigt?

Der Bot verwendet eine eigene Twitch-App:

- `TWITCH_CLIENT_ID`
- `TWITCH_CLIENT_SECRET`
- optional für den schnellen EventSub-Weg: `TWITCH_USER_ACCESS_TOKEN`

Das Passwort eines Streamers wird **nicht** benötigt.

## 1. Twitch-App erstellen

1. Öffne die Twitch Developer Console: https://dev.twitch.tv/console/apps
2. Melde dich mit dem Twitch-Konto an, das die Bot-App besitzen soll.
3. Klicke auf **Register Your Application**.
4. Name z. B. `ScratchAI Discord Bot`.
5. OAuth Redirect URL: `http://localhost:3000`.
6. Kategorie: z. B. `Chat Bot`.
7. App erstellen.
8. Unter **Manage** die **Client ID** kopieren.
9. Mit **New Secret** ein Client Secret erzeugen und sicher aufbewahren.

Wichtig: Das Client Secret und Access Tokens gehören in `.env` und niemals in GitHub.

## 2. `.env` eintragen

In `_inner_bot/.env`:

```env
TWITCH_CLIENT_ID=DEINE_CLIENT_ID
TWITCH_CLIENT_SECRET=DEIN_CLIENT_SECRET
TWITCH_EVENTSUB_ENABLED=1
```

Damit funktioniert bereits die vorhandene Twitch-API-Prüfung per Polling.

## 3. Schnelle EventSub-Live-Meldungen aktivieren

Für `stream.online` über Twitch EventSub WebSocket benötigt Twitch einen **User Access Token**. Für diese Subscription werden keine zusätzlichen Scopes benötigt, weil `stream.online` keine Benutzerberechtigung verlangt.

Am einfachsten geht das mit der offiziellen Twitch CLI.

### Twitch CLI installieren

Windows mit Scoop:

```powershell
scoop bucket add twitch https://github.com/twitchdev/scoop-bucket.git
scoop install twitch-cli
```

Danach die CLI mit derselben Twitch-App konfigurieren:

```powershell
twitch configure
```

Dort eintragen:

```text
Client ID: DEINE_CLIENT_ID
Client Secret: DEIN_CLIENT_SECRET
```

Dann einen User Access Token ohne Scopes erzeugen:

```powershell
twitch token --user-token --scopes ""
```

Der Browser öffnet Twitch für die Zustimmung. Verwende dafür das Twitch-Konto, dem die ScratchAI-Twitch-App gehört.

Die CLI gibt anschließend einen **User Access Token** und einen **Refresh Token** aus. Für den aktuellen ScratchAI-EventSub-Client wird der User Access Token benötigt.

In `.env`:

```env
TWITCH_USER_ACCESS_TOKEN=DEIN_USER_ACCESS_TOKEN
TWITCH_EVENTSUB_ENABLED=1
```

## 4. Bot neu starten

Nach der Änderung `.env` den Bot komplett neu starten.

Im Log sollte ungefähr stehen:

```text
Twitch EventSub connected; watching X creator(s)
Twitch EventSub subscribed: <creator-id>
```

Wenn kein User Token gesetzt ist, erscheint stattdessen sinngemäß:

```text
Twitch EventSub disabled ... Polling remains active.
```

Das ist kein Absturz: Die normale Twitch-Abfrage läuft als Fallback weiter.

## 5. Discord-Alert einrichten

Der Discord-Bot-Owner bzw. jemand mit **Server verwalten** kann z. B. ausführen:

```text
/notify add
```

Als `source` geht z. B.:

```text
https://www.twitch.tv/DEIN_STREAMER
```

Danach den gewünschten Discord-Kanal auswählen und optional eine Rolle zum Pingen.

Anschließend:

```text
/notify test
```

Damit wird sofort eine Testmeldung in den konfigurierten Kanal geschickt.

## 6. Echter Live-Test

1. Einen Twitch-Kanal hinzufügen, den du testen darfst.
2. Prüfen:

```text
/notify list
```

3. Testnachricht senden:

```text
/notify test
```

4. Bot neu starten und im Log nach `Twitch EventSub connected` suchen.
5. Den Test-Streamer offline lassen.
6. Danach den Stream starten.
7. ScratchAI sollte eine `🔴 Twitch ist LIVE!` Nachricht in den eingestellten Discord-Kanal schicken.

Der Alert wird pro Twitch-Stream-ID dedupliziert. Falls Twitch ein Event erneut zustellt, soll dadurch keine zweite identische Live-Meldung entstehen.

## 7. Wenn EventSub nicht funktioniert

Prüfe zuerst:

- `TWITCH_CLIENT_ID` ist gesetzt.
- `TWITCH_CLIENT_SECRET` ist gesetzt.
- `TWITCH_USER_ACCESS_TOKEN` gehört zur **gleichen Twitch-App** wie die Client ID.
- `TWITCH_EVENTSUB_ENABLED=1`.
- `websockets` ist installiert (`pip install -r requirements.txt`).
- Der Bot hat im Discord-Zielkanal die Berechtigung **Nachrichten senden** und **Links einbetten**.

Die normale Twitch-Polling-Funktion bleibt als Fallback aktiv.

## Sicherheit

Niemals diese Werte in GitHub committen:

```text
TWITCH_CLIENT_SECRET
TWITCH_USER_ACCESS_TOKEN
TWITCH_REFRESH_TOKEN
DISCORD_TOKEN
```

Wenn ein Secret versehentlich veröffentlicht wurde, sofort bei dem jeweiligen Dienst ersetzen bzw. widerrufen.

## Offizielle Twitch-Dokumentation

- App registrieren: https://dev.twitch.tv/docs/authentication/register-app/
- Twitch CLI: https://dev.twitch.tv/docs/cli/
- User Access Token mit Twitch CLI: https://dev.twitch.tv/docs/cli/token-command/
- EventSub: https://dev.twitch.tv/docs/eventsub/
- EventSub WebSocket: https://dev.twitch.tv/docs/eventsub/handling-websocket-events/
