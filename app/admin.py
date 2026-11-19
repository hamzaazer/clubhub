import secrets
from datetime import date

from flask import Blueprint, Response, abort, flash, jsonify, redirect, render_template, request, url_for
from flask_login import current_user
from sqlalchemy import func

from . import db
from .forms import (CommunityEventForm, CriterionForm, GalleryPhotoForm, HomepageContentForm,
                    LeaderForm, PartnershipForm, ProjectForm, TaskForm)
from .locations import algeria_locations, wilaya_code
from .models import (Criterion, PendingChange, Project, ProjectMember, Score, Task, TaskAssignment,
                     ClubRole, CommunityEvent, GalleryPhoto, GlobalCriterion, Leader, Partnership,
                     User, get_setting, leaderboard, member_rank, set_setting)
from .utils import perm_required, process_image, process_logo, role_required

bp = Blueprint("admin", __name__, url_prefix="/admin")


def approved_members():
    return User.query.filter_by(role="member", status="approved").order_by(func.lower(User.full_name)).all()


def first_error(form):
    for errs in form.errors.values():
        return errs[0]
    return "Please check the form."


# ---------- dashboard: registrations + profile changes ----------
@bp.route("/")
@perm_required()
def dashboard():
    can = current_user.has_perm("approve_members")
    pending = (User.query.filter_by(role="member", status="pending").order_by(User.created_at).all() if can else [])
    changes = (PendingChange.query.filter_by(status="pending").order_by(PendingChange.created_at).all() if can else [])
    stats = {"members": User.query.filter_by(role="member", status="approved").count(),
             "projects": Project.query.count(), "tasks": Task.query.count()}
    return render_template("admin_dashboard.html", pending=pending, changes=changes, stats=stats)


@bp.post("/members/<int:uid>/<action>")
@perm_required("approve_members")
def decide_member(uid, action):
    u = db.get_or_404(User, uid)
    if action not in ("approve", "reject") or u.role != "member" or u.status != "pending":
        abort(400)
    u.status = "approved" if action == "approve" else "rejected"
    db.session.commit()
    flash(f"{u.full_name} was {u.status}.", "success")
    return redirect(url_for("admin.dashboard"))


@bp.post("/changes/<int:cid>/<action>")
@perm_required("approve_members")
def decide_change(cid, action):
    c = db.get_or_404(PendingChange, cid)
    if action not in ("approve", "reject") or c.status != "pending":
        abort(400)
    if action == "approve":
        if c.field == "email":
            taken = User.query.filter(func.lower(User.email) == c.new_value.lower(), User.id != c.user_id).first()
            if taken:
                c.status = "rejected"
                db.session.commit()
                flash("That email is now used by another account, so the change was rejected.", "error")
                return redirect(url_for("admin.dashboard"))
            c.user.email = c.new_value.lower()
        else:
            c.user.full_name = c.new_value
        c.status = "approved"
    else:
        c.status = "rejected"
    db.session.commit()
    flash("Change " + c.status + ".", "success")
    return redirect(url_for("admin.dashboard"))


# ---------- members ----------
@bp.route("/members")
@perm_required()
def members():
    query, filters = member_query()
    return render_template("admin_members.html", members=query.order_by(func.lower(User.full_name)).all(),
                           **filters)


