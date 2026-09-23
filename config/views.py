from datetime import timedelta

from django.shortcuts import render
from django.utils import timezone

from apps.tryouts.models import TryoutYearSettings


def home(request):
    next_tryout_date = TryoutYearSettings.get_next_tryout_date()
    show_tryout_banner = False
    if next_tryout_date:
        today = timezone.localdate()
        show_tryout_banner = today <= next_tryout_date <= today + timedelta(days=30)

    return render(
        request,
        "home.html",
        {
            "next_tryout_date": next_tryout_date,
            "show_tryout_banner": show_tryout_banner,
        },
    )


def location(request):
    return render(request, "location.html")
