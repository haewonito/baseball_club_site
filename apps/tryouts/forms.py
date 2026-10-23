from django import forms

from apps.teams.models import Position, Team

from .models import (
    ProspectivePlayer,
    ProspectivePlayerPosition,
    TryoutSignup,
    TryoutSignupPosition,
)


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
        queryset=Team.objects.filter(accepting_tryouts=True, is_deleted_placeholder=False).order_by("-season_year", "division"),
        label="Which team are you trying out for?",
        empty_label="Select a team",
    )
    positions = forms.MultipleChoiceField(
        choices=Position.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Position(s)",
    )

    # Only for logged-in parents (dropped in __init__ otherwise): which saved
    # kid this is filled from, and whether to save a new one to the account.
    prospective_player = forms.ModelChoiceField(
        queryset=ProspectivePlayer.objects.none(),
        required=False,
        widget=forms.HiddenInput,
    )
    save_player = forms.BooleanField(
        required=False,
        label="Save this player to my account so I don't have to retype it",
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
        help_texts = {
            "parent_email": (
                "We'll email a confirmation here. Our emails sometimes land in spam, "
                "so please check there if you don't see it."
            ),
        }
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "previous_team": forms.TextInput(attrs={"placeholder": "e.g. Rockies 12U"}),
            "years_experience": forms.NumberInput(attrs={"min": 0}),
            "notes": forms.Textarea(attrs={"rows": 4}),
            "parent_phone": forms.TextInput(attrs={"type": "tel"}),
        }

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.user = user if user is not None and user.is_authenticated else None
        if self.user:
            # Only kids that haven't joined a team yet are offered.
            self.fields["prospective_player"].queryset = self.user.prospective_players.filter(
                promoted_player__isnull=True
            )
        else:
            del self.fields["prospective_player"]
            del self.fields["save_player"]
        # Required here but still nullable on the model, since older
        # sign-ups may lack it -- Player needs it for roster promotion
        # (apps.tryouts.roster.promote_signup_to_roster).
        self.fields["date_of_birth"].required = True

    def save(self, commit=True):
        # Standard ModelForm only saves TryoutSignup's own fields; `positions`
        # is a related set, so it's handled separately here (mirrors the
        # usual save_m2m pattern -- this repo never calls save(commit=False)
        # on this form, so the simpler always-commit version is enough).
        if self.user:
            self.instance.user = self.user
        signup = super().save(commit=commit)
        if commit:
            self._save_positions(signup)
            if self.user:
                self._sync_prospect(signup)
        return signup

    def _sync_prospect(self, signup):
        """Update the chosen saved kid with what was just submitted, or save a new one if asked."""
        kid = self.cleaned_data.get("prospective_player")
        if kid is None and not self.cleaned_data.get("save_player"):
            return
        if kid is None:
            kid = ProspectivePlayer(user=self.user)
        kid.first_name = signup.player_first_name
        kid.last_name = signup.player_last_name
        kid.date_of_birth = signup.date_of_birth
        kid.years_experience = signup.years_experience
        kid.previous_team = signup.previous_team
        kid.notes = signup.notes
        kid.save()
        kid.positions.all().delete()
        ProspectivePlayerPosition.objects.bulk_create(
            ProspectivePlayerPosition(prospect=kid, position=code)
            for code in self.cleaned_data.get("positions", [])
        )
        signup.prospective_player = kid
        signup.save(update_fields=["prospective_player"])

    def _save_positions(self, signup):
        signup.positions.all().delete()
        TryoutSignupPosition.objects.bulk_create(
            TryoutSignupPosition(signup=signup, position=code)
            for code in self.cleaned_data.get("positions", [])
        )


class ProspectivePlayerForm(forms.ModelForm):
    """A family's saved kid (dashboard add/edit). Positions are the canonical codes, as on the sign-up form."""

    positions = forms.MultipleChoiceField(
        choices=Position.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Position(s)",
    )

    class Meta:
        model = ProspectivePlayer
        fields = [
            "first_name",
            "last_name",
            "date_of_birth",
            "years_experience",
            "previous_team",
            "notes",
        ]
        labels = {
            "years_experience": "Years of experience",
            "previous_team": "Previous team (if any)",
            "notes": "Anything else we should know?",
        }
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
            "previous_team": forms.TextInput(attrs={"placeholder": "e.g. Rockies 12U"}),
            "years_experience": forms.NumberInput(attrs={"min": 0}),
            "notes": forms.Textarea(attrs={"rows": 4}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["positions"].initial = [p.position for p in self.instance.positions.all()]

    def save(self, commit=True):
        kid = super().save(commit=commit)
        if commit:
            kid.positions.all().delete()
            ProspectivePlayerPosition.objects.bulk_create(
                ProspectivePlayerPosition(prospect=kid, position=code)
                for code in self.cleaned_data.get("positions", [])
            )
        return kid