def member_query():
    status = request.args.get("status", "approved")
    status = status if status in ("approved", "pending", "rejected") else "approved"
    q = request.args.get("q", "").strip()[:60]
    selected_wilaya = request.args.get("wilaya", "")
    locations = algeria_locations()
    known_wilayas = {wilaya_code(item["code"]): item for item in locations}
    if selected_wilaya not in known_wilayas:
        selected_wilaya = ""
    selected_commune = request.args.get("commune", "")
    valid_communes = ({commune["name"] for commune in known_wilayas[selected_wilaya]["communes"]}
                      if selected_wilaya else set())
    if selected_commune not in valid_communes:
        selected_commune = ""
    member_title = request.args.get("member_title", "")
    role_names = {role.name for role in ClubRole.query.order_by(ClubRole.name).all()}
    if member_title not in role_names:
        member_title = ""
    query = User.query.filter_by(role="member", status=status)
    if q:
        query = query.filter(db.or_(User.full_name.ilike(f"%{q}%"), User.email.ilike(f"%{q}%")))
    if selected_wilaya:
        query = query.filter_by(wilaya=selected_wilaya)
    if selected_commune:
        query = query.filter_by(commune=selected_commune)
    if member_title:
        query = query.filter_by(member_title=member_title)
    filters = {"status": status, "q": q, "member_title": member_title, "wilaya": selected_wilaya,
               "commune": selected_commune, "wilayas": locations,
               "communes": known_wilayas[selected_wilaya]["communes"] if selected_wilaya else [],
               "club_roles": ClubRole.query.order_by(ClubRole.name).all()}
    return query, filters


@bp.get("/members/live")
@perm_required()
def members_live():
    query, _ = member_query()
    entries = []
    for u in query.order_by(func.lower(User.full_name)).all():
        location = f"{u.commune}, Wilaya {u.wilaya}" if u.commune and u.wilaya else ""
        entries.append({
            "id": u.id,
            "href": url_for("admin.member", uid=u.id),
            "name": u.full_name,
            "email": u.email,
            "club_role": u.member_title or "",
            "location": location,
            "status": u.status,
            "has_image": bool(u.has_image),
            "avatar_url": url_for("auth.avatar", uid=u.id, v=u.image_version) if u.has_image else "",
        })
    return jsonify(members=entries)


@bp.route("/members/<int:uid>")
@perm_required()
def member(uid):
    u = db.get_or_404(User, uid)
    if u.role != "member":
        abort(404)
    return render_template("admin_member.html", u=u, rank=member_rank(uid),
                           parts=ProjectMember.query.filter_by(user_id=uid).all(),
                           tasks=TaskAssignment.query.filter_by(user_id=uid).order_by(TaskAssignment.id.desc()).all())


@bp.get("/members/<int:uid>/live")
@perm_required()
def member_live(uid):
    u = db.get_or_404(User, uid)
    if u.role != "member":
        abort(404)
    return jsonify({
        "full_name": u.full_name,
        "status": u.status,
        "member_title": u.member_title or "Not set",
        "email": u.email,
        "phone": u.phone or "",
        "place_of_work": u.place_of_work or "Not set",
        "wilaya": u.wilaya or "Not set",
        "commune": u.commune or "Not set",
        "equipment": ", ".join(u.equipment_list) or "None listed",
    })


@bp.post("/members/<int:uid>/reset-password")
@perm_required("approve_members")
def reset_password(uid):
    u = db.get_or_404(User, uid)
    if u.role != "member":
        abort(404)
    temp = secrets.token_urlsafe(9)
    u.set_password(temp)
    db.session.commit()
    flash(f"Temporary password for {u.full_name}: {temp} — share it privately and ask them to change it.", "info")
    return redirect(url_for("admin.member", uid=uid))


@bp.post("/members/<int:uid>/delete")
@role_required("owner")
def delete_member(uid):
    u = db.get_or_404(User, uid)
    if u.role != "member":
        abort(404)
    db.session.delete(u)
    db.session.commit()
    flash("Member removed with all their data.", "success")
    return redirect(url_for("admin.members"))


# ---------- projects ----------
@bp.route("/projects")
@perm_required("manage_projects")
def projects():
    return render_template("admin_projects.html", projects=Project.query.order_by(Project.id.desc()).all())


@bp.route("/projects/new", methods=["GET", "POST"])
@perm_required("manage_projects")
def project_new():
    form = ProjectForm()
    if form.validate_on_submit():
        p = Project(title=form.title.data, description=form.description.data)
        db.session.add(p)
        db.session.flush()
        for global_criterion in GlobalCriterion.query.order_by(GlobalCriterion.id).all():
            db.session.add(Criterion(project_id=p.id, global_id=global_criterion.id,
                                     name=global_criterion.name, max_mark=global_criterion.max_mark))
        db.session.commit()
        flash("Project created. Add participants and criteria next.", "success")
        return redirect(url_for("admin.project", pid=p.id))
    return render_template("form.html", title="New project", form=form, submit="Create project",
                           back=url_for("admin.projects"))


