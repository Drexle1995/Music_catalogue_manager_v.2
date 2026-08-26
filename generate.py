"""
Generate blueprint — Beat-Generierung, temporaeres Audio-Serving, Speichern, Kontingent.

Der Music-Architect-Motor liegt ein Verzeichnis hoeher. Beide Pfade (Root und src/)
werden zu sys.path hinzugefuegt, damit die internen 'from src.*'-Imports des Motors
ohne Aenderung aufgeloest werden koennen.

Kontingent wird NUR bei /save verbraucht, niemals bei /generate. Zuhoeren ist immer frei.
"""

import io as _io
import json
import pathlib
import shutil
import sys
import tempfile
import time
import uuid
import wave
from datetime import date, datetime

from flask import (Blueprint, current_app, jsonify, request,
                   send_file, session)
from flask_login import current_user, login_required

import database as db
import export_service
import fusion_data
import palette_data as _palette_data
import theory_scorer as _theory_scorer
import sample_upload as _sample_upload
import gm_desc_data
import groove_data
import groove_processor
import instrument_data as _instr_data
import piano_roll_extractor
import production_advisor
import prompt_data

generate_bp = Blueprint("generate", __name__)

# Instrumentenlisten einmalig beim Modulimport laden (read-only JSON).
_INSTRUMENTS = _instr_data.load()

# Fusion-Presets einmalig laden.
_FUSION_PRESETS = fusion_data.load_presets()


def _set_instr(cfg, track: str, value):
    """
    Setzt den GM-Programm-Index fuer eine Spur in cfg.tracks, falls ein Wert
    uebergeben wurde. Leer-Strings und None werden ignoriert.
    """
    if value is None or str(value).strip() == "":
        return
    try:
        cfg.tracks[track]["instrument"] = int(value)
    except (KeyError, ValueError):
        pass  # Unbekannte Spur oder kein Integer -> stillschweigend ignorieren


def _set_volume(cfg, track: str, value):
    """
    Setzt die Lautstaerke (0.0–1.0) fuer eine Spur in cfg.tracks.
    Erwartet einen Wert als String oder Float.
    """
    if value is None or str(value).strip() == "":
        return
    try:
        vol = max(0.0, min(1.0, float(value)))
        if track in cfg.tracks:
            cfg.tracks[track]["volume"] = vol
        else:
            cfg.tracks[track] = {"enabled": True, "volume": vol, "instrument": None}
    except (KeyError, ValueError):
        pass


# ---------------------------------------------------------------------------
# Music-Architect-Pfad — relativ zu dieser Datei aufgeloest, damit die App
# unabhaengig vom Startverzeichnis funktioniert.
# ---------------------------------------------------------------------------
_MA_ROOT = pathlib.Path(__file__).parent.parent / "MUSIC_ARCHITECT_V7"
_MA_SRC  = _MA_ROOT / "src"


def _ensure_ma_path():
    """Fuegt MA-Pfade einmalig zu sys.path hinzu (idempotent)."""
    ma_root = str(_MA_ROOT)
    ma_src  = str(_MA_SRC)
    if ma_root not in sys.path:
        sys.path.insert(0, ma_root)
    if ma_src not in sys.path:
        sys.path.insert(0, ma_src)


# ---------------------------------------------------------------------------
# Kontingent-Grenzen
# ---------------------------------------------------------------------------
_FREE_DAILY    = 3
_PRO_DAILY     = 10
_PRO_MONTHLY   = 100


def _quota_limits(tier: str):
    daily   = _PRO_DAILY    if tier == "pro" else _FREE_DAILY
    monthly = _PRO_MONTHLY  if tier == "pro" else None
    return daily, monthly


def _quota_remaining(user_id: int, tier: str):
    today = date.today().isoformat()
    row   = db.get_quota(user_id, today)

    daily_used   = row["daily_saves"]   if row else 0
    monthly_used = row["monthly_saves"] if row else 0

    daily_limit, monthly_limit = _quota_limits(tier)
    daily_rem   = max(daily_limit - daily_used, 0)
    monthly_rem = (max(monthly_limit - monthly_used, 0)
                   if monthly_limit is not None else None)
    return daily_rem, monthly_rem, daily_used, monthly_used


def _read_seed_from_session(audio_uuid: str) -> int | None:
    """Liest den Kompositions-Seed aus der gespeicherten composition.json.

    Gibt den Seed-Wert (int) zurueck oder None, falls nicht verfuegbar.
    Wird beim ersten Export aufgerufen, um den Seed dauerhaft im Katalog zu sichern.
    """
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return None
    comp_path = pathlib.Path(tmp_dir_str) / "composition.json"
    if not comp_path.exists():
        return None
    try:
        comp_data = json.loads(comp_path.read_text(encoding="utf-8"))
        # Seed liegt unter composition.config.seed_value (MA-V7-Struktur).
        seed_val = (comp_data
                    .get("composition", {})
                    .get("config", {})
                    .get("seed_value"))
        return int(seed_val) if seed_val is not None else None
    except Exception:
        return None


