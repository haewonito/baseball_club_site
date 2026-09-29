from django.contrib import admin

from apps.accounts.admin_mixins import AutoUserFieldsAdminMixin

from .models import Event


@admin.register(Event)
class EventAdmin(AutoUserFieldsAdminMixin, admin.ModelAdmin):
    set_on_create = ("created_by",)
    set_on_save = ("updated_by",)
    list_display = ("team", "event_type", "start_datetime", "location_name", "status")
    list_filter = ("team", "event_type", "status")
    ordering = ["start_datetime"]
    # Coach permission scoping (edit own team's practices, view-only on
    # tournaments) is enforced in coach-facing views, not here -- this
    # registration is the full-access admin view.
