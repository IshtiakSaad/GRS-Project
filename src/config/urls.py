from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView, SpectacularSwaggerView

from apps.common import views as common_views

api_v1 = [
    path("", include("apps.accounts.urls")),
]

urlpatterns = [
    path("health/live", common_views.live, name="health-live"),
    path("health/ready", common_views.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", SpectacularSwaggerView.as_view(url_name="schema"), name="docs"),
]

handler404 = "apps.common.errors.not_found"
handler500 = "apps.common.errors.server_error"
