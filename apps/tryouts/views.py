from django.shortcuts import redirect, render

from .forms import TryoutSignupForm


def signup(request):
    """Public try-out sign-up form. No login required."""
    if request.method == "POST":
        form = TryoutSignupForm(request.POST)
        if form.is_valid():
            form.save()
            return redirect("tryouts:signup_success")
    else:
        form = TryoutSignupForm()
    return render(request, "tryouts/signup.html", {"form": form})


def signup_success(request):
    return render(request, "tryouts/signup_success.html")
