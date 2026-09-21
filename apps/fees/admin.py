from django.contrib import admin

from .models import Fee, Payment


class PaymentInline(admin.TabularInline):
    model = Payment
    extra = 1


@admin.register(Fee)
class FeeAdmin(admin.ModelAdmin):
    list_display = ("description", "player", "team", "amount_due", "balance", "status")
    list_filter = ("team",)
    inlines = [PaymentInline]
    # Access here is Admin-only, plus the one league-owner head coach
    # who also holds the Admin role (see apps.accounts.models.User.roles).


@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = ("fee", "amount", "method", "paid_at", "recorded_by")
