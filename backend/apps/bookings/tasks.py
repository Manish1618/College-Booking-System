from celery import shared_task

from . import services


@shared_task
def expire_stale_bookings():
    return services.expire_stale()


@shared_task
def mark_no_shows():
    return services.mark_no_shows()
