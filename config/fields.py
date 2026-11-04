from django import forms
from django.core.exceptions import ValidationError
from django.utils import timezone


class BirthDateInput(forms.DateInput):
    """Date picker whose latest selectable day is today (worked out at render time)."""

    input_type = "date"

    def __init__(self, attrs=None, format=None):
        super().__init__(attrs=attrs, format=format or "%Y-%m-%d")

    def get_context(self, name, value, attrs):
        attrs = {**(attrs or {}), "max": timezone.localdate().isoformat()}
        return super().get_context(name, value, attrs)


class BirthDateField(forms.DateField):
    """Date of birth: no dates in the future, in the picker or on the server."""

    widget = BirthDateInput

    def validate(self, value):
        super().validate(value)
        if value and value > timezone.localdate():
            raise ValidationError("Date of birth can't be in the future.")
