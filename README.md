# SBS Catalog — Lizenz- & Wirtschaftlichkeitsmodul

Kaufmännisches Ergänzungsmodul zum Musikproduktions-Gesamtpaket aus
**Music Architect V7** (AI-Beat-Generator) und **SBS-Synth Master** (DAW/Mastering).

Das Modul verwaltet den erzeugten Musikkatalog, verkauft Lizenzen mit Exklusiv-Schutz,
rechnet die Wirtschaftlichkeit (Umsatz, Deckungsbeitrag, Break-even, ROI) und führt ein
revisionssicheres Audit-Protokoll. Es ist der betriebswirtschaftliche Teil des
Abschlussprojekts und macht aus der reinen Produktionstechnik ein verkaufsfähiges Produkt.

## Kernidee: read-only Kopplung

Das Modul **verändert weder Music Architect noch die DAW**. Es liest ausschließlich deren
Ausgabedateien:

- **Katalog** ← `.mid`-Dateien von Music Architect (inkl. Layer-1-Wasserzeichen:
  `copyright`-Tag + SHA-256-Hash, ausgelesen per `mido`).
- **Exporte** ← gemasterte Audiodateien der DAW (WAV/MP3), zugeordnet über den Dateinamen
  und die vier Export-Stufen (Preview / Streaming / Lease / Trackout).

Dadurch bleibt die Kopplung robust und die beiden Sound-Programme im Fokus — dieses Modul
ergänzt lediglich.

## Installation

