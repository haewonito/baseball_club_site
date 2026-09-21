from django.contrib import admin

from .models import Event


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("team", "event_type", "start_datetime", "location_name", "status")
    list_filter = ("team", "event_type", "status")
    ordering = ["start_datetime"]
    # Coach permission scoping (edit own team's practices, view-only on
    # tournaments) is enforced in coach-facing views, not here -- this
    # registration is the full-access admin view.
