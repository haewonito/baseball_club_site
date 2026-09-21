from django.conf import settings
from django.db import models


class Team(models.Model):
    name = models.CharField(max_length=100)  # e.g. "12U Bulldogs"
    division = models.CharField(max_length=50)  # e.g. "12U"
    season_year = models.PositiveIntegerField()

    class Meta:
        ordering = ["-season_year", "division"]

    def __str__(self):
        return f"{self.name} ({self.season_year})"


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

    def __str__(self):
        return f"Bio for {self.coach}"


class Position(models.TextChoices):
    PITCHER = "P", "Pitcher"
    CATCHER = "C", "Catcher"
    FIRST = "1B", "First base"
    SECOND = "2B", "Second base"
    THIRD = "3B", "Third base"
    SHORTSTOP = "SS", "Shortstop"
    OUTFIELD = "OF", "Outfield"


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
