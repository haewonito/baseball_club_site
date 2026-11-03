from django import forms


class BugReportForm(forms.Form):
    message = forms.CharField(
        label="What went wrong?",
        max_length=2000,
        widget=forms.Textarea(attrs={"rows": 6}),
        help_text="Tell us what you were doing and what you expected to happen.",
    )
    reporter_email = forms.EmailField(
        label="Your email (optional)",
        required=False,
        help_text="Only if you'd like a reply.",
    )
    # Hidden from people with CSS; bots tend to fill every field.
    website = forms.CharField(required=False, widget=forms.TextInput(attrs={"tabindex": "-1", "autocomplete": "off"}))
    page = forms.CharField(required=False, max_length=300, widget=forms.HiddenInput)
