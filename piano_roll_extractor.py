"""
piano_roll_extractor.py — Extrahiert Piano-Roll-Daten aus einem Kompositions-Dict.

Das Kompositions-Dict des Music-Architect-V7-Systems hat folgendes Format:
  {
    'config':     {'bpm': float},
    'total_bars': int,
    'tracks':     {name: [(time_beats, dur_beats, pitch, vel), ...]},
    'track_info': {name: {'channel': int, 'program': int}},
  }

Dieser Extraktor wandelt die Rohdaten in ein JSON-serialisierbares Dict um,
das im Browser auf einem HTML5-Canvas gerendert werden kann.
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

from typing import Any, Dict, List

# Mapping: MA-V7-Spurname -> UI-Anzeigename + Farbe.
# Schluessel sind die internen Spurnamen aus composition['tracks'].
_TRACK_META: Dict[str, Dict[str, str]] = {
    "01_Kick":       {"label": "Kick",      "color": "#e05050"},
    "02_Percussion": {"label": "Perkussion","color": "#e07830"},
    "03_Bass":       {"label": "Bass",      "color": "#50b0e0"},
    "04_Melody":     {"label": "Lead",      "color": "#e0c850"},
    "05_Chords":     {"label": "Akkorde",   "color": "#50e0a0"},
    "06_Pad":        {"label": "Pad",       "color": "#a050e0"},
    "07_Arp":        {"label": "Arp",       "color": "#50e0d0"},
    "08_Stabs":      {"label": "Stabs",     "color": "#e050a0"},
    "09_Texture":    {"label": "Textur",    "color": "#8080c0"},
    "10_FX":         {"label": "FX",        "color": "#c0c0c0"},
}


def extract(composition: Dict[str, Any]) -> Dict[str, Any]:
    """
    Wandelt ein Kompositions-Dict in Piano-Roll-Daten fuer den Browser um.

    Parameter
    ---------
    composition : Ausgabe von CompositionEngine.compose()

    Rueckgabewert
    -------------
    {
      'bpm':        float,
      'total_bars': int,
      'tracks': [
        {
          'name':  str,   # interner Spurname (z. B. '03_Bass')
          'label': str,   # Anzeigename
          'color': str,   # CSS-Farbe
          'notes': [
            {'t': float, 'd': float, 'p': int, 'v': int},  # time/dur/pitch/vel
            ...
          ],
        },
        ...
      ]
    }
    """
    if not composition or "tracks" not in composition:
        return {"bpm": 120.0, "total_bars": 8, "tracks": []}

    bpm        = float((composition.get("config") or {}).get("bpm", 120.0))
    total_bars = int(composition.get("total_bars", 8))
    raw_tracks = composition.get("tracks", {})

    out_tracks: List[Dict[str, Any]] = []

    # Spurnamen sortiert ausgeben (01_ vor 02_ etc.)
    for track_name in sorted(raw_tracks.keys()):
        notes_raw = raw_tracks[track_name]
        if not notes_raw:
            continue

        meta  = _TRACK_META.get(track_name, {})
        label = meta.get("label", track_name)
        color = meta.get("color", "#888888")

        # Noten in JSON-serializierbare Dicts konvertieren.
        notes: List[Dict[str, Any]] = []
        for note in notes_raw:
            if len(note) < 4:
                continue
            time_beats, dur_beats, pitch, vel = note[0], note[1], note[2], note[3]
            notes.append({
                "t": round(float(time_beats), 3),
                "d": round(float(dur_beats),  3),
                "p": int(pitch),
                "v": int(vel),
            })

        out_tracks.append({
            "name":  track_name,
            "label": label,
            "color": color,
            "notes": notes,
        })

    return {
        "bpm":        bpm,
        "total_bars": total_bars,
        "tracks":     out_tracks,
    }
