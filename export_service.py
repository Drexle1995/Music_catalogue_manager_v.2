"""
export_service.py — Exportfunktionen fuer Beat-Kompositionen.

Unterstuetzt:
  - Audio: WAV (verschiedene Auflösungen), FLAC, MP3, OGG via ffmpeg (optional)
  - MIDI: Standard MIDI Format 1 via mido
  - JSON: Kompositions-JSON direkt
  - PDF: Produktionsberater via reportlab oder fpdf2

Plattformunabhaengig — kein kompilierter Code, keine Betriebssystem-APIs.
"""

from __future__ import annotations

import io
import pathlib
import shutil
import subprocess
from typing import Any, Dict

import mido  # in requirements.txt enthalten

# ── Audio-Formate ─────────────────────────────────────────────────────────────
# ffmpeg=False: Direktkopie moeglich; ffmpeg=True: Konvertierung erfordert ffmpeg.

AUDIO_FORMATS: Dict[str, Dict] = {
    "wav_cd":        {"label": "WAV CD Quality",         "ext": "wav",  "sr": 44100, "bits": 16, "ch": 2, "ffmpeg": False},
    "wav_master":    {"label": "WAV Mastering 32-Bit",   "ext": "wav",  "sr": 44100, "bits": 32, "ch": 2, "ffmpeg": True},
    "wav_broadcast": {"label": "WAV 48kHz Broadcast",    "ext": "wav",  "sr": 48000, "bits": 24, "ch": 2, "ffmpeg": True},
    "flac":          {"label": "FLAC Lossless",          "ext": "flac", "sr": 44100, "bits": 24, "ch": 2, "ffmpeg": True},
    "mp3_320":       {"label": "MP3 Highest (320 kbps)", "ext": "mp3",  "sr": 44100, "bits": 16, "ch": 2, "bitrate": "320k", "ffmpeg": True},
    "mp3_192":       {"label": "MP3 High (192 kbps)",    "ext": "mp3",  "sr": 44100, "bits": 16, "ch": 2, "bitrate": "192k", "ffmpeg": True},
    "mp3_128":       {"label": "MP3 Medium (128 kbps)",  "ext": "mp3",  "sr": 44100, "bits": 16, "ch": 2, "bitrate": "128k", "ffmpeg": True},
    "mp3_96":        {"label": "MP3 Lo-Fi (96 kbps)",    "ext": "mp3",  "sr": 44100, "bits": 16, "ch": 2, "bitrate": "96k",  "ffmpeg": True},
    "ogg_192":       {"label": "OGG 192 kbps",           "ext": "ogg",  "sr": 44100, "bits": 16, "ch": 2, "bitrate": "192k", "ffmpeg": True},
}


def ffmpeg_available() -> bool:
    """Gibt True zurueck wenn ffmpeg im PATH gefunden wurde."""
    return shutil.which("ffmpeg") is not None


def export_audio(src_wav: str, format_key: str, dest_path: str) -> str:
    """
    Konvertiert src_wav in das gewuenschte Format.
    Gibt den Pfad der erstellten Datei zurueck.
    Wirft RuntimeError wenn ffmpeg benoetigt wird, aber nicht verfuegbar ist.
    """
    fmt = AUDIO_FORMATS.get(format_key, AUDIO_FORMATS["wav_cd"])
    ext = fmt["ext"]
    out = pathlib.Path(dest_path).with_suffix(f".{ext}")

    # Keine Konvertierung noetig: einfache Kopie
    if not fmt.get("ffmpeg", False):
        shutil.copy2(src_wav, str(out))
        return str(out)

    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError(
            f"Das Format '{fmt['label']}' erfordert ffmpeg. "
            "Bitte ffmpeg installieren und im PATH verfuegbar machen."
        )

    cmd = [ffmpeg, "-y", "-i", src_wav, "-ar", str(fmt.get("sr", 44100))]

    if ext == "wav":
        bits = fmt.get("bits", 16)
        if bits == 32:
            cmd += ["-c:a", "pcm_f32le"]
        elif bits == 24:
            cmd += ["-c:a", "pcm_s24le"]
        else:
            cmd += ["-c:a", "pcm_s16le"]
    elif ext == "flac":
        cmd += ["-c:a", "flac", "-compression_level", "8"]
    elif ext == "mp3":
        cmd += ["-c:a", "libmp3lame", "-b:a", fmt.get("bitrate", "192k"),
                "-q:a", "0", "-joint_stereo", "1"]
    elif ext == "ogg":
        cmd += ["-c:a", "libvorbis", "-b:a", fmt.get("bitrate", "192k")]

    cmd.append(str(out))
    subprocess.run(cmd, check=True, capture_output=True)
    return str(out)


# ── MIDI-Export ───────────────────────────────────────────────────────────────

