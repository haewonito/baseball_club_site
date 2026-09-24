from django.contrib import admin

from .models import (
    TryoutSignup,
    TryoutSignupPosition,
    TryoutStatusChange,
    TryoutYearSettings,
)


class TryoutSignupPositionInline(admin.TabularInline):
    model = TryoutSignupPosition
    extra = 1


@admin.register(TryoutSignup)
class TryoutSignupAdmin(admin.ModelAdmin):
    list_display = (
        "player_full_name",
        "positions_display",
        "parent_full_name",
        "parent_phone",
        "submitted_at",
        "team",
        "status",
    )
    list_filter = ("team", "status")
    search_fields = (
        "player_first_name",
        "player_last_name",
        "parent_first_name",
        "parent_last_name",
        "parent_email",
    )
    ordering = ["-submitted_at"]
    readonly_fields = ("submitted_at",)
    inlines = [TryoutSignupPositionInline]
    # Coaches get view-only access to this same list via a custom
    # permission check in a coach-facing view, not through this
    # admin-site registration.


@admin.register(TryoutYearSettings)
class TryoutYearSettingsAdmin(admin.ModelAdmin):
    list_display = ("next_tryout_date",)


@admin.register(TryoutStatusChange)
class TryoutStatusChangeAdmin(admin.ModelAdmin):
    """
    Read-only -- this is an append-only audit trail (see CLAUDE.md), so
    editing/deleting rows here would let an admin falsify history that's
    meant to be immutable. Rows are written by the status-change flow on
    the custom admin dashboard, not created here.
    """

    list_display = ("signup", "old_status", "new_status", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False