def _persist_track(audio_uuid: str, user_id: int) -> int | None:
    """Speichert den Beat dauerhaft: WAV kopieren, Datenbank-Eintraege anlegen.

    Wird beim ersten Download (Audio oder MIDI) automatisch aufgerufen.
    Status wird sofort als 'exclusive_sold' gesetzt, da der Beat vom Nutzer
    heruntergeladen wurde und nicht mehr frei verfuegbar ist.
    Der Seed wird in watermark_tag gespeichert, um spaetere Rückverfolgbarkeit
    zu ermoeglichen (Traceability ohne harte Seed-Sperre).

    Gibt track_id zurueck oder None bei Fehler.
    Plattformunabhaengig: Pfade werden als POSIX-Strings (Slashes) gespeichert.
    """
    wav_str = session.get(f"temp_{audio_uuid}")
    if not wav_str:
        return None
    wav_src = pathlib.Path(wav_str)
    if not wav_src.exists():
        return None

    genre = session.get(f"temp_genre_{audio_uuid}", "unknown")
    now   = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    name  = f"{genre}_{now[:10]}"

    # Seed fuer Traceability auslesen (kein Pflichtfeld — schlaegt still fehl).
    seed_tag = _read_seed_from_session(audio_uuid)
    watermark_tag = f"seed:{seed_tag}" if seed_tag is not None else None

    # Zielverzeichnis plattformunabhaengig aufbauen.
    audio_dir = pathlib.Path(__file__).parent / "static" / "audio" / str(user_id)
    audio_dir.mkdir(parents=True, exist_ok=True)
    dest_path = audio_dir / f"{uuid.uuid4().hex}.wav"
    try:
        shutil.copy2(str(wav_src), str(dest_path))
    except OSError:
        return None

    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO tracks "
            "(title, genre, user_id, status, watermark_tag, created_at) "
            "VALUES (?, ?, ?, 'exclusive_sold', ?, ?)",
            (name, genre, user_id, watermark_tag, now),
        )
        track_id = cur.lastrowid
        # as_posix() stellt Forward-Slashes auf allen Betriebssystemen sicher.
        rel_path = dest_path.relative_to(pathlib.Path(__file__).parent).as_posix()
        conn.execute(
            "INSERT INTO exports (track_id, tier, file_path, file_format, found_at) "
            "VALUES (?, 'wav', ?, 'wav', ?)",
            (track_id, rel_path, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        conn.close()
        dest_path.unlink(missing_ok=True)
        return None
    conn.close()
    db.log_event("EXPORT_SAVE", "track", track_id,
                 {"user_id": user_id, "audio_uuid": audio_uuid,
                  "genre": genre, "seed_tag": watermark_tag})
    return track_id


# ---------------------------------------------------------------------------
# Routen
# ---------------------------------------------------------------------------

@generate_bp.route("/generate", methods=["GET"])
@login_required
def generate_page():
    from flask import render_template
    daily_rem, monthly_rem, _, _ = _quota_remaining(
        current_user.id, current_user.tier)
    # GM-Beschreibungen als JSON-String fuer das Template laden.
    import json as _json
    gm_descs: dict = {}
    for track_key, options in [
        ("drums",      _INSTRUMENTS.drums),
        ("percussion", _INSTRUMENTS.percussion),
        ("bass",       _INSTRUMENTS.bass),
        ("chords",     _INSTRUMENTS.chords),
        ("lead",       _INSTRUMENTS.lead),
        ("pad",        _INSTRUMENTS.pad),
        ("arp",        _INSTRUMENTS.arp),
        ("stabs",      _INSTRUMENTS.stabs),
        ("texture",    _INSTRUMENTS.texture),
        ("fx",         _INSTRUMENTS.fx),
    ]:
        gm_descs[track_key] = gm_desc_data.descriptions_for_track(track_key, options)

    # Vollstaendige GM → BDRA-Zuordnung einmalig berechnen und als JSON uebergeben.
    # Wird im Frontend fuer die Theorie-Bewertung bei manuellen Instrument-Aenderungen benoetigt.
    gm_bdra_codes = _palette_data.get_all_gm_bdra_codes()

    return render_template(
        "generate.html",
        tier                 = current_user.tier,
        daily_remaining      = daily_rem,
        monthly_remaining    = monthly_rem,
        _instruments         = _INSTRUMENTS,
        _fusion_presets      = _FUSION_PRESETS,
        _fusion_genres       = fusion_data.AVAILABLE_GENRES,
        _gm_descs_json       = _json.dumps(gm_descs),
        _groove_genres_json  = _json.dumps(groove_data.AVAILABLE_GENRES),
        _gm_bdra_codes_json  = _json.dumps(gm_bdra_codes),
    )


@generate_bp.route("/generate", methods=["POST"])
@login_required
def generate_track():
    """
    Beat aus dem Music-Architect-Motor erzeugen und temporaere Audio-URL zurueckgeben.
    Kein Kontingent wird hier verbraucht — nur /save dekrementiert den Zaehler.
    """
    data = request.get_json(silent=True) or request.form

    # --- Basis-Parameter ---
    genre   = data.get("genre",       "trap")
    bpm_raw = data.get("bpm",         None)
    comp    = int(data.get("complexity", 5))
    seed    = data.get("seed",         None)

    # --- Kompositions-Parameter ---
    key_note   = data.get("key_note",      "")
    key_scale  = data.get("key_scale",     "")
    duration   = data.get("duration_bars", 0)
    mutation   = data.get("mutation",      0.0)
    humanize   = data.get("humanize",      0.6)
    tension    = data.get("tension",       0.0)
    fx_variant = data.get("fx_variant",   "neutral")

    # --- Generierungsmodus ---
    # 'full' | 'vocal_ready' | 'both'
    gen_mode = data.get("generation_mode", "full")

    # --- Prompt-Dekodierung (SemanticCipher) ---
    # Wenn ein Prompt eingegeben wurde, ueberschreibt er die manuellen Parameter.
    prompt_text = (data.get("prompt") or "").strip()
    decoded_prompt: dict = {}
    if prompt_text:
        decoded_prompt = prompt_data.decode_prompt(prompt_text)
        # Prompt-Genre und BPM ueberschreiben manuelle Eingaben.
        if decoded_prompt.get("genre"):
            genre = decoded_prompt["genre"]
        if decoded_prompt.get("bpm") is not None:
            bpm_raw = str(decoded_prompt["bpm"])
        if decoded_prompt.get("tension_multiplier") is not None:
            tension = decoded_prompt["tension_multiplier"]
        if decoded_prompt.get("complexity") is not None:
            comp = int(decoded_prompt["complexity"])
        if decoded_prompt.get("scale_hint") and not key_scale:
            key_scale = decoded_prompt["scale_hint"]

    # --- Instrument-Auswahl pro Spur ---
    instr_bass       = data.get("instr_bass",       None)
    instr_chords     = data.get("instr_chords",     None)
    instr_lead       = data.get("instr_lead",       None)
    instr_pad        = data.get("instr_pad",        None)
    instr_arp        = data.get("instr_arp",        None)
    instr_drums      = data.get("instr_drums",      None)
    instr_stabs      = data.get("instr_stabs",      None)
    instr_texture    = data.get("instr_texture",    None)
    instr_fx         = data.get("instr_fx",         None)
    instr_percussion = data.get("instr_percussion", None)

    # --- Lautstaerke pro Spur (0.0–1.0) ---
    vol_drums      = data.get("vol_drums",      None)
    vol_percussion = data.get("vol_percussion", None)
    vol_bass       = data.get("vol_bass",       None)
    vol_chords     = data.get("vol_chords",     None)
    vol_lead       = data.get("vol_lead",       None)
    vol_pad        = data.get("vol_pad",        None)
    vol_arp        = data.get("vol_arp",        None)
    vol_stabs      = data.get("vol_stabs",      None)
    vol_texture    = data.get("vol_texture",    None)
    vol_fx         = data.get("vol_fx",         None)

    # --- Fusion-Parameter ---
    fusion_mode   = data.get("fusion_mode",   "off")     # 'off' | 'preset' | 'custom'
    fusion_preset = data.get("fusion_preset", None)
    fusion_genre1 = data.get("fusion_genre1", None)
    fusion_genre2 = data.get("fusion_genre2", None)
    fusion_ratio  = float(data.get("fusion_ratio", 0.5))

    # --- Soundfont-Auswahl (optional — beschleunigt Rendering erheblich) ---
    sf2_key  = data.get("sf2_key",  None)
    sf2_uuid = data.get("sf2_uuid", None)

    bpm = float(bpm_raw) if bpm_raw else None
    key = f"{key_note} {key_scale}".strip() if key_note and key_scale else (
          key_scale if key_scale else None)

    # Ob ein stummes Beat-Rendering ohne Lead-/Pad-/Arp-Stimmen gewuenscht ist.
    vocal_mask = gen_mode in ("vocal_ready", "both")

    # --- Seed-Sperre: exklusiv verkaufte Seeds koennen nicht erneut generiert werden ---
    # Nur pruefen wenn der Nutzer einen expliziten Seed eingegeben hat (kein Zufalls-Seed).
    if seed:
        try:
            seed_int = int(seed)
            _conn = db.get_conn()
            _row  = _conn.execute(
                "SELECT id FROM tracks "
                "WHERE watermark_tag = ? AND status = 'exclusive_sold' LIMIT 1",
                (f"seed:{seed_int}",),
            ).fetchone()
            _conn.close()
            if _row:
                return jsonify({
                    "error":   "seed_locked",
                    "message": (
                        f"Seed {seed_int} wurde bereits exklusiv verkauft "
                        "und kann nicht erneut generiert werden."
                    ),
                }), 409
        except ValueError:
            pass  # Kein gueltiger Integer-Seed — wird spaeter in CompositionConfig behandelt.

    try:
        _ensure_ma_path()
        from composition.composition_engine import CompositionEngine
        from composition.composition_config import CompositionConfig
        from rendering.wav_renderer import WAVRenderer

        cfg = CompositionConfig(
            genre             = genre,
            bpm               = bpm,
            complexity        = comp,
            seed_value        = int(seed) if seed else None,
            key               = key,
            duration_bars     = int(duration) if duration else 0,
            mutation          = float(mutation),
            humanize_amount   = float(humanize),
            tension_multiplier= float(tension),
            vocal_mask        = vocal_mask,
        )

        # Instrument-Auswahl in das tracks-Dict eintragen.
        _set_instr(cfg, "bass",       instr_bass)
        _set_instr(cfg, "chords",     instr_chords)
        _set_instr(cfg, "lead",       instr_lead)
        _set_instr(cfg, "pad",        instr_pad)
        _set_instr(cfg, "arp",        instr_arp)
        _set_instr(cfg, "drums",      instr_drums)
        _set_instr(cfg, "stabs",      instr_stabs)
        _set_instr(cfg, "texture",    instr_texture)
        _set_instr(cfg, "fx",         instr_fx)
        _set_instr(cfg, "percussion", instr_percussion)

        # Lautstaerke pro Spur setzen.
        _set_volume(cfg, "drums",      vol_drums)
        _set_volume(cfg, "percussion", vol_percussion)
        _set_volume(cfg, "bass",       vol_bass)
        _set_volume(cfg, "chords",     vol_chords)
        _set_volume(cfg, "lead",       vol_lead)
        _set_volume(cfg, "pad",        vol_pad)
        _set_volume(cfg, "arp",        vol_arp)
        _set_volume(cfg, "stabs",      vol_stabs)
        _set_volume(cfg, "texture",    vol_texture)
        _set_volume(cfg, "fx",         vol_fx)

        # Fusion-Modus: Preset oder Custom-Mix setzen (kein dict -- waere AttributeError).
        fusion_cfg = fusion_data.build_fusion_config(
            mode       = fusion_mode,
            preset_key = fusion_preset,
            genre1     = fusion_genre1,
            genre2     = fusion_genre2,
            ratio      = fusion_ratio,
        )
        if fusion_cfg is not None:
            cfg.fusion = fusion_cfg

        # Absoluten Seeds-Pfad uebergeben, damit die Web-App die 129.963 Seeds findet.
        engine      = CompositionEngine(seeds_dir=str(_MA_ROOT / "seeds"))
        composition = engine.compose(cfg)

        tmp_dir  = pathlib.Path(tempfile.mkdtemp())
        wav_path = tmp_dir / "beat.wav"

        # BPM fruehzeitig berechnen — wird fuer MIDI-Export und JSON benoetigt.
        _saved_bpm = composition.get("config", {}).get("bpm") or bpm or 120.0

        # Komposition in serialisierbares Dict umwandeln — notwendig fuer MIDI-Export
        # und JSON-Speicherung, da das rohe MA-V7-Objekt nicht-serialisierbare Typen enthalten kann.
        _comp_dict = groove_processor.jsonify_composition(composition)

        # SF2-Pfad aufloesen: hochgeladene Datei > manueller Preset-Key > Genre-Standard.
        # SoundFontLibrary.select(genre) liefert denselben genrespezifischen Font wie MA V7.
        _sf2_path = None
        if sf2_uuid:
            _sf2_path = session.get(f"sf2_{sf2_uuid}")
        else:
            try:
                from rendering.soundfont_library import SoundFontLibrary
                _lib = SoundFontLibrary()
                if sf2_key:
                    # Explizite Nutzerauswahl — direkt aus der Bibliothek laden.
                    _sf2_path = _lib._available.get(sf2_key)
                else:
                    # Kein SF2 ausgewaehlt → Genre-Standard verwenden (wie MA V7).
                    _sf2_path = _lib.select(genre)
            except Exception:
                pass

        # Builtin-Renderer immer bereitstellen — auch als Fallback und fuer Vocal-Modus.
        renderer = WAVRenderer()

        # Mit SF2 (FluidSynth) rendern falls verfuegbar, sonst Builtin-Synthesizer.
        _rendered_with_sf2 = False
        if _sf2_path and pathlib.Path(_sf2_path).exists():
            try:
                # Serialisierbares Dict verwenden, damit export_midi dasselbe Format
                # erhaelt wie beim Re-Render (dort wird aus JSON geladen).
                midi_bytes   = export_service.export_midi(_comp_dict, _saved_bpm)
                midi_tmp     = tmp_dir / "render.mid"
                midi_tmp.write_bytes(midi_bytes)
                renderer_sf2 = WAVRenderer(soundfont_path=str(_sf2_path))
                result_sf2   = renderer_sf2.render_midi_to_wav(str(midi_tmp), str(wav_path))
                # result_sf2 kann ein Pfad-String oder True sein — WAV muss existieren.
                if result_sf2 and wav_path.exists() and wav_path.stat().st_size > 0:
                    _rendered_with_sf2 = True
                else:
                    current_app.logger.warning(
                        "SF2-Rendering lieferte leere oder fehlende WAV, Fallback auf Builtin.")
            except Exception as _sf2e:
                current_app.logger.warning("SF2-Rendering fehlgeschlagen, Fallback: %s", _sf2e)

        if not _rendered_with_sf2:
            renderer.render_composition_to_wav(composition, str(wav_path))

        # Sicherstellen, dass die WAV-Datei tatsaechlich erstellt wurde.
        if not wav_path.exists() or wav_path.stat().st_size == 0:
            raise RuntimeError(
                "Rendering fehlgeschlagen: WAV-Datei fehlt oder ist leer. "
                "Bitte Server-Log pruefen."
            )

        # Komposition als JSON speichern — wird fuer Solo-Rendering und Re-Render benoetigt.
        try:
            comp_json = json.dumps({
                "composition": _comp_dict,
                "bpm":         _saved_bpm,
                "genre":       genre,
            }, ensure_ascii=False)
            (tmp_dir / "composition.json").write_text(comp_json, encoding="utf-8")
        except Exception as _je:
            current_app.logger.warning("Kompositions-JSON konnte nicht gespeichert werden: %s", _je)

        # Advisor-Daten fuer spaetere PDF-Exporte speichern
        try:
            _adv_early = production_advisor.get_full_advisor(genre, _saved_bpm, composition)
            _adv_meta  = {
                "bpm":        _saved_bpm,
                "key":        composition.get("config", {}).get("key", genre),
                "genre":      genre,
                "total_bars": composition.get("total_bars", 0),
            }
            (tmp_dir / "advisor.json").write_text(
                json.dumps({"advisor": _adv_early, "meta": _adv_meta, "genre": genre},
                           ensure_ascii=False),
                encoding="utf-8",
            )
        except Exception as _ae:
            current_app.logger.warning("Advisor-JSON konnte nicht gespeichert werden: %s", _ae)

        # Bei Modus 'both': zweite Version mit vocal_mask=True rendern.
        vocal_wav_path = None
        if gen_mode == "both":
            cfg_vocal             = CompositionConfig(**vars(cfg) if hasattr(cfg, '__dict__') else {})
            # Schnellere Alternative: vocal_mask direkt am selben Config aktivieren.
            cfg.vocal_mask        = True
            vocal_wav_path_tmp    = tmp_dir / "beat_vocal.wav"
            # Builtin-Renderer fuer Vocal-Version verwenden (SF2 kein vocal_mask-Unterstuetzung).
            renderer.render_composition_to_wav(composition, str(vocal_wav_path_tmp))
            vocal_wav_path = vocal_wav_path_tmp

    except Exception as exc:
        current_app.logger.error("Generierung fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500

    # Audio-Laenge via stdlib-wave berechnen (keine zusaetzliche Abhaengigkeit).
    try:
        with wave.open(str(wav_path), "rb") as wf:
            frames = wf.getnframes()
            rate   = wf.getframerate()
            audio_duration = round(frames / rate, 1) if rate > 0 and frames > 0 else 0.0
    except Exception as _we:
        current_app.logger.warning("WAV-Laenge konnte nicht gelesen werden (%s): %s", wav_path, _we)
        audio_duration = 0.0

    audio_uuid = str(uuid.uuid4())
    # WAV-Pfad und Kompositions-Verzeichnis in der Session speichern.
    session[f"temp_{audio_uuid}"]        = str(wav_path)
    session[f"temp_genre_{audio_uuid}"]  = genre
    session[f"temp_dir_{audio_uuid}"]    = str(tmp_dir)

    # Vocal-Version ebenfalls in Session speichern, falls vorhanden.
    # origin_uuid verknuepft Vocal-Export mit dem Haupt-Kontingent-Gate.
    if vocal_wav_path and vocal_wav_path.exists():
        vocal_uuid = str(uuid.uuid4())
        session[f"temp_{vocal_uuid}"]        = str(vocal_wav_path)
        session[f"temp_genre_{vocal_uuid}"]  = genre
        session[f"origin_uuid_{vocal_uuid}"] = audio_uuid
    else:
        vocal_uuid = None

    # Piano-Roll-Daten extrahieren.
    roll_data = piano_roll_extractor.extract(composition)

    # --- Ausgabe-Metadaten zusammenstellen ---------------------------------
    comp_cfg  = composition.get("config", {})
    comp_bpm  = comp_cfg.get("bpm", bpm or 120.0)
    comp_key  = comp_cfg.get("key", genre)
    chord_list= composition.get("chord_progression", [])

    # Song-Titel wie im Desktop-Programm formatieren.
    song_title = f"{genre.capitalize()} Song — {comp_bpm:.1f} BPM · {comp_key}"

    # Dauer als MM:SS formatieren.
    dur_secs = composition.get("duration_seconds", audio_duration) or audio_duration
    dur_min  = int(dur_secs // 60)
    dur_sec  = int(dur_secs % 60)
    dur_display = f"{dur_min:02d}:{dur_sec:02d}"

    # WAV-Bitrate berechnen (PCM 16-bit Stereo = frame_rate * channels * 2 * 8 bit).
    try:
        with wave.open(str(wav_path), "rb") as wf2:
            bitrate_kbps = (wf2.getframerate() * wf2.getnchannels()
                            * wf2.getsampwidth() * 8) // 1000
            sample_rate  = wf2.getframerate()
    except Exception:
        bitrate_kbps = 0
        sample_rate  = 44100

    # Ereigniszaehlung pro Spur.
    track_events = {
        tname: len(notes)
        for tname, notes in composition.get("tracks", {}).items()
    }

    output_meta = {
        "title":            song_title,
        "bpm":              comp_bpm,
        "key":              comp_key,
        "genre":            genre,
        "year":             datetime.now().year,
        "duration_display": dur_display,
        "duration_seconds": round(dur_secs, 1),
        "bitrate_kbps":     bitrate_kbps,
        "sample_rate":      sample_rate,
        "chord_progression": chord_list,
        "track_events":     track_events,
        "total_bars":       composition.get("total_bars", 0),
    }

    # --- Produktionsberater-Daten -----------------------------------------
    advisor_data = production_advisor.get_full_advisor(genre, comp_bpm, composition)

    # --- Instrument-Beschreibungen fuer die gewaehlten Spuren -------------
    track_info = composition.get("track_info", {})
    instruments_info: dict = {}
    for tname, ti in track_info.items():
        gm_prog  = ti.get("program", 0)
        is_drums = (ti.get("channel", 0) == 9)
        desc = (gm_desc_data.get_drum_description(gm_prog)
                if is_drums
                else gm_desc_data.get_description(gm_prog))
        instruments_info[tname] = {
            "gm":   gm_prog,
            "desc": desc,
        }

    return jsonify({
        "audio_url":       f"/temp_audio/{audio_uuid}",
        "vocal_url":       f"/temp_audio/{vocal_uuid}" if vocal_uuid else None,
        "duration":        audio_duration,
        "uuid":            audio_uuid,
        "vocal_uuid":      vocal_uuid,
        "piano_roll":      roll_data,
        "prompt_decoded":  decoded_prompt,
        "output_meta":     output_meta,
        "advisor":         advisor_data,
        "instruments_info":instruments_info,
    })


@generate_bp.route("/temp_audio/<audio_uuid>")
@login_required
def temp_audio(audio_uuid: str):
    """Temporaere WAV-Datei ausliefern. Dateien aelter als 1 Stunde werden geloescht."""
    wav_str = session.get(f"temp_{audio_uuid}")
    if not wav_str:
        return jsonify({"error": "not_found"}), 404

    wav_path = pathlib.Path(wav_str)
    if not wav_path.exists():
        return jsonify({"error": "not_found"}), 404

    # Automatisch nach 1 Stunde ablaufen lassen.
    if time.time() - wav_path.stat().st_mtime > 3600:
        wav_path.unlink(missing_ok=True)
        try:
            wav_path.parent.rmdir()
        except OSError:
            pass
        return jsonify({"error": "expired"}), 404

    return send_file(str(wav_path), mimetype="audio/wav")


@generate_bp.route("/save", methods=["POST"])
@login_required
def save_track():
    """
    Beat dauerhaft speichern:
      1. Kontingent pruefen.
      2. WAV in static/audio/<user_id>/ kopieren.
      3. INSERT in tracks + exports + audit_log.
      4. Kontingent-Zaehler erhoehen.
    """
    data       = request.get_json(silent=True) or request.form
    name       = (data.get("name") or "").strip() or "Untitled"
    audio_uuid = (data.get("uuid") or "").strip()

    if not audio_uuid:
        return jsonify({"error": "missing_uuid"}), 400

    wav_str = session.get(f"temp_{audio_uuid}")
    if not wav_str:
        return jsonify({"error": "not_found",
                        "message": "Kein generiertes Audio gefunden. Bitte zuerst generieren."}), 400

    genre = session.get(f"temp_genre_{audio_uuid}", "unknown")

    # --- Kontingent-Pruefung ------------------------------------------------
    today = date.today().isoformat()
    tier  = current_user.tier
    daily_rem, monthly_rem, _, _ = _quota_remaining(current_user.id, tier)

    if daily_rem <= 0:
        limit = _PRO_DAILY if tier == "pro" else _FREE_DAILY
        return jsonify({
            "error":   "quota_exceeded",
            "message": f"Tageslimit erreicht ({limit}/Tag im {tier}-Tarif).",
        }), 429

    if monthly_rem is not None and monthly_rem <= 0:
        return jsonify({
            "error":   "quota_exceeded",
            "message": f"Monatslimit erreicht ({_PRO_MONTHLY}/Monat im {tier}-Tarif).",
        }), 429

    # --- In dauerhaften Speicher kopieren -----------------------------------
    wav_src = pathlib.Path(wav_str)
    if not wav_src.exists():
        return jsonify({"error": "not_found",
                        "message": "Temporaere Datei fehlt. Bitte neu generieren."}), 400

    audio_dir = (pathlib.Path(__file__).parent / "static" / "audio"
                 / str(current_user.id))
    audio_dir.mkdir(parents=True, exist_ok=True)

    dest_name = f"{uuid.uuid4().hex}.wav"
    dest_path = audio_dir / dest_name
    shutil.copy2(str(wav_src), str(dest_path))

    # --- Datenbankeintraege -------------------------------------------------
    now  = __import__("datetime").datetime.now().isoformat(timespec="seconds")
    conn = db.get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO tracks (title, genre, user_id, status, created_at) "
            "VALUES (?, ?, ?, 'exclusive_sold', ?)",
            (name, genre, current_user.id, now),
        )
        track_id = cur.lastrowid

        rel_path = str(dest_path.relative_to(pathlib.Path(__file__).parent))
        conn.execute(
            "INSERT INTO exports (track_id, tier, file_path, file_format, found_at) "
            "VALUES (?, 'wav', ?, 'wav', ?)",
            (track_id, rel_path, now),
        )
        conn.commit()
    except Exception as exc:
        conn.rollback()
        conn.close()
        dest_path.unlink(missing_ok=True)
        return jsonify({"error": str(exc)}), 500

    conn.close()

    db.log_event("SAVE", "track", track_id, {
        "user_id": current_user.id,
        "name":    name,
        "genre":   genre,
        "file":    str(dest_path),
    })

    # --- Kontingent erhoehen -----------------------------------------------
    db.increment_quota(current_user.id, today)

    # Verbleibenden Stand nach Erhoehung neu auslesen.
    daily_rem_new, monthly_rem_new, _, _ = _quota_remaining(current_user.id, tier)

    # Temporaere Dateien aufraumen.
    try:
        wav_src.unlink(missing_ok=True)
        wav_src.parent.rmdir()
    except OSError:
        pass
    session.pop(f"temp_{audio_uuid}",       None)
    session.pop(f"temp_genre_{audio_uuid}", None)

    return jsonify({
        "success":           True,
        "track_id":          track_id,
        "quota_remaining":   daily_rem_new,
        "monthly_remaining": monthly_rem_new,
    })


@generate_bp.route("/groove_preset/<genre>")
@login_required
def groove_preset_route(genre: str):
    """
    Gibt die Groove-Voreinstellung fuer ein Genre als JSON zurueck.
    Wird vom Groove-Mixer im Frontend verwendet, um Schieberegler zu befuellen.
    """
    preset = groove_data.get_groove_preset(genre)
    return jsonify(preset)


@generate_bp.route("/advisor_data/<genre>")
@login_required
def advisor_data_route(genre: str):
    """
    Gibt Produktionsberater-Daten fuer ein Genre als JSON zurueck.
    Erlaubt nachladen der Advisor-Daten ohne erneute Generierung.
    """
    bpm_raw = request.args.get("bpm", "120")
    try:
        bpm = float(bpm_raw)
    except ValueError:
        bpm = 120.0
    data = production_advisor.get_full_advisor(genre, bpm)
    return jsonify(data)


@generate_bp.route("/decode_prompt", methods=["POST"])
@login_required
def decode_prompt_route():
    """
    Dekodiert einen natuerlichsprachigen Prompt via SemanticCipher und
    gibt die erkannten Parameter als JSON zurueck (ohne Generierung).
    Nuetzlich fuer Echtzeit-Vorschau der erkannten Parameter in der UI.
    """
    data   = request.get_json(silent=True) or request.form
    text   = (data.get("prompt") or "").strip()
    result = prompt_data.decode_prompt(text)
    return jsonify(result)


@generate_bp.route("/render_solo/<audio_uuid>/<track_name>")
@login_required
def render_solo(audio_uuid: str, track_name: str):
    """
    Rendert eine einzelne Spur als Solo-WAV.
    Alle anderen Spuren werden stummgeschaltet.
    Gibt eine temporaere Audio-URL zurueck.
    """
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"error": "not_found"}), 404

    comp_path = pathlib.Path(tmp_dir_str) / "composition.json"
    if not comp_path.exists():
        return jsonify({"error": "composition_not_found"}), 404

    try:
        comp_data   = json.loads(comp_path.read_text(encoding="utf-8"))
        composition = comp_data["composition"]
        bpm_val     = comp_data.get("bpm", 120.0)

        _ensure_ma_path()
        from rendering.wav_renderer import WAVRenderer

        solo_comp   = groove_processor.build_solo_composition(composition, track_name)
        solo_dir    = pathlib.Path(tempfile.mkdtemp())
        solo_path   = solo_dir / f"solo_{track_name}.wav"

        renderer = WAVRenderer()
        renderer.render_composition_to_wav(solo_comp, str(solo_path))

        solo_uuid = str(uuid.uuid4())
        session[f"temp_{solo_uuid}"] = str(solo_path)
        return jsonify({"audio_url": f"/temp_audio/{solo_uuid}"})

    except Exception as exc:
        current_app.logger.error("Solo-Rendering fehlgeschlagen (%s): %s", track_name, exc)
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/rerender", methods=["POST"])
@login_required
def rerender_track():
    """
    Re-Rendering mit Groove-Parametern, Instrument-Aenderungen und Mutes.

    Erwartet JSON:
    {
      "uuid":         str,
      "track_params": {
        "bass": {"volume_db": 0.0, "mute": false, "instrument": null,
                 "swing_pct": 50.0, "nudge_ms": 0.0,
                 "vel_min": 1, "vel_max": 127,
                 "vel_jitter": 0, "time_jitter": 0.0, "humanize_seed": null},
        ...
      }
    }
    """
    data         = request.get_json(silent=True) or {}
    audio_uuid   = (data.get("uuid") or "").strip()
    track_params = data.get("track_params", {})

    if not audio_uuid:
        return jsonify({"error": "missing_uuid"}), 400

    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"error": "not_found"}), 404

    comp_path = pathlib.Path(tmp_dir_str) / "composition.json"
    if not comp_path.exists():
        return jsonify({"error": "composition_not_found"}), 404

    # SF2-Soundfont aufloesen (optional — Preset-Key oder hochgeladene Datei)
    sf2_key  = data.get("sf2_key",  None)
    sf2_uuid = data.get("sf2_uuid", None)
    sf2_path = None
    if sf2_uuid:
        sf2_path = session.get(f"sf2_{sf2_uuid}")
    elif sf2_key:
        try:
            _ensure_ma_path()
            from rendering.soundfont_library import SoundFontLibrary
            _lib = SoundFontLibrary()
            sf2_path = _lib._available.get(sf2_key)
        except Exception:
            pass

    try:
        comp_data   = json.loads(comp_path.read_text(encoding="utf-8"))
        composition = comp_data["composition"]
        bpm_val     = float(comp_data.get("bpm", 120.0))

        # Genre-Standard SF2 als Fallback wenn kein SF2 explizit ausgewaehlt.
        if not sf2_path:
            try:
                _ensure_ma_path()
                from rendering.soundfont_library import SoundFontLibrary
                sf2_path = SoundFontLibrary().select(comp_data.get("genre", ""))
            except Exception:
                pass

        modified = groove_processor.apply_groove_to_composition(
            composition, track_params, bpm_val)

        _ensure_ma_path()
        from rendering.wav_renderer import WAVRenderer

        rr_dir  = pathlib.Path(tempfile.mkdtemp())
        rr_path = rr_dir / "rerendered.wav"

        # Sample-Zuweisungen aus der Session lesen (Web-Keys → MA-V7-Keys umwandeln).
        # resolve_sample_assignments folgt der origin_uuid-Kette fuer Re-Render-UUIDs.
        web_samples = _sample_upload.resolve_sample_assignments(audio_uuid)
        ma_samples  = _sample_upload.zu_ma_assignments(web_samples) if web_samples else {}

        # FluidSynth/SF2 wird uebersprungen wenn Samples zugewiesen sind,
        # da FluidSynth keine rohen Audiopuffer verarbeiten kann.
        sf2_erlaubt = bool(sf2_path) and not bool(ma_samples)

        # SF2 gewuenscht und vorhanden (und kein Sample-Override): FluidSynth-Render
        rendered_with_sf2 = False
        if sf2_erlaubt and pathlib.Path(sf2_path).exists():
            try:
                midi_bytes  = export_service.export_midi(modified, bpm_val)
                midi_tmp    = rr_dir / "render.mid"
                midi_tmp.write_bytes(midi_bytes)
                renderer_sf2 = WAVRenderer(soundfont_path=str(sf2_path))
                result_sf2   = renderer_sf2.render_midi_to_wav(str(midi_tmp), str(rr_path))
                if result_sf2:
                    rendered_with_sf2 = True
            except Exception as _sf2e:
                current_app.logger.warning("SF2-Rendering fehlgeschlagen, Fallback: %s", _sf2e)

        if not rendered_with_sf2:
            renderer = WAVRenderer()
            # sample_assignments=None wenn kein Sample zugewiesen (kein Overhead).
            renderer.render_composition_to_wav(
                modified, str(rr_path),
                sample_assignments=ma_samples or None,
            )

        rr_uuid = str(uuid.uuid4())
        session[f"temp_{rr_uuid}"]        = str(rr_path)
        session[f"temp_genre_{rr_uuid}"]  = comp_data.get("genre", "beat")
        # origin_uuid verknuepft Re-Render-Export mit dem Haupt-Kontingent-Gate.
        session[f"origin_uuid_{rr_uuid}"] = audio_uuid
        return jsonify({"audio_url": f"/temp_audio/{rr_uuid}", "uuid": rr_uuid})

    except Exception as exc:
        current_app.logger.error("Re-Rendering fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/export_audio/<audio_uuid>")
