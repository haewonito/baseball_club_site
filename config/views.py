from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from apps.content.models import HeroImage
from apps.tryouts.models import TryoutPoster, TryoutYearSettings

HOME_FIELD_ADDRESS = "1833 E Harmony Rd, Fort Collins, CO, United States, 80528"


def home(request):
    next_tryout_date = TryoutYearSettings.get_next_tryout_date()
    show_tryout_banner = False
    if next_tryout_date:
        today = timezone.localdate()
        show_tryout_banner = today <= next_tryout_date <= today + timedelta(days=30)

    # Banner slides: active try-out posters first (linking to the sign-up
    # form), then the banner pictures (each linking to its team's page).
    banner_slides = [
        {"kind": "poster", "poster": poster}
        for poster in TryoutPoster.objects.filter(is_active=True)
    ] + [
        {"kind": "picture", "image": image}
        for image in HeroImage.objects.filter(is_active=True).select_related("team")
    ]

    return render(
        request,
        "home.html",
        {
            "next_tryout_date": next_tryout_date,
            "show_tryout_banner": show_tryout_banner,
            "banner_slides": banner_slides,
        },
    )


def about(request):
    return render(request, "about.html")


def location(request):
    return render(request, "location.html", {"address": HOME_FIELD_ADDRESS})