@bp.route("/projects/<int:pid>/edit", methods=["GET", "POST"])
@perm_required("manage_projects")
def project_edit(pid):
    p = db.get_or_404(Project, pid)
    form = ProjectForm(obj=p)
    if form.validate_on_submit():
        p.title, p.description = form.title.data, form.description.data
        db.session.commit()
        flash("Project updated.", "success")
        return redirect(url_for("admin.project", pid=pid))
    return render_template("form.html", title="Edit project", form=form, submit="Save changes",
                           back=url_for("admin.project", pid=pid))


@bp.route("/projects/<int:pid>")
@perm_required("manage_projects")
def project(pid):
    p = db.get_or_404(Project, pid)
    marks = {(s.user_id, s.criterion_id): s.mark for s in Score.query.filter_by(project_id=pid)}
    return render_template("admin_project.html", p=p, candidates=approved_members(),
                           pm_ids={m.user_id for m in p.members}, marks=marks, cform=CriterionForm())


@bp.post("/projects/<int:pid>/delete")
@perm_required("manage_projects")
def project_delete(pid):
    db.session.delete(db.get_or_404(Project, pid))
    db.session.commit()
    flash("Project deleted.", "success")
    return redirect(url_for("admin.projects"))


@bp.post("/projects/<int:pid>/participants")
@perm_required("manage_projects")
def set_participants(pid):
    p = db.get_or_404(Project, pid)
    valid = {u.id for u in approved_members()}
    wanted = {int(x) for x in request.form.getlist("members") if x.isdigit()} & valid
    current = {m.user_id: m for m in p.members}
    for uid in wanted - set(current):
        db.session.add(ProjectMember(project_id=pid, user_id=uid))
    for uid in set(current) - wanted:
        db.session.delete(current[uid])
        Score.query.filter_by(project_id=pid, user_id=uid).delete()
    db.session.commit()
    flash("Participants updated.", "success")
    return redirect(url_for("admin.project", pid=pid))


@bp.post("/projects/<int:pid>/criteria")
@perm_required("manage_projects")
def criterion_add(pid):
    db.get_or_404(Project, pid)
    form = CriterionForm()
    if form.validate_on_submit():
        db.session.add(Criterion(project_id=pid, name=form.name.data, max_mark=round(form.max_mark.data, 2)))
        db.session.commit()
        flash("Criterion added.", "success")
    else:
        flash(first_error(form), "error")
    return redirect(url_for("admin.project", pid=pid))


@bp.post("/projects/<int:pid>/criteria/<int:cid>/delete")
@perm_required("manage_projects")
def criterion_delete(pid, cid):
    c = db.get_or_404(Criterion, cid)
    if c.project_id != pid:
        abort(404)
    db.session.delete(c)
    db.session.commit()
    flash("Criterion removed.", "success")
    return redirect(url_for("admin.project", pid=pid))


@bp.post("/projects/<int:pid>/evaluate")
@perm_required("manage_projects")
def evaluate(pid):
    p = db.get_or_404(Project, pid)
    existing = {(s.user_id, s.criterion_id): s for s in Score.query.filter_by(project_id=pid)}
    errors, updates = [], []
    for m in p.members:
        for c in p.criteria:
            raw = request.form.get(f"mark_{m.user_id}_{c.id}", "").strip()
            if raw == "":
                updates.append((m, c, None))
                continue
            try:
                v = round(float(raw), 2)
            except ValueError:
                errors.append(f"{m.user.full_name} / {c.name}: enter a number.")
                continue
            if not 0 <= v <= c.max_mark:
                errors.append(f"{m.user.full_name} / {c.name}: must be between 0 and {c.max_mark:g}.")
            else:
                updates.append((m, c, v))
    if errors:
        flash(" ".join(errors[:4]) + " Nothing was saved.", "error")
        return redirect(url_for("admin.project", pid=pid))
    for m in p.members:
        m.contribution = request.form.get(f"contribution_{m.user_id}", "").strip()[:3000]
        m.note = request.form.get(f"note_{m.user_id}", "").strip()[:3000]
    for m, c, v in updates:
        s = existing.get((m.user_id, c.id))
        if v is None:
            if s:
                db.session.delete(s)
        elif s:
            s.mark = v
        else:
            db.session.add(Score(project_id=pid, user_id=m.user_id, criterion_id=c.id, mark=v))
    db.session.commit()
    flash("Evaluation saved.", "success")
    return redirect(url_for("admin.project", pid=pid))


