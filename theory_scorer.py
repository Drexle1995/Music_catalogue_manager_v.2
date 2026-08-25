"""
theory_scorer.py — Theorie-Pruefung mit MA-V7-BDRA-Validierungslogik.

Delegiert an bdra_rules.validate_selection() aus dem MUSIC_ARCHITECT_V7-Projekt.
Die fuenf Prinzipien (P1-P5) entsprechen den psychoakustischen Regeln aus MA-V7:

  P1 — Sub-Bass-Exklusivitaet (kritische Bandmaskierung unter 80 Hz)
  P2 — Register-Monotonie     (Bass <= Akkorde <= Melodie <= Arp)
  P3 — Attack-Kontrast        (Transientenstau bei gleicher Lage und Attack)
  P4 — Dichte-Budget          (Σ D aller Spuren unter Branch-Schwellwert)
  P5 — Helligkeits-Kontrast   (Melodie B > Bass B fuer Durchsetzungsvermoegen)

Plattformunabhaengig — pathlib, kein Tkinter, keine OS-spezifischen APIs.
"""

from __future__ import annotations

import pathlib
import sys
from typing import Any, Dict

# Pfad zum MA-V7-Quellverzeichnis (relativ zu dieser Datei berechnet).
_MA_ROOT = pathlib.Path(__file__).parent.parent / "MUSIC_ARCHITECT_V7"
_MA_SRC  = _MA_ROOT / "src"


def _ensure_ma_path() -> None:
    """Fuegt MA-V7-Pfade zu sys.path hinzu (idempotent)."""
    for p in (str(_MA_ROOT), str(_MA_SRC)):
        if p not in sys.path:
            sys.path.insert(0, p)


# Mapping Web-Frontend-Schluessel → MA-V7-interne Track-Bezeichnung.
# 'lead' heisst in MA-V7 'melody'; 'pad' heisst 'pads'.
_WEB_TO_MA: Dict[str, str] = {
    'lead': 'melody',
    'pad':  'pads',
}

# Tracks, die fuer den BDRA-Score nicht relevant sind (kein BDRA-Code).
_SKIP_TRACKS = frozenset({'drums', 'percussion'})

# Tracks, die nur zum Dichte-Budget (P4) beitragen, nicht zu P3.
# Entspricht dem density_extra-Mechanismus in MA-V7 (instrument_builder.py).
_DENSITY_ONLY = frozenset({'texture', 'fx'})

# Deutschen Bewertungsbezeichnungen (MA-V7 gibt Englisch aus).
_GRADE_DE: Dict[str, str] = {
    'EXCELLENT':  'EXZELLENT',
    'GOOD':       'GUT',
    'ACCEPTABLE': 'BEFRIEDIGEND',
    'WARNING':    'VERBESSERUNGSBEDARF',
}

# Deutsche Prinzip-Kurznamen fuer die UI-Labels.
PRINCIPLE_LABELS_DE: Dict[str, str] = {
    'P1': 'Sub-Bass',
    'P2': 'Register',
    'P3': 'Attack',
    'P4': 'Dichte',
    'P5': 'Helligkeit',
}

# Beschreibung des bestandenen Zustands (wird angezeigt wenn kein Fehler vorliegt).
_PASS_DETAIL_DE: Dict[str, str] = {
    'P1': 'Maximal eine Quelle im Sub-Bass-Bereich (D=0, R=0) — kein Kammfiltereffekt.',
    'P2': 'Register steigen korrekt an: Bass ≤ Akkorde ≤ Melodie ≤ Arp.',
    'P3': 'Stimmen mit gleicher Lage haben unterschiedliche Huellenzeiten — kein Transientenstau.',
    'P4': 'Gesamt-Dichte Σ D innerhalb des Branch-Budgets — kein Spektralschlamm.',
    'P5': 'Melodie B > Bass B — Fuehrstimme setzt sich ohne EQ durch.',
}


