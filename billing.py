"""
Abrechnung (simuliert).

Bildet den Zahlungsfluss nach, ohne echten Zahlungsdienstleister:

  * Lizenzkauf: sell_license() legt die Lizenz mit Status 'open' an. Der
    simulierte Checkout ruft pay_license() -> Status 'paid'. cancel_license()
    storniert eine offene Bestellung und gibt den Track wieder frei.
  * Abo: create_subscription() legt ein Abo mit Laufzeit als 'open' an,
    pay_subscription() bestaetigt die (simulierte) Zahlung, aktiviert das Abo
    des Nutzers mit Start-/Enddatum und bucht den Umsatz.
  * invoice_context() liefert die Daten fuer die Rechnungs-/Belegansicht
    inkl. Netto/USt/Brutto.

In einem echten Rollout ersetzt ein Zahlungsdienstleister (z.B. Stripe/Mollie)
den simulierten Bestaetigungsschritt; die uebrige Logik bleibt gleich.
"""

from datetime import date, datetime

import config
import database as db


def _today():
    return date.today().isoformat()


def _add_months(iso_start, months):
    """Addiert Monate auf ein ISO-Datum (einfache, robuste Variante)."""
    d = date.fromisoformat(iso_start)
    month_index = d.month - 1 + months
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    # Tag ggf. auf Monatsende begrenzen.
    day = min(d.day, [31, 29 if year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
                      else 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1])
    return date(year, month, day).isoformat()


# --- Umsatzsteuer -----------------------------------------------------------

def vat_breakdown(net):
    """Zerlegt einen Nettobetrag in Netto/USt/Brutto anhand des USt-Satzes."""
    try:
        vat_pct = float(db.get_setting("vat_pct", "19"))
    except ValueError:
        vat_pct = 19.0
    vat = round(net * vat_pct / 100.0, 2)
    return {"net": round(net, 2), "vat_pct": vat_pct, "vat": vat,
            "gross": round(net + vat, 2)}


# --- Lizenz-Zahlung ---------------------------------------------------------

def get_license(license_id):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT l.*, t.title AS track_title, t.genre AS genre "
        "FROM licenses l JOIN tracks t ON t.id = l.track_id WHERE l.id = ?",
        (license_id,),
    ).fetchone()
    conn.close()
    return row


def pay_license(license_id):
    """Bestaetigt die (simulierte) Zahlung einer offenen Lizenz."""
    conn = db.get_conn()
    lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if not lic:
        conn.close()
        return False, "Lizenz nicht gefunden."
    if lic["payment_status"] == "paid":
        conn.close()
        return False, "Diese Lizenz ist bereits bezahlt."
    conn.execute("UPDATE licenses SET payment_status = 'paid', paid_at = ? WHERE id = ?",
                 (datetime.now().isoformat(timespec="seconds"), license_id))
    conn.commit()
    conn.close()
    db.log_event("LICENSE_PAID", "license", license_id, {"price": lic["price"]})
    return True, None


def cancel_license(license_id):
    """Storniert eine OFFENE Lizenz und gibt den Track-Status wieder frei."""
    conn = db.get_conn()
    lic = conn.execute("SELECT * FROM licenses WHERE id = ?", (license_id,)).fetchone()
    if not lic:
        conn.close()
        return False, "Lizenz nicht gefunden."
    if lic["payment_status"] == "paid":
        conn.close()
        return False, "Bezahlte Lizenzen koennen nicht storniert werden."
    track_id = lic["track_id"]
    conn.execute("DELETE FROM licenses WHERE id = ?", (license_id,))
    conn.commit()
    conn.close()
    _recompute_track_status(track_id)
    db.log_event("LICENSE_CANCELLED", "license", license_id, {"track_id": track_id})
    return True, None


def _recompute_track_status(track_id):
    """Setzt den Track-Status anhand der verbliebenen Lizenzen neu."""
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT license_type FROM licenses WHERE track_id = ?", (track_id,)
    ).fetchall()
    types = [r["license_type"] for r in rows]
    if "exclusive" in types:
        status = "exclusive_sold"
    elif types:
        status = "leased"
    else:
        status = "available"
    conn.execute("UPDATE tracks SET status = ? WHERE id = ?", (status, track_id))
    conn.commit()
    conn.close()


