# SBS Catalog — Web-Frontend für Music Architect V7

Webbasiertes Produktions- und Verwaltungsmodul zum Musikproduktions-Gesamtpaket aus
**Music Architect V7** (KI-Beat-Generator) und **SBS-Synth Master** (DAW/Mastering).

Das System verbindet Beat-Generierung, Klanggestaltung, Lizenzverwaltung und
Wirtschaftlichkeitsrechnung in einer einzigen Weboberfläche — von der Idee bis zum
verkaufsfähigen Track.

---

## Übersicht der Funktionsbereiche

| Bereich | Kurzbeschreibung |
|---|---|
| Beat-Generierung | KI-gesteuerter Beat-Generator mit Prompt, Genre, BPM, Tonart |
| Groove & Mixer | Per-Spur Lautstärke, Swing, Nudge, Velocity, Humanisierung |
| Feel-Presets | Benannte Genre-Feels (z. B. „Boom Bap", „Dark Memphis") |
| Theory-Score | Psychoakustische BDRA-Validierung nach MA V7-Regeln (P1–P5) |
| Samples | Upload eigener Audiodateien pro Instrument-Spur |
| Timbre-Editor | Synthesizer-Parameter (Attack, Decay, Brightness, Drive) |
| Production Advisor | Automatische Mixing-Empfehlungen nach Genre-Regeln |
| Piano Roll | Visuelle Notenansicht aller erzeugten Spuren |
| Katalog | Verwaltung aller erzeugten Tracks mit Genre- und Statusfilter |
| Lizenzverkauf | Stufenmodell (Preview / Streaming / Lease / Exklusiv) mit Checkout |
| Wirtschaftlichkeit | Umsatz, Deckungsbeitrag, Break-even, ROI |
| Audit-Protokoll | Revisionssicheres Ereignisprotokoll, CSV-Export |
| Auth & Rollen | Login, Admin-Rolle, Freemium-Kontingent |

---

## Installation

```bash
cd Music_catalogue_manager_v.2
python -m venv venv

# Windows:
venv\Scripts\activate
# macOS/Linux:
source venv/bin/activate

pip install -r requirements.txt
```

## Starten

```bash
python app.py
```

Browser öffnen: <http://127.0.0.1:5000>

Standardmäßig wird die Anwendung auf `127.0.0.1:5000` gestartet.  
Der Music Architect V7 muss sich im übergeordneten Verzeichnis befinden:
`../MUSIC_ARCHITECT_V7/`.

---

## Beat-Generierung

Der Kern der Anwendung. Ein Beat wird durch folgende Parameter gesteuert:

