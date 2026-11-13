import re
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac

from .models import OneTimeCode, Role, User

PHONE_RE = re.compile(r"^\+?[1-9]\d{9,14}$")


def normalise_identifier(raw):
    """Returns ("email"|"phone", value) or raises ValidationError."""
    value = (raw or "").strip()
    if "@" in value:
        validate_email(value)
        return "email", value.lower()
    digits = re.sub(r"[\s\-()]", "", value)
    if PHONE_RE.match(digits):
        if not digits.startswith("+"):
            digits = "+91" + digits[-10:] if len(digits) == 10 else "+" + digits
        return "phone", digits
    raise ValidationError("Enter a valid email address or phone number.")


def _hash(identifier, code):
    return salted_hmac("accounts.otp", f"{identifier}:{code}", algorithm="sha256").hexdigest()


def issue_code(identifier, ip=None):
    """Creates a fresh 6-digit code, invalidating earlier ones for the identifier."""
    now = timezone.now()
    OneTimeCode.objects.filter(identifier=identifier, consumed_at__isnull=True).update(consumed_at=now)
    code = f"{secrets.randbelow(10**6):06d}"
    OneTimeCode.objects.create(
        identifier=identifier,
        code_hash=_hash(identifier, code),
        expires_at=now + timedelta(minutes=settings.OTP_CODE_TTL_MINUTES),
        ip=ip or None,
    )
    return code


def check_code(identifier, code):
    """True if the code is right. Wrong guesses count against the cap; a right one is single-use."""
    now = timezone.now()
    otp = (
        OneTimeCode.objects.select_for_update()
        .filter(identifier=identifier, consumed_at__isnull=True, expires_at__gt=now)
        .order_by("-created_at")
        .first()
    )
    if otp is None or otp.attempts >= settings.OTP_MAX_ATTEMPTS:
        return False
    if not constant_time_compare(otp.code_hash, _hash(identifier, str(code).strip())):
        otp.attempts += 1
        otp.save(update_fields=["attempts"])
        return False
    otp.consumed_at = now
    otp.save(update_fields=["consumed_at"])
    return True


def is_college_email(email):
    domain = email.rsplit("@", 1)[-1].lower()
    return domain in {d.lower() for d in settings.COLLEGE_EMAIL_DOMAINS}


def get_or_create_user(kind, identifier, name=""):
    """College-domain emails become college requesters (the SSO fallback); everyone else is external."""
    user = User.objects.filter(**{kind: identifier}).first()
    if user:
        return user, False
    role = Role.REQUESTER if kind == "email" and is_college_email(identifier) else Role.EXTERNAL
    return User.objects.create_user(**{kind: identifier}, name=name.strip()[:150], role=role), True
