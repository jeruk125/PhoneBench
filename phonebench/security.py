from functools import wraps
from hashlib import sha256
from secrets import token_urlsafe

from flask import abort, current_app, request
from flask_login import current_user

from .extensions import db
from .models import AuditLog

ROLE_PERMISSIONS = {
    "OWNER": {"*"},
    "ADMIN": {"*"},
    "TECHNICIAN": {
        "repairs.read", "repairs.write", "knowledge.read", "knowledge.write",
        "devices.read", "devices.write", "inventory.read", "attachments.write",
    },
    "RECEPTIONIST": {
        "customers.read", "customers.write", "devices.read", "devices.write",
        "repairs.read", "repairs.write", "invoices.read", "portal.write",
    },
    "ACCOUNTING": {
        "invoices.read", "invoices.write", "payments.write", "accounting.read",
        "inventory.read", "reports.read",
    },
}


def permission_required(permission):
    def decorate(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            permissions = ROLE_PERMISSIONS.get(getattr(current_user, "role", ""), set())
            if "*" not in permissions and permission not in permissions:
                abort(403)
            return view(*args, **kwargs)
        return wrapped
    return decorate


def audit(action, entity_type, entity_id=None, old_value=None, new_value=None):
    db.session.add(AuditLog(
        user_id=current_user.id if current_user.is_authenticated else None,
        action=action,
        entity_type=entity_type,
        entity_id=str(entity_id) if entity_id is not None else None,
        old_value=old_value,
        new_value=new_value,
        ip_address=request.remote_addr,
    ))


def new_portal_token():
    token = token_urlsafe(36)
    return token, sha256(token.encode("utf-8")).hexdigest()


def allowed_upload(filename):
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return extension in current_app.config["ALLOWED_UPLOAD_EXTENSIONS"]
