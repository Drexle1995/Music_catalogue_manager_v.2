"""
Zentrale Konfiguration des Katalog- & Lizenzverwaltungsmoduls.

WICHTIG (Kopplungsprinzip):
Dieses Modul verändert weder Music Architect V7 noch SBS-Synth Master.
Es liest ausschließlich deren Ausgabedateien (read-only). Die Pfade unten
müsst ihr einmalig auf eure echten Ausgabeordner setzen (oder im Reiter
"Einstellungen" in der Web-Oberfläche anpassen).
"""

import os

# Basisverzeichnis dieses Moduls
BASE_DIR = os.path.abspath(os.path.dirname(__file__))

# SQLite-Datei (eine einzige Datei, kein Server, keine Einrichtung).
DB_PATH = os.path.join(BASE_DIR, "instance", "catalog.db")

# ---------------------------------------------------------------------------
# Kopplung an die beiden Sound-Programme (read-only)
# ---------------------------------------------------------------------------
# 1) Music Architect V7 legt wasserzeichenmarkierte .mid-Dateien ab, z. B. unter
#    Watermarked_Catalog/<genre>/track_XXX.mid  -> das ist der KATALOG-Ordner.
# 2) SBS-Synth Master exportiert die gemasterten Audiodateien (WAV/MP3) in den
#    vier Stufen (Preview/Streaming/Lease/Trackout) -> das ist der EXPORT-Ordner.
#
# Standard: die mitgelieferten Beispielordner, damit das Tool sofort ohne echte
# Daten läuft. Für den Echtbetrieb auf eure Pfade ändern.
DEFAULT_CATALOG_DIR = os.path.join(BASE_DIR, "sample_catalog")
DEFAULT_EXPORT_DIR = os.path.join(BASE_DIR, "sample_exports")

# ---------------------------------------------------------------------------
# Preis-Stufen (Tiers) — 1:1 an die Export-Ziele der DAW angelehnt.
# Beträge in Euro. Über die Weboberfläche editierbar (Tabelle "settings").
# ---------------------------------------------------------------------------
DEFAULT_TIERS = {
    # key             Anzeigename          DAW-Export-Ziel          Standardpreis
    "preview_mp3":   {"label": "Promo (MP3)",        "export": "Preview MP3",    "price": 0.0,   "kind": "lease"},
    "lease_mp3":     {"label": "Basic-Lizenz (MP3)", "export": "Preview MP3",    "price": 20.0,  "kind": "lease"},
    "lease_wav":     {"label": "Premium-Lizenz (WAV)","export": "Streaming WAV", "price": 35.0,  "kind": "lease"},
    "trackout":      {"label": "Trackout / Stems",   "export": "Trackout Stems", "price": 80.0,  "kind": "lease"},
    "exclusive":     {"label": "Exklusiv (Vollrechte)","export": "Lease WAV",    "price": 250.0, "kind": "exclusive"},
}

# ---------------------------------------------------------------------------
# Wirtschaftlichkeits-Annahmen (Standardwerte, in der Oberfläche editierbar).
# ---------------------------------------------------------------------------
DEFAULT_ECONOMICS = {
    # Einmalige Investition / Fixkosten (Entwicklung + Werkzeuge)
    "dev_hours":        "120",     # geleistete Entwicklungsstunden
    "hourly_rate":      "45.0",    # kalkulatorischer Stundensatz (EUR)
    "tooling_cost":     "150.0",   # Lizenzen/Werkzeuge einmalig (EUR)
    # Variable Kosten je Track (z. B. Rechenzeit für AI-Rendering, Speicher)
    "cost_per_track":   "0.15",    # EUR pro erzeugtem Track
}

# Dateiendungen, die als DAW-Audioexporte erkannt werden.
AUDIO_EXTENSIONS = (".wav", ".mp3", ".flac", ".ogg")

# Endungs-/Namensmuster -> Tier-Zuordnung beim Scan der Exportdateien.
# Der Dateiname-Stamm wird gegen die Katalog-Tracks gematcht; das Suffix
# entscheidet, welcher Export-Stufe die Datei zugeordnet wird.
EXPORT_SUFFIX_MAP = {
    "preview":   "preview_mp3",
    "promo":     "preview_mp3",
    "streaming": "lease_wav",
    "stream":    "lease_wav",
    "lease":     "lease_mp3",
    "trackout":  "trackout",
    "stems":     "trackout",
    "master":    "lease_wav",
}


# ---------------------------------------------------------------------------
# Abo-/Freemium-Modell (Subscription)
# ---------------------------------------------------------------------------
# Tageslimit fuer die Track-Generierung: einfache Nutzer vs. Abonnenten.
DEFAULT_SUBSCRIPTION = {
    "limit_free":       "3",     # Tracks/Tag ohne Abo
    "limit_subscriber": "10",    # Tracks/Tag mit Abo
    "discount_pct":     "5",     # Rabatt in % fuer Abonnenten beim Lizenzkauf
}

# Aufrufbefehl fuer Music Architect (Echtbetrieb). Platzhalter {count} und
# {user} werden ersetzt, falls vorhanden. Leer = Simulationsmodus (der Gateway
# erzeugt dann selbst Demo-Wasserzeichen-MIDIs, damit alles ohne das echte
# Programm lauffaehig bleibt).
# Beispiel Echtbetrieb:  python /pfad/music_architect_v7/main.py --count {count}
DEFAULT_MA_COMMAND = ""


# ---------------------------------------------------------------------------
# Abrechnung / Rechnung
# ---------------------------------------------------------------------------
DEFAULT_BILLING = {
    "seller_name":     "SBS Sound Studio",   # erscheint auf der Rechnung
    "vat_pct":         "19",                 # Umsatzsteuer in % (0 = Kleinunternehmer)
    "sub_price_month": "9.99",               # Abo-Preis pro Monat (EUR)
}

# Waehlbare Abo-Laufzeiten (Monate) fuer den Checkout.
SUBSCRIPTION_TERMS = [1, 3, 12]


# ---------------------------------------------------------------------------
# Token-Nachkauf (Generierung ueber das Kontingent hinaus)
# ---------------------------------------------------------------------------
# Ist das Tages-/Monatskontingent aufgebraucht, verbraucht jede weitere
# Generierung (bzw. jeder weitere Speichervorgang) genau 1 Token.
# Abonnenten zahlen pro Token weniger als Basis-Nutzer. Die Preise sind
# Nettopreise in EUR und in den Einstellungen editierbar; dort wird auch
# erzwungen, dass der Abo-Preis unter dem Basis-Preis liegt.
DEFAULT_TOKENS = {
    "token_price_basic":      "1.49",   # EUR netto pro Token ohne Abo
    "token_price_subscriber": "0.99",   # EUR netto pro Token mit aktivem Abo
}

# Waehlbare Paketgroessen (Anzahl Tokens) im Token-Shop.
TOKEN_PACKAGES = [1, 5, 10, 25]
