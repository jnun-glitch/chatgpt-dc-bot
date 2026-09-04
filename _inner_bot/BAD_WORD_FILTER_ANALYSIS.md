# 🛡️ Bad-Word-Filter – Analyse & Roadmap

## Kurzfazit

Der Filter ist inzwischen deutlich stärker als ein einfacher Wortvergleich. Er kombiniert eine externe Liste, Normalisierung und automatische Moderations-Logs.

**Aktueller Gesamtstand: 7,5/10**

Die größte Stärke ist die einfache Erweiterbarkeit. Die größten Schwächen sind False Positives, fehlender Kontext und dass ein Wortfilter allein keine gute Moderation ersetzen kann.

---

## ✅ Was bereits gut ist

| Bereich | Bewertung | Warum |
|---|---:|---|
| Große Wortliste | ⭐⭐⭐⭐⭐ | Deutsch, Englisch und mehrere Kategorien sind abgedeckt. |
| Varianten | ⭐⭐⭐⭐⭐ | Mehrere Schreibweisen und Flexionen sind enthalten. |
| Groß-/Kleinschreibung | ⭐⭐⭐⭐⭐ | Wird bei der Normalisierung vereinheitlicht. |
| Unicode-Normalisierung | ⭐⭐⭐⭐☆ | Hilft gegen einige ungewöhnliche Schreibweisen. |
| Einfache Umgehungen | ⭐⭐⭐⭐☆ | Zahlen und bestimmte Sonderzeichen werden normalisiert. |
| Externe TXT-Liste | ⭐⭐⭐⭐⭐ | Neue Begriffe können ohne Codeänderung ergänzt werden. |
| Logging | ⭐⭐⭐⭐⭐ | Treffer können in DB und Moderationskanal nachvollzogen werden. |
| Auto-Warn-System | ⭐⭐⭐⭐☆ | Wiederholte Verstöße werden automatisch erkannt. |
| Performance | ⭐⭐⭐⭐☆ | Für einen normalen Discord-Server ist die Lösung leicht genug. |
| Wartbarkeit | ⭐⭐⭐⭐☆ | Liste und Python-Logik sind getrennt. |

---

## ❌ Was noch schlecht / riskant ist

### 1. False Positives

Ein reiner Substring-Vergleich kann harmlose Wörter treffen, wenn ein gesuchter Begriff zufällig darin vorkommt.

**Beispielproblem:** Ein kurzer Filterbegriff kann Bestandteil eines normalen Wortes sein.

**Verbesserung:**
- Wortgrenzen für kurze Begriffe
- Kontextprüfung für längere/mehrdeutige Begriffe
- Whitelist für bekannte harmlose Treffer
- unterschiedliche Regeln je Kategorie

---

### 2. Kein Kontextverständnis

Der Filter weiß nicht, ob ein Begriff beleidigend verwendet wird oder z. B. in einer normalen Diskussion über Moderation, Spiele oder Nachrichten vorkommt.

**Verbesserung:**
- Stufe 1: schneller Wortfilter
- Stufe 2: Kontextbewertung nur bei unklaren Treffern
- Stufe 3: Moderator-Review bei hoher Unsicherheit

Dadurch muss nicht jede Nachricht durch ein KI-Modell laufen.

---

### 3. Zu viele harte Kategorien in einer einzigen Liste

Beleidigungen, sexuelle Begriffe, Diskriminierung und aggressive Aussagen werden aktuell gemeinsam als "Bad Word" behandelt.

**Besser:** Kategorien getrennt speichern:

```text
insults
profanity
sexual
harassment
discrimination
threats
spam
```

So kann der Server unterschiedliche Maßnahmen einstellen.

---

### 4. Keine Severity-Stufe

Nicht jeder Treffer sollte automatisch gleich behandelt werden.

**Empfohlenes System:**

| Stufe | Bedeutung | Beispielaktion |
|---|---|---|
| 0 | harmlos/unklar | nichts |
| 1 | leichte Beleidigung | Nachricht loggen |
| 2 | klarer Verstoß | löschen + loggen |
| 3 | schwerer Verstoß | löschen + Warnung |
| 4 | wiederholter/schwerer Verstoß | Moderatoren benachrichtigen |

