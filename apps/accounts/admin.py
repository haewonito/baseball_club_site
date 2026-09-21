from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as DjangoUserAdmin

from .models import ParentInvite, ParentPlayerLink, Player, User, UserRole


@admin.register(User)
class UserAdmin(DjangoUserAdmin):
    filter_horizontal = ("roles", "groups", "user_permissions")


@admin.register(UserRole)
class UserRoleAdmin(admin.ModelAdmin):
    list_display = ("role",)


@admin.register(Player)
class PlayerAdmin(admin.ModelAdmin):
    list_display = ("first_name", "last_name", "team", "jersey_number")
    list_filter = ("team",)
    search_fields = ("first_name", "last_name")


@admin.register(ParentPlayerLink)
class ParentPlayerLinkAdmin(admin.ModelAdmin):
    list_display = ("parent", "player", "created_at", "is_active")
    list_filter = ("player__team",)


@admin.register(ParentInvite)
class ParentInviteAdmin(admin.ModelAdmin):
    list_display = ("player", "created_by", "created_at", "expires_at", "claimed_at")