# --- Abo-Zahlung ------------------------------------------------------------

def subscription_price(term_months):
    try:
        per_month = float(db.get_setting("sub_price_month", "9.99"))
    except ValueError:
        per_month = 9.99
    return round(per_month * term_months, 2)


def create_subscription(user_id, term_months):
    """Legt ein Abo (Status 'open') mit Laufzeit an. Gibt subscription_id zurueck."""
    if term_months not in config.SUBSCRIPTION_TERMS:
        return None, "Ungueltige Laufzeit."
    price = subscription_price(term_months)
    start = _today()
    end = _add_months(start, term_months)
    conn = db.get_conn()
    cur = conn.execute(
        "INSERT INTO subscriptions (user_id, term_months, price, status, "
        "start_date, end_date, created_at) VALUES (?, ?, ?, 'open', ?, ?, ?)",
        (user_id, term_months, price, start, end,
         datetime.now().isoformat(timespec="seconds")),
    )
    sub_id = cur.lastrowid
    conn.commit()
    conn.close()
    db.log_event("SUBSCRIPTION_ORDERED", "subscription", sub_id,
                 {"user_id": user_id, "term_months": term_months, "price": price})
    return sub_id, None


def get_subscription(sub_id):
    conn = db.get_conn()
    row = conn.execute(
        "SELECT s.*, u.name AS user_name, u.email AS user_email "
        "FROM subscriptions s JOIN users u ON u.id = s.user_id WHERE s.id = ?",
        (sub_id,),
    ).fetchone()
    conn.close()
    return row


def pay_subscription(sub_id):
    """Bestaetigt die (simulierte) Abo-Zahlung und aktiviert das Abo."""
    conn = db.get_conn()
    sub = conn.execute("SELECT * FROM subscriptions WHERE id = ?", (sub_id,)).fetchone()
    if not sub:
        conn.close()
        return False, "Abo nicht gefunden."
    if sub["status"] == "paid":
        conn.close()
        return False, "Dieses Abo ist bereits bezahlt."
    conn.execute("UPDATE subscriptions SET status = 'paid', paid_at = ? WHERE id = ?",
                 (datetime.now().isoformat(timespec="seconds"), sub_id))
    # Nutzer als aktiven Abonnenten mit Laufzeit setzen.
    conn.execute(
        "UPDATE users SET is_subscriber = 1, sub_start = ?, sub_end = ? WHERE id = ?",
        (sub["start_date"], sub["end_date"], sub["user_id"]),
    )
    conn.commit()
    conn.close()
    db.log_event("SUBSCRIPTION_PAID", "subscription", sub_id,
                 {"user_id": sub["user_id"], "price": sub["price"],
                  "until": sub["end_date"]})
    return True, None


# --- Rechnungsdaten ---------------------------------------------------------

def invoice_context(kind, obj):
    """
    Baut die generischen Rechnungsdaten fuer die Ansicht.
    kind: 'license' oder 'subscription'. obj: der jeweilige DB-Row.
    """
    seller = db.get_setting("seller_name", "SBS Sound Studio")
    if kind == "license":
        tier = config.DEFAULT_TIERS.get(obj["tier"], {})
        desc = f"Lizenz: {obj['track_title']} — {tier.get('label', obj['tier'])}"
        buyer = obj["buyer_name"] or "Gast"
        net = obj["price"]
        list_price = obj["list_price"] if obj["list_price"] is not None else obj["price"]
        discount_pct = obj["discount_pct"] or 0
        number = f"L-{obj['id']:05d}"
        status = obj["payment_status"]
        dt = obj["paid_at"] or obj["sold_at"]
    else:
        desc = f"Abo — Laufzeit {obj['term_months']} Monat(e) ({obj['start_date']} bis {obj['end_date']})"
        buyer = obj["user_name"]
        net = obj["price"]
        list_price = obj["price"]
        discount_pct = 0
        number = f"A-{obj['id']:05d}"
        status = obj["status"]
        dt = obj["paid_at"] or obj["created_at"]

    v = vat_breakdown(net)
    return {
        "seller": seller,
        "number": number,
        "kind": kind,
        "desc": desc,
        "buyer": buyer,
        "list_price": list_price,
        "discount_pct": discount_pct,
        "status": status,
        "date": dt,
        **v,
    }
