"""Turns findings into messages a person sees: one when a problem starts, a reminder every
2 hours while it lasts, and one when it clears. Nothing while things are fine.

Messages go to ntfy (a push-notification service; NTFY_URL is a private topic URL) and always
to the log. A message that cannot be sent is retried on the next pass, not dropped.
"""

import logging
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta

from .checks import CRITICAL, Finding

logger = logging.getLogger("grs.monitor")

REMIND_EVERY = timedelta(hours=2)


@dataclass
class State:
    since: datetime
    sent_at: datetime | None = None


Sender = Callable[[str, str, str], bool]  # (title, message, severity) -> delivered


class Alerter:
    def __init__(self, send: Sender, source: str):
        self.send = send
        self.source = source
        self.firing: dict[str, State] = {}
        self.unsent_clears: dict[str, Finding] = {}

    def update(self, findings: list[Finding], now: datetime) -> list[str]:
        """Apply one pass of findings. Returns the titles of messages sent."""
        sent = []
        for finding in findings:
            state = self.firing.get(finding.name)
            if finding.firing:
                self.unsent_clears.pop(finding.name, None)
                if state is None:
                    state = self.firing[finding.name] = State(since=now)
                    logger.warning("alert %s: %s", finding.name, finding.summary)
                if state.sent_at is None or now - state.sent_at >= REMIND_EVERY:
                    prefix = "" if state.sent_at is None else "still: "
                    title = f"{prefix}{finding.name} on {self.source}"
                    if self.send(title, finding.summary, finding.severity):
                        state.sent_at = now
                        sent.append(title)
            elif state is not None:
                del self.firing[finding.name]
                logger.warning("resolved %s: %s", finding.name, finding.summary)
                if state.sent_at is not None:  # only clear what the person was told about
                    self.unsent_clears[finding.name] = finding
        for name, finding in list(self.unsent_clears.items()):
            title = f"resolved: {name} on {self.source}"
            if self.send(title, finding.summary, "resolved"):
                del self.unsent_clears[name]
                sent.append(title)
        return sent


def ntfy(url: str) -> Sender:
    """POST to the topic URL; ntfy reads the title, priority and tags from headers."""
    if not url.startswith(("https://", "http://")):
        raise ValueError("NTFY_URL must be an http(s) URL")
    priority = {CRITICAL: "urgent", "warning": "high", "resolved": "default"}
    tags = {CRITICAL: "rotating_light", "warning": "warning", "resolved": "white_check_mark"}

    def send(title: str, message: str, severity: str) -> bool:
        request = urllib.request.Request(  # noqa: S310 - scheme checked above
            url,
            data=message.encode(),
            method="POST",
            headers={"Title": title, "Priority": priority[severity], "Tags": tags[severity]},
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as reply:  # noqa: S310
                return 200 <= reply.status < 300
        except Exception as exc:  # noqa: BLE001 - retried next pass
            logger.error("could not send alert %r: %s", title, exc)
            return False

    return send


def log_only(title: str, message: str, severity: str) -> bool:
    logger.warning("[%s] %s: %s", severity, title, message)
    return True
