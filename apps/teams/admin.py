from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.urls import path, reverse
from django.utils.html import format_html

from .models import CoachProfile, Team, TeamCoach


class TeamCoachInline(admin.TabularInline):
    model = TeamCoach
    extra = 1


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "division", "season_year", "is_public", "accepting_tryouts")
    list_filter = ("division", "season_year", "is_public", "accepting_tryouts")
    list_editable = ("is_public", "accepting_tryouts")
    inlines = [TeamCoachInline]

    def get_urls(self):
        custom = [
            path(
                "<int:object_id>/publish/",
                self.admin_site.admin_view(self.publish_view),
                name="teams_team_publish",
            ),
        ]
        return custom + super().get_urls()

    def publish_view(self, request, object_id):
        if request.method != "POST":
            return redirect("admin:teams_team_change", object_id)
        team = get_object_or_404(Team, pk=object_id)
        if not self.has_change_permission(request, team):
            raise PermissionDenied
        team.is_public = not team.is_public
        team.save(update_fields=["is_public"])
        if team.is_public:
            messages.success(request, f'"{team}" is now public.')
        else:
            messages.success(request, f'"{team}" reverted to draft -- no longer public.')
        return redirect("admin:teams_team_change", object_id)

    def get_fieldsets(self, request, obj=None):
        if obj is None:
            # Creating a new team -- let the admin set the initial
            # visibility directly rather than always defaulting public
            # (Team.is_public's model default) and requiring a second step.
            return (
                (
                    None,
                    {
                        "fields": (
                            "name",
                            "division",
                            "season_year",
                            "is_public",
                            "accepting_tryouts",
                        )
                    },
                ),
            )
        return (
            (None, {"fields": ("name", "division", "season_year", "accepting_tryouts")}),
            ("Publish Status", {"fields": ("publish_status",)}),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("publish_status",)

    @admin.display(description="")
    def publish_status(self, obj):
        publish_url = reverse("admin:teams_team_publish", args=[obj.pk])
        if obj.is_public:
            return format_html(
                '<p style="color: #2e7d32; margin: 0 0 0.75rem;">'
                "This team is public &mdash; visible on the Teams, Coaches, and Schedule pages."
                "</p>"
                '<button type="submit" formaction="{}" formmethod="post" class="button">'
                "Unpublish (revert to draft)"
                "</button>",
                publish_url,
            )
        return format_html(
            '<p style="color: #a50d26; margin: 0 0 0.75rem;">'
            "This team is in <strong>draft mode</strong> and not shown anywhere on the "
            "public site (Teams, Coaches, Schedule). Click below once the roster is "
            "finalized and you&rsquo;re ready to make it public."
            "</p>"
            '<button type="submit" formaction="{}" formmethod="post" class="button default">'
            "Publish Team"
            "</button>",
            publish_url,
        )


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("coach",)
