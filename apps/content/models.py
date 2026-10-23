from django.db import models


class HeroImage(models.Model):
    """One picture in the banner slideshow right below the site header (home page). Managed in Django admin."""

    image = models.ImageField(upload_to="hero/")
    alt_text = models.CharField(
        max_length=200,
        blank=True,
        help_text="Describes the picture for screen readers, e.g. \"Players warming up before a game\".",
    )
    class Focus(models.IntegerChoices):
        TOP = 0, "Top"
        UPPER = 25, "Upper middle"
        MIDDLE = 50, "Middle"
        LOWER = 75, "Lower middle"
        BOTTOM = 100, "Bottom"

    focus_y = models.PositiveSmallIntegerField(
        "Part to keep",
        choices=Focus.choices,
        default=Focus.MIDDLE,
        help_text=(
            "The banner is a wide strip (about 12:5). A taller picture is cropped to fit, "
            "and this picks which part stays in view. The preview below shows the result."
        ),
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0, help_text="Lower numbers show first."
    )
    is_active = models.BooleanField(
        default=True, help_text="Untick to hide a picture without deleting it."
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order", "id"]
        verbose_name = "Banner Picture"
        verbose_name_plural = "Banner Pictures"

    def __str__(self):
        return self.alt_text or f"Banner picture {self.pk}"
