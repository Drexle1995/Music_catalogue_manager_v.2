"""
Token-Nachkauf: Generierung ueber das Kontingent hinaus.

Ist das Tages- bzw. Monatskontingent eines Nutzers aufgebraucht, kann er
Tokens kaufen. Jede weitere Generierung/Speicherung verbraucht dann 1 Token.

Datenmodell (siehe db/database.py):
  * token_purchases : Bestellungen (open -> paid | cancelled), Preise eingefroren.
  * token_ledger    : Buchungsjournal. Kontostand = SUM(delta).

Preislogik:
  * Abonnenten zahlen 'token_price_subscriber', alle anderen 'token_price_basic'.
  * Die Einstellungen erzwingen: Abo-Preis < Basis-Preis (validate_prices).

Nebenlaeufigkeit:
  Abbuchung und Gutschrift laufen in 'BEGIN IMMEDIATE'-Transaktionen. SQLite
  vergibt dabei sofort die Schreibsperre, sodass zwei parallele Requests nicht
  denselben Token doppelt ausgeben oder eine Bestellung doppelt gutschreiben.
"""

from datetime import datetime

import config
from db import database as db
from commerce import quota


class TokenError(Exception):
    pass


def _now():
    return datetime.now().isoformat(timespec="seconds")


# --- Preise -----------------------------------------------------------------

def fmt_eur(value):
    """1234.5 -> '1.234,50 €' (deutsches Zahlenformat fuer Meldungen/Belege)."""
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")


def _float_setting(key):
    try:
        return float(db.get_setting(key, config.DEFAULT_TOKENS[key]))
    except (TypeError, ValueError):
        return float(config.DEFAULT_TOKENS[key])


def get_prices():
    """Aktuelle Netto-Stueckpreise: {'basic': x, 'subscriber': y}."""
    return {
        "basic": _float_setting("token_price_basic"),
        "subscriber": _float_setting("token_price_subscriber"),
    }


def validate_prices(basic, subscriber):
    """Gibt eine Fehlermeldung zurueck oder None, wenn die Preise gueltig sind."""
    try:
        basic = float(basic)
        subscriber = float(subscriber)
    except (TypeError, ValueError):
        return "Token-Preise muessen Zahlen sein."
    if basic <= 0 or subscriber <= 0:
        return "Token-Preise muessen groesser als 0 sein."
    if subscriber >= basic:
        return ("Der Token-Preis fuer Abonnenten muss unter dem Basis-Preis liegen "
                f"(aktuell {fmt_eur(subscriber)} ≥ {fmt_eur(basic)}).")
    return None


def price_for(user_id):
    """
    Liefert das Preisangebot fuer einen Nutzer:
    {'group': 'subscriber'|'basic', 'unit_price': x, 'list_unit_price': y}
    """
    user = quota.get_user(user_id)
    prices = get_prices()
    if quota.has_subscription(user):
        # min() als Sicherheitsnetz, falls die DB manuell falsch befuellt wurde.
        unit = min(prices["subscriber"], prices["basic"])
        return {"group": "subscriber", "unit_price": unit,
                "list_unit_price": prices["basic"]}
    return {"group": "basic", "unit_price": prices["basic"],
            "list_unit_price": prices["basic"]}


# --- Kontostand & Journal ---------------------------------------------------

def balance(user_id):
    conn = db.get_conn()
    value = conn.execute(
        "SELECT COALESCE(SUM(delta), 0) AS b FROM token_ledger WHERE user_id = ?",
        (user_id,),
    ).fetchone()["b"]
    conn.close()
    return int(value)


def list_ledger(user_id, limit=20):
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT * FROM token_ledger WHERE user_id = ? ORDER BY id DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    conn.close()
    return rows


def consume(user_id, amount=1, reference=None):
    """
    Bucht 'amount' Tokens ab, sofern das Guthaben reicht.
    Pruefung und Abbuchung passieren in EINEM Statement unter Schreibsperre.
    Gibt True bei Erfolg zurueck, sonst False (nichts wird gebucht).
    """
    if amount <= 0:
        return True
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        cur = conn.execute(
            "INSERT INTO token_ledger (user_id, delta, reason, reference, created_at) "
            "SELECT ?, ?, 'consume', ?, ? "
            "WHERE (SELECT COALESCE(SUM(delta), 0) FROM token_ledger "
            "       WHERE user_id = ?) >= ?",
            (user_id, -amount, reference, _now(), user_id, amount),
        )
        ok = cur.rowcount == 1
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    if ok:
        db.log_event("TOKEN_CONSUMED", "user", user_id,
                     {"amount": amount, "reference": reference})
    return ok