# ---------- tasks ----------
@bp.route("/tasks")
@perm_required("manage_tasks")
def tasks():
    return render_template("admin_tasks.html", tasks=Task.query.order_by(Task.id.desc()).all())


@bp.route("/tasks/new", methods=["GET", "POST"])
@perm_required("manage_tasks")
def task_new():
    form = TaskForm()
    form.assignees.choices = [(u.id, u.full_name) for u in approved_members()]
    if form.validate_on_submit():
        t = Task(title=form.title.data, description=form.description.data, due_date=form.due_date.data,
                 created_by=current_user.id)
        db.session.add(t)
        db.session.flush()
        for uid in form.assignees.data:
            db.session.add(TaskAssignment(task_id=t.id, user_id=uid))
        db.session.commit()
        flash("Task sent.", "success")
        return redirect(url_for("admin.task", tid=t.id))
    return render_template("form.html", title="Send a task", form=form, submit="Send task",
                           back=url_for("admin.tasks"))


@bp.route("/tasks/<int:tid>")
@perm_required("manage_tasks")
def task(tid):
    return render_template("admin_task.html", t=db.get_or_404(Task, tid))


@bp.post("/tasks/<int:tid>/delete")
@perm_required("manage_tasks")
def task_delete(tid):
    db.session.delete(db.get_or_404(Task, tid))
    db.session.commit()
    flash("Task deleted.", "success")
    return redirect(url_for("admin.tasks"))


# ---------- public community site ----------
@bp.route("/community")
@perm_required()
def community_site():
    content = {
        "hero_heading": get_setting("homepage_hero_heading", "Capture today. Create tomorrow."),
        "hero_copy": get_setting("homepage_hero_copy", "A local home for photographers, filmmakers, editors and curious creators in Mascara, Algeria."),
        "about_heading": get_setting("homepage_about_heading", "A club for people who see stories everywhere."),
        "about_copy": get_setting("homepage_about_copy", "VALiDO brings creative people together to learn, make and share. Join a photo walk, try a new technique, or make your first short film alongside a welcoming community."),
        "community_copy": get_setting("homepage_community_copy", "From first-time photographers to experienced creators, there is room to learn, contribute and make something together."),
        "instagram": get_setting("homepage_instagram", ""),
        "facebook": get_setting("homepage_facebook", ""),
        "youtube": get_setting("homepage_youtube", ""),
        "tiktok": get_setting("homepage_tiktok", ""),
    }
    content_form = HomepageContentForm(data=content)
    return render_template(
        "admin_community.html", content_form=content_form,
        leader_form=LeaderForm(), partnership_form=PartnershipForm(),
        event_form=CommunityEventForm(), gallery_form=GalleryPhotoForm(),
        leaders=Leader.query.order_by(Leader.sort_order, Leader.id).all(),
        partnerships=Partnership.query.order_by(Partnership.sort_order, Partnership.id).all(),
        events=CommunityEvent.query.order_by(CommunityEvent.event_date, CommunityEvent.id).all(),
        gallery=GalleryPhoto.query.order_by(GalleryPhoto.sort_order, GalleryPhoto.id).all(),
    )


