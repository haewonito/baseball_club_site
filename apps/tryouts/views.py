from django.shortcuts import redirect, render

from apps.teams.models import Team

from .forms import TryoutSignupForm


def signup(request):
    """Public try-out sign-up form. No login required."""
    accepting_tryouts = Team.objects.filter(accepting_tryouts=True).exists()
    form = None
    if accepting_tryouts:
        if request.method == "POST":
            form = TryoutSignupForm(request.POST)
            if form.is_valid():
                form.save()
                return redirect("tryouts:signup_success")
        else:
            form = TryoutSignupForm()
    return render(
        request,
        "tryouts/signup.html",
        {"form": form, "accepting_tryouts": accepting_tryouts},
    )


def signup_success(request):
    return render(request, "tryouts/signup_success.html")
