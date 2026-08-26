"""
sample_upload.py — Flask-Blueprint fuer den Upload von Audio-Samples pro Track.

Jedes hochgeladene Sample wird im temporaeren Kompositionsverzeichnis der
aktuellen Session gespeichert. Die Zuordnungen (builder_key → Dateipfad)
liegen in der Flask-Session unter dem Schluessel 'samples_{audio_uuid}'.
Beim Re-Render werden sie an render_composition_to_wav() weitergeleitet.

Erlaubte Formate: .wav  .aif  .aiff  .flac  .ogg  .mp3
Maximale Dateigroesse: 20 MB pro Sample.

Plattformunabhaengig — nur pathlib, kein Tkinter, keine OS-APIs.
"""

from __future__ import annotations

import pathlib
from typing import Dict

from flask import Blueprint, current_app, jsonify, request, session
from flask_login import login_required

# ---------------------------------------------------------------------------
# Blueprint-Konfiguration
# ---------------------------------------------------------------------------

sample_upload_bp = Blueprint("sample_upload", __name__)

# Erlaubte Dateiendungen (Kleinbuchstaben).
_ERLAUBTE_ENDUNGEN = frozenset({".wav", ".aif", ".aiff", ".flac", ".ogg", ".mp3"})

# Maximale Dateigroesse pro Upload: 20 MiB.
_MAX_GROESSE_BYTES = 20 * 1024 * 1024

# Gueltige Web-Frontend-Schluessel (entspricht GROOVE_TRACKS im Template).
_GUELTIGE_KEYS = frozenset({
    "drums", "percussion", "bass", "lead",
    "chords", "pad", "arp", "stabs", "texture", "fx",
})

# Mapping Web-Key → MA-V7-Builder-Key fuer SampleEngine.load_from_assignments().
# 'percussion' heisst in MA-V7 'perc'; 'lead' heisst 'melody'; 'pad' heisst 'pads'.
WEB_ZU_MA_KEY: Dict[str, str] = {
    "percussion": "perc",
    "lead":       "melody",
    "pad":        "pads",
}


# ---------------------------------------------------------------------------
# Hilfsfunktionen
# ---------------------------------------------------------------------------

def _sicherer_stamm(builder_key: str) -> str:
    """Gibt einen sicheren Dateinamen-Stamm fuer einen Builder-Key zurueck."""
    return "".join(c for c in builder_key if c.isalnum() or c == "_")


def _vorhandene_entfernen(samples_verz: pathlib.Path, builder_key: str) -> None:
    """Loescht alle vorhandenen Dateien fuer einen Track-Key (alle Endungen)."""
    stamm = _sicherer_stamm(builder_key)
    for endung in _ERLAUBTE_ENDUNGEN:
        p = samples_verz / f"{stamm}{endung}"
        if p.exists():
            p.unlink(missing_ok=True)


def resolve_sample_assignments(audio_uuid: str) -> Dict[str, str]:
    """
    Liest die Sample-Zuweisungen aus der Session.

    Folgt der origin_uuid-Kette (Re-Render-UUIDs verweisen auf die Original-UUID),
    damit Samples auch nach mehrfachem Re-Render gefunden werden.

    Gibt {web_key: absoluter_pfad} zurueck — nur Pfade die tatsaechlich existieren.
    """
    # Direkt in der Session suchen.
    zuweisungen: Dict[str, str] = session.get(f"samples_{audio_uuid}") or {}

    # Falls keine direkte Zuweisung: origin_uuid-Kette verfolgen.
    if not zuweisungen:
        origin_uuid = session.get(f"origin_uuid_{audio_uuid}")
        if origin_uuid:
            zuweisungen = session.get(f"samples_{origin_uuid}") or {}

    # Nur Eintraege mit existierenden Dateien zurueckgeben.
    return {k: v for k, v in zuweisungen.items() if pathlib.Path(v).exists()}


def zu_ma_assignments(web_zuweisungen: Dict[str, str]) -> Dict[str, str]:
    """
    Wandelt Web-Frontend-Schluessel in MA-V7-Builder-Keys um.

    Benoetigt von render_composition_to_wav(sample_assignments=...) und
    SampleEngine.load_from_assignments(), die MA-V7-Keys erwarten.
    """
    return {WEB_ZU_MA_KEY.get(k, k): v for k, v in web_zuweisungen.items()}


# ---------------------------------------------------------------------------
# Route: Upload
# ---------------------------------------------------------------------------

