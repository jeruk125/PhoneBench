import os
import secrets

import click
from dotenv import load_dotenv
from flask import Flask
from flask_login import current_user
from flask_wtf.csrf import CSRFError

from .extensions import csrf, db, login_manager, migrate
from .models import User


def create_app(test_config=None):
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    os.makedirs(app.instance_path, exist_ok=True)
    secret_path = os.path.join(app.instance_path, "secret.key")
    if not os.path.exists(secret_path):
        try:
            with open(secret_path, "x", encoding="utf-8") as secret_file:
                secret_file.write(secrets.token_urlsafe(48))
        except FileExistsError:
            pass
    with open(secret_path, encoding="utf-8") as secret_file:
        local_secret = secret_file.read().strip()

    default_database = "sqlite:///" + os.path.join(app.instance_path, "phonebench.sqlite").replace("\\", "/")
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("PHONEBENCH_SECRET_KEY", local_secret),
        SQLALCHEMY_DATABASE_URI=os.environ.get("PHONEBENCH_DATABASE_URL", default_database),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
        UPLOAD_FOLDER=os.path.join(app.instance_path, "uploads"),
        BACKUP_FOLDER=os.path.join(app.instance_path, "backups"),
        MAX_CONTENT_LENGTH=1024 * 1024 * 1024,
        ATTACHMENT_MAX_BYTES=16 * 1024 * 1024,
        ALLOWED_UPLOAD_EXTENSIONS={"png", "jpg", "jpeg", "webp", "gif", "pdf", "txt", "log", "csv", "doc", "docx"},
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=os.environ.get("PHONEBENCH_COOKIE_SECURE", "").lower() in {"true", "1", "yes"},
        REMEMBER_COOKIE_HTTPONLY=True,
        REMEMBER_COOKIE_SAMESITE="Lax",
        AI_BASE_URL=os.environ.get("PHONEBENCH_AI_BASE_URL", ""),
        AI_API_KEY=os.environ.get("PHONEBENCH_AI_API_KEY", ""),
        AI_MODEL=os.environ.get("PHONEBENCH_AI_MODEL", ""),
        WHATSAPP_TOKEN=os.environ.get("PHONEBENCH_WHATSAPP_TOKEN", ""),
        WHATSAPP_PHONE_NUMBER_ID=os.environ.get("PHONEBENCH_WHATSAPP_PHONE_NUMBER_ID", ""),
        WHATSAPP_API_VERSION=os.environ.get("PHONEBENCH_WHATSAPP_API_VERSION", "v22.0"),
    )
    if test_config:
        app.config.update(test_config)

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message_category = "warning"

    @login_manager.unauthorized_handler
    def unauthorized():
        from flask import jsonify, redirect, request, url_for
        if request.path.startswith("/api/"):
            return jsonify({"error": "authentication_required"}), 401
        return redirect(url_for("auth.login", next=request.full_path))

    migrate.init_app(app, db)
    csrf.init_app(app)

    from .routes.auth import auth
    from .routes.core import core
    from .routes.api import api
    from .routes.repairs import repairs
    from .routes.finance import finance
    from .routes.operations import operations
    from .routes.portal import portal

    app.register_blueprint(auth)
    app.register_blueprint(api)
    app.register_blueprint(core)
    app.register_blueprint(repairs)
    app.register_blueprint(finance)
    app.register_blueprint(operations)
    app.register_blueprint(portal)

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    @app.context_processor
    def inject_shell_data():
        return {"current_user": current_user}

    @app.errorhandler(CSRFError)
    def handle_csrf_error(error):
        return f"Request rejected: {error.description}", 400

    @app.cli.command("init-db")
    def init_db():
        """Create the local database tables."""
        with app.app_context():
            db.create_all()
        click.echo("Database tables are ready.")

    @app.cli.command("create-admin")
    @click.option("--username", prompt=True)
    @click.option("--name", "display_name", prompt="Display name")
    def create_admin(username, display_name):
        """Create an owner account with an interactive password prompt."""
        password = click.prompt("Password", hide_input=True, confirmation_prompt=True)
        if len(password) < 12:
            raise click.ClickException("Use a password with at least 12 characters.")
        with app.app_context():
            if User.query.filter_by(username=username).first():
                raise click.ClickException("That username already exists.")
            user = User(username=username.strip(), display_name=display_name.strip(), role="OWNER")
            user.set_password(password)
            db.session.add(user)
            db.session.commit()
        click.echo(f"Owner account '{username}' created.")

    @app.cli.command("seed-demo")
    def seed_demo():
        """Insert clearly labeled fictional evaluation records."""
        from .seed import seed_demo_data
        with app.app_context():
            db.create_all()
            seed_demo_data()
        click.echo("Demo records inserted (fictional; no demo credentials were created).")

    @app.cli.command("backup-if-due")
    def backup_if_due():
        """Create scheduled backups; invoke daily from Windows Task Scheduler."""
        from datetime import datetime
        from .models import AppSetting
        from .services.backup import create_database_backup

        frequency = os.environ.get("PHONEBENCH_BACKUP_FREQUENCY", "daily").lower()
        if frequency not in {"daily", "weekly", "manual"}:
            raise click.ClickException("PHONEBENCH_BACKUP_FREQUENCY must be daily, weekly, or manual.")
        if frequency == "manual":
            click.echo("Automatic backup is disabled (manual mode).")
            return
        with app.app_context():
            previous = AppSetting.query.filter_by(key="last_auto_backup").first()
            if previous and previous.value:
                last = datetime.fromisoformat(previous.value)
                minimum_days = 7 if frequency == "weekly" else 1
                if (datetime.utcnow() - last).days < minimum_days:
                    click.echo("The scheduled backup is not due yet.")
                    return
            created = create_database_backup()
            if not previous:
                previous = AppSetting(key="last_auto_backup")
                db.session.add(previous)
            previous.value = datetime.utcnow().isoformat()
            db.session.commit()
            click.echo(f"Scheduled backup created: {created['database']}")

    return app
