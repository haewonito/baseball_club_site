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
        "tryout_year",
        "status",
    )
    list_filter = ("tryout_year", "status")
    search_fields = (
        "player_first_name",
        "player_last_name",
        "parent_first_name",
        "parent_last_name",
        "parent_email",
    )
    ordering = ["-submitted_at"]
    readonly_fields = ("submitted_at", "tryout_year")
    inlines = [TryoutSignupPositionInline]
    # Coaches get view-only access to this same list via a custom
    # permission check in a coach-facing view, not through this
    # admin-site registration.


@admin.register(TryoutYearSettings)
class TryoutYearSettingsAdmin(admin.ModelAdmin):
    list_display = ("cutoff_month", "cutoff_day")


@admin.register(TryoutStatusChange)
class TryoutStatusChangeAdmin(admin.ModelAdmin):
    list_display = ("signup", "old_status", "new_status", "changed_by", "changed_at")
