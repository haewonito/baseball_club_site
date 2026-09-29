from django.contrib import admin

from apps.accounts.admin_mixins import AutoUserFieldsAdminMixin

from .models import Fee, FeeReminder, Payment


@admin.register(Fee)
class FeeAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    set_on_create = ("created_by",)
    list_display = ("description", "player", "team", "amount_due", "balance", "status")
    list_filter = ("team",)
    # No PaymentInline here -- Payment is already its own registered
    # admin below; inlining it too would give a payment row two separate
    # edit surfaces in Django admin (here, and /admin/fees/payment/),
    # which is confusing without adding real capability. Every other
    # child/record model in this app (TryoutStatusChange,
    # TryoutDecisionChange, TryoutResponseInvite) is exposed the same
    # standalone way, never inlined on its parent.
    # Access here is Admin-only, plus the one league-owner head coach
    # who also holds the Admin role (see apps.accounts.models.User.roles).


@admin.register(Payment)
class PaymentAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    set_on_create = ("recorded_by",)
    list_display = ("fee", "amount", "method", "paid_at", "recorded_by")


@admin.register(FeeReminder)
class FeeReminderAdmin(admin.ModelAdmin):
    """History of Gus's automated overdue reminders (apps.fees.reminders). Read-only."""

    list_display = ("fee", "was_sent", "sent_to_email", "balance_at_send", "sent_at")
    list_filter = ("was_sent", "sent_at")
    search_fields = ("fee__player__first_name", "fee__player__last_name", "sent_to_email")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False
