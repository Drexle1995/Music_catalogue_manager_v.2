"""
fusion_data.py — Fusion-Preset-Daten fuer den Web-Generator.

Liest die FUSION_PRESETS aus dem MUSIC_ARCHITECT_V7-Projekt (read-only)
und stellt sie fuer die Template-Dropdowns und den generate-Blueprint bereit.
Plattformunabhaengig (kein Tkinter, keine OS-spezifischen APIs).
"""

from __future__ import annotations

import pathlib
import sys
from dataclasses import dataclass
from typing import Dict, List, Tuple, Optional

# ---------------------------------------------------------------------------
# MUSIC_ARCHITECT_V7-Pfad — relativ zu dieser Datei berechnet.
# ---------------------------------------------------------------------------
_MA_ROOT = pathlib.Path(__file__).parent.parent.parent / "MUSIC_ARCHITECT_V7"
_MA_SRC  = _MA_ROOT / "src"


def _ensure_ma_path() -> None:
    """Fuegt MA-Pfade zu sys.path hinzu (idempotent)."""
    for p in (str(_MA_ROOT), str(_MA_SRC)):
        if p not in sys.path:
            sys.path.insert(0, p)


@dataclass
class FusionPreset:
    """Repraesentiert ein einzelnes benanntes Fusion-Preset."""
    key:         str
    label:       str         # Anzeigename fuer die UI
    genres:      List[str]
    weights:     List[float]
    description: str
    bpm_range:   Tuple[int, int]


# Alle unterstuetzten Basis-Genres fuer den Custom-Mix-Modus.
AVAILABLE_GENRES: List[str] = [
    "trap", "phonk", "hiphop", "techno", "house",
    "edm", "pop", "cinematic", "classical", "jpop",
]

# Interne Beschriftung fuer das UI (Schluessel = Preset-ID aus FUSION_PRESETS).
_LABEL_MAP: Dict[str, str] = {
    "cyber_ninja":      "Cyber Ninja",
    "paladin":          "Paladin",
    "anime_boss":       "Anime Boss",
    "lofi_samurai":     "Lo-Fi Samurai",
    "dark_mage":        "Dark Mage",
    "street_fighter":   "Street Fighter",
    "space_pirate":     "Space Pirate",
    "shadow_assassin":  "Shadow Assassin",
    "healing_bard":     "Healing Bard",
    "mech_pilot":       "Mech Pilot",
    "drift_king":       "Drift King",
    "final_boss":       "Final Boss",
}


def load_presets() -> List[FusionPreset]:
    """
    Laedt FUSION_PRESETS aus dem MA-V7-Projekt und gibt eine sortierte
    Liste von FusionPreset-Objekten zurueck.
    Gibt eine leere Liste zurueck, wenn das Modul nicht verfuegbar ist.
    """
    try:
        _ensure_ma_path()
        from src.arrangement.fusion_presets import FUSION_PRESETS  # type: ignore
    except (ImportError, ModuleNotFoundError):
        return []

    result: List[FusionPreset] = []
    for key, data in FUSION_PRESETS.items():
        result.append(FusionPreset(
            key         = key,
            label       = _LABEL_MAP.get(key, key.replace("_", " ").title()),
            genres      = list(data["genres"]),
            weights     = list(data["weights"]),
            description = data.get("description", ""),
            bpm_range   = tuple(data.get("bpm_range", (80, 160))),
        ))
    # Alphabetisch nach Label sortiert fuer konsistente Darstellung.
    result.sort(key=lambda p: p.label)
    return result


def build_fusion_config(
    mode:        str,           # 'off' | 'preset' | 'custom'
    preset_key:  Optional[str] = None,
    genre1:      Optional[str] = None,
    genre2:      Optional[str] = None,
    ratio:       float          = 0.5,
) -> Optional[object]:
    """
    Erstellt ein FusionConfig-Objekt fuer den CompositionEngine-Aufruf.

    mode='off'    -> None (kein Fusion)
    mode='preset' -> FusionConfig.from_preset(preset_key)
    mode='custom' -> FusionConfig.custom(genre1, genre2, ratio)

    Gibt None zurueck, wenn der Modus 'off' ist oder ein Fehler auftritt.
    """
    if mode == "off" or not mode:
        return None

    try:
        _ensure_ma_path()
        from src.arrangement.fusion_config import FusionConfig  # type: ignore

        if mode == "preset" and preset_key:
            return FusionConfig.from_preset(preset_key)

        if mode == "custom" and genre1 and genre2:
            r = max(0.0, min(1.0, float(ratio)))
            return FusionConfig.custom(genre1, genre2, r)

    except Exception:
        pass

    return None
