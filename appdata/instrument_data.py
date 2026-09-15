"""
instrument_data.py — Kuratierte GM-Instrumentenliste fuer den Web-Generator.

Liest bdra_instruments.json aus dem MUSIC_ARCHITECT_V7-Projekt (read-only)
und stellt pro Spur eine sortierte Liste von (gm_programm, name)-Tupeln bereit.
Spuren, die nicht in der JSON-Datei enthalten sind (Drums, Perkussion, Textur,
FX), werden mit hartkodierten GM-Standardwerten befuellt.
Plattformunabhaengig: kein Tkinter, keine OS-spezifischen APIs.
"""

from __future__ import annotations

import json
import pathlib
from typing import List, Tuple

# Pfad zur JSON-Datei — relativ zu dieser Datei berechnet (plattformunabhaengig).
_JSON_PATH = (
    pathlib.Path(__file__).parent.parent.parent
    / "MUSIC_ARCHITECT_V7"
    / "data"
    / "production_guide"
    / "json"
    / "bdra_instruments.json"
)

# Abbildung bdra_instruments-Schluessel → CompositionConfig-Spurschluessel.
_KEY_MAP = {
    "bass":   "bass",
    "chords": "chords",
    "melody": "lead",    # im Desktop "melody", in der Config "lead"
    "arp":    "arp",
    "pads":   "pad",     # im Desktop "pads",   in der Config "pad"
    "stabs":  "stabs",
}

# ---------------------------------------------------------------------------
# Drum-Kits: GM-Bank-Nummern (MIDI-Kanal 10, Program-Nr = Bank-Wahl).
# ---------------------------------------------------------------------------
_DRUM_KITS: List[Tuple[int, str]] = [
    (0,  "Standard Kit"),
    (8,  "Room Kit"),
    (16, "Power Kit"),
    (24, "Electronic Kit"),
    (25, "TR-808 Kit"),
    (32, "Jazz Kit"),
    (40, "Brush Kit"),
    (48, "Orchestra Kit"),
    (56, "SFX Kit"),
]

# ---------------------------------------------------------------------------
# Perkussion: GM-Programme fuer rhythmische Melodie-Perkussion
# (auf normalen MIDI-Kanaelen, nicht Kanal 10).
# ---------------------------------------------------------------------------
_PERCUSSION_INSTRUMENTS: List[Tuple[int, str]] = [
    (9,  "Glockenspiel"),
    (11, "Vibraphone"),
    (12, "Marimba"),
    (13, "Xylophone"),
    (14, "Tubular Bells"),
    (47, "Timpani"),
    (112,"Tinkle Bell"),
    (113,"Agogo"),
    (114,"Steel Drums"),
    (115,"Woodblock"),
    (116,"Taiko Drum"),
    (117,"Melodic Tom"),
    (118,"Synth Drum"),
    (119,"Reverse Cymbal"),
]

# ---------------------------------------------------------------------------
# Textur-Pads: Atmosphaerische GM-Pads und Streicher.
# ---------------------------------------------------------------------------
_TEXTURE_INSTRUMENTS: List[Tuple[int, str]] = [
    (88, "New Age Pad"),
    (89, "Warm Pad"),
    (90, "Polysynth Pad"),
    (91, "Choir Pad"),
    (92, "Bowed Pad"),
    (93, "Metallic Pad"),
    (94, "Halo Pad"),
    (95, "Sweep Pad"),
    (51, "Synth Strings 2"),
    (54, "Synth Voice"),
    (97, "Crystal FX"),
    (98, "Atmosphere FX"),
    (99, "Brightness FX"),
]

# ---------------------------------------------------------------------------
# FX-Spuren: Spezial-Effekt-Programme aus GM-Bank.
# ---------------------------------------------------------------------------
_FX_INSTRUMENTS: List[Tuple[int, str]] = [
    (96,  "Rain FX"),
    (97,  "Crystal FX"),
    (98,  "Atmosphere FX"),
    (99,  "Brightness FX"),
    (100, "Goblins FX"),
    (101, "Echoes FX"),
    (102, "Sci-Fi FX"),
    (103, "Sitar"),
    (120, "Guitar Fret Noise"),
    (121, "Breath Noise"),
    (122, "Seashore"),
    (123, "Bird Tweet"),
    (124, "Telephone Ring"),
    (125, "Helicopter"),
    (126, "Applause"),
    (127, "Gunshot"),
]


class InstrumentData:
    """
    Haelt die Instrumentenlisten fuer alle Spuren.

    Attribute (jeweils List[Tuple[int, str]] = [(gm_nr, name), ...]):
        bass, chords, lead, pad, arp, stabs, drums, percussion, texture, fx
    """

    def __init__(
        self,
        bass:        List[Tuple[int, str]],
        chords:      List[Tuple[int, str]],
        lead:        List[Tuple[int, str]],
        pad:         List[Tuple[int, str]],
        arp:         List[Tuple[int, str]],
        stabs:       List[Tuple[int, str]],
        drums:       List[Tuple[int, str]],
        percussion:  List[Tuple[int, str]],
        texture:     List[Tuple[int, str]],
        fx:          List[Tuple[int, str]],
    ) -> None:
        self.bass       = bass
        self.chords     = chords
        self.lead       = lead
        self.pad        = pad
        self.arp        = arp
        self.stabs      = stabs
        self.drums      = drums
        self.percussion = percussion
        self.texture    = texture
        self.fx         = fx


def load() -> InstrumentData:
    """
    Liest bdra_instruments.json und gibt ein InstrumentData-Objekt zurueck.
    Falls die Datei nicht gefunden wird, werden leere Listen fuer die
    JSON-basierten Spuren geliefert. Drums, Perkussion, Textur und FX
    benutzen immer die hartkodierten GM-Listen als Fallback.
    """
    json_lists: dict = {}

    try:
        with _JSON_PATH.open(encoding="utf-8") as fh:
            raw = json.load(fh)

        def _extract(json_key: str) -> List[Tuple[int, str]]:
            """Gibt [(gm_nr, 'Name [CODE]'), ...] fuer den JSON-Schluessel zurueck."""
            return [
                (entry["gm"], f"{entry['name']}  [{entry.get('code', '')}]")
                for entry in raw.get(json_key, [])
            ]

        json_lists = {
            "bass":   _extract("bass"),
            "chords": _extract("chords"),
            "lead":   _extract("melody"),  # JSON-Schluessel ist "melody"
            "pad":    _extract("pads"),    # JSON-Schluessel ist "pads"
            "arp":    _extract("arp"),
            "stabs":  _extract("stabs"),
        }

    except (FileNotFoundError, json.JSONDecodeError):
        # Graceful Fallback: leere Listen -> Motor waehlt automatisch.
        empty: List[Tuple[int, str]] = []
        json_lists = {k: empty for k in ("bass", "chords", "lead", "pad", "arp", "stabs")}

    return InstrumentData(
        bass       = json_lists["bass"],
        chords     = json_lists["chords"],
        lead       = json_lists["lead"],
        pad        = json_lists["pad"],
        arp        = json_lists["arp"],
        stabs      = json_lists["stabs"],
        drums      = _DRUM_KITS,
        percussion = _PERCUSSION_INSTRUMENTS,
        texture    = _TEXTURE_INSTRUMENTS,
        fx         = _FX_INSTRUMENTS,
    )
