from django.urls import path

from . import views

app_name = "tryouts"

urlpatterns = [
    path("", views.signup, name="signup"),
    path("thanks/", views.signup_success, name="signup_success"),
    path("respond/<uuid:token>/", views.respond, name="respond"),
]
