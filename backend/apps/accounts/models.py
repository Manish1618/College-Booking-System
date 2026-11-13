import uuid

from django.contrib.auth.models import AbstractBaseUser, BaseUserManager, PermissionsMixin
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    REQUESTER = "REQUESTER", "College requester"
    EXTERNAL = "EXTERNAL", "External guest"
    APPROVER = "APPROVER", "Approver"
    MANAGER = "MANAGER", "Guesthouse manager"
    ADMIN = "ADMIN", "Super admin"


STAFF_ROLES = {Role.MANAGER, Role.ADMIN}


class UserManager(BaseUserManager):
    def create_user(self, email=None, phone=None, **extra):
        if not email and not phone:
            raise ValueError("A user needs an email or a phone number.")
        user = self.model(email=self.normalize_email(email).lower() if email else None, phone=phone or None, **extra)
        user.set_unusable_password()  # no passwords are stored
        user.save(using=self._db)
        return user

    def create_superuser(self, email, password=None, **extra):
        extra["role"] = Role.ADMIN
        return self.create_user(email=email, **extra)


class User(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=150, blank=True)
    email = models.EmailField(unique=True, null=True, blank=True)
    phone = models.CharField(max_length=15, unique=True, null=True, blank=True)
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.EXTERNAL)
    department = models.CharField(max_length=120, blank=True)
    sso_subject = models.CharField(max_length=255, unique=True, null=True, blank=True)
    is_active = models.BooleanField(default=True)
    date_joined = models.DateTimeField(default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["name", "email"]

    def __str__(self):
        return self.name or self.email or self.phone or str(self.pk)

    def save(self, *args, **kwargs):
        self.is_superuser = self.role == Role.ADMIN
        super().save(*args, **kwargs)

    @property
    def is_staff(self):
        return self.role in STAFF_ROLES


class OneTimeCode(models.Model):
    """A sign-in code sent by email or SMS. Only a keyed hash of the code is stored."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    identifier = models.CharField(max_length=254, db_index=True)  # normalised email or phone
    code_hash = models.CharField(max_length=64)
    attempts = models.PositiveSmallIntegerField(default=0)
    expires_at = models.DateTimeField()
    consumed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    ip = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