def refund(user_id, amount=1, reference=None):
    """Erstattet Tokens, z.B. wenn die Generierung nach der Abbuchung scheitert."""
    if amount <= 0:
        return
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO token_ledger (user_id, delta, reason, reference, created_at) "
        "VALUES (?, ?, 'refund', ?, ?)",
        (user_id, amount, reference, _now()),
    )
    conn.commit()
    conn.close()
    db.log_event("TOKEN_REFUNDED", "user", user_id,
                 {"amount": amount, "reference": reference})


def admin_adjust(user_id, amount, admin_id=None):
    """Manuelle Gut-/Lastschrift durch einen Admin (z.B. Kulanz)."""
    amount = int(amount)
    if amount == 0:
        raise TokenError("Betrag darf nicht 0 sein.")
    if amount < 0 and balance(user_id) + amount < 0:
        raise TokenError("Das Guthaben darf nicht negativ werden.")
    conn = db.get_conn()
    conn.execute(
        "INSERT INTO token_ledger (user_id, delta, reason, reference, created_at) "
        "VALUES (?, ?, 'admin', ?, ?)",
        (user_id, amount, f"admin:{admin_id}" if admin_id else "admin", _now()),
    )
    conn.commit()
    conn.close()
    db.log_event("TOKEN_ADJUSTED", "user", user_id,
                 {"amount": amount, "admin_id": admin_id})


# --- Bestellungen -----------------------------------------------------------

MAX_QUANTITY = 1000


def create_purchase(user_id, quantity):
    """Legt eine offene Token-Bestellung an. Rueckgabe: (purchase_id, error)."""
    try:
        quantity = int(quantity)
    except (TypeError, ValueError):
        return None, "Ungueltige Anzahl."
    if not 1 <= quantity <= MAX_QUANTITY:
        return None, f"Bitte zwischen 1 und {MAX_QUANTITY} Tokens waehlen."
    if not quota.get_user(user_id):
        return None, "Nutzer nicht gefunden."

    offer = price_for(user_id)
    total = round(offer["unit_price"] * quantity, 2)
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO token_purchases (user_id, quantity, price_group, unit_price, "
        "list_unit_price, price, status, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, 'open', ?)",
        (user_id, quantity, offer["group"], offer["unit_price"],
         offer["list_unit_price"], total, _now()),
    )
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_event("TOKENS_ORDERED", "token_purchase", pid,
                 {"user_id": user_id, "quantity": quantity,
                  "price_group": offer["group"], "price": total})
    return pid, None


def get_purchase(purchase_id):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT p.*, u.name AS user_name, u.email AS user_email "
        "FROM token_purchases p JOIN users u ON u.id = p.user_id WHERE p.id = ?",
        (purchase_id,),
    ).fetchone()
    conn.close()
    return row


def list_purchases(user_id=None, limit=50):
    conn = db.get_conn()
    if user_id is None:
        rows = conn.execute(
            "SELECT p.*, u.name AS user_name FROM token_purchases p "
            "JOIN users u ON u.id = p.user_id ORDER BY p.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM token_purchases WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
    conn.close()
    return rows


def pay_purchase(purchase_id):
    """
    Bestaetigt die (simulierte) Zahlung und schreibt die Tokens gut.
    Statuswechsel und Gutschrift sind eine Transaktion -> keine Doppelgutschrift.
    """
    conn = db.get_conn()
    try:
        conn.execute("BEGIN IMMEDIATE")
        p = conn.execute("SELECT * FROM token_purchases WHERE id = ?",
                         (purchase_id,)).fetchone()
        if not p:
            conn.rollback()
            return False, "Bestellung nicht gefunden."
        if p["status"] != "open":
            conn.rollback()
            return False, ("Diese Bestellung ist bereits bezahlt."
                           if p["status"] == "paid" else "Diese Bestellung wurde storniert.")
        now = _now()
        conn.execute(
            "UPDATE token_purchases SET status = 'paid', paid_at = ? "
            "WHERE id = ? AND status = 'open'",
            (now, purchase_id),
        )
        conn.execute(
            "INSERT INTO token_ledger (user_id, delta, reason, purchase_id, created_at) "
            "VALUES (?, ?, 'purchase', ?, ?)",
            (p["user_id"], p["quantity"], purchase_id, now),
        )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    db.log_event("TOKENS_PAID", "token_purchase", purchase_id,
                 {"user_id": p["user_id"], "quantity": p["quantity"], "price": p["price"]})
    return True, None


def cancel_purchase(purchase_id):
    """Storniert eine OFFENE Bestellung (bezahlte Tokens bleiben unberuehrt)."""
    conn = db.get_conn()
    cur = conn.execute(
        "UPDATE token_purchases SET status = 'cancelled' WHERE id = ? AND status = 'open'",
        (purchase_id,),
    )
    conn.commit()
    conn.close()
    if cur.rowcount != 1:
        return False, "Nur offene Bestellungen koennen storniert werden."
    db.log_event("TOKENS_CANCELLED", "token_purchase", purchase_id, None)
    return True, None
