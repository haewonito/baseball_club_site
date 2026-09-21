from django.conf import settings
from django.db import models


class EventType(models.TextChoices):
    PRACTICE = "practice", "Practice"
    TOURNAMENT = "tournament", "Tournament"


class EventStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    CANCELLED = "cancelled", "Cancelled"
    POSTPONED = "postponed", "Postponed"


class Event(models.Model):
    """
    One model for both practices and tournaments -- distinguished by
    `event_type`. Public, no login required to view. `status` drives
    the cancellation/postponement banner on the public schedule.

    Recurring practices use the simple approach: bulk-create writes
    individual rows here rather than a recurrence-rule/series concept.
    """

    team = models.ForeignKey("teams.Team", on_delete=models.CASCADE, related_name="events")
    event_type = models.CharField(max_length=20, choices=EventType.choices)
    title = models.CharField(max_length=150, blank=True)
    start_datetime = models.DateTimeField()
    end_datetime = models.DateTimeField(null=True, blank=True)
    location_name = models.CharField(max_length=150, blank=True)
    location_address = models.CharField(max_length=255, blank=True)
    notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, choices=EventStatus.choices, default=EventStatus.SCHEDULED
    )

    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["start_datetime"]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.team} - {self.start_datetime:%Y-%m-%d}"

    # NOTE: if the GameChanger ICS feed sync is confirmed available,
    # this model may gain a `source` field (manual vs. synced) and the
    # coach/admin edit UI may shrink to an override layer for cancellations.
