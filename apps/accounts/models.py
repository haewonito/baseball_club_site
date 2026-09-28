import uuid
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    PARENT = "parent", "Parent"
    COACH = "coach", "Coach"


class UserManager(BaseUserManager):
    """create_user/create_superuser keyed on email -- there is no username."""

    def _create_user(self, email, password, **extra_fields):
        # Fully lowercased, not just normalize_email's domain-only
        # lowercasing -- email is the account identifier here (no
        # username), so "James@x.com" and "james@x.com" must resolve to
        # the same account rather than silently becoming two.
        email = self.normalize_email(email).lower()
        user = self.model(email=email, **extra_fields)
        user.set_password(password)
        user.save(using=self._db)
        return user

    def create_user(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", False)
        extra_fields.setdefault("is_superuser", False)
        return self._create_user(email, password, **extra_fields)

    def create_superuser(self, email, password=None, **extra_fields):
        extra_fields.setdefault("is_staff", True)
        extra_fields.setdefault("is_superuser", True)
        if extra_fields.get("is_staff") is not True:
            raise ValueError("Superuser must have is_staff=True.")
        if extra_fields.get("is_superuser") is not True:
            raise ValueError("Superuser must have is_superuser=True.")
        return self._create_user(email, password, **extra_fields)


class User(AbstractUser):
    """
    One auth system, roles are many-to-many (not a single field) so a
    person can hold more than one role at once -- e.g. the league owner,
    who is also a head coach and needs to see fee data like an Admin.

    Login is by email, not username -- there is no username field.
    """

    username = None
    email = models.EmailField(unique=True)

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    objects = UserManager()

    roles = models.ManyToManyField(
        "UserRole", blank=True, related_name="users"
    )

    class Meta:
        # Belt-and-suspenders on top of the field-level unique=True above --
        # that's a case-sensitive DB index, so "James@x.com"/"james@x.com"
        # could otherwise coexist as two rows. Catches any creation path,
        # not just the ones that remember to check case-insensitively
        # themselves (see InviteClaimSignupForm.clean_email).
        constraints = [
            models.UniqueConstraint(Lower("email"), name="unique_lower_email"),
        ]

    def __str__(self):
        return self.get_full_name() or self.email

    def has_role(self, role: str) -> bool:
        return self.roles.filter(role=role).exists()

    @property
    def is_admin(self) -> bool:
        return self.has_role(Role.ADMIN)

    @property
    def is_parent(self) -> bool:
        return self.has_role(Role.PARENT)

    @property
    def is_coach(self) -> bool:
        return self.has_role(Role.COACH)


class UserRole(models.Model):
    """A single role grant. Referenced by User.roles (M2M)."""

    role = models.CharField(max_length=20, choices=Role.choices, unique=True)

    class Meta:
        verbose_name = "User Role"
        verbose_name_plural = "User Roles"

    def __str__(self):
        return self.get_role_display()


class Player(models.Model):
    """A kid in the club. Distinct from User -- players don't log in."""

    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    date_of_birth = models.DateField()
    jersey_number = models.PositiveSmallIntegerField(null=True, blank=True)
    team = models.ForeignKey(
        "teams.Team", on_delete=models.SET_NULL, null=True, blank=True, related_name="players"
    )
    # Profile "flair" -- distinct from the roster fields above (name/DOB/
    # jersey/position), which stay coach/admin-only. These three are the
    # parent's own domain: editable by the player's linked parent (or
    # admin) via apps.accounts.views.parent_player_profile_edit, never by
    # a coach. See apps.teams.views.player_detail for the tiered
    # public/coach-parent/admin page these feed.
    photo = models.ImageField(upload_to="player_photos/", null=True, blank=True)
    description = models.TextField(blank=True)
    is_public_profile = models.BooleanField(
        default=False,
        help_text=(
            "Whether this player's public-tier info (name, photo, jersey number, "
            "position, team) is visible on the public site. Off by default -- the "
            "parent (or admin) opts in."
        ),
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class PlayerGalleryPhoto(models.Model):
    """
    Extra photos for the "More Pictures" gallery at the bottom of the
    player detail page (apps.teams.views.player_detail). Added/deleted only
    by the player's linked parents (parent_player_gallery_add/_delete) --
    not coaches, and not admins from the site UI (Django admin can still
    remove one). Visible to whoever can see the player page at all, so it's
    public exactly when the rest of the profile is (is_public_profile).
    Images are downsized on upload (see PlayerGalleryPhotoForm) to keep R2
    storage small. seed_demo_data seeds a few per demo player; real
    parent uploads aren't seeded, so a flush wipes those.
    """

    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="gallery_photos")
    image = models.ImageField(upload_to="player_gallery/")
    uploaded_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "Player Gallery Photo"
        verbose_name_plural = "Player Gallery Photos"

    def __str__(self):
        return f"Gallery photo of {self.player}"


class ParentPlayerLink(models.Model):
    """
    Links a Parent-role User to a Player. Admin-created by default;
    second-parent self-service linking happens via ParentInvite below.
    Soft-delete keeps history for the admin-visible link log.
    """

    parent = models.ForeignKey(User, on_delete=models.CASCADE, related_name="player_links")
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="parent_links")
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, related_name="+"
    )
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "Parent-Player Link"
        verbose_name_plural = "Parent-Player Links"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "player"],
                condition=models.Q(removed_at__isnull=True),
                name="unique_active_parent_player_link",
            )
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None


def _default_invite_expiry():
    return timezone.now() + timedelta(days=14)


class ParentInvite(models.Model):
    """
    Self-service second-parent linking. The primary parent generates one
    of these for a specific player; the recipient claims it once. Expires
    in 14 days. The claim flow must show the "linked person can see this
    kid's private info" warning both when sending and when claiming.
    """

    token = models.UUIDField(default=uuid.uuid4, editable=False, unique=True)
    player = models.ForeignKey(Player, on_delete=models.CASCADE, related_name="invites")
    created_by = models.ForeignKey(User, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(default=_default_invite_expiry)
    claimed_at = models.DateTimeField(null=True, blank=True)
    claimed_by = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    # Both blank until the primary parent uses the "email it" option (see
    # accounts.views.parent_invite_send_email) -- the link itself never
    # requires an email address, this is purely for the optional send.
    invitee_email = models.EmailField(blank=True)
    emailed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Parent Invite"
        verbose_name_plural = "Parent Invites"

    @property
    def is_valid(self) -> bool:
        return self.claimed_at is None and timezone.now() < self.expires_at
