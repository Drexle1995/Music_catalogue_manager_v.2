"""
sample_data.py — Datenbankzugriff fuer die Sample-Bibliothek.

Kapselt alle CRUD-Operationen fuer die samples-Tabelle.
Kompatibilitaets-Score und Transponierempfehlung werden NICHT gespeichert
(werden zur Laufzeit pro Song-Key berechnet).
Track-Zuordnungen sind sitzungsgebunden und werden nicht persistent abgelegt.

Plattformunabhaengig — nur Python-Stdlib und pathlib. Kein ORM.
"""

from __future__ import annotations

import json
import pathlib
from datetime import datetime
from typing import Any, Dict, List, Optional

import database as db


# ---------------------------------------------------------------------------
# Interne Hilfsfunktionen
# ---------------------------------------------------------------------------

def _row_to_dict(row) -> Dict[str, Any]:
    """Konvertiert eine sqlite3.Row in ein normales Dict mit aufgeloesten Feldern."""
    d = dict(row)
    # Tags als JSON-Array-String → Python-Liste
    try:
        d["tags"] = json.loads(d.get("tags") or "[]")
    except (json.JSONDecodeError, TypeError):
        d["tags"] = []
    # analysed als Integer → bool
    d["analysed"] = bool(d.get("analysed", 0))
    return d


def _path_to_posix(path: pathlib.Path | str) -> str:
    """Normalisiert einen Dateipfad in einen POSIX-String (plattformunabhaengig)."""
    return pathlib.Path(path).as_posix()


# ---------------------------------------------------------------------------
# Schreiboperationen
# ---------------------------------------------------------------------------

def upsert_sample(
    path:                 pathlib.Path | str,
    name:                 str,
    category:             str,
    subcategory:          str,
    root_note:            Optional[int]   = None,
    root_hz:              Optional[float] = None,
    duration_sec:         float           = 0.0,
    spectral_centroid_hz: float           = 0.0,
    source_sample_rate:   int             = 44100,
    channels:             int             = 1,
    tags:                 Optional[List[str]] = None,
    bpm:                  Optional[float] = None,
    analysed:             bool            = False,
) -> int:
    """
    Fuegt ein Sample ein oder aktualisiert es bei identischem Pfad (UPSERT).

    Gibt die Datensatz-ID des eingefuegten oder aktualisierten Samples zurueck.
    Kategorie wird gegen ('tone', 'color', 'environment') geprueft.
    Root-Note wird gegen den MIDI-Bereich 0-127 geprueft.
    """
    if category not in ("tone", "color", "environment"):
        raise ValueError(
            f"Ungueltige Kategorie '{category}'. "
            "Erlaubt: 'tone', 'color', 'environment'."
        )
    if root_note is not None and not (0 <= root_note <= 127):
        raise ValueError(
            f"root_note {root_note} liegt ausserhalb des MIDI-Bereichs 0-127."
        )
    if channels not in (1, 2):
        raise ValueError(f"channels muss 1 oder 2 sein, erhalten: {channels}.")

    posix_path = _path_to_posix(path)
    tags_json  = json.dumps(tags or [], ensure_ascii=False)
    now        = datetime.now().isoformat(timespec="seconds")

    conn = db.get_conn()
    cur  = conn.execute(
        """
        INSERT INTO samples
            (path, name, category, subcategory, root_note, root_hz,
             duration_sec, spectral_centroid_hz, source_sample_rate,
             channels, tags, bpm, analysed, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(path) DO UPDATE SET
            name                 = excluded.name,
            category             = excluded.category,
            subcategory          = excluded.subcategory,
            root_note            = excluded.root_note,
            root_hz              = excluded.root_hz,
            duration_sec         = excluded.duration_sec,
            spectral_centroid_hz = excluded.spectral_centroid_hz,
            source_sample_rate   = excluded.source_sample_rate,
            channels             = excluded.channels,
            tags                 = excluded.tags,
            bpm                  = excluded.bpm,
            analysed             = excluded.analysed
        """,
        (
            posix_path, name, category, subcategory, root_note, root_hz,
            duration_sec, spectral_centroid_hz, source_sample_rate,
            channels, tags_json, bpm, int(analysed), now,
        ),
    )
    sample_id = cur.lastrowid
    conn.commit()
    conn.close()
    return sample_id


def mark_analysed(sample_id: int, analysed: bool = True) -> None:
    """Setzt das analysed-Flag eines Samples (nach abgeschlossener Audioanalyse)."""
    conn = db.get_conn()
    conn.execute(
        "UPDATE samples SET analysed = ? WHERE id = ?",
        (int(analysed), sample_id),
    )
    conn.commit()
    conn.close()


def update_audio_fields(
    sample_id:            int,
    root_note:            Optional[int],
    root_hz:              Optional[float],
    duration_sec:         float,
    spectral_centroid_hz: float,
    bpm:                  Optional[float],
) -> None:
    """
    Aktualisiert die von SampleAnalyzer berechneten Audiofelder.
    Wird nach der Analyse aufgerufen um root_note, root_hz,
    duration_sec, spectral_centroid_hz und bpm nachzutragen.
    """
    conn = db.get_conn()
    conn.execute(
        """
        UPDATE samples
           SET root_note            = ?,
               root_hz              = ?,
               duration_sec         = ?,
               spectral_centroid_hz = ?,
               bpm                  = ?,
               analysed             = 1
         WHERE id = ?
        """,
        (root_note, root_hz, duration_sec, spectral_centroid_hz, bpm, sample_id),
    )
    conn.commit()
    conn.close()


