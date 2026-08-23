"""
synth_core_fix.py — Sichert den Python-Fallback wenn synth_core.SynthCore fehlt.

synth_core existiert in diesem Projekt als leeres Namespace-Package (kein
kompiliertes .pyd / .so). builtin_synthesizer.py setzt _CPP_AVAILABLE=True
sobald 'import synth_core' gelingt — prueft aber nicht ob SynthCore auch
wirklich als Klasse vorhanden ist.

Loesung: Wir installieren einen Meta-Path-Finder, der kuenftige
'import synth_core'-Anweisungen mit ImportError blockiert.
builtin_synthesizer.py setzt dann _CPP_AVAILABLE=False und verwendet
automatisch den reinen Python-Renderer (kein Absturz).

Plattformunabhaengig — nur Standard-Python-Bibliotheken.
"""
from __future__ import annotations

import sys
from typing import Optional, Sequence


class _SynthCoreBlocker:
    """
    Meta-Path-Finder und -Loader, der 'import synth_core' mit ImportError
    blockiert, solange kein kompiliertes SynthCore verfuegbar ist.
    Implementiert die alte find_module/load_module-Schnittstelle, die
    in allen Python-3-Versionen stabil funktioniert.
    """

    def find_module(self, fullname: str, path: Optional[Sequence] = None):
        """Greift nur fuer synth_core-Importe ein."""
        if fullname == "synth_core":
            return self
        return None

    def load_module(self, fullname: str):
        """Wirft ImportError — builtin_synthesizer setzt _CPP_AVAILABLE=False."""
        raise ImportError(
            "synth_core ist als Namespace-Package vorhanden, "
            "aber SynthCore wurde nicht kompiliert. "
            "Reiner Python-Renderer wird verwendet."
        )


def ensure_python_fallback() -> None:
    """
    Prueft ob synth_core.SynthCore als kompilierte Klasse vorhanden ist.
    Falls nicht: entfernt das Namespace-Package aus dem Modul-Cache und
    installiert einen Import-Blocker, damit builtin_synthesizer._CPP_AVAILABLE
    korrekt auf False gesetzt wird.

    Idempotent — kann mehrfach aufgerufen werden.
    Muss VOR dem Import von rendering.wav_renderer aufgerufen werden.
    """
    # Bereits ein Blocker installiert? Nichts tun.
    if any(isinstance(f, _SynthCoreBlocker) for f in sys.meta_path):
        return

    try:
        import synth_core as _sc  # type: ignore
        if hasattr(_sc, "SynthCore"):
            # Kompilierte Extension vorhanden — kein Eingriff noetig.
            return
        # Namespace-Package ohne SynthCore: aus Cache entfernen.
        sys.modules.pop("synth_core", None)
    except ImportError:
        pass  # Schon nicht importierbar — Blocker trotzdem eintragen

    # Blocker an erste Position setzen, damit er vor Namespace-Package-Finder greift.
    sys.meta_path.insert(0, _SynthCoreBlocker())