@bp.post("/community/content")
@perm_required()
def community_content_save():
    form = HomepageContentForm()
    if form.validate_on_submit():
        for field in ("hero_heading", "hero_copy", "about_heading", "about_copy", "community_copy",
                      "instagram", "facebook", "youtube", "tiktok"):
            set_setting("homepage_" + field, getattr(form, field).data or "")
        flash("Homepage content saved.", "success")
    else:
        flash(first_error(form), "error")
    return redirect(url_for("admin.community_site"))


def _photo_upload(form, keep_square=True):
    upload = form.photo.data
    if not upload or not getattr(upload, "filename", ""):
        return None, None
    data = process_image(upload) if keep_square else process_logo(upload)
    return (data, "image/jpeg") if keep_square else (data, "image/png")


@bp.post("/community/leaders")
@perm_required()
def leader_add():
    form = LeaderForm()
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form)
        if not form.photo.data or not form.photo.data.filename:
            form.photo.errors.append("Add a portrait photo for this leader.")
        elif photo is None:
            form.photo.errors.append("We couldn't read that photo.")
        else:
            last = db.session.query(db.func.max(Leader.sort_order)).scalar() or 0
            db.session.add(Leader(name=form.name.data, title=form.title.data, photo_data=photo, has_photo=True,
                                  photo_type=photo_type or "image/jpeg", sort_order=last + 1))
            db.session.commit()
            flash("Leader added.", "success")
            return redirect(url_for("admin.community_site"))
    flash(first_error(form), "error")
    return redirect(url_for("admin.community_site"))


@bp.route("/community/leaders/<int:leader_id>", methods=["GET", "POST"])
@perm_required()
def leader_edit(leader_id):
    leader = db.get_or_404(Leader, leader_id)
    form = LeaderForm(obj=leader)
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form)
        if form.photo.data and form.photo.data.filename and photo is None:
            form.photo.errors.append("We couldn't read that photo.")
        else:
            leader.name, leader.title = form.name.data, form.title.data
            if photo:
                leader.photo_data, leader.photo_type, leader.has_photo = photo, photo_type, True
                leader.photo_version = (leader.photo_version or 0) + 1
            elif form.remove_photo.data:
                leader.photo_data, leader.photo_type, leader.has_photo = None, "image/jpeg", False
                leader.photo_version = (leader.photo_version or 0) + 1
            db.session.commit()
            flash("Leader updated.", "success")
            return redirect(url_for("admin.community_site"))
    return render_template("form.html", title="Edit leader", form=form, submit="Save changes",
                           has_file=True, back=url_for("admin.community_site"),
                           current_photo=url_for("admin.leader_photo", leader_id=leader.id,
                                                 v=leader.photo_version) if leader.has_photo else "")


@bp.post("/community/leaders/<int:leader_id>/delete")
@perm_required()
def leader_delete(leader_id):
    db.session.delete(db.get_or_404(Leader, leader_id))
    db.session.commit()
    flash("Leader removed.", "success")
    return redirect(url_for("admin.community_site"))


@bp.post("/community/leaders/<int:leader_id>/move/<direction>")
@perm_required()
def leader_move(leader_id, direction):
    leader = db.get_or_404(Leader, leader_id)
    leaders = Leader.query.order_by(Leader.sort_order, Leader.id).all()
    index = leaders.index(leader)
    target_index = index - 1 if direction == "up" else index + 1 if direction == "down" else index
    if 0 <= target_index < len(leaders) and target_index != index:
        neighbor = leaders[target_index]
        leader.sort_order, neighbor.sort_order = neighbor.sort_order, leader.sort_order
        db.session.commit()
    return redirect(url_for("admin.community_site"))


