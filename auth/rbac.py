"""
rbac.py — Rollenbasierte Zugriffskontrolle (Role-Based Access Control).

Stellt den Dekorator `require_admin` bereit, der alle Admin-Routen schuetzt.
Normale Nutzer (is_admin=0) werden bei Zugriffsversuch auf /generate umgeleitet.
"""

from functools import wraps

from flask import redirect, url_for
from flask_login import current_user


def require_admin(fn):
    """
    Dekorator fuer Flask-Routen, die nur Admins zugaenglich sein sollen.

    Anwendung::
        @app.route('/catalog')
        @login_required
        @require_admin
        def catalog(): ...

    Reihenfolge: @login_required muss VOR @require_admin stehen, damit
    nicht-eingeloggte Nutzer zuerst zur Login-Seite geleitet werden.
    """
    @wraps(fn)
    def wrapper(*args, **kwargs):
        # Attribut is_admin wird aus der users-Tabelle geladen (User.load()).
        if not getattr(current_user, "is_admin", False):
            return redirect(url_for("generate.generate_page"))
        return fn(*args, **kwargs)
    return wrapper
