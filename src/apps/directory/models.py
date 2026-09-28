from django.conf import settings
from django.db import models
from django.db.models import F, Q

from apps.common.db import created_at_field


class Department(models.Model):
    code = models.CharField(max_length=20, unique=True)
    name_bn = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    is_active = models.BooleanField(default=True)
    created_at = created_at_field()

    class Meta:
        db_table = "department"

    def __str__(self):
        return self.code


class Category(models.Model):
    # Immutable after creation (trigger): requests denormalise department_id, which is safe
    # only if a category never moves. To move one, deactivate it and create a new one.
    department = models.ForeignKey(Department, on_delete=models.PROTECT, related_name="categories")
    code = models.CharField(max_length=30, unique=True)
    name_bn = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    target_working_days = models.PositiveSmallIntegerField()
    is_active = models.BooleanField(default=True)
    created_at = created_at_field()

    class Meta:
        db_table = "category"
        constraints = [
            models.CheckConstraint(
                condition=Q(target_working_days__gt=0), name="category_target_days_positive"
            ),
        ]

    def __str__(self):
        return self.code


class Holiday(models.Model):
    """Non-working days. Editing this table triggers a recompute of open requests' due dates."""

    date = models.DateField(unique=True)
    name_bn = models.CharField(max_length=120)
    name_en = models.CharField(max_length=120)
    # No index: users are never deleted, and nothing queries holidays by creator.
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        related_name="+",
        db_index=False,
    )
    created_at = created_at_field()

    class Meta:
        db_table = "holiday"


class SlaSuspension(models.Model):
    """Force majeure (internet shutdown, disaster): suspended days do not count toward SLAs."""

    scope_department = models.ForeignKey(
        Department,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="+",
        db_index=False,
        help_text="Empty means national.",
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    reason = models.CharField(max_length=500)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+", db_index=False
    )
    created_at = created_at_field()

    class Meta:
        db_table = "sla_suspension"
        constraints = [
            models.CheckConstraint(
                condition=Q(ends_on__gte=F("starts_on")), name="sla_suspension_range_valid"
            ),
        ]
        indexes = [models.Index(fields=["starts_on", "ends_on"], name="sla_suspension_range_idx")]
