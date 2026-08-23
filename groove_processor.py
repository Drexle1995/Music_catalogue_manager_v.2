"""
groove_processor.py — Groove- und Mixer-Transformationen fuer Kompositionsdaten.

Wendet Lautstaerke-, Swing-, Nudge-, Velocity- und Humanize-Anpassungen
direkt auf Note-Tupel (time_beats, dur_beats, pitch, vel) an.
Benoetigt keinen MA V7-Motor — laeuft plattformunabhaengig in reinem Python.
"""
from __future__ import annotations

import copy
import math
import random
from typing import Any, Dict, List, Optional, Sequence, Tuple

# Jede Note: (time_beats, dur_beats, pitch, vel)
_Note = Tuple[float, float, int, int]

# Abbildung Frontend-Schluessel → Praefix des Kompositions-Track-Namens.
# Komposition verwendet "01_Kick", "02_Percussion" usw.;
# das Frontend sendet "drums", "percussion" usw.
_TRACK_KEY_MAP: Dict[str, str] = {
    "drums":      "01_",
    "percussion": "02_",
    "bass":       "03_",
    "lead":       "04_",
    "chords":     "05_",
    "pad":        "06_",
    "arp":        "07_",
    "stabs":      "08_",
    "texture":    "09_",
    "fx":         "10_",
}


def _to_list(notes: Sequence) -> List[_Note]:
    """Normalisiert Notes (Liste von Listen oder Tupeln) in Tupel-Liste."""
    return [(float(n[0]), float(n[1]), int(n[2]), int(n[3])) for n in notes]


def resolve_track_key(frontend_key: str, comp_tracks: Dict[str, Any]) -> Optional[str]:
    """
    Findet den tatsaechlichen Kompositions-Schluessel fuer einen Frontend-Schluessel.
    Direkter Treffer hat Vorrang, danach Praefix-Suche via _TRACK_KEY_MAP.
    """
    if frontend_key in comp_tracks:
        return frontend_key
    prefix = _TRACK_KEY_MAP.get(frontend_key)
    if prefix:
        for k in comp_tracks:
            if k.startswith(prefix):
                return k
    return None


# ---------------------------------------------------------------------------
# Einzelne Transformationen
# ---------------------------------------------------------------------------

def apply_nudge(notes: List[_Note], nudge_beats: float) -> List[_Note]:
    """Verschiebt alle Noten um nudge_beats (kann negativ sein, Floor bei 0)."""
    return [(max(0.0, t + nudge_beats), d, p, v) for t, d, p, v in notes]