@login_required
def export_audio_route(audio_uuid: str):
    """
    Audio-Datei im gewuenschten Format konvertieren und als Download senden.
    Beim ersten Herunterladen einer UUID wird das Kontingent um 1 dekrementiert.
    Erwartet Query-Parameter: ?format=<format_key>
    """
    fmt_key  = request.args.get("format", "wav_cd")
    wav_str  = session.get(f"temp_{audio_uuid}")
    if not wav_str:
        return jsonify({"error": "not_found"}), 404

    wav_path = pathlib.Path(wav_str)
    if not wav_path.exists():
        return jsonify({"error": "not_found"}), 404

    # --- Kontingent beim ersten Export dekrementieren ----------------------
    # Alle Varianten (Re-Render, Vocal, Original) teilen denselben Gate-Key,
    # damit ein Download pro Beat genuegt, unabhaengig vom Quellformat.
    origin_uuid  = session.get(f"origin_uuid_{audio_uuid}", audio_uuid)
    exported_key = f"exported_{origin_uuid}"
    if not session.get(exported_key):
        today = date.today().isoformat()
        tier  = current_user.tier
        daily_rem, monthly_rem, _, _ = _quota_remaining(current_user.id, tier)

        if daily_rem <= 0:
            limit = _PRO_DAILY if tier == "pro" else _FREE_DAILY
            return jsonify({
                "error":   "quota_exceeded",
                "message": f"Tageslimit erreicht ({limit}/Tag im {tier}-Tarif).",
            }), 429

        if monthly_rem is not None and monthly_rem <= 0:
            return jsonify({
                "error":   "quota_exceeded",
                "message": f"Monatslimit erreicht ({_PRO_MONTHLY}/Monat im {tier}-Tarif).",
            }), 429

        _persist_track(audio_uuid, current_user.id)
        db.increment_quota(current_user.id, today)
        db.log_event("EXPORT", "audio", audio_uuid, {
            "user_id": current_user.id,
            "format":  fmt_key,
            "genre":   session.get(f"temp_genre_{audio_uuid}", "beat"),
        })
        session[exported_key] = True

    try:
        fmt_info = export_service.AUDIO_FORMATS.get(
            fmt_key, export_service.AUDIO_FORMATS["wav_cd"])
        ext = fmt_info["ext"]

        out_dir  = pathlib.Path(tempfile.mkdtemp())
        out_path = out_dir / f"export.{ext}"
        result   = export_service.export_audio(str(wav_path), fmt_key, str(out_path))

        genre    = session.get(f"temp_genre_{audio_uuid}", "beat")
        filename = f"{genre}_{fmt_key}.{ext}"
        mime_map = {"wav": "audio/wav", "mp3": "audio/mpeg",
                    "flac": "audio/flac", "ogg": "audio/ogg"}

        return send_file(result, mimetype=mime_map.get(ext, "application/octet-stream"),
                         as_attachment=True, download_name=filename)

    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        current_app.logger.error("Audio-Export fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/export_midi/<audio_uuid>")
