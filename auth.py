"""
Authentifizierungs-Blueprint — Registrierung, Anmeldung, Abmeldung.

Verwendet Flask-Login fuer die Sitzungsverwaltung und Werkzeug fuer das
Passwort-Hashing. Die User-Klasse kapselt die SQLite-Zeile, damit die
Flask-Login-Mixins ohne ORM funktionieren.
"""

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required
from werkzeug.security import check_password_hash, generate_password_hash

import database as db

auth_bp = Blueprint("auth", __name__)

# --- User model -------------------------------------------------------------

class User(UserMixin):
    """Thin wrapper um eine users-Tabellenzeile fuer Flask-Login."""

    def __init__(self, row):
        self.id            = row["id"]
        self.email         = row["email"]
        self.password_hash = row["password_hash"]
        self.tier          = row["tier"] if row["tier"] else "free"
        # is_admin: 1 = voller Admin-Zugang, 0 = nur /generate und /stats.
        self.is_admin      = bool(row["is_admin"]) if "is_admin" in row.keys() else False

    def get_id(self):
        return str(self.id)

    @staticmethod
    def load(user_id: int):
        """Wird vom login_manager-user_loader-Callback in app.py aufgerufen."""
        conn = db.get_conn()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        conn.close()
        return User(row) if row else None


# --- Routen -----------------------------------------------------------------

@auth_bp.route("/register", methods=["GET", "POST"])
def register():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm = request.form.get("confirm", "")

        if not email or not password:
            flash("E-Mail und Passwort sind erforderlich.", "error")
            return render_template("register.html")
        if password != confirm:
            flash("Passwoerter stimmen nicht ueberein.", "error")
            return render_template("register.html")
        if db.get_user_by_email(email):
            flash("Ein Konto mit dieser E-Mail-Adresse existiert bereits.", "error")
            return render_template("register.html")

        hashed = generate_password_hash(password)
        uid = db.create_user(email, hashed, tier="free")
        db.log_event("USER_REGISTERED", "user", uid, {"email": email})

        row = db.get_user_by_email(email)
        login_user(User(row))
        return redirect(url_for("generate.generate_page"))

    return render_template("register.html")


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")

        row = db.get_user_by_email(email)
        if not row or not row["password_hash"]:
            flash("Ungueltige E-Mail oder falsches Passwort.", "error")
            return render_template("login.html")
        if not check_password_hash(row["password_hash"], password):
            flash("Ungueltige E-Mail oder falsches Passwort.", "error")
            return render_template("login.html")

        login_user(User(row))
        next_page = request.args.get("next")
        return redirect(next_page or url_for("generate.generate_page"))

    return render_template("login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for("auth.login"))
