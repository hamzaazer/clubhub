import base64
from io import BytesIO

from flask import Blueprint, Response, abort, flash, redirect, render_template, request, url_for
from flask_login import current_user

from . import db
from .forms import AdminForm, ClubRoleForm, CriterionForm, SettingsForm
from .models import (ClubRole, Criterion, GlobalCriterion, PERMISSIONS, Project, Score, User,
                     get_setting, set_setting)
from .utils import perm_required, process_logo, role_required

bp = Blueprint("owner", __name__, url_prefix="/owner")


@bp.route("/roles", methods=["GET", "POST"])
@role_required("owner")
def roles():
    form = ClubRoleForm()
    if form.validate_on_submit():
        name = form.name.data
        duplicate = ClubRole.query.filter(db.func.lower(ClubRole.name) == name.lower()).first()
        if duplicate:
            form.name.errors.append("That club role already exists.")
        else:
            db.session.add(ClubRole(name=name))
            db.session.commit()
            flash("Club role added.", "success")
            return redirect(url_for("owner.roles"))
    return render_template("owner_roles.html", form=form,
                           roles=ClubRole.query.order_by(ClubRole.name).all())


@bp.post("/roles/<int:role_id>/delete")
@role_required("owner")
def role_delete(role_id):
    role = db.get_or_404(ClubRole, role_id)
    User.query.filter_by(member_title=role.name).update({User.member_title: ""})
    db.session.delete(role)
    db.session.commit()
    flash("Club role removed. Members assigned to it now have no role.", "success")
    return redirect(url_for("owner.roles"))


@bp.route("/admins")
@role_required("owner")
def admins():
    return render_template("owner_admins.html", admins=User.query.filter_by(role="admin").order_by(User.full_name).all())


@bp.route("/admins/new", methods=["GET", "POST"])
@role_required("owner")
def admin_new():
    form = AdminForm()
    if form.validate_on_submit():
        if not form.password.data:
            form.password.errors.append("Set a password for the new admin.")
        else:
            a = User(role="admin", status="approved", full_name=form.full_name.data,
                     email=form.email.data.lower(), phone=form.phone.data or "")
            for p in PERMISSIONS:
                setattr(a, p, getattr(form, p).data)
            a.set_password(form.password.data)
            db.session.add(a)
            db.session.commit()
            flash("Admin added.", "success")
            return redirect(url_for("owner.admins"))
    return render_template("form.html", title="Add admin", form=form, submit="Add admin",
                           back=url_for("owner.admins"))


@bp.route("/admins/<int:uid>", methods=["GET", "POST"])
@role_required("owner")
def admin_edit(uid):
    a = db.get_or_404(User, uid)
    if a.role != "admin":
        abort(404)
    form = AdminForm(obj=a, user_id=a.id)
    if form.validate_on_submit():
        a.full_name, a.email, a.phone = form.full_name.data, form.email.data.lower(), form.phone.data or ""
        for p in PERMISSIONS:
            setattr(a, p, getattr(form, p).data)
        if form.password.data:
            a.set_password(form.password.data)
        db.session.commit()
        flash("Admin updated.", "success")
        return redirect(url_for("owner.admins"))
    return render_template("form.html", title="Edit admin", form=form, submit="Save changes",
                           back=url_for("owner.admins"))


@bp.post("/admins/<int:uid>/delete")
@role_required("owner")
def admin_delete(uid):
    a = db.get_or_404(User, uid)
    if a.role != "admin":
        abort(404)
    db.session.delete(a)
    db.session.commit()
    flash("Admin removed.", "success")
    return redirect(url_for("owner.admins"))


