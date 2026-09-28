import re

from apps.accounts import totp
from apps.notifications import delivery
from apps.notifications.models import DeliveryStatus, Notification

PASSWORD = "a-long-demo-passphrase"


def deliver_all() -> None:
    """What the worker would do: send every pending notification."""
    for n in Notification.objects.filter(status=DeliveryStatus.PENDING):
        delivery.deliver(n.pk, n.created_at)


def sms_code(api, phone: str) -> str:
    """Deliver pending messages, then read the newest code from the demo SMS inbox."""
    deliver_all()
    inbox = api.get(f"/api/v1/demo/sms/{phone}").json()
    return re.search(r"[0-9]{6}", inbox[0]["body"]).group()


def current_totp(user) -> str:
    import time

    user.refresh_from_db()
    secret = totp.decrypt_secret(user.totp_secret_encrypted)
    return totp.code_at(secret, int(time.time() // 30))


def error_code(response) -> str:
    return response.json()["error"]["code"]
