"""
Wirtschaftlichkeitsrechnung.

Berechnet aus den erfassten Lizenzverkaeufen und den (editierbaren)
Kostenannahmen die zentralen betriebswirtschaftlichen Kennzahlen:

  - Umsatz (gesamt und je Stufe/Genre)
  - variable Kosten und Deckungsbeitrag
  - Fixkosten / einmalige Investition
  - Gewinn
  - Break-even (Umsatz und Anzahl durchschnittlich bepreister Lizenzen)
  - ROI

Bewusst als reine, testbare Funktionen gehalten -- ideal fuer das Testprotokoll.
"""

import database as db


def _f(value, default=0.0):
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def get_cost_assumptions():
    """Liest die Kostenannahmen aus den Einstellungen."""
    s = db.get_all_settings()
    dev_hours = _f(s.get("dev_hours"))
    hourly_rate = _f(s.get("hourly_rate"))
    tooling = _f(s.get("tooling_cost"))
    cost_per_track = _f(s.get("cost_per_track"))

    fixed_cost = dev_hours * hourly_rate + tooling
    return {
        "dev_hours": dev_hours,
        "hourly_rate": hourly_rate,
        "tooling_cost": tooling,
        "cost_per_track": cost_per_track,
        "fixed_cost": fixed_cost,   # einmalige Investition
    }


def compute():
    """Zentrale Kennzahlen-Berechnung. Gibt ein dict fuer die Oberflaeche zurueck."""
    conn = db.get_conn()

    track_count = conn.execute("SELECT COUNT(*) c FROM tracks").fetchone()["c"]
    # Nur BEZAHLTE Lizenzen zaehlen als Umsatz.
    license_count = conn.execute(
        "SELECT COUNT(*) c FROM licenses WHERE payment_status = 'paid'"
    ).fetchone()["c"]
    license_revenue = conn.execute(
        "SELECT COALESCE(SUM(price), 0) s FROM licenses WHERE payment_status = 'paid'"
    ).fetchone()["s"]
    open_amount = conn.execute(
        "SELECT COALESCE(SUM(price), 0) s FROM licenses WHERE payment_status = 'open'"
    ).fetchone()["s"]
    open_count = conn.execute(
        "SELECT COUNT(*) c FROM licenses WHERE payment_status = 'open'"
    ).fetchone()["c"]
    # Abo-Umsatz (zweiter Erloesstrom des Freemium-Modells).
    subscription_revenue = conn.execute(
        "SELECT COALESCE(SUM(price), 0) s FROM subscriptions WHERE status = 'paid'"
    ).fetchone()["s"]

    revenue_total = license_revenue + subscription_revenue

    # Summe der gewaehrten Abo-Rabatte (nur bezahlte Lizenzen).
    discounts_total = conn.execute(
        "SELECT COALESCE(SUM(COALESCE(list_price, price) - price), 0) s "
        "FROM licenses WHERE payment_status = 'paid'"
    ).fetchone()["s"]

    revenue_by_tier = conn.execute(
        "SELECT tier, COUNT(*) n, COALESCE(SUM(price),0) s "
        "FROM licenses WHERE payment_status = 'paid' GROUP BY tier ORDER BY s DESC"
    ).fetchall()
    revenue_by_genre = conn.execute(
        "SELECT t.genre AS genre, COUNT(*) n, COALESCE(SUM(l.price),0) s "
        "FROM licenses l JOIN tracks t ON t.id = l.track_id "
        "WHERE l.payment_status = 'paid' "
        "GROUP BY t.genre ORDER BY s DESC"
    ).fetchall()

    status_counts = {"available": 0, "leased": 0, "exclusive_sold": 0}
    for row in conn.execute(
        "SELECT status, COUNT(*) c FROM tracks GROUP BY status"
    ).fetchall():
        status_counts[row["status"]] = row["c"]
    conn.close()

    costs = get_cost_assumptions()

    # Variable Kosten: je erzeugtem Track (Rechenzeit/Speicher).
    variable_cost = track_count * costs["cost_per_track"]
    contribution_margin = revenue_total - variable_cost   # Deckungsbeitrag
    profit = revenue_total - variable_cost - costs["fixed_cost"]

    # Durchschnittlicher Deckungsbeitrag je Lizenz -> Break-even in Stueck.
    avg_price = (revenue_total / license_count) if license_count else 0.0
    # DB je Lizenz naeherungsweise: Erloes minus variabler Kostenanteil je Track.
    # (Variable Kosten fallen je Track an, nicht je Lizenz; fuer die Break-even-
    #  Stueckzahl nutzen wir den Durchschnittspreis als konservative Naeherung.)
    break_even_units = (costs["fixed_cost"] / avg_price) if avg_price else None
    break_even_revenue = costs["fixed_cost"] + variable_cost

    total_investment = costs["fixed_cost"] + variable_cost
    roi = (profit / total_investment * 100.0) if total_investment else None

    # Fortschritt Richtung Break-even (fuer die VU-Meter-Anzeige).
    be_progress = 0.0
    if break_even_revenue > 0:
        be_progress = min(revenue_total / break_even_revenue * 100.0, 100.0)

    return {
        "track_count": track_count,
        "license_count": license_count,
        "status_counts": status_counts,
        "revenue_total": revenue_total,
        "license_revenue": license_revenue,
        "subscription_revenue": subscription_revenue,
        "open_amount": open_amount,
        "open_count": open_count,
        "discounts_total": discounts_total,
        "variable_cost": variable_cost,
        "contribution_margin": contribution_margin,
        "fixed_cost": costs["fixed_cost"],
        "profit": profit,
        "avg_price": avg_price,
        "break_even_units": break_even_units,
        "break_even_revenue": break_even_revenue,
        "roi": roi,
        "be_progress": be_progress,
        "revenue_by_tier": revenue_by_tier,
        "revenue_by_genre": revenue_by_genre,
        "costs": costs,
    }
