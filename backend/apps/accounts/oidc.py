"""College SSO over OIDC. Loaded only when OIDC_ENABLED is true."""

from mozilla_django_oidc.auth import OIDCAuthenticationBackend

from .models import Role, User


class CollegeOIDCBackend(OIDCAuthenticationBackend):
    def filter_users_by_claims(self, claims):
        sub = claims.get("sub")
        if not sub:
            return User.objects.none()
        users = User.objects.filter(sso_subject=sub)
        if users.exists():
            return users
        email = (claims.get("email") or "").lower()
        return User.objects.filter(email=email) if email else User.objects.none()

    def create_user(self, claims):
        return User.objects.create_user(
            email=claims.get("email"),
            name=claims.get("name", ""),
            sso_subject=claims["sub"],
            role=Role.REQUESTER,
        )

    def update_user(self, user, claims):
        user.sso_subject = claims.get("sub") or user.sso_subject
        user.name = user.name or claims.get("name", "")
        user.save(update_fields=["sso_subject", "name"])
        return user
