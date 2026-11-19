from flask import (Blueprint, Response, abort, flash, redirect, render_template, request,
                   session, url_for)
from flask_login import current_user, login_required, login_user, logout_user
from sqlalchemy import func
from sqlalchemy.orm import undefer
from datetime import date

from . import db, limiter
from .forms import LoginForm, RegisterForm, configure_location_choices
from .models import (ClubRole, CommunityEvent, GalleryPhoto, Leader, Partnership, User,
                    get_setting)
from .utils import parse_equipment, process_image

bp = Blueprint("auth", __name__)


@bp.route("/")
def index():
    if current_user.is_authenticated:
        return redirect(url_for("member.dashboard" if current_user.role == "member" else "admin.dashboard"))
    content = {
        "hero_heading": get_setting("homepage_hero_heading", "Capture today. Create tomorrow."),
        "hero_copy": get_setting("homepage_hero_copy", "A local home for photographers, filmmakers, editors and curious creators in Mascara, Algeria."),
        "about_heading": get_setting("homepage_about_heading", "A club for people who see stories everywhere."),
        "about_copy": get_setting("homepage_about_copy", "VALiDO brings creative people together to learn, make and share. Join a photo walk, try a new technique, or make your first short film alongside a welcoming community."),
        "community_copy": get_setting("homepage_community_copy", "From first-time photographers to experienced creators, there is room to learn, contribute and make something together."),
    }
    events = CommunityEvent.query.filter(CommunityEvent.event_date >= date.today()).order_by(
        CommunityEvent.event_date, CommunityEvent.id).all()
    return render_template("index.html", content=content, events=events,
                           leaders=Leader.query.order_by(Leader.sort_order, Leader.id).all(),
                           partnerships=Partnership.query.order_by(Partnership.sort_order, Partnership.id).all(),
                           gallery=GalleryPhoto.query.order_by(GalleryPhoto.sort_order, GalleryPhoto.id).all())


@bp.route("/healthz")
def healthz():
    return "ok"


@bp.route("/login", methods=["GET", "POST"])
@limiter.limit("10 per minute", methods=["POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))
    form = LoginForm()
    if form.validate_on_submit():
        user = User.query.filter(func.lower(User.email) == form.email.data.lower()).first()
        if user and user.check_password(form.password.data):
            if user.status == "pending":
                flash("Your registration is waiting for admin approval. Please check back soon.", "info")
            elif user.status == "rejected":
                flash("Your registration was not approved. Please contact a club admin.", "error")
            else:
                login_user(user)
                session.permanent = True
                nxt = request.args.get("next", "")
                if nxt.startswith("/") and not nxt.startswith("//") and "\\" not in nxt:
                    return redirect(nxt)
                return redirect(url_for("auth.index"))
        else:
            flash("Incorrect email or password.", "error")
    return render_template("form.html", title="Log in", form=form, submit="Log in",
                           footer_link=(url_for("auth.register"), "New here? Request to join"))


@bp.route("/logout", methods=["POST"])
@login_required
def logout():
    logout_user()
    flash("You have been logged out.", "info")
    return redirect(url_for("auth.login"))


@bp.route("/join", methods=["GET", "POST"])
@limiter.limit("10 per hour", methods=["POST"])
def register():
    if current_user.is_authenticated:
        return redirect(url_for("auth.index"))
    form = RegisterForm()
    form.member_title.choices = [("", "No role")] + [
        (role.name, role.name) for role in ClubRole.query.order_by(ClubRole.name).all()
    ]
    configure_location_choices(form)
    if form.validate_on_submit():
        data = process_image(form.image.data)
        if data is None:
            form.image.errors.append("We couldn't read that image. Try a different JPG or PNG.")
        else:
            u = User(full_name=form.full_name.data, email=form.email.data.lower(), phone=form.phone.data,
                     member_title=form.member_title.data or "", place_of_work=form.place_of_work.data or "",
                     wilaya=form.wilaya.data, commune=form.commune.data,
                     role="member", status="pending",
                     equipment="\n".join(parse_equipment(form.equipment.data)),
                     image_data=data, has_image=True, image_version=1)
            u.set_password(form.password.data)
            db.session.add(u)
            db.session.commit()
            flash("Thanks! Your registration was sent. An admin will review it, then you can log in.", "success")
            return redirect(url_for("auth.login"))
    return render_template("form.html", title="Request to join", form=form, submit="Send registration",
                           has_file=True, footer_link=(url_for("auth.login"), "Already approved? Log in"))


@bp.route("/avatar/<int:uid>")
@login_required
def avatar(uid):
    u = User.query.options(undefer(User.image_data)).filter_by(id=uid).first_or_404()
    if not u.has_image or not u.image_data:
        abort(404)
    resp = Response(u.image_data, mimetype="image/jpeg")
    resp.headers["Cache-Control"] = "private, max-age=86400"
    return resp
