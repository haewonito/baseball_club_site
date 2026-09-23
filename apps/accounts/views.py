from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import redirect, render


class LoginView(BaseLoginView):
    template_name = "accounts/login.html"


@login_required
def dashboard_redirect(request):
    """
    Single landing point after login. Priority when a user holds more than
    one role (e.g. the league owner, who is both Admin and Coach) is
    admin > coach > parent -- Admin is the most privileged view.
    """
    user = request.user
    if user.is_admin:
        return redirect("accounts:dashboard_admin")
    if user.is_coach:
        return redirect("accounts:dashboard_coach")
    if user.is_parent:
        return redirect("accounts:dashboard_parent")
    if user.is_superuser:
        return redirect("/admin/")
    return render(request, "accounts/no_dashboard.html")


@login_required
def dashboard_admin(request):
    if not request.user.is_admin:
        raise PermissionDenied
    return render(request, "accounts/dashboard_admin.html")


@login_required
def dashboard_coach(request):
    if not request.user.is_coach:
        raise PermissionDenied
    return render(request, "accounts/dashboard_coach.html")


@login_required
def dashboard_parent(request):
    if not request.user.is_parent:
        raise PermissionDenied
    return render(request, "accounts/dashboard_parent.html")
