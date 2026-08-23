"""
gm_desc_data.py — GM-Instrumentenbeschreibungen fuer den Web-Generator.

Kapselt den Zugriff auf gm_descriptions.py aus dem MUSIC_ARCHITECT_V7-Projekt
(read-only) und stellt einfache Abruffunktionen bereit.
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

import pathlib
import sys
from typing import Dict, Optional

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


# Gecachte Referenzen nach erstem Import.
_GM_DESCRIPTIONS: Optional[Dict[int, str]] = None
_get_description_fn = None
_get_drum_description_fn = None


def _load() -> None:
    """Laedt gm_descriptions einmalig (lazy, idempotent)."""
    global _GM_DESCRIPTIONS, _get_description_fn, _get_drum_description_fn
    if _get_description_fn is not None:
        return
    try:
        _ensure_ma_path()
        from composition.gm_descriptions import (  # type: ignore
            GM_DESCRIPTIONS,
            get_description,
            get_drum_description,
        )
        _GM_DESCRIPTIONS = GM_DESCRIPTIONS
        _get_description_fn      = get_description
        _get_drum_description_fn = get_drum_description
    except ImportError:
        # Graceful Fallback: leere Beschreibungen.
        _get_description_fn      = lambda gm: ""
        _get_drum_description_fn = lambda kit: ""


def get_description(gm_program: int) -> str:
    """
    Gibt die Klangbeschreibung fuer ein GM-Programm (0-127) zurueck.
    Beispiel: get_description(38) -> 'Synth bass 1 - smooth subby...'
    """
    _load()
    try:
        return _get_description_fn(gm_program) or ""
    except Exception:
        return ""


def get_drum_description(kit_bank: int) -> str:
    """
    Gibt die Klangbeschreibung fuer ein Drum-Kit (MIDI-Bank-Nummer) zurueck.
    Beispiel: get_drum_description(0) -> 'Standard kit - tight kick...'
    """
    _load()
    try:
        return _get_drum_description_fn(kit_bank) or ""
    except Exception:
        return ""


def descriptions_for_track(
    track_key: str,
    options: list,
) -> Dict[int, str]:
    """
    Gibt ein Dict {gm_nr: beschreibung} fuer alle Optionen einer Spur zurueck.
    Nuetzlich, um Dropdown-Beschreibungen vorab zu laden.

    Parameter
    ---------
    track_key : Spur-Schluessel (z. B. 'drums', 'bass', ...)
    options   : Liste von (gm_nr, name)-Tupeln
    """
    _load()
    result: Dict[int, str] = {}
    is_drums = (track_key == "drums")
    for gm_nr, _ in options:
        if is_drums:
            result[gm_nr] = get_drum_description(gm_nr)
        else:
            result[gm_nr] = get_description(gm_nr)
    return result
