"""
Lizenzlogik -- Kern des kaufmaennischen Prozesses.

Zentrale Regel (Exklusiv-Sperre):
  * Ein Track, der bereits EXKLUSIV verkauft wurde, darf weder erneut exklusiv
    noch als Lease verkauft werden. Genau hier verbindet sich der IP-Schutz
    (Wasserzeichen) mit einem echten Geschaeftsprozess.
  * Nicht-exklusive Lizenzen (Leases) duerfen mehrfach verkauft werden.
  * Beim Exklusivverkauf wird gewarnt, falls bereits Leases existieren
    (der Verkauf ist erlaubt, die Info wird aber protokolliert).

Jede erfolgreiche Transaktion wird im Audit-Protokoll festgehalten.
"""

from datetime import date, datetime

import config
from db import database as db
from commerce import quota


class LicenseError(Exception):
    """Wird geworfen, wenn ein Verkauf gegen die Geschaeftsregeln verstoesst."""


def _tier_kind(tier):
    return config.DEFAULT_TIERS.get(tier, {}).get("kind", "lease")


def get_price(tier):
    """Aktueller Preis einer Stufe (aus den Einstellungen, sonst Standard)."""
    stored = db.get_setting(f"price_{tier}")
    if stored is not None:
        try:
            return float(stored)
        except ValueError:
            pass
    return config.DEFAULT_TIERS.get(tier, {}).get("price", 0.0)


def sell_license(track_id, tier, buyer_name="", buyer_email="", notes="",
                 price=None, user_id=None):
    """
    Verkauft eine Lizenz. Prueft die Exklusiv-Sperre, wendet ggf. den
    Abo-Rabatt an, schreibt den Datensatz, aktualisiert den Track-Status und
    protokolliert alles.

    Ist ein 'user_id' angegeben und dieser Nutzer Abonnent, wird automatisch
    der konfigurierte Rabatt (Standard 5 %) auf den Listenpreis gewaehrt.

    Gibt bei Erfolg (license_id, warning) zurueck; wirft sonst LicenseError.
    """
    if tier not in config.DEFAULT_TIERS:
        raise LicenseError(f"Unbekannte Preis-Stufe: {tier}")

    conn = db.get_conn()

    # Abo-Rabatt bestimmen (nur wenn Kaeufer ein AKTIVER Abonnent ist).
    discount_pct = 0.0
    if user_id is not None:
        buyer = conn.execute(
            "SELECT name, email, is_subscriber, sub_end FROM users WHERE id = ?",
            (user_id,)
        ).fetchone()
        if buyer:
            if not buyer_name:
                buyer_name = buyer["name"]
            if not buyer_email:
                buyer_email = buyer["email"] or ""
            active = bool(buyer["is_subscriber"]) and (
                not buyer["sub_end"] or buyer["sub_end"] >= date.today().isoformat())
            if active:
                try:
                    discount_pct = float(db.get_setting("discount_pct", "5"))
                except ValueError:
                    discount_pct = 5.0
    track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not track:
        conn.close()
        raise LicenseError("Track nicht gefunden.")

    kind = _tier_kind(tier)

    # --- Geschaeftsregel: Exklusiv-Sperre ---------------------------------
    if track["status"] == "exclusive_sold":
        conn.close()
        raise LicenseError(
            f"'{track['title']}' wurde bereits exklusiv verkauft und ist "
            "gesperrt. Keine weitere Lizenzierung moeglich."
        )

    existing_leases = conn.execute(
        "SELECT COUNT(*) c FROM licenses WHERE track_id = ?", (track_id,)
    ).fetchone()["c"]

    warning = None
    if kind == "exclusive" and existing_leases > 0:
        # Erlaubt, aber protokolliert (wichtig fuer saubere Historie).
        warning = (f"Achtung: Fuer diesen Track existieren bereits "
                   f"{existing_leases} Lease-Lizenz(en).")

    # --- Geschaeftsregel: Tages-Bezugslimit -------------------------------
    # Ein Lizenzkauf zaehlt (wie eine Generierung) als Tages-Bezug des Kaeufers.
    # Registrierte Nutzer sind gedeckelt (3 Basis / 10 Abo); Gaeste nicht.
    if user_id is not None:
        buyer_user = quota.get_user(user_id)
        if buyer_user:
            allowed, qs = quota.check_quota(buyer_user, 1)
            if not allowed:
                conn.close()
                raise LicenseError(
                    f"Tageslimit erreicht: {buyer_user['name']} hat heute "
                    f"{qs['used']}/{qs['limit']} Bezüge (Generierungen + Lizenzen). "
                    "Heute ist kein weiterer Bezug möglich.")

    list_price = get_price(tier) if price is None else float(price)
    net_price = round(list_price * (1 - discount_pct / 100.0), 2)

    sold_at = datetime.now().isoformat(timespec="seconds")
    cur = conn.execute(
        "INSERT INTO licenses (track_id, tier, license_type, buyer_name, "
        "buyer_email, buyer_user_id, price, list_price, discount_pct, currency, sold_at, notes) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'EUR', ?, ?)",
        (track_id, tier, kind, buyer_name, buyer_email, user_id, net_price,
         list_price, discount_pct, sold_at, notes),
    )
    license_id = cur.lastrowid

    # Track-Status aktualisieren.
    new_status = "exclusive_sold" if kind == "exclusive" else "leased"
    conn.execute("UPDATE tracks SET status = ? WHERE id = ?", (new_status, track_id))
    conn.commit()
    conn.close()

    db.log_event(
        "LICENSE_SOLD",
        entity="license",
        entity_id=license_id,
        details={
            "track_id": track_id,
            "title": track["title"],
            "tier": tier,
            "type": kind,
            "list_price": list_price,
            "discount_pct": discount_pct,
            "price": net_price,
            "buyer": buyer_name,
            "warning": warning,
        },
    )
    return license_id, warning


def list_licenses():
    conn = db.get_conn()
    rows = conn.execute(
        "SELECT l.*, t.title AS track_title, t.genre AS genre "
        "FROM licenses l JOIN tracks t ON t.id = l.track_id "
        "ORDER BY l.id DESC"
    ).fetchall()
    conn.close()
    return rows
