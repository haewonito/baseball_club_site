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
        widgets = {
            "focus_x": forms.HiddenInput,
            "focus_y": forms.HiddenInput,
            "zoom": forms.HiddenInput,
        }

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
    fields = ("image", "alt_text", "preview", "focus_x", "focus_y", "zoom", "sort_order", "is_active")

    class Media:
        js = ("js/hero-crop.js",)

    @admin.display(description="Crop")
    def preview(self, obj):
        # Same shape and crop rule as the home page banner (.hero-banner in
        # main.css); hero-crop.js lets you drag the picture and zoom to choose what stays in view.
        has_image = bool(obj and obj.image)
        x = obj.focus_x if obj else 50
        y = obj.focus_y if obj else 50
        zoom = obj.zoom if obj else 100
        return format_html(
            '<div data-crop-frame style="width:100%;max-width:700px;aspect-ratio:12/5;overflow:hidden;'
            'background:#111;cursor:grab;touch-action:none;position:relative">'
            '<img src="{}" alt="" draggable="false" style="width:100%;height:100%;object-fit:cover;'
            'object-position:{}% {}%;transform-origin:{}% {}%;transform:scale({});'
            'user-select:none;display:{}"></div>'
            '<p style="margin:.6rem 0 0"><label>Zoom <input type="range" data-crop-zoom min="100" max="300" '
            'step="5" value="{}" style="vertical-align:middle;width:220px"></label></p>'
            '<p class="help">The banner shows this strip. Zoom in to cut off the edges you don\'t want, '
            "then drag the picture to choose what stays in view, and save. "
            "Choosing a new file shows it here first.</p>",
            obj.image.url if has_image else "",
            x, y, x, y, zoom / 100,
            "block" if has_image else "none",
            zoom,
        )