def export_midi(composition: dict, bpm: float) -> bytes:
    """
    Erstellt eine Standard-MIDI-Datei (Format 1) aus Kompositionsdaten.
    Benutzt mido — keine weiteren Abhaengigkeiten.
    """
    TICKS = 480  # Ticks pro Beat

    mid = mido.MidiFile(type=1, ticks_per_beat=TICKS)

    # Tempo-Spur (Track 0)
    tempo_trk = mido.MidiTrack()
    tempo_trk.name = "Tempo"
    tempo_trk.append(mido.MetaMessage(
        "set_tempo", tempo=mido.bpm2tempo(max(bpm, 1.0)), time=0))
    tempo_trk.append(mido.MetaMessage("end_of_track", time=0))
    mid.tracks.append(tempo_trk)

    tracks_data = composition.get("tracks", {})
    track_info  = composition.get("track_info", {})

    for track_name, notes in tracks_data.items():
        if not notes:
            continue
        info    = track_info.get(track_name, {})
        channel = int(info.get("channel", 0)) % 16
        program = int(info.get("program", 0)) & 0x7F

        trk = mido.MidiTrack()
        trk.name = track_name

        if channel != 9:
            trk.append(mido.Message(
                "program_change", channel=channel, program=program, time=0))

        # Absolute Ticks aufbauen, sortieren, Delta-Times berechnen
        events = []
        for note in notes:
            t, d, pitch, vel = float(note[0]), float(note[1]), int(note[2]), int(note[3])
            tick_on  = max(0, int(t * TICKS))
            tick_off = max(tick_on + 1, int((t + max(d, 0.01)) * TICKS))
            vel_c    = max(1, min(127, vel))
            events.append((tick_on,  "note_on",  pitch, vel_c))
            events.append((tick_off, "note_off", pitch, 0))

        events.sort(key=lambda x: x[0])
        prev = 0
        for tick, ev_type, pitch, vel in events:
            delta = tick - prev
            prev  = tick
            trk.append(mido.Message(
                ev_type, channel=channel,
                note=pitch & 0x7F, velocity=vel, time=delta))

        trk.append(mido.MetaMessage("end_of_track", time=0))
        mid.tracks.append(trk)

    buf = io.BytesIO()
    mid.save(file=buf)
    return buf.getvalue()


# ── PDF-Export ────────────────────────────────────────────────────────────────

def export_advisory_pdf(advisor: dict, meta: dict, genre: str) -> bytes:
    """
    Erstellt einen Produktionsberater-PDF.
    Versucht reportlab, dann fpdf2.
    Wirft RuntimeError wenn keine PDF-Bibliothek installiert ist.
    """
    try:
        return _pdf_reportlab(advisor, meta, genre)
    except ImportError:
        pass
    try:
        return _pdf_fpdf2(advisor, meta, genre)
    except ImportError:
        pass
    raise RuntimeError(
        "Keine PDF-Bibliothek installiert. "
        "Bitte 'pip install reportlab' oder 'pip install fpdf2' ausfuehren."
    )


