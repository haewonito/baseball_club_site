from django import forms

from apps.teams.models import Position, Team

from .models import TryoutSignup, TryoutSignupPosition


class TryoutSignupForm(forms.ModelForm):
    """
    Public-facing form for the try-out sign-up page. Deliberately excludes
    the admin-only fields (submitted_at, status, admin_notes) -- those are
    managed from the admin list, not set by the family.

    `positions` isn't a plain TryoutSignup field -- it's backed by
    TryoutSignupPosition (see models.py) so each selection is one of the
    canonical Position codes, never free text. save() below writes those
    rows after the main instance is saved.
    """

    team = forms.ModelChoiceField(
        queryset=Team.objects.filter(accepting_tryouts=True).order_by("-season_year", "division"),
        label="Which team are you trying out for?",
        empty_label="Select a team",
    )
    positions = forms.MultipleChoiceField(
        choices=Position.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Position(s)",
    )

    class Meta:
        model = TryoutSignup
        fields = [
            "team",
            "player_first_name",
            "player_last_name",
            "date_of_birth",
            "years_experience",
            "previous_team",
            "notes",
            "parent_first_name",
            "parent_last_name",
            "parent_phone",
            "parent_email",
        ]
        labels = {
            "player_first_name": "First name",
            "player_last_name": "Last name",
            "years_experience": "Years of experience",
            "previous_team": "Previous team (if any)",
            "notes": "Anything else we should know?",
            "parent_first_name": "First name",
            "parent_last_name": "Last name",
            "parent_phone": "Phone number",
            "parent_email": "Email address",
        }
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "previous_team": forms.TextInput(attrs={"placeholder": "e.g. Rockies 12U"}),
            "years_experience": forms.NumberInput(attrs={"min": 0}),
            "notes": forms.Textarea(attrs={"rows": 4}),
            "parent_phone": forms.TextInput(attrs={"type": "tel"}),
        }

    def save(self, commit=True):
        # Standard ModelForm only saves TryoutSignup's own fields; `positions`
        # is a related set, so it's handled separately here (mirrors the
        # usual save_m2m pattern -- this repo never calls save(commit=False)
        # on this form, so the simpler always-commit version is enough).
        signup = super().save(commit=commit)
        if commit:
            self._save_positions(signup)
        return signup

    def _save_positions(self, signup):
        signup.positions.all().delete()
        TryoutSignupPosition.objects.bulk_create(
            TryoutSignupPosition(signup=signup, position=code)
            for code in self.cleaned_data.get("positions", [])
        )
