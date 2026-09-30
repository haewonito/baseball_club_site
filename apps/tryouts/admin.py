from django.contrib import admin

from apps.accounts.admin_mixins import AutoUserFieldsAdminMixin

from .models import (
    TryoutDecisionChange,
    TryoutMassEmail,
    TryoutPoster,
    TryoutResponseInvite,
    TryoutSignup,
    TryoutSignupPosition,
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
        "coach_decision",
        "family_response",
    )
    list_filter = ("team", "coach_decision", "family_response")
    search_fields = (
        "player_first_name",
        "player_last_name",
        "parent_first_name",
        "parent_last_name",
        "parent_email",
    )
    readonly_fields = ("submitted_at",)
    inlines = [TryoutSignupPositionInline]
    # Coaches get view-only access to this same list via a custom
    # permission check in a coach-facing view, not through this
    # admin-site registration.


@admin.register(TryoutYearSettings)
class TryoutYearSettingsAdmin(admin.ModelAdmin):
    list_display = ("next_tryout_date",)


@admin.register(TryoutResponseInvite)
class TryoutResponseInviteAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    set_on_create = ("created_by",)
    list_display = ("signup", "created_by", "created_at", "expires_at", "responded_at")


@admin.register(TryoutDecisionChange)
class TryoutDecisionChangeAdmin(admin.ModelAdmin):
    """Read-only except superuser deletes, same reasoning as the decision-change audit admin."""

    list_display = ("signup", "old_decision", "new_decision", "changed_by", "changed_at")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TryoutMassEmail)
class TryoutMassEmailAdmin(admin.ModelAdmin):
    """Read-only history of Email Families sends; they're sent from the
    dashboard page (accounts.tryout_mass_email), not created here."""

    list_display = ("subject", "sent_by", "team", "decision", "sent_at")
    readonly_fields = ("sent_by", "sent_at", "team", "decision", "subject", "body", "recipients")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return request.user.is_superuser


@admin.register(TryoutPoster)
class TryoutPosterAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    set_on_create = ("uploaded_by",)
    # Secondary access point for Django-admin superusers -- the primary
    # upload/edit flow is the custom accounts dashboard page
    # (admin_tryout_posters_list etc.), since a business-Admin-role user
    # may not have Django-admin access at all (same reasoning as
    # CoachProfile's coach_detail).
    list_display = ("title", "poster_type", "is_active", "display_order", "created_at")
    list_filter = ("poster_type", "is_active")