def apply_swing(notes: List[_Note], swing_pct: float, grid: float = 0.5) -> List[_Note]:
    """
    Wendet Swing auf Off-Beat-Noten an.
    swing_pct: 25..75, 50 = kein Swing, >50 = Late-Swing.
    """
    if abs(swing_pct - 50.0) < 0.5:
        return notes
    ratio = swing_pct / 100.0
    result: List[_Note] = []
    for t, d, p, v in notes:
        # Position innerhalb eines 2*grid-Fensters bestimmen
        two_grid = 2.0 * grid
        base     = (t // two_grid) * two_grid
        frac     = (t - base) / grid          # 0.0 = on-beat, 1.0 = off-beat
        if 0.8 < frac < 1.2:                  # Off-Beat-Note
            new_t = base + two_grid * ratio
            result.append((new_t, d, p, v))
        else:
            result.append((t, d, p, v))
    return result


def apply_velocity_range(notes: List[_Note], vel_min: int, vel_max: int) -> List[_Note]:
    """Skaliert Velocity linear auf den Bereich [vel_min, vel_max]."""
    if not notes:
        return notes
    orig_min = min(v for _, _, _, v in notes)
    orig_max = max(v for _, _, _, v in notes)
    span     = orig_max - orig_min or 1
    target   = vel_max - vel_min
    return [
        (t, d, p, max(1, min(127, vel_min + int((v - orig_min) / span * target))))
        for t, d, p, v in notes
    ]


def apply_volume_db(notes: List[_Note], volume_db: float) -> List[_Note]:
    """Skaliert Velocity proportional zum dB-Wert."""
    if abs(volume_db) < 0.01:
        return notes
    factor = 10.0 ** (volume_db / 20.0)
    return [
        (t, d, p, max(1, min(127, int(v * factor))))
        for t, d, p, v in notes
    ]


def apply_vel_jitter(notes: List[_Note], jitter: int, rng: random.Random) -> List[_Note]:
    """Streut Velocity-Werte zufaellig um ±jitter."""
    if jitter <= 0:
        return notes
    return [
        (t, d, p, max(1, min(127, v + rng.randint(-jitter, jitter))))
        for t, d, p, v in notes
    ]


def apply_time_jitter(notes: List[_Note], jitter_ms: float, bpm: float,
                      rng: random.Random) -> List[_Note]:
    """Streut Timing zufaellig um ±jitter_ms (in ms)."""
    if jitter_ms <= 0.0 or bpm <= 0.0:
        return notes
    jitter_beats = (jitter_ms / 1000.0) * (bpm / 60.0)
    return [
        (max(0.0, t + rng.uniform(-jitter_beats, jitter_beats)), d, p, v)
        for t, d, p, v in notes
    ]


# ---------------------------------------------------------------------------
# Haupt-API
# ---------------------------------------------------------------------------

def apply_groove_to_composition(
    composition: Dict[str, Any],
    track_params: Dict[str, Dict[str, Any]],
    bpm: float,
) -> Dict[str, Any]:
    """
    Wendet Groove-Parameter auf alle Spuren einer Komposition an und gibt
    eine veraenderte Kopie zurueck.

    track_params-Struktur pro Spur:
    {
      "volume_db":   float,   # dB-Gain (+6 / -12 usw.), Standard 0.0
      "mute":        bool,    # True = Spur stummschalten
      "instrument":  int|None,# GM-Programm, None = unveraendert
      "swing_pct":   float,   # 25..75, Standard 50
      "nudge_ms":    float,   # ms, Standard 0.0
      "vel_min":     int,     # 1..127
      "vel_max":     int,     # 1..127
      "vel_jitter":  int,     # 0..30
      "time_jitter": float,   # ms 0..50
      "humanize_seed":int|None,
    }
    """
    result = copy.deepcopy(composition)
    beats_per_second = (bpm or 120.0) / 60.0
    comp_tracks = composition.get("tracks", {})

    for track_name, notes_raw in comp_tracks.items():
        # Direkter Treffer; falls nicht gefunden, umgekehrte Praefix-Suche.
        params = track_params.get(track_name)
        if params is None:
            for fkey, prefix in _TRACK_KEY_MAP.items():
                if track_name.startswith(prefix):
                    params = track_params.get(fkey)
                    break
        if params is None:
            params = {}

        # Stummschalten
        if params.get("mute"):
            result["tracks"][track_name] = []
            continue

        notes = _to_list(notes_raw)

        # Nudge
        nudge_ms = float(params.get("nudge_ms", 0.0))
        if nudge_ms:
            notes = apply_nudge(notes, nudge_ms / 1000.0 * beats_per_second)

        # Swing
        swing = float(params.get("swing_pct", 50.0))
        notes = apply_swing(notes, swing)

        # Velocity-Bereich
        vel_min = int(params.get("vel_min", 1))
        vel_max = int(params.get("vel_max", 127))
        if vel_min != 1 or vel_max != 127:
            notes = apply_velocity_range(notes, vel_min, vel_max)

        # Volume (dB)
        vol_db = float(params.get("volume_db", 0.0))
        if abs(vol_db) > 0.01:
            notes = apply_volume_db(notes, vol_db)

        # Humanize
        vel_jitter  = int(params.get("vel_jitter", 0))
        time_jitter = float(params.get("time_jitter", 0.0))
        if vel_jitter > 0 or time_jitter > 0.0:
            seed = params.get("humanize_seed")
            rng  = random.Random(seed)
            notes = apply_vel_jitter(notes, vel_jitter, rng)
            notes = apply_time_jitter(notes, time_jitter, bpm, rng)

        result["tracks"][track_name] = notes

        # Instrument-Aenderung in track_info uebernehmen
        instr = params.get("instrument")
        if instr is not None:
            for tk in list(result.get("track_info", {}).keys()):
                if tk == track_name:
                    result["track_info"][tk]["program"] = int(instr)

    return result


def build_solo_composition(composition: Dict[str, Any], solo_track: str) -> Dict[str, Any]:
    """
    Erstellt eine Kompositionskopie mit nur einer aktiven Spur (fuer Solo-Rendering).
    solo_track kann der Frontend-Schluessel ('drums') oder der Kompositions-
    Schluessel ('01_Kick') sein — resolve_track_key erledigt die Zuordnung.
    """
    result = copy.deepcopy(composition)
    comp_tracks = result.get("tracks", {})
    resolved = resolve_track_key(solo_track, comp_tracks)
    for track_name in list(comp_tracks.keys()):
        if track_name != resolved and track_name != solo_track:
            result["tracks"][track_name] = []
    return result


def jsonify_composition(comp: Dict[str, Any]) -> Dict[str, Any]:
    """Konvertiert Note-Tupel in JSON-serialisierbare Listen (fuer Session-Speicherung)."""
    result: Dict[str, Any] = {}
    for k, v in comp.items():
        if k == "tracks":
            result[k] = {
                tn: [[float(n[0]), float(n[1]), int(n[2]), int(n[3])] for n in notes]
                for tn, notes in v.items()
            }
        else:
            result[k] = v
    return result
