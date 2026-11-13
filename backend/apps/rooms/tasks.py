import io

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from django.db import transaction
from PIL import Image, ImageOps

from .models import RoomPhoto
from .uploads import private_storage


@shared_task
def process_room_photo(photo_id):
    """Builds WebP copies at three widths in the public bucket. The original stays private."""
    photo = RoomPhoto.objects.filter(pk=photo_id).first()
    if photo is None:
        return
    file_ref = photo.file_ref
    try:
        fh = private_storage().open(file_ref)
    except FileNotFoundError:
        return  # replaced or deleted since this task was queued; the newer task makes the copies
    with fh:
        image = ImageOps.exif_transpose(Image.open(fh))
        image = image.convert("RGB")
        variants = {}
        stem = file_ref.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        for width in settings.PHOTO_WIDTHS:
            copy = image.copy()
            if copy.width > width:
                copy = copy.resize((width, round(copy.height * width / copy.width)), Image.LANCZOS)
            buf = io.BytesIO()
            copy.save(buf, "WEBP", quality=80, method=4)
            variants[str(width)] = default_storage.save(f"room-photos/{stem}-{width}.webp", ContentFile(buf.getvalue()))
    # Publish only if the photo still points at the original these copies were made from. A replacement
    # uploaded meanwhile has its own task, and a slower older task must not put the old picture back.
    with transaction.atomic():
        current = RoomPhoto.objects.select_for_update().filter(pk=photo_id, file_ref=file_ref).first()
        if current is None:
            stale = list(variants.values())
        else:
            stale = [path for path in current.variants.values() if path not in variants.values()]
            current.variants = variants
            current.save(update_fields=["variants"])
    for path in stale:
        default_storage.delete(path)


def delete_photo_files(file_ref, variants):
    private_storage().delete(file_ref)
    for path in variants.values():
        default_storage.delete(path)
