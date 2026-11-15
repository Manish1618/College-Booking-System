"""Approval routing rules by stay category."""

from django.db.models import Exists, OuterRef, Q

from apps.accounts.models import Role, User

from .models import ApprovalRule, Booking


def can_decide(user, booking):
    """Admins can always decide. An approver decides if routed to the category, or if it has no rules."""
    if booking.requester_id == user.pk:
        return False  # nobody approves their own request
    if user.role == Role.ADMIN:
        return True
    if user.role != Role.APPROVER:
        return False
    rules = ApprovalRule.objects.filter(category=booking.category)
    return not rules.exists() or rules.filter(approver=user).exists()


def approvers_for(booking):
    rules = ApprovalRule.objects.filter(category=booking.category)
    users = User.objects.filter(role=Role.APPROVER, is_active=True).exclude(pk=booking.requester_id)
    return users.filter(pk__in=rules.values("approver")) if rules.exists() else users


def routed_to(user):
    """Queryset filter for the submitted bookings an approver may see."""
    mine = ApprovalRule.objects.filter(category=OuterRef("category"), approver=user)
    any_rule = ApprovalRule.objects.filter(category=OuterRef("category"))
    return Booking.objects.exclude(status="DRAFT").filter(Q(Exists(mine)) | ~Q(Exists(any_rule)))
