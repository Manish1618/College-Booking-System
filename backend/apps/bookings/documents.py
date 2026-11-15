"""Private documents: recommendation letters and guest ID copies."""

from django.conf import settings
from django.db import transaction
from django.http import FileResponse, HttpResponseRedirect
from rest_framework.exceptions import ValidationError

from apps.audit import services as audit
from apps.rooms.uploads import private_storage, sniff, store_private

from . import routing
from .models import Document


def remove_document(document):
    file_ref = document.file_ref
    document.delete()
    transaction.on_commit(lambda: private_storage().delete(file_ref))


@transaction.atomic
def attach(booking, user, doc_type, upload, guest_id=None):
    """Stores an upload and links it. A new letter or ID replaces the earlier one."""
    if doc_type not in Document.Type.values:
        raise ValidationError({"type": ["Unknown document type."]})
    guest = None
    if doc_type == Document.Type.GUEST_ID:
        guest = booking.guests.filter(pk=guest_id).first() if guest_id else None
        if guest is None:
            raise ValidationError({"guest": ["Choose which guest this ID belongs to."]})
    ext, content_type = sniff(upload)
    document = Document.objects.create(
        booking=booking,
        type=doc_type,
        file_ref=store_private(upload, f"documents/{booking.pk}", ext),
        content_type=content_type,
        size=upload.size,
        uploaded_by=user,
    )
    if guest:
        old = guest.id_document
        guest.id_document = document
        guest.id_verified = False
        guest.save(update_fields=["id_document", "id_verified"])
        if old:
            remove_document(old)
    else:
        for old in booking.documents.filter(type=doc_type).exclude(pk=document.pk):
            remove_document(old)
    audit.log("document.uploaded", document, actor=user, after={"booking": str(booking.pk), "type": doc_type})
    return document


def can_view(request, document, *, manager):
    """ID copies: manager and admin only. Letters: also the requester and the approver they are routed to."""
    if manager:
        return True
    if document.type == Document.Type.GUEST_ID:
        return False
    booking = document.booking
    return booking.requester_id == request.user.pk or (
        booking.status != "DRAFT" and request.user.role == "APPROVER" and routing.can_decide(request.user, booking)
    )


def serve(request, document):
    """Logs the view, then streams the file (local) or redirects to a short-lived signed URL (S3)."""
    audit.log("document.viewed", document, actor=request.user, after={"type": document.type})
    if settings.S3_ENABLED:
        return HttpResponseRedirect(private_storage().url(document.file_ref))
    response = FileResponse(private_storage().open(document.file_ref), content_type=document.content_type)
    response["Content-Disposition"] = "inline"
    response["Cache-Control"] = "private, no-store"
    return response
