"""
Gateway / Wrapper fuer die Track-Generierung.

Dies ist der Durchsetzungspunkt des Tageslimits: Der Gateway prueft ZUERST das
Kontingent des Nutzers und ruft ERST DANN Music Architect auf. Reicht das
Kontingent nicht, wird die Differenz mit gekauften Tokens gedeckt; scheitert
die Generierung danach, werden die Tokens automatisch erstattet. Der Code des
Partnerprojekts bleibt dadurch vollstaendig unangetastet -- er wird nur als
externer Prozess gestartet.

Zwei Betriebsarten:
  * Echtbetrieb  : fuehrt den in den Einstellungen hinterlegten Befehl
                   (music_architect_cmd) via subprocess aus.
  * Simulation   : ist kein Befehl hinterlegt (oder --simulate gesetzt), erzeugt
                   der Gateway selbst wasserzeichenmarkierte Demo-MIDIs, damit der
                   gesamte Freemium-Ablauf ohne das echte Programm vorfuehrbar ist.

CLI:
    python -m commerce.gateway --user "Abo-Kunde (Demo)" --count 4
    python -m commerce.gateway --user 2 --count 5 --simulate
"""

import argparse
import hashlib
import os
import shlex
import subprocess
import sys
from datetime import datetime

import config
from db import database as db
from commerce import quota
from commerce import tokens


def _simulate_generation(count, catalog_dir):
    """Erzeugt 'count' echte wasserzeichenmarkierte Demo-MIDIs (Simulation)."""
    try:
        import mido
    except ImportError:
        return []
    os.makedirs(catalog_dir, exist_ok=True)
    created = []
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    for i in range(count):
        genre_dir = os.path.join(catalog_dir, "generated")
        os.makedirs(genre_dir, exist_ok=True)
        fname = f"gen_{stamp}_{i+1:03d}.mid"
        path = os.path.join(genre_dir, fname)
        file_hash = hashlib.sha256(fname.encode("utf-8")).hexdigest()

        midi = mido.MidiFile()
        meta = mido.MidiTrack()
        meta.append(mido.MetaMessage(
            "copyright",
            text="(C) 2026 MUSIC_ARCHITECT_V7 - AUTHORIZED_COMMERCIAL_SYNC_ASSET_CLASS_A",
            time=0))
        meta.append(mido.MetaMessage("text", text=f"WM_HASH:{file_hash}", time=0))
        midi.tracks.append(meta)
        notes = mido.MidiTrack()
        for pitch in (60, 63, 67):
            notes.append(mido.Message("note_on", note=pitch, velocity=72, time=0))
            notes.append(mido.Message("note_off", note=pitch, velocity=0, time=240))
        midi.tracks.append(notes)
        midi.save(path)
        created.append(path)
    return created