@login_required
def export_midi_route(audio_uuid: str):
    """Komposition als Standard-MIDI-Datei exportieren."""
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"error": "not_found"}), 404

    comp_path = pathlib.Path(tmp_dir_str) / "composition.json"
    if not comp_path.exists():
        return jsonify({"error": "composition_not_found"}), 404

    # --- Gemeinsames Kontingent-Gate (Audio und MIDI teilen denselben Schluessel) ---
    # Alle Varianten (Re-Render, Vocal, MIDI, Audio) werden auf die Ursprungs-UUID
    # zurueckgefuehrt, sodass nur ein Token pro Beat-Generierung verbraucht wird.
    origin_uuid  = session.get(f"origin_uuid_{audio_uuid}", audio_uuid)
    exported_key = f"exported_{origin_uuid}"
    if not session.get(exported_key):
        today = date.today().isoformat()
        tier  = current_user.tier
        daily_rem, monthly_rem, _, _ = _quota_remaining(current_user.id, tier)

        if daily_rem <= 0:
            limit = _PRO_DAILY if tier == "pro" else _FREE_DAILY
            return jsonify({
                "error":   "quota_exceeded",
                "message": f"Tageslimit erreicht ({limit}/Tag im {tier}-Tarif).",
            }), 429

        if monthly_rem is not None and monthly_rem <= 0:
            return jsonify({
                "error":   "quota_exceeded",
                "message": f"Monatslimit erreicht ({_PRO_MONTHLY}/Monat im {tier}-Tarif).",
            }), 429

        _persist_track(audio_uuid, current_user.id)
        db.increment_quota(current_user.id, today)
        db.log_event("EXPORT", "midi", audio_uuid, {
            "user_id": current_user.id,
            "genre":   session.get(f"temp_genre_{audio_uuid}", "beat"),
        })
        session[exported_key] = True

    try:
        comp_data   = json.loads(comp_path.read_text(encoding="utf-8"))
        composition = comp_data["composition"]
        bpm_val     = float(comp_data.get("bpm", 120.0))
        genre       = comp_data.get("genre", "beat")

        midi_bytes  = export_service.export_midi(composition, bpm_val)

        return send_file(
            _io.BytesIO(midi_bytes),
            mimetype="audio/midi",
            as_attachment=True,
            download_name=f"{genre}_composition.mid",
        )
    except Exception as exc:
        current_app.logger.error("MIDI-Export fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/export_json/<audio_uuid>")