def delete_sample(sample_id: int) -> None:
    """Loescht einen Sample-Datensatz anhand seiner ID."""
    conn = db.get_conn()
    conn.execute("DELETE FROM samples WHERE id = ?", (sample_id,))
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Leseoperationen
# ---------------------------------------------------------------------------

def get_sample_by_id(sample_id: int) -> Optional[Dict[str, Any]]:
    """Gibt den Sample-Datensatz mit der angegebenen ID zurueck oder None."""
    conn = db.get_conn()
    row  = conn.execute(
        "SELECT * FROM samples WHERE id = ?", (sample_id,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def get_sample_by_path(path: pathlib.Path | str) -> Optional[Dict[str, Any]]:
    """Gibt den Sample-Datensatz fuer einen Dateipfad zurueck oder None."""
    posix_path = _path_to_posix(path)
    conn = db.get_conn()
    row  = conn.execute(
        "SELECT * FROM samples WHERE path = ?", (posix_path,)
    ).fetchone()
    conn.close()
    return _row_to_dict(row) if row else None


def list_samples(
    category:    Optional[str] = None,
    subcategory: Optional[str] = None,
    analysed:    Optional[bool] = None,
    tag:         Optional[str] = None,
    limit:       int = 500,
    offset:      int = 0,
) -> List[Dict[str, Any]]:
    """
    Gibt eine gefilterte Liste von Sample-Datensaetzen zurueck.

    category    — Filterung nach Oberkategorie (tone/color/environment)
    subcategory — Filterung nach Unterklasse
    analysed    — True = nur analysierte, False = nur unanalysierte, None = alle
    tag         — Volltext-Suche im tags-JSON-Feld (LIKE-Suche)
    limit       — maximale Anzahl Ergebnisse
    offset      — Offset fuer Seitennavigation
    """
    whereParts: List[str] = []
    params:     List[Any] = []

    if category is not None:
        whereParts.append("category = ?")
        params.append(category)
    if subcategory is not None:
        whereParts.append("subcategory = ?")
        params.append(subcategory)
    if analysed is not None:
        whereParts.append("analysed = ?")
        params.append(int(analysed))
    if tag is not None:
        # Einfache JSON-Textsuche: prueft ob der Tag-String im JSON-Array vorkommt
        whereParts.append("tags LIKE ?")
        params.append(f'%"{tag}"%')

    where_sql = ("WHERE " + " AND ".join(whereParts)) if whereParts else ""
    params += [limit, offset]

    conn = db.get_conn()
    rows = conn.execute(
        f"SELECT * FROM samples {where_sql} ORDER BY name ASC LIMIT ? OFFSET ?",
        params,
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


def count_samples(
    category: Optional[str] = None,
    analysed: Optional[bool] = None,
) -> int:
    """Zaehlt Sample-Datensaetze mit optionaler Filterung."""
    whereParts: List[str] = []
    params:     List[Any] = []

    if category is not None:
        whereParts.append("category = ?")
        params.append(category)
    if analysed is not None:
        whereParts.append("analysed = ?")
        params.append(int(analysed))

    where_sql = ("WHERE " + " AND ".join(whereParts)) if whereParts else ""
    conn = db.get_conn()
    count = conn.execute(
        f"SELECT COUNT(*) c FROM samples {where_sql}", params
    ).fetchone()["c"]
    conn.close()
    return count


def search_samples(query: str, limit: int = 100) -> List[Dict[str, Any]]:
    """
    Einfache Volltextsuche ueber name- und tags-Felder.
    Gibt Treffer absteigend nach Relevanz (name-Treffer zuerst) zurueck.
    """
    pattern = f"%{query}%"
    conn    = db.get_conn()
    rows    = conn.execute(
        """
        SELECT *, (name LIKE ? AND 1 OR 0) AS name_match
          FROM samples
         WHERE name LIKE ? OR tags LIKE ?
         ORDER BY name_match DESC, name ASC
         LIMIT ?
        """,
        (pattern, pattern, pattern, limit),
    ).fetchall()
    conn.close()
    return [_row_to_dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Import-Hilfsfunktion (aus SampleMetadata-Dict)
# ---------------------------------------------------------------------------

def import_from_metadata_dict(data: Dict[str, Any]) -> int:
    """
    Importiert ein Sample aus einem SampleMetadata.to_dict()-Ergebnis.
    Gibt die Datensatz-ID des eingefuegten oder aktualisierten Samples zurueck.
    Kompatibel mit dem Serialisierungsformat des Desktop-Clients.
    """
    return upsert_sample(
        path                 = data["path"],
        name                 = data["name"],
        category             = data["category"],
        subcategory          = data["subcategory"],
        root_note            = data.get("root_note"),
        root_hz              = data.get("root_hz"),
        duration_sec         = float(data.get("duration_sec", 0.0)),
        spectral_centroid_hz = float(data.get("spectral_centroid_hz", 0.0)),
        source_sample_rate   = int(data.get("source_sample_rate", 44100)),
        channels             = int(data.get("channels", 1)),
        tags                 = list(data.get("tags", [])),
        bpm                  = data.get("bpm"),
        analysed             = bool(data.get("analysed", False)),
    )
