from django.contrib import admin

from .models import CoachProfile, Team, TeamCoach


class TeamCoachInline(admin.TabularInline):
    model = TeamCoach
    extra = 1


@admin.register(Team)
class TeamAdmin(admin.ModelAdmin):
    list_display = ("name", "division", "season_year")
    list_filter = ("division", "season_year")
    inlines = [TeamCoachInline]


@admin.register(CoachProfile)
class CoachProfileAdmin(admin.ModelAdmin):
    list_display = ("coach",)
