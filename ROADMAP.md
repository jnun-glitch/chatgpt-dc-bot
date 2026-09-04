# 🗺️ ScratchAI Roadmap

Stand: 4. September 2026

## ✅ Bereits umgesetzt / gehärtet

- [x] Modularer Cog-Aufbau und automatisches Cog-Laden
- [x] SQLite-Performance: WAL, Connection-Caching, Indizes und Retention
- [x] Sichere Rollen-Hierarchie und Staff-Channel-Absicherung
- [x] `/setup-smp` und `/setup-roles` für reproduzierbares Server-Setup
- [x] Erweiterter AutoMod inkl. URL-/Invite-/Spam-/Raid-Prüfungen
- [x] Audit-Logging für wichtige Serverevents
- [x] Ticket-System mit Transkripten und AI-Anbindung
- [x] Musik-Steuerung mit Voice-/Player-Berechtigungsprüfung
- [x] Lokale Voice-Transkription mit faster-whisper
- [x] Nicht-punitiver Voice-AutoMod-Review über `#bad-word-log`
- [x] Dashboard mit Live-Ansicht, Audit-Daten und Serververwaltung
- [x] AI-Rate-Limit pro Server + Benutzer mit aktivem Speicher-Cleanup
- [x] AI-Fehler werden nicht mehr als rohe Fehlermeldungen an Benutzer weitergegeben
- [x] CI: Dependency-Check, Compile-Smoke-Test, Pytest und Bot-Import
- [x] Zusätzliche AI- und Voice-Testabdeckung

## 🔜 Nächste Ausbaustufe

- [ ] Dashboard: feinere Server-/Feature-Konfiguration und sichere Authentifizierung über Discord OAuth
- [ ] Voice: konfigurierbare Transkriptionskanäle und bessere Session-Verwaltung
- [ ] AI: robuste Retry-/Timeout-Schicht und bessere Provider-Statusanzeige
- [ ] Tests: mehr Mock-Tests für Discord Events, Tickets, Dashboard und Datenbank-Retention
- [ ] CI/CD: Release-Workflow, reproduzierbare Dependency-Versionen und Deployment-Smoke-Test
- [ ] Observability: strukturierte Metriken für Command-Latenz, Fehler und aktive Voice-Sessions
- [ ] Performance: weitere DB-Abfragen bündeln und unnötige API-Aufrufe reduzieren

## 🎯 Ziel

Der Bot soll stabil, sicher und modular genug sein, dass neue Features ergänzt werden können, ohne bestehende SMP-/Community-Funktionen zu gefährden.
