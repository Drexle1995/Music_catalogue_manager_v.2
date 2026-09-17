"""
Abo-/Freemium-Logik: Nutzerverwaltung, Nutzungszaehlung und Tageslimit.

Das Tageslimit wird ueber die Tabelle 'generations' gezaehlt (eine Zeile je
erzeugtem Track). Abonnenten haben ein hoeheres Limit als Basis-Nutzer.
Beide Limits sind in den Einstellungen konfigurierbar.
"""

from datetime import date, datetime

from db import database as db


# --- Nutzer -----------------------------------------------------------------

def list_users():
    conn = db.get_conn()
    rows = conn.execute("SELECT * FROM users ORDER BY name").fetchall()
    conn.close()
    return rows


def get_user(user_id):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
    conn.close()
    return row


def get_user_by_name(name):
    conn = db.get_conn()
    row = conn.execute("SELECT * FROM users WHERE name = ?", (name,)).fetchone()
    conn.close()
    return row


def add_user(name, email=None, is_subscriber=False):
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO users (name, email, is_subscriber, created_at) VALUES (?, ?, ?, ?)",
        (name, email or None, 1 if is_subscriber else 0,
         datetime.now().isoformat(timespec="seconds")),
    )
    uid = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_event("USER_ADDED", "user", uid,
                 {"name": name, "is_subscriber": bool(is_subscriber)})
    return uid


def set_subscriber(user_id, is_subscriber):
    conn = db.get_conn()
    conn.execute("UPDATE users SET is_subscriber = ? WHERE id = ?",
                 (1 if is_subscriber else 0, user_id))
    conn.commit()
    conn.close()
    db.log_event("SUBSCRIPTION_CHANGED", "user", user_id,
                 {"is_subscriber": bool(is_subscriber)})


# --- Limits & Nutzung -------------------------------------------------------

def is_active_subscriber(user):
    """True, wenn der Nutzer ein Abo hat, dessen Laufzeit nicht abgelaufen ist."""
    if not user or not user["is_subscriber"]:
        return False
    end = user["sub_end"] if "sub_end" in user.keys() else None
    return (not end) or (end >= date.today().isoformat())


def has_subscription(user):
    """
    Einheitliche Abo-Pruefung fuer die Token-Preise.
    Beruecksichtigt beide Abo-Kennzeichen der Anwendung:
      * Admin-/Billing-Abo: is_subscriber = 1 mit gueltiger Laufzeit (sub_end)
      * Web-Tarif:          users.tier = 'pro'
    """
    if not user:
        return False
    tier = user["tier"] if "tier" in user.keys() else None
    return tier == "pro" or is_active_subscriber(user)


def daily_limit(user):
    """Liefert das Tageslimit fuer einen Nutzer (aktives Abo vs. Basis)."""
    if is_active_subscriber(user):
        return int(db.get_setting("limit_subscriber", "10"))
    return int(db.get_setting("limit_free", "3"))


def used_today(user_id, on_day=None):
    """
    Zaehlt die heute (lokales Datum) BEZOGENEN Tracks eines Nutzers:
    Generierungen + gekaufte Lizenzen teilen sich denselben Tages-Topf.
    Stornierte (geloeschte) Lizenzen fallen automatisch wieder heraus.
    """
    day = (on_day or date.today()).isoformat()
    conn = db.get_conn()
    gens = conn.execute(
        "SELECT COUNT(*) c FROM generations "
        "WHERE user_id = ? AND substr(created_at, 1, 10) = ?",
        (user_id, day),
    ).fetchone()["c"]
    lics = conn.execute(
        "SELECT COUNT(*) c FROM licenses "
        "WHERE buyer_user_id = ? AND substr(sold_at, 1, 10) = ?",
        (user_id, day),
    ).fetchone()["c"]
    conn.close()
    return gens + lics


def quota_status(user):
    """Gibt limit / used / remaining fuer die Anzeige zurueck."""
    from commerce import tokens  # lokaler Import vermeidet Zirkelbezug
    limit = daily_limit(user)
    used = used_today(user["id"])
    return {"limit": limit, "used": used, "remaining": max(limit - used, 0),
            "tokens": tokens.balance(user["id"])}


def check_quota(user, count=1):
    """
    Prueft, ob 'count' weitere Generierungen heute erlaubt sind.
    Gibt (allowed: bool, status: dict) zurueck.
    """
    status = quota_status(user)
    status["requested"] = count
    allowed = count <= status["remaining"]
    return allowed, status


def record_generation(user_id, source=None, count=1):
    """Traegt 'count' Generierungen fuer den Nutzer ein (Nutzungsprotokoll)."""
    conn = db.get_conn()
    now = datetime.now().isoformat(timespec="seconds")
    for _ in range(count):
        conn.execute(
            "INSERT INTO generations (user_id, source, created_at) VALUES (?, ?, ?)",
            (user_id, source, now),
        )
    conn.commit()
    conn.close()