@login_required
def export_json_route(audio_uuid: str):
    """Kompositions-JSON als Datei herunterladen."""
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"error": "not_found"}), 404

    comp_path = pathlib.Path(tmp_dir_str) / "composition.json"
    if not comp_path.exists():
        return jsonify({"error": "composition_not_found"}), 404

    try:
        comp_data = json.loads(comp_path.read_text(encoding="utf-8"))
        genre     = comp_data.get("genre", "beat")

        return send_file(
            _io.BytesIO(comp_path.read_bytes()),
            mimetype="application/json",
            as_attachment=True,
            download_name=f"{genre}_composition.json",
        )
    except Exception as exc:
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/export_advisory_pdf/<audio_uuid>")
@login_required
def export_advisory_pdf_route(audio_uuid: str):
    """Produktionsberater als PDF-Datei herunterladen."""
    tmp_dir_str = session.get(f"temp_dir_{audio_uuid}")
    if not tmp_dir_str:
        return jsonify({"error": "not_found"}), 404

    adv_path = pathlib.Path(tmp_dir_str) / "advisor.json"
    if not adv_path.exists():
        return jsonify({
            "error":   "advisor_not_found",
            "message": "Berater-Daten nicht gefunden — bitte neu generieren.",
        }), 404

    try:
        adv_data  = json.loads(adv_path.read_text(encoding="utf-8"))
        advisor   = adv_data.get("advisor", {})
        meta      = adv_data.get("meta", {})
        genre     = adv_data.get("genre", "beat")

        pdf_bytes = export_service.export_advisory_pdf(advisor, meta, genre)

        return send_file(
            _io.BytesIO(pdf_bytes),
            mimetype="application/pdf",
            as_attachment=True,
            download_name=f"{genre}_production_advisor.pdf",
        )
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 503
    except Exception as exc:
        current_app.logger.error("PDF-Export fehlgeschlagen: %s", exc)
        return jsonify({"error": str(exc)}), 500


