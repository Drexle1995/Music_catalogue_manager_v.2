"""
mixer_data.py — Spur-Definitionen fuer den Web-Mixer.

Beschreibt alle 10 Spuren des Music-Architect-V7-Systems mit
Standardlautstaerke, Akzentfarbe und dem internen Config-Schluessel.
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List


@dataclass(frozen=True)
class TrackDef:
    """Definition einer einzelnen Mischpult-Spur."""
    key:       str    # interner Schluessel fuer CompositionConfig.tracks
    label:     str    # Anzeigename fuer die UI (Deutsch)
    color:     str    # Akzentfarbe als CSS-Hex-Wert
    default_volume: float  # 0.0 – 1.0 (Standard-Gain-Faktor)
    has_instrument: bool   # True = Instrument-Dropdown anzeigen


# Reihenfolge entspricht der internen Spur-Nummerierung des MA-V7-Systems.
# Die Schluessel stimmen mit CompositionConfig.tracks und den Kompositions-
# Ausgabe-Schluesseln (01_Kick, 02_Percussion, …) ueberein.
TRACKS: List[TrackDef] = [
    TrackDef(
        key="drums",       label="Drums",       color="#e05050",
        default_volume=0.85, has_instrument=True,
    ),
    TrackDef(
        key="percussion",  label="Perkussion",  color="#e07830",
        default_volume=0.65, has_instrument=True,
    ),
    TrackDef(
        key="bass",        label="Bass",        color="#50b0e0",
        default_volume=0.80, has_instrument=True,
    ),
    TrackDef(
        key="chords",      label="Akkorde",     color="#50e0a0",
        default_volume=0.70, has_instrument=True,
    ),
    TrackDef(
        key="lead",        label="Lead",        color="#e0c850",
        default_volume=0.75, has_instrument=True,
    ),
    TrackDef(
        key="pad",         label="Pad",         color="#a050e0",
        default_volume=0.60, has_instrument=True,
    ),
    TrackDef(
        key="arp",         label="Arp",         color="#50e0d0",
        default_volume=0.50, has_instrument=True,
    ),
    TrackDef(
        key="stabs",       label="Stabs",       color="#e050a0",
        default_volume=0.55, has_instrument=True,
    ),
    TrackDef(
        key="texture",     label="Textur",      color="#8080c0",
        default_volume=0.40, has_instrument=True,
    ),
    TrackDef(
        key="fx",          label="FX",          color="#c0c0c0",
        default_volume=0.35, has_instrument=True,
    ),
]

# Hilfsfunktion: Spur nach Schluessel suchen.
def get_track(key: str) -> TrackDef | None:
    for t in TRACKS:
        if t.key == key:
            return t
    return None
