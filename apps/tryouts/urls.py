from django.urls import path

from . import views

app_name = "tryouts"

urlpatterns = [
    path("", views.signup, name="signup"),
    path("thanks/", views.signup_success, name="signup_success"),
    # admin list/detail, HTMX status-change endpoint go here later
]
