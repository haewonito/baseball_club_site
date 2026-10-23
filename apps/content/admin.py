from django import forms
from django.contrib import admin
from django.utils.html import format_html

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
    readonly_fields = ("preview",)
    fields = ("image", "alt_text", "focus_y", "preview", "sort_order", "is_active")

    @admin.display(description="Banner preview")
    def preview(self, obj):
        # Same shape and crop rule as the home page banner (see .hero-banner in main.css).
        if not obj or not obj.image:
            return "Save the picture to see how it will be cropped."
        return format_html(
            '<div style="width:100%;max-width:700px;aspect-ratio:12/5;overflow:hidden;background:#111">'
            '<img src="{}" alt="" style="width:100%;height:100%;object-fit:cover;object-position:center {}%"></div>',
            obj.image.url,
            obj.focus_y,
        )
