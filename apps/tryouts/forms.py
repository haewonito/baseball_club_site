from django import forms

from .models import TryoutSignup


class TryoutSignupForm(forms.ModelForm):
    """
    Public-facing form for the try-out sign-up page. Deliberately excludes
    the admin-only fields (submitted_at, tryout_year, status, admin_notes)
    -- those are set by the model's save() or managed from the admin list.
    """

    class Meta:
        model = TryoutSignup
        fields = [
            "player_first_name",
            "player_last_name",
            "date_of_birth",
            "positions",
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
            "positions": "Position(s)",
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
            "positions": forms.TextInput(attrs={"placeholder": "e.g. SS, 2B"}),
            "previous_team": forms.TextInput(attrs={"placeholder": "e.g. Rockies 12U"}),
            "years_experience": forms.NumberInput(attrs={"min": 0}),
            "notes": forms.Textarea(attrs={"rows": 4}),
            "parent_phone": forms.TextInput(attrs={"type": "tel"}),
        }
