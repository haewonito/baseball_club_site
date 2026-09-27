from django.contrib import admin

from .models import Fee, Payment


@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
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
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("fee", "amount", "method", "paid_at", "recorded_by")
