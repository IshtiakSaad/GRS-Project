from django.urls import path

from . import views

urlpatterns = [
    path("categories", views.CategoriesView.as_view()),
    path("requests", views.RequestsView.as_view()),
    path("requests/by-tracking/<str:number>", views.ByTrackingView.as_view()),
    path("requests/break-glass", views.BreakGlassView.as_view()),
    path("requests/<uuid:request_id>", views.RequestView.as_view()),
    path("requests/<uuid:request_id>/actions/<str:action>", views.RequestActionView.as_view()),
    path("requests/<uuid:request_id>/priority", views.RequestPriorityView.as_view()),
    path("requests/<uuid:request_id>/timeline", views.TimelineView.as_view()),
    path("queue", views.QueueView.as_view()),
    path("queue/claim-next", views.ClaimNextView.as_view()),
]
