"""
groove_bridge.py — Bruecke zwischen Web-Frontend-Mixer und MA V7 CompositionGroover.

Drei Aufgaben:
  1. build_mixer_only_params  — Neutralisiert Timing/Velocity-Groove-Parameter, so dass
                                groove_processor nur Mixer-Aktionen (Mute, Lautstaerke,
                                Instrument) ausfuehrt.
  2. build_song_groove_settings — Wandelt Web-Frontend-Track-Parameter in ein
                                  MA V7 SongGrooveSettings-Objekt um.
  3. apply_composition_groover  — Ruft CompositionGroover.apply() auf und gibt None
                                  zurueck, wenn MA V7 nicht verfuegbar ist.

Alle drei Funktionen werden in /rerender aufgerufen, nachdem _ensure_ma_path()
den MA V7-Suchpfad gesetzt hat.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Optional

_LOG = logging.getLogger(__name__)

# Neutralwerte fuer Timing- und Velocity-Groove-Parameter (kein Effekt).
# Diese Werte ersetzen die Frontend-Parameter, wenn groove_processor nur als
# Mixer (Mute / Lautstaerke / Instrument) dienen soll.
_NEUTRALE_GROOVE_PARAMS: Dict[str, Any] = {
    "swing_pct":     50.0,
    "nudge_ms":       0.0,
    "vel_min":          1,
    "vel_max":        127,
    "vel_jitter":       0,
    "time_jitter":    0.0,
    "humanize_seed": None,
    "curve":        "flat",
}


def build_mixer_only_params(
    track_params: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """
    Gibt eine Kopie von track_params zurueck, bei der alle Timing- und
    Velocity-Groove-Parameter neutralisiert sind.

    Aktiv bleiben: mute, volume_db, instrument (Mixer-Funktionen).
    Neutralisiert: swing_pct, nudge_ms, vel_min/max, vel_jitter, time_jitter,
                   humanize_seed, curve.

    Wird in /rerender verwendet, damit groove_processor nur Mixer-Aktionen
    ausfuehrt und CompositionGroover separat Timing/Velocity-Groove anwendet.
    """
    ergebnis: Dict[str, Dict[str, Any]] = {}
    for key, params in track_params.items():
        p = copy.copy(params)
        p.update(_NEUTRALE_GROOVE_PARAMS)
        ergebnis[key] = p
    return ergebnis


def build_song_groove_settings(
    track_params: Dict[str, Dict[str, Any]],
    genre: Optional[str] = None,
) -> Any:
    """
    Wandelt Web-Frontend-Track-Parameter in ein MA V7 SongGrooveSettings-Objekt um.

    Parameter-Mapping (Frontend → TrackGrooveSettings):
        swing_pct     → swing_pct
        nudge_ms      → timing_nudge_ms
        vel_min       → vel_min
        vel_max       → vel_max
        vel_jitter    → vel_humanize
        time_jitter   → timing_humanize_ms
        humanize_seed → seed
        transpose_st  → transpose_st
        curve         → vel_curve

    Gibt None zurueck, wenn MA V7 nicht importiert werden kann.
    """
    try:
        from src.midi.groove_settings import SongGrooveSettings, TrackGrooveSettings
    except ImportError:
        _LOG.warning("MA V7 groove_settings nicht importierbar — CompositionGroover deaktiviert.")
        return None

    track_dict: Dict[str, Any] = {}
    for web_key, params in track_params.items():
        # Stummgeschaltete Spuren ueberspringen — kein Groove noetig.
        if params.get("mute"):
            continue
        ts = TrackGrooveSettings(
            swing_pct          = float(params.get("swing_pct",          50.0)),
            timing_nudge_ms    = float(params.get("nudge_ms",            0.0)),
            vel_min            = int(  params.get("vel_min",               1)),
            vel_max            = int(  params.get("vel_max",             127)),
            vel_humanize       = int(  params.get("vel_jitter",            0)),
            timing_humanize_ms = float(params.get("time_jitter",         0.0)),
            seed               =       params.get("humanize_seed"),
            transpose_st       = int(  params.get("transpose_st",          0)),
            vel_curve          = str(  params.get("curve",            "flat")),
        )
        track_dict[web_key] = ts

    return SongGrooveSettings(tracks=track_dict, genre=genre)


def apply_composition_groover(
    composition: Dict[str, Any],
    song_groove_settings: Any,
) -> Optional[Dict[str, Any]]:
    """
    Ruft CompositionGroover.apply() mit den gegebenen Einstellungen auf.

    Gibt die bearbeitete Kompositionskopie zurueck.
    Gibt None zurueck, wenn der Import oder die Ausfuehrung fehlschlaegt —
    der Aufrufer muss auf None pruefen und ggf. auf groove_processor zurueckfallen.
    """
    try:
        from src.rendering.composition_groover import CompositionGroover
        return CompositionGroover.apply(composition, song_groove_settings)
    except Exception as exc:
        _LOG.warning("CompositionGroover.apply fehlgeschlagen: %s", exc)
        return None