@bp.route("/settings", methods=["GET", "POST"])
@perm_required()
def settings():
    can_manage_settings = current_user.has_perm("manage_settings")
    can_manage_criteria = current_user.has_perm("manage_global_criteria")
    if not (can_manage_settings or can_manage_criteria):
        abort(403)
    if request.method == "POST" and not can_manage_settings:
        abort(403)
    form = SettingsForm(club_name=get_setting("club_name", "ClubHub"))
    if form.validate_on_submit():
        logo_data = process_logo(form.logo.data) if form.logo.data else None
        if form.logo.data and logo_data is None:
            form.logo.errors.append("We couldn't read that image. Try a different JPG, PNG or WebP file.")
        if not form.logo.errors:
            set_setting("club_name", form.club_name.data)
            if logo_data:
                set_setting("club_logo", base64.b64encode(logo_data).decode("ascii"))
                set_setting("club_logo_version", str(int(get_setting("club_logo_version", "0")) + 1))
            elif form.remove_logo.data:
                set_setting("club_logo", "")
                set_setting("club_logo_version", str(int(get_setting("club_logo_version", "0")) + 1))
            flash("Club settings saved.", "success")
            return redirect(url_for("owner.settings"))
    return render_template("owner_settings.html", form=form, criteria_form=CriterionForm(),
                           global_criteria=GlobalCriterion.query.order_by(GlobalCriterion.id).all(),
                           has_club_logo=bool(get_setting("club_logo")),
                           can_manage_settings=can_manage_settings,
                           can_manage_criteria=can_manage_criteria)


@bp.get("/logo")
def club_logo():
    encoded = get_setting("club_logo")
    if not encoded:
        abort(404)
    try:
        data = base64.b64decode(encoded, validate=True)
    except (ValueError, base64.binascii.Error):
        abort(404)
    response = Response(data, mimetype="image/png")
    response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@bp.post("/settings/global-criteria")
@perm_required("manage_global_criteria")
def global_criterion_add():
    form = CriterionForm()
    if form.validate_on_submit():
        global_criterion = GlobalCriterion(name=form.name.data, max_mark=round(form.max_mark.data, 2))
        db.session.add(global_criterion)
        db.session.flush()
        for project in Project.query.all():
            db.session.add(Criterion(project_id=project.id, global_id=global_criterion.id,
                                     name=global_criterion.name, max_mark=global_criterion.max_mark))
        db.session.commit()
        flash("Global scoring criterion added to all projects.", "success")
    else:
        errors = [error for field_errors in form.errors.values() for error in field_errors]
        flash(errors[0] if errors else "Check the criterion fields.", "error")
    return redirect(url_for("owner.settings"))


@bp.post("/settings/global-criteria/<int:criterion_id>")
@perm_required("manage_global_criteria")
def global_criterion_edit(criterion_id):
    global_criterion = db.get_or_404(GlobalCriterion, criterion_id)
    form = CriterionForm()
    if form.validate_on_submit():
        name, max_mark = form.name.data, round(form.max_mark.data, 2)
        highest_mark = (db.session.query(db.func.max(Score.mark))
                        .join(Criterion, Criterion.id == Score.criterion_id)
                        .filter(Criterion.global_id == global_criterion.id).scalar())
        if highest_mark is not None and max_mark < highest_mark:
            flash(f"Maximum mark cannot be lower than an existing mark ({highest_mark:g}).", "error")
        else:
            global_criterion.name, global_criterion.max_mark = name, max_mark
            Criterion.query.filter_by(global_id=global_criterion.id).update(
                {Criterion.name: name, Criterion.max_mark: max_mark}, synchronize_session=False)
            db.session.commit()
            flash("Global scoring criterion updated across all projects.", "success")
    else:
        errors = [error for field_errors in form.errors.values() for error in field_errors]
        flash(errors[0] if errors else "Check the criterion fields.", "error")
    return redirect(url_for("owner.settings"))


@bp.post("/settings/global-criteria/<int:criterion_id>/delete")
@perm_required("manage_global_criteria")
def global_criterion_delete(criterion_id):
    global_criterion = db.get_or_404(GlobalCriterion, criterion_id)
    has_marks = (db.session.query(Score.id).join(Criterion, Criterion.id == Score.criterion_id)
                 .filter(Criterion.global_id == global_criterion.id).first())
    if has_marks:
        flash("This criterion has saved marks. Remove those marks from projects before deleting it.", "error")
    else:
        Criterion.query.filter_by(global_id=global_criterion.id).delete(synchronize_session=False)
        db.session.delete(global_criterion)
        db.session.commit()
        flash("Global scoring criterion removed from all projects.", "success")
    return redirect(url_for("owner.settings"))
