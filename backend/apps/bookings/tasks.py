from celery import shared_task

from . import changes, services


@shared_task
def expire_stale_bookings():
    """Lapsed holds release their dates, and lapsed changes of dates release the dates they asked for."""
    return services.expire_stale() + changes.expire_stale()


@shared_task
def mark_no_shows():
    return services.mark_no_shows()
