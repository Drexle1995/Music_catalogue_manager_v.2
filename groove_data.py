"""
groove_data.py — Groove-Preset-Daten fuer den Web-Mixer.

Laedt die GroovePresetLibrary aus dem MUSIC_ARCHITECT_V7-Projekt (read-only)
und stellt vorberechnete Genre-Voreinstellungen fuer den Web-Mixer bereit.
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# MUSIC_ARCHITECT_V7-Pfad — relativ zu dieser Datei berechnet.
# ---------------------------------------------------------------------------
_MA_ROOT = pathlib.Path(__file__).parent.parent / "MUSIC_ARCHITECT_V7"
_MA_SRC  = _MA_ROOT / "src"


def _ensure_ma_path() -> None:
    """Fuegt MA-Pfade zu sys.path hinzu (idempotent)."""
    for p in (str(_MA_ROOT), str(_MA_SRC)):
        if p not in sys.path:
            sys.path.insert(0, p)


# Alle verfuegbaren Genre-Voreinstellungen (muss mit GroovePresetLibrary uebereinstimmen).
AVAILABLE_GENRES: List[str] = [
    "trap", "hiphop", "house", "edm", "techno",
    "dnb", "phonk", "pop", "jpop", "cinematic",
]


def get_groove_preset(genre: str) -> Dict[str, Dict[str, Any]]:
    """
    Gibt die Groove-Voreinstellung fuer ein Genre zurueck.

    Rueckgabewert
    -------------
    {
      track_key: {
        'gain_db':         float,
        'pan':             int,
        'swing_pct':       float,
        'timing_nudge_ms': float,
        'vel_min':         int,
        'vel_max':         int,
        'vel_curve':       str,
      },
      ...
    }
    Gibt ein leeres Dict zurueck, wenn die Bibliothek nicht verfuegbar ist.
    """
    try:
        _ensure_ma_path()
        from midi.groove_presets import GroovePresetLibrary  # type: ignore
        lib        = GroovePresetLibrary()
        song_cfg   = lib.get(genre)
        if song_cfg is None:
            return {}

        result: Dict[str, Dict[str, Any]] = {}
        for track_key, settings in song_cfg.tracks.items():
            result[track_key] = {
                "gain_db":         settings.gain_db,
                "pan":             settings.pan,
                "swing_pct":       settings.swing_pct,
                "timing_nudge_ms": settings.timing_nudge_ms,
                "vel_min":         settings.vel_min,
                "vel_max":         settings.vel_max,
                "vel_curve":       settings.vel_curve,
            }
        return result

    except Exception:
        return {}


def get_all_presets() -> Dict[str, Dict[str, Dict[str, Any]]]:
    """
    Laedt alle Genre-Voreinstellungen auf einmal (fuer die UI-Initialisierung).
    Rueckgabe: {genre: {track_key: settings}}
    """
    result: Dict[str, Dict[str, Dict[str, Any]]] = {}
    for genre in AVAILABLE_GENRES:
        preset = get_groove_preset(genre)
        if preset:
            result[genre] = preset
    return result


# ---------------------------------------------------------------------------
# Benannte Feels (Named Presets) pro Genre
# ---------------------------------------------------------------------------

def _settings_zu_dict(settings: Any) -> Dict[str, Any]:
    """Konvertiert ein TrackGrooveSettings-Objekt in ein JSON-serialisierbares Dict."""
    return {
        "gain_db":         settings.gain_db,
        "pan":             settings.pan,
        "swing_pct":       settings.swing_pct,
        "timing_nudge_ms": settings.timing_nudge_ms,
        "vel_min":         settings.vel_min,
        "vel_max":         settings.vel_max,
        "vel_curve":       settings.vel_curve,
    }


def get_named_presets_map() -> Dict[str, List[str]]:
    """
    Gibt alle verfuegbaren Feel-Namen pro Genre zurueck.

    Rueckgabewert
    -------------
    { genre: ["Boom Bap", "Lo-Fi Chill", "Modern Rap", ...], ... }

    Genres ohne benannte Presets sind nicht enthalten.
    Gibt ein leeres Dict zurueck, wenn die Bibliothek nicht verfuegbar ist.
    """
    try:
        _ensure_ma_path()
        from midi.groove_presets import NamedGroovePresetLibrary  # type: ignore
        lib = NamedGroovePresetLibrary()
        return {genre: lib.genre_names(genre) for genre in lib.all_genres()}
    except Exception:
        return {}


def get_named_groove_preset(genre: str, preset_name: str) -> Dict[str, Dict[str, Any]]:
    """
    Gibt die benannte Groove-Voreinstellung (Feel) fuer ein Genre zurueck.

    Die Basis-Genre-Werte werden mit den preset-spezifischen Ueberschreibungen
    zusammengefuehrt — identisch zur Logik in NamedGroovePresetLibrary.get_named().

    Rueckgabewert
    -------------
    { track_key: { gain_db, pan, swing_pct, timing_nudge_ms, vel_min, vel_max, vel_curve } }

    Gibt ein leeres Dict zurueck, wenn Genre oder Preset nicht gefunden wird.
    """
    try:
        _ensure_ma_path()
        from midi.groove_presets import NamedGroovePresetLibrary  # type: ignore
        lib      = NamedGroovePresetLibrary()
        song_cfg = lib.get_named(genre, preset_name)
        if song_cfg is None:
            return {}

        return {
            track_key: _settings_zu_dict(settings)
            for track_key, settings in song_cfg.tracks.items()
        }
    except Exception:
        return {}