**Basis-Parameter**
- **Prompt** — Freitext-Eingabe (z. B. „dark cinematic trap beat"), wird automatisch
  in Genre, BPM und Tonart dekodiert.
- **Genre** — trap, phonk, hiphop, techno, house, edm, pop, cinematic, jpop u. a.
- **BPM** — manuell oder automatisch durch den Generator.
- **Komplexität** (1–10) — Dichte der Patterns.
- **Seed** — reproduzierbare Ergebnisse bei gleichem Seed.

**Tonart & Struktur**
- Ton (C, C#, D … B), Tonleiter (major, minor, dorian, phrygian, blues …)
- Takte, Bars, Strukturvariante.

**Instrumente (manuell ändern vor Re-Rendering)**
- Pro Spur (Drums, Bass, Lead, Chords, Pad, Arp, Stabs, Texture, FX) kann das
  GM-Programm manuell überschrieben werden.
- Ein **Theory-Score** (0–100) bewertet die Instrumentkombination nach den fünf
  psychoakustischen BDRA-Prinzipien von MA V7 (P1 Sub-Bass, P2 Register,
  P3 Attack-Kontrast, P4 Dichte, P5 Helligkeit). Note: EXZELLENT / GUT /
  BEFRIEDIGEND / VERBESSERUNGSBEDARF.

**Rendering-Modi**
- **Builtin-Synthesizer** — plattformunabhängig, kein externes Tool nötig.
- **SF2 / FluidSynth** — hochwertigere Ausgabe mit SoundFont-Bibliothek; Genre-Standard
  wird automatisch gewählt, eigene `.sf2`-Datei kann hochgeladen werden.
- **Modus „Beide"** — erzeugt gleichzeitig eine instrumentale und eine Vocal-Mask-Version.

---

## Groove & Mixer

Der Groove-Bereich erscheint nach der Generierung im Reiter **Groove & Mix — Re-Render**.

### Mixer-Schieberegler (pro Spur)
- **Lautstärke** (dB) — kontinuierlicher Fader.
- **Mute / Solo** — Spur stumm oder solo rendern.
- **Pan** — Stereoposition.
- **C-Button** — öffnet das erweiterte Groove-Param-Panel für die Spur.
- **S-Button** — Solo-Vorschau der Spur (ohne erneute Voll-Generierung).

### Groove-Parameter pro Spur
- **Swing** (25–75 %) — Off-Beat-Verschiebung der 16tel-Noten; 50 = gerade.
- **Nudge** (ms) — fester Timing-Versatz der gesamten Spur (negativ = Pocket).
- **Velocity-Bereich** (min/max) — Dynamik der Spur eingrenzen.
- **Velocity-Kurve** — flat, accent, crescendo, diminuendo.
- **Velocity-Humanisierung** — zufälliger ±Jitter auf Velocity.
- **Timing-Humanisierung** — zufälliger ±Jitter in ms.
- **Seed** — reproduzierbarer Humanisierungseffekt.
- **Transpose** — Halbtonverschiebung der Spur.

### Genre-Presets & Feel-Presets
- **Genre-Dropdown** — lädt theorie-korrekte Mixer-Grundwerte (Gain, Pan, Swing,
  Velocity-Bereiche) für das gewählte Genre.
- **Feel-Dropdown** — benannte Varianten pro Genre, z. B.:
  - *hiphop*: Boom Bap, Lo-Fi Chill, Modern Rap
  - *trap*: Standard, Dark Memphis, Melodic Trap, Phonk Trap
  - *house*: Deep Chill, Tech House, Classic House
  - *techno*: Minimal, Hard Industrial, Detroit, Hypnotic
  - *phonk*: Classic Drift, Brazilian Rave, Slowed Chopped
  - *edm*: Festival, Future Bass, Progressive
  - *pop*: Radio Hit, Indie, Dance Pop
- **Preset laden** — übernimmt Genre- oder Feel-Werte in alle Schieberegler.
- **Zurücksetzen** — setzt alle Mixer-Werte auf Null zurück.

### Groove-Stacking-Schutz
Jeder Re-Render startet immer von der **originalen, unbearbeiteten Komposition** —
Groove-Effekte akkumulieren sich nicht über mehrere Re-Renders.  
Intern: `CompositionGroover` (MA V7, Beat-Raum) für Timing/Velocity,
`groove_processor.py` (Web) für Mute/Lautstärke/Instrument-Änderungen.

---

## Samples — Eigene Audiodateien pro Spur

Im Panel **Samples (eigene Audio-Dateien pro Track)** kann pro Spur eine eigene
Audiodatei hinterlegt werden, die den eingebauten Synthesizer für diese Spur ersetzt.

- **Unterstützte Formate**: WAV, AIFF, FLAC, OGG, MP3
- **Maximale Dateigröße**: 20 MB pro Sample
- **Browse** (📁) — öffnet den Datei-Dialog für die Spur.
- **Vorschau** (▶) — spielt die zugewiesene Datei direkt im Browser ab (Web Audio API).
- **Löschen** (✕) — entfernt die Zuweisung und die serverseitige Datei.
- Hochgeladene Samples bleiben über mehrere Re-Renders erhalten (Session-basiert).
- Wenn Samples zugewiesen sind, wird SF2/FluidSynth automatisch deaktiviert.

---

## Timbre-Editor

Per-Instrument-Klangsynthese-Parameter für vier Rollen:

| Rolle | Parameter |
|---|---|
| **KICK** | Pitch Ende (Hz), Rauschanteil, Ausklingen (ms) |
| **SNARE** | Pitch (Hz), Rauschanteil, Ausklingen (ms) |
| **HI-HAT** | Ausklingen (ms), Rauschanteil (Helligkeit), Sättigung |
| **MELODIC** | Anschlag (ms), Helligkeit, Sättigung |

- Jede Rolle bietet ein **Preset-Dropdown** mit vordefinierten Klangcharakteren.
- Einzelne Schieberegler können nach dem Laden eines Presets feineingestellt werden.
- Alle Werte fließen beim Re-Render in den eingebauten Synthesizer ein.

---

## Production Advisor

Nach der Generierung analysiert der Advisor automatisch die Komposition und zeigt
im gleichnamigen Reiter detaillierte Empfehlungen:

| Sektion | Inhalt |
|---|---|
| Palette & Prompt-Analyse | verwendete Palette, dekodierter Prompt, erkanntes Genre |
| Instrumente | GM-Programm und Beschreibung pro Spur |
| Gain Staging & Ziele | Ziel-RMS, Peak, LUFS-S und empfohlener Fader pro Spur |
| Effektketten | empfohlene Insert-Effekte (EQ, Kompressor, Sättiger …) |
| Frequenzallokation | HPF/LPF-Zonen pro Spur zur Vermeidung von Maskierung |
| BPM-Zeitwerte | ms-Werte für 1/4, 1/8, 1/16, dotted, triplet beim aktuellen BPM |
| Export-Ziele | empfohlene Lautheitsziele je Plattform (Spotify, YouTube …) |
| Groove & Mix | Kurzzusammenfassung der angewendeten Groove-Einstellungen |

Alle Sektionen starten eingeklappt und werden per Klick geöffnet.

---

## Piano Roll

Zeigt alle Noten der erzeugten Komposition als interaktive Piano Roll:
- Jede Spur hat eine eigene Farbe.
- Horizontal = Zeit (Takte), vertikal = Tonhöhe (MIDI-Note).
- Zoom In / Out / Reset.
- Klick auf die Waveform-Zeitleiste springt zur gewünschten Position.

---

## Export

Nach dem Generieren oder Re-Rendern stehen folgende Exportformate zur Verfügung:

| Format | Beschreibung |
|---|---|
| WAV 24-bit / 44.1 kHz | unkomprimiertes Studioformat |
| WAV 16-bit / 44.1 kHz | CD-Qualität |
| MP3 320 kbps | universell kompatibel |
| FLAC | verlustfrei komprimiert |
| MIDI | rohe Notendaten für die DAW |

Das Kontingent wird **nur beim Speichern / Download** verbraucht, nicht beim Vorhören.

---

## Katalog- & Lizenzverwaltung

### Katalog
- Zeigt alle erzeugten Tracks mit Genre, Titel, Status und Exportverknüpfungen.
- Filter nach Genre und Status (verfügbar / verkauft / exklusiv gesperrt).
- **Read-only-Kopplung**: das Modul verändert weder Music Architect noch die DAW.

### Lizenzstufen

| Stufe | Beschreibung |
|---|---|
| Preview | MP3-Vorschau, eingeschränkte Nutzung |
| Streaming | Streaming-Plattformen, kein Sync |
| Lease | vollständige Nutzung, nicht exklusiv |
| Exklusiv (Trackout) | exklusive Rechte — Track wird dauerhaft gesperrt |

### Checkout & Zahlung (simuliert)
1. Lizenz anlegen → Status *offen*, Exklusiv-Sperre greift sofort.
2. Checkout-Seite bestätigen → Status *bezahlt*.
3. Stornieren → Track wird wieder freigegeben.
4. Rechnung mit Netto, USt (Standard 19 %) und Brutto, druckfertig.

---

## Abo-/Freemium-Modell

| Tier | Tageslimit | Monatslimit | Rabatt |
|---|---|---|---|
| Free | 3 Tracks | — | — |
| Subscriber | 10 Tracks | konfigurierbar | 5 % auf Lizenzen |

- Limit wird **vor** der Generierung geprüft (Gateway-Pattern).
- Stornierte Lizenzen geben das Kontingent wieder frei.
- Abo mit wählbarer Laufzeit (1 / 3 / 12 Monate), eigener Checkout-Seite und
  Laufzeitprüfung bei jedem Request.

---

## Wirtschaftlichkeit

Automatische Berechnung aus den Ist-Daten der Datenbank:

- **Umsatz** (Lizenz / Abo / gesamt, nur bezahlte Positionen)
- **Kosten** (Entwicklungsstunden × Stundensatz + Tooling)
- **Deckungsbeitrag** = Umsatz − variable Kosten pro Track
- **Break-even** — wie viele Tracks müssen verkauft werden?
- **ROI** — Return on Investment in Prozent
- Alle Parameter konfigurierbar unter *Einstellungen*.

---

## Audit-Protokoll

Jede relevante Aktion (Generierung, Lizenzverkauf, Zahlung, Einstellungsänderung …)
wird mit Zeitstempel, Ereignistyp und Details protokolliert.

- Einsehbar unter `/audit`.
- Export als CSV (`/audit.csv`) für die Projektdokumentation.

---

## Authentifizierung & Rollen

- Flask-Login mit server-seitigen Sessions (kein Cookie-Limit).
- Rollen: **Admin** (voller Zugriff) und **User** (nur Beat-Generierung).
- Standardmäßig ist ein Admin-Account beim ersten Start anzulegen.

---

## Aufbau — Dateiübersicht

### Anwendungskern
| Datei | Zweck |
|---|---|
| `app.py` | Flask-Einstiegspunkt, Blueprints, Login-Manager |
| `auth.py` | Login / Logout, User-Modell |
| `config.py` | Pfade, Preis-Stufen, Limits, Abrechnung |
| `database.py` | SQLite-Schema, Einstellungen, Audit-Log, Migration |
| `rbac.py` | Rollen-Decorator (`@require_admin`) |

### Beat-Generierung & Audio
| Datei | Zweck |
|---|---|
| `generate.py` | Blueprint für /generate, /rerender, /export, /theory_score … |
| `groove_processor.py` | Mixer-Transformationen auf Noten-Tupeln (Mute, Vol, Swing …) |
| `groove_bridge.py` | Brücke zu MA V7 `CompositionGroover` (Beat-Raum Groove) |
| `groove_data.py` | Genre- und Feel-Preset-Daten aus MA V7 (read-only) |
| `theory_scorer.py` | BDRA-Validierung P1–P5 via MA V7 `bdra_rules` |
| `sample_upload.py` | Blueprint für Sample-Upload/-Löschung pro Spur |
| `export_service.py` | WAV / MP3 / FLAC / MIDI Export-Konvertierung |
| `piano_roll_extractor.py` | Noten-Extraktion für die Piano-Roll-Ansicht |
| `production_advisor.py` | Mixing-Empfehlungen nach Genre-Produktionsregeln |
| `synth_core_fix.py` | Kompatibilitäts-Patch für den eingebauten Synthesizer |

### Daten & Presets
| Datei | Zweck |
|---|---|
| `palette_data.py` | Instrument-Paletten aus MA V7 (BDRA-Codes) |
| `instrument_data.py` | GM-Instrument-Listen pro Spur |
| `fusion_data.py` | Fusion-Presets (Genre-Kombinationen) |
| `groove_data.py` | Groove- und Feel-Preset-Bibliothek |
| `gm_desc_data.py` | GM-Programm-Beschreibungen |
| `mixer_data.py` | Mixer-Voreinstellungen |
| `prompt_data.py` | Prompt-Dekodierung (Freitext → Parameter) |

### Katalog & Verwaltung
| Datei | Zweck |
|---|---|
| `scanner.py` | Katalog- und Export-Ordner scannen (read-only) |
| `licensing.py` | Lizenzverkauf, Exklusiv-Sperre, Abo-Rabatt |
| `quota.py` | Nutzerverwaltung, Kontingent, Tageslimit |
| `gateway.py` | Limit-Prüfung vor Generierung (Gateway-Pattern) |
| `billing.py` | Checkout, Zahlung, Storno, Abo-Laufzeit, Rechnungsdaten |
| `economics.py` | Umsatz, Deckungsbeitrag, Break-even, ROI |
| `watermark_reader.py` | Layer-1-Wasserzeichen aus `.mid` auslesen (mido) |
| `demo_data.py` | Demo-Wasserzeichen und Beispieldaten erzeugen |
| `stats.py` | Nutzungsstatistiken-Blueprint |

---

## Erster Durchlauf (Demo)

1. App starten, einloggen.
2. Auf **Beat generieren** gehen — Genre wählen, „▶ Generieren" klicken.
3. Beat anhören, Piano Roll ansehen, Theory Score prüfen.
4. Im **Groove & Mixer**: Feel laden (z. B. „Boom Bap" für Hiphop), Re-Rendern.
5. Eigenes Sample für eine Spur hochladen → erneut Re-Rendern.
6. Track im gewünschten Format exportieren.
7. Im Admin-Bereich: **Demo-Daten erzeugen** → **Scannen** → Katalog ansehen.
8. Track-Detail öffnen → Lizenz verkaufen → Checkout → Zahlung bestätigen.
9. **Wirtschaftlichkeit** und **Audit-Protokoll** ansehen.

## Echtbetrieb — Kopplung an eigene Ordner

Unter **Einstellungen**:
- *Katalog-Ordner*: Pfad zu den watermarked `.mid`-Dateien von Music Architect.
- *Export-Ordner*: Pfad zu den gemasterten Audiodateien der DAW.
- *Music Architect Befehl*: z. B. `python /pfad/music_architect_v7/main.py --count {count}`.

Danach **Scannen** — alle vorhandenen Tracks werden in den Katalog übernommen.

---

## Technische Hinweise

- **Groove-Stacking**: Re-Render startet immer von der originalen Komposition —
  mehrfaches Re-Rendern akkumuliert keine Effekte.
- **SF2 + Samples**: FluidSynth wird automatisch deaktiviert, sobald Samples
  zugewiesen sind (FluidSynth unterstützt keine rohen Audiopuffer).
- **Session-Storage**: Große Audio-Pfade liegen im Dateisystem (Flask-Session),
  nicht im Cookie — kein 4-KB-Limit.
- **Layer-2-Wasserzeichen** (Velocity-LSB) wird von diesem Modul nicht dekodiert —
  dafür ist die Original-Engine zuständig (`python main.py watermark --extract`).
- **Plattformkompatibilität**: alle Pfad-Operationen via `pathlib`, kein
  OS-spezifischer Code.
