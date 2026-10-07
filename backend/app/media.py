"""Image intake: normalize uploads and sign short-lived URLs so <img> tags can load them."""

import hashlib
import io
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import imagehash
import jwt
from PIL import Image, ImageOps, UnidentifiedImageError

from app.config import get_settings

MAX_EDGE = 1600  # enough detail for item recognition; keeps the database small
MAX_UPLOAD_BYTES = 15 * 1024 * 1024
EXIF_IFD = 0x8769
EXIF_DATETIME_ORIGINAL = 36867
EXIF_DATETIME = 306


class InvalidImage(ValueError):
    pass


@dataclass
class PreparedImage:
    jpeg: bytes
    width: int
    height: int
    sha256: str  # of the original upload, so re-uploads of the same file are detectable
    phash: str  # perceptual hash, so the same photo is matched even after resizing or re-compression
    captured_at: datetime | None


def _captured_at(img: Image.Image) -> datetime | None:
    exif = img.getexif()
    raw = exif.get_ifd(EXIF_IFD).get(EXIF_DATETIME_ORIGINAL) or exif.get(EXIF_DATETIME)
    try:
        return datetime.strptime(str(raw), "%Y:%m:%d %H:%M:%S").replace(tzinfo=UTC) if raw else None
    except ValueError:
        return None


def prepare_image(raw: bytes) -> PreparedImage:
    if len(raw) > MAX_UPLOAD_BYTES:
        raise InvalidImage("Image is larger than 15 MB")
    try:
        img = Image.open(io.BytesIO(raw))
        captured = _captured_at(img)
        img = ImageOps.exif_transpose(img).convert("RGB")
    except (UnidentifiedImageError, OSError) as e:
        raise InvalidImage("Not a readable image") from e
    img.thumbnail((MAX_EDGE, MAX_EDGE))
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=85)
    return PreparedImage(
        buf.getvalue(), img.width, img.height, hashlib.sha256(raw).hexdigest(), str(imagehash.phash(img)), captured
    )


def media_url(media_id: int) -> str:
    s = get_settings()
    token = jwt.encode(
        {"media": media_id, "exp": datetime.now(UTC) + timedelta(hours=s.token_ttl_hours)},
        s.secret_key,
        algorithm="HS256",
    )
    return f"/media/{media_id}?t={token}"


def media_token_valid(media_id: int, token: str) -> bool:
    try:
        return jwt.decode(token, get_settings().secret_key, algorithms=["HS256"])["media"] == media_id
    except (jwt.PyJWTError, KeyError):
        return False
