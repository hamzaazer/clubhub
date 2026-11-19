from flask_wtf import FlaskForm
from flask_wtf.file import FileAllowed, FileField, FileRequired
from sqlalchemy import func
from wtforms import (BooleanField, DateField, FloatField, PasswordField, SelectField,
                     SelectMultipleField, StringField, TextAreaField, widgets)
from wtforms.validators import (DataRequired, Email, EqualTo, Length, NumberRange, Optional,
                                Regexp, ValidationError)

from .models import ClubRole, PERMISSIONS, User
from .locations import algeria_locations, wilaya_code

strip = [lambda v: v.strip() if isinstance(v, str) else v]
PHONE = Regexp(r"^\+?[0-9 ()\-]{7,20}$", message="Enter a valid phone number, e.g. +213 555 12 34 56.")
IMAGE = FileAllowed(["jpg", "jpeg", "png", "webp"], "Images only (JPG, PNG or WebP).")


def unique_email(form, field):
    q = User.query.filter(func.lower(User.email) == field.data.strip().lower())
    if getattr(form, "user_id", None):
        q = q.filter(User.id != form.user_id)
    if q.first():
        raise ValidationError("This email address is already registered.")


class MultiCheckboxField(SelectMultipleField):
    widget = widgets.ListWidget(prefix_label=False)
    option_widget = widgets.CheckboxInput()


class LoginForm(FlaskForm):
    email = StringField("Email", filters=strip, validators=[DataRequired(), Email()])
    password = PasswordField("Password", validators=[DataRequired()])


class RegisterForm(FlaskForm):
    full_name = StringField("Full name", filters=strip, validators=[DataRequired(), Length(3, 120)])
    member_title = SelectField("Club role", choices=[], validators=[Optional()],
                               description="Choose a role created by the club owner.")
    place_of_work = StringField("Place of work", filters=strip, validators=[Optional(), Length(max=150)])
    wilaya = SelectField("Wilaya", choices=[], validators=[DataRequired("Choose a wilaya.")])
    commune = SelectField("Commune", choices=[], validators=[DataRequired("Choose a commune.")])
    email = StringField("Email address", filters=strip, validators=[DataRequired(), Email(), Length(max=255), unique_email])
    phone = StringField("Phone number", filters=strip, validators=[DataRequired(), PHONE])
    equipment = TextAreaField("Equipment you own", filters=strip, validators=[Length(max=1500)],
                              description="One item per line, e.g. Canon EOS 90D camera, tripod, drone.")
    image = FileField("Profile image", validators=[FileRequired("Please add a profile image."), IMAGE])
    password = PasswordField("Password", validators=[DataRequired(), Length(8, 128, message="Use at least 8 characters.")])
    confirm = PasswordField("Confirm password", validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])


class ProfileForm(FlaskForm):
    full_name = StringField("Full name", filters=strip, validators=[DataRequired(), Length(3, 120)],
                            description="Changing your name needs admin approval.")
    member_title = SelectField("Club role", choices=[], validators=[Optional()],
                               description="Choose a role created by the club owner.")
    place_of_work = StringField("Place of work", filters=strip, validators=[Optional(), Length(max=150)])
    wilaya = SelectField("Wilaya", choices=[], validators=[DataRequired("Choose a wilaya.")])
    commune = SelectField("Commune", choices=[], validators=[DataRequired("Choose a commune.")])
    email = StringField("Email address", filters=strip, validators=[DataRequired(), Email(), Length(max=255), unique_email],
                        description="Changing your email needs admin approval.")
    phone = StringField("Phone number", filters=strip, validators=[DataRequired(), PHONE])
    equipment = TextAreaField("Equipment you own", filters=strip, validators=[Length(max=1500)],
                              description="One item per line.")
    image = FileField("New profile image", validators=[IMAGE], description="Leave empty to keep your current image.")

    def __init__(self, *a, user_id=None, **k):
        super().__init__(*a, **k)
        self.user_id = user_id
        self.member_title.choices = club_role_choices()
        configure_location_choices(self)


def club_role_choices():
    return [("", "No role")] + [(role.name, role.name) for role in ClubRole.query.order_by(ClubRole.name).all()]


def configure_location_choices(form):
    locations = algeria_locations()
    form.wilaya.choices = [("", "Select wilaya")] + [
        (wilaya_code(item["code"]), item["name"]) for item in locations
    ]
    selected_wilaya = wilaya_code(form.wilaya.data)
    selected = next((item for item in locations if wilaya_code(item["code"]) == selected_wilaya), None)
    communes = selected["communes"] if selected else []
    form.commune.choices = [("", "Select commune")] + [
        (commune["name"], commune["name"]) for commune in communes
    ]


class ChangePasswordForm(FlaskForm):
    current = PasswordField("Current password", validators=[DataRequired()])
    password = PasswordField("New password", validators=[DataRequired(), Length(8, 128, message="Use at least 8 characters.")])
    confirm = PasswordField("Confirm new password", validators=[DataRequired(), EqualTo("password", "Passwords do not match.")])


class ProjectForm(FlaskForm):
    title = StringField("Project title", filters=strip, validators=[DataRequired(), Length(3, 150)])
    description = TextAreaField("Description", filters=strip, validators=[Length(max=4000)])


class CriterionForm(FlaskForm):
    name = StringField("Criterion", filters=strip, validators=[DataRequired(), Length(2, 120)])
    max_mark = FloatField("Maximum mark", validators=[DataRequired("Enter a number."), NumberRange(0.5, 1000)])


class TaskForm(FlaskForm):
    title = StringField("Task title", filters=strip, validators=[DataRequired(), Length(3, 150)])
    description = TextAreaField("Instructions", filters=strip, validators=[Length(max=4000)])
    due_date = DateField("Due date (optional)", validators=[Optional()])
    assignees = MultiCheckboxField("Send to", coerce=int, validators=[DataRequired("Pick at least one member.")])


class ResponseForm(FlaskForm):
    message = TextAreaField("Your reply or progress update", filters=strip,
                            validators=[DataRequired(), Length(2, 3000)])
    status = SelectField("Progress", choices=[("in_progress", "In progress"), ("done", "Done"), ("open", "Not started")])


class AdminForm(FlaskForm):
    full_name = StringField("Full name", filters=strip, validators=[DataRequired(), Length(3, 120)])
    email = StringField("Email address", filters=strip, validators=[DataRequired(), Email(), Length(max=255), unique_email])
    phone = StringField("Phone number (optional)", filters=strip, validators=[Optional(), PHONE])
    password = PasswordField("Password", validators=[Optional(), Length(8, 128, message="Use at least 8 characters.")],
                             description="Required for new admins. When editing, leave empty to keep the current password.")
    approve_members = BooleanField(PERMISSIONS["approve_members"])
    manage_projects = BooleanField(PERMISSIONS["manage_projects"])
    manage_tasks = BooleanField(PERMISSIONS["manage_tasks"])
    manage_leaderboard = BooleanField(PERMISSIONS["manage_leaderboard"])

    def __init__(self, *a, user_id=None, **k):
        super().__init__(*a, **k)
        self.user_id = user_id


class SettingsForm(FlaskForm):
    club_name = StringField("Club name", filters=strip, validators=[DataRequired(), Length(2, 60)])
    logo = FileField("Club logo", validators=[IMAGE], description="Optional JPG, PNG or WebP image.")
    remove_logo = BooleanField("Remove current logo")


class ClubRoleForm(FlaskForm):
    name = StringField("Role name", filters=strip, validators=[DataRequired(), Length(2, 80)])
