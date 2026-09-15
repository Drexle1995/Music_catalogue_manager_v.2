"""
Katalog- & Lizenzverwaltung -- Flask-Anwendung (Einstiegspunkt).

Ergaenzendes kaufmaennisches Modul zum Musikproduktions-Gesamtpaket
(Music Architect V7 + SBS-Synth Master). Koppelt read-only an deren
Ausgabeordner, verwaltet Katalog & Lizenzen, rechnet die Wirtschaftlichkeit
und fuehrt ein Audit-Protokoll.

Start:  python main.py     ->  http://127.0.0.1:5000
"""

import csv
import io
import pathlib
from datetime import timedelta

from flask import (Flask, flash, redirect, render_template, request,
                   Response, url_for)
from flask_login import LoginManager, login_required, current_user
from flask_session import Session

import config
from db import database as db
from commerce import billing
from commerce import economics
from commerce import gateway
from commerce import licensing
from commerce import quota
from catalog import scanner
from db.demo_data import generate as generate_demo
from auth.auth import auth_bp, User
from beatgen.generate import generate_bp
from auth.rbac import require_admin
from catalog.sample_upload import sample_upload_bp
from catalog.stats import stats_bp

app = Flask(__name__)
app.secret_key = "change-me-in-production"

# --- Serverseitige Session-Konfiguration ------------------------------------
# Cookie-basierte Sessions sind auf ~4 KB begrenzt — zu klein fuer Audio-Pfade.
# Flask-Session speichert Sitzungsdaten auf dem Dateisystem, kein Groessenlimit.
_session_dir = pathlib.Path(__file__).parent / "flask_session"
_session_dir.mkdir(exist_ok=True)
app.config["SESSION_TYPE"]             = "filesystem"
app.config["SESSION_FILE_DIR"]         = str(_session_dir)
# Permanent=True damit die Session einen Browser-Neustart ueberlebt (Mac-Kompatibilitaet).
app.config["SESSION_PERMANENT"]        = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(hours=8)
app.config["SESSION_USE_SIGNER"]       = True   # Session-ID im Cookie signieren
app.config["SESSION_FILE_THRESHOLD"]   = 500    # max. Anzahl gespeicherter Session-Dateien
Session(app)

# --- Flask-Login setup ------------------------------------------------------

login_manager = LoginManager(app)
login_manager.login_view = "auth.login"
login_manager.login_message = "Bitte melden Sie sich an, um auf diese Seite zuzugreifen."
login_manager.login_message_category = "error"


@login_manager.user_loader
def load_user(user_id):
    return User.load(int(user_id))


# --- Blueprints -------------------------------------------------------------

app.register_blueprint(auth_bp)
app.register_blueprint(generate_bp)
app.register_blueprint(sample_upload_bp)
app.register_blueprint(stats_bp)

# Datenbank beim Import initialisieren (idempotent).
db.init_db()


# --- Root redirect ----------------------------------------------------------

@app.route("/")
def dashboard():
    """Redirect to /generate when logged in, otherwise to login."""
    if current_user.is_authenticated:
        return redirect(url_for("generate.generate_page"))
    return redirect(url_for("auth.login"))


@app.route("/dashboard")
@login_required
@require_admin
def dashboard_view():
    metrics = economics.compute()
    return render_template("dashboard.html", m=metrics, tiers=config.DEFAULT_TIERS)


# --- Katalog ----------------------------------------------------------------

@app.route("/catalog")
@login_required
@require_admin
def catalog():
    genre = request.args.get("genre", "")
    status = request.args.get("status", "")
    query = "SELECT * FROM tracks WHERE 1=1"
    params = []
    if genre:
        query += " AND genre = ?"
        params.append(genre)
    if status:
        query += " AND status = ?"
        params.append(status)
    query += " ORDER BY genre, title"

    conn = db.get_conn()
    tracks = conn.execute(query, params).fetchall()
    genres = [r["genre"] for r in conn.execute(
        "SELECT DISTINCT genre FROM tracks ORDER BY genre").fetchall()]
    conn.close()
    return render_template("catalog.html", tracks=tracks, genres=genres,
                           sel_genre=genre, sel_status=status)


@app.route("/track/<int:track_id>")
@login_required
@require_admin
def track_detail(track_id):
    conn = db.get_conn()
    track = conn.execute("SELECT * FROM tracks WHERE id = ?", (track_id,)).fetchone()
    if not track:
        conn.close()
        flash("Track nicht gefunden.", "error")
        return redirect(url_for("catalog"))
    exports = conn.execute(
        "SELECT * FROM exports WHERE track_id = ? ORDER BY tier", (track_id,)
    ).fetchall()
    lics = conn.execute(
        "SELECT * FROM licenses WHERE track_id = ? ORDER BY id DESC", (track_id,)
    ).fetchall()
    conn.close()
    # Preise fuer die Verkaufsmaske.
    tiers = {k: {**v, "price": licensing.get_price(k)}
             for k, v in config.DEFAULT_TIERS.items()}
    users = quota.list_users()
    return render_template("track_detail.html", track=track, exports=exports,
                           licenses=lics, tiers=tiers, users=users)


