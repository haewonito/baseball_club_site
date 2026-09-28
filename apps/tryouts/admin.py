from django.contrib import admin

from .models import (
    TryoutDecisionChange,
    TryoutPoster,
    TryoutResponseInvite,
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
        "coach_decision",
        "family_response",
    )
    list_filter = ("team", "status", "coach_decision", "family_response")
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
    editing rows here would let an admin falsify history that's meant to be
    immutable. Rows are written by the status-change flow on the custom
    admin dashboard, not created here.

    Superusers may delete, though: deleting a TryoutSignup cascades to its
    audit rows, and Django admin refuses the whole signup deletion unless
    it may delete those rows too.
    """

    list_display = ("signup", "old_status", "new_status", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TryoutResponseInvite)
class TryoutResponseInviteAdmin(admin.ModelAdmin):
    list_display = ("signup", "created_by", "created_at", "expires_at", "responded_at")


@admin.register(TryoutDecisionChange)
class TryoutDecisionChangeAdmin(admin.ModelAdmin):
    """Read-only except superuser deletes, same reasoning as TryoutStatusChangeAdmin above."""

    list_display = ("signup", "old_decision", "new_decision", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TryoutPoster)
class TryoutPosterAdmin(admin.ModelAdmin):
    # Secondary access point for Django-admin superusers -- the primary
    # upload/edit flow is the custom accounts dashboard page
    # (admin_tryout_posters_list etc.), since a business-Admin-role user
    # may not have Django-admin access at all (same reasoning as
    # CoachProfile's admin_coach_bio_edit).
    list_display = ("title", "poster_type", "is_active", "display_order", "created_at")
    list_filter = ("poster_type", "is_active")
