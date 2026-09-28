"""Model helpers that push rules down into PostgreSQL."""

from django.db import models
from django.db.models.functions import Now


def in_choices(field: str, choices: type[models.TextChoices], table: str) -> models.CheckConstraint:
    """CHECK that a text column holds one of its choices.

    Django's `choices` are enforced only by forms and serializers. This makes the database refuse
    any other value, whichever code path writes the row. Text + CHECK instead of a PostgreSQL
    ENUM: a CHECK can be changed online (NOT VALID, then VALIDATE).
    """
    return models.CheckConstraint(
        condition=models.Q(**{f"{field}__in": choices.values}),
        name=f"{table}_{field}_valid",
    )


def created_at_field() -> models.DateTimeField:
    """Creation time taken from the database clock, the one clock every host agrees on."""
    return models.DateTimeField(db_default=Now(), editable=False)