# --- Lizenz verkaufen -------------------------------------------------------

@app.route("/license/sell", methods=["POST"])
@login_required
@require_admin
def sell():
    track_id = int(request.form["track_id"])
    tier = request.form["tier"]
    buyer = request.form.get("buyer_name", "").strip()
    email = request.form.get("buyer_email", "").strip()
    notes = request.form.get("notes", "").strip()
    buyer_user = request.form.get("buyer_user", "").strip()
    user_id = int(buyer_user) if buyer_user.isdigit() else None
    try:
        lid, warning = licensing.sell_license(
            track_id, tier, buyer_name=buyer, buyer_email=email, notes=notes,
            user_id=user_id)
        if warning:
            flash(warning, "warning")
        return redirect(url_for("checkout", license_id=lid))
    except licensing.LicenseError as exc:
        flash(str(exc), "error")
        return redirect(url_for("track_detail", track_id=track_id))


# --- Checkout & Zahlung (simuliert) -----------------------------------------

@app.route("/checkout/<int:license_id>")
@login_required
@require_admin
def checkout(license_id):
    lic = billing.get_license(license_id)
    if not lic:
        flash("Bestellung nicht gefunden.", "error")
        return redirect(url_for("catalog"))
    ctx = billing.invoice_context("license", lic)
    return render_template("checkout.html", lic=lic, ctx=ctx)


@app.route("/license/<int:license_id>/pay", methods=["POST"])
@login_required
@require_admin
def license_pay(license_id):
    ok, err = billing.pay_license(license_id)
    flash("Zahlung bestätigt — die Lizenz ist bezahlt." if ok else err,
          "success" if ok else "error")
    return redirect(url_for("invoice", license_id=license_id))


@app.route("/license/<int:license_id>/cancel", methods=["POST"])
@login_required
@require_admin
def license_cancel(license_id):
    lic = billing.get_license(license_id)
    track_id = lic["track_id"] if lic else None
    ok, err = billing.cancel_license(license_id)
    flash("Bestellung storniert, Track wieder freigegeben." if ok else err,
          "success" if ok else "error")
    return redirect(url_for("track_detail", track_id=track_id) if track_id
                    else url_for("licenses"))


@app.route("/invoice/<int:license_id>")
@login_required
@require_admin
def invoice(license_id):
    lic = billing.get_license(license_id)
    if not lic:
        flash("Rechnung nicht gefunden.", "error")
        return redirect(url_for("licenses"))
    ctx = billing.invoice_context("license", lic)
    return render_template("invoice.html", ctx=ctx)


@app.route("/licenses")
@login_required
@require_admin
def licenses():
    rows = licensing.list_licenses()
    return render_template("licenses.html", licenses=rows)


# --- Wirtschaftlichkeit -----------------------------------------------------

@app.route("/economics")
@login_required
@require_admin
def economics_view():
    metrics = economics.compute()
    settings = db.get_all_settings()
    return render_template("economics.html", m=metrics, s=settings,
                           tiers=config.DEFAULT_TIERS)


# --- Einstellungen ----------------------------------------------------------

@app.route("/settings", methods=["GET", "POST"])
@login_required
@require_admin
def settings_view():
    if request.method == "POST":
        # Pfade + Kostenannahmen + Preise speichern.
        keys = ["catalog_dir", "export_dir", "dev_hours", "hourly_rate",
                "tooling_cost", "cost_per_track", "music_architect_cmd",
                "limit_free", "limit_subscriber", "discount_pct",
                "seller_name", "vat_pct", "sub_price_month"]
        keys += [f"price_{k}" for k in config.DEFAULT_TIERS]
        changed = {}
        for key in keys:
            if key in request.form:
                db.set_setting(key, request.form[key])
                changed[key] = request.form[key]
        db.log_event("SETTINGS_CHANGED", "settings", None, changed)
        flash("Einstellungen gespeichert.", "success")
        return redirect(url_for("settings_view"))

    settings = db.get_all_settings()
    return render_template("settings.html", s=settings, tiers=config.DEFAULT_TIERS)


# --- Aktionen: Scan & Demo --------------------------------------------------

@app.route("/scan", methods=["POST"])
@login_required
@require_admin
def scan():
    result = scanner.scan_all()
    cat, exp = result["catalog"], result["exports"]
    if cat.get("error"):
        flash(cat["error"], "error")
    else:
        flash(f"Katalog gescannt: {cat['added']} neu, {cat['updated']} "
              f"aktualisiert ({cat['scanned']} Dateien).", "success")
    if exp.get("error"):
        flash(exp["error"], "error")
    else:
        flash(f"Exporte gescannt: {exp['linked']} verknuepft, "
              f"{exp['unmatched']} ohne Zuordnung.", "success")
    return redirect(request.referrer or url_for("dashboard_view"))


@app.route("/load-demo", methods=["POST"])
@login_required
@require_admin
def load_demo():
    result = generate_demo()
    if result.get("error"):
        flash(result["error"], "error")
    else:
        flash(f"Demo-Daten erzeugt: {result['midi_created']} MIDI-Dateien, "
              f"{result['exports_created']} Exporte. Jetzt 'Scannen' klicken.",
              "success")
        db.log_event("DEMO_LOADED", "catalog", None, result)
    return redirect(request.referrer or url_for("dashboard_view"))


