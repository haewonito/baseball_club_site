import uuid
from datetime import timedelta

from django.contrib.auth.base_user import BaseUserManager
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.utils import timezone


class Role(models.TextChoices):
    ADMIN = "admin", "Admin"
    PARENT = "parent", "Parent"
    COACH = "coach", "Coach"


class UserManager(BaseUserManager):
    """create_user/create_superuser keyed on email -- there is no username."""

    def _create_user(self, email, password, **extra_fields):
        email = self.normalize_email(email)
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

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


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

    class Meta:
        verbose_name = "Parent Invite"
        verbose_name_plural = "Parent Invites"

    @property
    def is_valid(self) -> bool:
        return self.claimed_at is None and timezone.now() < self.expires_at