@generate_bp.route("/export_formats")
@login_required
def export_formats_route():
    """Verfuegbare Audio-Formate und ffmpeg-Status zurueckgeben."""
    return jsonify({
        "formats":         export_service.AUDIO_FORMATS,
        "ffmpeg_available": export_service.ffmpeg_available(),
    })


@generate_bp.route("/available_soundfonts")
@login_required
def available_soundfonts_route():
    """Gibt installierte SF2-Soundfonts und FluidSynth-Status zurueck."""
    _ensure_ma_path()
    try:
        from rendering.soundfont_library import SoundFontLibrary, _SF2_DISPLAY
        from rendering.fluidsynth_renderer import _FLUIDSYNTH_EXE
        lib    = SoundFontLibrary()
        fonts  = [{"key": k, "label": _SF2_DISPLAY.get(k, k), "path": p}
                  for k, p in lib._available.items()]
        fs_ok  = _FLUIDSYNTH_EXE is not None
    except Exception:
        fonts = []
        fs_ok = False
    return jsonify({"fonts": fonts, "fluidsynth_available": fs_ok})


@generate_bp.route("/upload_soundfont", methods=["POST"])
@login_required
def upload_soundfont_route():
    """SF2-Datei vom Browser hochladen und temporaer speichern."""
    if "sf2" not in request.files:
        return jsonify({"error": "Keine Datei empfangen."}), 400
    f = request.files["sf2"]
    if not f.filename.lower().endswith(".sf2"):
        return jsonify({"error": "Nur .sf2-Dateien erlaubt."}), 400
    safe_name = pathlib.Path(f.filename).name
    sf2_dir   = pathlib.Path(tempfile.mkdtemp())
    sf2_path  = sf2_dir / safe_name
    f.save(str(sf2_path))
    sf2_uuid  = str(uuid.uuid4())
    session[f"sf2_{sf2_uuid}"] = str(sf2_path)
    return jsonify({"sf2_uuid": sf2_uuid, "name": safe_name})


