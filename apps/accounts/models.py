import uuid
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models, transaction
from django.db.models.functions import Lower
from django.db.models.signals import post_delete
from django.dispatch import receiver
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

    def get_by_natural_key(self, email):
        # What ModelBackend calls at login. Case-insensitive to match the
        # unique_lower_email constraint (a phone's autocapitalize turns
        # "james@x.com" into "James@x.com"); the constraint guarantees at
        # most one match.
        return self.get(email__iexact=email)

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
        # Lists of people sort by last name everywhere (Django admin lists
        # and dropdowns included), per the user.
        ordering = ["last_name", "first_name", "email"]

    def __str__(self):
        return self.get_full_name() or self.email

    def has_role(self, role: str) -> bool:
        # A superuser can already do everything through Django admin, so
        # every role check passes for them, whatever UserRole rows they hold.
        if self.is_superuser and self.is_active:
            return True
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
        "teams.Team",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="players",
        limit_choices_to={"is_deleted_placeholder": False},
    )
    # Profile "flair" -- distinct from the roster fields above (name/DOB/
    # jersey/position), which stay coach/admin-only. These three are the
    # parent's own domain: editable by the player's linked parent (or
    # admin) via the inline form on teams.views.player_detail, never by
    # a coach. See apps.teams.views.player_detail for the tiered
    # public/coach-parent/admin page these feed.
    photo = models.ImageField(upload_to="player_photos/", null=True, blank=True)
    description = models.TextField(blank=True)
    is_public_profile = models.BooleanField(
        default=False,
        help_text=(
            "Player's public-tier info (name, photo, jersey number, "
            "position, team) will be visible on the public site. Private by default"
        ),
    )

    class Meta:
        ordering = ["last_name", "first_name"]

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

    Every kid with any active link has exactly one primary parent, the one
    who gets automated emails like overdue-fee reminders (apps.fees). It's
    otherwise identical to any other link. save() keeps that true wherever
    links are created or removed: the first active link becomes primary,
    making a link primary un-primaries the old one, and removing the
    primary hands it to the longest-linked remaining adult.
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
    is_primary = models.BooleanField(
        default=False,
        help_text=(
            "The primary parent gets automated emails about this player, like overdue "
            "payment reminders. Exactly one active link per player is primary; ticking "
            "this moves it here."
        ),
    )

    class Meta:
        ordering = ["player__last_name", "player__first_name", "parent__last_name"]
        verbose_name = "Parent-Player Link"
        verbose_name_plural = "Parent-Player Links"
        constraints = [
            models.UniqueConstraint(
                fields=["parent", "player"],
                condition=models.Q(removed_at__isnull=True),
                name="unique_active_parent_player_link",
            ),
            models.UniqueConstraint(
                fields=["player"],
                condition=models.Q(is_primary=True, removed_at__isnull=True),
                name="one_primary_parent_per_player",
            ),
        ]

    @property
    def is_active(self) -> bool:
        return self.removed_at is None

    def save(self, *args, **kwargs):
        update_fields = kwargs.get("update_fields")
        if update_fields is not None:
            kwargs["update_fields"] = {*update_fields, "is_primary"}
        with transaction.atomic():
            other_active = ParentPlayerLink.objects.filter(
                player_id=self.player_id, removed_at__isnull=True
            ).exclude(pk=self.pk)
            if self.removed_at is not None:
                was_primary = self.is_primary
                self.is_primary = False
                super().save(*args, **kwargs)
                if was_primary:
                    ensure_primary_parent(self.player_id)
                return
            if self.is_primary:
                other_active.filter(is_primary=True).update(is_primary=False)
            elif not other_active.filter(is_primary=True).exists():
                self.is_primary = True
            super().save(*args, **kwargs)


def ensure_primary_parent(player_id):
    """
    If the player has active links but no primary (the primary was just
    removed or deleted), make the longest-linked remaining adult primary.
    """
    active = ParentPlayerLink.objects.filter(player_id=player_id, removed_at__isnull=True)
    if active.exists() and not active.filter(is_primary=True).exists():
        first = active.order_by("created_at", "pk").first()
        ParentPlayerLink.objects.filter(pk=first.pk).update(is_primary=True)


@receiver(post_delete, sender=ParentPlayerLink)
def _reassign_primary_after_delete(sender, instance, **kwargs):
    # Hard deletes (Django admin) bypass save(); still hand primary on.
    if instance.is_primary and instance.removed_at is None:
        ensure_primary_parent(instance.player_id)


def _default_invite_expiry():
    return timezone.now() + timedelta(days=14)


# Most adults a parent can link to one kid through self-service invites
# (each linked adult sees the kid's private info). Counts active links
# plus still-open invites. Admins can link more in Django admin.
MAX_LINKED_ADULTS_PER_PLAYER = 3


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
    # Set when the parent who created it cancels it before anyone uses it
    # (accounts.views.parent_invite_cancel). Kept rather than deleted, as a record.
    cancelled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Parent Invite"
        verbose_name_plural = "Parent Invites"

    @classmethod
    def open_invites(cls):
        """Unused, uncancelled, unexpired invites -- the ones a link can still claim."""
        return cls.objects.filter(
            claimed_at__isnull=True, cancelled_at__isnull=True, expires_at__gt=timezone.now()
        )

    @classmethod
    def slots_left(cls, player):
        """How many more adults can be invited for `player` before hitting
        MAX_LINKED_ADULTS_PER_PLAYER (active links + open invites)."""
        used = (
            player.parent_links.filter(removed_at__isnull=True).count()
            + cls.open_invites().filter(player=player).count()
        )
        return max(MAX_LINKED_ADULTS_PER_PLAYER - used, 0)

    @property
    def is_valid(self) -> bool:
        return (
            self.claimed_at is None
            and self.cancelled_at is None
            and timezone.now() < self.expires_at
        )
