from django import forms
from django.contrib import admin
from django.utils.html import format_html

from apps.accounts.forms import downsize_image

from .models import HeroImage


class HeroImageAdminForm(forms.ModelForm):
    class Meta:
        model = HeroImage
        fields = "__all__"
        # Set by dragging the picture in the preview frame (hero-crop.js).
        widgets = {"focus_x": forms.HiddenInput, "focus_y": forms.HiddenInput}

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
    fields = ("image", "alt_text", "preview", "focus_x", "focus_y", "sort_order", "is_active")

    class Media:
        js = ("js/hero-crop.js",)

    @admin.display(description="Crop")
    def preview(self, obj):
        # Same shape and crop rule as the home page banner (.hero-banner in
        # main.css); hero-crop.js lets you drag the picture to choose what stays in view.
        has_image = bool(obj and obj.image)
        return format_html(
            '<div data-crop-frame style="width:100%;max-width:700px;aspect-ratio:12/5;overflow:hidden;'
            'background:#111;cursor:grab;touch-action:none;position:relative">'
            '<img src="{}" alt="" draggable="false" style="width:100%;height:100%;object-fit:cover;'
            'object-position:{}% {}%;user-select:none;display:{}"></div>'
            '<p class="help">The banner shows this strip. Drag the picture to choose what stays in view, '
            "then save. Choosing a new file shows it here first.</p>",
            obj.image.url if has_image else "",
            obj.focus_x if obj else 50,
            obj.focus_y if obj else 50,
            "block" if has_image else "none",
        )