@bp.get("/community/leaders/<int:leader_id>/photo")
def leader_photo(leader_id):
    leader = db.get_or_404(Leader, leader_id)
    if not leader.has_photo or not leader.photo_data:
        abort(404)
    return Response(leader.photo_data, mimetype=leader.photo_type or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@bp.post("/community/partnerships")
@perm_required()
def partnership_add():
    form = PartnershipForm()
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form, keep_square=False)
        if form.photo.data and form.photo.data.filename and photo is None:
            form.photo.errors.append("We couldn't read that logo or photo.")
        else:
            last = db.session.query(db.func.max(Partnership.sort_order)).scalar() or 0
            db.session.add(Partnership(name=form.name.data, description=form.description.data or "",
                                       website=form.website.data or "", photo_data=photo,
                                       has_photo=bool(photo),
                                       photo_type=photo_type or "image/png", sort_order=last + 1))
            db.session.commit()
            flash("Collaboration added.", "success")
            return redirect(url_for("admin.community_site"))
    flash(first_error(form), "error")
    return redirect(url_for("admin.community_site"))


@bp.route("/community/partnerships/<int:partnership_id>", methods=["GET", "POST"])
@perm_required()
def partnership_edit(partnership_id):
    partnership = db.get_or_404(Partnership, partnership_id)
    form = PartnershipForm(obj=partnership)
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form, keep_square=False)
        if form.photo.data and form.photo.data.filename and photo is None:
            form.photo.errors.append("We couldn't read that logo or photo.")
        else:
            partnership.name, partnership.description = form.name.data, form.description.data or ""
            partnership.website = form.website.data or ""
            if photo:
                partnership.photo_data, partnership.photo_type, partnership.has_photo = photo, photo_type, True
                partnership.photo_version = (partnership.photo_version or 0) + 1
            elif form.remove_photo.data:
                partnership.photo_data, partnership.photo_type, partnership.has_photo = None, "image/png", False
                partnership.photo_version = (partnership.photo_version or 0) + 1
            db.session.commit()
            flash("Collaboration updated.", "success")
            return redirect(url_for("admin.community_site"))
    return render_template("form.html", title="Edit collaboration", form=form, submit="Save changes",
                           has_file=True, back=url_for("admin.community_site"),
                           current_photo=url_for("admin.partnership_photo", partnership_id=partnership.id,
                                                 v=partnership.photo_version) if partnership.has_photo else "")


@bp.post("/community/partnerships/<int:partnership_id>/delete")
@perm_required()
def partnership_delete(partnership_id):
    db.session.delete(db.get_or_404(Partnership, partnership_id))
    db.session.commit()
    flash("Collaboration removed.", "success")
    return redirect(url_for("admin.community_site"))


@bp.get("/community/partnerships/<int:partnership_id>/photo")
def partnership_photo(partnership_id):
    partnership = db.get_or_404(Partnership, partnership_id)
    if not partnership.has_photo or not partnership.photo_data:
        abort(404)
    return Response(partnership.photo_data, mimetype=partnership.photo_type or "image/png",
                    headers={"Cache-Control": "public, max-age=86400"})


@bp.post("/community/events")
@perm_required()
def event_add():
    form = CommunityEventForm()
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form)
        if form.photo.data and form.photo.data.filename and photo is None:
            form.photo.errors.append("We couldn't read that event photo.")
        else:
            db.session.add(CommunityEvent(title=form.title.data, description=form.description.data or "",
                                          event_date=form.event_date.data, event_time=form.event_time.data,
                                          location=form.location.data or "",
                                          link=form.link.data or "", photo_data=photo, has_photo=bool(photo),
                                          photo_type=photo_type or "image/jpeg"))
            db.session.commit()
            flash("Event added.", "success")
            return redirect(url_for("admin.community_site"))
    flash(first_error(form), "error")
    return redirect(url_for("admin.community_site"))


