from datetime import datetime

from flask import Blueprint, abort, flash, redirect, render_template, url_for
from flask_login import current_user, login_required

from . import db
from .forms import ChangePasswordForm, ProfileForm, ResponseForm, configure_location_choices
from .models import PendingChange, ProjectMember, TaskAssignment, TaskResponse, leaderboard, member_rank
from .utils import parse_equipment, process_image, role_required

bp = Blueprint("member", __name__)


@bp.route("/dashboard")
@role_required("member")
def dashboard():
    open_tasks = TaskAssignment.query.filter(TaskAssignment.user_id == current_user.id,
                                             TaskAssignment.status != "done").order_by(TaskAssignment.id.desc()).all()
    return render_template("member_dashboard.html", open_tasks=open_tasks, rank=member_rank(current_user.id),
                           project_count=ProjectMember.query.filter_by(user_id=current_user.id).count())


@bp.route("/profile", methods=["GET", "POST"])
@role_required("member")
def profile():
    u = current_user._get_current_object()
    form = ProfileForm(obj=u, user_id=u.id)
    configure_location_choices(form)
    if form.validate_on_submit():
        data = None
        if form.image.data:
            data = process_image(form.image.data)
            if data is None:
                form.image.errors.append("We couldn't read that image. Try a different JPG or PNG.")
        if not form.image.errors:
            u.phone = form.phone.data
            u.place_of_work = form.place_of_work.data or ""
            u.wilaya, u.commune = form.wilaya.data, form.commune.data
            u.member_title = form.member_title.data or ""
            u.equipment = "\n".join(parse_equipment(form.equipment.data))
            if data:
                u.image_data, u.has_image, u.image_version = data, True, (u.image_version or 0) + 1
            asked = False
            for field, value in (("full_name", form.full_name.data), ("email", form.email.data.lower())):
                if value != getattr(u, field):
                    PendingChange.query.filter_by(user_id=u.id, field=field, status="pending").delete()
                    db.session.add(PendingChange(user_id=u.id, field=field, new_value=value))
                    asked = True
            db.session.commit()
            flash("Profile saved." + (" Your name or email change is waiting for admin approval." if asked else ""),
                  "success")
            return redirect(url_for("member.profile"))
    pending = PendingChange.query.filter_by(user_id=u.id, status="pending").all()
    return render_template("profile.html", form=form, pending=pending)


@bp.route("/account/password", methods=["GET", "POST"])
@login_required
def password():
    form = ChangePasswordForm()
    if form.validate_on_submit():
        if not current_user.check_password(form.current.data):
            form.current.errors.append("That is not your current password.")
        else:
            current_user.set_password(form.password.data)
            db.session.commit()
            flash("Password updated.", "success")
            return redirect(url_for("auth.index"))
    return render_template("form.html", title="Change password", form=form, submit="Update password")


@bp.route("/tasks")
@role_required("member")
def tasks():
    items = TaskAssignment.query.filter_by(user_id=current_user.id).order_by(TaskAssignment.id.desc()).all()
    return render_template("member_tasks.html", items=items)


@bp.route("/tasks/<int:aid>", methods=["GET", "POST"])
@role_required("member")
def task(aid):
    a = db.get_or_404(TaskAssignment, aid)
    if a.user_id != current_user.id:
        abort(403)
    form = ResponseForm(status=a.status if a.status != "open" else "in_progress")
    if form.validate_on_submit():
        db.session.add(TaskResponse(assignment_id=a.id, message=form.message.data, status=form.status.data))
        a.status, a.updated_at = form.status.data, datetime.utcnow()
        db.session.commit()
        flash("Your update was sent.", "success")
        return redirect(url_for("member.task", aid=a.id))
    return render_template("member_task.html", a=a, form=form)


@bp.route("/projects")
@role_required("member")
def projects():
    items = ProjectMember.query.filter_by(user_id=current_user.id).order_by(ProjectMember.id.desc()).all()
    return render_template("member_projects.html", items=items)


@bp.route("/projects/<int:pid>")
@role_required("member")
def project(pid):
    pm = ProjectMember.query.filter_by(project_id=pid, user_id=current_user.id).first_or_404()
    return render_template("member_project.html", pm=pm)


@bp.route("/leaderboard")
@login_required
def board():
    return render_template("leaderboard.html", rows=leaderboard())