def score_instruments(
    branch:      str,
    instruments: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Prueft eine Instrumentenwahl gegen die fuenf psychoakustischen Prinzipien.

    Parameter
    ----------
    branch      : 'A', 'B' oder 'C' — aus dem branch-Feld der gewaehlten Palette.
                  Bestimmt Branch-Regeln und Dichte-Budget.
    instruments : {web_track_key: {'code': 'B? D? A? R?'}}
                  Web-Schluessel ('lead', 'pad') werden automatisch in MA-V7-
                  Bezeichnungen ('melody', 'pads') umgewandelt.

    Rueckgabe
    ---------
    {
      'score':    int (0-100),
      'grade':    str,
      'checks':   { 'p1': {label, pass, partial, detail}, ..., 'p5': {...} },
      'feedback': str,
    }
    """
    try:
        _ensure_ma_path()
        from src.composition import bdra_rules as br  # type: ignore

        # BDRA-Auswahl und Dichte-Extra aufbauen.
        selection:     Dict[str, str] = {}
        density_extra: int            = 0

        for web_key, instr in instruments.items():
            if web_key in _SKIP_TRACKS:
                continue
            code = (instr.get('code') or '') if isinstance(instr, dict) else ''
            if not code:
                continue
            ma_key = _WEB_TO_MA.get(web_key, web_key)
            if web_key in _DENSITY_ONLY:
                # Texture und FX fliessen nur in den Dichte-Check (P4) ein.
                density_extra += br.parse_bdra(code).get('D', 0)
            else:
                selection[ma_key] = code

        branch = branch if branch in ('A', 'B', 'C') else 'A'
        result = br.validate_selection(branch, selection, density_extra=density_extra)

        # Verletzungs- und Warnungsmeldungen nach Prinzip-ID aufschluesseln.
        # Meldungen beginnen mit der Prinzip-ID (z.B. "P3 Attack: ...").
        msg_by_p: Dict[str, str] = {}
        for msg in result.violations + result.warnings:
            for pid in ('P1', 'P2', 'P3', 'P4', 'P5'):
                if msg.startswith(pid):
                    msg_by_p.setdefault(pid, msg)
                    break

        # Branch-Verletzungen (P0) gesondert sammeln fuer Feedback-Text.
        branch_violations = [m for m in result.violations if m.startswith('P0')]

        # Checks-Dict fuer das Frontend aufbauen.
        checks: Dict[str, Dict[str, Any]] = {}
        for pid in ('P1', 'P2', 'P3', 'P4', 'P5'):
            status = result.principles.get(pid, 'pass')
            if status == 'pass':
                detail = _PASS_DETAIL_DE[pid]
            else:
                detail = msg_by_p.get(pid, _PASS_DETAIL_DE[pid])
            checks[pid.lower()] = {
                'label':   PRINCIPLE_LABELS_DE[pid],
                'pass':    status == 'pass',
                'partial': status == 'warn',
                'detail':  detail,
            }

        grade = _GRADE_DE.get(result.label, result.label)

        # Feedback: wichtigste Verletzung zuerst, dann Warnungen, dann Branch-Fehler.
        p_violations = [m for m in result.violations if not m.startswith('P0')]
        feedback = (
            p_violations[0]      if p_violations      else
            result.warnings[0]   if result.warnings    else
            branch_violations[0] if branch_violations  else
            f'Alle Theorie-Regeln erfuellt (Branch {branch})'
        )

        return {
            'score':    result.score,
            'grade':    grade,
            'checks':   checks,
            'feedback': feedback,
        }

    except Exception:
        return _fallback()


def _fallback() -> Dict[str, Any]:
    """Neutrales Ergebnis wenn MA-V7 nicht geladen werden kann."""
    leere_pruefung = {
        'label': '—', 'pass': False, 'partial': True,
        'detail': 'MA-V7-Bibliothek nicht erreichbar.',
    }
    return {
        'score':    0,
        'grade':    'FEHLER',
        'checks':   {p: dict(leere_pruefung) for p in ('p1', 'p2', 'p3', 'p4', 'p5')},
        'feedback': 'Theorie-Pruefung nicht verfuegbar — MA-V7-Bibliothek fehlt.',
    }
