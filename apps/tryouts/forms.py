from django import forms
from django.db.models import Q

from apps.teams.models import Position, Team
from config.fields import BirthDateField

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
        field_classes = {"date_of_birth": BirthDateField}
        widgets = {
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
        if self.user:
            self.fields["parent_email"].help_text = (
                "Updates and the try-out result are emailed here. It can differ from your account email. "
                "Our emails sometimes land in spam, so please check there."
            )

    def clean(self):
        cleaned = super().clean()
        team, first, last, dob = (
            cleaned.get(k) for k in ("team", "player_first_name", "player_last_name", "date_of_birth")
        )
        if team and first and last and dob:
            same = TryoutSignup.objects.filter(
                team=team,
                player_first_name__iexact=first.strip(),
                player_last_name__iexact=last.strip(),
                date_of_birth=dob,
                withdrawn_at__isnull=True,
            ).exclude(pk=self.instance.pk)
            if same.exists():
                raise forms.ValidationError(
                    f"{first} {last} already has a sign-up for {team.display_name}. "
                    "To change it, log in and use My Account; otherwise contact the club."
                )
        return cleaned

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
        self._write_kid(kid, signup)

    def _write_kid(self, kid, signup):
        """Copies the sign-up's player details onto a saved kid and links the two."""
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


class TryoutSignupEditForm(TryoutSignupForm):
    """A family changing an existing sign-up from their account (accounts.prospect_signup_edit).
    Same fields as the sign-up page, minus the saved-player controls; the team can be changed,
    and the current one stays selectable even if it has stopped accepting try-outs."""

    def __init__(self, *args, user=None, **kwargs):
        super().__init__(*args, user=user, **kwargs)
        self.fields.pop("prospective_player", None)
        self.fields.pop("save_player", None)
        self.fields["team"].queryset = Team.objects.filter(
            Q(accepting_tryouts=True) | Q(pk=self.instance.team_id), is_deleted_placeholder=False
        ).order_by("-season_year", "division")
        self.initial.setdefault("positions", [p.position for p in self.instance.positions.all()])

    def _sync_prospect(self, signup):
        # Keep the saved kid this sign-up came from in step with the changes.
        kid = signup.prospective_player
        if kid is not None and kid.promoted_player_id is None:
            self._write_kid(kid, signup)


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
        field_classes = {"date_of_birth": BirthDateField}
        widgets = {
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