def _pdf_reportlab(advisor: dict, meta: dict, genre: str) -> bytes:
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.units import mm
    from reportlab.platypus import (Paragraph, SimpleDocTemplate, Spacer,
                                    Table, TableStyle)

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4,
                            leftMargin=20 * mm, rightMargin=20 * mm,
                            topMargin=20 * mm, bottomMargin=20 * mm)
    styles  = getSampleStyleSheet()
    C_ACCENT = colors.HexColor("#7c6dea")
    C_TEXT   = colors.HexColor("#333333")
    C_BG     = colors.HexColor("#1e1e2e")
    C_BORDER = colors.HexColor("#2a2a40")

    h1   = ParagraphStyle("h1", parent=styles["Heading1"], fontSize=16, textColor=C_ACCENT)
    h2   = ParagraphStyle("h2", parent=styles["Heading2"], fontSize=11, textColor=C_ACCENT)
    h3   = ParagraphStyle("h3", parent=styles["Heading3"], fontSize=9,  textColor=C_ACCENT)
    norm = ParagraphStyle("norm", parent=styles["Normal"], fontSize=8,  textColor=C_TEXT)

    def make_table(rows, widths):
        t = Table(rows, colWidths=widths)
        t.setStyle(TableStyle([
            ("FONTSIZE",       (0, 0), (-1, -1), 8),
            ("BACKGROUND",     (0, 0), (-1,  0), C_BG),
            ("TEXTCOLOR",      (0, 0), (-1,  0), C_ACCENT),
            ("TEXTCOLOR",      (0, 1), (-1, -1), C_TEXT),
            ("GRID",           (0, 0), (-1, -1), 0.4, C_BORDER),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.HexColor("#f5f5ff"), colors.HexColor("#ececff")]),
        ]))
        return t

    story = [Paragraph(f"Produktionsberater — {genre.upper()}", h1),
             Spacer(1, 3 * mm)]

    story.append(Paragraph(
        f"BPM: {meta.get('bpm','—')}  ·  Tonart: {meta.get('key','—')}  "
        f"·  Takte: {meta.get('total_bars','—')}", norm))
    story.append(Spacer(1, 4 * mm))

    gs = advisor.get("gain_staging", [])
    if gs:
        story.append(Paragraph("GAIN STAGING", h2))
        rows = [["Spur", "RMS", "Peak", "LUFS-S", "Fader"]] + [
            [r.get("label", r.get("track", "—")),
             str(r.get("rms", "—")), str(r.get("peak", "—")),
             str(r.get("lufs_s", "—")), str(r.get("fader_db", "—"))]
            for r in gs]
        story.append(make_table(rows, [42*mm, 22*mm, 22*mm, 28*mm, 22*mm]))
        story.append(Spacer(1, 3 * mm))

    bpm_times = advisor.get("bpm_times", {})
    if bpm_times:
        story.append(Paragraph("BPM-ZEITWERTE", h2))
        rows = [["Parameter", "Wert"]] + [[k, str(v)] for k, v in bpm_times.items()]
        story.append(make_table(rows, [90*mm, 60*mm]))
        story.append(Spacer(1, 3 * mm))

    chains = advisor.get("effect_chains", {})
    if chains:
        story.append(Paragraph("EFFEKTKETTEN", h2))
        for track, slots in chains.items():
            story.append(Paragraph(track.upper(), h3))
            for s in slots:
                story.append(Paragraph(
                    f"[{s.get('slot','')}] {s.get('effect','')} — {s.get('params','')}",
                    norm))
        story.append(Spacer(1, 3 * mm))

    freq = advisor.get("frequency_allocation", [])
    if freq:
        story.append(Paragraph("FREQUENZALLOKATION", h2))
        rows = [["Spur", "HPF", "LPF", "Zone"]] + [
            [r.get("label", r.get("track", "—")),
             str(r.get("hpf", "—")), str(r.get("lpf", "—")), str(r.get("zone", "—"))]
            for r in freq]
        story.append(make_table(rows, [40*mm, 28*mm, 28*mm, 60*mm]))
        story.append(Spacer(1, 3 * mm))

    specs = advisor.get("export_specs", {})
    if specs:
        story.append(Paragraph("EXPORT-ZIELE", h2))
        for label, s in specs.items():
            story.append(Paragraph(label.upper(), h3))
            for k, v in s.items():
                story.append(Paragraph(f"{k}: {v}", norm))

    doc.build(story)
    return buf.getvalue()


def _pdf_fpdf2(advisor: dict, meta: dict, genre: str) -> bytes:
    from fpdf import FPDF

    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(auto=True, margin=20)

    def accent():
        pdf.set_text_color(124, 109, 234)

    def normal():
        pdf.set_text_color(50, 50, 50)

    pdf.set_font("Helvetica", "B", 16)
    accent()
    pdf.cell(0, 10, f"Produktionsberater - {genre.upper()}", ln=True)
    pdf.set_font("Helvetica", "", 9)
    normal()
    pdf.cell(0, 6,
             f"BPM: {meta.get('bpm','—')}  |  Tonart: {meta.get('key','—')}  |  "
             f"Takte: {meta.get('total_bars','—')}", ln=True)
    pdf.ln(3)

    def section(title):
        pdf.set_font("Helvetica", "B", 11)
        accent()
        pdf.cell(0, 8, title, ln=True)
        pdf.set_font("Helvetica", "", 9)
        normal()

    def subsection(title):
        pdf.set_font("Helvetica", "B", 9)
        accent()
        pdf.cell(0, 6, title, ln=True)
        pdf.set_font("Helvetica", "", 8)
        normal()

    gs = advisor.get("gain_staging", [])
    if gs:
        section("GAIN STAGING")
        for r in gs:
            pdf.cell(0, 5,
                     f"  {r.get('label', r.get('track',''))}: "
                     f"RMS {r.get('rms','—')} dB  Peak {r.get('peak','—')} dB  "
                     f"Fader {r.get('fader_db','—')} dB", ln=True)
        pdf.ln(2)

    bpm_times = advisor.get("bpm_times", {})
    if bpm_times:
        section("BPM-ZEITWERTE")
        for k, v in bpm_times.items():
            pdf.cell(0, 5, f"  {k}: {v}", ln=True)
        pdf.ln(2)

    chains = advisor.get("effect_chains", {})
    if chains:
        section("EFFEKTKETTEN")
        for track, slots in chains.items():
            subsection(f"  {track.upper()}")
            for s in slots:
                pdf.cell(0, 4,
                         f"    [{s.get('slot','')}] {s.get('effect','')} "
                         f"- {s.get('params','')}", ln=True)
        pdf.ln(2)

    freq = advisor.get("frequency_allocation", [])
    if freq:
        section("FREQUENZALLOKATION")
        for r in freq:
            pdf.cell(0, 5,
                     f"  {r.get('label', r.get('track',''))}: "
                     f"HPF {r.get('hpf','—')}  LPF {r.get('lpf','—')}  "
                     f"Zone: {r.get('zone','—')}", ln=True)
        pdf.ln(2)

    return bytes(pdf.output())
