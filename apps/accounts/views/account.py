import logging

from django.contrib import messages
from django.contrib.auth import logout as auth_logout
from django.contrib.auth.forms import AuthenticationForm
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import ValidationError
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST


from ..emails import read_unsubscribe_token, read_verification_token, send_verification_email
from ..forms import RegistrationForm, ResendVerificationForm
from ..models import Role, User, UserRole

logger = logging.getLogger(__name__)


class LoginForm(AuthenticationForm):
    """Blocks self-registered accounts until they've confirmed their email."""

    unverified = False

    def confirm_login_allowed(self, user):
        super().confirm_login_allowed(user)
        # Checked after the password, so this never reveals whether an email is registered.
        if not user.email_verified:
            self.unverified = True
            raise ValidationError(
                "Please confirm your email address first. We sent you a link when you registered.",
                code="unverified",
            )


class LoginView(BaseLoginView):
    template_name = "accounts/login.html"
    authentication_form = LoginForm

    def get_initial(self):
        # ?email= prefills the email box (the try-out sign-up form's
        # "log in first" prompt sends it).
        initial = super().get_initial()
        if self.request.method == "GET" and self.request.GET.get("email"):
            initial["username"] = self.request.GET["email"]
        return initial


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
    if user.is_prospective_parent:
        return redirect("accounts:dashboard_prospect")
    if user.is_superuser:
        return redirect("/admin/")
    return render(request, "accounts/no_dashboard.html")


# How long before a new verification email can be requested, so the resend
# form can't be used to burn through Resend's 100/day.
VERIFICATION_RESEND_MINUTES = 2


def _send_verification(user, request):
    """Sends the link and stamps verification_sent_at; returns False if the send failed."""
    try:
        send_verification_email(user, request)
    except Exception:
        logger.exception("Verification email failed for user %s", user.pk)
        return False
    user.verification_sent_at = timezone.now()
    user.save(update_fields=["verification_sent_at"])
    return True


def register(request):
    """Public: create an account (roles: prospective parent) before, or without, signing up for a try-out."""
    if request.user.is_authenticated:
        return redirect("accounts:dashboard")

    if request.method == "POST":
        form = RegistrationForm(request.POST)
        if form.is_valid():
            user = form.save()
            role, _ = UserRole.objects.get_or_create(role=Role.PROSPECTIVE_PARENT)
            user.roles.add(role)
            sent = _send_verification(user, request)
            return render(
                request, "accounts/register_check_email.html", {"email": user.email, "sent": sent}
            )
    else:
        form = RegistrationForm()
    return render(request, "accounts/register.html", {"form": form})


def verify_email(request, token):
    payload = read_verification_token(token)
    user = User.objects.filter(pk=payload["uid"], email=payload["email"]).first() if payload else None
    if user is None:
        return render(request, "accounts/verify_email_invalid.html")
    if not user.email_verified:
        user.email_verified = True
        user.save(update_fields=["email_verified"])
    messages.success(request, "Your email is confirmed. You can log in now.")
    return redirect("accounts:login")


def resend_verification(request):
    sent_to = None
    if request.method == "POST":
        form = ResendVerificationForm(request.POST)
        if form.is_valid():
            user = User.objects.filter(email__iexact=form.cleaned_data["email"]).first()
            recent = user and user.verification_sent_at and (
                timezone.now() - user.verification_sent_at
                < timezone.timedelta(minutes=VERIFICATION_RESEND_MINUTES)
            )
            if user and not user.email_verified and not recent:
                _send_verification(user, request)
            # Same answer whether or not the address is registered.
            sent_to = form.cleaned_data["email"]
    else:
        form = ResendVerificationForm(initial={"email": request.GET.get("email", "")})
    return render(
        request, "accounts/resend_verification.html", {"form": form, "sent_to": sent_to}
    )


@csrf_exempt
def unsubscribe(request, token):
    """
    The link in every "interested families" email. The signed token says who,
    so no login is needed; the button (a POST, so mail scanners that prefetch
    links can't unsubscribe anyone) turns the opt-in off. Mail apps'
    one-click List-Unsubscribe also POSTs here, so it's exempt from CSRF:
    the token is the credential.
    """
    uid = read_unsubscribe_token(token)
    user = User.objects.filter(pk=uid).first() if uid else None
    if user is None:
        return render(request, "accounts/unsubscribe.html", {"invalid": True})
    if request.method == "POST":
        user.info_emails_opt_in = False
        user.info_emails_opted_out_at = timezone.now()
        user.save(update_fields=["info_emails_opt_in", "info_emails_opted_out_at"])
        if request.POST.get("List-Unsubscribe") == "One-Click":
            return HttpResponse(status=200)
        return render(request, "accounts/unsubscribe.html", {"done": True, "email": user.email})
    return render(request, "accounts/unsubscribe.html", {"email": user.email})


@login_required
@require_POST
def info_emails_set(request):
    """The My Account page's opt-in / opt-out switch."""
    user = request.user
    if request.POST.get("opt_in") == "yes":
        user.info_emails_opt_in = True
        user.info_emails_opt_in_at = timezone.now()
        user.info_emails_opted_out_at = None
        messages.success(request, "You'll get emails about try-outs and club news.")
    else:
        user.info_emails_opt_in = False
        user.info_emails_opted_out_at = timezone.now()
        messages.success(request, "You won't get club info emails anymore.")
    user.save(
        update_fields=["info_emails_opt_in", "info_emails_opt_in_at", "info_emails_opted_out_at"]
    )
    return redirect("accounts:dashboard_prospect")


def account_delete_blocker(user):
    """Why `user` can't delete their own account from the site, or None if they can.

    Only families who never joined a team are self-service: anyone who has been
    linked to a player (even a removed link, which is audit history), holds a
    staff role, or has invoices goes through the club instead.
    """
    if user.is_staff or user.is_superuser or user.roles.filter(role__in=[Role.ADMIN, Role.COACH]).exists():
        return "This is a staff account."
    if user.player_links.exists() or user.invoices.exists():
        return "Your account is linked to a player on a team, so the club keeps its records."
    return None


@login_required
def account_delete(request):
    """Self-service "delete my account" for families who haven't joined a team. Asks for the password again."""
    user = request.user
    blocker = account_delete_blocker(user)
    error = None
    if request.method == "POST" and not blocker:
        if user.check_password(request.POST.get("password", "")):
            user.delete()
            auth_logout(request)
            return render(request, "accounts/account_deleted.html")
        error = "That password isn't right."
    return render(
        request, "accounts/account_delete.html", {"blocker": blocker, "error": error}
    )
