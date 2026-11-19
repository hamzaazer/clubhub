import re
from functools import wraps
from io import BytesIO

from flask import abort
from flask_login import current_user
from PIL import Image, ImageOps

from . import login_manager

Image.MAX_IMAGE_PIXELS = 30_000_000


def role_required(*roles):
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


def perm_required(perm=None):
    """Admins (with the given permission) and the Owner (always)."""
    def deco(f):
        @wraps(f)
        def wrapper(*a, **k):
            if not current_user.is_authenticated:
                return login_manager.unauthorized()
            if current_user.role not in ("admin", "owner"):
                abort(403)
            if perm and not current_user.has_perm(perm):
                abort(403)
            return f(*a, **k)
        return wrapper
    return deco


def parse_equipment(text):
    items = []
    for part in re.split(r"[\n,;]+", text or ""):
        p = part.strip()[:60]
        if p and p.lower() not in [i.lower() for i in items]:
            items.append(p)
    return items[:30]


def process_image(file_storage):
    """Validate an upload, square-crop to 400px and re-encode as JPEG. Returns bytes or None."""
    try:
        Image.open(file_storage.stream).verify()
        file_storage.stream.seek(0)
        img = ImageOps.exif_transpose(Image.open(file_storage.stream)).convert("RGB")
        img = ImageOps.fit(img, (400, 400))
        buf = BytesIO()
        img.save(buf, "JPEG", quality=85, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def process_logo(file_storage):
    """Validate and resize a club logo without cropping its aspect ratio or transparency."""
    try:
        Image.open(file_storage.stream).verify()
        file_storage.stream.seek(0)
        img = ImageOps.exif_transpose(Image.open(file_storage.stream)).convert("RGBA")
        img.thumbnail((800, 400), Image.Resampling.LANCZOS)
        buf = BytesIO()
        img.save(buf, "PNG", optimize=True)
        return buf.getvalue()
    except Exception:
        return None
