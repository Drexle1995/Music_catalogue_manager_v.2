"""
Scanner -- koppelt read-only an die Ausgabeordner der beiden Sound-Programme.

1) Katalog-Scan: durchsucht den Music-Architect-Ordner nach .mid-Dateien,
   liest das Wasserzeichen und legt/aktualisiert Track-Datensaetze an.
2) Export-Scan: durchsucht den DAW-Exportordner nach Audiodateien und ordnet
   sie ueber den Dateinamen-Stamm den Tracks + Preis-Stufen zu.

Der Scan ist idempotent: mehrfaches Ausfuehren erzeugt keine Duplikate.
"""

import os
import re
from datetime import datetime

import config
import database as db
from watermark_reader import read_watermark


# --- Hilfsfunktionen --------------------------------------------------------

def _normalize_stem(filename):
    """
    Reduziert einen Dateinamen auf seinen 'Kern' (ohne Endung und ohne die
    bekannten Export-Suffixe), damit z.B. 'track_001_streaming.wav' und
    'track_001.mid' demselben Track zugeordnet werden.
    """
    stem = os.path.splitext(os.path.basename(filename))[0].lower()
    for suffix in config.EXPORT_SUFFIX_MAP:
        stem = re.sub(rf"[_\-\s]{suffix}$", "", stem)
    return stem.strip("_- ")


def _detect_tier(filename):
    """Leitet aus dem Dateinamen die Export-/Preis-Stufe ab (oder None)."""
    lower = os.path.basename(filename).lower()
    for suffix, tier in config.EXPORT_SUFFIX_MAP.items():
        if suffix in lower:
            return tier
    return None


def _extract_fitness(filename):
    """Optional: liest einen Fitness-Score aus dem Dateinamen, falls kodiert."""
    match = re.search(r"(?:fit|score)[_\-]?(\d{1,3}(?:\.\d+)?)", filename.lower())
    return float(match.group(1)) if match else None


# --- Katalog-Scan (Music Architect .mid) ------------------------------------

def scan_catalog(catalog_dir=None):
    catalog_dir = catalog_dir or db.get_setting("catalog_dir", config.DEFAULT_CATALOG_DIR)
    stats = {"scanned": 0, "added": 0, "updated": 0, "dir": catalog_dir}

    if not catalog_dir or not os.path.isdir(catalog_dir):
        stats["error"] = f"Katalog-Ordner nicht gefunden: {catalog_dir}"
        db.log_event("SCAN_CATALOG", "catalog", None, stats)
        return stats

    conn = db.get_conn()
    for root, _dirs, files in os.walk(catalog_dir):
        for name in files:
            if not name.lower().endswith(".mid"):
                continue
            path = os.path.join(root, name)
            stats["scanned"] += 1

            wm = read_watermark(path)
            # Genre = Name des Unterordners relativ zum Katalog-Stamm.
            rel = os.path.relpath(root, catalog_dir)
            genre = rel.split(os.sep)[0] if rel != "." else "unbekannt"
            title = os.path.splitext(name)[0]
            fitness = _extract_fitness(name)

            existing = conn.execute(
                "SELECT id FROM tracks WHERE source_midi = ?", (path,)
            ).fetchone()

            if existing:
                conn.execute(
                    "UPDATE tracks SET title=?, genre=?, watermark_tag=?, "
                    "watermark_hash=?, fitness_score=? WHERE id=?",
                    (title, genre, wm["tag"], wm["hash"], fitness, existing["id"]),
                )
                stats["updated"] += 1
            else:
                conn.execute(
                    "INSERT INTO tracks (title, genre, source_midi, watermark_tag, "
                    "watermark_hash, fitness_score, status, created_at) "
                    "VALUES (?, ?, ?, ?, ?, ?, 'available', ?)",
                    (title, genre, path, wm["tag"], wm["hash"], fitness,
                     datetime.now().isoformat(timespec="seconds")),
                )
                stats["added"] += 1

    conn.commit()
    conn.close()
    db.log_event("SCAN_CATALOG", "catalog", None, stats)
    return stats


# --- Export-Scan (DAW-Audiodateien) -----------------------------------------

def scan_exports(export_dir=None):
    export_dir = export_dir or db.get_setting("export_dir", config.DEFAULT_EXPORT_DIR)
    stats = {"scanned": 0, "linked": 0, "unmatched": 0, "dir": export_dir}

    if not export_dir or not os.path.isdir(export_dir):
        stats["error"] = f"Export-Ordner nicht gefunden: {export_dir}"
        db.log_event("SCAN_EXPORTS", "catalog", None, stats)
        return stats

    conn = db.get_conn()
    # Track-Index: normalisierter Stamm -> track_id
    index = {}
    for row in conn.execute("SELECT id, source_midi FROM tracks").fetchall():
        index[_normalize_stem(row["source_midi"])] = row["id"]

    for root, _dirs, files in os.walk(export_dir):
        for name in files:
            if not name.lower().endswith(config.AUDIO_EXTENSIONS):
                continue
            path = os.path.join(root, name)
            stats["scanned"] += 1

            stem = _normalize_stem(name)
            track_id = index.get(stem)
            if not track_id:
                stats["unmatched"] += 1
                continue

            tier = _detect_tier(name) or "lease_wav"
            fmt = os.path.splitext(name)[1].lstrip(".").lower()
            # Idempotent: pro Dateipfad nur ein Eintrag.
            exists = conn.execute(
                "SELECT id FROM exports WHERE file_path = ?", (path,)
            ).fetchone()
            if exists:
                continue
            conn.execute(
                "INSERT INTO exports (track_id, tier, file_path, file_format, found_at) "
                "VALUES (?, ?, ?, ?, ?)",
                (track_id, tier, path, fmt,
                 datetime.now().isoformat(timespec="seconds")),
            )
            stats["linked"] += 1

    conn.commit()
    conn.close()
    db.log_event("SCAN_EXPORTS", "catalog", None, stats)
    return stats


def scan_all():
    cat = scan_catalog()
    exp = scan_exports()
    return {"catalog": cat, "exports": exp}
