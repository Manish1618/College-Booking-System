from rest_framework import serializers, viewsets

from apps.accounts.permissions import IsAdmin

from .models import AuditLog


class AuditLogSerializer(serializers.ModelSerializer):
    actor_name = serializers.SerializerMethodField()

    class Meta:
        model = AuditLog
        fields = ["id", "actor", "actor_name", "action", "entity", "entity_id", "before", "after", "ip", "created_at"]

    def get_actor_name(self, obj):
        return str(obj.actor) if obj.actor else "system"


class AuditLogViewSet(viewsets.ReadOnlyModelViewSet):
    serializer_class = AuditLogSerializer
    permission_classes = [IsAdmin]

    def get_queryset(self):
        qs = AuditLog.objects.select_related("actor")
        for field in ("entity", "entity_id", "action", "actor"):
            if value := self.request.query_params.get(field):
                qs = qs.filter(**{field: value})
        return qs
