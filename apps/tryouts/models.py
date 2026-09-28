import uuid
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from apps.teams.models import Position, get_deleted_team


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


class TryoutDecision(models.TextChoices):
    """
    Separate axis from TryoutStatus above -- status tracks contact/
    attendance logistics, this tracks the actual roster call. Never shown
    to the family until a signup resolves to INVITE/NOT_SELECTED -- a coach
    can send that signup's decision email as soon as it's set, independent
    of every other signup on the team (see
    apps.accounts.views.coach_tryout_send_email).
    """

    UNDECIDED = "undecided", "Undecided"
    INVITE = "invite", "Invite"
    NOT_SELECTED = "not_selected", "Not Selected"


class TryoutFamilyResponse(models.TextChoices):
    """
    Only meaningful once coach_decision=INVITE and its decision email has
    gone out (TryoutSignup.decision_emailed_at) -- see TryoutResponseInvite
    below. A NOT_SELECTED signup's response page is purely informational
    (nothing to accept/decline), so this stays PENDING forever for those.
    """

    PENDING = "pending", "Pending"
    ACCEPTED = "accepted", "Accepted"
    DECLINED = "declined", "Declined"


class TryoutSignup(models.Model):
    """Public, no-login submission from a prospective family."""

    # Which team's tryout this is for -- the parent picks from whichever
    # teams currently have Team.accepting_tryouts=True. Deleting a team
    # doesn't delete its signups (they're historical records) or block the
    # delete: they move to the "Deleted team" placeholder instead, and
    # TeamAdmin's delete confirmation warns which ones. A signup on the
    # placeholder can't be emailed, responded to or promoted to a roster.
    team = models.ForeignKey(
        "teams.Team", on_delete=models.SET(get_deleted_team), related_name="tryout_signups"
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

    # Set by whichever coach is assigned to `team` -- see
    # apps.accounts.views.coach_tryout_decision_change, which enforces that
    # scoping (the existing coach_assignments__coach=user pattern, same as
    # roster/practice editing). Admins can see it but don't set it here.
    coach_decision = models.CharField(
        max_length=20, choices=TryoutDecision.choices, default=TryoutDecision.UNDECIDED
    )
    family_response = models.CharField(
        max_length=20,
        choices=TryoutFamilyResponse.choices,
        default=TryoutFamilyResponse.PENDING,
    )
    # Set alongside family_response by apps.tryouts.views._complete_response
    # -- the User who actually accepted/declined (either newly created on
    # the spot or already logged in). Promotion (admin_tryout_promote)
    # needs this to link the right parent account without guessing from
    # parent_email, which the family could've changed on the accept form.
    responded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="+",
    )
    # Set once by admin_tryout_promote -- guards against promoting the
    # same signup twice and gives the detail page something to link to.
    promoted_player = models.OneToOneField(
        "accounts.Player",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="tryout_signup",
    )
    # Set by apps.accounts.views.coach_tryout_send_email once the
    # acceptance/rejection email for the CURRENT coach_decision has gone
    # out -- drives the send button's disabled/"Sent" state on the coach's
    # try-out list. Reset to None by coach_tryout_decision_change whenever
    # the decision actually changes, since a changed decision needs its own
    # new email.
    decision_emailed_at = models.DateTimeField(null=True, blank=True)

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
        if self.team.is_deleted_placeholder:
            return f"{self.player_full_name} ({self.team.name})"
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


class TryoutDecisionChange(models.Model):
    """
    Audit trail for coach_decision changes -- same append-only pattern as
    TryoutStatusChange above, just on the coach-driven axis instead of the
    admin-driven one.
    """

    signup = models.ForeignKey(
        TryoutSignup, on_delete=models.CASCADE, related_name="decision_changes"
    )
    old_decision = models.CharField(max_length=20, choices=TryoutDecision.choices)
    new_decision = models.CharField(max_length=20, choices=TryoutDecision.choices)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Try-Out Decision Change"
        verbose_name_plural = "Try-Out Decision Changes"


def _default_response_expiry():
    return timezone.now() + timedelta(days=14)