@bp.route("/community/events/<int:event_id>", methods=["GET", "POST"])
@perm_required()
def event_edit(event_id):
    event = db.get_or_404(CommunityEvent, event_id)
    form = CommunityEventForm(obj=event)
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form)
        if form.photo.data and form.photo.data.filename and photo is None:
            form.photo.errors.append("We couldn't read that event photo.")
        else:
            event.title, event.description = form.title.data, form.description.data or ""
            event.event_date, event.event_time = form.event_date.data, form.event_time.data
            event.location, event.link = form.location.data or "", form.link.data or ""
            if photo:
                event.photo_data, event.photo_type, event.has_photo = photo, photo_type, True
                event.photo_version = (event.photo_version or 0) + 1
            elif form.remove_photo.data:
                event.photo_data, event.photo_type, event.has_photo = None, "image/jpeg", False
                event.photo_version = (event.photo_version or 0) + 1
            db.session.commit()
            flash("Event updated.", "success")
            return redirect(url_for("admin.community_site"))
    return render_template("form.html", title="Edit event", form=form, submit="Save changes",
                           has_file=True, back=url_for("admin.community_site"),
                           current_photo=url_for("admin.event_photo", event_id=event.id,
                                                 v=event.photo_version) if event.has_photo else "")


@bp.post("/community/events/<int:event_id>/delete")
@perm_required()
def event_delete(event_id):
    db.session.delete(db.get_or_404(CommunityEvent, event_id))
    db.session.commit()
    flash("Event removed.", "success")
    return redirect(url_for("admin.community_site"))


@bp.get("/community/events/<int:event_id>/photo")
def event_photo(event_id):
    event = db.get_or_404(CommunityEvent, event_id)
    if not event.has_photo or not event.photo_data:
        abort(404)
    return Response(event.photo_data, mimetype=event.photo_type or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


@bp.post("/community/gallery")
@perm_required()
def gallery_add():
    form = GalleryPhotoForm()
    if form.validate_on_submit():
        photo, photo_type = _photo_upload(form)
        if not form.photo.data or not form.photo.data.filename:
            form.photo.errors.append("Choose a photo.")
        elif photo is None:
            form.photo.errors.append("We couldn't read that photo.")
        else:
            last = db.session.query(db.func.max(GalleryPhoto.sort_order)).scalar() or 0
            db.session.add(GalleryPhoto(caption=form.caption.data, link=form.link.data or "",
                                        photo_data=photo, has_photo=True, photo_type=photo_type, sort_order=last + 1))
            db.session.commit()
            flash("Gallery photo added.", "success")
            return redirect(url_for("admin.community_site"))
    flash(first_error(form), "error")
    return redirect(url_for("admin.community_site"))


@bp.post("/community/gallery/<int:photo_id>/delete")
@perm_required()
def gallery_delete(photo_id):
    db.session.delete(db.get_or_404(GalleryPhoto, photo_id))
    db.session.commit()
    flash("Gallery photo removed.", "success")
    return redirect(url_for("admin.community_site"))


@bp.get("/community/gallery/<int:photo_id>/photo")
def gallery_photo(photo_id):
    photo = db.get_or_404(GalleryPhoto, photo_id)
    if not photo.has_photo or not photo.photo_data:
        abort(404)
    return Response(photo.photo_data, mimetype=photo.photo_type or "image/jpeg",
                    headers={"Cache-Control": "public, max-age=86400"})


# ---------- leaderboard ----------
@bp.route("/leaderboard", methods=["GET", "POST"])
@perm_required("manage_leaderboard")
def board():
    rows = leaderboard()
    if request.method == "POST":
        ids = {r["user"].id for r in rows}
        bonuses, bad = {}, []
        for r in rows:
            raw = request.form.get(f"bonus_{r['user'].id}", "0").strip() or "0"
            try:
                v = int(raw)
                if not -10000 <= v <= 10000:
                    raise ValueError
                bonuses[r["user"]] = v
            except ValueError:
                bad.append(r["user"].full_name)
        if bad:
            flash("Bonus points must be whole numbers between -10000 and 10000: " + ", ".join(bad), "error")
            return redirect(url_for("admin.board"))
        for u, v in bonuses.items():
            u.bonus_points = v
        first = request.form.get("first_place", "0")
        db.session.commit()
        set_setting("first_place_user_id", first if first.isdigit() and int(first) in ids else "")
        flash("Leaderboard updated.", "success")
        return redirect(url_for("admin.board"))
    from .models import get_setting
    return render_template("admin_leaderboard.html", rows=rows, first=get_setting("first_place_user_id", "0"))
