from django.contrib import admin, messages
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect
from django.template.response import TemplateResponse
from django.urls import path, reverse
from django.utils import timezone
from django.utils.html import format_html

from django import forms

from apps.accounts.forms import downsize_image

from .models import CoachProfile, Team, TeamCoach, TeamPhoto


class TeamCoachInline(admin.TabularInline):
    model = TeamCoach
    extra = 1


class TeamPhotoAdminForm(forms.ModelForm):
    class Meta:
        model = TeamPhoto
        fields = ("image", "caption", "is_featured")

    def clean_image(self):
        image = self.cleaned_data["image"]
        # Only a fresh upload is re-encoded; an unchanged field is a FieldFile.
        if hasattr(image, "content_type"):
            return downsize_image(image)
        return image


class TeamPhotoInline(admin.StackedInline):
    # Stacked rather than tabular so each field's help text (e.g. what "Is featured" does) is
    # printed under it; the tabular layout only shows it as a tiny "?" with a hover tooltip.
    model = TeamPhoto
    form = TeamPhotoAdminForm
    extra = 1


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "division",
        "season_year",
        "is_public",
        "accepting_tryouts",
    )
    list_filter = ("division", "season_year", "is_public", "accepting_tryouts")
    list_editable = ("is_public", "accepting_tryouts")
    inlines = [TeamCoachInline, TeamPhotoInline]

    def formfield_for_dbfield(self, db_field, request, **kwargs):
        field = super().formfield_for_dbfield(db_field, request, **kwargs)
        if db_field.name == "season_year":
            # Stored as the year the season ends (2027 = "2026-2027", see Team.season_label).
            field.label = "Season Ending Year"
            field.help_text = "The year the season ends: enter 2027 for the 2026-2027 season."
        return field

    def get_changeform_initial_data(self, request):
        # The Add Team form's season year starts at the season now under way or about to start:
        # from August on that is the one ending next year (e.g. 2026-2027), otherwise this year's.
        initial = super().get_changeform_initial_data(request)
        today = timezone.localdate()
        initial.setdefault("season_year", today.year + 1 if today.month >= 8 else today.year)
        return initial

    def save_formset(self, request, form, formset, change):
        instances = formset.save(commit=False)
        for obj in formset.deleted_objects:
            obj.delete()
        for obj in instances:
            if isinstance(obj, TeamPhoto) and obj.uploaded_by_id is None:
                obj.uploaded_by = request.user
            obj.save()
        formset.save_m2m()

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

    # The "Deleted team" placeholder (Team.is_deleted_placeholder) isn't a
    # real team: hidden here so it can't be edited, published or deleted.
    def get_queryset(self, request):
        return super().get_queryset(request).filter(is_deleted_placeholder=False)

    # Deleting a team keeps its try-out signups (moved to the "Deleted team"
    # placeholder) and players (left team-less), which Django's own delete
    # confirmation doesn't mention -- it only lists what gets deleted. Both
    # delete paths (the per-team Delete button and the bulk "Delete
    # selected" action) get a warning listing them; the templates are
    # apps/teams/templates/admin/teams/team/delete_*confirmation.html.
    def delete_view(self, request, object_id, extra_context=None):
        response = super().delete_view(request, object_id, extra_context)
        return self._add_delete_warning(response, Team.objects.filter(pk=object_id))

    def get_actions(self, request):
        actions = super().get_actions(request)
        if "delete_selected" in actions:
            delete_selected, name, description = actions["delete_selected"]

            def delete_selected_with_warning(modeladmin, request, queryset):
                response = delete_selected(modeladmin, request, queryset)
                return modeladmin._add_delete_warning(response, queryset)

            actions["delete_selected"] = (delete_selected_with_warning, name, description)
        return actions

    def _add_delete_warning(self, response, teams):
        # Only the confirmation page is a TemplateResponse; the confirmed
        # POST redirects, and by then the rows have already moved.
        if isinstance(response, TemplateResponse) and response.context_data is not None:
            from apps.accounts.models import Player
            from apps.tryouts.models import TryoutSignup

            response.context_data["signups_to_move"] = list(
                TryoutSignup.objects.filter(team__in=teams)
                .select_related("team")
                .order_by("team__name", "player_last_name", "player_first_name")
            )
            response.context_data["players_to_detach"] = list(
                Player.objects.filter(team__in=teams)
                .select_related("team")
                .order_by("team__name", "last_name", "first_name")
            )
        return response

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
            (
                "GameChanger schedule sync",
                {"fields": ("gamechanger_feed_url", "gamechanger_last_synced_at")},
            ),
        )

    def get_readonly_fields(self, request, obj=None):
        if obj is None:
            return ()
        return ("publish_status", "gamechanger_last_synced_at")

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
    list_display = ("coach", "list_first")
    list_editable = ("list_first",)
