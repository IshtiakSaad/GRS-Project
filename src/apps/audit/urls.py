from django.urls import path

from . import views

urlpatterns = [
    path("requests/<uuid:request_id>/access-log", views.AccessLogView.as_view()),
    path("admin/break-glass", views.BreakGlassReportView.as_view()),
]
