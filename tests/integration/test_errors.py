import pytest
from django.test import Client

pytestmark = pytest.mark.urls("tests.integration.error_urls")


def _error(response):
    body = response.json()
    assert set(body) == {"error"}
    assert set(body["error"]) == {"code", "message", "fields", "request_id"}
    assert body["error"]["request_id"] == response["X-Request-ID"]
    return body["error"]


def test_validation_error_lists_fields(client):
    response = client.post(
        "/validation", {"title": "far too long"}, content_type="application/json"
    )
    assert response.status_code == 400
    error = _error(response)
    assert error["code"] == "VALIDATION_ERROR"
    assert "title" in error["fields"]


def test_domain_error_keeps_its_code_and_status(client):
    response = client.post("/domain", content_type="application/json")
    assert response.status_code == 409
    assert _error(response)["code"] == "INVALID_TRANSITION"


def test_malformed_json_is_an_envelope_too(client):
    response = client.post("/validation", "{not json", content_type="application/json")
    assert response.status_code == 400
    assert _error(response)["code"] == "MALFORMED_REQUEST"


def test_views_are_closed_by_default(client):
    # A view that forgets to declare permissions must not be public.
    response = client.get("/default-permission")
    assert response.status_code == 401
    assert _error(response)["code"] == "NOT_AUTHENTICATED"
    assert response["WWW-Authenticate"].startswith("Bearer")
    assert b"leaked" not in response.content


def test_unknown_url_is_json_404(client):
    response = client.get("/does-not-exist")
    assert response.status_code == 404
    assert _error(response)["code"] == "NOT_FOUND"


def test_crash_is_json_500_without_internals():
    response = Client(raise_request_exception=False).get("/crash")
    assert response.status_code == 500
    error = _error(response)
    assert error["code"] == "INTERNAL_ERROR"
    assert "boom" not in response.content.decode()


def test_caller_request_id_is_echoed(client):
    response = client.get("/does-not-exist", headers={"X-Request-ID": "trace-12345678"})
    assert response["X-Request-ID"] == "trace-12345678"
    assert _error(response)["request_id"] == "trace-12345678"
