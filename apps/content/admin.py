from django import forms
from django.contrib import admin

from apps.accounts.forms import downsize_image

from .models import HeroImage


class HeroImageAdminForm(forms.ModelForm):
    class Meta:
        model = HeroImage
        fields = "__all__"

    def clean_image(self):
        image = self.cleaned_data["image"]
        # Only a fresh upload is re-encoded; an unchanged field is a FieldFile.
        if hasattr(image, "content_type"):
            return downsize_image(image)
        return image


@admin.register(HeroImage)
class HeroImageAdmin(admin.ModelAdmin):
    form = HeroImageAdminForm
    list_display = ("__str__", "sort_order", "is_active", "created_at")
    list_editable = ("sort_order", "is_active")
