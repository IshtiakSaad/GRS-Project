from django.urls import path

from . import views

# Routes that hash a password must match the api-auth location in deploy/nginx/default.conf;
# tests/meta/test_bulkhead.py fails the build if one does not.
urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/otp/verify", views.VerifyPhoneView.as_view()),
    path("auth/otp/resend", views.ResendCodeView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/2fa/verify", views.SecondFactorView.as_view()),
    path("auth/2fa/recovery", views.RecoveryCodeView.as_view()),
    path("auth/2fa/setup", views.TotpSetupView.as_view()),
    path("auth/2fa/confirm", views.TotpConfirmView.as_view()),
    path("auth/token/refresh", views.RefreshView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("auth/password/reset/request", views.PasswordResetRequestView.as_view()),
    path("auth/password/reset/confirm", views.PasswordResetConfirmView.as_view()),
    path("auth/email/verify", views.EmailVerifyView.as_view()),
    path("me", views.MeView.as_view()),
    path("me/password", views.MyPasswordView.as_view()),
    path("me/sessions", views.MySessionsView.as_view()),
    path("me/sessions/<uuid:session_id>", views.MySessionView.as_view()),
    path("demo/sms/<str:phone>", views.DemoSmsView.as_view()),
]
