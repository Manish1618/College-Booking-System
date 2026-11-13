import json

from django.core.serializers.json import DjangoJSONEncoder

from .middleware import current_ip
from .models import AuditLog


def _clean(data):
    return None if data is None else json.loads(json.dumps(data, cls=DjangoJSONEncoder))


def log(action, obj=None, *, actor=None, before=None, after=None, entity=None, entity_id=None):
    """Write one audit entry. Call inside the same transaction as the change it records."""
    if actor is not None and not getattr(actor, "is_authenticated", False):
        actor = None
    return AuditLog.objects.create(
        actor=actor,
        action=action,
        entity=entity or obj._meta.model_name,
        entity_id=str(entity_id or obj.pk),
        before=_clean(before),
        after=_clean(after),
        ip=current_ip(),
    )
