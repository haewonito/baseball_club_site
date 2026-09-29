from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.teams.models import PlayerPosition

from .admin_mixins import AutoUserFieldsAdminMixin

from .models import ParentInvite, ParentPlayerLink, Player, PlayerGalleryPhoto, User, UserRole


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    """
    Django's UserAdmin hard-codes "username" in fieldsets/add_fieldsets/
    ordering -- overridden here since User has no username field, email is
    USERNAME_FIELD instead.
    """

    filter_horizontal = ("roles", "groups", "user_permissions")
    ordering = ("last_name", "first_name", "email")
    list_display = ("first_name", "last_name", "email", "is_staff")
    search_fields = ("email", "first_name", "last_name")
    fieldsets = (
        (None, {"fields": ("email", "password")}),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        (
            "Permissions",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "roles",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("Important dates", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2"),
            },
        ),
        ("Personal info", {"fields": ("first_name", "last_name")}),
        ("Permissions", {"fields": ("roles",)}),
    )


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("role",)


class PlayerPositionInline(admin.TabularInline):
    # PlayerPosition -> apps.teams.models.Position is the same canonical
    # position list used by apps.tryouts.TryoutSignupPosition; see
    # CLAUDE.md's "Baseball positions" note. Inlined here so a position is
    # editable right on the player -- this is the only place to edit it in
    # Django admin; the separate top-level "Player positions" page was
    # removed as redundant.
    model = PlayerPosition
    extra = 1


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "team", "jersey_number", "positions_display")
    list_filter = ("team",)
    search_fields = ("first_name", "last_name")
    inlines = [PlayerPositionInline]

    @admin.display(description="Positions")
    def positions_display(self, player):
        return ", ".join(p.get_position_display() for p in player.positions.all())


@admin.register(ParentPlayerLink)
class ParentPlayerLinkAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    list_display = ("parent", "player", "is_primary", "created_at", "is_active")
    list_filter = ("player__team", "is_primary")
    set_on_create = ("created_by",)

    def get_readonly_fields(self, request, obj=None):
        return (*super().get_readonly_fields(request, obj), "removed_by")

    def save_model(self, request, obj, form, change):
        # removed_by follows removed_at: whoever sets it is the remover.
        if "removed_at" in form.changed_data:
            obj.removed_by = request.user if obj.removed_at else None
        super().save_model(request, obj, form, change)


@admin.register(ParentInvite)
class ParentInviteAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    list_display = ("player", "created_by", "created_at", "expires_at", "claimed_at", "cancelled_at")
    set_on_create = ("created_by",)
    readonly_fields = ("claimed_by",)  # set by the claim flow


@admin.register(PlayerGalleryPhoto)
class PlayerGalleryPhotoAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    # Moderation fallback only -- parents manage these from the player page.
    list_display = ("player", "uploaded_by", "created_at")
    search_fields = ("player__first_name", "player__last_name")
    set_on_create = ("uploaded_by",)
