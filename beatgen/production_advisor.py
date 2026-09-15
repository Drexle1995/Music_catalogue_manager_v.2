"""
production_advisor.py — Produktionsberater-Daten fuer den Web-Generator.

Laedt genre-spezifische JSON-Produktionsleitfaeden aus dem MUSIC_ARCHITECT_V7-
Projekt (read-only) und stellt strukturierte Daten fuer die Advisor-Anzeige bereit:
  - Gain-Staging-Ziele pro Spur
  - Effektketten pro Spur
  - Frequenzallokation
  - BPM-Zeitwerte
  - Export-Spezifikationen
  - Parallelverdichtung
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

import json
import pathlib
from typing import Any, Dict, List, Optional, Tuple

# Pfad zu den Produktionsleitfaden-JSONs.
_GUIDE_DIR = (
    pathlib.Path(__file__).parent.parent.parent
    / "MUSIC_ARCHITECT_V7"
    / "data"
    / "production_guide"
    / "json"
)

# Abbildung Genre -> JSON-Dateiname (Fallback auf 'pop' falls nicht gefunden).
_GENRE_FILES: Dict[str, str] = {
    "trap":      "trap.json",
    "phonk":     "phonk.json",
    "hiphop":    "hiphop.json",
    "techno":    "techno.json",
    "house":     "house.json",
    "edm":       "house.json",   # kein eigenes EDM-File -> House als naechstes
    "pop":       "pop.json",
    "cinematic": "cinematic.json",
    "classical": "cinematic.json",
    "jpop":      "jpop.json",
    "dnb":       "dnb.json",
}

# Interne Spur-Aliasse (JSON-Schluessel vs. Config-Schluessel).
_TRACK_ALIAS: Dict[str, str] = {
    "melody": "lead",
    "pads":   "pad",
}

# Kein Cache — JSON-Dateien sind klein und selten geoeffnet.
def _load_genre_json(genre: str) -> Dict[str, Any]:
    """
    Laedt die JSON-Datei fuer das angegebene Genre.
    Gibt ein leeres Dict zurueck, wenn die Datei nicht gefunden wird.
    """
    filename = _GENRE_FILES.get(genre, "pop.json")
    path     = _GUIDE_DIR / filename
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def compute_bpm_times(bpm: float) -> Dict[str, str]:
    """
    Berechnet BPM-abhaengige Zeitwerte (in ms) aus einer gegebenen Tempozahl.
    Rueckgabe als {bezeichnung: wert_string}.
    """
    if not bpm or bpm <= 0:
        return {}
    ms = 60000.0 / bpm
    return {
        "1/4-Note":       f"{ms:.1f} ms",
        "1/8-Note":       f"{ms / 2:.1f} ms",
        "1/8 punktiert":  f"{ms * 0.75:.1f} ms",
        "1/16-Note":      f"{ms / 4:.1f} ms",
        "Pre-Delay":      f"{ms / 16:.1f} ms",
        "SC Release":     f"{ms * 2.5:.1f} ms",
        "CMP Release":    f"{ms * 11.5:.1f} ms",
    }


def get_gain_staging(genre: str) -> List[Dict[str, Any]]:
    """
    Gibt Gain-Staging-Ziele pro Spur zurueck.
    Format: [{'track': str, 'rms': float, 'peak': float, 'lufs_s': float}, ...]
    """
    data   = _load_genre_json(genre)
    tracks = data.get("tracks", {})
    result: List[Dict[str, Any]] = []

    for json_key, track_data in tracks.items():
        cfg_key = _TRACK_ALIAS.get(json_key, json_key)
        gs      = track_data.get("gain_staging", {})
        if not gs:
            continue
        result.append({
            "track":      cfg_key,
            "label":      json_key.upper(),
            "rms":        gs.get("clip_gain_rms_dbfs"),
            "peak":       gs.get("peak_ceiling_dbfs"),
            "fader_db":   gs.get("output_fader_db"),
            "lufs_s":     gs.get("lufs_s"),
            "headroom":   gs.get("headroom_to_master_db"),
        })
    return result


def get_effect_chains(genre: str) -> Dict[str, List[Dict[str, str]]]:
    """
    Gibt Effektketten pro Spur zurueck.
    Format: {cfg_track: [{'slot': '1', 'effect': str, 'params': str}, ...]}
    """
    data   = _load_genre_json(genre)
    tracks = data.get("tracks", {})
    result: Dict[str, List[Dict[str, str]]] = {}

    for json_key, track_data in tracks.items():
        cfg_key = _TRACK_ALIAS.get(json_key, json_key)
        chain   = track_data.get("effect_chain", [])
        if not chain:
            continue
        result[cfg_key] = [
            {
                "slot":   str(e.get("slot", "")),
                "effect": e.get("effect", ""),
                "params": e.get("params", ""),
            }
            for e in chain
        ]
    return result


def get_frequency_allocation(genre: str) -> List[Dict[str, Any]]:
    """
    Gibt die Frequenzallokation pro Spur zurueck.
    Format: [{'track': str, 'hpf': str, 'lpf': str, 'zone': str, 'width': str?}, ...]
    """
    data   = _load_genre_json(genre)
    fa     = data.get("frequency_allocation", {})
    result: List[Dict[str, Any]] = []

    for json_key, fa_data in fa.items():
        cfg_key = _TRACK_ALIAS.get(json_key, json_key)
        hpf     = fa_data.get("hpf_hz", "")
        lpf     = fa_data.get("lpf_hz", "")
        result.append({
            "track":  cfg_key,
            "label":  json_key.upper(),
            "hpf":    str(hpf) if hpf else "—",
            "lpf":    str(lpf) if lpf else "—",
            "zone":   fa_data.get("dominant_zone", "—"),
            "claim":  fa_data.get("exclusive_claim", ""),
        })
    return result


def get_export_specs(genre: str) -> Dict[str, Any]:
    """
    Gibt Export-Spezifikationen (Streaming, Broadcast, Sync-Lizenzierung) zurueck.
    """
    data = _load_genre_json(genre)
    return data.get("export_specs", {})


def get_parallel_compression(genre: str) -> Dict[str, Any]:
    """
    Gibt die Parallelverdichtungs-Parameter zurueck.
    """
    data = _load_genre_json(genre)
    return data.get("parallel_compression", {})


def get_full_advisor(
    genre: str,
    bpm: float,
    composition: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """
    Kombiniert alle Advisor-Daten zu einem einzigen Dict fuer die UI.

    Parameter
    ---------
    genre       : Genre-String (z. B. 'pop', 'trap')
    bpm         : Aktuelles Tempo
    composition : Kompositions-Dict aus CompositionEngine.compose() (optional)

    Rueckgabewert
    -------------
    {
      'gain_staging':          [...],
      'effect_chains':         {...},
      'frequency_allocation':  [...],
      'export_specs':          {...},
      'parallel_compression':  {...},
      'bpm_times':             {...},
      'plr_target':            str,
      'lra_target':            str,
      'valid_scales':          [...],
    }
    """
    data = _load_genre_json(genre)

    return {
        "gain_staging":         get_gain_staging(genre),
        "effect_chains":        get_effect_chains(genre),
        "frequency_allocation": get_frequency_allocation(genre),
        "export_specs":         get_export_specs(genre),
        "parallel_compression": get_parallel_compression(genre),
        "bpm_times":            compute_bpm_times(bpm),
        "plr_target":           str(data.get("plr_target_db", "—")),
        "lra_target":           str(data.get("lra_target_lu", "—")),
        "valid_scales":         data.get("valid_scales", []),
    }
