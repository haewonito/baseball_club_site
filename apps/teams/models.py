from django.conf import settings
from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=100)  # e.g. "12U Bulldogs"
    division = models.CharField(max_length=50)  # e.g. "12U"
    # The spring/summer year the season plays out in -- e.g. 2027 for a team
    # assembled from fall-2026 tryouts (see compute_tryout_year's cutoff
    # logic in apps.tryouts.models, which uses this same convention).
    season_year = models.PositiveIntegerField()

    class Meta:
        ordering = ["-season_year", "division"]

    @property
    def season_label(self):
        """e.g. season_year=2027 -> "2026-2027" -- distinguishes this season
        from the one before/after it more intuitively than a bare year."""
        return f"{self.season_year - 1}-{self.season_year}"

    def __str__(self):
        return f"{self.name} ({self.season_label})"


class TeamCoachRole(models.TextChoices):
    HEAD = "head", "Head coach"
    ASSISTANT = "assistant", "Assistant coach"


class TeamCoach(models.Model):
    """
    Join table between a coach (User with the Coach role) and a Team.
    A coach can be linked to multiple teams; a team can have one head
    coach and several assistants. Head and assistant currently carry
    the same permission level -- this field is for display only.
    """

    team = models.ForeignKey(Team, on_delete=models.CASCADE, related_name="coach_assignments")
    coach = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="team_assignments"
    )
    role = models.CharField(max_length=20, choices=TeamCoachRole.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["team", "coach"], name="unique_team_coach"),
        ]

    def __str__(self):
        return f"{self.coach} - {self.team} ({self.get_role_display()})"


class CoachProfile(models.Model):
    """Bio content, kept separate from the auth/role record."""

    coach = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="coach_profile"
    )
    bio_text = models.TextField(blank=True)
    photo = models.ImageField(upload_to="coach_photos/", blank=True, null=True)
    contact_email = models.EmailField(blank=True)  # optional; may route through admins instead

    class Meta:
        verbose_name = "Coach Profile"
        verbose_name_plural = "Coach Profiles"

    def save(self, *args, **kwargs):
        if not self.contact_email:
            self.contact_email = self.coach.email
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Bio for {self.coach}"


class Position(models.TextChoices):
    """
    The one canonical list of positions for the whole site -- used here for
    roster assignments and by apps.tryouts for sign-up position selection,
    so a position is never spelled/named two different ways in two places.
    """

    LEFT_PITCHER = "LP", "LH Pitcher"
    RIGHT_PITCHER = "RP", "RH Pitcher"
    CATCHER = "C", "Catcher"
    FIRST_BASE = "B1", "First Base"
    SECOND_BASE = "B2", "Second Base"
    THIRD_BASE = "B3", "Third Base"
    SHORTSTOP = "SS", "Shortstop"
    LEFT_FIELD = "LF", "Left Field"
    CENTER_FIELD = "CF", "Center Field"
    RIGHT_FIELD = "RF", "Right Field"


class PlayerPosition(models.Model):
    """
    Many-to-many: a player usually plays multiple positions.
    """

    player = models.ForeignKey(
        "accounts.Player", on_delete=models.CASCADE, related_name="positions"
    )
    position = models.CharField(max_length=5, choices=Position.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["player", "position"], name="unique_player_position"),
        ]

    def __str__(self):
        return f"{self.player} - {self.get_position_display()}"