@generate_bp.route("/palette_data/<genre>")
@login_required
def palette_data_route(genre: str):
    """
    Gibt Instrumenten-Paletten und FX-Ketten-Varianten fuer ein Genre zurueck.
    Datenquelle: MA V7 production_guide JSON-Dateien via palette_data.py.
    """
    palettes    = _palette_data.get_palettes(genre)
    fx_variants = _palette_data.get_fx_variants(genre)
    return jsonify({"palettes": palettes, "fx_variants": fx_variants})


@generate_bp.route("/theory_score", methods=["POST"])
@login_required
def theory_score_route():
    """
    Berechnet den Theorie-Score (P1-P5) mit MA-V7-BDRA-Validierung.
    Erwartet JSON: {branch, instruments: {bass:{code}, lead:{code}, ...}}
    branch: 'A', 'B' oder 'C' (aus der gewaehlten Palette, Standard: 'A').
    """
    data        = request.get_json(silent=True) or {}
    branch      = data.get("branch", "A")
    instruments = data.get("instruments", {})
    result      = _theory_scorer.score_instruments(branch, instruments)
    return jsonify(result)


@generate_bp.route("/quota")
@login_required
def quota():
    daily_rem, monthly_rem, _, _ = _quota_remaining(current_user.id, current_user.tier)
    return jsonify({
        "daily_remaining":   daily_rem,
        "monthly_remaining": monthly_rem,
        "tier":              current_user.tier,
    })