def run_generation(user_id, count=1, simulate=None):
    """
    Zentrale Funktion (von CLI UND Weboberflaeche genutzt).
    Prueft das Limit und fuehrt dann die Generierung aus.

    Rueckgabe: dict mit Ergebnis/Status. 'ok' = True/False.
    """
    user = quota.get_user(user_id)
    if not user:
        return {"ok": False, "error": "Nutzer nicht gefunden."}

    if count < 1:
        return {"ok": False, "error": "Anzahl muss mindestens 1 sein."}

    allowed, status = quota.check_quota(user, count)
    tokens_needed = 0
    token_ref = None
    if not allowed:
        # Kontingent reicht nicht: Differenz ueber Tokens abdecken.
        tokens_needed = count - status["remaining"]
        token_ref = f"gateway:{user_id}:{datetime.now().isoformat(timespec='seconds')}"
        if not tokens.consume(user_id, tokens_needed, reference=token_ref):
            offer = tokens.price_for(user_id)
            balance = tokens.balance(user_id)
            return {
                "ok": False,
                "error": (f"Kontingent reicht nicht. {user['name']} hat heute "
                          f"{status['used']}/{status['limit']} Tracks erzeugt "
                          f"(noch {status['remaining']} moeglich, {count} angefragt). "
                          f"Benoetigt: {tokens_needed} Token(s), Guthaben: {balance}. "
                          f"Token-Preis: {tokens.fmt_eur(offer['unit_price'])} "
                          f"({'Abo' if offer['group'] == 'subscriber' else 'Basis'})."),
                "status": status,
                "user": user["name"],
                "tokens_needed": tokens_needed,
                "token_balance": balance,
            }

    def _fail(payload):
        # Fehlgeschlagene Laeufe verbrauchen weder Kontingent noch Tokens.
        if tokens_needed:
            tokens.refund(user_id, tokens_needed, reference=token_ref)
        payload.setdefault("ok", False)
        return payload

    cmd_template = db.get_setting("music_architect_cmd", "") or ""
    catalog_dir = db.get_setting("catalog_dir", config.DEFAULT_CATALOG_DIR)

    use_sim = simulate if simulate is not None else (cmd_template.strip() == "")
    mode = "simulation" if use_sim else "real"
    produced = []

    if use_sim:
        produced = _simulate_generation(count, catalog_dir)
        if not produced:
            return _fail({"error": "Simulation fehlgeschlagen (mido nicht verfuegbar)."})
    else:
        # Echtbetrieb: externen Befehl ausfuehren. Platzhalter ersetzen.
        cmd = cmd_template.replace("{count}", str(count)).replace(
            "{user}", str(user_id))
        try:
            result = subprocess.run(shlex.split(cmd), capture_output=True,
                                    text=True, timeout=600)
        except Exception as exc:
            return _fail({"error": f"Aufruf von Music Architect fehlgeschlagen: {exc}"})
        if result.returncode != 0:
            return _fail({"error": f"Music Architect endete mit Fehlercode {result.returncode}.",
                          "stderr": result.stderr[-500:]})

    # Erst nach erfolgreicher Generierung das Kontingent verbuchen.
    quota.record_generation(user_id, source=f"{mode}:{count}", count=count)
    new_status = quota.quota_status(user)

    db.log_event("GENERATION", "user", user_id,
                 {"mode": mode, "count": count, "tokens_used": tokens_needed,
                  "used_today": new_status["used"], "limit": new_status["limit"]})

    return {
        "ok": True,
        "mode": mode,
        "count": count,
        "produced": produced,
        "status": new_status,
        "user": user["name"],
        "tokens_used": tokens_needed,
    }


def _main(argv=None):
    parser = argparse.ArgumentParser(description="Gateway fuer Track-Generierung mit Tageslimit.")
    parser.add_argument("--user", required=True, help="Nutzer-ID oder exakter Name")
    parser.add_argument("--count", type=int, default=1, help="Anzahl Tracks (Standard 1)")
    parser.add_argument("--simulate", action="store_true", help="Simulationsmodus erzwingen")
    args = parser.parse_args(argv)

    db.init_db()

    # Nutzer per ID oder Name aufloesen.
    user = None
    if args.user.isdigit():
        user = quota.get_user(int(args.user))
    if user is None:
        user = quota.get_user_by_name(args.user)
    if user is None:
        print(f"FEHLER: Nutzer '{args.user}' nicht gefunden.", file=sys.stderr)
        return 2

    res = run_generation(user["id"], count=args.count,
                         simulate=True if args.simulate else None)
    if res["ok"]:
        print(f"OK [{res['mode']}]: {res['count']} Track(s) fuer {res['user']} erzeugt. "
              f"Heute {res['status']['used']}/{res['status']['limit']} "
              f"(noch {res['status']['remaining']}). "
              f"Tokens verbraucht: {res['tokens_used']}, Guthaben: {res['status']['tokens']}.")
        return 0
    else:
        print(f"ABGELEHNT: {res['error']}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(_main())