# --- Nutzer & Abo -----------------------------------------------------------

@app.route("/users")
@login_required
@require_admin
def users_view():
    users = quota.list_users()
    # Kontingent-Status je Nutzer fuer die Anzeige.
    rows = []
    for u in users:
        st = quota.quota_status(u)
        rows.append({"u": u, "st": st})
    limits = {"free": db.get_setting("limit_free"),
              "sub": db.get_setting("limit_subscriber"),
              "discount": db.get_setting("discount_pct")}
    terms = [{"months": m, "price": billing.subscription_price(m)}
             for m in config.SUBSCRIPTION_TERMS]
    return render_template("users.html", rows=rows, limits=limits, terms=terms)


# --- Abo-Checkout -----------------------------------------------------------

@app.route("/subscription/start", methods=["POST"])
@login_required
@require_admin
def subscription_start():
    user_id = int(request.form["user_id"])
    term = int(request.form.get("term_months", "1"))
    sub_id, err = billing.create_subscription(user_id, term)
    if err:
        flash(err, "error")
        return redirect(url_for("users_view"))
    return redirect(url_for("subscription_checkout", sub_id=sub_id))


@app.route("/subscription/checkout/<int:sub_id>")
@login_required
@require_admin
def subscription_checkout(sub_id):
    sub = billing.get_subscription(sub_id)
    if not sub:
        flash("Abo-Bestellung nicht gefunden.", "error")
        return redirect(url_for("users_view"))
    ctx = billing.invoice_context("subscription", sub)
    return render_template("checkout.html", sub=sub, ctx=ctx)


@app.route("/subscription/<int:sub_id>/pay", methods=["POST"])
@login_required
@require_admin
def subscription_pay(sub_id):
    ok, err = billing.pay_subscription(sub_id)
    flash("Abo bezahlt und aktiviert." if ok else err, "success" if ok else "error")
    return redirect(url_for("subscription_invoice", sub_id=sub_id))


@app.route("/subscription/invoice/<int:sub_id>")
@login_required
@require_admin
def subscription_invoice(sub_id):
    sub = billing.get_subscription(sub_id)
    if not sub:
        flash("Rechnung nicht gefunden.", "error")
        return redirect(url_for("users_view"))
    ctx = billing.invoice_context("subscription", sub)
    return render_template("invoice.html", ctx=ctx)


@app.route("/users/add", methods=["POST"])
@login_required
@require_admin
def users_add():
    name = request.form.get("name", "").strip()
    email = request.form.get("email", "").strip()
    is_sub = request.form.get("is_subscriber") == "on"
    if not name:
        flash("Bitte einen Namen angeben.", "error")
    else:
        quota.add_user(name, email, is_sub)
        flash(f"Nutzer '{name}' angelegt{' (Abo)' if is_sub else ''}.", "success")
    return redirect(url_for("users_view"))


@app.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@require_admin
def users_toggle(user_id):
    user = quota.get_user(user_id)
    if user:
        new_state = not bool(user["is_subscriber"])
        quota.set_subscriber(user_id, new_state)
        flash(f"'{user['name']}' ist jetzt {'Abonnent' if new_state else 'Basis-Nutzer'}.",
              "success")
    return redirect(url_for("users_view"))


@app.route("/generate-legacy", methods=["POST"])
@login_required
@require_admin
def generate_track():
    user_id = int(request.form["user_id"])
    try:
        count = max(1, int(request.form.get("count", "1")))
    except ValueError:
        count = 1
    res = gateway.run_generation(user_id, count=count)
    if res["ok"]:
        flash(f"[{res['mode']}] {res['count']} Track(s) fuer {res['user']} erzeugt. "
              f"Heute {res['status']['used']}/{res['status']['limit']} "
              f"(noch {res['status']['remaining']}). Zum Uebernehmen: Scannen.",
              "success")
    else:
        flash(res["error"], "error")
    return redirect(request.referrer or url_for("users_view"))


# --- Audit-Protokoll --------------------------------------------------------

@app.route("/audit")
@login_required
@require_admin
def audit():
    rows = db.get_audit_log()
    return render_template("audit.html", rows=rows)


@app.route("/audit.csv")
@login_required
@require_admin
def audit_csv():
    rows = db.get_audit_log(limit=100000)
    buffer = io.StringIO()
    writer = csv.writer(buffer, delimiter=";")
    writer.writerow(["id", "zeitstempel", "ereignis", "objekt", "objekt_id", "details"])
    for r in rows:
        writer.writerow([r["id"], r["ts"], r["event"], r["entity"],
                         r["entity_id"], r["details"]])
    return Response(
        buffer.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_protokoll.csv"},
    )


# --- Jinja-Filter -----------------------------------------------------------

@app.template_filter("euro")
def euro(value):
    try:
        return f"{float(value):,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".")
    except (TypeError, ValueError):
        return "–"


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
