"""
palette_data.py — Laedt Instrumenten-Paletten, FX-Varianten und berechnet
den Theorie-Score direkt aus den MUSIC_ARCHITECT_V7 Production-Guide-JSONs.

Datenquellen (read-only):
  - instrument_palettes.json  → Paletten mit BDRA-Codes pro Genre
  - fx_variants.json          → FX-Ketten-Varianten (bright/neutral/dark)
  - <genre>.json              → valid_scales, bpm_range fuer Theorie-Pruefungen

Plattformunabhaengig — nur Python-Stdlib. Kein Tkinter, keine OS-APIs.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple

# Pfad zum MA V7 Production-Guide-Verzeichnis
_GUIDE_DIR = (
    pathlib.Path(__file__).parent.parent
    / "MUSIC_ARCHITECT_V7"
    / "data"
    / "production_guide"
    / "json"
)

# Genre → Dateiname fuer Genre-JSONs (identisch mit production_advisor.py)
_GENRE_FILES: Dict[str, str] = {
    "trap":      "trap.json",
    "phonk":     "phonk.json",
    "hiphop":    "hiphop.json",
    "techno":    "techno.json",
    "house":     "house.json",
    "edm":       "house.json",
    "pop":       "pop.json",
    "cinematic": "cinematic.json",
    "classical": "cinematic.json",
    "jpop":      "jpop.json",
}

# Laufzeit-Caches (Dateien werden einmalig gelesen)
_palettes_cache: Optional[Dict]  = None
_fx_cache:       Optional[Dict]  = None
_genre_cache:    Dict[str, Dict] = {}


def _load_palettes() -> Dict:
    global _palettes_cache
    if _palettes_cache is None:
        path = _GUIDE_DIR / "instrument_palettes.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        _palettes_cache = {k: v for k, v in data.items() if k != "_meta"}
    return _palettes_cache


def _load_fx() -> Dict:
    global _fx_cache
    if _fx_cache is None:
        path = _GUIDE_DIR / "fx_variants.json"
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        _fx_cache = data.get("variants", {})
    return _fx_cache


def _load_genre(genre: str) -> Dict:
    if genre not in _genre_cache:
        fname = _GENRE_FILES.get(genre, "pop.json")
        path  = _GUIDE_DIR / fname
        try:
            with open(path, encoding="utf-8") as fh:
                _genre_cache[genre] = json.load(fh)
        except FileNotFoundError:
            _genre_cache[genre] = {}
    return _genre_cache[genre]


# ---------------------------------------------------------------------------
# Oeffentliche API
# ---------------------------------------------------------------------------

def get_palettes(genre: str) -> List[Dict]:
    """
    Gibt alle vorvalidierten Instrumenten-Paletten fuer ein Genre zurueck.
    Jede Palette enthaelt id, name, branch, kick_code, kick_desc, instruments.
    """
    all_pal = _load_palettes()
    return all_pal.get(genre, all_pal.get("pop", []))


def get_fx_variants(genre: str) -> List[Dict]:
    """
    Gibt die FX-Ketten-Varianten (bright/neutral/dark) fuer ein Genre zurueck.
    Nur id, label und description werden zurueckgegeben (chain_overlay ausgelassen).
    """
    all_fx = _load_fx()
    variants = all_fx.get(genre, all_fx.get("pop", []))
    return [{"id": v["id"], "label": v["label"], "description": v.get("description", "")}
            for v in variants]


def get_palette_by_id(genre: str, palette_id: str) -> Optional[Dict]:
    """Gibt eine einzelne Palette anhand ihrer ID zurueck."""
    for pal in get_palettes(genre):
        if pal.get("id") == palette_id:
            return pal
    return None


# ---------------------------------------------------------------------------
# Vollstaendige GM → BDRA-Zuordnung (genreuebergreifend)
# ---------------------------------------------------------------------------

def get_all_gm_bdra_codes() -> Dict[str, Dict[int, str]]:
    """
    Gibt eine vollstaendige Zuordnung von GM-Programmnummer zu BDRA-Code
    fuer alle Spur-Typen zurueck, aggregiert aus allen Genres und Paletten.

    Rueckgabe: { spur_key: { gm_nummer: bdra_code } }
    Beispiel:  { "bass": { 35: "B0 D2 A1 R0", 34: "B0 D2 A1 R0" }, ... }

    Wird einmalig beim ersten Aufruf berechnet und danach gecacht.
    """
    if _gm_bdra_cache:
        return _gm_bdra_cache

    alle_paletten = _load_palettes()
    # Ueber alle Genres und alle Paletten iterieren
    for genre_paletten in alle_paletten.values():
        for palette in genre_paletten:
            for spur_key, instr in palette.get("instruments", {}).items():
                gm   = instr.get("gm")
                code = instr.get("code", "")
                if gm is not None and code:
                    _gm_bdra_cache.setdefault(spur_key, {})[int(gm)] = code

    return _gm_bdra_cache


# Laufzeit-Cache fuer get_all_gm_bdra_codes (einmalig befuellt)
_gm_bdra_cache: Dict[str, Dict[int, str]] = {}


# ---------------------------------------------------------------------------
# BDRA-Hilfsfunktionen
# ---------------------------------------------------------------------------

def parse_bdra(code: str) -> Dict[str, int]:
    """
    Parst einen BDRA-Code-String in ein Dict.
    Beispiel: 'B1 D2 A0 R2' → {'B': 1, 'D': 2, 'A': 0, 'R': 2}
    """
    result: Dict[str, int] = {}
    for part in (code or "").split():
        if len(part) >= 2 and part[0] in "BDAR":
            try:
                result[part[0]] = int(part[1])
            except ValueError:
                pass
    return result


# ---------------------------------------------------------------------------
# Theorie-Score (P1–P5)
# ---------------------------------------------------------------------------

def score_theory(
    genre: str,
    bpm: float,
    scale: str,
    instruments: Dict[str, Dict],
) -> Dict:
    """
    Berechnet den Theorie-Score fuer eine Instrumentenwahl.

    P1 — BPM: Liegt das Tempo im gueltigen Genre-Bereich?
    P2 — Tonleiter: Ist die Tonleiter fuer dieses Genre gueltig?
    P3 — Register (R-Achse): Bass tief (R≤1), Lead hoch (R≥2)?
    P4 — Dichte (D-Achse): Nicht mehr als 2 Spuren mit D=3?
    P5 — Helligkeit (B-Achse): Bass B < Lead B (logische Hierarchie)?

    Jede Pruefung ergibt 0, 10 (partiell) oder 20 Punkte → max. 100.

    Returns
    -------
    {
      "score":    int (0-100),
      "grade":    str,
      "checks":   { "p1": {...}, ..., "p5": {...} },
      "feedback": str,
    }
    """
    genre_data = _load_genre(genre)
    checks:    Dict[str, Dict] = {}
    total:     int = 0

    # ── P1: BPM im Genre-Bereich ──────────────────────────────────────────
    bpm_range = genre_data.get("bpm_range", [60, 200])
    bpm_lo, bpm_hi = bpm_range[0], bpm_range[1]
    bpm_ok      = bpm_lo <= bpm <= bpm_hi
    # Bis zu 20 BPM ausserhalb → partielles Bestehen
    bpm_partial = not bpm_ok and (bpm_lo - 20 <= bpm <= bpm_hi + 20)
    checks["p1"] = {
        "label":   "BPM",
        "pass":    bpm_ok,
        "partial": bpm_partial,
        "detail": (
            f"BPM {bpm:.0f} liegt im Genre-Bereich {bpm_lo}–{bpm_hi}"
            if bpm_ok else
            f"BPM {bpm:.0f} ausserhalb Bereich {bpm_lo}–{bpm_hi} fuer {genre}"
        ),
    }
    total += 20 if bpm_ok else (10 if bpm_partial else 0)

    # ── P2: Tonleiter gueltig fuer Genre ─────────────────────────────────
    valid_scales = [s.lower().replace(" ", "_").replace("-", "_")
                    for s in genre_data.get("valid_scales", [])]
    scale_norm = scale.lower().replace(" ", "_").replace("-", "_")
    scale_ok = scale_norm in valid_scales

    # Verwandte Tonleitern-Gruppen → partielles Bestehen
    SCALE_GROUPS = [
        {"minor", "natural_minor", "harmonic_minor", "melodic_minor",
         "phrygian", "pentatonic_minor", "blues"},
        {"major", "lydian", "mixolydian", "pentatonic_major", "dorian",
         "japanese"},
    ]
    scale_partial = False
    if not scale_ok and valid_scales:
        for grp in SCALE_GROUPS:
            if scale_norm in grp and any(v in grp for v in valid_scales):
                scale_partial = True
                break

    checks["p2"] = {
        "label":   "Tonleiter",
        "pass":    scale_ok,
        "partial": scale_partial,
        "detail": (
            f"Tonleiter '{scale}' ist korrekt fuer {genre}"
            if scale_ok else
            f"'{scale}' passt nicht optimal zu {genre} — empfohlen: {', '.join(valid_scales[:3])}"
        ),
    }
    total += 20 if scale_ok else (10 if scale_partial else 0)

    # ── P3: Register (R-Achse) — Bass tief, Lead hoch ───────────────────
    bass_bdra  = parse_bdra(instruments.get("bass",  {}).get("code", "B1 D1 A1 R1"))
    lead_bdra  = parse_bdra(instruments.get("lead",  {}).get("code", "B2 D2 A1 R2"))

    bass_r, lead_r = bass_bdra.get("R", 1), lead_bdra.get("R", 2)
    reg_ok      = bass_r <= 1 and lead_r >= 2
    reg_partial = not reg_ok and (bass_r <= 2 and lead_r >= 1)
    checks["p3"] = {
        "label":   "Register",
        "pass":    reg_ok,
        "partial": reg_partial,
        "detail": (
            f"Register: Bass R={bass_r}, Lead R={lead_r} — optimale Spektral-Trennung"
            if reg_ok else
            f"Register: Bass R={bass_r}, Lead R={lead_r} — Bass sollte R≤1, Lead R≥2 haben"
        ),
    }
    total += 20 if reg_ok else (10 if reg_partial else 0)

    # ── P4: Dichte (D-Achse) — max. 2 Spuren mit D=3 ────────────────────
    d_vals      = [parse_bdra(v.get("code", "")).get("D", 1)
                   for v in instruments.values() if isinstance(v, dict) and v.get("code")]
    dense_count = sum(1 for d in d_vals if d == 3)
    density_ok      = dense_count <= 2
    density_partial = dense_count == 3
    checks["p4"] = {
        "label":   "Dichte",
        "pass":    density_ok,
        "partial": density_partial,
        "detail": (
            f"Dichte: {dense_count} dichte Spuren (D=3) — ausgewogene Textur"
            if density_ok else
            f"Dichte: {dense_count} Spuren mit D=3 — zu viel Sattigung, max. 2 empfohlen"
        ),
    }
    total += 20 if density_ok else (10 if density_partial else 0)

    # ── P5: Helligkeit (B-Achse) — Bass B < Lead B ──────────────────────
    bass_b, lead_b = bass_bdra.get("B", 1), lead_bdra.get("B", 2)
    bright_ok      = bass_b < lead_b
    bright_partial = bass_b == lead_b        # gleiche Helligkeit = Warnung
    margin         = lead_b - bass_b
    checks["p5"] = {
        "label":   "Helligkeit",
        "pass":    bright_ok,
        "partial": bright_partial,
        "detail": (
            f"Helligkeit: Lead B={lead_b}, Bass B={bass_b} — {margin}-Stufen-Abstand"
            if bright_ok else
            (f"Helligkeit gleich: Lead B={lead_b}, Bass B={bass_b} — 1-Stufen-Abstand empfohlen"
             if bright_partial else
             f"Bass B={bass_b} heller als Lead B={lead_b} — Hierarchie umkehren")
        ),
    }
    total += 20 if bright_ok else (10 if bright_partial else 0)

    # ── Gesamtbewertung ──────────────────────────────────────────────────
    if total >= 90:
        grade = "EXZELLENT"
    elif total >= 70:
        grade = "GUT"
    elif total >= 50:
        grade = "BEFRIEDIGEND"
    else:
        grade = "VERBESSERUNGSBEDARF"

    # Feedback: erster fehlgeschlagener Check
    issues = [c["detail"] for c in checks.values() if not c["pass"] and not c["partial"]]
    partials = [c["detail"] for c in checks.values() if not c["pass"] and c["partial"]]
    feedback = (issues + partials)[0] if (issues or partials) else (
        f"Alle Theorie-Regeln erfuellt fuer {genre}")

    return {
        "score":    total,
        "grade":    grade,
        "checks":   checks,
        "feedback": feedback,
    }
