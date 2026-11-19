import os
from datetime import datetime

from flask_login import UserMixin
from sqlalchemy.orm import deferred
from werkzeug.security import check_password_hash, generate_password_hash

from . import db, login_manager

PERMISSIONS = {
    "approve_members": "Approve or reject registrations and profile changes",
    "manage_projects": "Create projects, scoring criteria and marks",
    "manage_tasks": "Send tasks and read member replies",
    "manage_leaderboard": "Manage the leaderboard and first place",
}


class ClubRole(db.Model):
    __tablename__ = "club_roles"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(80), nullable=False, unique=True)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    full_name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), nullable=False, unique=True, index=True)
    phone = db.Column(db.String(30), default="")
    address = db.Column(db.String(255), default="")
    place_of_work = db.Column(db.String(150), default="")
    wilaya = db.Column(db.String(2), default="")
    commune = db.Column(db.String(100), default="")
    member_title = db.Column(db.String(80), default="")
    equipment = db.Column(db.Text, default="")
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(10), nullable=False, default="member")        # owner|admin|member
    status = db.Column(db.String(10), nullable=False, default="pending")     # pending|approved|rejected
    image_data = deferred(db.Column(db.LargeBinary))
    has_image = db.Column(db.Boolean, default=False)
    image_version = db.Column(db.Integer, default=0)
    bonus_points = db.Column(db.Integer, default=0)
    approve_members = db.Column(db.Boolean, default=False)
    manage_projects = db.Column(db.Boolean, default=False)
    manage_tasks = db.Column(db.Boolean, default=False)
    manage_leaderboard = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    memberships = db.relationship("ProjectMember", back_populates="user", cascade="all, delete-orphan")
    assignments = db.relationship("TaskAssignment", back_populates="user", cascade="all, delete-orphan")
    changes = db.relationship("PendingChange", back_populates="user", cascade="all, delete-orphan")
    scores = db.relationship("Score", back_populates="user", cascade="all, delete-orphan")

    @property
    def is_active(self):
        return self.status == "approved"

    def set_password(self, pw):
        self.password_hash = generate_password_hash(pw)

    def check_password(self, pw):
        return check_password_hash(self.password_hash, pw)

    def has_perm(self, perm):
        return self.role == "owner" or (self.role == "admin" and bool(getattr(self, perm, False)))

    @property
    def equipment_list(self):
        return [x for x in (self.equipment or "").split("\n") if x]


@login_manager.user_loader
def load_user(uid):
    u = db.session.get(User, int(uid))
    return u if u and u.status == "approved" else None


class Project(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default="")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    members = db.relationship("ProjectMember", back_populates="project", cascade="all, delete-orphan")
    criteria = db.relationship("Criterion", back_populates="project", cascade="all, delete-orphan",
                               order_by="Criterion.id")
    scores = db.relationship("Score", back_populates="project", cascade="all, delete-orphan")


class GlobalCriterion(db.Model):
    __tablename__ = "global_criteria"
    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    max_mark = db.Column(db.Float, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)


class ProjectMember(db.Model):
    __table_args__ = (db.UniqueConstraint("project_id", "user_id"),)
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    contribution = db.Column(db.Text, default="")
    note = db.Column(db.Text, default="")
    project = db.relationship("Project", back_populates="members")
    user = db.relationship("User", back_populates="memberships")

    def score_rows(self):
        marks = {s.criterion_id: s.mark for s in
                 Score.query.filter_by(project_id=self.project_id, user_id=self.user_id)}
        return [(c, marks.get(c.id)) for c in self.project.criteria]

    def totals(self):
        rows = self.score_rows()
        return (sum(m for _, m in rows if m is not None), sum(c.max_mark for c, _ in rows))


