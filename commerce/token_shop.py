"""
Token-Shop-Blueprint — fuer ALLE eingeloggten Nutzer (nicht nur Admins).

Ablauf analog zu Lizenz- und Abo-Kauf:
  /tokens                 Guthaben, Preise, Pakete, eigene Bestellungen
  /tokens/buy      (POST) Bestellung anlegen  -> Checkout
  /tokens/checkout/<id>   simulierte Zahlungsseite
  /tokens/<id>/pay (POST) Zahlung bestaetigen -> Tokens werden gutgeschrieben
  /tokens/<id>/cancel     offene Bestellung stornieren
  /tokens/invoice/<id>    Rechnung

Nutzer sehen und bezahlen nur ihre EIGENEN Bestellungen; Admins alle.
"""

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_required

import config
from commerce import billing
from commerce import tokens

tokens_bp = Blueprint("tokens", __name__)


def _own_purchase_or_404(purchase_id):
    p = tokens.get_purchase(purchase_id)
    if not p:
        abort(404)
    if p["user_id"] != current_user.id and not getattr(current_user, "is_admin", False):
        abort(404)   # fremde Bestellungen nicht preisgeben
    return p


@tokens_bp.route("/tokens")
@login_required
def shop():
    offer = tokens.price_for(current_user.id)
    prices = tokens.get_prices()
    packages = [{"quantity": q,
                 "price": round(q * offer["unit_price"], 2),
                 "list_price": round(q * prices["basic"], 2)}
                for q in config.TOKEN_PACKAGES]
    saving_pct = 0
    if prices["basic"] > 0:
        saving_pct = round((1 - prices["subscriber"] / prices["basic"]) * 100)
    return render_template(
        "tokens.html",
        balance=tokens.balance(current_user.id),
        offer=offer,
        prices=prices,
        saving_pct=saving_pct,
        packages=packages,
        purchases=tokens.list_purchases(current_user.id, limit=20),
        ledger=tokens.list_ledger(current_user.id, limit=20),
        max_quantity=tokens.MAX_QUANTITY,
    )


@tokens_bp.route("/tokens/buy", methods=["POST"])
@login_required
def buy():
    pid, err = tokens.create_purchase(current_user.id, request.form.get("quantity"))
    if err:
        flash(err, "error")
        return redirect(url_for("tokens.shop"))
    return redirect(url_for("tokens.checkout", purchase_id=pid))


@tokens_bp.route("/tokens/checkout/<int:purchase_id>")
@login_required
def checkout(purchase_id):
    p = _own_purchase_or_404(purchase_id)
    if p["status"] == "cancelled":
        flash("Diese Bestellung wurde storniert.", "error")
        return redirect(url_for("tokens.shop"))
    ctx = billing.invoice_context("tokens", p)
    return render_template("checkout.html", purchase=p, ctx=ctx)


@tokens_bp.route("/tokens/<int:purchase_id>/pay", methods=["POST"])
@login_required
def pay(purchase_id):
    p = _own_purchase_or_404(purchase_id)
    ok, err = tokens.pay_purchase(purchase_id)
    if ok:
        flash(f"Zahlung bestätigt — {p['quantity']} Token(s) gutgeschrieben.", "success")
        return redirect(url_for("tokens.invoice", purchase_id=purchase_id))
    flash(err, "error")
    return redirect(url_for("tokens.shop"))


@tokens_bp.route("/tokens/<int:purchase_id>/cancel", methods=["POST"])
@login_required
def cancel(purchase_id):
    _own_purchase_or_404(purchase_id)
    ok, err = tokens.cancel_purchase(purchase_id)
    flash("Bestellung storniert." if ok else err, "success" if ok else "error")
    return redirect(url_for("tokens.shop"))


@tokens_bp.route("/tokens/invoice/<int:purchase_id>")
@login_required
def invoice(purchase_id):
    p = _own_purchase_or_404(purchase_id)
    if p["status"] == "cancelled":
        flash("Für stornierte Bestellungen gibt es keine Rechnung.", "error")
        return redirect(url_for("tokens.shop"))
    ctx = billing.invoice_context("tokens", p)
    return render_template("invoice.html", ctx=ctx)
