from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from apps.teams.models import PlayerPosition

from .models import ParentInvite, ParentPlayerLink, Player, User, UserRole


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    filter_horizontal = ("roles", "groups", "user_permissions")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("role",)


class PlayerPositionInline(admin.TabularInline):
    # PlayerPosition -> apps.teams.models.Position is the same canonical
    # position list used by apps.tryouts.TryoutSignupPosition; see
    # CLAUDE.md's "Baseball positions" note. Inlined here so a position is
    # editable right on the player, not only via the separate top-level
    # Player positions admin page.
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
class ParentPlayerLinkAdmin(admin.ModelAdmin):
    list_display = ("parent", "player", "created_at", "is_active")
    list_filter = ("player__team",)


@admin.register(ParentInvite)
class ParentInviteAdmin(admin.ModelAdmin):
    list_display = ("player", "created_by", "created_at", "expires_at", "claimed_at")
