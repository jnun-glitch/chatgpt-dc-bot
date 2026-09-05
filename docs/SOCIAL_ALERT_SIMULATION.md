# Social-Alert Simulation (ohne echte Plattform-Events)

Mit diesem Test kannst du prüfen, wie ScratchAI auf eingehende Creator-Ereignisse reagieren soll, ohne einen echten Twitch-/YouTube-/X-Account zu benutzen und ohne echte Nachrichten an Discord zu senden.

## Was wird simuliert?

Der Test erzeugt drei Fake-Eingaben:

1. **Twitch:** `Test` geht live mit einer Fake-Stream-ID.
2. **YouTube:** `Test` bekommt einen Fake-Live-Eintrag.
3. **X:** `Test` veröffentlicht einen neuen Fake-Post.

Das sind absichtlich nur Testdaten. Es werden keine Requests an Twitch, YouTube oder X geschickt.

## Test starten

Im Ordner `_inner_bot`:

```text
pytest -q tests/test_social_simulation.py
```

Erwartung:

```text
3 passed
```

## Was dabei geprüft wird

### Twitch

Der Bot baut einen Live-Alert mit:

- `🔴 Twitch ist LIVE!`
- Creator `Test`
- Streamtitel `Test ist LIVE!`
- Kategorie `Test Game`
- 123 Zuschauer

Außerdem wird geprüft, dass dieselbe Stream-ID **nicht zweimal** als neuer Live-Start erkannt wird.

Das entspricht dem echten Twitch-Prinzip: EventSub liefert bei einem Online-Event eine Stream-ID; der Bot kann diese als Dedupe-Marker verwenden. Twitch dokumentiert `stream.online` als Event für den Start eines Streams. 

### YouTube

Der Bot baut einen Live-Alert mit:

- `🔴 YouTube ist LIVE!`
- Creator `Test`
- Fake-Video-ID

Zusätzlich wird geprüft, dass ein neuer Eintrag gegenüber dem gespeicherten Marker als ungesehen erkannt wird.

### X

Der Bot bekommt einen alten Fake-Post `100` und einen neuen Fake-Post `101`.

Gespeicherter Marker: `100`

Erwartung: Nur `101` wird als neu erkannt.

## Wichtig

Dieser Offline-Test beweist die **Verarbeitungslogik**, aber nicht die Verbindung zu den echten Plattformen oder Discord.

Für einen echten Integrationstest brauchst du anschließend:

1. Bot starten.
2. `/notify add` für einen echten Creator einrichten.
3. `/notify test` verwenden, um Discord-Berechtigungen und das Embed zu prüfen.
4. Bei Twitch zusätzlich die EventSub-Verbindung im Bot-Log kontrollieren.

Twitch-WebSockets liefern zuerst eine `session_welcome`-Nachricht und danach EventSub-Benachrichtigungen; bei einer verlorenen Verbindung müssen die Subscriptions für eine neue Session wiederhergestellt werden. citeturn0search0turn0search1
