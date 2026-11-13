import io

from celery import shared_task
from django.conf import settings
from django.core.files.base import ContentFile
from django.core.files.storage import default_storage
from PIL import Image, ImageOps

from .models import RoomPhoto
from .uploads import private_storage


@shared_task
def process_room_photo(photo_id):
    """Builds WebP copies at three widths in the public bucket. The original stays private."""
    photo = RoomPhoto.objects.filter(pk=photo_id).first()
    if photo is None:
        return
    old = dict(photo.variants)
    with private_storage().open(photo.file_ref) as fh:
        image = ImageOps.exif_transpose(Image.open(fh))
        image = image.convert("RGB")
        variants = {}
        stem = photo.file_ref.rsplit("/", 1)[-1].rsplit(".", 1)[0]
        for width in settings.PHOTO_WIDTHS:
            copy = image.copy()
            if copy.width > width:
                copy = copy.resize((width, round(copy.height * width / copy.width)), Image.LANCZOS)
            buf = io.BytesIO()
            copy.save(buf, "WEBP", quality=80, method=4)
            variants[str(width)] = default_storage.save(f"room-photos/{stem}-{width}.webp", ContentFile(buf.getvalue()))
    photo.variants = variants
    photo.save(update_fields=["variants"])
    for path in old.values():
        if path not in variants.values():
            default_storage.delete(path)


def delete_photo_files(file_ref, variants):
    private_storage().delete(file_ref)
    for path in variants.values():
        default_storage.delete(path)
