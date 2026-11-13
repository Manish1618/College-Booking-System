import logging

from django.conf import settings
from django.utils.module_loading import import_string

logger = logging.getLogger(__name__)


class ConsoleSMSBackend:
    """Development backend: writes the SMS to the log. Swap SMS_BACKEND for a real gateway in production."""

    def send(self, phone, message):
        logger.info("SMS to %s: %s", phone, message)


def send_sms(phone, message):
    import_string(settings.SMS_BACKEND)().send(phone, message)
