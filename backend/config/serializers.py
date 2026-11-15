class WritesOnlyChangedFields:
    """Serializer mixin: an update writes only the fields the request set.

    ModelSerializer's own update saves every column from the copy that was read at the start of the
    request. Anything changed in between by someone else (a role taken away, an account disabled, a
    photo's resized copies published) would be silently put back. Use it on serializers whose writable
    fields are plain model fields.
    """

    def update(self, instance, validated_data):
        for name, value in validated_data.items():
            setattr(instance, name, value)
        auto = [f.name for f in instance._meta.concrete_fields if getattr(f, "auto_now", False)]
        instance.save(update_fields=[*validated_data, *auto])
        return instance
