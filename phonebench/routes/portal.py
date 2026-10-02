from hashlib import sha256

from flask import Blueprint, abort, flash, redirect, render_template, request, url_for
from flask_login import login_required

from ..extensions import db
from ..models import PortalToken, Repair
from ..security import audit, new_portal_token, permission_required

portal = Blueprint("portal", __name__)


@portal.post("/repairs/<int:repair_id>/portal-token")
@login_required
@permission_required("portal.write")
def token_create(repair_id):
    repair = db.get_or_404(Repair, repair_id)
    token, token_hash = new_portal_token()
    db.session.add(PortalToken(token_hash=token_hash, repair_id=repair.id))
    audit("portal_token_created", "repair", repair.id)
    db.session.commit()
    return render_template("portal_link.html", link=f"{request.url_root.rstrip('/')}{url_for('portal.customer_portal', token=token)}", repair=repair)


@portal.post("/portal/<int:token_id>/revoke")
@login_required
@permission_required("portal.write")
def token_revoke(token_id):
    token = db.get_or_404(PortalToken, token_id)
    token.active = False
    audit("portal_token_revoked", "portal_token", token.id)
    db.session.commit()
    flash("Customer portal access revoked.", "success")
    return redirect(url_for("repairs.repair_detail", repair_id=token.repair_id))


@portal.get("/customer/<token>")
def customer_portal(token):
    token_hash = sha256(token.encode("utf-8")).hexdigest()
    access = PortalToken.query.filter_by(token_hash=token_hash, active=True).first()
    if not access:
        abort(404)
    repair = access.repair
    invoices = [invoice for invoice in repair.invoices if invoice.status in {"ISSUED", "PARTIALLY_PAID", "PAID", "OVERDUE"}]
    return render_template("customer_portal.html", repair=repair, invoices=invoices)
