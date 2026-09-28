from django.urls import path

from . import views

urlpatterns = [
    path("admin/departments", views.DepartmentsView.as_view()),
    path("admin/departments/<str:code>", views.DepartmentView.as_view()),
    path("admin/categories", views.CategoriesView.as_view()),
    path("admin/categories/<str:code>", views.CategoryView.as_view()),
    path("admin/holidays", views.HolidaysView.as_view()),
    path("admin/holidays/<str:day>", views.HolidayView.as_view()),
    path("admin/sla-suspensions", views.SuspensionsView.as_view()),
    path("admin/sla-suspensions/<int:pk>", views.SuspensionView.as_view()),
    path("admin/users", views.UsersView.as_view()),
    path("admin/users/<uuid:user_id>", views.UserView.as_view()),
    path("admin/users/<uuid:user_id>/reset-password", views.UserResetPasswordView.as_view()),
    path("admin/stats", views.StatsView.as_view()),
    path("admin/reviews", views.ReviewsView.as_view()),
    path("admin/reviews/<uuid:review_id>/decision", views.ReviewDecisionView.as_view()),
]
