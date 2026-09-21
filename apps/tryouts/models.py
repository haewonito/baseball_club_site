from datetime import date

from django.conf import settings
from django.db import models


class TryoutYearSettings(models.Model):
    """
    Singleton-ish: the cutoff date used to decide which tryout_year a
    submission gets tagged with. Default is September 1; admin can
    change it. If no row exists, settings.DEFAULT_TRYOUT_YEAR_CUTOFF_*
    is used instead.
    """

    cutoff_month = models.PositiveSmallIntegerField(default=9)
    cutoff_day = models.PositiveSmallIntegerField(default=1)

    def __str__(self):
        return f"Cutoff: {self.cutoff_month}/{self.cutoff_day}"

    @classmethod
    def get_cutoff(cls):
        row = cls.objects.first()
        if row:
            return row.cutoff_month, row.cutoff_day
        return (
            settings.DEFAULT_TRYOUT_YEAR_CUTOFF_MONTH,
            settings.DEFAULT_TRYOUT_YEAR_CUTOFF_DAY,
        )


def compute_tryout_year(submission_date: date) -> int:
    """
    A submission after the cutoff date is tagged for next year's
    tryouts; before the cutoff, it's tagged for the current year's.
    e.g. cutoff Sept 1: a submission on 2026-09-15 -> 2027,
    a submission on 2026-08-15 -> 2026.
    """
    cutoff_month, cutoff_day = TryoutYearSettings.get_cutoff()
    cutoff_this_year = date(submission_date.year, cutoff_month, cutoff_day)
    if submission_date >= cutoff_this_year:
        return submission_date.year + 1
    return submission_date.year


class TryoutStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    ATTENDED = "attended", "Attended"


class TryoutSignup(models.Model):
    """Public, no-login submission from a prospective family."""

    player_name = models.CharField(max_length=150)
    date_of_birth = models.DateField(null=True, blank=True)
    positions = models.CharField(max_length=100, blank=True)  # free text, e.g. "SS, 2B"
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_team = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)

    parent_name = models.CharField(max_length=150)
    parent_phone = models.CharField(max_length=30)
    parent_email = models.EmailField()

    submitted_at = models.DateTimeField(auto_now_add=True)
    tryout_year = models.PositiveIntegerField(editable=False)

    status = models.CharField(
        max_length=20, choices=TryoutStatus.choices, default=TryoutStatus.NEW
    )
    admin_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]

    def save(self, *args, **kwargs):
        if not self.tryout_year:
            submitted_date = self.submitted_at.date() if self.submitted_at else date.today()
            self.tryout_year = compute_tryout_year(submitted_date)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.player_name} ({self.tryout_year})"


class TryoutStatusChange(models.Model):
    """
    Audit trail for status changes -- pairs with the confirmation-dialog
    UX so an admin's status edit is deliberate and traceable.
    """

    signup = models.ForeignKey(
        TryoutSignup, on_delete=models.CASCADE, related_name="status_changes"
    )
    old_status = models.CharField(max_length=20, choices=TryoutStatus.choices)
    new_status = models.CharField(max_length=20, choices=TryoutStatus.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