class TryoutResponseInvite(models.Model):
    """
    Public, token-based Accept/Decline link for a family -- same UUID-
    token/expiring/single-response pattern as apps.accounts.ParentInvite.
    Created automatically the moment a coach sends the decision email (see
    apps.accounts.views.coach_tryout_send_email) -- no separate admin
    "finalize" step. The public response page (apps.tryouts.views.respond)
    branches on coach_decision -- INVITE gets Accept/Decline, NOT_SELECTED
    is purely informational. UNDECIDED can't reach here, since
    coach_tryout_send_email refuses to send until a decision is set.
    """

    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    signup = models.ForeignKey(
        TryoutSignup, on_delete=models.CASCADE, related_name="response_invites"
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_response_expiry)
    responded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Try-Out Response Invite"
        verbose_name_plural = "Try-Out Response Invites"

    @property
    def is_valid(self) -> bool:
        return self.responded_at is None and timezone.now() < self.expires_at


class TryoutMassEmail(models.Model):
    """
    One email a coach or admin sent to every family matching a filter on
    the Email Families page (apps.accounts.views.tryout_mass_email).
    Append-only history of what was sent, by whom and to whom.
    """

    sent_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    sent_at = models.DateTimeField(auto_now_add=True)
    # The filter used. A null team means "all teams the sender could email".
    team = models.ForeignKey(
        "teams.Team",
        on_delete=models.SET(get_deleted_team),
        null=True,
        blank=True,
        related_name="+",
    )
    decision = models.CharField(max_length=20, choices=TryoutDecision.choices, blank=True)
    subject = models.CharField(max_length=200)
    body = models.TextField()
    # The addresses it actually went to, one copy each.
    recipients = models.JSONField(default=list)

    class Meta:
        ordering = ["-sent_at"]

    def __str__(self):
        return f"{self.subject} ({self.sent_at:%Y-%m-%d})"


class TryoutPosterType(models.TextChoices):
    INITIAL = "initial", "Initial Tryouts"
    SUPPLEMENTAL = "supplemental", "Supplemental / Make-Up Tryouts"


class TryoutPoster(models.Model):
    """
    A ready-made poster image an admin uploads for the home page's
    upcoming-tryouts section (see config.views.home). Manual upload only
    for now -- auto-generating one from a background photo/logo/time/
    location is a planned follow-up once the source assets (the exact
    background photo and font used) are available; see CLAUDE.md.
    """

    poster_type = models.CharField(max_length=20, choices=TryoutPosterType.choices)
    # Not rendered on the poster (all its info is already baked into the
    # image) -- used as the <img alt> text and in the admin list, since a
    # flattened image has no other way to be described for accessibility.
    title = models.CharField(max_length=200)
    image = models.ImageField(upload_to="tryout_posters/")
    # Only one poster may be active at a time (see clean() below) -- the
    # active poster *is* the currently open try-out: it's what the home
    # page shows, and the public sign-up form is closed without one.
    is_active = models.BooleanField(
        default=True,
        help_text=(
            "Whether this poster currently shows on the home page. Only one poster "
            "can be active at a time, and the try-out sign-up form is closed unless one is."
        ),
    )
    display_order = models.PositiveIntegerField(
        default=0, help_text="Lower numbers show first, on the home page and in this list."
    )
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["display_order", "-created_at"]
        verbose_name = "Try-Out Poster"
        verbose_name_plural = "Try-Out Posters"

    def __str__(self):
        return f"{self.title} ({self.get_poster_type_display()})"

    def clean(self):
        # Enforced here rather than as a DB constraint so it applies to both
        # the dashboard form and Django admin without a migration that would
        # fail on any existing data with two active posters.
        if self.is_active:
            others = TryoutPoster.objects.filter(is_active=True).exclude(pk=self.pk)
            active = others.first()
            if active:
                raise ValidationError(
                    {
                        "is_active": (
                            f"Only one try-out can be active at a time -- "
                            f"\"{active.title}\" is already active. Deactivate it first."
                        )
                    }
                )

    @classmethod
    def get_active(cls):
        return cls.objects.filter(is_active=True).first()
