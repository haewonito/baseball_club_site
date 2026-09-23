from django import forms

from apps.schedule.models import Event
from apps.teams.models import PlayerPosition, Position

from .models import Player


class PlayerRosterForm(forms.ModelForm):
    """
    Used for both adding a new player to a team and editing an existing
    one -- `team` isn't a form field, it's set on the instance by the view
    before binding, the same way TryoutSignupForm handles `positions`
    (see apps/tryouts/forms.py) via a separate M2M-style save step.
    """

    positions = forms.MultipleChoiceField(
        choices=Position.choices,
        required=False,
        widget=forms.CheckboxSelectMultiple,
        label="Position(s)",
    )

    class Meta:
        model = Player
        fields = ["first_name", "last_name", "date_of_birth", "jersey_number"]
        widgets = {
            "date_of_birth": forms.DateInput(attrs={"type": "date"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["positions"].initial = list(
                self.instance.positions.values_list("position", flat=True)
            )

    def save(self, commit=True):
        player = super().save(commit=commit)
        if commit:
            self._save_positions(player)
        return player

    def _save_positions(self, player):
        player.positions.all().delete()
        PlayerPosition.objects.bulk_create(
            PlayerPosition(player=player, position=code)
            for code in self.cleaned_data.get("positions", [])
        )


class PracticeEventForm(forms.ModelForm):
    """`team` and `event_type` aren't form fields -- set on the instance by
    the view before binding, so a coach can't reassign a practice to a
    different team or relabel it as a tournament through this form."""

    # HTML5 datetime-local inputs submit "YYYY-MM-DDTHH:MM" (T-separated),
    # which isn't in Django's default DATETIME_INPUT_FORMATS (space-
    # separated) -- declared explicitly here so parsing the POST works,
    # not just rendering the initial value.
    start_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
    )
    end_datetime = forms.DateTimeField(
        input_formats=["%Y-%m-%dT%H:%M"],
        widget=forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
        required=False,
    )

    class Meta:
        model = Event
        fields = [
            "title",
            "start_datetime",
            "end_datetime",
            "location_name",
            "location_address",
            "notes",
            "status",
        ]
        widgets = {
            "notes": forms.Textarea(attrs={"rows": 3}),
        }
