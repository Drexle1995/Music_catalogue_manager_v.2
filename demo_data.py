"""
Erzeugt Demo-Daten, damit das Tool ohne die echten Programme lauffaehig ist.

Wichtig: Die MIDI-Dateien werden mit ECHTEN Layer-1-Wasserzeichen geschrieben
(copyright- + text-MetaMessage inkl. SHA-256-Hash) -- also genau in dem Format,
das Music Architect V7 verwendet. So liest der Watermark-Reader echte Daten und
die Demo ist keine Attrappe, sondern ein vollstaendiger End-to-End-Durchlauf.

Zusaetzlich werden leere Platzhalter-Audiodateien im DAW-Namensschema angelegt
(z.B. track_001_streaming.wav), damit auch der Export-Scan etwas zu tun hat.
"""

import hashlib
import os

import config

try:
    import mido
except ImportError:
    mido = None

# (Titel, Genre)
_DEMO_TRACKS = [
    ("track_001", "pop"),
    ("track_002", "trap"),
    ("track_003", "house"),
    ("track_004", "cinematic"),
    ("track_005", "hiphop"),
    ("track_006", "edm"),
]

_COPYRIGHT = "(C) 2026 MUSIC_ARCHITECT_V7 - AUTHORIZED_COMMERCIAL_SYNC_ASSET_CLASS_A"

# Welche Export-Dateien pro Track erzeugt werden (Suffix -> Endung).
_DEMO_EXPORTS = {
    "preview": "mp3",
    "streaming": "wav",
    "lease": "mp3",
    "trackout": "wav",
}


def _write_watermarked_midi(path, filename):
    """Schreibt eine minimale .mid mit Layer-1-Wasserzeichen."""
    file_hash = hashlib.sha256(filename.encode("utf-8")).hexdigest()

    midi = mido.MidiFile()
    # Versteckter Meta-Track mit dem Wasserzeichen.
    meta = mido.MidiTrack()
    meta.append(mido.MetaMessage("copyright", text=_COPYRIGHT, time=0))
    meta.append(mido.MetaMessage("text", text=f"WM_HASH:{file_hash}", time=0))
    midi.tracks.append(meta)

    # Ein kurzer Noten-Track, damit die Datei musikalisch nicht leer ist.
    notes = mido.MidiTrack()
    for pitch in (60, 64, 67, 72):
        notes.append(mido.Message("note_on", note=pitch, velocity=80, time=0))
        notes.append(mido.Message("note_off", note=pitch, velocity=0, time=240))
    midi.tracks.append(notes)

    midi.save(path)


def generate(catalog_dir=None, export_dir=None):
    """Legt Demo-Katalog und Demo-Exporte an. Gibt eine kleine Statistik zurueck."""
    if mido is None:
        return {"error": "mido ist nicht installiert -- Demo nicht moeglich."}

    catalog_dir = catalog_dir or config.DEFAULT_CATALOG_DIR
    export_dir = export_dir or config.DEFAULT_EXPORT_DIR
    os.makedirs(catalog_dir, exist_ok=True)
    os.makedirs(export_dir, exist_ok=True)

    midi_count = 0
    export_count = 0

    for title, genre in _DEMO_TRACKS:
        genre_dir = os.path.join(catalog_dir, genre)
        os.makedirs(genre_dir, exist_ok=True)
        filename = f"{title}.mid"
        midi_path = os.path.join(genre_dir, filename)
        _write_watermarked_midi(midi_path, filename)
        midi_count += 1

        # Passende DAW-Exportdateien (leere Platzhalter) erzeugen.
        for suffix, ext in _DEMO_EXPORTS.items():
            exp_name = f"{title}_{suffix}.{ext}"
            with open(os.path.join(export_dir, exp_name), "wb") as fh:
                fh.write(b"")  # Platzhalter -- der Scanner braucht nur den Namen.
            export_count += 1

    return {
        "midi_created": midi_count,
        "exports_created": export_count,
        "catalog_dir": catalog_dir,
        "export_dir": export_dir,
    }
