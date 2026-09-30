from django.urls import include, path
from drf_spectacular.views import SpectacularAPIView

from apps.common import docs
from apps.common import views as common_views

api_v1 = [
    path("", include("apps.accounts.urls")),
    path("", include("apps.service_requests.urls")),
    path("", include("apps.collab.urls")),
    path("", include("apps.admin_api.urls")),
    path("", include("apps.audit.urls")),
]

urlpatterns = [
    path("health/live", common_views.live, name="health-live"),
    path("health/ready", common_views.ready, name="health-ready"),
    path("api/v1/", include(api_v1)),
    path("api/schema/", SpectacularAPIView.as_view(), name="schema"),
    path("api/docs/", docs.api_docs, name="docs"),
]

handler404 = "apps.common.errors.not_found"
handler500 = "apps.common.errors.server_error"
