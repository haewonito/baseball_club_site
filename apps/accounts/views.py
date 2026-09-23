from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import LoginView as BaseLoginView
from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from apps.fees.models import Payment

from .models import ParentPlayerLink


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

    links = (
        ParentPlayerLink.objects.filter(parent=request.user, removed_at__isnull=True)
        .select_related("player", "player__team")
        .prefetch_related("player__fees__payments")
    )
    now = timezone.now()
    cards = []
    for link in links:
        player = link.player
        next_event = None
        if player.team:
            next_event = player.team.events.filter(start_datetime__gte=now).order_by("start_datetime").first()
        # Team-wide fees (Fee.player=None) aren't included here -- per
        # CLAUDE.md that's an open design question, not yet resolved.
        balance = sum(fee.balance for fee in player.fees.all())
        cards.append({"player": player, "next_event": next_event, "balance": balance})

    return render(request, "accounts/dashboard_parent.html", {"cards": cards})


@login_required
def parent_player_payments(request, player_id):
    if not request.user.is_parent:
        raise PermissionDenied

    link = get_object_or_404(
        ParentPlayerLink.objects.select_related("player"),
        parent=request.user,
        player_id=player_id,
        removed_at__isnull=True,
    )
    player = link.player
    fees = list(player.fees.all())
    total_due = sum(fee.amount_due for fee in fees)

    payments = Payment.objects.filter(fee__player=player).select_related("fee").order_by("paid_at", "recorded_at")
    running_total = 0
    rows = []
    for payment in payments:
        running_total += payment.amount
        rows.append({"payment": payment, "running_total": running_total})

    return render(
        request,
        "accounts/parent_player_payments.html",
        {
            "player": player,
            "rows": rows,
            "total_due": total_due,
            "total_paid": running_total,
            "balance": total_due - running_total,
        },
    )
