"""
stats.py — Statistik-Blueprint fuer den aktuell eingeloggten Nutzer.

Zeigt aggregierte Speicher-Aktivitaet aus quota_ledger und generations,
gefiltert nach current_user.id. Kein Zugriff auf fremde Nutzerdaten.

Routen:
    GET /stats  — Statistik-Seite (HTML)
    GET /stats/api — JSON-Endpunkt fuer AJAX-Aktualisierungen
"""

from datetime import date, timedelta

from flask import Blueprint, jsonify, render_template
from flask_login import current_user, login_required

from db import database as db

stats_bp = Blueprint("stats", __name__)


def _compute_stats(user_id: int) -> dict:
    """
    Berechnet Tages-, Wochen- und Monatswerte aus quota_ledger und generations.

    Gibt ein dict zurueck, das direkt an das Template uebergeben werden kann.
    """
    today       = date.today()
    week_start  = today - timedelta(days=today.weekday())   # Montag
    month_start = today.replace(day=1)

    today_str       = today.isoformat()
    week_start_str  = week_start.isoformat()
    month_start_str = month_start.isoformat()

    conn = db.get_conn()

    # --- Gespeicherte Songs (quota_ledger) ---
    # Tagesanzahl direkt aus der Tageszeile lesen.
    row = conn.execute(
        "SELECT daily_saves FROM quota_ledger WHERE user_id = ? AND date = ?",
        (user_id, today_str),
    ).fetchone()
    saves_today = row["daily_saves"] if row else 0

    # Wochensumme: alle Zeilen ab Montag summieren.
    row = conn.execute(
        "SELECT COALESCE(SUM(daily_saves), 0) AS s FROM quota_ledger "
        "WHERE user_id = ? AND date >= ?",
        (user_id, week_start_str),
    ).fetchone()
    saves_week = row["s"]

    # Monatssumme: monthly_saves des heutigen Eintrags spiegelt den Monatsstand.
    row = conn.execute(
        "SELECT COALESCE(SUM(daily_saves), 0) AS s FROM quota_ledger "
        "WHERE user_id = ? AND date >= ?",
        (user_id, month_start_str),
    ).fetchone()
    saves_month = row["s"]

    # --- Erzeugte Songs (generations-Tabelle) ---
    row = conn.execute(
        "SELECT COUNT(*) c FROM generations "
        "WHERE user_id = ? AND substr(created_at, 1, 10) = ?",
        (user_id, today_str),
    ).fetchone()
    gen_today = row["c"]

    row = conn.execute(
        "SELECT COUNT(*) c FROM generations "
        "WHERE user_id = ? AND substr(created_at, 1, 10) >= ?",
        (user_id, week_start_str),
    ).fetchone()
    gen_week = row["c"]

    row = conn.execute(
        "SELECT COUNT(*) c FROM generations "
        "WHERE user_id = ? AND substr(created_at, 1, 10) >= ?",
        (user_id, month_start_str),
    ).fetchone()
    gen_month = row["c"]

    # --- Letzte 7 Tage pro Tag (fuer Sparkline-Chart) ---
    daily_rows = conn.execute(
        "SELECT date, COALESCE(daily_saves, 0) AS saves FROM quota_ledger "
        "WHERE user_id = ? AND date >= ? ORDER BY date",
        (user_id, (today - timedelta(days=6)).isoformat()),
    ).fetchall()

    # Luecken mit 0 fuellen, damit jeder der 7 Tage vorhanden ist.
    daily_map = {r["date"]: r["saves"] for r in daily_rows}
    chart_labels = [(today - timedelta(days=i)).isoformat() for i in range(6, -1, -1)]
    chart_data   = [daily_map.get(d, 0) for d in chart_labels]

    # --- Genre-Verteilung der gespeicherten Tracks ---
    genre_rows = conn.execute(
        "SELECT genre, COUNT(*) cnt FROM tracks "
        "WHERE user_id = ? GROUP BY genre ORDER BY cnt DESC",
        (user_id,),
    ).fetchall()
    genres       = [r["genre"] or "unbekannt" for r in genre_rows]
    genre_counts = [r["cnt"] for r in genre_rows]

    conn.close()

    return {
        "saves_today":   saves_today,
        "saves_week":    saves_week,
        "saves_month":   saves_month,
        "gen_today":     gen_today,
        "gen_week":      gen_week,
        "gen_month":     gen_month,
        "chart_labels":  chart_labels,
        "chart_data":    chart_data,
        "genres":        genres,
        "genre_counts":  genre_counts,
        "today":         today_str,
        "week_start":    week_start_str,
        "month_start":   month_start_str,
    }


@stats_bp.route("/stats")
@login_required
def stats_page():
    """Statistik-Seite: gespeicherte und erzeugte Songs des aktuellen Nutzers."""
    data = _compute_stats(current_user.id)
    return render_template("stats.html", s=data,
                           tier=current_user.tier,
                           email=current_user.email)


@stats_bp.route("/stats/api")
@login_required
def stats_api():
    """JSON-Endpunkt fuer Live-Aktualisierung der Statistik ohne Seitenneuladen."""
    return jsonify(_compute_stats(current_user.id))
