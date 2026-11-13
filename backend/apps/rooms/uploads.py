"""Upload checks shared by room photos and booking documents: type by content, size cap, random names."""

import uuid

from django.conf import settings
from django.core.files.storage import storages
from PIL import Image, UnidentifiedImageError
from rest_framework.exceptions import ValidationError

SIGNATURES = {
    b"%PDF-": ("pdf", "application/pdf"),
    b"\xff\xd8\xff": ("jpg", "image/jpeg"),
    b"\x89PNG\r\n\x1a\n": ("png", "image/png"),
}
# Refuse decompression bombs well before Pillow's own (much higher) limit.
Image.MAX_IMAGE_PIXELS = 50_000_000


def private_storage():
    return storages["private"]


def sniff(upload, *, allow_pdf=True):
    """Returns (extension, content_type) from the file's bytes, never from its name or declared type."""
    if upload is None:
        raise ValidationError({"file": ["Choose a file to upload."]})
    if upload.size > settings.UPLOAD_MAX_BYTES:
        raise ValidationError({"file": [f"The file is larger than {settings.UPLOAD_MAX_BYTES // (1024 * 1024)} MB."]})
    head = upload.read(8)
    upload.seek(0)
    kind = next((kind for signature, kind in SIGNATURES.items() if head.startswith(signature)), None)
    if kind is None or (kind[0] == "pdf" and not allow_pdf):
        allowed = "JPG, PNG or PDF" if allow_pdf else "JPG or PNG"
        raise ValidationError({"file": [f"Only {allowed} files are accepted."]})
    ext, content_type = kind
    if ext != "pdf":
        try:
            Image.open(upload).verify()
        except (UnidentifiedImageError, Image.DecompressionBombError, OSError, SyntaxError) as exc:
            raise ValidationError({"file": ["That image could not be read."]}) from exc
        finally:
            upload.seek(0)
    return ext, content_type


def store_private(upload, folder, ext):
    """Saves under a random name; the client's filename is never used."""
    return private_storage().save(f"{folder}/{uuid.uuid4().hex}.{ext}", upload)