class Criterion(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    global_id = db.Column(db.Integer, db.ForeignKey("global_criteria.id"), nullable=True, index=True)
    name = db.Column(db.String(120), nullable=False)
    max_mark = db.Column(db.Float, nullable=False)
    project = db.relationship("Project", back_populates="criteria")
    global_source = db.relationship("GlobalCriterion")
    scores = db.relationship("Score", back_populates="criterion", cascade="all, delete-orphan")


class Score(db.Model):
    __table_args__ = (db.UniqueConstraint("project_id", "user_id", "criterion_id"),)
    id = db.Column(db.Integer, primary_key=True)
    project_id = db.Column(db.Integer, db.ForeignKey("project.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    criterion_id = db.Column(db.Integer, db.ForeignKey("criterion.id"), nullable=False)
    mark = db.Column(db.Float, nullable=False)
    project = db.relationship("Project", back_populates="scores")
    user = db.relationship("User", back_populates="scores")
    criterion = db.relationship("Criterion", back_populates="scores")


class Task(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(150), nullable=False)
    description = db.Column(db.Text, default="")
    due_date = db.Column(db.Date)
    created_by = db.Column(db.Integer)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignments = db.relationship("TaskAssignment", back_populates="task", cascade="all, delete-orphan")

    @property
    def sender_name(self):
        u = db.session.get(User, self.created_by) if self.created_by else None
        return u.full_name if u else "Club admin"


class TaskAssignment(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    task_id = db.Column(db.Integer, db.ForeignKey("task.id"), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    status = db.Column(db.String(12), default="open")  # open|in_progress|done
    updated_at = db.Column(db.DateTime, default=datetime.utcnow)
    task = db.relationship("Task", back_populates="assignments")
    user = db.relationship("User", back_populates="assignments")
    responses = db.relationship("TaskResponse", back_populates="assignment", cascade="all, delete-orphan",
                                order_by="TaskResponse.id")


class TaskResponse(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    assignment_id = db.Column(db.Integer, db.ForeignKey("task_assignment.id"), nullable=False)
    message = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(12), default="open")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    assignment = db.relationship("TaskAssignment", back_populates="responses")


class PendingChange(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False)
    field = db.Column(db.String(20), nullable=False)  # full_name|email
    new_value = db.Column(db.String(255), nullable=False)
    status = db.Column(db.String(10), default="pending")
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    user = db.relationship("User", back_populates="changes")


class Setting(db.Model):
    key = db.Column(db.String(50), primary_key=True)
    value = db.Column(db.Text)


def get_setting(key, default=None):
    s = db.session.get(Setting, key)
    return s.value if s and s.value else default


def set_setting(key, value):
    s = db.session.get(Setting, key)
    if s:
        s.value = value
    else:
        db.session.add(Setting(key=key, value=value))
    db.session.commit()


def leaderboard():
    """Ranked list: marks + bonus points; the admin-chosen first place is pinned to #1."""
    members = User.query.filter_by(role="member", status="approved").all()
    totals = dict(db.session.query(Score.user_id, db.func.sum(Score.mark)).group_by(Score.user_id).all())
    rows = [(u, round((totals.get(u.id) or 0) + (u.bonus_points or 0), 2)) for u in members]
    rows.sort(key=lambda r: (-r[1], r[0].full_name.lower()))
    first = get_setting("first_place_user_id")
    if first:
        idx = next((i for i, r in enumerate(rows) if str(r[0].id) == first), None)
        if idx:
            rows.insert(0, rows.pop(idx))
    return [{"rank": i + 1, "user": u, "points": p} for i, (u, p) in enumerate(rows)]


def member_rank(uid):
    return next((r for r in leaderboard() if r["user"].id == uid), None)


def make_owner(name, email, password):
    email = email.strip().lower()
    u = User.query.filter(db.func.lower(User.email) == email).first() or User(email=email)
    u.full_name, u.role, u.status = name.strip(), "owner", "approved"
    u.set_password(password)
    db.session.add(u)
    db.session.commit()


def seed_owner():
    """Create the first Owner from env vars (useful on hosts without a shell)."""
    email, pw = os.environ.get("OWNER_EMAIL"), os.environ.get("OWNER_PASSWORD")
    if email and pw and not User.query.filter_by(role="owner").first():
        make_owner(os.environ.get("OWNER_NAME", "Club Owner"), email, pw)
