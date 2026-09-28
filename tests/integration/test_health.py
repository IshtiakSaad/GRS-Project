import pytest
from django.test import override_settings

pytestmark = pytest.mark.django_db

DEAD_REDIS = "redis://127.0.0.1:1/0"  # nothing listens on port 1


def test_live_answers_without_checking_dependencies(client):
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_ready_reports_build_and_database(client, settings):
    settings.BUILD_SHA = "abc1234"
    response = client.get("/health/ready")
    body = response.json()
    assert response.status_code == 200
    assert body["database"] is True
    assert body["build"] == "abc1234"


@override_settings(REDIS_CACHE_URL=DEAD_REDIS, REDIS_BROKER_URL=DEAD_REDIS)
def test_redis_down_is_degraded_not_unavailable(client):
    # Submissions need only PostgreSQL, so a Redis outage must keep the API in rotation.
    response = client.get("/health/ready")
    body = response.json()
    assert response.status_code == 200
    assert body["status"] == "ok"
    assert set(body["degraded"]) == {"redis-cache", "redis-broker"}