---

### 5. Auto-Warn bei jeder 5. Meldung

Das vorhandene System ist einfach, aber nicht besonders intelligent.

Problem: Fünf kleine Verstöße sind nicht zwingend gleich schlimm wie ein einzelner schwerer Verstoß.

**Besser:** Punkte statt reiner Anzahl.

```text
leichter Treffer = 1 Punkt
mittlerer Treffer = 2 Punkte
schwerer Treffer = 4 Punkte
```

Dann können Zeitfenster und Eskalationsstufen verwendet werden.

---

### 6. Keine zeitliche Rücksetzung

Ein langfristiger Zähler kann einen Nutzer noch Wochen später wegen alter Nachrichten eskalieren lassen.

**Besser:**
- Punkte verfallen nach konfigurierbarer Zeit
- Moderationshistorie bleibt trotzdem erhalten
- Eskalation berücksichtigt nur einen definierten Zeitraum

---

### 7. Umgehungen sind nie vollständig lösbar

Es gibt unendlich viele kreative Schreibweisen. Ein riesiger Wortschatz allein wird deshalb nie perfekt.

**Besser:** Normalisierung + Mustererkennung + Kontext + Rate-Limits + Moderator-Tools kombinieren.

---

## 🧠 Empfohlene Zielarchitektur

```text
Discord Nachricht
       ↓
Normalisierung
       ↓
Schneller Wort-/Musterfilter
       ↓
Treffer?
  ┌────┴────┐
 Nein       Ja
  ↓          ↓
weiter   Kategorie + Severity
             ↓
       False-Positive-Check
             ↓
       ┌─────┴─────┐
     sicher      unklar
       ↓            ↓
   Maßnahme     Kontextprüfung
       ↓            ↓
       └──────┬─────┘
              ↓
         Moderationslog
              ↓
      Warn-/Punktesystem
              ↓
      ggf. Moderator-Alert
```

---

## 🚀 Prioritäten für die nächsten Versionen

### V1 – sofort sinnvoll

- [x] größere Liste
- [x] externe `bad_words.txt`
- [x] Normalisierung
- [x] Varianten
- [x] Logging
- [x] automatische Warnung
- [ ] False-Positive-Whitelist
- [ ] bessere Wortgrenzen

### V2 – Moderation deutlich besser

- [ ] Kategorien in separaten Listen
- [ ] Severity pro Begriff
- [ ] Punkte statt nur Treffer zählen
- [ ] zeitlicher Verfall der Punkte
- [ ] konfigurierbare Aktionen
- [ ] Moderator-Review für unklare Treffer

### V3 – richtig gutes System

- [ ] Spam-/Flood-Erkennung
- [ ] wiederholte Nachrichten erkennen
- [ ] Caps-Lock-Erkennung
- [ ] Mention-Spam erkennen
- [ ] Link-Spam erkennen
- [ ] Invite-Spam erkennen
- [ ] Raid-Schutz
- [ ] Moderations-Dashboard
- [ ] Statistiken über Treffer und False Positives

---

## ⭐ Bewertung

| System | Aktuell | Ziel |
|---|---:|---:|
| Wortabdeckung | 9/10 | 9/10 |
| Umgehungsschutz | 8/10 | 9/10 |
| False-Positive-Schutz | 5/10 | 9/10 |
| Kontextverständnis | 2/10 | 8/10 |
| Moderationsaktionen | 7/10 | 9/10 |
| Logging | 9/10 | 9/10 |
| Wartbarkeit | 8/10 | 9/10 |
| Performance | 9/10 | 9/10 |
| **Gesamt** | **7,5/10** | **9/10+** |

---

## 🎯 Meine Empfehlung

Nicht einfach immer mehr Wörter hinzufügen. Ab einem gewissen Punkt bringt **bessere Erkennung** mehr als eine noch längere Liste.

Der nächste sinnvolle Entwicklungsschritt ist deshalb:

**False-Positive-Schutz → Kategorien → Severity → Punkte/Verfall → Kontextprüfung → Dashboard.**

Damit wird aus einem einfachen Bad-Word-Filter ein richtiges Moderationssystem.