```bash
cd music_catalog_manager
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

Dann im Browser öffnen: <http://127.0.0.1:5000>

## Erster Durchlauf (Demo, ohne echte Daten)

1. Auf dem Dashboard **„Demo-Daten erzeugen“** klicken. Das schreibt echte
   wasserzeichenmarkierte MIDI-Dateien nach `sample_catalog/` und Platzhalter-Exporte
   nach `sample_exports/` — also ein vollständiger, nicht simulierter End-to-End-Test.
2. Oben rechts **„↻ Scannen“** klicken. Der Katalog und die Exporte werden eingelesen.
3. Im **Katalog** einen Track öffnen und eine **Lizenz verkaufen** (z. B. Exklusiv).
   Ein exklusiv verkaufter Track wird danach automatisch gesperrt.
4. **Wirtschaftlichkeit** und **Protokoll** ansehen.

## Echtbetrieb (Kopplung an eure Ordner)

Unter **Einstellungen** die beiden Pfade setzen:

- *Katalog-Ordner*: wohin Music Architect die watermarked `.mid` schreibt
  (z. B. `.../music_architect_v7/Watermarked_Catalog`).
- *Export-Ordner*: wohin die DAW die gemasterten Audiodateien exportiert.

Danach **„↻ Scannen“**. Passt euer DAW-Export ein anderes Namensschema an, könnt ihr die
Suffix-Zuordnung in `config.py` (`EXPORT_SUFFIX_MAP`) anpassen.

## Abo-/Freemium-Modell

Das Modul bildet ein Freemium-Modell ab:

- **Tages-Bezugslimit**: Pro Tag darf ein Nutzer eine begrenzte Zahl an Tracks
  *beziehen* — Basis-Nutzer 3, Abonnenten 10 (konfigurierbar). Als Bezug zählen
  **sowohl Generierungen als auch gekaufte Lizenzen** gegen denselben Tages-Topf;
  ein Lizenzkauf lässt den Zähler also hochspringen. Ist der Topf leer, werden
  weitere Generierungen und Käufe abgelehnt. Stornierte Lizenzen geben ihren Bezug
  wieder frei. Gäste (nicht registriert) unterliegen keinem Limit.
- **Abo-Rabatt**: registrierte Abonnenten erhalten beim Lizenzkauf automatisch
  5 % Rabatt (konfigurierbar). Listenpreis, Rabatt und Nettopreis werden getrennt
  gespeichert, sodass die Wirtschaftlichkeitsrechnung korrekt bleibt.

### Durchsetzung über den Gateway (kein Eingriff ins Partnerprojekt)

Das Tageslimit wird **vor** der Generierung durchgesetzt. Der Gateway `gateway.py`
prüft zuerst das Kontingent des Nutzers und ruft **erst dann** Music Architect auf.
Der Code des Partnerprojekts bleibt dadurch unangetastet — er wird nur als externer
Prozess gestartet.

- **Simulationsmodus** (Standard): ist kein Befehl hinterlegt, erzeugt der Gateway
  selbst wasserzeichenmarkierte Demo-MIDIs. So ist der komplette Freemium-Ablauf
  ohne das echte Programm vorführbar.
- **Echtbetrieb**: unter *Einstellungen* den Aufrufbefehl setzen, z. B.
  `python /pfad/music_architect_v7/main.py --count {count}`. Die Platzhalter
  `{count}` und `{user}` werden ersetzt. Fehlgeschlagene Läufe verbrauchen kein
  Kontingent.

CLI-Beispiele:
```bash
python gateway.py --user "Abo-Kunde (Demo)" --count 4
python gateway.py --user 2 --count 5 --simulate
```
In der Weboberfläche geht es einfacher: Reiter **Nutzer** → Anzahl wählen → „Erzeugen“,
danach oben „Scannen“, um die neuen Tracks in den Katalog zu übernehmen.

Beim Lizenzverkauf im Track-Detail wählt man den Käufer aus der Nutzerliste; ist es
ein aktiver Abonnent, wird der Rabatt automatisch abgezogen (Gast = kein Rabatt).

## Abrechnung (simuliert)

Der komplette Zahlungsfluss ist nachgebildet — ohne echten Zahlungsdienstleister und
ohne echte Kartendaten:

- **Lizenz-Checkout**: Ein Verkauf legt die Lizenz zunächst mit Status *offen* an und
  reserviert den Track (Exklusiv-Sperre greift sofort). Im Checkout bestätigt man die
  simulierte Zahlung → Status *bezahlt*, oder man storniert → der Track wird wieder
  freigegeben. **Nur bezahlte** Positionen zählen als Umsatz.
- **Abo mit Laufzeit**: Im Reiter *Nutzer* eine Laufzeit (1/3/12 Monate) wählen und
  „Buchen“ → Checkout → Zahlung bestätigen. Das Abo wird mit Start-/Enddatum aktiv,
  der Abo-Umsatz wird gebucht, und das höhere Tageslimit sowie der Rabatt gelten nur
  innerhalb der Laufzeit.
- **Rechnung/Beleg**: Zu jeder Position gibt es eine Rechnungsansicht mit Netto, USt
  (Satz konfigurierbar, Standard 19 %) und Brutto, inklusive Druckfunktion.
- **Umsatz** teilt sich in der Wirtschaftlichkeit in **Lizenz-** und **Abo-Umsatz** auf;
  offene (unbezahlte) Beträge werden separat ausgewiesen.

In einem echten Rollout ersetzt ein Zahlungsdienstleister (z. B. Stripe/Mollie) den
simulierten Bestätigungsschritt und schaltet per Webhook den Status auf „bezahlt“
bzw. das Abo bei ausbleibender Zahlung wieder ab — die übrige Logik bleibt gleich.

## Aufbau

| Datei | Zweck |
| ----- | ----- |
| `app.py` | Flask-Anwendung + Routen |
| `config.py` | Pfade, Preis-Stufen, Kostenannahmen, Abo-Limits, Abrechnung |
| `database.py` | SQLite-Schema, Einstellungen, Audit-Log, Migration |
| `watermark_reader.py` | liest Layer-1-Wasserzeichen aus `.mid` (mido) |
| `scanner.py` | scannt Katalog- + Export-Ordner (read-only) |
| `licensing.py` | Lizenzverkauf mit Exklusiv-Sperre + Abo-Rabatt |
| `quota.py` | Nutzerverwaltung, Nutzungszählung, Tageslimit |
| `gateway.py` | Durchsetzungspunkt des Limits vor der Generierung |
| `billing.py` | Checkout, Zahlung, Storno, Abo-Laufzeit, Rechnungsdaten |
| `economics.py` | Umsatz (Lizenz/Abo), Deckungsbeitrag, Break-even, ROI |
| `demo_data.py` | erzeugt echte Demo-Wasserzeichen |
| `templates/`, `static/` | Weboberfläche (Dark-Neon, passend zur DAW) |

## Bezug zum Abschlussprojekt

- **Funktionsfähig & gekoppelt**: liest die echten Ausgaben beider Programme.
- **Wirtschaftlicher Aspekt**: Preis-Stufen = Erlösmodell, dazu Break-even/ROI-Rechnung.
- **Protokoll**: das Audit-Log erfüllt die Protokollpflicht auf Software-Ebene und lässt
  sich als CSV für die Dokumentation exportieren.

## Hinweise

- Layer-2-Wasserzeichen (Velocity-LSB) wird hier nicht dekodiert — dafür ist die
  Original-Engine zuständig (`python main.py watermark --extract ...`).
- Die AI-Nutzung im Gesamtprojekt ist in den READMEs der Sound-Programme offengelegt.
- Rechtliche Fragen (Schutzfähigkeit AI-generierter Musik) sind ein sinnvoller
  Risiko-/Rechtsaspekt für die schriftliche Ausarbeitung — bitte eigenständig belastbar
  recherchieren (dies ist keine Rechtsberatung).