@sample_upload_bp.route("/sample_upload", methods=["POST"])
@login_required
def upload_sample():
    """
    Laedt ein einzelnes Audio-Sample fuer einen Track hoch.

    Formular-Felder (multipart/form-data):
        audio_uuid   — UUID der aktuellen Kompositions-Session
        builder_key  — Track-Bezeichnung (drums | bass | lead | ...)
        audio        — Audiodatei

    Antwort (JSON):
        { ok: true, filename: str, size_bytes: int, builder_key: str }
        { ok: false, error: str }  bei Fehler
    """
    audio_uuid  = (request.form.get("audio_uuid")  or "").strip()
    builder_key = (request.form.get("builder_key") or "").strip().lower()
    audio_datei = request.files.get("audio")

    # --- Eingaben validieren -------------------------------------------------
    if not audio_uuid:
        return jsonify({"ok": False, "error": "audio_uuid fehlt"}), 400
    if builder_key not in _GUELTIGE_KEYS:
        return jsonify({"ok": False, "error": f"Ungueltiger Track-Key: '{builder_key}'"}), 400
    if audio_datei is None:
        return jsonify({"ok": False, "error": "Keine Datei empfangen"}), 400

    endung = pathlib.Path(audio_datei.filename or "").suffix.lower()
    if endung not in _ERLAUBTE_ENDUNGEN:
        return jsonify({
            "ok":    False,
            "error": (f"Format '{endung}' nicht unterstuetzt. "
                      f"Erlaubt: {', '.join(sorted(_ERLAUBTE_ENDUNGEN))}"),
        }), 415

    # --- Kompositionsverzeichnis aus Session lesen ---------------------------
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"ok": False, "error": "Kompositions-Session nicht gefunden"}), 404

    tmp_verz = pathlib.Path(tmp_dir_str)
    if not tmp_verz.exists():
        return jsonify({"ok": False, "error": "Kompositions-Verzeichnis fehlt"}), 404

    # --- Sample-Unterverzeichnis anlegen (idempotent) -----------------------
    samples_verz = tmp_verz / "samples"
    samples_verz.mkdir(exist_ok=True)

    # Vorherige Datei fuer diesen Key entfernen (max. ein Sample pro Track).
    _vorhandene_entfernen(samples_verz, builder_key)

    # --- Datei in Chunks schreiben und Groesse pruefen ----------------------
    ziel_pfad = samples_verz / f"{_sicherer_stamm(builder_key)}{endung}"
    groesse   = 0

    try:
        with open(ziel_pfad, "wb") as fh:
            while True:
                chunk = audio_datei.stream.read(65_536)  # 64-KiB-Chunks
                if not chunk:
                    break
                groesse += len(chunk)
                if groesse > _MAX_GROESSE_BYTES:
                    fh.close()
                    ziel_pfad.unlink(missing_ok=True)
                    return jsonify({
                        "ok":    False,
                        "error": f"Datei ueberschreitet 20-MB-Limit ({groesse // 1_048_576} MB empfangen)",
                    }), 413
                fh.write(chunk)
    except OSError as exc:
        current_app.logger.error("Sample-Datei konnte nicht gespeichert werden: %s", exc)
        return jsonify({"ok": False, "error": "Datei konnte nicht gespeichert werden"}), 500

    # --- Session-Zuweisung aktualisieren ------------------------------------
    zuweisungen: Dict[str, str] = session.get(f"samples_{audio_uuid}") or {}
    zuweisungen[builder_key] = str(ziel_pfad)
    session[f"samples_{audio_uuid}"] = zuweisungen

    current_app.logger.info(
        "Sample hochgeladen: uuid=%s key=%s datei=%s groesse=%d B",
        audio_uuid, builder_key, audio_datei.filename, groesse,
    )
    return jsonify({
        "ok":          True,
        "filename":    audio_datei.filename,
        "size_bytes":  groesse,
        "builder_key": builder_key,
    })


# ---------------------------------------------------------------------------
# Route: Loeschen
# ---------------------------------------------------------------------------

@sample_upload_bp.route("/sample_upload/<audio_uuid>/<builder_key>", methods=["DELETE"])
@login_required
def delete_sample(audio_uuid: str, builder_key: str):
    """
    Entfernt die Sample-Zuweisung eines Tracks und loescht die Datei.

    Pfad-Parameter:
        audio_uuid  — UUID der Kompositions-Session
        builder_key — Track-Bezeichnung
    """
    zuweisungen: Dict[str, str] = session.get(f"samples_{audio_uuid}") or {}
    datei_pfad = zuweisungen.pop(builder_key, None)
    session[f"samples_{audio_uuid}"] = zuweisungen

    if datei_pfad:
        try:
            pathlib.Path(datei_pfad).unlink(missing_ok=True)
        except Exception as exc:
            current_app.logger.warning("Sample-Datei konnte nicht geloescht werden: %s", exc)

    return jsonify({"ok": True})
