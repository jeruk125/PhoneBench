from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import current_user, login_user, logout_user
from urllib.parse import urlsplit

from ..extensions import db
from ..models import User
from ..security import audit

auth = Blueprint("auth", __name__)


@auth.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("core.dashboard"))
    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")
        user = User.query.filter_by(username=username, active=True).first()
        if user and user.check_password(password):
            login_user(user, remember=bool(request.form.get("remember")))
            audit("login", "user", user.id)
            db.session.commit()
            next_url = request.args.get("next")
            target = urlsplit(next_url or "")
            if next_url and not target.scheme and not target.netloc and target.path.startswith("/") and not target.path.startswith("//") and "\\" not in next_url:
                return redirect(next_url)
            return redirect(url_for("core.dashboard"))
        flash("Username or password was not recognized.", "danger")
    return render_template("login.html")


@auth.post("/logout")
def logout():
    if current_user.is_authenticated:
        audit("logout", "user", current_user.id)
        db.session.commit()
    logout_user()
    return redirect(url_for("auth.login"))
