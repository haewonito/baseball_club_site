from django.conf import settings
from django.db import models


class EventType(models.TextChoices):
    PRACTICE = "practice", "Practice"
    TOURNAMENT = "tournament", "Tournament"
    # Anything else with a custom name -- a team party, a meeting, a photo
    # day. The value + "s" is the URL segment ("events"), see EVENT_KINDS.
    EVENT = "event", "Event"


class EventStatus(models.TextChoices):
    SCHEDULED = "scheduled", "Scheduled"
    CANCELLED = "cancelled", "Cancelled"
    POSTPONED = "postponed", "Postponed"


class EventSource(models.TextChoices):
    MANUAL = "manual", "Added on the website"
    GAMECHANGER = "gamechanger", "Synced from GameChanger"


class Event(models.Model):
    """
    One model for practices, tournaments and custom events -- distinguished by
    `event_type`. Public, no login required to view. `status` drives
    the cancellation/postponement banner on the public schedule.

    Recurring practices use the simple approach: bulk-create writes
    individual rows here rather than a recurrence-rule/series concept.
    """

    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.CASCADE,
        related_name="events",
        limit_choices_to={"is_deleted_placeholder": False},
    )
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

    # Where the row came from. GameChanger rows are written by
    # apps.schedule.gamechanger.sync_team and matched on `external_id` (the
    # feed's UID); coaches and admins can't edit or delete them, only the
    # local overlay fields (location, notes, status). See that module.
    source = models.CharField(
        max_length=20, choices=EventSource.choices, default=EventSource.MANUAL
    )
    external_id = models.CharField(max_length=255, blank=True)
    # The last status the feed reported ("scheduled", "cancelled", or
    # "removed" when the event vanished from the feed). Kept apart from
    # `status` so a local override survives a sync; `status` is only
    # rewritten when this changes.
    feed_status = models.CharField(max_length=20, blank=True)

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
        constraints = [
            models.UniqueConstraint(
                fields=["team", "external_id"],
                condition=~models.Q(external_id=""),
                name="unique_external_event_per_team",
            ),
        ]

    def __str__(self):
        return f"{self.get_event_type_display()} - {self.team} - {self.start_datetime:%Y-%m-%d}"

    @property
    def is_synced(self):
        return self.source == EventSource.GAMECHANGER
