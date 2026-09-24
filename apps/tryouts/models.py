from django.conf import settings
from django.db import models

from apps.teams.models import Position


class TryoutYearSettings(models.Model):
    """
    Singleton-ish. Used to just also hold the fall-cutoff date for
    computing which season a signup belonged to -- retired now that every
    TryoutSignup is explicitly tied to a Team (whose own season_year is the
    single source of truth), so all that's left here is the home-page
    banner date.
    """

    next_tryout_date = models.DateField(
        null=True,
        blank=True,
        help_text="Drives the public home page banner -- shown when this date is within 30 days.",
    )

    class Meta:
        verbose_name = "Try-Out Year Settings"
        verbose_name_plural = "Try-Out Year Settings"

    def __str__(self):
        return f"Next try-out: {self.next_tryout_date or 'not set'}"

    @classmethod
    def get_next_tryout_date(cls):
        row = cls.objects.first()
        return row.next_tryout_date if row else None


class TryoutStatus(models.TextChoices):
    NEW = "new", "New"
    CONTACTED = "contacted", "Contacted"
    ATTENDED = "attended", "Attended"


class TryoutSignup(models.Model):
    """Public, no-login submission from a prospective family."""

    # Which team's tryout this is for -- the parent picks from whichever
    # teams currently have Team.accepting_tryouts=True. PROTECT rather than
    # CASCADE/SET_NULL: a signup is a historical record, and losing which
    # team it was for isn't something a Team deletion should silently do.
    team = models.ForeignKey(
        "teams.Team", on_delete=models.PROTECT, related_name="tryout_signups"
    )
    player_first_name = models.CharField(max_length=100)
    player_last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField(null=True, blank=True)
    # Which positions were selected: see TryoutSignupPosition below -- kept
    # as a normalized set (one canonical code per row) rather than a free
    # text field so "shortstop"/"short stop"/"SS" can't all show up as
    # different values.
    years_experience = models.PositiveSmallIntegerField(null=True, blank=True)
    previous_team = models.CharField(max_length=150, blank=True)
    notes = models.TextField(blank=True)

    parent_first_name = models.CharField(max_length=100)
    parent_last_name = models.CharField(max_length=100)
    parent_phone = models.CharField(max_length=30)
    parent_email = models.EmailField()

    submitted_at = models.DateTimeField(auto_now_add=True)

    status = models.CharField(
        max_length=20, choices=TryoutStatus.choices, default=TryoutStatus.NEW
    )
    admin_notes = models.TextField(blank=True)

    class Meta:
        ordering = ["-submitted_at"]
        verbose_name = "Try-Out Sign-Up"
        verbose_name_plural = "Try-Out Sign-Ups"

    def save(self, *args, **kwargs):
        # Public form, no input validation on casing -- normalize names so
        # "john smith" / "JOHN SMITH" / "john SMITH" all store consistently
        # rather than however each family happened to type it.
        self.player_first_name = self.player_first_name.strip().title()
        self.player_last_name = self.player_last_name.strip().title()
        self.parent_first_name = self.parent_first_name.strip().title()
        self.parent_last_name = self.parent_last_name.strip().title()
        super().save(*args, **kwargs)

    @property
    def player_full_name(self):
        return f"{self.player_first_name} {self.player_last_name}"

    @property
    def parent_full_name(self):
        return f"{self.parent_first_name} {self.parent_last_name}"

    @property
    def positions_display(self):
        return ", ".join(p.get_position_display() for p in self.positions.all())

    @property
    def season_label(self):
        return self.team.season_label

    def __str__(self):
        return f"{self.player_full_name} ({self.season_label})"


class TryoutSignupPosition(models.Model):
    """
    One selected position for a sign-up. Uses the shared apps.teams.Position
    list -- the same canonical codes used for roster assignments -- so a
    position is never entered as free text here.
    """

    signup = models.ForeignKey(
        TryoutSignup, on_delete=models.CASCADE, related_name="positions"
    )
    position = models.CharField(max_length=5, choices=Position.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["signup", "position"], name="unique_signup_position"
            ),
        ]

    def __str__(self):
        return f"{self.signup} - {self.get_position_display()}"


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

    class Meta:
        verbose_name = "Try-Out Status Change"
        verbose_name_plural = "Try-Out Status Changes"
