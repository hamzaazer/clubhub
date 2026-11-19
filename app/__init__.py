import os
from datetime import timedelta

import click
from flask import Flask, render_template, session, url_for
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_sqlalchemy import SQLAlchemy
from flask_wtf.csrf import CSRFProtect
from sqlalchemy import inspect, text
from werkzeug.middleware.proxy_fix import ProxyFix

from .i18n import translate_html

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()
limiter = Limiter(key_func=get_remote_address)


def create_app():
    app = Flask(__name__)
    prod = os.environ.get("FLASK_ENV") == "production"
    secret = os.environ.get("SECRET_KEY")
    if prod and not secret:
        raise RuntimeError("SECRET_KEY must be set in production")

    db_url = os.environ.get("DATABASE_URL") or "sqlite:///club.db"
    if db_url.startswith("postgres://"):
        db_url = db_url.replace("postgres://", "postgresql://", 1)

    app.config.update(
        SECRET_KEY=secret or "dev-only-change-me",
        SQLALCHEMY_DATABASE_URI=db_url,
        SQLALCHEMY_ENGINE_OPTIONS={"pool_pre_ping": True, "pool_recycle": 280},
        MAX_CONTENT_LENGTH=6 * 1024 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=prod,
        PERMANENT_SESSION_LIFETIME=timedelta(hours=12),
        RATELIMIT_STORAGE_URI="memory://",
    )
    if prod:  # behind Render's HTTPS proxy
        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1)

    db.init_app(app)
    csrf.init_app(app)
    limiter.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please log in to continue."

    from . import auth, member, admin, owner, models

    for module in (auth, member, admin, owner):
        app.register_blueprint(module.bp)

    app.jinja_env.filters["num"] = lambda v: "" if v is None else "%g" % v

    @app.context_processor
    def inject_globals():
        logo_version = models.get_setting("club_logo_version", "0")
        return {"club_name": models.get_setting("club_name", "ClubHub"),
                "current_language": session.get("language", "en"),
                "club_logo_url": url_for("owner.club_logo", v=logo_version)
                if models.get_setting("club_logo") else "",
                "social_links": {
                    "instagram": models.get_setting("homepage_instagram", ""),
                    "facebook": models.get_setting("homepage_facebook", ""),
                    "youtube": models.get_setting("homepage_youtube", ""),
                    "tiktok": models.get_setting("homepage_tiktok", ""),
                },
                "PERMISSIONS": models.PERMISSIONS}

    @app.after_request
    def security_headers(resp):
        translate_html(resp, session.get("language", "en"))
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "same-origin"
        resp.headers["Content-Security-Policy"] = (
            "default-src 'self'; img-src 'self' data:; style-src 'self'; "
            "script-src 'self'; frame-ancestors 'none'; form-action 'self'")
        if prod:
            resp.headers["Strict-Transport-Security"] = "max-age=31536000; includeSubDomains"
        return resp

    for code, msg in ((403, "You don't have access to this page."),
                      (404, "We couldn't find that page."),
                      (413, "That file is too large. Please upload an image under 5 MB."),
                      (429, "Too many attempts. Please wait a minute and try again.")):
        app.register_error_handler(code, lambda e, code=code, msg=msg: (
            render_template("error.html", code=code, message=msg), code))

    @app.cli.command("create-owner")
    @click.option("--name", prompt=True)
    @click.option("--email", prompt=True)
    @click.password_option()
    def create_owner(name, email, password):
        """Create (or promote) an Owner account."""
        models.make_owner(name, email, password)
        click.echo("Owner ready.")

    with app.app_context():
        db.create_all()
        if os.environ.get("SUPABASE_ENABLE_RLS", "").lower() in ("1", "true", "yes"):
            # Flask uses the trusted database connection; the table owner bypasses RLS.
            # Enabling RLS with no client policies blocks direct Data API access.
            preparer = db.engine.dialect.identifier_preparer
            with db.engine.begin() as connection:
                for table in db.metadata.sorted_tables:
                    table_name = preparer.quote(table.name)
                    connection.execute(text(f"ALTER TABLE public.{table_name} ENABLE ROW LEVEL SECURITY"))
        user_columns = {column["name"] for column in inspect(db.engine).get_columns("users")}
        new_columns = {
            "member_title": "VARCHAR(80) NOT NULL DEFAULT ''",
            "place_of_work": "VARCHAR(150) NOT NULL DEFAULT ''",
            "wilaya": "VARCHAR(2) NOT NULL DEFAULT ''",
            "commune": "VARCHAR(100) NOT NULL DEFAULT ''",
        }
        with db.engine.begin() as connection:
            for name, declaration in new_columns.items():
                if name not in user_columns:
                    connection.execute(text(f"ALTER TABLE users ADD COLUMN {name} {declaration}"))
        criterion_columns = {column["name"] for column in inspect(db.engine).get_columns("criterion")}
        if "global_id" not in criterion_columns:
            with db.engine.begin() as connection:
                connection.execute(text("ALTER TABLE criterion ADD COLUMN global_id INTEGER"))
        table_names = set(inspect(db.engine).get_table_names())
        optional_columns = {
            "leaders": {"has_photo": "BOOLEAN NOT NULL DEFAULT FALSE",
                        "link": "VARCHAR(500) NOT NULL DEFAULT ''"},
            "partnerships": {"has_photo": "BOOLEAN NOT NULL DEFAULT FALSE"},
            "community_events": {
                "event_time": "TIME",
                "has_photo": "BOOLEAN NOT NULL DEFAULT FALSE",
            },
            "gallery_photos": {"has_photo": "BOOLEAN NOT NULL DEFAULT TRUE"},
        }
        for table, columns in optional_columns.items():
            if table not in table_names:
                continue
            existing = {column["name"] for column in inspect(db.engine).get_columns(table)}
            with db.engine.begin() as connection:
                for name, declaration in columns.items():
                    if name not in existing:
                        connection.execute(text(f"ALTER TABLE {table} ADD COLUMN {name} {declaration}"))
        role_names = {role.name.lower() for role in models.ClubRole.query.all()}
        for (member_title,) in db.session.query(models.User.member_title).distinct():
            title = (member_title or "").strip()
            if title and title.lower() not in role_names:
                db.session.add(models.ClubRole(name=title))
                role_names.add(title.lower())
        db.session.commit()
        models.seed_owner()
    return app
